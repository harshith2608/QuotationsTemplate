"""
Shared trials app: many trial customers in ONE deployment and ONE Postgres
database, each in its own schema (e.g. trial "acme" → schema "t_acme").

    TENANT_MODE=1                       turn it on (trials project only)
    TENANT_BASE_DOMAIN=quote-room.co.in trials are served at <slug>.quote-room.co.in

How isolation works
  * Every request is mapped from its Host to a trial using the registry table
    public.tenants. Unknown hosts get a plain 404 before any data is touched.
  * When the ORM session starts a transaction, the connection gets
    schema_translate_map {None: "<tenant schema>"}, so every query and every
    flush (INSERT/UPDATE/DELETE) goes to that schema. This is compiled into
    the SQL, so it is safe with Neon's PgBouncer (transaction pooling).
  * In tenant mode a request that reaches the database without a tenant
    raises instead of silently using the public schema (fail closed).
  * Login identities are "<slug>:<user id>", so a session or remember-me
    cookie from one trial is rejected by every other trial.

Paying customers in the same app ("shared" hosting, app/customers.py): once a trial is converted, its data
lives in the customer's OWN database (in the same Neon project) with its own encryption key. Their requests
use that database (g.tenant_engine, picked up by the session in app/__init__.py) and key; their secrets
come sealed from public.customers (CONSOLE_VAULT_KEY). While a trial is being moved ("moving"), its address
shows a short "being upgraded" page instead of risking writes that wouldn't be copied.
Postgres only.
"""
import os
import re
import time
from contextlib import contextmanager

from flask import Response, g, has_app_context, has_request_context, request
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from . import db

SLUG_RE = re.compile(r'^[a-z][a-z0-9-]{1,29}$')
SCHEMA_RE = re.compile(r'^t_[a-z][a-z0-9_]{1,29}$')
RESERVED = {'www', 'app', 'api', 'admin', 'demo', 'trials', 'trial', 'mail', 'smtp', 'support', 'static',
            'ops', 'console', 'status', 'help', 'blog', 'docs'}

REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS public.tenants (
    slug          VARCHAR(40)  PRIMARY KEY,
    schema_name   VARCHAR(64)  NOT NULL UNIQUE,
    status        VARCHAR(20)  NOT NULL DEFAULT 'active',
    created_at    TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    converted_at  TIMESTAMP
)
"""

NOT_FOUND_HTML = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                  '<title>Not found</title><body style="font-family:system-ui;padding:3rem;text-align:center">'
                  '<h1>Not found</h1><p>This app doesn\'t exist or is no longer available.</p></body>')

_CACHE_TTL = 15          # seconds an instance trusts what it looked up (a moved trial's schema is renamed meanwhile)
STUCK_MOVE = 300         # a move that hasn't finished in 5 minutes is called off: the trial is given back
_cache = {}   # slug → (target or None, fetched_at); target: ('schema', name) | ('db', {url, key}) | ('moving', None)
_engines = {}  # slug → (url, engine): a paying customer's own database

MOVING_HTML = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
               '<meta http-equiv="refresh" content="10"><title>Upgrading</title>'
               '<body style="font-family:system-ui;padding:3rem;text-align:center"><h1>Moving you to your paid plan</h1>'
               '<p>Your app is being upgraded. This takes less than a minute; this page reloads by itself.</p></body>')


class TenantError(Exception):
    pass


def tenant_mode():
    return (os.environ.get('TENANT_MODE') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def base_domain():
    return (os.environ.get('TENANT_BASE_DOMAIN') or '').strip().lower().lstrip('.')


def validate_slug(slug):
    slug = (slug or '').strip().lower()
    if not SLUG_RE.match(slug) or slug.endswith('-') or '--' in slug:
        raise TenantError('Use 2–30 characters: lowercase letters, numbers and single hyphens, starting with a letter.')
    if slug in RESERVED:
        raise TenantError(f'"{slug}" is reserved. Choose another name.')
    return slug


def schema_for(slug):
    schema = 't_' + slug.replace('-', '_')
    assert SCHEMA_RE.match(schema)
    return schema


def current_slug():
    if has_app_context():
        return g.get('tenant_slug')
    return None


def current_schema():
    if has_app_context():
        return g.get('tenant_schema')
    return None


def slug_from_host(host):
    host = (host or '').split(':')[0].strip().lower().rstrip('.')
    base = base_domain()
    if not base or not host.endswith('.' + base):
        return None
    label = host[: -len(base) - 1]
    return label if label and '.' not in label else None


def ensure_registry():
    with db.engine.begin() as conn:
        conn.execute(text(REGISTRY_DDL))
        conn.execute(text('ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS moving_since TIMESTAMP'))


def lookup(slug):
    """Where this address's data lives, cached briefly: ('schema', name) for an active trial, ('db', {url, key})
    for a paying customer in their own database, ('moving', None) while being moved, or None. Own connections."""
    hit = _cache.get(slug)
    if hit and time.time() - hit[1] < _CACHE_TTL:
        return hit[0]
    target = None
    try:
        with db.engine.connect() as conn:
            row = conn.execute(text("SELECT schema_name, status FROM public.tenants WHERE slug = :s"), {'s': slug}).first()
        if row and row[1] == 'active' and SCHEMA_RE.match(row[0]):
            target = ('schema', row[0])
        elif row and row[1] == 'moving':
            target = ('moving', None)
            if _move_stuck(slug):                 # interrupted (e.g. a time limit): give the trial back
                from .ops import set_moving
                set_moving(slug, False)
                target = ('schema', schema_for(slug))
    except Exception:
        target = None
    if target is None:
        target = _shared_customer(slug)
    _cache[slug] = (target, time.time())
    return target


def _move_stuck(slug):
    try:
        with db.engine.connect() as conn:
            age = conn.execute(text("SELECT EXTRACT(EPOCH FROM ((now() AT TIME ZONE 'utc') - moving_since)) "
                                    "FROM public.tenants WHERE slug = :s"), {'s': slug}).scalar()
        return age is not None and age > STUCK_MOVE
    except Exception:
        return False


def _shared_customer(slug):
    """('db', {url, key}) for an active paying customer hosted in this app, else None."""
    try:
        with db.engine.connect() as conn:
            if conn.execute(text("SELECT to_regclass('public.customers')")).scalar() is None:
                return None
            row = conn.execute(text("SELECT secrets FROM public.customers WHERE slug = :s AND status = 'active' "
                                    "AND hosting = 'shared'"), {'s': slug}).first()
        if not row:
            return None
        from .customers import unseal
        s = unseal(row[0])
        if s.get('app_url') and s.get('data_key'):
            return ('db', {'url': s['app_url'], 'key': s['data_key']})
    except Exception:
        current_logger_warning(f'Could not open the paying customer "{slug}".')
    return None


def current_logger_warning(message):
    try:
        from flask import current_app
        current_app.logger.warning(message)
    except Exception:
        pass


def lookup_schema(slug):
    """Schema for an active trial (None for anything else)."""
    target = lookup(slug)
    return target[1] if target and target[0] == 'schema' else None


def customer_engine(slug, url):
    """The engine for a paying customer's own database, made once per process (small pool: serverless)."""
    hit = _engines.get(slug)
    if hit and hit[0] == url:
        return hit[1]
    from sqlalchemy import create_engine
    from .ops import normalize_url
    engine = create_engine(normalize_url(url), pool_pre_ping=True, pool_size=2, max_overflow=3, pool_recycle=300)
    if hit:
        hit[1].dispose()
    _engines[slug] = (url, engine)
    return engine


