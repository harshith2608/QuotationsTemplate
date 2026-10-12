"""
External services used by the operator console to provision paying customers.

CustomerDatabases: one Postgres DATABASE + its own LOGIN per customer, inside ONE shared Neon project
  (CUSTOMERS_ADMIN_DATABASE_URL = that project's owner connection, direct, not -pooler). Each customer's
  login owns only its database, and CONNECT is revoked from everyone else, so a leaked customer URL
  opens that customer's data and nothing more. No Neon API key is needed: it's plain SQL.

Vercel: creates the customer's project (linked to the GitHub repo, env vars, Singapore region),
  adds their subdomain and starts deployments. VERCEL_TOKEN, optional VERCEL_TEAM_ID.
"""
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request

import psycopg2

NAME_RE = re.compile(r'^[a-z][a-z0-9_]{1,40}$')


class ProviderError(Exception):
    pass


def _env(name, default=''):
    return (os.environ.get(name) or default).strip()


# ── Customer databases (shared Neon project) ─────────────────────────────────

def names_for(slug):
    base = slug.replace('-', '_')
    db_name, role = f'c_{base}', f'r_{base}'
    if not (NAME_RE.match(db_name) and NAME_RE.match(role)):
        raise ProviderError(f'Unusable customer name "{slug}".')
    return db_name, role


class CustomerDatabases:
    def __init__(self, admin_url=None, use_pooler=None):
        self.admin_url = admin_url or _env('CUSTOMERS_ADMIN_DATABASE_URL')
        if not self.admin_url:
            raise ProviderError('CUSTOMERS_ADMIN_DATABASE_URL is not set.')
        self.parts = urllib.parse.urlsplit(self.admin_url.replace('postgresql+psycopg2://', 'postgresql://'))
        # Neon's pooled hostname is the endpoint id + "-pooler"; off for plain Postgres (e.g. tests)
        self.use_pooler = ('neon.tech' in (self.parts.hostname or '')) if use_pooler is None else use_pooler

    def _admin(self):
        conn = psycopg2.connect(self.admin_url.replace('postgresql+psycopg2://', 'postgresql://'))
        conn.autocommit = True                      # CREATE / DROP DATABASE can't run in a transaction
        return conn

    def _url(self, role, password, db_name, pooled):
        host = self.parts.hostname or ''
        host = host.replace('-pooler.', '.', 1)
        if pooled and self.use_pooler:
            first, _, rest = host.partition('.')
            host = f'{first}-pooler.{rest}'
        port = f':{self.parts.port}' if self.parts.port else ''
        query = self.parts.query or ('sslmode=require' if self.use_pooler else '')
        return (f'postgresql://{urllib.parse.quote(role)}:{urllib.parse.quote(password)}@{host}{port}/{db_name}'
                + (f'?{query}' if query else ''))

    def exists(self, slug):
        db_name, role = names_for(slug)
        conn = self._admin()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (db_name,))
                has_db = cur.fetchone() is not None
                cur.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (role,))
                has_role = cur.fetchone() is not None
        finally:
            conn.close()
        return has_db, has_role

    def create(self, slug):
        """Create the customer's login and database (fails if either exists). Returns connection details."""
        db_name, role = names_for(slug)
        password = secrets.token_urlsafe(30)
        conn = self._admin()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT current_user')
                admin = cur.fetchone()[0]
                cur.execute(f'CREATE ROLE "{role}" LOGIN PASSWORD %s', (password,))
                # The admin needs SET on the role to make it the database owner (PostgreSQL 16+)
                cur.execute(f'GRANT "{role}" TO "{admin}" WITH INHERIT FALSE, SET TRUE')
                # Always UTF-8 (₹, names in any script), whatever the server's default template is
                cur.execute(f'CREATE DATABASE "{db_name}" OWNER "{role}" ENCODING \'UTF8\' TEMPLATE template0')
                # Only the owner may revoke PUBLIC's CONNECT, so do it as the customer's login
                cur.execute(f'SET ROLE "{role}"')
                cur.execute(f'REVOKE CONNECT ON DATABASE "{db_name}" FROM PUBLIC')
                cur.execute('RESET ROLE')
                # Customer logins must not open the admin database either
                cur.execute('SELECT current_database()')
                admin_db = cur.fetchone()[0]
                cur.execute(f'REVOKE CONNECT ON DATABASE "{admin_db}" FROM PUBLIC')
        finally:
            conn.close()
        return {'db_name': db_name, 'role': role,
                'direct_url': self._url(role, password, db_name, pooled=False),
                'pooled_url': self._url(role, password, db_name, pooled=True)}

    def drop(self, slug):
        """Permanently delete the customer's database and login."""
        db_name, role = names_for(slug)
        has_db, has_role = self.exists(slug)
        conn = self._admin()
        try:
            with conn.cursor() as cur:
                if has_db:
                    cur.execute(f'SET ROLE "{role}"' if has_role else 'RESET ROLE')
                    cur.execute(f'DROP DATABASE "{db_name}" WITH (FORCE)')
                    cur.execute('RESET ROLE')
                if has_role:
                    cur.execute(f'DROP ROLE "{role}"')
        finally:
            conn.close()

    @staticmethod
    def can_connect(url):
        try:
            conn = psycopg2.connect(url.replace('postgresql+psycopg2://', 'postgresql://'), connect_timeout=10)
            conn.close()
            return True, ''
        except psycopg2.Error as exc:
            return False, str(exc).strip().splitlines()[0]


