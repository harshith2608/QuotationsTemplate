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
              business_other='Ravi Modular Kitchens', company_name='Kumar Woodcraft', city='Vijayawada',
              email='ravi@kumarwood.example', source='facebook', created_at=datetime.utcnow())])

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
ok('live demo card says counting starts after the update (no demo_stats table yet)', 'Counting starts after the database update' in t)
from datetime import date, timedelta as _td
from app.models import DemoStat
DemoStat.__table__.create(le, checkfirst=True)
with le.begin() as conn:
    conn.execute(DemoStat.__table__.insert(), [dict(day=datetime.utcnow().date(), starts=4, quotations=2, pdfs=3, site_visitors=40),
                                               dict(day=datetime.utcnow().date() - _td(days=3), starts=6, quotations=1, pdfs=0, site_visitors=60),
                                               dict(day=datetime.utcnow().date() - _td(days=20), starts=10, quotations=0, pdfs=1, site_visitors=100)])
t = c.get('/').text
flat = re.sub(r'\s+', ' ', t)
row = lambda label, *cells: f'<td>{label}</td> ' + ' '.join(cells) + '</tr>'
ok('funnel: site visitors → demo → quotations → PDFs, and trial requests, with % (today, 7 and 30 days)',
   '<h2>Website &amp; live demo</h2>' in t
   and row('Today', '<td><strong>40</strong></td>', '<td><strong>4</strong><span class="muted small"> · 10%</span></td>',
           '<td>2<span class="muted small"> · 50%</span></td>', '<td>3<span class="muted small"> · 75%</span></td>',
           '<td><strong>1</strong><span class="muted small"> · 2%</span></td>') in flat
   and row('Last 30 days', '<td><strong>200</strong></td>', '<td><strong>20</strong><span class="muted small"> · 10%</span></td>',
           '<td>3<span class="muted small"> · 15%</span></td>', '<td>4<span class="muted small"> · 20%</span></td>',
           '<td><strong>1</strong><span class="muted small"> · 0%</span></td>') in flat)
with le.begin() as conn:
    conn.execute(text('alter table demo_stats drop column site_visitors'))
flat = re.sub(r'\s+', ' ', c.get('/').text)
ok('before the update that adds site visitors: the card still shows the demo numbers', '<td><strong>—</strong></td> <td><strong>4</strong>' in flat
   and 'Site visitors are counted after the next database update' in flat)
with le.begin() as conn:
    conn.execute(text('alter table demo_stats add column site_visitors integer not null default 0'))
ok('dashboard shows new trial request with company and an address suggested from it', 'Ravi Kumar' in t
   and 'Kumar Woodcraft' in t and 'Ravi Modular Kitchens' in t and 'value="kumar-woodcraft"' in t
   and 'name="company" value="Kumar Woodcraft" maxlength="80"' in t)
with crypto.using_key(LEADS_KEY), le.connect() as conn:
    lead_id = conn.execute(Lead.__table__.select()).first().id
ok('request shows city and email, both editable before Create', 'Vijayawada' in t and 'ravi@kumarwood.example' in t
   and 'name="city" value="Vijayawada"' in t and 'name="email" value="ravi@kumarwood.example"' in t)
r = c.post('/trials', data={'slug': 'ravi-modular', 'days': '7', 'lead_id': lead_id, 'name': 'Ravi Kumar', 'company': 'Kumar Woodcraft',
                            'phone': '919876543210', 'city': 'Vijayawada', 'email': 'ravi@kumarwood.example'})
m = re.search(r'Password:</strong> <span class="secret">([^<]+)</span>', r.text)
password = m.group(1) if m else ''
wa = re.search(r'href="(https://wa\.me/919876543210\?text=[^"]+)"', r.text)
ok('create trial → credentials shown once + WhatsApp message to the lead', r.status_code == 200 and password
   and wa and 'https://ravi-modular.quote-room.test' in unquote(wa.group(1)) and password in unquote(wa.group(1))
   and 'free trial for Kumar Woodcraft is ready' in unquote(wa.group(1))
   and "I've already put in Kumar Woodcraft and your contact details" in unquote(wa.group(1)))
ok('no tutorials on the site yet → welcome message has no tutorials link', '/tutorials' not in unquote(wa.group(1)))
with app.app_context():
    from app import ops
    trial = [x for x in ops.list_trials() if x['slug'] == 'ravi-modular']
    ok('trial exists and is active with a 7-day plan', trial and trial[0]['status'] == 'active'
       and trial[0]['status_obj'].days_left == 7)
    with tenancy.tenant_context('ravi-modular'):
        u = User.query.filter_by(username='admin').first()
        ok('generated password works for the trial admin', u and check_password_hash(u.password_hash, password))
        from app import branding as _br
        from app.models import AppSetting as _AS
        ok('trial starts with the company name and phone from the request (name open for one correction)',
           _AS.get('company_name') == 'Kumar Woodcraft' and _AS.get('company_mobile') == '+91 98765 43210'
           and _AS.get('company_address') == 'Vijayawada' and _AS.get('company_email') == 'ravi@kumarwood.example'
           and 'name' not in _br.locked_fields())
