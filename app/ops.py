"""
Trial operations shared by the CLI (`flask trial …`) and the operator console.

All functions need an app context whose DATABASE_URL is the shared trials database
(Postgres), and DATA_ENCRYPTION_KEY set to the trials project's key.
"""
import secrets
from datetime import timedelta

from sqlalchemy import text

from . import db, tenancy
from . import plan as plan_mod


class OpsError(Exception):
    pass


def need_postgres():
    if db.engine.dialect.name != 'postgresql':
        raise OpsError('Trials need a PostgreSQL DATABASE_URL.')


def migrate_schema(schema):
    from flask_migrate import upgrade
    upgrade(x_arg=[f'tenant_schema={schema}'])


def generate_password():
    """Readable one-time admin password, e.g. 'tide-4821-amber'."""
    words = ['amber', 'birch', 'cedar', 'delta', 'ember', 'fern', 'grove', 'harbor', 'ivory', 'jade', 'kite',
             'lotus', 'maple', 'nova', 'olive', 'pearl', 'quartz', 'river', 'sage', 'tide', 'umber', 'velvet',
             'willow', 'zephyr']
    return f'{secrets.choice(words)}-{secrets.randbelow(9000) + 1000}-{secrets.choice(words)}'


def schema_of(slug, active_only=True):
    tenancy.ensure_registry()
    sql = 'SELECT schema_name FROM public.tenants WHERE slug = :s' + (" AND status = 'active'" if active_only else '')
    with db.engine.connect() as conn:
        row = conn.execute(text(sql), {'s': slug}).first()
    if not row:
        raise OpsError(f'No {"active " if active_only else ""}trial named "{slug}".')
    return row[0]


def create_trial(slug, admin_username='admin', admin_password=None, days=7, log=None):
    """Create schema, tables, admin login, default data and the trial plan. Returns a summary dict."""
    from .seed import SeedError, bootstrap
    log = log or (lambda line: None)
    need_postgres()
    try:
        slug = tenancy.validate_slug(slug)
    except tenancy.TenantError as exc:
        raise OpsError(str(exc))
    admin_username = (admin_username or 'admin').strip()
    if not admin_username or len(admin_username) > 80:
        raise OpsError('Choose an admin username (up to 80 characters).')
    admin_password = admin_password or generate_password()
    if len(admin_password) < 8:
        raise OpsError('The admin password must be at least 8 characters.')
    if not 1 <= int(days) <= 90:
        raise OpsError('Trial length must be between 1 and 90 days.')
    schema = tenancy.schema_for(slug)
    tenancy.ensure_registry()
    with db.engine.begin() as conn:
        if conn.execute(text('SELECT 1 FROM public.tenants WHERE slug = :s'), {'s': slug}).first():
            raise OpsError(f'A trial named "{slug}" already exists.')
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text("INSERT INTO public.tenants (slug, schema_name, status) VALUES (:s, :sc, 'creating')"),
                     {'s': slug, 'sc': schema})
    log(f'Creating tables in schema {schema}…')
    migrate_schema(schema)
    with tenancy.tenant_context(slug, schema):
        try:
            for line in bootstrap(username=admin_username, password=admin_password):
                log(line)
        except SeedError as exc:
            raise OpsError(str(exc))
        start = plan_mod.today()
        end = start + timedelta(days=int(days))
        plan_mod.save_plan('trial', start, end)
        db.session.commit()
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE public.tenants SET status = 'active' WHERE slug = :s"), {'s': slug})
    tenancy.clear_cache()
    return {'slug': slug, 'schema': schema, 'username': admin_username, 'password': admin_password,
            'ends_on': end, 'url': trial_url(slug)}


def trial_url(slug):
    base = tenancy.base_domain()
    return f'https://{slug}.{base}' if base else f'https://{slug}.<TENANT_BASE_DOMAIN>'


def list_trials():
    """Every registered trial with its plan status (active ones only have a plan)."""
    need_postgres()
    tenancy.ensure_registry()
    out = []
    for r in tenancy.registry_rows():
        item = dict(r, url=trial_url(r['slug']), status_obj=None)
        if r['status'] == 'active':
            try:
                with tenancy.tenant_context(r['slug'], r['schema_name']):
                    item['status_obj'] = plan_mod.load_status(on=plan_mod.today())
            except Exception as exc:          # a half-created trial shouldn't break the whole list
                item['error'] = str(exc)
        out.append(item)
    return out


def extend_trial(slug, length):
    """Add time (e.g. '7d'): from the end date if still running, else from today. Returns the new status."""
    need_postgres()
    try:
        plan_mod.parse_length(length)
    except ValueError as exc:
        raise OpsError(str(exc))
    schema = schema_of(slug)
    with tenancy.tenant_context(slug, schema):
        st = plan_mod.load_status(on=plan_mod.today())
        base = max(st.ends_on, plan_mod.today()) if st.has_limit else plan_mod.today()
        plan_mod.save_plan('trial', st.started_on or plan_mod.today(), plan_mod.add_length(base, length))
        db.session.commit()
        return plan_mod.load_status(on=plan_mod.today())


def delete_trial(slug):
    """Permanently drop a trial's schema and registry row."""
    need_postgres()
    schema = schema_of(slug, active_only=False)
    with db.engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text('DELETE FROM public.tenants WHERE slug = :s'), {'s': slug})
    tenancy.clear_cache()


def reset_admin_password(slug, username=None, new_password=None):
    """Set a new password for a trial's admin (the first admin if no username). Returns (username, password)."""
    from werkzeug.security import generate_password_hash
    from .models import User
    new_password = new_password or generate_password()
    schema = schema_of(slug)
    with tenancy.tenant_context(slug, schema):
        q = User.query.filter_by(role='admin')
        user = (q.filter_by(username=username) if username else q.order_by(User.id)).first()
        if not user:
            raise OpsError(f'No admin user{" " + repr(username) if username else ""} in trial "{slug}".')
        user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
        db.session.commit()
        return user.username, new_password


def admin_usernames(slug):
    from .models import User
    with tenancy.tenant_context(slug, schema_of(slug)):
        return [u.username for u in User.query.filter_by(role='admin').order_by(User.id)]


def unlock_company(slug, fields):
    """Unlock company identity fields (name / gstin / logo) so the trial's admin can change them once."""
    from . import branding
    with tenancy.tenant_context(slug, schema_of(slug)):
        branding.unlock(fields)
        db.session.commit()
