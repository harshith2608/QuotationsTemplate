"""
Trial operations shared by the CLI (`flask trial …`) and the operator console.

All functions need an app context whose DATABASE_URL is the shared trials database
(Postgres), and DATA_ENCRYPTION_KEY set to the trials project's key.
"""
import re
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
        if r['status'] not in ('active', 'spare'):
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
    and start their paid plan there (plan_name None: keep the plan the trial already has, e.g. bought in the app).
    Returns ({table: rows}, start, end). Doesn't change the trial."""
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
            if plan_name:                             # start the paid plan today
                start = plan_mod.today()
                end = plan_mod.add_length(start, plan_name)
                for key, value in ((plan_mod.PLAN_KEY, plan_name), (plan_mod.STARTED_KEY, start.isoformat()),
                                   (plan_mod.ENDS_KEY, end.isoformat())):
                    tc.execute(text('DELETE FROM app_settings WHERE key = :k'), {'k': key})
                    tc.execute(text('INSERT INTO app_settings (key, value) VALUES (:k, :v)'), {'k': key, 'v': value})
            else:                                     # already paid in the trial (bought in the app): keep that plan
                got = dict(tc.execute(text('SELECT key, value FROM app_settings WHERE key IN (:a, :b)'),
                                      {'a': plan_mod.STARTED_KEY, 'b': plan_mod.ENDS_KEY}).all())
                start = plan_mod._parse_date(got.get(plan_mod.STARTED_KEY)) or plan_mod.today()
                end = plan_mod._parse_date(got.get(plan_mod.ENDS_KEY))
        db.session.rollback()
    target.dispose()
    return copied, start, end


MOVING_PREFIX = 'm_'


def set_moving(slug, on):
    """While a trial is copied into a paying customer's database, its address shows "being upgraded" and its schema
    is renamed (t_acme → m_acme), so an app instance that hasn't noticed yet can't write to it: such a write fails
    instead of being lost, and nobody has to wait for caches to expire. Off: back to the trial as it was."""
    tenancy.ensure_registry()
    with db.engine.begin() as conn:
        row = conn.execute(text('SELECT schema_name, status FROM public.tenants WHERE slug = :s FOR UPDATE'),
                           {'s': slug}).first()
        if not row:
            raise OpsError(f'No trial named "{slug}".')
        schema, status = row
        if on and status == 'active':
            moved = MOVING_PREFIX + schema[2:]
            conn.execute(text(f'ALTER SCHEMA "{schema}" RENAME TO "{moved}"'))
            conn.execute(text("UPDATE public.tenants SET status = 'moving', schema_name = :m, "
                              "moving_since = (now() AT TIME ZONE 'utc') WHERE slug = :s"), {'s': slug, 'm': moved})
        elif not on and status == 'moving':
            back = tenancy.schema_for(slug)
            conn.execute(text(f'ALTER SCHEMA "{schema}" RENAME TO "{back}"'))
            conn.execute(text("UPDATE public.tenants SET status = 'active', schema_name = :b, moving_since = NULL "
                              "WHERE slug = :s"), {'s': slug, 'b': back})
    tenancy.clear_cache()


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


PREFILLED_NAME_KEY = 'company_name_prefilled'


def phone_display(digits):
    """'919876543210' → '+91 98765 43210' (as typed elsewhere in the app); other numbers get a leading +."""
    digits = re.sub(r'\D', '', digits or '')
    if len(digits) == 12 and digits.startswith('91'):
        return f'+91 {digits[2:7]} {digits[7:]}'
    return f'+{digits}' if digits else ''


SPARE_PREFIX = 'spare-'