t = c.get('/').text
ok('request no longer "new"; shown as handled → trial', 'Not interested' not in t and 'trial <a href="/trials/ravi-modular">' in t)
ok('running trial shows "running"', '>running<' in t)
ok('a fresh trial shows "Not used yet"', 'Not used yet' in t)

# The customer signs in to their trial and makes a quotation → the console shows it was used
os.environ['TENANT_MODE'] = '1'; os.environ.pop('CONSOLE_MODE')
trial_app = create_app('development'); trial_app.config['WTF_CSRF_ENABLED'] = False
tc_ = trial_app.test_client(); TB = 'http://ravi-modular.quote-room.test'
tc_.post('/login', base_url=TB, data={'username': 'admin', 'password': password})
import json as _json
tc_.post('/projects/new', base_url=TB, data={'customer_name': 'First Client', 'mobile': '9000000001', 'discount_type': 'none',
         'discount_value': '0', 'rooms_data': _json.dumps([{'name': 'Hall', 'items': [
             {'name': 'TV Unit', 'length': 8, 'width': 6, 'wood_type': 'Laminates', 'work_type': 'Box Work'}]}])})
os.environ['CONSOLE_MODE'] = '1'; os.environ.pop('TENANT_MODE')
t = c.get('/').text
ok('dashboard shows usage after sign-in + a quotation', 'Not used yet' not in t and '1 quotation</strong>' in t
   and 'last used today' in t and 'no company details' in t)
t = c.get('/trials/ravi-modular').text
ok('trial page shows usage details (sign-in time, quotations)', '<h2>Usage</h2>' in t and 'none recorded' not in t
   and '<strong>1</strong>' in t and '(today)' in t)

ok('trial page: WhatsApp card with the request\'s name and number, suggested draft for a trial in use',
   'id="whatsapp"' in t and 'id="waName" type="text" value="Ravi"' in t and 'value="919876543210"' in t
   and 'value="quote" data-body=' in t and 'selected>Going well: make a real quotation (suggested)' in t
   and 'trial ends on' in t and '₹4,999' in t and 'class="btn btn-wa"' in t)
ok('trial page: Features card with BOQ lines off', 'id="features"' in t and 'Turn on BOQ lines' in t)
r = c.post('/trials/ravi-modular/boq', data={'on': '1'}, follow_redirects=True)
with app.app_context():
    from app.models import AppSetting as _AS2
    with tenancy.tenant_context('ravi-modular'):
        _boq_on = _AS2.get('feature_boq') == '1'
    from app.models import BoqItem as _BQ
    with tenancy.tenant_context('ravi-modular'):
        _starter = _BQ.query.count()
        _layout = _AS2.get('initial_layout')
ok('console turns BOQ lines on for one trial only, with the starter lines and the BOQ layout', 'BOQ lines turned on' in r.text
   and 'Turn off BOQ lines' in r.text and _boq_on and _starter >= 25 and _layout == 'boq')
r = c.post('/trials/ravi-modular/boq', data={'on': '0'}, follow_redirects=True)
with app.app_context():
    with tenancy.tenant_context('ravi-modular'):
        _boq_on = _AS2.get('feature_boq') == '1'
ok('…and off again (audited)', 'BOQ lines turned off' in r.text and not _boq_on and '<td>boq</td>' in r.text)
import io as _io, json as _json
_pl = {'lines': [{'name': 'Wardrobe', 'unit': 'Sq.ft', 'rate': 1950, 'group': 'Bedroom', 'description': 'BWR ply, laminate'},
                 {'name': 'Site Cleaning', 'unit': 'LS', 'rate': 9000, 'group': 'Services'},
                 {'name': 'Fan Fitting', 'unit': 'nos', 'rate': 450, 'group': 'Lights'}],
       'templates': [{'name': '2 BHK firm', 'rooms': [{'name': 'Bedroom', 'items': ['Wardrobe', 'Site Cleaning', 'Nope']},
                                                      {'name': 'Rates', 'items': [{'name': 'Fan Fitting', 'rate_only': True}]}]}],
       'settings': {'payment_terms': 'Half before work starts.'}}
r = c.post('/trials/ravi-modular/price-list', data={'remove_starter': '1', 'file': (_io.BytesIO(_json.dumps(_pl).encode()), 'firm.json')},
           content_type='multipart/form-data', follow_redirects=True)
