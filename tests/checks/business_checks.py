"""What kind of business it is (app/business.py) and the words that follow: an interiors business (and one that never
said) sees what it always saw; a uPVC or construction business sees its own examples, suggestions and section word,
no interiors tagline, a neutral thank-you, and AI helpers told what it does. The trial form offers every kind."""
import json
from app import create_app, db, business, boq
from app.models import AppSetting, BoqItem, Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client()
c.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
c.post('/welcome/exit')


def kind(value):
    with app.app_context():
        business.set_kind(value) if value else AppSetting.set(business.KEY, '')
        db.session.commit()


# ── Never said: interiors, as before ──
with app.app_context():
    ok('a business that never said is interiors', business.kind() == 'interiors' and business.is_interiors())
new = c.get('/projects/new').text
ok('interiors: the tagline, "e.g. Wardrobe", Rooms, the interiors suggestions',
   'Interior Design &amp; Furnishing Solutions' in new and 'placeholder="e.g. Wardrobe"' in new
   and 'Rooms &amp; Items' in new and '<option value="Wardrobe">' in new)

# ── uPVC ──
kind('upvc')
with app.app_context():
    boq.set_enabled(True, starter=False)
    db.session.add(BoqItem(name='Sliding Window (2 track)', unit='sqft', rate=550)); db.session.commit()
    p = business.profile()
ok('uPVC: its own examples, room by room', p['kind'] == 'upvc' and p['section'] == 'Room'
   and p['item_example'] == 'Sliding Window (2 track)' and not p['interiors'])
new = c.get('/projects/new').text
ok('…no interiors tagline in the footer', 'Interior Design' not in new)
ok('…its own item example and suggestions (its lines, not wardrobes)', 'placeholder="e.g. Sliding Window (2 track)"' in new
   and '<option value="Wardrobe">' not in new and '<option value="Sliding Window (2 track)">' in new)
ok('…the section words for the form', '"section": "Room"' in new and '"example": "Hall"' in new)
ok('…login page without "Interior Design"', 'Interior Design' not in app.test_client().get('/login').text)
st = c.get('/admin/settings?tab=company').text
ok('…no interiors tagline as the Settings placeholder', 'Interior Design &amp; Furnishing' not in st)
setup = c.get('/admin/setup').text
ok('…Setup guide examples are its own', 'wardrobe, false ceiling' not in setup and 'sliding window' in setup.lower())

from app import ai_tools, pdf_utils
with app.test_request_context():
    draft = ai_tools._for_business(ai_tools.DRAFT_PROMPT, ai_tools.DRAFT_OTHER)
    check = ai_tools._for_business(ai_tools.CHECK_PROMPT, ai_tools.CHECK_OTHER)
    thanks = pdf_utils._thank_you_text()
ok('…AI helpers told what it does (no interior designer, no hob and chimney)', "interior designer" not in draft
   and 'upvc windows' in draft.lower() and 'hob' not in check and 'mosquito mesh' in check)
ok('…a neutral thank-you on the PDF', 'working with you' in thanks and 'transforming' not in thanks)

save = c.post('/projects/new', data={'customer_name': 'Window Home', 'mobile': '9000000777', 'discount_type': 'none',
                                     'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Hall', 'items': [
                                         {'name': 'Sliding Window (2 track)', 'type': 'boq', 'quantity': 24,
                                          'unit': 'sqft', 'unit_price': 550}]}])})
with app.app_context():
    pid = Project.query.order_by(Project.id.desc()).first().id
view = c.get(f'/projects/{pid}').text
ok('…the quotation page: Room by room, no "Summary by material" on a by-item invoice',
   'Room-by-Room Breakdown' in view and 'Summary by material' not in view)

# ── Construction: Areas ──
kind('construction')
new = c.get('/projects/new').text
ok('construction: Areas, its own section suggestions', 'Areas &amp; Items' in new and 'Add First Area' in new
   and '<option value="Ground Floor">' in new and '<option value="Master Bedroom">' not in new)
with app.test_request_context():
    check = ai_tools._for_business(ai_tools.CHECK_PROMPT, ai_tools.CHECK_OTHER)
ok('…the AI check: its own often-missed things', 'waterproofing' in check)

# ── Back to interiors ──
kind('interiors')
new = c.get('/projects/new').text
ok('interiors chosen: as before', 'Interior Design &amp; Furnishing Solutions' in new and 'placeholder="e.g. Wardrobe"' in new)
kind('kitchens')
with app.app_context():
    ok('an old kind (modular kitchens) is interiors', business.kind() == 'interiors')

