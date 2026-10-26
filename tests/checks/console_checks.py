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
ok('trial page: Features card, pricing by material', 'id="features"' in t and 'Switch to pricing by item' in t)
import html as _html0
r = c.post('/trials/ravi-modular/boq', data={'on': '1'}, follow_redirects=True)
with app.app_context():
    from app.models import AppSetting as _AS2
    with tenancy.tenant_context('ravi-modular'):
        _boq_on = _AS2.get('feature_boq') == '1'
    from app.models import BoqItem as _BQ
    with tenancy.tenant_context('ravi-modular'):
        _starter = _BQ.query.count()
        _layout = _AS2.get('initial_layout')
ok('console switches one trial to pricing by item: BOQ lines, the starter lines and the BOQ layout',
   'now prices by item' in _html0.unescape(r.text) and 'Switch to pricing by material' in r.text and _boq_on and _starter >= 25 and _layout == 'boq')
r = c.post('/trials/ravi-modular/boq', data={'on': '0'}, follow_redirects=True)
with app.app_context():
    with tenancy.tenant_context('ravi-modular'):
        _boq_on = _AS2.get('feature_boq') == '1'
ok('…and back to by material (audited)', 'now prices by material' in _html0.unescape(r.text) and not _boq_on and '<td>boq</td>' in r.text)
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
       _con.follow_ups(_t(6))[1] == 'signin' and _con.follow_ups(_t(5, last_login_at=1, used=True))[1] == 'details'
       and _con.follow_ups(_t(5, last_login_at=1, used=True, company_set=True))[1] == 'firstquote'
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

# ── Self-serve trials: the website's link → the public /start page → a ready-made trial, renamed ──
import html as _h
os.environ['SIGNUP_SECRET'] = 'signup-secret-for-tests'
from app import ops as _ops, signup as _su, plan as _pl
with crypto.using_key(LEADS_KEY), le.begin() as conn:
    self_id = conn.execute(Lead.__table__.insert().values(name='Meera Shah', phone='919811100022', business_type='interiors',
                           company_name='Shah Design Studio', city='Pune', email='meera@shahstudio.example',
                           created_at=datetime.utcnow())).inserted_primary_key[0]
    other_id = conn.execute(Lead.__table__.insert().values(name='Not Eligible', phone='919811100023', business_type='other',
                            business_other='Tiles shop', company_name='Tiles', city='Pune',
                            created_at=datetime.utcnow())).inserted_primary_key[0]
with app.app_context():
    _ops.create_trial('taken-one', 'admin', 'taken-pass-123', 7)
    made = _ops.top_up_spares(2)
    spares_before = _ops.spare_count()
    listed = [t['slug'] for t in _ops.list_trials()]
ok('ready-made trials are made and kept out of the trials list', made == 2 and spares_before == 2
   and not any(s.startswith('spare-') for s in listed))
tok = _su.make_token(self_id)
ok('the link carries only a signed id: no name, phone or email', 'Meera' not in tok and '9811100022' not in tok
   and _su.read_token(tok) == self_id and _su.read_token(tok[:-1] + ('0' if tok[-1] != '0' else '1')) is None
   and _su.read_token(_su.make_token(self_id, now=time.time() - 4 * 86400)) is None)
anon = app.test_client()
r = anon.get('/start?t=' + tok)
ok('/start without signing in: the setup form; the web address comes from the firm name (no address box)', r.status_code == 200
   and 'Hi Meera Shah' in r.text and 'shah-studio.quote-room.test' in r.text and 'Shah Design Studio' in r.text
   and 'name="slug"' not in r.text)
ok('a bad or not-eligible link is refused', anon.get('/start?t=1.2.3').status_code == 404
   and anon.get('/start?t=' + _su.make_token(other_id)).status_code == 404)
ok('the address follows the firm name as they type; a taken one gets a number', anon.get(
       f'/start/check?t={tok}&company=Taken One Interiors').get_json()['address'] == 'taken-one-2.quote-room.test'
   and anon.get(f'/start/check?t={tok}&company=Shah Design Studio').get_json()['slug'] == 'shah-studio'
   and anon.get('/start/check?t=bad&company=x').status_code == 404)
base = dict(t=tok, company='Shah Design Studio', username='meera', password='meera-pass-123')
r = anon.post('/start', data=dict(base, password2='different-pass'))
ok('mistakes are shown on the form (passwords differ, terms not ticked)', "passwords don't match" in _h.unescape(r.text)
   and 'accept the terms' in r.text)
