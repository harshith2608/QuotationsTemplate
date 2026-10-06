import os, re, json
from sqlalchemy import create_engine, text
os.environ.update(TENANT_MODE='1', TENANT_BASE_DOMAIN='quote-room.test', SUPPORT_WHATSAPP='919876543210')
for k in ['DEMO_MODE', 'MARKETING_SITE']: os.environ.pop(k, None)
from app import create_app, db
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
runner = app.test_cli_runner()
with app.app_context():
    ENGINE = db.engine          # direct DB checks in this test
TARGET = os.environ['TEST_PG_TARGET_URL']  # empty, already-migrated Postgres for `trial convert`

r = runner.invoke(args=['trial', 'create', 'acme', '--admin-password', 'acme-pass-123'])
ok('create acme', r.exit_code == 0 and 'Trial "acme" is ready' in r.output)
r = runner.invoke(args=['trial', 'create', 'sharma', '--admin-username', 'owner', '--admin-password', 'sharma-pass-1'])
ok('create sharma', r.exit_code == 0)
ok('duplicate rejected', runner.invoke(args=['trial', 'create', 'acme', '--admin-password', 'x'*9]).exit_code != 0)
ok('reserved/invalid slugs rejected', runner.invoke(args=['trial', 'create', 'www', '--admin-password', 'x'*9]).exit_code != 0
   and runner.invoke(args=['trial', 'create', 'Bad_Name', '--admin-password', 'x'*9]).exit_code != 0)
with ENGINE.connect() as c:
    public_tables = {r[0] for r in c.execute(text("select table_name from information_schema.tables where table_schema='public'"))}
    acme_tables = {r[0] for r in c.execute(text("select table_name from information_schema.tables where table_schema='t_acme'"))}
ok(f'public schema holds only the registry {sorted(public_tables)}', public_tables == {'tenants'})
ok('acme schema has all app tables + alembic_version', {'users', 'projects', 'items', 'app_settings', 'price_list_items', 'alembic_version'} <= acme_tables)

A, B = 'http://acme.quote-room.test', 'http://sharma.quote-room.test'
ca, cb = app.test_client(), app.test_client()
ok('unknown trial → 404 page', ca.get('/', base_url='http://nobody.quote-room.test').status_code == 404)
ok('bare base domain / other hosts → 404', ca.get('/login', base_url='http://quote-room.test').status_code == 404
   and ca.get('/login', base_url='http://trials.vercel.app').status_code == 404)

ca.post('/login', base_url=A, data={'username': 'admin', 'password': 'acme-pass-123'})
cb.post('/login', base_url=B, data={'username': 'owner', 'password': 'sharma-pass-1'})
ok('acme admin signed in', ca.get('/projects', base_url=A).status_code == 200)
ok('sharma password does not work on acme', app.test_client().post('/login', base_url=A, data={'username': 'owner', 'password': 'sharma-pass-1'}).status_code == 200)

# Different data per trial
ca.post('/admin/settings', base_url=A, data={'section': 'company', 'company_name': 'Acme Interiors', 'confirm_identity': '1'})
cb.post('/admin/settings', base_url=B, data={'section': 'company', 'company_name': 'Sharma Furniture', 'confirm_identity': '1'})
d = ca.post('/api/draft', base_url=A, json={'customer_name': 'Acme Customer', 'mobile': '1', 'rooms_data': [
    {'name': 'Kitchen', 'items': [{'type': 'fixed', 'name': 'Magic Corner', 'quantity': 1, 'unit_price': 18000}]}]})
ta, tb = ca.get('/projects', base_url=A).text, cb.get('/projects', base_url=B).text
ok('branding per trial', 'Acme Interiors' in ta and 'Sharma Furniture' in tb and 'Acme Interiors' not in tb)
ok('acme quotation not visible to sharma', 'Acme Customer' in ta and 'Acme Customer' not in tb)
pid = d.get_json()['draft_id']
ok('sharma cannot open acme quotation id', cb.get(f'/projects/{pid}', base_url=B).status_code in (302, 404))

# Cookie replay: acme session cookie presented to sharma
sess = ca.get_cookie('session', domain='acme.quote-room.test')
remember = ca.get_cookie('remember_token', domain='acme.quote-room.test')
attacker = app.test_client()
attacker.set_cookie('session', sess.value, domain='sharma.quote-room.test')
if remember: attacker.set_cookie('remember_token', remember.value, domain='sharma.quote-room.test')
r = attacker.get('/projects', base_url=B)
ok('stolen acme cookies rejected on sharma', r.status_code == 302 and '/login' in r.headers['Location'])
ok('stolen cookies still valid on acme (sanity)', (lambda c: (c.set_cookie('session', sess.value, domain='acme.quote-room.test'), c.get('/projects', base_url=A).status_code)[1])(app.test_client()) == 200)