with app.app_context():
    with tenancy.tenant_context('ravi-modular'):
        _lines = {b.name: (b.unit, b.rate, b.category) for b in _BQ.query.all()}
        _tpl = _json.loads(_AS2.get('quote_templates') or '[]')
        _pay, _on = _AS2.get('payment_terms'), _AS2.get('feature_boq') == '1'
ok('console loads a firm\'s own price list into that trial: its lines (units cleaned), BOQ lines back on, untouched '
   'starter lines removed', 'Price list loaded' in r.text and _on
   and _lines.get('Wardrobe') == ('sqft', 1950, 'Bedroom') and _lines.get('Site Cleaning') == ('lump sum', 9000, 'Services')
   and _lines.get('Fan Fitting') == ('nos', 450, 'Lights') and len(_lines) == 3)
_items = {i['name']: i for room in (_tpl[0]['rooms'] if _tpl else []) for i in room['items']}
ok('…its starting quotation: lines filled from the list, sizes still to type (lump sum: 1, rate card: rate only)',
   len(_tpl) == 1 and _tpl[0]['name'] == '2 BHK firm' and _items['Wardrobe'].get('pending') and _items['Wardrobe']['quantity'] == 0
   and _items['Wardrobe']['unit_price'] == 1950 and _items['Site Cleaning']['quantity'] == 1 and not _items['Site Cleaning'].get('pending')
   and _items['Fan Fitting']['quantity'] == 0 and not _items['Fan Fitting'].get('pending')
   and 'Nope' not in _items and 'left out of the starting quotation: Nope' in r.text)
ok('…and settings never saved are filled in (audited)', _pay == 'Half before work starts.' and '<td>price list</td>' in r.text)
r = c.post('/trials/ravi-modular/price-list', data={'file': (_io.BytesIO(b'{"lines": [{"name": "X", "rate": "abc"}]}'), 'bad.json')},
           content_type='multipart/form-data', follow_redirects=True)
import html as _html
ok('a bad price list file is refused with the reason', '"X": the rate should be a number' in _html.unescape(r.text))
ok('dashboard: WhatsApp button per running trial', 'href="/trials/ravi-modular#whatsapp">WhatsApp</a>' in c.get('/').text)
with app.app_context():
    from types import SimpleNamespace as _NS
    from datetime import date as _date
    from app import console as _con
    _t = lambda days, **u: {'url': 'https://x.test', 'usage': u, 'status_obj': _NS(
        has_limit=True, days_left=days, ends_on=_date(2026, 10, 27), delete_on=_date(2026, 11, 26))}
    ok('suggested draft follows the trial: not signed in / no quotation / ending / ended',
       _con.follow_ups(_t(6))[1] == 'signin' and _con.follow_ups(_t(5, last_login_at=1, used=True))[1] == 'rates'
       and _con.follow_ups(_t(2, quotations=3))[1] == 'ending' and _con.follow_ups(_t(-1))[1] == 'ended')
    _d = dict((k, b) for k, _, b in _con.follow_ups(_t(-1))[0])
    ok('drafts keep {name} for the page, fill in dates and prices', _d['ended'].startswith('Hi {name},')
       and '27 Oct' in _d['ended'] and '26 Nov' in _d['ended'] and '₹8,999' in _d['ended'])

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
    AppSetting.set('company_name', 'Ravi Kitchens'); branding.relock('name'); db.session.commit()   # as Settings → Company does
    ok('company name locked after the customer corrects the pre-filled one', 'name' in branding.locked_fields())
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

# Tutorials for the marketing site (in the demo database)
t = c.get('/tutorials').text
ok('tutorials page asks for the database update before the table exists', 'Run the database update first' in t
   and '/tutorials">Tutorials</a>' in t)
from app.models import Tutorial
Tutorial.__table__.create(le, checkfirst=True)
ok('empty list offers the first six', 'Add the first six tutorials' in c.get('/tutorials').text)
r = c.post('/tutorials/starters', follow_redirects=True)
ok('one button adds the six starter videos, none on the site yet', r.text.count('needs a YouTube link') == 6
   and '0 on the site' in r.text and '1 · Your company details' in r.text)
c.post('/tutorials/starters')
with le.begin() as conn:
    ok('starters only fill an empty list', conn.execute(text('select count(*) from tutorials')).scalar() == 6)
    conn.execute(text('delete from tutorials'))
r = c.post('/tutorials/add', data={'title': 'Full walkthrough', 'about': 'Everything.', 'length': '4 min', 'youtube': 'https://youtu.be/AAAAAAAAAAA', 'shown': 'on'}, follow_redirects=True)
ok('add a tutorial with a YouTube link → on the site', 'Added &#34;Full walkthrough&#34;' in r.text and '1 on the site' in r.text
   and 'i.ytimg.com/vi/AAAAAAAAAAA/' in r.text)