r = anon.post('/start', data=dict(base, password2='meera-pass-123', terms='1'))
with app.app_context():
    spares_after = _ops.spare_count()
    with tenancy.tenant_context('shah-studio'):
        admin = User.query.filter_by(role='admin').first()
        from app.models import AppSetting as _AS
        got = _AS.get_many(['company_name', 'company_mobile', 'company_address', 'company_email'])
        st = _pl.load_status(on=_pl.today())
    with db.engine.connect() as conn:
        tstatus = conn.execute(text("select status from public.tenants where slug='shah-studio'")).scalar()
        linked = conn.execute(text('select status, slug from public.console_lead_links where lead_id = :i'), {'i': self_id}).first()
ok('"Create my app": a ready-made trial becomes theirs at once (their login, company, city, email; 7-day trial)',
   'Your app is ready' in r.text and 'https://shah-studio.quote-room.test/login?u=meera' in r.text
   and spares_after == spares_before - 1 and tstatus == 'active' and admin.username == 'meera'
   and check_password_hash(admin.password_hash, 'meera-pass-123') and got['company_name'] == 'Shah Design Studio'
   and got['company_address'] == 'Pune' and got['company_email'] == 'meera@shahstudio.example'
   and st.plan == 'trial' and st.days_left == 7)
from app.console import _session_tag
signed = app.test_client()                                # (the client above was signed out by the password change)
with app.test_request_context():
    tag = _session_tag()
with signed.session_transaction() as sess:
    sess['console_at'], sess['console_tag'] = time.time(), tag
ok('…linked to the request in the console (audited), and the link only works once', tuple(linked) == ('trial', 'shah-studio')
   and 'already set up' in anon.get('/start?t=' + tok).text and 'trial self start' in signed.get('/activity').text)
with crypto.using_key(LEADS_KEY), le.begin() as conn:
    manual_id = conn.execute(Lead.__table__.insert().values(name='Ravi Rao', phone='919811100024', business_type='interiors',
                             company_name='Rao Interiors', city='Pune', email='ravi@rao.example',
                             created_at=datetime.utcnow())).inserted_primary_key[0]
with app.app_context():
    _ops.create_trial('rao-made', 'admin', 'rao-pass-1234', 7)
    from app.console import _link_lead
    _link_lead(manual_id, 'trial', 'rao-made')            # what Create trial on the request does
    spares_mid = _ops.spare_count()
r = anon.get('/start?t=' + _su.make_token(manual_id))
with app.app_context():
    spares_mid2 = _ops.spare_count()
ok('a request you already made a trial for by hand: the emailed link opens that app (no second app)',
   'already set up' in r.text and 'rao-made.quote-room.test' in r.text and 'name="password"' not in r.text
   and spares_mid2 == spares_mid)
with app.app_context():
    _ops.delete_trial('rao-made')
_dash = signed.get('/').text
ok('the dashboard shows self-serve and the ready-made trials', 'Self-serve trials' in _dash and 'shah-studio' in _dash
   and 'ready-made trial' in _dash)
with app.app_context():
    _ops.delete_trial('shah-studio')
    while _ops.spare_count():                              # with none ready, a new one is made on the spot
        with db.engine.connect() as conn:
            sp = conn.execute(text("select slug from public.tenants where status='spare' limit 1")).scalar()
        _ops.delete_trial(sp)
    t2 = _ops.claim_trial('fresh-made', 'boss', 'boss-pass-123', 7, company='Fresh')
ok('with no ready-made trial, one is made on the spot', t2['slug'] == 'fresh-made' and t2['username'] == 'boss')

# ── Follow-ups: each trial's stage, who's due today, the queue, the log, snooze / not interested, stage emails ──
from datetime import timedelta as _td
from app import followups as _fu, plan as _plm
from app.models import AppSetting as _AS2
with app.app_context():
    for sl in ('fu-new', 'fu-set', 'fu-end'):
        _ops.create_trial(sl, 'admin', 'fu-pass-1234', 7, company=sl.upper(), phone='919800000' + str(len(sl)), email=f'{sl}@x.example')
    with tenancy.tenant_context('fu-set'):
        _AS2.set('company_name', 'Set Interiors'); _AS2.set('last_login_at', datetime.utcnow().isoformat()); db.session.commit()
    with tenancy.tenant_context('fu-end'):
        _plm.save_plan('trial', _plm.today() - _td(days=6), _plm.today() + _td(days=1)); db.session.commit()
    with db.engine.begin() as conn:                        # started two days ago (for the stage emails)
        conn.execute(text("UPDATE public.tenants SET created_at = (now() AT TIME ZONE 'utc') - interval '2 days' "
                          "WHERE slug IN ('fu-new', 'fu-set', 'fu-end')"))
    from app.console import _followup_trials
    with app.test_request_context():
        _tr, _ct = _followup_trials()
    b = _fu.board(_tr, _ct)
    stages = {r['slug']: r['stage'] for r in b['rows']}