def create_trial(slug, admin_username='admin', admin_password=None, days=7, log=None, company=None, phone=None,
                 city=None, email=None, spare=False):
    """Create schema, tables, admin login, default data and the trial plan. Returns a summary dict.
    `company` / `phone` / `city` / `email` (from the trial request) are filled in as the business's company name,
    phone, address and email, so the
    customer starts with their own name on quotations. The name stays open for one correction by the customer
    (it locks after they save it, like any company name)."""
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
        if spare:                                  # ready-made: the details and the plan come when it's claimed
            db.session.commit()
    if spare:
        with db.engine.begin() as conn:
            conn.execute(text("UPDATE public.tenants SET status = 'spare' WHERE slug = :s"), {'s': slug})
        return {'slug': slug, 'schema': schema}
    end = _finish_trial(slug, schema, company, phone, city, email, days, log)
    return {'slug': slug, 'schema': schema, 'username': admin_username, 'password': admin_password,
            'ends_on': end, 'url': trial_url(slug), 'company': ' '.join((company or '').split())[:80]}


def _finish_trial(slug, schema, company, phone, city, email, days, log=lambda line: None):
    """The trial's details from the request (company, phone, city, email), its plan from today, then live."""
    with tenancy.tenant_context(slug, schema):
        company = ' '.join((company or '').split())[:80]
        if company:
            from . import branding
            from .models import AppSetting
            AppSetting.set(branding.FIELDS['name'][0], company)
            AppSetting.set(PREFILLED_NAME_KEY, company)       # so the console doesn't count it as the customer's own
            branding.unlock(['name'])
            log(f'Company name: {company}')
        from .models import AppSetting
        for key, value in (('company_mobile', phone_display(phone)), ('company_address', ' '.join((city or '').split())[:60]),
                           ('company_email', (email or '').strip()[:120] if '@' in (email or '') else '')):
            if value:
                AppSetting.set(key, value)
        start = plan_mod.today()
        end = start + timedelta(days=int(days))
        plan_mod.save_plan('trial', start, end)
        db.session.commit()
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE public.tenants SET status = 'active' WHERE slug = :s"), {'s': slug})
    tenancy.clear_cache()
    return end


# ── Ready-made (spare) trials: a new trial in under a second ─────────────────

def spare_count():
    tenancy.ensure_registry()
    with db.engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM public.tenants WHERE status = 'spare'")).scalar()


def top_up_spares(target=None, log=None):
    """Keep `target` (SPARE_TRIALS, default 3) ready-made trials: empty, migrated, with an admin login to be renamed.
    Returns how many were made."""
    target = int(os.environ.get('SPARE_TRIALS', '3') if target is None else target)
    made = 0
    while spare_count() < target:
        create_trial(SPARE_PREFIX + secrets.token_hex(3), 'admin', None, 7, log=log, spare=True)
        made += 1
    return made


def claim_trial(slug, admin_username, admin_password, days=7, company=None, phone=None, city=None, email=None):
    """A new trial at once: a ready-made one renamed to `slug` with this admin login and these details (or, with none
    ready, a new one made now). Returns create_trial's summary."""
    from werkzeug.security import generate_password_hash
    from .models import User
    need_postgres()
    try:
        slug = tenancy.validate_slug(slug)
    except tenancy.TenantError as exc:
        raise OpsError(str(exc))
    admin_username = (admin_username or 'admin').strip()[:80] or 'admin'
    if len(admin_password or '') < 8:
        raise OpsError('The password must be at least 8 characters.')
    schema = tenancy.schema_for(slug)
    tenancy.ensure_registry()
    with db.engine.begin() as conn:
        if conn.execute(text('SELECT 1 FROM public.tenants WHERE slug = :s'), {'s': slug}).first():
            raise OpsError(f'"{slug}" is taken. Choose another address.')
        spare = conn.execute(text("SELECT slug, schema_name FROM public.tenants WHERE status = 'spare' "
                                  "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED")).first()
        if spare:
            conn.execute(text(f'ALTER SCHEMA "{spare[1]}" RENAME TO "{schema}"'))
            conn.execute(text("UPDATE public.tenants SET slug = :n, schema_name = :sc, status = 'creating', "
                              "created_at = (now() AT TIME ZONE 'utc') WHERE slug = :o"),
                         {'n': slug, 'sc': schema, 'o': spare[0]})
    if not spare:
        return create_trial(slug, admin_username, admin_password, days, company=company, phone=phone, city=city,
                            email=email)
    if _schema_revision(schema) != _head_revision():
        migrate_schema(schema)                     # made before the latest update
    with tenancy.tenant_context(slug, schema):
        admin = User.query.filter_by(role='admin').order_by(User.id).first()
        admin.username = admin_username
        admin.password_hash = generate_password_hash(admin_password, method='pbkdf2:sha256')
        db.session.commit()
    end = _finish_trial(slug, schema, company, phone, city, email, days)
    return {'slug': slug, 'schema': schema, 'username': admin_username, 'password': admin_password,
            'ends_on': end, 'url': trial_url(slug), 'company': ' '.join((company or '').split())[:80]}


