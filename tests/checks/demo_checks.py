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
ok('off: no demo banner or guide', 'exploring the demo' not in c.get('/projects').text and 'See a quotation' not in c.get('/projects').text)
ok('off: /projects/new?try=1 is a normal new quotation', 'My first customer' not in c.get('/projects/new?try=1').text)

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
with app.app_context():
    SAMPLE = int(AppSetting.get('demo_sample_project'))
    ok('the seed marks the sample quotation', db.session.get(Project, SAMPLE).customer_name == 'Priya Example')
# Closing the browser drops the session cookie; the remember-me cookie keeps them signed in
b = app.test_client(); b.get('/demo')
ok('demo sign-in sets a remember-me cookie', b.get_cookie('remember_token') is not None)
b.delete_cookie('session')
ok('still signed in after the browser is closed', b.get('/projects').status_code == 200)
ok('landing demo button → /demo', 'href="/demo" data-demo>Try the live demo — no signup' in c.get('/').text)
r = c.get('/demo')
ok('/demo signs in without a password and opens the sample quotation', r.status_code == 302
   and r.headers['Location'].endswith(f'/projects/{SAMPLE}'))
ok('signed in already: /demo opens the sample again', c.get('/demo').headers['Location'].endswith(f'/projects/{SAMPLE}'))
t = c.get('/projects').text
ok('demo guide on the list: 3 steps, start here, free trial', 'See a quotation' in t and 'Make your own' in t
   and 'Get your PDF' in t and 'Start here' in t and '/free-trial' in t)
t = c.get(f'/projects/{SAMPLE}').text
ok('step 1 on the sample: its PDF and next step', 'class="is-on"' in t and f'/projects/{SAMPLE}/pdf' in t
   and 'See the PDF your customer gets' in t and '/projects/new?try=1' in t)
t = c.get('/projects/new?try=1').text
ok('step 2: Make your own starts from the sample\'s first room with a made-up customer',
   'Change any size' in t and 'Master Bedroom' in t and 'Wardrobe' in t and 'Kitchen' not in t.split('rooms_json')[-1][:4000]
   and 'value="My first customer"' in t and 'value="9000000000"' in t and 'ki-start-cards' not in t)
t = c.get('/projects/new').text
ok('step 2 blank: points to the filled-in bedroom', 'start from a filled-in bedroom' in t)
t = c.get('/projects/3').text
ok('step 3 on their own quotation: their PDF and the free trial', 'See your PDF' in t and '/projects/3/pdf' in t
   and 'Start your free trial' in t)

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
    ok(f'watermark, notice box and footer on every page of {u}', 'DEMO — NOT A VALID QUOTATION' in t
       and 'DEMO QUOTATION — NOT VALID' in t and 'fictional firm' in t
       and t.count('made with QuoteRoom') == len(PdfReader(io.BytesIO(c.get(u).data)).pages))
    ok(f'real totals on {u} (they add up)', all(v in t for v in REAL))
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
v.get(f'/projects/{SAMPLE}/pdf', headers=UA)
v.get('/projects/new?try=1', headers=UA); v.get('/projects/new', headers=UA)
with app.app_context():
    st = DemoStat.query.one()
    ok(f'demo counts: 1 visitor (no repeat, no bot), 1 sample PDF, 1 Make your own, 1 quotation, 2 own PDFs '
       f'({st.starts}, {st.sample_pdfs}, {st.tried}, {st.quotations}, {st.pdfs})',
       (st.starts, st.sample_pdfs, st.tried, st.quotations, st.pdfs) == (1, 1, 1, 1, 2))

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


# Website visitors (marketing deployment): a browser's first visit counts once; bots and app pages don't
appm = make(DEMO_MODE='1', MARKETING_SITE='1')
with appm.app_context():
    DemoStat.query.delete(); db.session.commit()
b1, b2 = appm.test_client(), appm.test_client()
r = b1.get('/', headers=UA)
b1.get('/tutorials', headers=UA); b1.get('/', headers=UA)           # same browser again
b2.get('/privacy', headers=UA)                                        # another browser, another page
appm.test_client().get('/', headers={'User-Agent': 'Googlebot/2.1'})  # a bot
appm.test_client().get('/', headers={'User-Agent': 'facebookexternalhit/1.1'})
with appm.app_context():
    st = DemoStat.query.one()
    ok(f'site visitors: 2 browsers counted once each, no bots ({st.site_visitors}); cookie has no ID',
       st.site_visitors == 2 and 'qr_seen=1' in r.headers.get('Set-Cookie', '') and 'HttpOnly' in r.headers.get('Set-Cookie', ''))
ok('privacy policy explains the site\'s own counting cookie', 'qr_seen' in b1.get('/privacy', headers=UA).text)
with appm.app_context():
    db.session.execute(__import__('sqlalchemy').text('ALTER TABLE demo_stats DROP COLUMN site_visitors')); db.session.commit()
b3 = appm.test_client()
r = b3.get('/', headers=UA)
ok('before the update that adds site visitors: site works, no cookie set (counted later)', r.status_code == 200
   and 'qr_seen' not in r.headers.get('Set-Cookie', ''))


# Before the database update adds demo_stats: the demo works, nothing is counted
from sqlalchemy import text as _text
app3 = make(DEMO_MODE='1')
with app3.app_context():
    db.session.execute(_text('DROP TABLE demo_stats')); db.session.commit()
w = app3.test_client()
r = w.get('/demo', headers=UA)
ok('before the update: /demo still signs in', r.status_code == 302 and w.get('/projects', headers=UA).status_code == 200)
