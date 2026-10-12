"""
Paying customers, managed from the operator console.

Each customer gets:
  * their own Postgres database + login inside the shared Neon "customers" project (providers.CustomerDatabases)
  * their own Vercel project (qr-<slug>) with their own SECRET_KEY and DATA_ENCRYPTION_KEY
  * the address <slug>.<TENANT_BASE_DOMAIN> (a specific domain wins over the trials wildcard)

Provisioning runs as steps, recorded in public.customers (in the console's database), so a failure can be
retried from where it stopped:  database → data → project → deploy → domain (once the first build is ready).
Customer secrets (database URLs, keys) are stored sealed with CONSOLE_VAULT_KEY.
"""
import json
import os
import secrets
from contextlib import contextmanager
from datetime import date

from flask import Flask, current_app
from sqlalchemy import text

from . import crypto, db, migrate, ops, tenancy
from . import plan as plan_mod
from . import providers

STEPS = ['database', 'data', 'project', 'deploy', 'domain']
STEP_LABELS = {'database': 'Create database', 'data': 'Set up data and plan', 'project': 'Create Vercel project',
               'deploy': 'Start first build', 'domain': 'Connect address'}
PLANS = ('6m', '1y')

REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS public.customers (
    slug                VARCHAR(40)  PRIMARY KEY,
    name                VARCHAR(120) NOT NULL,
    status              VARCHAR(20)  NOT NULL,            -- provisioning / active / failed / deleted
    step                VARCHAR(20),                      -- last completed provisioning step
    error               TEXT,
    plan                VARCHAR(10),
    ends_on             DATE,
    source_trial        VARCHAR(40),
    phone               VARCHAR(20),
    vercel_project_id   VARCHAR(80),
    vercel_project_name VARCHAR(100),
    secrets             TEXT,                              -- sealed JSON
    created_at          TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    updated_at          TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    deleted_at          TIMESTAMP
)
"""


class CustomerError(Exception):
    pass


def _env(name, default=''):
    return (os.environ.get(name) or default).strip()


def missing_settings():
    """Console env vars still needed before customers can be provisioned."""
    need = ['CONSOLE_VAULT_KEY', 'CUSTOMERS_ADMIN_DATABASE_URL', 'VERCEL_TOKEN', 'TENANT_BASE_DOMAIN']
    return [k for k in need if not _env(k)]


# ── Sealed secrets ───────────────────────────────────────────────────────────

def _vault_key():
    key = _env('CONSOLE_VAULT_KEY')
    if not key:
        raise CustomerError('CONSOLE_VAULT_KEY is not set.')
    return key


def seal(data):
    with crypto.using_key(_vault_key()):
        return crypto.encrypt(json.dumps(data))


def unseal(blob):
    if not blob:
        return {}
    with crypto.using_key(_vault_key()):
        return json.loads(crypto.decrypt(blob))


# ── Registry ─────────────────────────────────────────────────────────────────

_registry_ready = False


def ensure_registry():
    global _registry_ready
    if not _registry_ready:
        with db.engine.begin() as conn:
            conn.execute(text(REGISTRY_DDL))
        _registry_ready = True


def get(slug):
    ensure_registry()
    with db.engine.connect() as conn:
        row = conn.execute(text('SELECT * FROM public.customers WHERE slug = :s'), {'s': slug}).mappings().first()
    return dict(row) if row else None


def all_customers(include_deleted=False):
    ensure_registry()
    sql = 'SELECT * FROM public.customers' + ('' if include_deleted else " WHERE status <> 'deleted'") + \
          ' ORDER BY created_at DESC'
    with db.engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql)).mappings()]


def _update(slug, **fields):
    fields['updated_at'] = text("(now() AT TIME ZONE 'utc')")
    sets, params = [], {'s': slug}
    for k, v in fields.items():
        if hasattr(v, 'text'):
            sets.append(f'{k} = {v.text}')
        else:
            sets.append(f'{k} = :{k}')
            params[k] = v
    with db.engine.begin() as conn:
        conn.execute(text(f'UPDATE public.customers SET {", ".join(sets)} WHERE slug = :s'), params)


def _secrets(slug):
    return unseal((get(slug) or {}).get('secrets'))


def _save_secrets(slug, data):
    _update(slug, secrets=seal(data))


def domain_for(slug):
    return f'{slug}.{tenancy.base_domain()}'


def app_url(slug):
    return f'https://{domain_for(slug)}'


# ── Running code against a customer's database ───────────────────────────────

@contextmanager
def customer_app(url, data_key):
    """An app context whose db.session talks to the customer's database, encrypting with their key."""
    tmp = Flask('customer', root_path=current_app.root_path)
    tmp.config.update(SQLALCHEMY_DATABASE_URI=ops.normalize_url(url),
                      SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True}, SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      SECRET_KEY=current_app.config.get('SECRET_KEY'))
    db.init_app(tmp)
    migrate.init_app(tmp, db)
    with tmp.app_context(), crypto.using_key(data_key):
        try:
            yield tmp
        finally:
            db.session.remove()
            db.engine.dispose()


