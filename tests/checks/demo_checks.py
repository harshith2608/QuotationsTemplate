import io, os
from urllib.parse import unquote
from pypdf import PdfReader
from app import create_app, db
from app.models import AppSetting, Project, User, Payment
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
def make(**env):
    for k in ['DEMO_MODE', 'CRON_SECRET', 'MARKETING_SITE', 'DEMO_USER']: os.environ.pop(k, None)
    os.environ.update(env)
    app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
    return app
pdftext = lambda c, u: '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages)

# ── Demo mode OFF (client deployments) ──
app = make(); c = app.test_client()
ok('off: /demo and /demo/reset 404', c.get('/demo').status_code == 404 and c.get('/demo/reset').status_code == 404)
c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
ok('off: no watermark on PDFs', 'NOT A VALID QUOTATION' not in pdftext(c, '/projects/1/pdf'))
ok('off: no demo banner', 'exploring the demo' not in c.get('/projects').text)

# ── Demo mode ON ──
app = make(DEMO_MODE='1', CRON_SECRET='s3cret-value', MARKETING_SITE='1'); c = app.test_client()
ok('login page offers one-click demo', 'href="/demo"' in c.get('/login').text)
ok('landing demo button → /demo', 'href="/demo">Try the live demo — no signup' in c.get('/').text)
r = c.get('/demo')
ok('/demo signs in without a password', r.status_code == 302 and r.headers['Location'].endswith('/projects'))
t = c.get('/projects').text
ok('demo banner + get-your-own link', 'exploring the demo' in t and '/landingpage#pricing' in t)

with app.app_context():
    name_before = AppSetting.get('company_name')
r = c.post('/admin/settings', data={'section': 'company', 'company_name': 'Real Business Pvt Ltd'}, follow_redirects=True)
with app.app_context():
    ok('company/branding change blocked', AppSetting.get('company_name') == name_before and 'disabled in the demo' in r.text)
r = c.post('/admin/settings', data={'section': 'appearance', 'theme_primary': '#ff0000'}, follow_redirects=True)
ok('theme save blocked', 'disabled in the demo' in r.text and '#ff0000' not in c.get('/projects').text)
c.post('/admin/payment-settings', data={'upi_id': 'scam@upi'})
c.post('/admin/users/new', data={'username': 'intruder', 'password': 'x'*8, 'confirm_password': 'x'*8, 'role': 'admin'})
c.post('/admin/rates', data={'item_rates_submit': '1', 'rate_acrylic_box_work': '1'})
c.post('/projects/2/delete')
with app.app_context():
    ok('payment settings / users / rates / delete blocked',
       AppSetting.get('upi_id') != 'scam@upi' and not User.query.filter_by(username='intruder').first()
       and db.session.get(Project, 2) is not None)
    pay = Payment.query.first(); pid, payid = pay.project_id, pay.id
c.post(f'/projects/{pid}/payments/{payid}/delete')
r = c.post('/projects/1/access', json={'user_ids': []})
r2 = c.post('/projects/1/payment-link')
with app.app_context():
    ok('delete payment blocked', db.session.get(Payment, payid) is not None)
ok('JSON endpoints answer 403 JSON', r.status_code == 403 and r.is_json and r2.status_code == 403 and r2.is_json)

# Core features still work
r = c.post('/projects/3/stage', data={'stage': 'confirmed'})
c.post('/projects/3/payments/add', data={'amount': '5000', 'note': 'demo'})
with app.app_context():
    p3 = db.session.get(Project, 3)
    ok('stage change + add payment allowed', p3.stage == 'confirmed' and p3.payments.count() == 1)

# Watermark + WhatsApp label
for u in ['/projects/1/pdf', '/projects/1/pdf/customer']:
    ok(f'watermark on {u}', 'DEMO — NOT A VALID QUOTATION' in pdftext(c, u))
wa = unquote(c.get('/projects/1/whatsapp').headers['Location'])
ok('WhatsApp summary marked as demo', 'DEMO — NOT A VALID QUOTATION' in wa)

# Nightly reset
anon = app.test_client()
ok('reset without secret → 404', anon.get('/demo/reset').status_code == 404)
ok('reset with wrong secret → 404', anon.get('/demo/reset', headers={'Authorization': 'Bearer nope'}).status_code == 404)
r = anon.get('/demo/reset', headers={'Authorization': 'Bearer s3cret-value'})
with app.app_context():
    p3 = db.session.query(Project).filter_by(customer_name='Meera Test').first()
    ok('reset with secret restores demo data', r.status_code == 200 and p3.stage == 'pending' and p3.payments.count() == 0
       and Project.query.count() == 5)
ok('visitor can sign in again after reset', anon.get('/demo').status_code == 302)

# DEMO_MODE on but no CRON_SECRET → reset impossible
app2 = make(DEMO_MODE='1')
ok('no CRON_SECRET → reset disabled', app2.test_client().get('/demo/reset', headers={'Authorization': 'Bearer '}).status_code == 404)