ok('each trial gets its stage: never signed in / set up, no quotation / ending soon',
   stages.get('fu-new') == 'signin' and stages.get('fu-set') == 'firstquote' and stages.get('fu-end') == 'ending'
   and b['counts']['signin'] >= 1)
ok('…all three due today, the one ending soon first', [r['slug'] for r in b['due']][:1] == ['fu-end']
   and {'fu-new', 'fu-set', 'fu-end'} <= {r['slug'] for r in b['due']})
page = signed.get('/follow-ups').text
ok('Follow-ups page: counts by stage and the due list', 'Not signed in' in page and 'Ending soon' in page
   and 'Start: one after another' in page and 'Follow-ups' in signed.get('/').text)
q = signed.get('/follow-ups/queue').text
ok('the queue shows the most urgent one with its message', 'fu-end' in q and 'trial ends on' in q and 'Open in WhatsApp' in q)
r = signed.post('/follow-ups/fu-end/whatsapp', data={'phone': '919800000006', 'message': 'Hi there', 'stage': 'ending'})
ok('Open in WhatsApp: logged, then WhatsApp opens with the message', r.status_code == 302
   and r.headers['Location'].startswith('https://wa.me/919800000006?text=Hi'))
ok('…and the next one comes up (it isn\'t due again today)', 'fu-end' not in signed.get('/follow-ups/queue').text.split('<h1>')[1][:80])
signed.post('/follow-ups/fu-new/mark', data={'snooze': '3'})
signed.post('/follow-ups/fu-set/mark', data={'mark': 'lost'})
signed.post('/follow-ups/fu-set/mark', data={'note': 'wants a call Monday'})
with app.app_context(), app.test_request_context():
    _tr, _ct = _followup_trials()
    b = _fu.board(_tr, _ct)
    due = {r['slug'] for r in b['due']}
    mk = _fu.marks()
ok('snoozed and not-interested trials drop off the list (with the note kept)', not ({'fu-new', 'fu-set', 'fu-end'} & due)
   and mk['fu-set']['mark'] == 'lost' and mk['fu-set']['note'] == 'wants a call Monday')
tp = signed.get('/trials/fu-end').text
ok('the trial page shows its stage and what was sent', 'Follow-up' in tp and 'Ending soon' in tp and 'Hi there' in tp)
# Stage emails (daily task), once each
import glob as _glob, email as _em
_box = tempfile.mkdtemp(); os.environ['MAIL_OUTBOX_DIR'] = _box
with app.app_context(), app.test_request_context():
    _tr, _ = _followup_trials()
    sent1 = _fu.send_stage_emails(_tr)
    sent2 = _fu.send_stage_emails(_tr)
mails = [_em.message_from_bytes(open(f, 'rb').read()) for f in sorted(_glob.glob(_box + '/*.eml'))]
ok('stage emails: "not signed in" and "no quotation" once each (not to a trial ending soon), not twice',
   sent1.get('fu-new') == 'signin' and sent1.get('fu-set') == 'firstquote' and 'fu-end' not in sent1 and not sent2
   and {m['To'] for m in mails} == {'fu-new@x.example', 'fu-set@x.example'})

# ── Emails: opened / clicked, writing from the console, the website's set-up email ──
from app import emails as _ems
def _html(m):
    part = m.get_body(preferencelist=('html',)) if hasattr(m, 'get_body') else None
    for p_ in m.walk():
        if p_.get_content_type() == 'text/html':
            return p_.get_payload(decode=True).decode()
    return ''
_new = next(m for m in mails if m['To'] == 'fu-new@x.example')
_h1 = _html(_new)
_tokm = re.search(r'/e/o/([A-Za-z0-9_-]+)\.gif', _h1)
_lnk = re.search(r'href="[^"]*/e/c/([A-Za-z0-9_-]+)/(\d+)"', _h1)
ok('a stage email has an HTML copy with the open image and its link through the console', bool(_tokm and _lnk)
   and _new.get_content_type() == 'multipart/alternative')
g = anon.get(f'/e/o/{_tokm.group(1)}.gif')
ok('the open image: a tiny GIF, public, never cached', g.status_code == 200 and g.mimetype == 'image/gif'
   and 'no-store' in g.headers['Cache-Control'])