def _schema_revision(schema):
    with db.engine.connect() as conn:
        try:
            return conn.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar()
        except Exception:
            return None


def _head_revision():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option('script_location', MIGRATIONS_DIR)
    return ScriptDirectory.from_config(cfg).get_current_head()


def trial_url(slug):
    base = tenancy.base_domain()
    return f'https://{slug}.{base}' if base else f'https://{slug}.<TENANT_BASE_DOMAIN>'


def list_trials():
    """Every registered trial with its plan status (active ones only have a plan)."""
    need_postgres()
    tenancy.ensure_registry()
    out = []
    for r in tenancy.registry_rows():
        if r['status'] == 'spare':                # ready-made, not anyone's trial yet
            continue
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


def boq_status(slug):
    """How they price ({'ready', 'on'}) and whether photos on lines are on ('photos': {'ready', 'on'})."""
    from . import boq, item_images, layout, quote_gst
    with tenancy.tenant_context(slug, schema_of(slug)):
        return dict(boq.console_status(), photos=item_images.console_status(), gst=quote_gst.console_status(),
                    show_rate=layout.show_rate())


def set_show_rate(slug, on):
    """The Rate column on the customer's BOQ shown or hidden, for a trial."""
    from . import layout
    from .models import AppSetting
    with tenancy.tenant_context(slug, schema_of(slug)):
        AppSetting.set(layout.HIDE_RATE_KEY, '' if on else '1')
        db.session.commit()


def set_quote_gst(slug, on, rate):
    """GST on quotations on or off (and its rate), for a trial."""
    from . import quote_gst
    with tenancy.tenant_context(slug, schema_of(slug)):
        try:
            quote_gst.set_gst(on, rate)
        except ValueError as exc:
            raise OpsError(str(exc))
        db.session.commit()


def set_photos(slug, on):
    """Photos on quotation lines on or off, for a trial."""
    from . import item_images
    with tenancy.tenant_context(slug, schema_of(slug)):
        if on and not item_images.console_status()['ready']:
            raise OpsError('This trial needs the latest database update first (Updates → Update all).')
        item_images.set_enabled(on)
        db.session.commit()


def set_boq(slug, on):
    """Pricing by item (BOQ lines) or by material, for a trial."""
    from . import boq
    with tenancy.tenant_context(slug, schema_of(slug)):
        if on and not boq.console_status()['ready']:
            raise OpsError('This trial needs the latest database update first (Updates → Update all).')
        boq.set_pricing(boq.ITEM if on else boq.MATERIAL)
        db.session.commit()


def load_price_list(slug, parsed, remove_starter, replace_settings):
    """Load a firm's own price list into this trial only (app/price_list.py). Returns the summary dict."""
    from . import price_list
    with tenancy.tenant_context(slug, schema_of(slug)):
        try:
            return price_list.apply(parsed, remove_starter, replace_settings)
        except (price_list.PriceListError, ValueError) as exc:
            db.session.rollback()
            raise OpsError(str(exc))


def unlock_company(slug, fields):
    """Unlock company identity fields (name / gstin / logo) so the trial's admin can change them once."""
    from . import branding
    with tenancy.tenant_context(slug, schema_of(slug)):
        branding.unlock(fields)
        db.session.commit()
