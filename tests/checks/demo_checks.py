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
with app.app_context():
    p1 = db.session.get(Project, 1); REAL = [f'{p1.final_total:,.2f}', f'{p1.grand_total:,.2f}']
off_txt = pdftext(c, '/projects/1/pdf')
ok('off: no watermark on PDFs', 'NOT A VALID QUOTATION' not in off_txt and 'DEMO QUOTATION' not in off_txt)
ok('off: PDFs show the real totals', all(v in off_txt for v in REAL))
ok('off: no demo banner', 'exploring the demo' not in c.get('/projects').text)

# ── Demo mode ON ──
app = make(DEMO_MODE='1', CRON_SECRET='s3cret-value', MARKETING_SITE='1'); c = app.test_client()
r = c.get('/login')
ok('login page never shown: redirects to one-click demo', r.status_code == 302 and r.headers['Location'].endswith('/demo'))
r = c.get('/projects/3')
r2 = c.get(r.headers['Location'])
ok('protected page → login → /demo keeps the destination', r.status_code == 302 and r2.status_code == 302
   and '/demo?next=' in r2.headers['Location'])
fresh = app.test_client()
r = fresh.get(fresh.get(fresh.get('/projects/3').headers['Location']).headers['Location'])
ok('…and lands on that page after signing in', r.status_code == 302 and r.headers['Location'].endswith('/projects/3'))
ok('/demo?next= to another site is ignored', app.test_client().get('/demo?next=//evil.example').headers['Location'].endswith('/projects'))
# Closing the browser drops the session cookie; the remember-me cookie keeps them signed in
b = app.test_client(); b.get('/demo')
ok('demo sign-in sets a remember-me cookie', b.get_cookie('remember_token') is not None)
b.delete_cookie('session')
ok('still signed in after the browser is closed', b.get('/projects').status_code == 200)
ok('landing demo button → /demo', 'href="/demo" data-demo>Try the live demo — no signup' in c.get('/').text)
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
    t = pdftext(c, u)
    ok(f'watermark, notice box and footer on {u}', 'DEMO — NOT A VALID QUOTATION' in t
       and 'DEMO QUOTATION — NOT VALID' in t and 'not actual calculated values' in t
       and t.count('amounts are altered sample figures') == len(PdfReader(io.BytesIO(c.get(u).data)).pages))
    ok(f'real totals never appear on {u}', not any(v in t for v in REAL) and 'Rs. 0.00' not in t.split('Amount Paid')[0])
from app.demo import scramble_amount
vals = [1, 99.5, 4500, 18000, 172710, 181800.25]
ok('scrambled amounts are always wrong, deterministic, positive',
   all(scramble_amount(v) != v and scramble_amount(v) == scramble_amount(v) and scramble_amount(v) > 0 for v in vals)
   and scramble_amount(0) == 0)
wa = unquote(c.get('/projects/1/whatsapp').headers['Location'])
ok('WhatsApp summary marked as demo', 'DEMO — NOT A VALID QUOTATION' in wa)

# Anonymous usage counts
import json as _json
from app.models import DemoStat
UA = {'User-Agent': 'Mozilla/5.0 (iPhone) Safari'}
with app.app_context():
    DemoStat.query.delete(); db.session.commit()
v = app.test_client()
v.get('/demo', headers=UA)
v.get('/demo', headers=UA)                                   # same browser again: already signed in
app.test_client().get('/demo', headers={'User-Agent': 'facebookexternalhit/1.1'})   # link preview
v.post('/projects/new', headers=UA, data={'customer_name': 'Count Me', 'mobile': '9000000077', 'discount_type': 'none',
       'discount_value': '0', 'rooms_data': _json.dumps([{'name': 'Hall', 'items': [
           {'name': 'TV Unit', 'length': 8, 'width': 6, 'wood_type': 'Laminates', 'work_type': 'Box Work'}]}])})
v.post('/projects/new', headers=UA, data={'customer_name': '', 'mobile': ''})     # invalid: not saved, not counted
with app.app_context():
    pid = Project.query.order_by(Project.id.desc()).first().id
v.get(f'/projects/{pid}/pdf', headers=UA); v.get(f'/projects/{pid}/pdf/customer', headers=UA)
with app.app_context():
    st = DemoStat.query.one()
    ok(f'demo counts: 1 visitor (no repeat, no bot), 1 quotation, 2 PDFs ({st.starts}, {st.quotations}, {st.pdfs})',
       (st.starts, st.quotations, st.pdfs) == (1, 1, 2))

# Nightly reset
anon = app.test_client()
ok('reset without secret → 404', anon.get('/demo/reset').status_code == 404)
ok('reset with wrong secret → 404', anon.get('/demo/reset', headers={'Authorization': 'Bearer nope'}).status_code == 404)
r = anon.get('/demo/reset', headers={'Authorization': 'Bearer s3cret-value'})
with app.app_context():
    p3 = next(p for p in Project.query.all() if p.customer_name == 'Meera Test')
    ok('reset with secret restores demo data', r.status_code == 200 and p3.stage == 'pending' and p3.payments.count() == 0
       and Project.query.count() == 5)
ok('visitor can sign in again after reset', anon.get('/demo').status_code == 302)
with app.app_context():
    ok('nightly reset keeps the demo counts', DemoStat.query.count() == 1)

# DEMO_MODE on but no CRON_SECRET → reset impossible
app2 = make(DEMO_MODE='1')
ok('no CRON_SECRET → reset disabled', app2.test_client().get('/demo/reset', headers={'Authorization': 'Bearer '}).status_code == 404)


# Before the database update adds demo_stats: the demo works, nothing is counted
from sqlalchemy import text as _text
app3 = make(DEMO_MODE='1')
with app3.app_context():
    db.session.execute(_text('DROP TABLE demo_stats')); db.session.commit()
w = app3.test_client()
r = w.get('/demo', headers=UA)
ok('before the update: /demo still signs in', r.status_code == 302 and w.get('/projects', headers=UA).status_code == 200)
