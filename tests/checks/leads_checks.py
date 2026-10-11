import base64, os
from sqlalchemy import text
from app import create_app, db
from app.models import Lead
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
for k in ['DEMO_MODE', 'LEADS_PASSWORD', 'META_PIXEL_ID']: os.environ.pop(k, None)

os.environ['MARKETING_SITE'] = ''
app = create_app('development'); c = app.test_client()
ok('off on client deployments: form, page and leads all 404',
   c.get('/free-trial').status_code == 404 and c.post('/trial-request').status_code == 404 and c.get('/leads').status_code == 404)

os.environ.update(MARKETING_SITE='1', MARKETING_WHATSAPP='919876543210', META_PIXEL_ID='1234567890')
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = True   # the form must work with CSRF on
c = app.test_client()
J = {'Accept': 'application/json'}
good = {'name': '  Ravi   Kumar ', 'phone': '+91 98765-43210', 'business_type': 'interiors', 'utm_source': 'facebook',
        'utm_campaign': 'oct-launch', 'page': '/'}

t = c.get('/free-trial?utm_source=fb').text
ok('/free-trial page renders the form (no-JS / ad link)', 'data-trial-form' in t and 'value="fb"' in t and 'id="trialDialog"' not in t)

r = c.post('/trial-request', data=good, headers=J); d = r.get_json()
ok('valid request → ok + WhatsApp follow-up link', r.status_code == 200 and d['ok'] and d['name'] == 'Ravi Kumar'
   and d['whatsapp_url'].startswith('https://wa.me/919876543210?text=') and 'Ravi%20Kumar' in d['whatsapp_url']
   and 'Interior%20designer' in d['whatsapp_url'])
with app.app_context():
    l = Lead.query.one()
    ok('stored: name tidied, phone normalised, source kept', l.name == 'Ravi Kumar' and l.phone == '919876543210'
       and l.business_type == 'interiors' and l.source == 'facebook · oct-launch · /')
    raw = db.session.execute(text('select name, phone from leads')).first()
    ok('name and phone encrypted in the database', all(str(v).startswith('enc1:') for v in raw))

bad = c.post('/trial-request', data={'name': 'R', 'phone': '12345', 'business_type': 'other'}, headers=J)
e = bad.get_json()['errors']
ok('validation errors per field', bad.status_code == 400 and set(e) == {'name', 'phone', 'business_other'})
e = c.post('/trial-request', data={'name': 'Ab', 'phone': '9876543211', 'business_type': 'carpenter'}, headers=J).get_json()['errors']
ok('unknown business type rejected', set(e) == {'business_type'})
r = c.post('/trial-request', data={'name': 'Meena', 'phone': '09123456789', 'business_type': 'other',
                                   'business_other': 'Modular kitchens'}, headers=J)
ok('"Others" with text accepted (0-prefixed number ok)', r.get_json()['ok'] and 'Modular%20kitchens' in r.get_json()['whatsapp_url'])
for num, valid in [('98765 43210', True), ('919876543210', True), ('5876543210', False), ('98765432', False), ('+1 415 555 0100', False)]:
    from app.marketing import normalise_phone
    ok(f'phone {num!r} → {"valid" if valid else "invalid"}', bool(normalise_phone(num)) == valid)

c.post('/trial-request', data=good, headers=J)
with app.app_context():
    ok('same number within a day not stored twice', Lead.query.count() == 2)
r = c.post('/trial-request', data=dict(good, phone='9000000001', website='http://spam'), headers=J)
with app.app_context():
    ok('honeypot: bot gets "ok" but nothing is stored', r.get_json()['ok'] and Lead.query.count() == 2)
for i in range(5):
    r = c.post('/trial-request', data=dict(good, phone=f'90000000{10+i}'), headers=J)
ok('rate limit: max 5 per visitor per hour', r.status_code == 429 and 'WhatsApp' in r.get_json()['errors']['form'])

# No-JS form post → thank-you page with the WhatsApp button
app2 = create_app('development'); c2 = app2.test_client()
t = c2.post('/trial-request', data=dict(good, phone='9811111111'), environ_base={'REMOTE_ADDR': '10.9.9.9'}).text
ok('no-JS post → thank-you page with "Skip the wait" WhatsApp button', 'Thanks, Ravi Kumar!' in t and 'Skip the wait' in t
   and 'wa.me/919876543210?text=' in t)
t = c2.post('/trial-request', data={'name': '', 'phone': ''}, environ_base={'REMOTE_ADDR': '10.9.9.8'}).text
ok('no-JS post with errors → form again with messages', 'Please enter your name.' in t and 'data-trial-form' in t)

# Leads page
ok('/leads is 404 until LEADS_PASSWORD is set', c.get('/leads').status_code == 404)
os.environ['LEADS_PASSWORD'] = 'leads-pass-123'
auth = lambda pw: {'Authorization': 'Basic ' + base64.b64encode(f'me:{pw}'.encode()).decode()}
r = c.get('/leads')
ok('/leads asks for a password', r.status_code == 401 and 'Basic' in r.headers.get('WWW-Authenticate', ''))
ok('wrong password refused', c.get('/leads', headers=auth('nope')).status_code == 401)
r = c.get('/leads', headers=auth('leads-pass-123'))
ok('right password → list with decrypted details + WhatsApp links', r.status_code == 200 and 'Ravi Kumar' in r.text
   and '+91 98765 43210' in r.text and 'Modular kitchens' in r.text and 'wa.me/919876543210' in r.text
   and r.headers.get('Cache-Control') == 'no-store' and 'fbevents' not in r.text and 'cookieBanner' not in r.text)
r = c.get('/leads.csv', headers=auth('leads-pass-123'))
ok('CSV download', r.status_code == 200 and r.mimetype == 'text/csv' and 'Ravi Kumar' in r.text and '+919876543210' in r.text)
ok('CSV needs the password too', c.get('/leads.csv').status_code == 401)

# Leads survive the nightly demo reset; old leads expire
from app.seed import seed_demo
from datetime import datetime, timedelta
with app.app_context():
    n = Lead.query.count()
    seed_demo(reset=True)
    ok('nightly demo reset keeps leads', Lead.query.count() == n and n > 0)
    old = Lead.query.first(); old.created_at = datetime.utcnow() - timedelta(days=400); db.session.commit()
c3 = app.test_client()
c3.post('/trial-request', data=dict(good, phone='9822222222'), headers=J, environ_base={'REMOTE_ADDR': '10.1.1.1'})
with app.app_context():
    ok('leads older than 12 months deleted automatically', Lead.query.count() == n)

# Privacy page and cookie notice
t = c.get('/privacy').text
ok('privacy page explains the Meta Pixel and consent', 'id="cookies"' in t and 'Meta Pixel' in t and 'only load if you tap' in t
   and '_fbp' in t and 'trial form' in t and '12 months' in t)
t = c.get('/').text
ok('cookie notice links to the cookies section', 'href="/privacy#cookies"' in t)
