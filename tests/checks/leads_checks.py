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
good = {'name': '  Ravi   Kumar ', 'company_name': ' Sharma  Interiors ', 'city': ' Hyderabad ', 'email': 'ravi@sharma.example',
        'phone': '+91 98765-43210', 'business_type': 'interiors', 'utm_source': 'facebook',
        'utm_campaign': 'oct-launch', 'page': '/'}

t = c.get('/free-trial?utm_source=fb').text
ok('/free-trial page renders the form (no-JS / ad link)', 'data-trial-form' in t and 'value="fb"' in t and 'id="trialDialog"' not in t)

r = c.post('/trial-request', data=good, headers=J); d = r.get_json()
ok('valid request → ok, no WhatsApp follow-up link', r.status_code == 200 and d['ok'] and d['name'] == 'Ravi Kumar'
   and 'whatsapp_url' not in d)
ok('self-serve off (default): no "set up now" link', d.get('setup_url') is None)
with app.app_context():
    l = Lead.query.one()
    ok('stored: name tidied, phone normalised, source kept', l.name == 'Ravi Kumar' and l.phone == '919876543210'
       and l.company_name == 'Sharma Interiors' and l.city == 'Hyderabad' and l.email == 'ravi@sharma.example'
       and l.business_type == 'interiors' and l.source == 'facebook · oct-launch · /')
    raw = db.session.execute(text('select name, phone, company_name, city, email from leads')).first()
    ok('name, phone, company, city and email encrypted in the database', all(str(v).startswith('enc1:') for v in raw))

bad = c.post('/trial-request', data={'name': 'R', 'phone': '12345', 'business_type': 'other'}, headers=J)
e = bad.get_json()['errors']
ok('validation errors per field (WhatsApp number and email are required)', bad.status_code == 400
   and set(e) == {'name', 'company_name', 'city', 'phone', 'email', 'business_other'}
   and e['email'] == 'Please enter your email address.' and 'WhatsApp' in e['phone'])
e = c.post('/trial-request', data={'name': 'Ab', 'company_name': 'Ab Co', 'city': 'Pune', 'phone': '9876543211', 'email': 'ab@abco.example',
                                   'business_type': 'carpenter'}, headers=J).get_json()['errors']
ok('unknown business type rejected', set(e) == {'business_type'})
e = c.post('/trial-request', data=dict(good, phone='9876543212', email='not-an-email'), headers=J).get_json()['errors']
ok('a mistyped email is caught', set(e) == {'email'})
r = c.post('/trial-request', data={'name': 'Meena', 'company_name': 'Meena Kitchens', 'city': 'Chennai', 'phone': '09123456789', 'business_type': 'other',
                                   'business_other': 'Modular kitchens', 'email': 'meena@kitchens.example'}, headers=J)
ok('"Others" with text accepted (0-prefixed number ok)', r.get_json()['ok'])
e = c.post('/trial-request', data=dict(good, phone='9876543213', email=''), headers=J).get_json()['errors']
ok('no email → asked for it', set(e) == {'email'})
for num, valid in [('98765 43210', True), ('919876543210', True), ('5876543210', False), ('98765432', False), ('+1 415 555 0100', False)]:
    from app.marketing import normalise_phone
    ok(f'phone {num!r} → {"valid" if valid else "invalid"}', bool(normalise_phone(num)) == valid)

c.post('/trial-request', data=dict(good, name='Second Try', company_name='New Name Interiors', city='Mysuru',
                                   email='second@newname.example'), headers=J)
with app.app_context():
    _same = [l for l in Lead.query.all() if l.phone == normalise_phone(good['phone'])]
    ok('same number within a day not stored twice, but the new details replace the old (the set-up page greets them)',
       Lead.query.count() == 2 and len(_same) == 1 and _same[0].name == 'Second Try'
       and _same[0].company_name == 'New Name Interiors' and _same[0].city == 'Mysuru'
       and _same[0].email == 'second@newname.example')
r = c.post('/trial-request', data=dict(good, phone='9000000001', website='http://spam'), headers=J)
with app.app_context():
    ok('honeypot: bot gets "ok" but nothing is stored', r.get_json()['ok'] and Lead.query.count() == 2)
for i in range(5):
    r = c.post('/trial-request', data=dict(good, phone=f'90000000{10+i}'), headers=J)