def migrate_current_app():
    from flask_migrate import upgrade
    upgrade(directory=ops.MIGRATIONS_DIR)


def db_revision():
    try:
        return db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()
    except Exception:
        db.session.rollback()
        return None


def head_revision():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option('script_location', ops.MIGRATIONS_DIR)
    return ScriptDirectory.from_config(cfg).get_current_head()


@contextmanager
def open_customer(slug):
    s = _secrets(slug)
    if not s.get('direct_url'):
        raise CustomerError(f'"{slug}" has no database yet.')
    with customer_app(s['direct_url'], s['data_key']) as tmp:
        yield tmp


# ── Provisioning ─────────────────────────────────────────────────────────────

def start(slug, name, plan, source_trial=None, admin_username='admin', phone=''):
    """Register a new customer and run provisioning. Returns the registry row."""
    if missing_settings():
        raise CustomerError('Set these console settings first: ' + ', '.join(missing_settings()))
    try:
        slug = tenancy.validate_slug(slug)
    except tenancy.TenantError as exc:
        raise CustomerError(str(exc))
    if plan not in PLANS:
        raise CustomerError('Choose the 6-month or 12-month plan.')
    name = (name or '').strip()[:120] or slug
    ensure_registry()
    existing = get(slug)
    if existing and existing['status'] != 'deleted':
        raise CustomerError(f'A customer "{slug}" already exists.')
    if source_trial:
        ops.schema_of(source_trial)                       # must be an active trial
        if source_trial != slug:
            raise CustomerError('A converted trial keeps its address: use the trial\'s name as the customer name.')
    else:
        tenancy.ensure_registry()
        with db.engine.connect() as conn:
            if conn.execute(text("SELECT 1 FROM public.tenants WHERE slug = :s AND status = 'active'"),
                            {'s': slug}).first():
                raise CustomerError(f'"{slug}" is an active trial. Choose "Convert this trial" instead.')
    with db.engine.begin() as conn:
        conn.execute(text('DELETE FROM public.customers WHERE slug = :s'), {'s': slug})
        conn.execute(text('INSERT INTO public.customers (slug, name, status, plan, source_trial, phone, secrets) '
                          "VALUES (:s, :n, 'provisioning', :p, :t, :ph, :sec)"),
                     {'s': slug, 'n': name, 'p': plan, 't': source_trial, 'ph': (phone or '')[:20],
                      'sec': seal({'admin_username': (admin_username or 'admin').strip()[:80] or 'admin'})})
    return resume(slug)


def next_step(row):
    if row['step'] is None:
        return STEPS[0]
    i = STEPS.index(row['step'])
    return STEPS[i + 1] if i + 1 < len(STEPS) else None


def resume(slug, log=None):
    """Run the remaining steps until done, waiting for the build, or a failure. Returns the registry row."""
    log = log or (lambda line: None)
    row = get(slug)
    if not row or row['status'] in ('active', 'deleted'):
        return row
    _update(slug, status='provisioning', error=None)
    while True:
        row = get(slug)
        step = next_step(row)
        if step is None:
            break
        try:
            done = STEP_FUNCS[step](row, log)
        except Exception as exc:                          # record and stop; "Retry" resumes here
            if isinstance(exc, (CustomerError, ops.OpsError, providers.ProviderError)):
                current_app.logger.warning('Provisioning %s stopped at %s: %s', slug, step, exc)
            else:                                         # a bug: keep the full trace in the logs
                current_app.logger.exception('Provisioning %s failed at %s', slug, step)
            _update(slug, status='failed', error=f'{STEP_LABELS[step]}: {exc}')
            return get(slug)
        if not done:                                      # waiting (first build still running)
            return get(slug)
        _update(slug, step=step)
    _update(slug, status='active', error=None)
    return get(slug)