cl = anon.get(f'/e/c/{_lnk.group(1)}/{_lnk.group(2)}')
ok('a link: noted, then on to where it pointed (their app)', cl.status_code == 302 and 'fu-new.quote-room.test' in cl.headers['Location'])
ok('an unknown link goes to the website, never elsewhere', 'quote-room.co.in' in anon.get('/e/c/unknowntoken123/0').headers['Location'])
with app.app_context():
    _row = [e for e in _ems.for_trial('fu-new') if e['kind'] == 'stage'][0]
ok('…and the trial shows it opened and clicked', _row['opened_at'] and _row['clicked_at'] and _row['opens'] == 1)
ok('Email needs the console sign-in', anon.get('/email?slug=fu-new').status_code == 302)
ep = signed.get('/email?slug=fu-new').text
ok('Email a trial: their address filled in, the follow-up drafts as emails, what was sent before', 'value="fu-new@x.example"' in ep
   and 'Your QuoteRoom app is ready' in ep and 'automatic' in ep and 'opened' in ep)
r = signed.post('/email?slug=fu-new', data={'to': 'fu-new@x.example', 'subject': 'Quick question',
                                            'body': 'Hi,\n\nOpen your app: https://fu-new.quote-room.test\n\nHarshith'})
mails2 = [_em.message_from_bytes(open(f, 'rb').read()) for f in sorted(_glob.glob(_box + '/*.eml'))]
mine = [m for m in mails2 if m['Subject'] == 'Quick question']
ok('…sent from hello@ with a copy there, logged as a follow-up', r.status_code == 302 and len(mine) == 1
   and mine[0]['Bcc'] and 'Quick question' in signed.get('/trials/fu-new').text)
ok('…a bad address is refused', 'valid email' in signed.post('/email?slug=fu-new', data={'to': 'nope', 'subject': 'x', 'body': 'y'},
                                                           follow_redirects=True).text)
lp = signed.get(f'/email?lead={self_id}').text
ok('Email a trial request: the set-up link again (a fresh one), to the address they gave', 'Set-up link again' in lp
   and '/start?t=' in lp and 'meera@shahstudio.example' in lp)
ok('Email anyone: a blank email', signed.get('/email').status_code == 200 and 'Email' in signed.get('/').text)
# The website's set-up email: the open image is signed; the console adds the row on the first open, /start is the click
os.environ['SIGNUP_URL'] = 'https://ops.quote-room.test'
with app.app_context():
    sent_ok = _su.email_setup_link('meera@shahstudio.example', 'Meera Shah', 'Shah Design Studio',
                                   _su.setup_url(self_id), lead_id=self_id)
setup_mail = [_em.message_from_bytes(open(f, 'rb').read()) for f in sorted(_glob.glob(_box + '/*.eml'))][-1]
_sh = _html(setup_mail)
_st = re.search(r'https://ops\.quote-room\.test/e/o/(L\d+\.[0-9a-f]+)\.gif', _sh)
ok("the website's set-up email carries a signed open image (no name or email in it)", sent_ok and bool(_st)
   and 'Meera' not in _st.group(1) and '/start?t=' in _sh)
_opens = lambda: sum(e['opens'] for e in _ems.for_lead(self_id))
with app.app_context():
    before = _opens()
anon.get(f'/e/o/L{self_id}.{"0" * 32}.gif')
with app.app_context():
    forged = _opens() - before
anon.get(f'/e/o/{_st.group(1)}.gif')
with app.app_context():
    real = _opens() - before - forged
    seen = _ems.by_lead().get(self_id, {})
ok('…a forged one is ignored; the real one shows the set-up email opened', forged == 0 and real == 1 and seen.get('opened_at'))
anon.get('/start?t=' + _su.make_token(self_id))
with app.app_context():
    seen = _ems.by_lead().get(self_id, {})
ok('…and opening the set-up link counts as the click', bool(seen.get('clicked_at')))
fp = signed.get('/follow-ups').text
ok('Follow-ups shows how many set-up emails are opened, and the emails sent from here', 'Set-up link email' in fp
   and 'Sent from here' in fp)
os.environ.pop('SIGNUP_URL', None)
os.environ.pop('MAIL_OUTBOX_DIR', None)
with app.app_context():
    for sl in ('fu-new', 'fu-set', 'fu-end'):
        _ops.delete_trial(sl)

# Clean up the public console tables so other suites start from a clean trials database
with app.app_context(), db.engine.begin() as conn:
    for tname in ('console_audit', 'console_state', 'console_lead_links', 'signups', 'console_followups',
                  'console_trial_marks', 'plan_reminders', 'platform_payments', 'console_emails', 'console_emails_since'):
        conn.execute(text(f'DROP TABLE IF EXISTS public.{tname}'))
    conn.execute(text('DELETE FROM public.tenants'))