ok('rate limit: max 5 per visitor per hour', r.status_code == 429 and 'try again later' in r.get_json()['errors']['form'])

# No-JS form post → thank-you page with the WhatsApp button
app2 = create_app('development'); c2 = app2.test_client()
t = c2.post('/trial-request', data=dict(good, phone='9811111111'), environ_base={'REMOTE_ADDR': '10.9.9.9'}).text
ok('no-JS post → thank-you page with the live demo button, no WhatsApp button', 'Thanks, Ravi Kumar!' in t
   and 'Skip the wait' not in t and 'data-trial-wa' not in t and 'Try the live demo' in t and 'data-demo' in t)
t = c2.get('/').text
ok('pop-up form asks for the company name, city and email, no WhatsApp follow-up', 'name="company_name"' in t
   and 'name="city"' in t and 'name="email"' in t and 'Skip the wait' not in t)
ok('every trade it\'s for counts as a Lead; Others → LeadOther', "if (btype && btype !== 'other') track('Lead'" in t and "track('LeadOther')" in t)
ok('Lead event sends a value and INR currency (Meta asks for both)', 'leadValue: 1000.0' in t
   and "track('Lead', true, { value: T.leadValue, currency: 'INR', content_category: btype })" in t)
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
   and '+91 98765 43210' in r.text and 'Modular kitchens' in r.text and 'Sharma Interiors' in r.text and 'wa.me/919876543210' in r.text
   and r.headers.get('Cache-Control') == 'no-store' and 'fbevents' not in r.text and 'cookieBanner' not in r.text)
r = c.get('/leads.csv', headers=auth('leads-pass-123'))
ok('CSV download', r.status_code == 200 and r.mimetype == 'text/csv' and 'Ravi Kumar' in r.text and '+919876543210' in r.text
   and 'Sharma Interiors' in r.text)
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


# Right after a deploy, before the database update adds leads.company_name: the form still works
import app.marketing as _mk
with app.app_context():
    for col in ('company_name', 'city', 'email'):
        db.session.execute(text(f'ALTER TABLE leads DROP COLUMN {col}'))
    db.session.commit()
_mk._lead_columns.clear()
c4 = app.test_client()
r = c4.post('/trial-request', data=dict(good, phone='9833333333'), headers=J, environ_base={'REMOTE_ADDR': '10.2.2.2'})
with app.app_context():
    stored = any(l.phone == '919833333333' for l in Lead.query.all())
ok('before the update: request accepted and stored (without the company, city and email)', r.status_code == 200 and r.get_json()['ok'] and stored)
r = c4.get('/leads', headers=auth('leads-pass-123'))
ok('before the update: /leads and CSV still work', r.status_code == 200 and 'Ravi Kumar' in r.text
   and c4.get('/leads.csv', headers=auth('leads-pass-123')).status_code == 200)


# Self-serve trials on: interior designers and furniture works get a signed "set up my app now" link (no personal data)
os.environ.update(AUTO_TRIALS='1', SIGNUP_URL='https://ops.quote-room.test', SIGNUP_SECRET='signup-secret')
from app import signup as _su
c5 = create_app('development').test_client()
r = c5.post('/trial-request', data=dict(good, phone='9811100044', company_name='Kiran Interiors'), headers=J,
            environ_base={'REMOTE_ADDR': '10.9.0.1'}); d = r.get_json()
ok('self-serve on: an interior designer gets "set up my app now" (a signed link with only the request id)',
   d['ok'] and d['setup_url'] and d['setup_url'].startswith('https://ops.quote-room.test/start?t=')
   and '9811100044' not in d['setup_url'] and 'Kiran' not in d['setup_url']
   and _su.read_token(d['setup_url'].split('t=', 1)[1].replace('%2E', '.')) is not None)
r = c5.post('/trial-request', data=dict(good, phone='9811100045', business_type='other', business_other='Tiles'), headers=J,
            environ_base={'REMOTE_ADDR': '10.9.0.2'})
ok('…"Others" set up their own app too (no waiting for us)', r.get_json()['ok'] and r.get_json()['setup_url'])
r = c5.post('/trial-request', data=dict(good, phone='9811100051', business_type='upvc'), headers=J,
            environ_base={'REMOTE_ADDR': '10.9.0.8'})