def clear_cache():
    _cache.clear()


def resolve_tenant():
    """before_request hook (registered first): pick the trial or paying customer from the Host, or 404."""
    if not tenant_mode():
        return None
    slug = slug_from_host(request.host)
    target = lookup(slug) if slug else None
    if not target:
        return Response(NOT_FOUND_HTML, status=404, mimetype='text/html')
    if target[0] == 'moving':
        return Response(MOVING_HTML, status=503, mimetype='text/html', headers={'Retry-After': '10'})
    g.tenant_slug = slug
    if target[0] == 'schema':
        g.tenant_schema = target[1]
    else:                                         # a paying customer: their own database and encryption key
        from . import crypto
        g.tenant_engine = customer_engine(slug, target[1]['url'])
        g.tenant_key_token = crypto.push_key(target[1]['key'])
    return None


def release_tenant(exc=None):
    """teardown hook: stop using the paying customer's key after the request."""
    token = g.pop('tenant_key_token', None) if has_app_context() else None
    if token is not None:
        from . import crypto
        crypto.pop_key(token)


@contextmanager
def tenant_context(slug, schema=None):
    """Run ORM code against one trial's schema (CLI use). Must be inside an app context."""
    db.session.remove()                      # drop any connection opened without the schema map
    g.tenant_slug, g.tenant_schema = slug, schema or schema_for(slug)
    try:
        yield
    finally:
        db.session.remove()
        g.pop('tenant_slug', None)
        g.pop('tenant_schema', None)


@event.listens_for(Session, 'after_begin')
def _apply_tenant_schema(session, transaction, connection):
    if has_app_context() and g.get('tenant_engine') is not None:
        return                                   # a paying customer's own database: its default schema
    schema = current_schema()
    if schema:
        # SQLAlchemy 2.x: Connection.execution_options() updates this connection in place
        connection.execution_options(schema_translate_map={None: schema})
    elif tenant_mode() and has_request_context():
        raise TenantError('Database access without a tenant in tenant mode.')


def registry_rows():
    with db.engine.connect() as conn:
        return conn.execute(text('SELECT slug, schema_name, status, created_at, converted_at '
                                 'FROM public.tenants ORDER BY created_at')).mappings().all()
