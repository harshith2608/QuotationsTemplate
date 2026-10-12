"""Paying-customer provisioning against a REAL PostgreSQL (one database + login per customer) with a fake Vercel."""
import os, re, time
from datetime import timedelta
from urllib.parse import unquote
import psycopg2
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'
ADMIN = os.environ['TEST_REAL_PG_ADMIN_URL']
os.environ.update(CONSOLE_MODE='1', TENANT_BASE_DOMAIN='quote-room.test', CONSOLE_TOTP_SECRET=SECRET,
                  CONSOLE_PASSWORD_HASH=generate_password_hash('console-pass-123', method='pbkdf2:sha256'),
                  CONSOLE_VAULT_KEY=Fernet.generate_key().decode(), CUSTOMERS_ADMIN_DATABASE_URL=ADMIN,
                  VERCEL_TOKEN='fake-token', SUPPORT_WHATSAPP='919876543210')
for k in ['TENANT_MODE', 'DEMO_MODE', 'MARKETING_SITE', 'LEADS_DATABASE_URL']: os.environ.pop(k, None)

from app import create_app, db, crypto, providers, ops, customers as cust
from app.console import totp_code
from app.models import User, Project, AppSetting
from app.tenancy import tenant_context


class FakeVercel:
    def __init__(self):
        self.projects, self.domains, self.deploys, self.deleted, self.state = {}, [], [], [], 'BUILDING'
        self.fail_create = 0
    def get_project(self, name):
        p = self.projects.get(name) or next((p for p in self.projects.values() if p['id'] == name), None)
        return dict(p) if p else None
    def create_project(self, name, env, region='sin1'):
        if self.fail_create:
            self.fail_create -= 1
            raise providers.ProviderError('Vercel POST /v11/projects: rate limited (HTTP 429)')
        self.projects[name] = {'id': 'prj_' + name, 'name': name, 'repo_id': 42, 'env': env, 'region': region}
        return {'id': 'prj_' + name, 'name': name, 'repo_id': 42}
    def deploy(self, pid, name, repo_id, ref='main'):
        self.deploys.append((pid, repo_id, ref)); return 'dpl_1'
    def latest_deployment(self, pid):
        return self.state, 'x.vercel.app'
    def add_domain(self, project, domain):
        self.domains.append((project, domain))
    def delete_project(self, pid):
        self.deleted.append(pid)


for leftover in ('sharma', 'acme', 'beta'):           # from an earlier interrupted run
    providers.CustomerDatabases(ADMIN).drop(leftover)

fake = FakeVercel()
providers.vercel = lambda: fake