# ── Vercel ───────────────────────────────────────────────────────────────────

class Vercel:
    API = 'https://api.vercel.com'

    def __init__(self, token=None, team_id=None, repo=None):
        self.token = token or _env('VERCEL_TOKEN')
        self.team_id = team_id if team_id is not None else _env('VERCEL_TEAM_ID')
        self.repo = repo or _env('VERCEL_GIT_REPO', 'harshith2608/QuotationsTemplate')
        if not self.token:
            raise ProviderError('VERCEL_TOKEN is not set.')

    def _call(self, method, path, body=None):
        url = self.API + path
        if self.team_id:
            url += ('&' if '?' in url else '?') + 'teamId=' + urllib.parse.quote(self.team_id)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read()).get('error', {})
                msg = err.get('message') or err.get('code') or str(exc)
            except Exception:
                msg = str(exc)
            raise ProviderError(f'Vercel {method} {path.split("?")[0]}: {msg} (HTTP {exc.code})') from None
        except urllib.error.URLError as exc:
            raise ProviderError(f'Vercel unreachable: {exc.reason}') from None

    def create_project(self, name, env, region='sin1'):
        """New project linked to the repo, with production env vars. Returns {'id', 'name', 'repo_id'}."""
        body = {
            'name': name,
            'framework': None,
            'gitRepository': {'type': 'github', 'repo': self.repo},
            'serverlessFunctionRegion': region,
            'environmentVariables': [{'key': k, 'value': v, 'target': ['production'], 'type': 'encrypted'}
                                     for k, v in env.items()],
        }
        p = self._call('POST', '/v11/projects', body)
        return {'id': p['id'], 'name': p['name'], 'repo_id': (p.get('link') or {}).get('repoId')}

    def get_project(self, id_or_name):
        try:
            p = self._call('GET', f'/v9/projects/{urllib.parse.quote(id_or_name)}')
        except ProviderError as exc:
            if '404' in str(exc):
                return None
            raise
        return {'id': p['id'], 'name': p['name'], 'repo_id': (p.get('link') or {}).get('repoId')}

    def add_domain(self, project, domain):
        try:
            self._call('POST', f'/v10/projects/{urllib.parse.quote(project)}/domains', {'name': domain})
        except ProviderError as exc:
            if 'already' not in str(exc).lower():      # already on this project: fine
                raise

    def deploy(self, project_id, project_name, repo_id, ref='main'):
        """Start a production deployment of the repo's branch. Returns the deployment id."""
        d = self._call('POST', '/v13/deployments', {
            'name': project_name, 'project': project_id, 'target': 'production',
            'gitSource': {'type': 'github', 'repoId': repo_id, 'ref': ref}})
        return d.get('id')

    def latest_deployment(self, project_id):
        """(state, url) of the newest deployment: QUEUED / BUILDING / READY / ERROR / CANCELED, or (None, None)."""
        d = self._call('GET', f'/v6/deployments?projectId={urllib.parse.quote(project_id)}&limit=1')
        items = d.get('deployments') or []
        if not items:
            return None, None
        return items[0].get('state') or items[0].get('readyState'), items[0].get('url')

    def get_env(self, project_id):
        """{key: value or None} of the project's production env vars (values decrypted where Vercel allows)."""
        d = self._call('GET', f'/v9/projects/{urllib.parse.quote(project_id)}/env?decrypt=true')
        out = {}
        for e in d.get('envs') or []:
            if 'production' in (e.get('target') or []):
                out[e['key']] = e.get('value') if e.get('decrypted', True) else None
        return out

    def delete_project(self, id_or_name):
        try:
            self._call('DELETE', f'/v9/projects/{urllib.parse.quote(id_or_name)}')
        except ProviderError as exc:
            if '404' not in str(exc):
                raise


def vercel():
    """The Vercel client (tests replace this function)."""
    return Vercel()


def customer_databases():
    """The customer-database provider (tests may replace this function)."""
    return CustomerDatabases()
