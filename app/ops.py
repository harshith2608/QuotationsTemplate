"""
Trial operations shared by the CLI (`flask trial …`) and the operator console.

All functions need an app context whose DATABASE_URL is the shared trials database
(Postgres), and DATA_ENCRYPTION_KEY set to the trials project's key.
"""
import os
import secrets
from datetime import timedelta

from sqlalchemy import text

from . import activity, db, tenancy
from . import plan as plan_mod


class OpsError(Exception):
    pass


def need_postgres():
    if db.engine.dialect.name != 'postgresql':
        raise OpsError('Trials need a PostgreSQL DATABASE_URL.')


MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')


def migrate_schema(schema):
    from flask_migrate import upgrade
    upgrade(directory=MIGRATIONS_DIR, x_arg=[f'tenant_schema={schema}'])


def migrate_all_trials(log=None):
    """Apply database updates (and encrypt leftovers) in every active trial schema. Returns failed slugs."""
    from .seed import encrypt_existing_data
    log = log or (lambda line: None)
    need_postgres()
    tenancy.ensure_registry()
    failed = []
    for r in tenancy.registry_rows():
        if r['status'] != 'active':
            continue
        log(f'→ {r["slug"]} ({r["schema_name"]})')
        try:
            migrate_schema(r['schema_name'])
            with tenancy.tenant_context(r['slug'], r['schema_name']):
                log('  ' + encrypt_existing_data())
        except Exception as exc:              # keep going; report at the end
            failed.append(r['slug'])
            log(f'  FAILED: {exc}')
    return failed


def normalize_url(url):
    url = url.strip()
    for prefix in ('postgres://', 'postgresql://'):
        if url.startswith(prefix):
            return 'postgresql+psycopg2://' + url[len(prefix):]
    return url


def engine_for(url):
    from sqlalchemy import create_engine
    return create_engine(normalize_url(url), pool_pre_ping=True)


# Tables only the marketing (demo) database uses: never copied into a customer's database
MARKETING_TABLES = {'leads', 'demo_stats', 'tutorials'}


def copy_trial(slug, target_url, to_key, plan_name):
    """Copy a trial into a customer's own, migrated, EMPTY database, re-encrypting with the customer's key,
    and start their paid plan there. Returns ({table: rows}, start, end). Doesn't change the trial."""
    from sqlalchemy import inspect
    from . import crypto
    from .models import AppSetting
    need_postgres()
    try:
        crypto.validate_key(to_key)
    except crypto.EncryptionError as exc:
        raise OpsError(f'Customer key: {exc}')
    if not crypto.enabled():
        raise OpsError(f'Set {crypto.ENV} to the trials project\'s key so the trial data can be read.')
    schema = schema_of(slug, active_only=False)
    target = engine_for(target_url)
    tables = db.metadata.sorted_tables
    copy_tables = [t for t in tables if t.name not in MARKETING_TABLES]
    with target.connect() as tc:
        names = set(inspect(tc).get_table_names())
        if [t.name for t in tables if t.name not in names] or 'alembic_version' not in names:
            raise OpsError('The new database isn\'t set up yet (run its database update first).')
        if tc.execute(text('SELECT COUNT(*) FROM users')).scalar():
            raise OpsError('The new database already has users. Use an empty database.')
    copied = {}
    with tenancy.tenant_context(slug, schema):
        src = db.session.connection()                 # schema-mapped to the trial
        with target.begin() as tc:
            for table in copy_tables:
                # Read decrypts with the trials key; insert re-encrypts with the customer's own key
                rows = [dict(r) for r in src.execute(table.select()).mappings()]
                if table.name == 'app_settings':
                    for r in rows:
                        if r['key'] in AppSetting.ENCRYPTED_KEYS and r['value']:
                            plain = crypto.decrypt(r['value'])
                            with crypto.using_key(to_key):
                                r['value'] = crypto.encrypt(plain)
                if rows:
                    with crypto.using_key(to_key):
                        tc.execute(table.insert(), rows)
                copied[table.name] = len(rows)
            for table in tables:                      # continue id sequences after the copied rows
                if 'id' in table.c and table.c.id.primary_key:
                    tc.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1), "
                        f"(SELECT MAX(id) FROM \"{table.name}\") IS NOT NULL)"))
            start = plan_mod.today()
            end = plan_mod.add_length(start, plan_name)
            for key, value in ((plan_mod.PLAN_KEY, plan_name), (plan_mod.STARTED_KEY, start.isoformat()),
                               (plan_mod.ENDS_KEY, end.isoformat())):
                tc.execute(text('DELETE FROM app_settings WHERE key = :k'), {'k': key})
                tc.execute(text('INSERT INTO app_settings (key, value) VALUES (:k, :v)'), {'k': key, 'v': value})
        db.session.rollback()
    target.dispose()
    return copied, start, end


def mark_converted(slug):
    """The trials app stops serving this trial (its data stays until deleted)."""
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE public.tenants SET status = 'converted', converted_at = (now() AT TIME ZONE 'utc') "
                          "WHERE slug = :s"), {'s': slug})
    tenancy.clear_cache()


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
                    item['usage'] = activity.usage()
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
