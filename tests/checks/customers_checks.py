"""Paying-customer provisioning against a REAL PostgreSQL (one database + login per customer) with a fake Vercel."""
import os, re, time
import json as _json_mod
from datetime import timedelta
from urllib.parse import unquote
import psycopg2
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)


def _dec(key, value):
    from app import crypto as _c
    with _c.using_key(key):
        return _c.decrypt(value)


SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'
ADMIN = os.environ['TEST_REAL_PG_ADMIN_URL']
os.environ.update(CONSOLE_MODE='1', TENANT_BASE_DOMAIN='quote-room.test', CONSOLE_TOTP_SECRET=SECRET,
                  CONSOLE_PASSWORD_HASH=generate_password_hash('console-pass-123', method='pbkdf2:sha256'),
                  CONSOLE_VAULT_KEY=Fernet.generate_key().decode(), CUSTOMERS_ADMIN_DATABASE_URL=ADMIN,
                  VERCEL_TOKEN='fake-token', SUPPORT_WHATSAPP='919876543210', SHARED_HOSTING='1')
for k in ['TENANT_MODE', 'DEMO_MODE', 'MARKETING_SITE', 'LEADS_DATABASE_URL']: os.environ.pop(k, None)

from app import create_app, db, crypto, providers, ops, customers as cust
from app.console import totp_code
from app.models import User, Project, AppSetting
from app.tenancy import tenant_context


class FakeVercel:
    def __init__(self):
        self.projects, self.domains, self.deploys, self.deleted, self.state = {}, [], [], [], 'BUILDING'
        self.fail_create = 0
        self.domain_owner, self.released = {}, []
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
    def add_domain(self, project, domain, release_from=None):
        owner = self.domain_owner.get(domain)
        if owner and owner != project:
            if release_from and owner == release_from:
                self.domain_owner.pop(domain); self.released.append((release_from, domain))
            else:
                raise providers.ProviderError(f'{domain} is attached to another Vercel project. Remove it there '
                                              '(Project → Settings → Domains), then press Retry.')
        self.domain_owner[domain] = project
        self.domains.append((project, domain))
    def delete_project(self, pid):
        self.deleted.append(pid)
    def get_env(self, pid):
        p = next(p for p in self.projects.values() if p['id'] == pid)
        return dict(p['env'])


for leftover in ('sharma', 'acme', 'beta', 'legacy', 'nest', 'payer', 'closer', 'reminded', 'linked', 'paidfirst'):           # from an earlier interrupted run
    providers.CustomerDatabases(ADMIN).drop(leftover)

fake = FakeVercel()
providers.vercel = lambda: fake
LIVE = {}            # what the (pretend) live app reports from its signed /healthz
cust.live_report = lambda slug, s=None: LIVE.get(slug, 'unreachable')