app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client()
c.post('/login', data={'password': 'console-pass-123', 'code': totp_code(SECRET, int(time.time() // 30))})
ok('signed in', c.get('/customers').status_code == 200)
ok('customers page has the form (all settings present)', 'New paying customer' in c.get('/customers').text)

# A trial with real data, to convert
with app.app_context():
    t = ops.create_trial('sharma', 'owner', 'sharma-pass-123', 7)
    with tenant_context('sharma'):
        u = User.query.first()
        db.session.add(Project(customer_name='Trial Customer One', mobile='9000000001', created_by=u.id,
                               grand_total=50000, discount_type='none', discount_value=0, status='complete'))
        AppSetting.set('account_number', 'SHARMA-ACCT-9'); AppSetting.set('company_name', 'Sharma Interiors')
        db.session.commit()

# Convert: runs database → data → project → deploy, then waits for the build
r = c.post('/customers', data={'source': 'trial', 'trial': 'sharma', 'name': 'Sharma Interiors', 'plan': '1y',
                               'phone': '919811111111'})
ok('convert starts and opens the customer page', r.status_code == 302 and r.headers['Location'].endswith('/customers/sharma'))
with app.app_context():
    row = cust.get('sharma')
ok('steps up to the first build done; waiting for it', row['status'] == 'provisioning' and row['step'] == 'deploy'
   and fake.deploys == [('prj_qr-sharma', 42, 'main')])
env = fake.projects['qr-sharma']['env']
ok('Vercel project gets its own keys + database URL, Singapore', fake.projects['qr-sharma']['region'] == 'sin1'
   and env['FLASK_ENV'] == 'production' and env['DATABASE_URL'].startswith('postgresql://r_sharma:')
   and Fernet(env['DATA_ENCRYPTION_KEY'].encode()) and len(env['SECRET_KEY']) == 64 and env['SUPPORT_WHATSAPP'])
t = c.get('/customers/sharma').text
ok('page shows "waiting for the first build" and refreshes itself', 'waiting for the first build' in t and 'http-equiv="refresh"' in t)
ok('address not connected before the build is ready', fake.domains == [])

fake.state = 'READY'
t = c.get('/customers/sharma').text
with app.app_context():
    row = cust.get('sharma')
    with db.engine.connect() as conn:
        tstatus = conn.execute(text("select status from public.tenants where slug='sharma'")).scalar()
ok('build ready → address connected, customer active', row['status'] == 'active'
   and fake.domains == [('prj_qr-sharma', 'sharma.quote-room.test')])
ok('trial stops being served by the trials app', tstatus == 'converted')
wa = re.search(r'href="(https://wa\.me/919811111111\?text=[^"]+)"', t)
ok('"now on your paid plan" WhatsApp message ready', wa and 'paid plan' in unquote(wa.group(1)))

# The customer's own database
with app.app_context():
    s = cust.unseal(cust.get('sharma')['secrets'])
key = s['data_key']
eng = create_engine(s['direct_url'].replace('postgresql://', 'postgresql+psycopg2://'))
with eng.connect() as conn:
    raw_name = conn.execute(text('select customer_name from projects')).scalar()
    users = conn.execute(text('select username from users')).scalars().all()
    plan = dict(conn.execute(text("select key, value from app_settings where key like 'plan_%'")).all())
with crypto.using_key(key):
    ok('trial data copied and re-encrypted with the customer\'s own key', crypto.decrypt(raw_name) == 'Trial Customer One')
ok('logins kept', users == ['owner'])
ok('12-month plan started today', plan.get('plan_name') == '1y')
with eng.connect() as conn:
    enc = conn.execute(text('select pg_encoding_to_char(encoding) from pg_database where datname = current_database()')).scalar()
ok('customer database is UTF-8', enc == 'UTF8')
with app.app_context():
    st, rev = cust.live_status('sharma')
ok('console reads the live plan (≈365 days left)', 360 <= st.days_left <= 366 and rev == cust.head_revision())

# Isolation: the customer's login opens only its own database
def can(url):
    try:
        psycopg2.connect(url).close(); return True
    except psycopg2.Error:
        return False
base = s['direct_url'].rsplit('/', 1)[0]
ok('customer login can\'t open the admin database', not can(base + '/' + ADMIN.rsplit('/', 1)[1]))

r = c.post('/customers/sharma/reveal')
ok('"Show connection details" reveals the direct URL + key (and is logged)', s['direct_url'] in r.text and key in r.text
   and 'customer reveal secrets' in c.get('/activity').text)

# Secrets are sealed in the registry
with app.app_context(), db.engine.connect() as conn:
    blob = conn.execute(text("select secrets from public.customers where slug='sharma'")).scalar()
ok('customer secrets stored sealed (no URL or key in plain text)', blob.startswith('enc1:') and 'postgresql' not in blob
   and key not in blob)

# New customer without a trial: admin password shown once, only after setup finished
fake.state = 'BUILDING'
r = c.post('/customers', data={'source': 'new', 'slug': 'acme', 'name': 'Acme Interiors', 'plan': '6m', 'admin_username': 'boss'})
t = c.get('/customers/acme').text
ok('password not shown (or used up) while the setup page is still refreshing', 'shown once' not in t and 'http-equiv="refresh"' in t)
fake.state = 'READY'
t = c.get('/customers/acme').text
m = re.search(r'Password:</strong> <span class="secret">([^<]+)</span>', t)
ok('new customer: admin password shown once', m and 'Username:</strong> <span class="secret">boss' in t)
ok('…and not again', 'shown once' not in c.get('/customers/acme').text)
with app.app_context():
    s2 = cust.unseal(cust.get('acme')['secrets'])
with create_engine(s2['direct_url'].replace('postgresql://', 'postgresql+psycopg2://')).connect() as conn:
    h = conn.execute(text("select password_hash from users where username='boss'")).scalar()
ok('that password works for the new admin', m and check_password_hash(h, m.group(1)))
ok('pending password removed from storage', 'pending_password' not in s2)
ok('one customer\'s login can\'t open another customer\'s database', can(s['direct_url']) and not can(base + '/c_acme')
   and not can(s2['direct_url'].rsplit('/', 1)[0] + '/c_sharma'))
with app.app_context():
    ops.create_trial('still-trial', 'admin', 'still-pass-123', 7)
r = c.post('/customers', data={'source': 'new', 'slug': 'still-trial', 'name': 'x', 'plan': '6m'}, follow_redirects=True)
with app.app_context():
    ok('an active trial\'s name can\'t be taken as a new customer', 'is an active trial' in r.text and cust.get('still-trial') is None)

# Renew, reset password, unlock
with app.app_context():
    before = cust.live_status('acme')[0].ends_on
r = c.post('/customers/acme/renew', data={'length': '1y'}, follow_redirects=True)
with app.app_context():
    after = cust.live_status('acme')[0]
ok('renew on time adds to the end date (no days lost)', after.ends_on > before + timedelta(days=360) and after.plan == '1y')
r = c.post('/customers/acme/reset-password', data={})
m2 = re.search(r'Password:</strong> <span class="secret">([^<]+)</span>', r.text)
with create_engine(s2['direct_url'].replace('postgresql://', 'postgresql+psycopg2://')).connect() as conn:
    h2 = conn.execute(text("select password_hash from users where username='boss'")).scalar()
ok('reset admin password works', m2 and check_password_hash(h2, m2.group(1)) and not check_password_hash(h2, m.group(1)))
with app.app_context():
    with cust.open_customer('acme'):
        AppSetting.set('company_name', 'Acme Interiors'); db.session.commit()
    ok('company name locked in the customer app', 'name' in cust.locked_fields('acme'))
c.post('/customers/acme/unlock', data={'fields': ['name']})
with app.app_context():
    ok('unlock works on customer apps', 'name' not in cust.locked_fields('acme'))

# Failure + retry
fake.fail_create = 1
c.post('/customers', data={'source': 'new', 'slug': 'beta', 'name': 'Beta', 'plan': '6m'})
with app.app_context():
    row = cust.get('beta')
ok('a provider error stops setup at that step with the reason', row['status'] == 'failed' and row['step'] == 'data'
   and 'Create Vercel project' in row['error'] and '429' in row['error'])
c.post('/customers/beta/retry')
with app.app_context():
    row = cust.get('beta')
ok('Retry continues from the failed step', row['status'] == 'active' and 'qr-beta' in fake.projects)

# Database updates for everything
r = c.post('/updates', data={'target': 'all'})
ok('Update all: trials + every customer up to date', r.text.count('>ok<') >= 4 and '>failed<' not in r.text)

# Delete
r = c.post('/customers/acme/delete', data={'confirm': 'acme'}, follow_redirects=True)
with app.app_context():
    ok('delete needs "delete <name>" typed', cust.get('acme')['status'] == 'active')
r = c.post('/customers/acme/delete', data={'confirm': 'delete acme'}, follow_redirects=True)
admin = psycopg2.connect(ADMIN); admin.autocommit = True
with admin.cursor() as cur:
    cur.execute("select count(*) from pg_database where datname='c_acme'"); dbs_left = cur.fetchone()[0]
    cur.execute("select count(*) from pg_roles where rolname='r_acme'"); roles_left = cur.fetchone()[0]
with app.app_context():
    row = cust.get('acme')
ok('delete removes Vercel project, database and login; record kept without secrets',
   'prj_qr-acme' in fake.deleted and dbs_left == 0 and roles_left == 0 and row['status'] == 'deleted' and row['secrets'] is None)

t = c.get('/activity').text
ok('activity log has the customer actions', all(w in t for w in ['customer create', 'customer renew', 'customer delete', 'db update']))

# Leave the server tidy
eng.dispose()
for slug in ('sharma', 'beta'):
    with app.app_context():
        providers.CustomerDatabases(ADMIN).drop(slug)
