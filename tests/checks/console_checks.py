import os, re, tempfile, time
from datetime import datetime
from urllib.parse import unquote
from sqlalchemy import create_engine, text
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash, check_password_hash

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'
LEADS_KEY = Fernet.generate_key().decode()
leads_db = os.path.join(os.environ.get('TEST_OUTPUT_DIR') or tempfile.mkdtemp(), 'leads.db')
os.environ.update(CONSOLE_MODE='1', TENANT_BASE_DOMAIN='quote-room.test',
                  CONSOLE_PASSWORD_HASH=generate_password_hash('console-pass-123', method='pbkdf2:sha256'),
                  CONSOLE_TOTP_SECRET=SECRET, LEADS_DATABASE_URL=f'sqlite:///{leads_db}', LEADS_DATA_ENCRYPTION_KEY=LEADS_KEY)
for k in ['TENANT_MODE', 'DEMO_MODE', 'MARKETING_SITE']: os.environ.pop(k, None)

from app import create_app, db, crypto, tenancy
from app.console import totp_code, totp_match
from app.models import Lead, User

# A trial request in the (separate) marketing database, encrypted with ITS key
le = create_engine(f'sqlite:///{leads_db}')
Lead.__table__.create(le, checkfirst=True)
with crypto.using_key(LEADS_KEY), le.begin() as c:
    c.execute(Lead.__table__.insert(), [dict(name='Ravi Kumar', phone='919876543210', business_type='other',
              business_other='Ravi Modular Kitchens', source='facebook', created_at=datetime.utcnow())])