ok('…uPVC, glass and kitchen firms set up their own app too', r.get_json()['ok'] and r.get_json()['setup_url']
   and all(f'value="{v}"' in c5.get('/free-trial').text for v in ('kitchens', 'upvc', 'glass'))
   and 'uPVC windows &amp; doors' in c5.get('/free-trial').text)
t = c5.post('/trial-request', data=dict(good, phone='9811100046'), environ_base={'REMOTE_ADDR': '10.9.0.3'}).text
ok('…and the page without JavaScript shows the button too, with no demo button beside it (one clear next step)',
   'Set up my app now' in t and '/start?t=' in t and '<div data-demo-wait hidden>' in t)

# With email set up, the link goes to their email instead (proves the address is theirs)
import glob, tempfile, email as _email
box = tempfile.mkdtemp()
os.environ['MAIL_OUTBOX_DIR'] = box
r = c5.post('/trial-request', data=dict(good, phone='9811100047', email='kiran@kiraninteriors.example'), headers=J,
            environ_base={'REMOTE_ADDR': '10.9.0.4'}); d = r.get_json()
from email import policy as _policy
mails = [_email.message_from_bytes(open(f, 'rb').read(), policy=_policy.default) for f in sorted(glob.glob(box + '/*.eml'))]
ok('email set up: the set-up link is shown straight away, and a copy emailed (the page says where)', d['ok']
   and d['setup_url'] and d['setup_url'].startswith('https://ops.quote-room.test/start?t=')
   and d['emailed_to'] == 'ki***@kiraninteriors.example' and len(mails) == 1
   and mails[0]['To'] == 'kiran@kiraninteriors.example' and mails[0]['Subject'] == 'Set up your QuoteRoom app'
   and 'https://ops.quote-room.test/start?t=' in mails[0].get_body(('plain',)).get_content()
   and '/e/o/L' in mails[0].get_body(('html',)).get_content())        # the open image (app/emails.py)
ok('…with a hidden copy to hello@ (app emails don\'t show in the mailbox\'s Sent folder)',
   mails[0]['Bcc'] == 'hello@quote-room.co.in')
t = c5.post('/trial-request', data=dict(good, phone='9811100048', email='x@kiraninteriors.example'),
            environ_base={'REMOTE_ADDR': '10.9.0.5'}).text
ok('…and the page without JavaScript: Set up my app now, and the email copy', 'Set up my app now' in t
   and 'also emailed this link to' in t and 'x***@kiraninteriors.example' in t and 'Check your email' not in t)
# Buying a plan on the website: the plan buttons open the same form, then straight on to set up and pay (any business,
# and the link is shown, not emailed: Razorpay checks the payer)
lp = c5.get('/').text
ok('plan buttons: the same form for that plan (no WhatsApp)', 'data-plan="1m"' in lp and 'data-plan="1y"' in lp
   and '/free-trial?plan=1y' in lp and 'interested%20in%20the' not in lp and 'Continue to payment' in lp)
t = c5.get('/free-trial?plan=1y').text
ok('/free-trial?plan=1y (no JavaScript): the 12-month plan and "Continue to payment"', '12-month plan · ₹5,999' in t
   and 'name="plan" value="1y"' in t and 'Continue to payment' in t)
r = c5.post('/trial-request', data=dict(good, phone='9811100049', business_type='other', business_other='Kitchens', plan='1y'),
            headers=J, environ_base={'REMOTE_ADDR': '10.9.0.6'}); d = r.get_json()
ok('…submitted: on to /start for that plan (even "Others"; shown, not emailed)', d['ok'] and d['pay_url']
   and d['pay_url'].startswith('https://ops.quote-room.test/start?t=') and d['pay_url'].endswith('&plan=1y'))
r = c5.post('/trial-request', data=dict(good, phone='9811100050', plan='1m'), environ_base={'REMOTE_ADDR': '10.9.0.7'})
ok('…without JavaScript: redirected there (the monthly plan too)', r.status_code == 302
   and r.headers['Location'].endswith('&plan=1m'))
with app.app_context():
    ok('…the request notes the plan they\'re buying', any('buying 1m' in (l.source or '') for l in Lead.query.all()))
ok('pricing: monthly ₹599 (a month at a time, or autopay), 12 months ₹5,999 with 2 months free; no 6-month plan',
   '₹599' in lp and '₹5,999' in lp and '2 months free' in lp and 'one month' in lp and 'autopay' in lp.lower()
   and '₹4,999' not in lp)