# Plans per trial
ok('trial banner shown (7-day trial)', 'Free trial</strong> ends in 7 days' in ta)
out = runner.invoke(args=['trial', 'list']).output
ok('trial list shows both', 'acme' in out and 'sharma' in out and 'trial' in out)
r = runner.invoke(args=['trial', 'extend', 'acme', '7d'])
ok('trial extend adds days', r.exit_code == 0 and '14 days left' in r.output)
ok('trial extend unknown slug fails', runner.invoke(args=['trial', 'extend', 'ghost', '7d']).exit_code != 0)
r1 = runner.invoke(args=['company-status', '--trial', 'acme']); r2 = runner.invoke(args=['company-unlock', 'name', '--trial', 'acme'])
with ENGINE.connect() as c:
    unl = c.execute(text("select value from t_acme.app_settings where key='company_unlocked'")).scalar()
ok(f'company-status/unlock --trial work inside the trial ({unl})', 'name   LOCKED' in r1.output and r2.exit_code == 0 and unl == 'name')
ok('company-unlock --trial unknown fails', runner.invoke(args=['company-unlock', 'name', '--trial', 'ghost']).exit_code != 0)
r = runner.invoke(args=['trial', 'migrate-all'])
ok('migrate-all succeeds', r.exit_code == 0 and 'up to date' in r.output)

# Database-level isolation check: data physically in the right schema
with ENGINE.connect() as c:
    a_proj = c.execute(text('select count(*) from t_acme.projects')).scalar()
    b_proj = c.execute(text('select count(*) from t_sharma.projects')).scalar()
    a_name = c.execute(text("select value from t_acme.app_settings where key='company_name'")).scalar()
ok(f'rows land in the right schema (acme={a_proj}, sharma={b_proj})', a_proj == 1 and b_proj == 0 and a_name == 'Acme Interiors')

# Convert sharma → its own database
cb.post('/api/draft', base_url=B, json={'customer_name': 'Sharma Client', 'mobile': '2', 'rooms_data': [
    {'name': 'Hall', 'items': [{'name': 'TV Unit', 'length': 9, 'width': 7, 'wood_type': 'Veneer', 'work_type': 'Frame Work'}]}]})
from cryptography.fernet import Fernet
from app import crypto
NEW_KEY = Fernet.generate_key().decode()
with app.app_context():
    from app.tenancy import tenant_context
    from app.models import AppSetting
    with tenant_context('sharma'):
        AppSetting.set('account_number', 'SHARMA-ACCT-1'); db.session.commit()
ok('convert refuses a bad --to-key', runner.invoke(args=['trial', 'convert', 'sharma', '--to', TARGET, '--plan', '1y',
                                                         '--to-key', 'nope']).exit_code != 0)
r = runner.invoke(args=['trial', 'convert', 'sharma', '--to', TARGET, '--plan', '1y', '--to-key', NEW_KEY])
ok('convert sharma', r.exit_code == 0 and 'Paid plan 1y' in r.output)
t = create_engine(TARGET.replace('postgresql://', 'postgresql+psycopg2://'))
with t.begin() as c:
    users = c.execute(text('select username from users')).scalars().all()
    raw_projects = c.execute(text('select customer_name from projects')).scalars().all()
    raw_acct = c.execute(text("select value from app_settings where key='account_number'")).scalar()
    plan = dict(c.execute(text("select key, value from app_settings where key like 'plan_%'")).all())
    name = c.execute(text("select value from app_settings where key='company_name'")).scalar()
    c.execute(text("insert into projects (customer_name, mobile, created_by, grand_total, status, stage) values ('After', '3', 1, 0, 'complete', 'pending')"))
with crypto.using_key(NEW_KEY):
    projects = [crypto.decrypt(v) for v in raw_projects]
    acct = crypto.decrypt(raw_acct)
ok(f'target has sharma data only {users} {projects}', users == ['owner'] and projects == ['Sharma Client'] and name == 'Sharma Furniture')
ok('target data re-encrypted with the customer\'s own key', all(v.startswith('enc1:') for v in raw_projects)
   and acct == 'SHARMA-ACCT-1')
try:
    crypto.decrypt(raw_projects[0]); ok('trials key can no longer read the customer copy', False)
except crypto.EncryptionError:
    ok('trials key can no longer read the customer copy', True)
ok(f'paid plan set on target {plan}', plan.get('plan_name') == '1y' and plan.get('plan_ends_on'))
ok('sequences continue after copy (insert worked)', True)
ok('converted trial no longer served by trials app', app.test_client().get('/login', base_url=B).status_code == 404)

# Delete acme
r = runner.invoke(args=['trial', 'delete', 'acme', '--yes'])
with ENGINE.connect() as c:
    gone = c.execute(text("select count(*) from information_schema.schemata where schema_name='t_acme'")).scalar() == 0
ok('delete drops schema and stops serving', r.exit_code == 0 and gone and app.test_client().get('/login', base_url=A).status_code == 404)