app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client()
now_code = lambda offset=0: totp_code(SECRET, int(time.time() // 30) + offset)

# TOTP itself: RFC 6238 test vector (SHA-1, T=59 → 94287082 → last 6 digits)
import base64
rfc_secret = base64.b32encode(b'12345678901234567890').decode()
ok('TOTP matches the RFC 6238 test vector', totp_code(rfc_secret, 59 // 30) == '287082')
ok('TOTP accepts ±30 s, rejects older codes', totp_match(SECRET, now_code(-1)) is not None and totp_match(SECRET, now_code(-3)) is None)

ok('console serves its icon files', c.get('/static/brand/quoteroom-icon.svg').status_code == 200
   and 'quoteroom-icon.svg' in c.get('/login').text)
ok('console serves nothing else (app pages 404)', c.get('/projects').status_code == 404 and c.get('/admin/dashboard').status_code == 404
   and c.get('/free-trial').status_code == 404)
ok('signed out → dashboard redirects to sign-in', c.get('/').headers.get('Location', '').endswith('/login'))
r = c.post('/login', data={'password': 'console-pass-123', 'code': '000000'})
ok('right password + wrong code refused', 'Wrong password or code' in r.text)
r = c.post('/login', data={'password': 'wrong', 'code': now_code()})
ok('wrong password + right code refused', 'Wrong password or code' in r.text)
code = now_code()
r = c.post('/login', data={'password': 'console-pass-123', 'code': code})
ok('password + code → signed in', r.status_code == 302 and r.headers['Location'].endswith('/'))
ok('responses are no-store / noindex / no framing', c.get('/').headers.get('Cache-Control') == 'no-store'
   and c.get('/').headers.get('X-Frame-Options') == 'DENY')
c2 = app.test_client()
r = c2.post('/login', data={'password': 'console-pass-123', 'code': code})
ok('the same code can\'t be used twice', 'already used' in r.text)

# Dashboard shows the request; create a trial from it
t = c.get('/').text
ok('dashboard shows new trial request with suggested address', 'Ravi Kumar' in t and 'Ravi Modular Kitchens' in t
   and 'value="ravi-modular"' in t)
with crypto.using_key(LEADS_KEY), le.connect() as conn:
    lead_id = conn.execute(Lead.__table__.select()).first().id
r = c.post('/trials', data={'slug': 'ravi-modular', 'days': '7', 'lead_id': lead_id, 'name': 'Ravi Kumar', 'phone': '919876543210'})
m = re.search(r'Password:</strong> <span class="secret">([^<]+)</span>', r.text)
password = m.group(1) if m else ''
wa = re.search(r'href="(https://wa\.me/919876543210\?text=[^"]+)"', r.text)
ok('create trial → credentials shown once + WhatsApp message to the lead', r.status_code == 200 and password
   and wa and 'https://ravi-modular.quote-room.test' in unquote(wa.group(1)) and password in unquote(wa.group(1)))
with app.app_context():
    from app import ops
    trial = [x for x in ops.list_trials() if x['slug'] == 'ravi-modular']
    ok('trial exists and is active with a 7-day plan', trial and trial[0]['status'] == 'active'
       and trial[0]['status_obj'].days_left == 7)
    with tenancy.tenant_context('ravi-modular'):
        u = User.query.filter_by(username='admin').first()
        ok('generated password works for the trial admin', u and check_password_hash(u.password_hash, password))
t = c.get('/').text
ok('request no longer "new"; shown as handled → trial', 'Not interested' not in t and 'trial <a href="/trials/ravi-modular">' in t)
ok('running trial shows "running"', '>running<' in t)

r = c.post('/trials', data={'slug': 'ravi-modular', 'days': '7'}, follow_redirects=True)
ok('duplicate address refused with a message', 'already exists' in r.text)
r = c.post('/trials', data={'slug': 'www', 'days': '7'}, follow_redirects=True)
ok('reserved address refused', 'reserved' in r.text)
r = c.post('/trials', data={'slug': 'ops', 'days': '7'}, follow_redirects=True)
ok('"ops" (the console address) is reserved', 'reserved' in r.text)

# Extend, reset password, unlock, delete
r = c.post('/trials/ravi-modular/extend', data={'length': '7d'}, follow_redirects=True)
ok('extend +7 days', '14 days left' in r.text)
ok('extend only allows the offered lengths', c.post('/trials/ravi-modular/extend', data={'length': '999d'}).status_code == 400)
r = c.post('/trials/ravi-modular/reset-password', data={})
m = re.search(r'Password:</strong> <span class="secret">([^<]+)</span>', r.text)
with app.app_context(), tenancy.tenant_context('ravi-modular'):
    u = User.query.filter_by(username='admin').first()
    ok('reset password → new one works, old one doesn\'t', m and check_password_hash(u.password_hash, m.group(1))
       and not check_password_hash(u.password_hash, password))
with app.app_context(), tenancy.tenant_context('ravi-modular'):
    from app.models import AppSetting
    from app import branding
    AppSetting.set('company_name', 'Ravi Kitchens'); db.session.commit()
    ok('company name locked after first save', 'name' in branding.locked_fields())
c.post('/trials/ravi-modular/unlock', data={'fields': ['name']})
with app.app_context(), tenancy.tenant_context('ravi-modular'):
    ok('unlock button unlocks it for one change', 'name' not in branding.locked_fields())
t = c.get('/trials/ravi-modular').text
ok('trial page shows history of console actions', 'extend' in t and 'reset password' in t and 'unlock' in t)

r = c.post('/trials/ravi-modular/delete', data={'confirm': 'wrong'}, follow_redirects=True)
with app.app_context():
    ok('delete needs the name typed exactly', 'exactly to confirm the deletion' in r.text
       and any(x['slug'] == 'ravi-modular' for x in ops.list_trials()))
r = c.post('/trials/ravi-modular/delete', data={'confirm': 'ravi-modular'}, follow_redirects=True)
with app.app_context(), db.engine.connect() as conn:
    gone = conn.execute(text("select count(*) from information_schema.schemata where schema_name='t_ravi_modular'")).scalar() == 0
ok('delete drops the trial and its data', 'Deleted trial' in r.text and gone)

# Leads: dismiss and undo
with crypto.using_key(LEADS_KEY), le.begin() as conn:
    conn.execute(Lead.__table__.insert(), [dict(name='Spam Person', phone='919000000001', business_type='interiors',
                                                created_at=datetime.utcnow())])
    spam_id = conn.execute(text("select max(id) from leads")).scalar()
c.post(f'/leads/{spam_id}/dismiss')
t = c.get('/').text
ok('"Not interested" moves a request to handled, with Undo', 'not interested' in t and f'/leads/{spam_id}/restore' in t)
c.post(f'/leads/{spam_id}/restore')
ok('Undo brings it back', 'Spam Person' in c.get('/').text.split('Handled requests')[0])

t = c.get('/activity').text
ok('activity log lists sign-ins and actions', all(w in t for w in ['login failed', 'trial create', 'trial delete', 'lead dismiss']))

# Changing the password signs every session out
os.environ['CONSOLE_PASSWORD_HASH'] = generate_password_hash('a-new-console-pass', method='pbkdf2:sha256')
ok('changing the password signs out existing sessions', c.get('/').headers.get('Location', '').endswith('/login'))

# Lockout after repeated failures
lock = app.test_client()
for _ in range(6):
    r = lock.post('/login', data={'password': 'nope', 'code': '123456'})
ok('sign-in locks after 5 failures in 15 minutes', 'Sign-in is locked' in r.text)

# CSRF is enforced on the real config
app_csrf = create_app('development'); cc = app_csrf.test_client()
ok('forms need a CSRF token', cc.post('/login', data={'password': 'x', 'code': '1'}).status_code == 400)
# Over HTTPS Flask-WTF also checks the Referer, so the console must not suppress it on its own pages
hs = app_csrf.test_client()
r = hs.get('/login', base_url='https://ops.quote-room.test')
ok('Referrer-Policy keeps same-origin referrers (needed for HTTPS form posts)', r.headers.get('Referrer-Policy') == 'same-origin')
tok = re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)
r = hs.post('/login', base_url='https://ops.quote-room.test', data={'csrf_token': tok, 'password': 'x', 'code': '123456'},
            headers={'Referer': 'https://ops.quote-room.test/login'})
ok('HTTPS sign-in form post passes CSRF (with same-origin Referer)', r.status_code == 200 and ('Wrong password or code' in r.text or 'Sign-in is locked' in r.text))

# Console needs its secrets in production
import subprocess, sys
code_ = ("import os; os.environ.update(FLASK_ENV='production', SECRET_KEY='x', CONSOLE_MODE='1', "
         "DATA_ENCRYPTION_KEY='" + Fernet.generate_key().decode() + "'); os.environ.pop('CONSOLE_TOTP_SECRET', None); "
         "from app import create_app; create_app('production')")
r = subprocess.run([sys.executable, '-c', code_], capture_output=True, text=True, env=dict(os.environ))
ok('production console refuses to start without its 2FA secret', r.returncode != 0 and 'CONSOLE_TOTP_SECRET' in r.stderr)

# Clean up the public console tables so other suites start from a clean trials database
with app.app_context(), db.engine.begin() as conn:
    for tname in ('console_audit', 'console_state', 'console_lead_links'):
        conn.execute(text(f'DROP TABLE IF EXISTS public.{tname}'))
    conn.execute(text('DELETE FROM public.tenants'))