# Prices from the console's Pricing (a copy in the website's own database): no code change
import json as _json
from app.models import AppSetting as _AS
from app import pricing as _pr
with app.app_context():
    _AS.set(_pr.KEY, _json.dumps({'plans': {'1m': {'price': 699, 'on': False}, '6m': {'price': 2999, 'on': True},
                                            '1y': {'price': 4999, 'on': True}}, 'addon': 149}))
    db.session.commit()
lp2 = c5.get('/').text
t2 = c5.get('/free-trial?plan=1m').text
r = c5.post('/trial-request', data=dict(good, phone='9811100060', plan='1m'), headers=J, environ_base={'REMOTE_ADDR': '10.9.0.9'})
ok('the console\'s prices: 6 months ₹2,999 and 12 months ₹4,999 shown, monthly switched off (not shown, not buyable)',
   '₹2,999' in lp2 and '₹4,999' in lp2 and 'data-plan="6m"' in lp2 and 'data-plan="1m"' not in lp2
   and '₹5,999' not in lp2 and 'Monthly plan · ' not in t2 and not (r.get_json() or {}).get('pay_url'))
with app.app_context():
    ok('…and what they work out to (without a monthly plan, no "Save" or "months free")',
       _pr.per_month('6m') == 500 and _pr.prices()['ai40'] == 149 and 'Save ₹' not in lp2 and 'months free' not in lp2)
    _AS.set(_pr.KEY, ''); db.session.commit()
ok('…and back to the defaults when nothing is saved', '₹5,999' in c5.get('/').text)
data, errs = _pr.validate({'price_1m': '599', 'on_1m': '1', 'price_1y': '5,999', 'on_1y': '1', 'addon': '99'})
ok('Pricing form: "5,999" is read as 5999; 12 months is 2 months free against ₹599', not errs and data['plans']['1y']['price'] == 5999
   and _pr.badge('1y', data) == '2 months free' and _pr.saving('1y', data) == 1189)
_, errs = _pr.validate({'price_1y': '', 'on_1y': '1', 'addon': '99'})
_, errs2 = _pr.validate({'price_1m_ai': '749', 'on_1m_ai': '1', 'addon': '99'})
ok('…a plan switched on needs a price, and one plan without AI must stay on', any('12 months' in e for e in errs)
   and any('at least one plan without AI' in e for e in errs2))
os.environ.pop('MAIL_OUTBOX_DIR', None)
lp = c5.get('/').text
ok('"Book a call with us": a band before the pricing and a line under it, to the console\'s booking page',
   lp.count('href="https://ops.quote-room.test/call"') >= 2 and 'Rather see it with someone?' in lp
   and lp.index('Rather see it with someone?') < lp.index('id="pricing"') and 'Not sure which plan?' in lp)
for k in ('AUTO_TRIALS', 'SIGNUP_URL', 'SIGNUP_SECRET'):
    os.environ.pop(k, None)
lp = create_app('development').test_client().get('/').text
ok('self-serve off: the plan buttons still open WhatsApp', 'interested%20in%20the' in lp and 'data-plan=' not in lp)

ok('…and none without the console link (SIGNUP_URL)', 'Rather see it with someone?' not in create_app('development').test_client().get('/').text)

# ── Telegram: a "📝 Trial request" alert for each new request (a repeat from the same number: none) ──
from app import notify as _nt
_tg = []
_nt.send = lambda title, lines=(), phone='', console_path='', chat_id=None: _tg.append((title, list(lines), phone, console_path)) or True
_ct = create_app('development').test_client()
_ct.post('/trial-request', data=dict(good, phone='9811100088', company_name='Alert Studio'), headers=J,
         environ_base={'REMOTE_ADDR': '10.9.1.1'})
_ct.post('/trial-request', data=dict(good, phone='9811100088', company_name='Alert Studio'), headers=J,
         environ_base={'REMOTE_ADDR': '10.9.1.2'})
ok('a new trial request alerts you on Telegram (app not set up yet, phone, console link); a repeat doesn\'t',
   len(_tg) == 1 and _tg[0][0] == '📝 Trial request: Alert Studio' and 'App not set up yet' in _tg[0][1][0]
   and _tg[0][2] == '919811100088' and _tg[0][3] == '/#newRequests')