app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client()
c.post('/login', data={'password': 'console-pass-123', 'code': totp_code(SECRET, int(time.time() // 30))})
ok('signed in', c.get('/customers').status_code == 200)
ok('customers page has the form (all settings present)', 'New paying customer' in c.get('/customers').text)

# A trial with real data, to convert
# (made like a real one: details pre-filled from the trial request, then the recent features used: plywood on the
#  quotation and on an item, room descriptions, staff "Can edit" access, specs with placeholders)
with app.app_context():
    t = ops.create_trial('sharma', 'owner', 'sharma-pass-123', 7, company='Sharma Interiors', phone='919811111111',
                         city='Hyderabad', email='hello@sharma.example')
    with tenant_context('sharma'):
        from app.models import Room, Item, ProjectAccess, PlywoodOption
        from app import plywood as _ply
        u = User.query.first()
        _ply.ensure_options()
        ply_names = [o.name for o in PlywoodOption.query.order_by(PlywoodOption.sort_order)]
        p1 = Project(customer_name='Trial Customer One', mobile='9000000001', created_by=u.id,
                     grand_total=50000, discount_type='none', discount_value=0, status='complete', plywood=ply_names[1])
        db.session.add(p1); db.session.flush()
        room = Room(project_id=p1.id, name='Kitchen', description='Carcass: BWP ply · Shutters: 1mm laminate')
        db.session.add(room); db.session.flush()
        db.session.add(Item(room_id=room.id, name='Base Cabinet', length=10, width=3, quantity=2, wood_type='Laminates',
                            work_type='Box Work', area=60, plywood=ply_names[2]))
        staff = User(username='rahul', password_hash=generate_password_hash('rahul-pass-123', method='pbkdf2:sha256'),
                     role='employee')
        db.session.add(staff); db.session.flush()
        db.session.add(ProjectAccess(project_id=p1.id, user_id=staff.id, granted_by=u.id, can_edit=True))
        AppSetting.set('account_number', 'SHARMA-ACCT-9')
        AppSetting.set('material_specs', 'Plywood: {plywood_details} for all carcass and shutters')
        db.session.commit()
        trial_pid = p1.id
        # Turnkey features: priced by item from a loaded price list (items + a starting quotation), and a BOQ quotation
        # with a line measured by size, a "Price to follow" line and a rate-only line
        import json as _j
        from app import price_list as _pl
        _pl.apply(_pl.parse(_j.dumps({'lines': [
            {'name': 'Wardrobe', 'unit': 'sqft', 'rate': 1950, 'group': 'Bedroom', 'description': 'BWR ply, laminate'},
            {'name': 'Lights & Fittings', 'unit': 'LS', 'rate': 50000, 'group': 'Services'},
            {'name': 'COB Light', 'unit': 'nos', 'rate': 520, 'group': 'Light rates'}],
            'templates': [{'name': '2 BHK turnkey', 'rooms': [{'name': 'Bedroom', 'items': ['Wardrobe'],
                                                                'description': ['Sizes as per site']}]}]}).encode()))
        p2 = Project(customer_name='Turnkey Customer', mobile='9000000002', created_by=u.id, grand_total=109200,
                     discount_type='none', discount_value=0, status='complete')
        db.session.add(p2); db.session.flush()
        r2 = Room(project_id=p2.id, name='Bedroom', description='Sizes as per site')
        db.session.add(r2); db.session.flush()
        for kw in (dict(name='Wardrobe', quantity=56, unit_price=1950, unit='sqft', description='BWR ply, laminate',
                        length=7, width=8),
                   dict(name='Lights & Fittings', quantity=1, unit_price=None, unit='lump sum'),
                   dict(name='COB Light', quantity=0, unit_price=520, unit='nos')):
            kw.setdefault('length', 0); kw.setdefault('width', 0)
            db.session.add(Item(room_id=r2.id, item_type='boq', area=0, wood_type='', work_type='', **kw))
        db.session.commit()
        boq_pid = p2.id

# Convert: runs database → data → project → deploy, then waits for the build
r = c.post('/customers', data={'hosting': 'own', 'source': 'trial', 'trial': 'sharma', 'name': 'Sharma Interiors', 'plan': '1y',
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
ok('logins kept', sorted(users) == ['owner', 'rahul'])
with eng.connect() as conn:
    sett = dict(conn.execute(text("select key, value from app_settings where key in "
                                  "('company_name', 'company_mobile', 'company_address', 'company_email')")).all())
    ply_cols = conn.execute(text('select p.plywood, i.plywood, r.description, a.can_edit from projects p '
                                 'join rooms r on r.project_id = p.id join items i on i.room_id = r.id '
                                 'join project_access a on a.project_id = p.id')).first()
ok('pre-filled company details carried over', sett == {'company_name': 'Sharma Interiors', 'company_mobile': '+91 98111 11111',
                                                     'company_address': 'Hyderabad', 'company_email': 'hello@sharma.example'})
desc = ply_cols and (_dec(key, ply_cols[2]) if str(ply_cols[2]).startswith('enc1:') else ply_cols[2])
ok('recent features carried over: quotation + item plywood, room description, Can edit access',
   ply_cols is not None and ply_cols[0] and ply_cols[1] and ply_cols[3] is True and 'BWP' in (desc or ''))
ok('12-month plan started today', plan.get('plan_name') == '1y')
with eng.connect() as conn:
    tk = dict(conn.execute(text("select key, value from app_settings where key in ('feature_boq', 'initial_layout', "
                                "'quote_templates', 'room_descriptions')")).all())
    n_lines = conn.execute(text('select count(*) from boq_items')).scalar()
    boq_items = conn.execute(text("select name, unit, description, unit_price, length from items "
                                  "where item_type = 'boq' order by id")).all()
_tpl = _json_mod.loads(tk.get('quote_templates') or '[]')
ok('turnkey features carried over: priced by item, BOQ layout, saved lines, starting quotation, section notes',
   tk.get('feature_boq') == '1' and tk.get('initial_layout') == 'boq' and n_lines == 3
   and [t['name'] for t in _tpl] == ['2 BHK turnkey'] and 'Sizes as per site' in (tk.get('room_descriptions') or ''))
ok('…and the BOQ lines: unit, description, size, "Price to follow" (no rate) and rate-only',
   len(boq_items) == 3 and boq_items[0][1] == 'sqft' and boq_items[0][4] == 7 and boq_items[1][3] is None
   and boq_items[2][3] is not None and boq_items[0][2])
with eng.connect() as conn:
    enc = conn.execute(text('select pg_encoding_to_char(encoding) from pg_database where datname = current_database()')).scalar()
ok('customer database is UTF-8', enc == 'UTF8')
with app.app_context():
    st, rev = cust.live_status('sharma')
ok('console reads the live plan (≈365 days left)', 360 <= st.days_left <= 366 and rev == cust.head_revision())

# The customer's own app, started on its new database with its own key: the owner and staff use it as before
import subprocess, sys, json as _json
code_ = '''
import json, os, re
os.environ.pop("CONSOLE_MODE", None)
from app import create_app
app = create_app("development"); app.config["WTF_CSRF_ENABLED"] = False
pid = int(os.environ["PID"]); out = {}
c = app.test_client(); c.post("/login", data={"username": "owner", "password": "sharma-pass-123"})
for u in ["/projects", f"/projects/{pid}", f"/projects/{pid}/edit", f"/projects/{pid}/pdf", f"/projects/{pid}/pdf/customer",
          "/admin/reports", "/admin/rates", "/admin/settings", "/admin/settings?tab=documents", "/admin/dashboard"]:
    r = c.get(u); out[u] = r.status_code
v = c.get(f"/projects/{pid}").text
out["name"] = "Sharma Interiors" in v
s = app.test_client(); s.post("/login", data={"username": "rahul", "password": "rahul-pass-123"})
out["staff_edit"] = s.get(f"/projects/{pid}/edit").status_code
out["staff_reports"] = s.get("/admin/reports").status_code
bp = int(os.environ["BOQ_PID"])
for u in [f"/projects/{bp}", f"/projects/{bp}/edit", f"/projects/{bp}/pdf", f"/projects/{bp}/pdf/customer", "/templates",
          "/admin/settings?tab=pricing", "/projects/new"]:
    r = c.get(u); out["boq " + u] = r.status_code
out["start_cards"] = "2 BHK turnkey" in c.get("/projects/new").text
bv = c.get(f"/projects/{bp}").text
out["boq_page"] = "Quotation PDF" in bv and "price to follow" in bv and "Section Total" in bv
import io
from pypdf import PdfReader
pdf = " ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(c.get(f"/projects/{bp}/pdf/customer").data)).pages)
out["boq_pdf"] = "Price to follow" in pdf and "1,09,200" in pdf.replace("109,200", "1,09,200")
print("RESULT " + json.dumps(out))
'''
env_ = dict(os.environ, DATABASE_URL=s['direct_url'], DATA_ENCRYPTION_KEY=key, PID=str(trial_pid), BOQ_PID=str(boq_pid),
            FLASK_ENV='development')
res = subprocess.run([sys.executable, '-c', code_], capture_output=True, text=True, env=env_,
                     cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
m = re.search(r'RESULT (.*)', res.stdout)
out = _json.loads(m.group(1)) if m else {}
pages = {k: v for k, v in out.items() if k.startswith('/')}
ok(f'converted app: every main page works for the owner {pages or res.stderr[-400:]}',
   pages and all(v == 200 for v in pages.values()) and out.get('name'))
ok(f'converted app: the turnkey quotation, its PDFs, starting quotations and Settings → Pricing all work '
   f'{ {k: v for k, v in out.items() if k.startswith("boq ") or k in ("start_cards", "boq_page", "boq_pdf")} }',
   all(v == 200 for k, v in out.items() if k.startswith('boq /')) and out.get('start_cards') and out.get('boq_page')
   and out.get('boq_pdf'))
ok('converted app: staff keep their "Can edit" access; reports stay admin-only',
   out.get('staff_edit') == 200 and out.get('staff_reports') in (302, 403))

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
r = c.post('/customers', data={'hosting': 'own', 'source': 'new', 'slug': 'acme', 'name': 'Acme Interiors', 'plan': '6m', 'admin_username': 'boss'})
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
r = c.post('/customers', data={'hosting': 'own', 'source': 'new', 'slug': 'still-trial', 'name': 'x', 'plan': '6m'}, follow_redirects=True)
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
LIVE['acme'] = {'database': 'c_acme', 'user': 'r_acme', 'flask_env': 'production', 'admins': ['boss']}
r = c.post('/customers/acme/diagnose', data={'password': m2.group(1)})
ok('Diagnose: same database, settings present, password matches', r.text.count('>problem<') == 0
   and 'Live app is connected to the same database' in r.text
   and 'App settings point to the same database' in r.text and 'yes, for boss' in r.text and m2.group(1) not in r.text)
fake.projects['qr-acme']['env']['DATABASE_URL'] = 'postgresql://someone:pw@other-host/otherdb'
LIVE['acme'] = {'database': 'otherdb', 'user': 'someone', 'flask_env': 'production', 'admins': ['x']}
r = c.post('/customers/acme/diagnose', data={'password': 'wrong-password'})
ok('Diagnose flags a different app database and a non-matching password', r.text.count('>problem<') == 3
   and 'someone @ other-host / otherdb' in r.text and 'no admin has this password' in r.text)
fake.projects['qr-acme']['env']['DATABASE_URL'] = s2['app_url']
with app.app_context():
    with cust.open_customer('acme'):
        AppSetting.set('company_name', 'Acme Interiors'); db.session.commit()
    ok('company name locked in the customer app', 'name' in cust.locked_fields('acme'))
c.post('/customers/acme/unlock', data={'fields': ['name']})
with app.app_context():
    ok('unlock works on customer apps', 'name' not in cust.locked_fields('acme'))

# An address added by hand to another project (before the wildcard): clear error, no silent "success"
with app.app_context():
    ops.create_trial('legacy', 'admin', 'legacy-pass-123', 7)
fake.domain_owner['legacy.quote-room.test'] = 'prj_some-other-project'
c.post('/customers', data={'hosting': 'own', 'source': 'trial', 'trial': 'legacy', 'name': 'Legacy', 'plan': '6m'})
c.get('/customers/legacy')
with app.app_context():
    row = cust.get('legacy')
    with db.engine.connect() as conn:
        tstatus = conn.execute(text("select status from public.tenants where slug='legacy'")).scalar()
ok('address held by another project → setup stops with a clear message; trial NOT marked converted',
   row['status'] == 'failed' and 'attached to another Vercel project' in row['error'] and tstatus == 'active')
os.environ['VERCEL_TRIALS_PROJECT'] = 'prj_some-other-project'
c.post('/customers/legacy/retry')
with app.app_context():
    row = cust.get('legacy')
ok('with VERCEL_TRIALS_PROJECT set, Retry moves the address from the trials project and finishes',
   row['status'] == 'active' and ('prj_some-other-project', 'legacy.quote-room.test') in fake.released
   and fake.domain_owner['legacy.quote-room.test'] == 'prj_qr-legacy')

# Failure + retry
fake.fail_create = 1
c.post('/customers', data={'hosting': 'own', 'source': 'new', 'slug': 'beta', 'name': 'Beta', 'plan': '6m'})
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
for slug in ('sharma', 'beta', 'legacy'):
    with app.app_context():
        providers.CustomerDatabases(ADMIN).drop(slug)


# Before shared hosting is switched on (SHARED_HOSTING), "own app" stays the default and shared is refused
os.environ.pop('SHARED_HOSTING')
t_ = c.get('/customers').text
with app.app_context():
    try:
        cust.start('notyet', 'Not Yet', '6m', hosting='shared'); refused = False
    except cust.CustomerError:
        refused = True
ok('before setup: the console keeps "own app" as the default and refuses the shared app',
   refused and 'value="own" checked' in t_.replace('  ', ' ') or (refused and re.search(r'value="own"\s+checked', t_) is not None))
os.environ['SHARED_HOSTING'] = '1'

# ── Shared hosting: the trial converts in seconds into its own database, served by the shared trials app ──

with app.app_context():
    ops.create_trial('nest', 'owner', 'nest-pass-123', 7, company='Nest Interiors')
    ops.create_trial('mover', 'admin', 'mover-pass-123', 7)
    with tenant_context('nest'):
        u = User.query.first()
        db.session.add(Project(customer_name='Nest Customer', mobile='9000000077', created_by=u.id, grand_total=1000,
                               discount_type='none', discount_value=0, status='complete'))
        db.session.commit()
r = c.post('/customers', data={'hosting': 'shared', 'source': 'trial', 'trial': 'nest', 'name': 'Nest Interiors',
                               'plan': '6m', 'phone': '919822222222'})
with app.app_context():
    row = cust.get('nest')
    with db.engine.connect() as conn:
        tstatus = conn.execute(text("select status from public.tenants where slug='nest'")).scalar()
ok('shared hosting: converted in one go (database → data → switch), no Vercel project',
   row['status'] == 'active' and row['hosting'] == 'shared' and row['step'] == 'switch' and tstatus == 'converted'
   and 'qr-nest' not in fake.projects)
with app.app_context():
    sn = cust.unseal(row['secrets'])
eng_n = create_engine(sn['direct_url'].replace('postgresql://', 'postgresql+psycopg2://'))
with eng_n.connect() as conn:
    raw = conn.execute(text('select customer_name from projects')).scalar()
ok('…its data is in its own database, encrypted with its own key', _dec(sn['data_key'], raw) == 'Nest Customer'
   and sn['data_key'] != os.environ['DATA_ENCRYPTION_KEY'])
t = c.get('/customers/nest').text
ok('customer page shows the shared app', 'shared app (own database and key)' in t)
with app.app_context():
    ops.set_moving('mover', True)

# The shared trials app (TENANT_MODE) serves the trial, the paying customer and the "moving" page
code_s = """
import json, os, re
os.environ.pop("CONSOLE_MODE", None)
from app import create_app
app = create_app("development"); app.config["WTF_CSRF_ENABLED"] = False
out = {}
c = app.test_client()
H = {"base_url": "http://nest.quote-room.test"}
c.post("/login", data={"username": "owner", "password": "nest-pass-123"}, **H)
v = c.get("/projects", **H)
out["list"] = v.status_code; out["has_customer"] = "Nest Customer" in v.text
pid = int(re.search(r"/projects/(\\d+)", v.text).group(1))
for u in [f"/projects/{pid}", f"/projects/{pid}/pdf/customer", "/projects/new", "/admin/settings", "/admin/rates"]:
    out[u] = c.get(u, **H).status_code
r = c.post("/projects/new", data={"customer_name": "Saved After Move", "mobile": "9000000088", "discount_type": "none",
           "discount_value": "0", "rooms_data": json.dumps([{"name": "Hall", "items": [{"name": "TV Unit", "type": "fixed",
           "quantity": 1, "unit_price": 5000}]}])}, **H)
out["save"] = r.status_code
t = app.test_client()
out["trial_login"] = t.post("/login", data={"username": "admin", "password": "still-pass-123"},
                            base_url="http://still-trial.quote-room.test").status_code
out["trial_page"] = t.get("/projects", base_url="http://still-trial.quote-room.test").status_code
out["moving"] = app.test_client().get("/login", base_url="http://mover.quote-room.test").status_code
out["unknown"] = app.test_client().get("/login", base_url="http://nobody.quote-room.test").status_code
out["cross"] = c.get("/projects", base_url="http://still-trial.quote-room.test").status_code
print("RESULT " + json.dumps(out))
"""
env_s = dict(os.environ, TENANT_MODE='1', FLASK_ENV='development')
env_s.pop('CONSOLE_MODE', None)
res = subprocess.run([sys.executable, '-c', code_s], capture_output=True, text=True, env=env_s,
                     cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
m = re.search(r'RESULT (.*)', res.stdout)
o = _json.loads(m.group(1)) if m else {}
ok(f'shared app: the paying customer signs in with the same login and sees their data {o or res.stderr[-600:]}',
   o.get('list') == 200 and o.get('has_customer'))
ok('…every page and the PDF work from their own database',
   all(o.get(k) == 200 for k in o if k.startswith('/')) and o.get('save') == 302)
with eng_n.connect() as conn:
    names = [_dec(sn['data_key'], r_) for r_ in conn.execute(text('select customer_name from projects')).scalars()]
ok('…and a quotation saved after the move goes into their own database', 'Saved After Move' in names)
ok('the same app still serves trials; a trial being moved shows "upgrading"; unknown addresses 404; '
   'a customer\'s login doesn\'t open a trial', o.get('trial_page') == 200 and o.get('moving') == 503
   and o.get('unknown') == 404 and o.get('cross') in (302, 401))
with app.app_context():
    ops.set_moving('mover', False)
    with db.engine.connect() as conn:
        ok('a move that is called off gives the trial back', conn.execute(
            text("select status from public.tenants where slug='mover'")).scalar() == 'active')
with app.app_context():
    keys = [k for k, _ in cust.update_targets()]
    res_u = cust.run_update('customer:nest')
ok('Update all includes shared-hosting customers', 'customer:nest' in keys and res_u.startswith('up to date'))

# ── Plans bought in the app (Razorpay): pay → plan active → moved to its own database (plan kept) → renew ──
import hmac as _hmac, hashlib as _hl
os.environ.update(PLATFORM_RAZORPAY_KEY_ID='rzp_test_platform', PLATFORM_RAZORPAY_KEY_SECRET='platform-secret',
                  PLATFORM_RAZORPAY_WEBHOOK_SECRET='hook-secret', PLATFORM_LEGAL_NAME='Harshith Pola (QuoteRoom)',
                  CRON_SECRET='cron-secret')
from app import subscription as subs
import glob as _glob, tempfile as _tf, email as _em
OUTBOX = _tf.mkdtemp()
os.environ.update(MAIL_OUTBOX_DIR=OUTBOX, OPERATOR_EMAIL='hello@quote-room.test')
def outbox():
    import email.policy as _pol
    return [_em.message_from_bytes(open(f, 'rb').read(), policy=_pol.default) for f in sorted(_glob.glob(OUTBOX + '/*.eml'))]
with app.app_context():
    ops.create_trial('payer', 'admin', 'payer-pass-123', 7, company='Payer Interiors', email='owner@payer.example')
    trial_end = None
    with tenant_context('payer'):
        from app import plan as _pm
        trial_end = _pm.load_status(on=_pm.today()).ends_on
code_p = """
import json, os, re, hmac, hashlib
os.environ.pop("CONSOLE_MODE", None)
from app import create_app, subscription as S
n = {"i": 0}
def fake_api(method, path, payload=None):
    n["i"] += 1
    return {"id": f"order_{os.environ['RUN']}{n['i']}", "amount": payload["amount"]}
S._api = fake_api
app = create_app("development"); app.config["WTF_CSRF_ENABLED"] = False
H = {"base_url": "http://" + os.environ["SLUG"] + ".quote-room.test"}
c = app.test_client(); c.post("/login", data={"username": "admin", "password": os.environ["PW"]}, **H)
out = {}
p = c.get("/plan", **H); out["page"] = p.status_code; out["prices"] = "₹4,999" in p.text and "₹8,999" in p.text
out["checkout_js"] = "checkout.razorpay.com/v1/checkout.js" in p.text
out["banner"] = 'href="/plan"' in c.get("/projects", **H).text
o = c.post("/plan/order", json={"plan": os.environ["PLAN"]}, **H).get_json(); out["order"] = o
sig = hmac.new(b"platform-secret", f"{o['order_id']}|pay_{o['order_id']}".encode(), hashlib.sha256).hexdigest()
bad = c.post("/plan/paid", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_x", "razorpay_signature": "nope"}, **H)
out["bad_sig"] = bad.status_code
r = c.post("/plan/paid", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_" + o["order_id"],
                                "razorpay_signature": sig}, **H).get_json()
out["paid"] = r
again = c.post("/plan/paid", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": "pay_" + o["order_id"],
                                    "razorpay_signature": sig}, **H).get_json()
out["again_ok"] = again.get("ok")
t = c.get(r["redirect"], **H); out["thanks"] = t.status_code; out["moving_note"] = "own private database" in t.text
pid = int(r["redirect"].rsplit("/", 1)[1])
rc = c.get(f"/plan/receipt/{pid}", **H); out["receipt"] = rc.status_code == 200 and rc.data[:4] == b"%PDF"
print("RESULT " + json.dumps(out))
"""
def run_app(slug, pw, plan, run):
    env_p = dict(os.environ, TENANT_MODE='1', FLASK_ENV='development', SLUG=slug, PW=pw, PLAN=plan, RUN=run)
    env_p.pop('CONSOLE_MODE', None)
    res = subprocess.run([sys.executable, '-c', code_p], capture_output=True, text=True, env=env_p,
                         cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    m = re.search(r'RESULT (.*)', res.stdout)
    return (_json.loads(m.group(1)) if m else {}), res.stderr[-800:]
o, err = run_app('payer', 'payer-pass-123', '1y', 'A')
ok(f'in the app: Choose a plan shows both prices with Razorpay Checkout; the banner opens it {o or err}',
   o.get('page') == 200 and o.get('prices') and o.get('checkout_js') and o.get('banner'))
ok('…a payment with a wrong signature is refused; the right one activates the plan (once, even if sent twice)',
   o.get('bad_sig') == 400 and (o.get('paid') or {}).get('ok') and o.get('again_ok'))
ok('…thank-you page (with the "moving to your own database" note) and a receipt PDF', o.get('thanks') == 200
   and o.get('moving_note') and o.get('receipt'))
with app.app_context():
    with tenant_context('payer'):
        st = _pm.load_status(on=_pm.today())
    row = subs.get_by_order(o['order']['order_id'])
mails = outbox()
paid_mail = next((m for m in mails if m['To'] == 'owner@payer.example'), None)
with app.app_context():
    paid_receipt = subs.get_by_order(o['order']['order_id'])['receipt_no']
ok('payment emails: "Payment received" to the business with the receipt PDF attached, and a note to the operator',
   paid_mail is not None and 'Payment received' in paid_mail['Subject']
   and any(p.get_filename() == f'QuoteRoom-receipt-{paid_receipt}.pdf'
           for p in paid_mail.iter_attachments())
   and any(m['To'] == 'hello@quote-room.test' and m['Subject'].startswith('Payment: ₹8,999 from Payer Interiors') for m in mails))
ok('the 12-month plan starts when the trial ends: no trial days lost', st.plan == '1y'
   and st.ends_on == _pm.add_length(trial_end, '1y') and row['status'] == 'paid' and row['receipt_no'].startswith('QR'))

def hook(event, order_id, pay_id, secret='hook-secret'):
    body = _json.dumps({'event': event, 'payload': {'order': {'entity': {'id': order_id}},
                                                    'payment': {'entity': {'id': pay_id, 'order_id': order_id}}}}).encode()
    sig = _hmac.new(secret.encode(), body, _hl.sha256).hexdigest()
    return c.post('/billing/razorpay-webhook', data=body, headers={'X-Razorpay-Signature': sig},
                  content_type='application/json')
r = hook('order.paid', o['order']['order_id'], 'pay_' + o['order']['order_id'], secret='wrong')
ok('webhook with a wrong signature is refused', r.status_code == 400)
r = hook('order.paid', o['order']['order_id'], 'pay_' + o['order']['order_id'])
with app.app_context():
    pc = cust.get('payer')
    with cust.open_customer('payer'):
        st2 = _pm.load_status(on=_pm.today())
    with db.engine.connect() as conn:
        n_paid = conn.execute(text("select count(*) from public.platform_payments where slug='payer' and status='paid'")).scalar()
ok('webhook after the app recorded it: counted once, and the paid trial is moved to its own database',
   r.status_code == 200 and r.get_json()['result'] == 'already recorded' and n_paid == 1
   and pc and pc['status'] == 'active' and pc['hosting'] == 'shared')
ok('…keeping the plan it bought (not restarted from today)', st2.plan == '1y' and st2.ends_on == st.ends_on)

# A payment whose browser closed: only the webhook records it, adds the plan and moves the trial
with app.app_context():
    ops.create_trial('closer', 'admin', 'closer-pass-123', 7, company='Closer Interiors')
    subs._api = lambda method, path, payload=None: {'id': 'order_CLOSED1', 'amount': payload['amount']}
    subs.create_order('closer', '6m', 'Closer Interiors', 'admin')
r = hook('order.paid', 'order_CLOSED1', 'pay_CLOSED1')
with app.app_context():
    pc2 = cust.get('closer')
    rowc = subs.get_by_order('order_CLOSED1')
ok('browser closed after paying: the webhook records it (receipt number), adds the 6-month plan and moves the trial',
   r.get_json()['result'].startswith('paid') and rowc['status'] == 'paid' and rowc['source'] == 'webhook'
   and rowc['plan_end'] is not None and pc2 and pc2['status'] == 'active')

# Renewing later, as a paying customer in the shared app
o2, err2 = run_app('payer', 'payer-pass-123', '6m', 'B')
with app.app_context():
    with cust.open_customer('payer'):
        st3 = _pm.load_status(on=_pm.today())
ok(f'a moved customer renews in the app: 6 more months added to the end date {o2.get("paid") or err2}',
   (o2.get('paid') or {}).get('ok') and st3.ends_on == _pm.add_length(st2.ends_on, '6m') and not o2.get('moving_note'))

t = c.get('/payments').text
ok('console Payments: every payment with its receipt and totals', 'Payer Interiors' in t and 'Closer Interiors' in t
   and '₹8,999' in t and '₹4,999' in t and c.get(f'/payments/{row["id"]}/receipt').data[:4] == b'%PDF')
# Reminders: a trial ending tomorrow gets one email (not one per tick)
with app.app_context():
    ops.create_trial('reminded', 'admin', 'reminded-pass-123', 1, company='Reminded Interiors', email='r@reminded.example')
before = len(outbox())
r1 = c.get('/cron/tick', headers={'Authorization': 'Bearer cron-secret'}).get_json()
r2 = c.get('/cron/tick', headers={'Authorization': 'Bearer cron-secret'}).get_json()
rem = [m for m in outbox()[before:] if m['To'] == 'r@reminded.example']
ok('daily reminders: "trial ends tomorrow" once (not again on the next tick), with the link to choose a plan',
   len(rem) == 1 and rem[0]['Subject'] == 'Your QuoteRoom free trial ends tomorrow'
   and 'https://reminded.quote-room.test/plan' in rem[0].get_payload(decode=True).decode()
   and (r1.get('moved') or {}).get('reminders', {}).get('reminded') == 'trial_2'
   and 'reminded' not in (r2.get('moved') or {}).get('reminders', {}))
# ── Payment links from the console: a trial, and a new customer whose app is made when they pay ──
_n = {'i': 0}
def fake_api(method, path, payload=None):
    _n['i'] += 1
    if path == '/payment_links':
        return {'id': f'plink_T{_n["i"]}', 'short_url': f'https://rzp.io/l/T{_n["i"]}', 'amount': payload['amount']}
    return {'id': f'order_X{_n["i"]}', 'amount': payload['amount']}
subs._api = fake_api
with app.app_context():
    ops.create_trial('linked', 'admin', 'linked-pass-123', 7, company='Linked Interiors', phone='919844444444',
                     email='owner@linked.example')
t = c.get('/trials/linked').text
ok('trial page: a Payment link card with the plan, WhatsApp number and email filled in', 'Make payment link' in t
   and 'value="919844444444"' in t and 'value="owner@linked.example"' in t)
r = c.post('/payments/link', data={'slug': 'linked', 'plan': '1y', 'name': 'Linked Interiors', 'phone': '919844444444',
                                   'email': 'owner@linked.example'}, follow_redirects=True)
ok('payment link made: Send on WhatsApp (your WhatsApp, message with the link) and Send by email', 'rzp.io/l/T' in r.text
   and 'https://wa.me/919844444444?text=' in r.text and 'Send by email' in r.text and '₹8,999' in r.text)
with app.app_context():
    plink = subs.history(limit=1) and None
    with db.engine.connect() as conn:
        lrow = conn.execute(text("select id, order_id from public.platform_payments where slug='linked'")).first()
before = len(outbox())
c.post(f'/payments/{lrow[0]}/link/email', data={'email': 'owner@linked.example'})
sent = [m for m in outbox()[before:] if m['To'] == 'owner@linked.example']
ok('…emailed from hello@ with the link', len(sent) == 1 and 'rzp.io/l/T' in sent[0].get_content())
ok('the link page offers a proforma invoice', 'Download proforma invoice (PDF)' in c.get(f'/payments/{lrow[0]}/link').text)
pf = c.post(f'/payments/{lrow[0]}/proforma', data={'bill_to': 'Linked Interiors Pvt', 'address': 'Shop 4, Pune'})
import io as _io, re as _re
from pypdf import PdfReader as _PR
pft = _re.sub(r'\s+', ' ', ' '.join(pg.extract_text() for pg in _PR(_io.BytesIO(pf.data)).pages)) if pf.status_code == 200 else ''
ok('proforma invoice PDF: their name, the plan and amount, the payment link, and "not a GST invoice" in plain words',
   pf.mimetype == 'application/pdf' and 'Linked Interiors Pvt' in pft and 'Shop 4, Pune' in pft and '8,999.00' in pft
   and 'rzp.io/l/T' in pft and 'Not a GST invoice' in pft and 'no GST is charged' in pft and 'PF' in pft)
def link_hook(plink_id, pay_id):
    body = _json.dumps({'event': 'payment_link.paid', 'payload': {'payment_link': {'entity': {'id': plink_id}},
                        'payment': {'entity': {'id': pay_id, 'order_id': 'order_from_link'}}}}).encode()
    sig = _hmac.new(b'hook-secret', body, _hl.sha256).hexdigest()
    return c.post('/billing/razorpay-webhook', data=body, headers={'X-Razorpay-Signature': sig}, content_type='application/json')
r = link_hook(lrow[1], 'pay_LINK1')
with app.app_context():
    lc = cust.get('linked')
ok('they pay the link: the plan is added and the trial moves to its own database', r.get_json()['result'].startswith('paid')
   and lc and lc['status'] == 'active' and lc['hosting'] == 'shared')

# A brand-new customer who pays first
r = c.post('/customers', data={'collect': 'link', 'source': 'new', 'slug': 'paidfirst', 'name': 'Paid First Interiors',
                               'plan': '6m', 'phone': '919855555555', 'email': 'boss@paidfirst.example',
                               'admin_username': 'boss'}, follow_redirects=True)
with app.app_context():
    pf = cust.get('paidfirst')
    with db.engine.connect() as conn:
        prow = conn.execute(text("select id, order_id, kind from public.platform_payments where slug='paidfirst'")).first()
ok('new customer, "Send a payment link first": registered as awaiting payment, link page shown, nothing made yet',
   pf['status'] == 'awaiting_payment' and prow[2] == 'new' and 'their app is made when they pay' in r.text
   and 'awaiting payment' in c.get('/customers').text and 'Waiting for payment' in c.get('/customers/paidfirst').text
   and not providers.CustomerDatabases(ADMIN).exists('paidfirst')[0])
before = len(outbox())
r = link_hook(prow[1], 'pay_NEW1')
with app.app_context():
    pf = cust.get('paidfirst')
    with cust.open_customer('paidfirst'):
        st_pf = _pm.load_status(on=_pm.today())
receipt_mails = [m for m in outbox()[before:] if m['To'] == 'boss@paidfirst.example']
ok('they pay: their app is made (shared, 6 months from today) and the receipt is emailed',
   pf['status'] == 'active' and st_pf.plan == '6m' and st_pf.ends_on == _pm.add_length(_pm.today(), '6m')
   and len(receipt_mails) == 1 and 'Payment received' in receipt_mails[0]['Subject'])
t = c.get('/customers/paidfirst').text
ok('…the console shows their login once with the WhatsApp welcome to send (no password by email)',
   'Username:</strong> <span class="secret">boss' in t and 'wa.me/919855555555' in t
   and all('Password' not in m.get_content() for m in receipt_mails if not m.is_multipart())
   and 'shown once' not in c.get('/customers/paidfirst').text)
# A payment received outside Razorpay, recorded by hand; and removing a payment record (a test payment)
p_page = c.get('/payments').text
ok('Payments: a "Record a payment" form listing trials and customers', 'Record payment' in p_page
   and 'value="paidfirst"' in p_page and 'value="linked"' in p_page)
end_before = st_pf.ends_on
before = len(outbox())
r = c.post('/payments/manual', data={'slug': 'paidfirst', 'plan': '6m', 'amount': '4999', 'method': 'UPI',
                                     'reference': 'UPI-123456', 'paid_on': _pm.today().isoformat(), 'add_plan': '1',
                                     'notify': '1'}, follow_redirects=True)
with app.app_context():
    with db.engine.connect() as conn:
        mrow = conn.execute(text("select id, receipt_no, source, paid_by, payment_id, amount_paise, plan_end from "
                                 "public.platform_payments where slug='paidfirst' and source='manual'")).first()
    with cust.open_customer('paidfirst'):
        st_m = _pm.load_status(on=_pm.today())
ok('recorded: a receipt number, UPI and its reference, the plan extended from where it ended (no days lost)',
   mrow is not None and mrow[1].startswith('QR') and mrow[3] == 'UPI' and mrow[4] == 'UPI-123456' and mrow[5] == 499900
   and st_m.ends_on == _pm.add_length(end_before, '6m') and 'Payment recorded' in r.text and 'UPI · UPI-123456' in r.text)
mails = [m for m in outbox()[before:] if m['To'] == 'boss@paidfirst.example']
ok('…the receipt emailed to them', len(mails) == 1 and 'Payment received' in mails[0]['Subject'])
import io as _io2, re as _re2
from pypdf import PdfReader as _PR2
rt = _re2.sub(r'\s+', ' ', ' '.join(pg.extract_text() for pg in _PR2(_io2.BytesIO(c.get(f'/payments/{mrow[0]}/receipt').data)).pages))
ok('…its receipt says how it was paid (not Razorpay)', 'Paid by UPI' in rt and 'Razorpay' not in rt)
bad = c.post('/payments/manual', data={'slug': 'nobody', 'plan': '6m', 'amount': '4999', 'method': 'UPI'}, follow_redirects=True)
ok('a business that doesn\'t exist is refused', 'No trial or customer' in bad.text)
r = c.post(f'/payments/{mrow[0]}/delete', follow_redirects=True)
with app.app_context():
    with db.engine.connect() as conn:
        gone = conn.execute(text('select 1 from public.platform_payments where id = :i'), {'i': mrow[0]}).first() is None
    with cust.open_customer('paidfirst'):
        st_d = _pm.load_status(on=_pm.today())
ok('Remove: the payment record is gone, their plan is unchanged', gone and st_d.ends_on == st_m.ends_on
   and 'Removed payment' in r.text and mrow[1] not in c.get('/payments').text)
ok('daily tick needs the cron secret', c.get('/cron/tick').status_code == 404
   and c.get('/cron/tick', headers={'Authorization': 'Bearer cron-secret'}).status_code == 200)
