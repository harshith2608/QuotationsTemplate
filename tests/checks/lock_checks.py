import io, os
from PIL import Image
from app import create_app, db
from app.models import AppSetting
for k in ['DEMO_MODE', 'LOCK_COMPANY_DETAILS']: os.environ.pop(k, None)
os.environ['SUPPORT_WHATSAPP'] = '919876543210'
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
get = lambda k: (lambda: AppSetting.get(k, ''))
def val(k):
    with app.app_context(): return AppSetting.get(k, '')
company = lambda **f: c.post('/admin/settings', data={'section': 'company', **f}, follow_redirects=True)

t = c.get('/admin/settings?tab=company').text
ok('first time: fields editable + confirmation box', 'name="confirm_identity"' in t and 'readonly' not in t)

r = company(company_name='Acme Interiors', company_address='12 Main Rd')
ok('name without confirmation → not saved, address saved', val('company_name') == '' and val('company_address') == '12 Main Rd'
   and 'Tick &#34;These details are correct&#34;' in r.text or 'These details are correct' in r.text)
r = company(company_name='Acme Interiors', confirm_identity='1')
ok('name with confirmation → saved', val('company_name') == 'Acme Interiors')
t = c.get('/admin/settings?tab=company').text
ok('name now read-only with lock + support link', 'id="company_name" name="company_name" class="form-control bg-light"' in t.replace('\n', ' ').replace('  ', ' ')
   or ('readonly aria-readonly="true"' in t and 'Locked after setup.' in t))
ok('support WhatsApp linked', 'href="https://wa.me/919876543210?text=' in t)
ok('GSTIN (empty) still editable → confirmation box still shown', 'name="confirm_identity"' in t)

company(company_name='Someone Else Pvt Ltd', confirm_identity='1', company_address='99 New Rd')
ok('locked name ignored, other fields still save', val('company_name') == 'Acme Interiors' and val('company_address') == '99 New Rd')

r = company(company_gstin='12345', confirm_identity='1')
ok('invalid GSTIN rejected', val('company_gstin') == '' and 'valid GSTIN' in r.text)
company(company_gstin='29abcde1234f1z5', confirm_identity='1')
ok('valid GSTIN uppercased + saved', val('company_gstin') == '29ABCDE1234F1Z5')
t = c.get('/admin/settings?tab=company').text
ok('all identity fields locked → no confirmation box', 'name="confirm_identity"' not in t)
company(company_gstin='36ZZZZZ9999Z1Z5', confirm_identity='1')
ok('locked GSTIN ignored', val('company_gstin') == '29ABCDE1234F1Z5')

def png():
    b = io.BytesIO(); Image.new('RGB', (300, 100), (10, 120, 60)).save(b, 'PNG'); b.seek(0); return b
appearance = {'section': 'appearance', 'theme_primary': '#1a237e', 'theme_secondary': '#283593', 'theme_accent': '#f57f17',
              'theme_background': '#f5f6fa', 'theme_header': 'gradient', 'theme_corners': 'rounded', 'theme_buttons': 'standard', 'theme_font': 'system'}
r = c.post('/admin/settings', data={**appearance, 'logo': (png(), 'l.png')}, content_type='multipart/form-data', follow_redirects=True)
ok('logo without confirmation → rejected', val('logo_version') == '' and "This is my company" in r.text)
c.post('/admin/settings', data={**appearance, 'confirm_logo': '1', 'logo': (png(), 'l.png')}, content_type='multipart/form-data')
v1 = val('logo_version')
ok('logo with confirmation → uploaded', bool(v1))
r = c.post('/admin/settings', data={**appearance, 'confirm_logo': '1', 'logo': (png(), 'l.png')}, content_type='multipart/form-data', follow_redirects=True)
r2 = c.post('/admin/settings', data={**appearance, 'remove_logo': '1'}, follow_redirects=True)
ok('locked logo: replace + remove rejected', val('logo_version') == v1 and 'logo is locked' in r.text and 'logo is locked' in r2.text)
t = c.get('/admin/settings?tab=appearance').text
ok('appearance page shows locked logo, no file input', 'Your logo is locked.' in t and 'id="logoInput"' not in t)

# Operator unlock for one change
runner = app.test_cli_runner()
out = runner.invoke(args=['company-status']).output
ok('company-status shows locks', 'name   LOCKED' in out and 'gstin  LOCKED' in out and 'logo   LOCKED' in out)
out = runner.invoke(args=['company-unlock', 'gstin']).output
ok('company-unlock gstin', 'Unlocked: gstin' in out)
t = c.get('/admin/settings?tab=company').text
ok('GSTIN editable again, name still locked', t.count('Locked after setup.') == 1)
company(company_gstin='36ABCDE1234F1Z9', confirm_identity='1')
ok('client changes GSTIN once', val('company_gstin') == '36ABCDE1234F1Z9')
company(company_gstin='29ABCDE1234F1Z5', confirm_identity='1')
ok('re-locked after the change', val('company_gstin') == '36ABCDE1234F1Z9')
ok('bad unlock args rejected', runner.invoke(args=['company-unlock', 'colour']).exit_code != 0)

# Lock disabled
os.environ['LOCK_COMPANY_DETAILS'] = '0'
app2 = create_app('development'); app2.config['WTF_CSRF_ENABLED'] = False
c2 = app2.test_client(); c2.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
c2.post('/admin/settings', data={'section': 'company', 'company_name': 'Renamed Freely'})
with app2.app_context():
    ok('LOCK_COMPANY_DETAILS=0 → free edits, no confirmation', AppSetting.get('company_name') == 'Renamed Freely'
       and 'confirm_identity' not in c2.get('/admin/settings?tab=company').text)
os.environ.pop('LOCK_COMPANY_DETAILS')

# Support link carries the client's details
import re, html
from urllib.parse import unquote
os.environ['LOCK_COMPANY_DETAILS'] = '1'
app3 = create_app('development'); app3.config['WTF_CSRF_ENABLED'] = False
c3 = app3.test_client(); c3.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
c3.post('/admin/settings', data={'section': 'company', 'company_name': 'Acme Interiors', 'company_mobile': '+91 90000 11111', 'confirm_identity': '1'})
t = c3.get('/admin/settings?tab=company').text
links = re.findall(r'href="https://wa\.me/919876543210\?text=([^"]+)"', t)
msg = unquote(html.unescape(links[0])) if links else ''
ok('support message names company, phone, app URL and requester', 'change my company name' in msg and 'Company: Renamed Freely' in msg
   and 'App: http://localhost/' in msg and 'Requested by: owner' in msg and 'owner (owner)' not in msg)
t = c3.get('/admin/settings?tab=appearance').text
logo_msg = unquote(html.unescape(re.findall(r'href="https://wa\.me/919876543210\?text=([^"]+)"', t)[0]))
ok('logo support message', 'change my logo' in logo_msg and "send the new logo in this chat" in logo_msg)
os.environ.pop('LOCK_COMPANY_DETAILS')