# ── The trial form ──
from app import marketing, signup
ok('the trial form offers every kind, and each can set up its own app',
   {'tiles', 'construction', 'painting', 'ceiling', 'fabrication', 'curtains', 'turnkey'} <= set(marketing.BUSINESS_TYPES)
   and set(marketing.BUSINESS_TYPES) - {'other'} == signup.ELIGIBLE)

# ── Kinds of business offered (the console's Features → Kinds of business) ──
with app.app_context():
    ok('not saved yet: the kinds offered before (interiors, furniture, uPVC, glass, something else)',
       business.kinds_offered() == ['interiors', 'furniture', 'upvc', 'glass', 'other'])
    AppSetting.set(business.KINDS_KEY, json.dumps(['tiles', 'painting'])); db.session.commit()
with app.app_context():
    ok('saved: those kinds, with interiors and something else always',
       business.kinds_offered() == ['interiors', 'tiles', 'painting', 'other'])
    ok('…the trial form\'s types follow (modular kitchens is interiors)', business.offered('tiles')
       and business.offered('kitchens') and not business.offered('upvc') and not business.offered('construction'))
with app.test_request_context():
    types = [k for k, _ in marketing._context()['business_types']]
ok('…the website\'s trial form shows only those', types == ['interiors', 'kitchens', 'tiles', 'painting', 'other'])
c.post('/welcome/restart')
kp = c.get('/welcome/work').text
ok('…the guided setup offers only those', 'value="tiles"' in kp and 'value="painting"' in kp and 'value="upvc"' not in kp
   and 'value="interiors"' in kp)
kind('upvc')
with app.app_context():
    from app import welcome as W
    s = W.state(); s['kind'] = 'upvc'; W._store(s); db.session.commit()
ok('…a business that chose a kind since switched off still sees it', 'value="upvc"' in c.get('/welcome/work').text)

from app import seed
with app.app_context():
    seed._clear_all_tables()
    ok('the website keeps the choice on the demo\'s nightly reset', AppSetting.get(business.KINDS_KEY) is not None
       and AppSetting.get(business.KEY) is None)

# ── A QA copy (QA_MODE=1): behind the QA key, marked on every page, kept out of search engines; the live app isn't ──
import os
live = app.test_client().get('/login')
os.environ['QA_MODE'] = '1'
closed = create_app('development').test_client().get('/login')
ok('QA copy with no key set: closed', closed.status_code == 503 and 'QA_ACCESS_KEY is not set' in closed.text
   and 'Username' not in closed.text)
os.environ.update(QA_ACCESS_KEY='qa-test-key-123', QA_COOKIE_DOMAIN='qa.example.test')
qapp = create_app('development')
qc = qapp.test_client()
r = qc.get('/login', base_url='https://test1.qa.example.test')
ok('…every page asks for the QA key first, nothing else shown', r.status_code == 401 and 'Enter the QA key' in r.text
   and 'Username' not in r.text and r.headers.get('X-Robots-Tag') == 'noindex, nofollow')
r = qc.post('/qa-access?next=/login', data={'key': 'wrong'}, base_url='https://test1.qa.example.test')
ok('…a wrong key: still the key page', r.status_code == 401 and 'not right' in r.text)
r = qc.post('/qa-access?next=/login', data={'key': 'qa-test-key-123'}, base_url='https://test1.qa.example.test')
cookie = r.headers.get('Set-Cookie', '')
ok('…the right key: back to the page, remembered for every QA address', r.status_code == 302
   and r.headers['Location'].endswith('/login') and 'qa_access=' in cookie and 'Domain=qa.example.test' in cookie
   and 'HttpOnly' in cookie)
r = qc.get('/login', base_url='https://test1.qa.example.test')
ok('…then the app, with the QA label and noindex', r.status_code == 200 and '>QA</div>' in r.text
   and r.headers.get('X-Robots-Tag') == 'noindex, nofollow')
r = qc.post('/qa-access?next=//evil.example', data={'key': 'qa-test-key-123'}, base_url='https://test1.qa.example.test')
ok('…never sends you to another site', r.headers['Location'].endswith('/') and 'evil' not in r.headers['Location'])
for k in ('QA_MODE', 'QA_ACCESS_KEY', 'QA_COOKIE_DOMAIN'):
    os.environ.pop(k)
ok('the live app: no key page, no QA label, indexed as usual', live.status_code == 200 and '>QA</div>' not in live.text
   and 'X-Robots-Tag' not in live.headers)