def _step_database(row, log):
    slug = row['slug']
    s = unseal(row['secrets'])
    if s.get('direct_url'):
        return True                                       # done in an earlier attempt
    dbs = providers.customer_databases()
    has_db, has_role = dbs.exists(slug)
    if has_db or has_role:
        raise CustomerError('A database or login for this name already exists from an earlier attempt. '
                            'Use "Remove leftovers" on this page, then Retry.')
    info = dbs.create(slug)
    ok, why = dbs.can_connect(info['pooled_url'])
    s.update(direct_url=info['direct_url'], pooled_url=info['pooled_url'],
             app_url=info['pooled_url'] if ok else info['direct_url'],
             pooler_note='' if ok else f'pooled connection failed ({why}); app uses the direct connection',
             data_key=crypto_new_key(), secret_key=secrets.token_hex(32))
    _save_secrets(slug, s)
    log('Database created.')
    return True


def crypto_new_key():
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


def _step_data(row, log):
    slug = row['slug']
    s = unseal(row['secrets'])
    with customer_app(s['direct_url'], s['data_key']):
        migrate_current_app()
        from .models import User
        already = User.query.first() is not None
    if already:
        return True                                       # data step finished in an earlier attempt
    if row['source_trial']:
        copied, start_on, end = ops.copy_trial(row['source_trial'], s['direct_url'], s['data_key'], row['plan'])
        log('Copied trial: ' + ', '.join(f'{k} {v}' for k, v in copied.items() if v))
    else:
        from .seed import bootstrap
        password = ops.generate_password()
        with customer_app(s['direct_url'], s['data_key']):
            bootstrap(username=s.get('admin_username') or 'admin', password=password)
            start_on = plan_mod.today()
            end = plan_mod.add_length(start_on, row['plan'])
            plan_mod.save_plan(row['plan'], start_on, end)
            db.session.commit()
        s['pending_password'] = password                  # shown once on the customer page, then removed
        _save_secrets(slug, s)
    _update(slug, ends_on=end)
    return True


def _project_env(s):
    env = {'FLASK_ENV': 'production', 'SECRET_KEY': s['secret_key'], 'DATABASE_URL': s['app_url'],
           'DATA_ENCRYPTION_KEY': s['data_key']}
    if _env('SUPPORT_WHATSAPP'):
        env['SUPPORT_WHATSAPP'] = _env('SUPPORT_WHATSAPP')
    return env


def _step_project(row, log):
    slug = row['slug']
    s = unseal(row['secrets'])
    v = providers.vercel()
    name = f'qr-{slug}'
    project = v.get_project(name)
    if project is None:
        project = v.create_project(name, _project_env(s), region=_env('CUSTOMER_REGION', 'sin1'))
    _update(slug, vercel_project_id=project['id'], vercel_project_name=project['name'])
    s['repo_id'] = project.get('repo_id')
    _save_secrets(slug, s)
    log(f'Vercel project {project["name"]} ready.')
    return True


def _step_deploy(row, log):
    s = unseal(row['secrets'])
    v = providers.vercel()
    repo_id = s.get('repo_id') or (v.get_project(row['vercel_project_id']) or {}).get('repo_id')
    if not repo_id:
        raise CustomerError('The Vercel project isn\'t linked to the GitHub repo. Check the Vercel GitHub app has '
                            'access to the repository, then Retry.')
    v.deploy(row['vercel_project_id'], row['vercel_project_name'], repo_id)
    log('First build started.')
    return True


def _step_domain(row, log):
    """Connect the address once the first build is READY (until then the address would show a Vercel error)."""
    v = providers.vercel()
    state, _ = v.latest_deployment(row['vercel_project_id'])
    if state == 'ERROR' or state == 'CANCELED':
        raise CustomerError(f'The first build {state.lower()}. Open the project in Vercel to see why, then Retry.')
    if state != 'READY':
        return False
    v.add_domain(row['vercel_project_id'], domain_for(row['slug']))
    if row['source_trial']:
        ops.mark_converted(row['source_trial'])          # the trials app stops serving it
    log('Address connected.')
    return True


STEP_FUNCS = {'database': _step_database, 'data': _step_data, 'project': _step_project,
              'deploy': _step_deploy, 'domain': _step_domain}


def take_pending_password(slug):
    """The new admin password, once (then forgotten)."""
    s = _secrets(slug)
    password = s.pop('pending_password', None)
    if password:
        _save_secrets(slug, s)
    return s.get('admin_username') or 'admin', password


