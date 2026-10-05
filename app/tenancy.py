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
RESERVED = {'www', 'app', 'api', 'admin', 'demo', 'trials', 'trial', 'mail', 'smtp', 'support', 'static'}

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

_CACHE_TTL = 60
_cache = {}   # slug → (schema or None, fetched_at)


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


def lookup_schema(slug):
    """Schema for an active trial, cached briefly. Uses its own connection, not the ORM session."""
    hit = _cache.get(slug)
    if hit and time.time() - hit[1] < _CACHE_TTL:
        return hit[0]
    try:
        with db.engine.connect() as conn:
            row = conn.execute(text("SELECT schema_name FROM public.tenants WHERE slug = :s AND status = 'active'"),
                               {'s': slug}).first()
        schema = row[0] if row and SCHEMA_RE.match(row[0]) else None
    except Exception:
        schema = None
    _cache[slug] = (schema, time.time())
    return schema


def clear_cache():
    _cache.clear()


def resolve_tenant():
    """before_request hook (registered first): pick the trial from the Host, or 404."""
    if not tenant_mode():
        return None
    slug = slug_from_host(request.host)
    schema = lookup_schema(slug) if slug else None
    if not schema:
        return Response(NOT_FOUND_HTML, status=404, mimetype='text/html')
    g.tenant_slug, g.tenant_schema = slug, schema
    return None


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