# ── The QA console may sign in with its password alone; the live console never ──
import subprocess, sys
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash
start = ("import os; os.environ.update(FLASK_ENV='production', SECRET_KEY='x', CONSOLE_MODE='1', "
         "CONSOLE_PASSWORD_HASH='h', DATA_ENCRYPTION_KEY='" + Fernet.generate_key().decode() + "'); "
         "os.environ.pop('CONSOLE_TOTP_SECRET', None); {qa}from app import create_app; create_app('production'); print('started')")
env = {k: v for k, v in os.environ.items() if k not in ('QA_MODE', 'QA_ACCESS_KEY', 'TENANT_MODE')}
live_run = subprocess.run([sys.executable, '-c', start.format(qa='')], capture_output=True, text=True, env=env)
qa_run = subprocess.run([sys.executable, '-c', start.format(qa="os.environ['QA_MODE']='1'; ")], capture_output=True,
                        text=True, env=env)
ok('the live console still refuses to start without 2FA; the QA console starts without it',
   live_run.returncode != 0 and 'CONSOLE_TOTP_SECRET' in live_run.stderr and 'started' in qa_run.stdout)
from app import console as CON
os.environ.pop('CONSOLE_TOTP_SECRET', None)
os.environ['CONSOLE_PASSWORD_HASH'] = generate_password_hash('qa-console-pass-1')
with app.test_request_context():
    live_2fa = CON._two_factor()
    os.environ['QA_MODE'] = '1'
    qa_2fa, qa_ready = CON._two_factor(), CON._configured()
    os.environ['CONSOLE_TOTP_SECRET'] = CON.new_totp_secret()
    qa_with_secret = CON._two_factor()
for k in ('QA_MODE', 'CONSOLE_TOTP_SECRET', 'CONSOLE_PASSWORD_HASH'):
    os.environ.pop(k, None)
ok('…sign-in: the live console always asks for the code; QA only when it has a 2FA secret',
   live_2fa and not qa_2fa and qa_ready and qa_with_secret)

# ── A free set-up call (app/callbook.py): our hours, free slots, the card ──
from datetime import datetime as _dt
from app import callbook as CB
with app.app_context():
    try:
        CB.parse_ranges('9-10'); bad = False
    except ValueError:
        bad = True
    ok('call hours: ranges read, a wrong one refused', CB.parse_ranges('09:00-10:15, 12:00-20:00') == [(540, 615), (720, 1200)]
       and bad)
    days = dict(CB.slots(now=_dt(2026, 11, 9, 0, 30), taken=[]))      # Monday 6:00 AM India time
    mon = [lbl for _, lbl in days['Today']]
    ok('…Monday: 9:00 and 9:30, nothing 10:15–12:00 (a 10:00 call would run into it), from 12:00 to 7:30 PM',
       mon[:3] == ['9:00 AM', '9:30 AM', '12:00 PM'] and mon[-1] == '7:30 PM' and '10:00 AM' not in mon
       and '11:30 AM' not in mon)
    ok('…Wednesday and Thursday only after office (6:30 PM); Saturday all day; Sunday off',
       [l for _, l in days['Wednesday 11 Nov']] == ['6:30 PM', '7:00 PM', '7:30 PM']
       and [l for _, l in days['Thursday 12 Nov']] == ['6:30 PM', '7:00 PM', '7:30 PM']
       and days['Saturday 14 Nov'][0][1] == '9:00 AM' and 'Sunday 15 Nov' not in days)
    soon = dict(CB.slots(now=_dt(2026, 11, 9, 6, 0), taken=[_dt(2026, 11, 9, 8, 30)]))   # Monday 11:30 AM India time
    today = [l for _, l in soon['Today']]
    ok('…not within the next hour, and a booked time (2:00 PM) is taken',
       today[:4] == ['12:30 PM', '1:00 PM', '1:30 PM', '2:30 PM'] and '2:00 PM' not in today)
    ok('the card only for trials in the shared app (not here)', not CB.available())
lp = c.get('/projects').text
ok('…so no card on the quotations here', 'Get your rates set up for you' not in lp)
with app.test_request_context():
    from flask import render_template_string
    card = render_template_string('{% include "partials/_help_card.html" %}',
                                  help_card={'booked': None, 'whatsapp': 'https://wa.me/919999999999?text=Hi'})
    done = render_template_string('{% include "partials/_help_card.html" %}',
                                  help_card={'booked': {'when': 'Mon 9 Nov, 5:00 PM'}, 'whatsapp': ''})
ok('…the card: Book a free call and Chat on WhatsApp; once booked, when', 'Get your rates set up for you' in card
   and '/welcome/call' in card and 'wa.me/919999999999' in card and 'Your free set-up call: Mon 9 Nov, 5:00 PM' in done
   and '/welcome/call' not in done)