def remove_leftovers(slug):
    """After a failed first step: drop a half-created database/login so the step can run again."""
    row = get(slug)
    if not row or row['step'] is not None:
        raise CustomerError('Only possible before the database step has completed.')
    providers.customer_databases().drop(slug)


# ── After provisioning ───────────────────────────────────────────────────────

def live_status(slug):
    with open_customer(slug):
        st = plan_mod.load_status(on=plan_mod.today())
        rev = db_revision()
    if st.has_limit:
        _update(slug, ends_on=st.ends_on, plan=st.plan)
    return st, rev


def renew(slug, length):
    if length not in PLANS:
        raise CustomerError('Renew by 6 months or 12 months.')
    with open_customer(slug):
        st = plan_mod.renew(length)
        db.session.commit()
    _update(slug, ends_on=st.ends_on, plan=st.plan)
    return st


def reset_admin_password(slug, username=None):
    from werkzeug.security import generate_password_hash
    from .models import User
    password = ops.generate_password()
    with open_customer(slug):
        q = User.query.filter_by(role='admin')
        user = (q.filter_by(username=username) if username else q.order_by(User.id)).first()
        if not user:
            raise CustomerError('No admin user found.')
        user.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        db.session.commit()
        return user.username, password


def admin_usernames(slug):
    from .models import User
    with open_customer(slug):
        return [u.username for u in User.query.filter_by(role='admin').order_by(User.id)]


def locked_fields(slug):
    from . import branding
    with open_customer(slug):
        return branding.locked_fields()


def unlock_company(slug, fields):
    from . import branding
    with open_customer(slug):
        branding.unlock(fields)
        db.session.commit()


def delete(slug):
    """Delete the customer's Vercel project, database and login. The registry keeps a record without secrets."""
    row = get(slug)
    if not row or row['status'] == 'deleted':
        raise CustomerError(f'No customer "{slug}".')
    if row['vercel_project_id']:
        providers.vercel().delete_project(row['vercel_project_id'])
    providers.customer_databases().drop(slug)
    _update(slug, status='deleted', secrets=None, deleted_at=text("(now() AT TIME ZONE 'utc')"))


# ── Database updates for everything ──────────────────────────────────────────

def update_targets():
    """[(key, label)] of every database the console can update."""
    targets = []
    if _env('LEADS_DATABASE_URL') and _env('LEADS_DATA_ENCRYPTION_KEY'):
        targets.append(('demo', 'Demo / marketing site'))
    targets.append(('trials', 'All trials'))
    for c in all_customers():
        if c['status'] == 'active' or (c['step'] and STEPS.index(c['step']) >= STEPS.index('data')):
            targets.append((f'customer:{c["slug"]}', c['name'] + f' ({c["slug"]})'))
    return targets


def run_update(key):
    """Bring one target to the latest database version. Returns a short result line."""
    from .seed import encrypt_existing_data
    if key == 'demo':
        with customer_app(_env('LEADS_DATABASE_URL'), _env('LEADS_DATA_ENCRYPTION_KEY')):
            migrate_current_app()
            return f'up to date ({db_revision()}). {encrypt_existing_data()}'
    if key == 'trials':
        lines = []
        failed = ops.migrate_all_trials(log=lines.append)
        if failed:
            raise CustomerError('failed for ' + ', '.join(failed) + ': ' + ' '.join(lines)[-300:])
        return f'{sum(1 for l in lines if l.startswith("→"))} trial(s) up to date.'
    if key.startswith('customer:'):
        slug = key.split(':', 1)[1]
        with open_customer(slug):
            migrate_current_app()
            return f'up to date ({db_revision()}). {encrypt_existing_data()}'
    raise CustomerError(f'Unknown target {key}.')


def plan_badge(row, today=None):
    """(label, css class) for the customers list, from the cached plan end date."""
    today = today or plan_mod.today()
    if row['status'] == 'failed':
        return 'setup failed', 'b-due'
    if row['status'] == 'provisioning':
        return 'setting up', 'b-reminder'
    if row['status'] == 'deleted':
        return 'deleted', 'b-other'
    ends = row['ends_on']
    if not ends:
        return 'active', 'b-active'
    if isinstance(ends, str):
        ends = date.fromisoformat(ends)
    days = (ends - today).days
    if days < -plan_mod.GRACE_DAYS:
        return 'expired · read-only', 'b-read_only'
    if days < 0:
        return 'expired · grace', 'b-grace'
    if days < plan_mod.REMIND_DAYS:
        return f'renew soon · {days} d', 'b-reminder'
    return 'active', 'b-active'