r = c.post('/tutorials/add', data={'title': '6 · Your team', 'youtube': '', 'shown': 'on'}, follow_redirects=True)
ok('add without a link → listed, flagged as needing one, not on the site', 'needs a YouTube link' in r.text and '1 on the site' in r.text)
r = c.post('/tutorials/add', data={'title': 'Bad', 'youtube': 'https://example.com/x'}, follow_redirects=True)
ok('a link that isn\'t YouTube is refused', 'look like a YouTube link' in r.text and r.text.count('class="item" id="t') == 2)
r = c.post('/tutorials/add', data={'title': 'x'}, follow_redirects=True)
ok('a title is required', 'Give the video a title' in r.text)
with le.connect() as conn:
    ids = [x.id for x in conn.execute(text('select id from tutorials order by position, id'))]
r = c.post(f'/tutorials/{ids[1]}', data={'title': '6 · Your team & logins', 'length': '1 min',
           'youtube': 'https://www.youtube.com/watch?v=BBBBBBBBBBB&t=2', 'shown': 'on'}, follow_redirects=True)
with le.connect() as conn:
    row = conn.execute(text('select title, youtube_id, hidden from tutorials where id = :i'), {'i': ids[1]}).first()
ok('edit saves title and the ID from a watch link', row.title == '6 · Your team & logins' and row.youtube_id == 'BBBBBBBBBBB'
   and not row.hidden and '2 on the site' in r.text)
r = c.post(f'/tutorials/{ids[1]}', data={'title': '6 · Your team & logins', 'length': '1 min', 'wide': 'on',
           'youtube': 'https://youtu.be/BBBBBBBBBBB', 'shown': 'on'}, follow_redirects=True)
with le.connect() as conn:
    wide = conn.execute(text('select wide from tutorials where id = :i'), {'i': ids[1]}).scalar()
ok('Landscape video tick box saves (shown wide on the site)', bool(wide) and 'name="wide" checked' in r.text)
with le.begin() as conn:
    conn.execute(text('alter table tutorials drop column wide'))
r = c.post('/tutorials/add', data={'title': 'Before the update', 'youtube': 'https://youtu.be/DDDDDDDDDDD', 'wide': 'on', 'shown': 'on'},
           follow_redirects=True)
ok('before the database update that adds Landscape: list, add and edit still work, no tick box',
   r.status_code == 200 and 'Added &#34;Before the update&#34;' in r.text and 'name="wide"' not in r.text
   and c.post(f'/tutorials/{ids[1]}', data={'title': '6 · Your team & logins', 'youtube': 'https://youtu.be/BBBBBBBBBBB',
                                            'shown': 'on'}).status_code == 302)
with le.begin() as conn:
    conn.execute(text("delete from tutorials where title = 'Before the update'"))
    conn.execute(text('alter table tutorials add column wide boolean not null default 0'))
from app.console import _tutorials_line, _welcome_message
from datetime import date as _date
msg = _welcome_message('Ravi', 'https://x.quote-room.test', 'admin', 'pw', _date(2026, 10, 23))
ok('with videos on the site, the welcome message links the Tutorials page', 'New here? Short setup videos' in msg
   and 'https://www.quote-room.co.in/tutorials' in msg and msg.index('Password: pw') < msg.index('/tutorials') < msg.index('trial runs until'))
c.post(f'/tutorials/{ids[1]}/move', data={'dir': 'up'})
with le.connect() as conn:
    order = [x.id for x in conn.execute(text('select id from tutorials order by position, id'))]
ok('↑ Up moves a video earlier', order == [ids[1], ids[0]])
r = c.post(f'/tutorials/{ids[0]}', data={'title': 'Full walkthrough', 'youtube': 'https://youtu.be/AAAAAAAAAAA'}, follow_redirects=True)
ok('unticking Show hides it from the site', 'hidden</span>' in r.text and '1 on the site' in r.text)
r = c.post(f'/tutorials/{ids[0]}/delete', follow_redirects=True)
with le.connect() as conn:
    left = conn.execute(text('select count(*) from tutorials')).scalar()
with le.begin() as conn:
    conn.execute(text('update tutorials set hidden = :h'), {'h': True})
ok('all videos hidden → no tutorials line', _tutorials_line() == '')
with le.begin() as conn:
    conn.execute(text('update tutorials set hidden = :h'), {'h': False})
ok('remove deletes it from the list', 'Removed &#34;Full walkthrough&#34;' in r.text and left == 1)

t = c.get('/activity').text
ok('activity log lists sign-ins and actions', all(w in t for w in ['login failed', 'trial create', 'trial delete', 'lead dismiss', 'tutorial add', 'tutorial delete']))

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
