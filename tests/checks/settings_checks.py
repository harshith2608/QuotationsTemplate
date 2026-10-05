import os; os.environ['LOCK_COMPANY_DETAILS'] = '0'
import io, re
from PIL import Image
from pypdf import PdfReader
from app import create_app, db
from app.models import AppSetting
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)

# Nav + tabs render
home = c.get('/projects').text
ok('admin menu has Settings link', '/admin/settings' in home and 'Payment Settings' in home)
for tab in ['company', 'appearance', 'documents', 'email']:
    r = c.get(f'/admin/settings?tab={tab}'); ok(f'settings tab {tab} renders', r.status_code == 200)
pay = c.get('/admin/payment-settings').text
ok('payment page only payment fields', 'razorpay_key_id' in pay and 'upi_id' in pay and 'smtp_host' not in pay
   and 'company_name' not in pay and 'terms_conditions' not in pay)
ok('payment page shows real webhook URL', 'http://localhost/webhook/razorpay' in pay)

# Payment save must not wipe other settings
c.post('/admin/payment-settings', data={'upi_id': 'new@upi'})
with app.app_context():
    ok('payment save keeps company + terms', AppSetting.get('company_name') == 'Demo Interiors' and AppSetting.get('upi_id') == 'new@upi')

# Company tab
c.post('/admin/settings', data={'section': 'company', 'company_name': 'Acme Interiors', 'company_tagline': 'Homes & More',
                                'signatory_name': 'R. Acme', 'signatory_title': 'Director', 'company_gstin': '29ABCDE1234F1Z5'})
t = c.get('/projects').text
ok('company name in navbar', 'Acme Interiors' in t and 'Homes &amp; More' in t)

# Appearance: yellow primary (light) + light header + pill + soft + font
r = c.post('/admin/settings', data={'section': 'appearance', 'theme_primary': '#fde047', 'theme_secondary': '#facc15',
     'theme_accent': '#0f766e', 'theme_background': '#fffdf5', 'theme_header': 'solid', 'theme_corners': 'soft',
     'theme_buttons': 'pill', 'theme_font': 'poppins'}, follow_redirects=True)
ok('appearance saved', 'Settings saved.' in r.text)
t = c.get('/projects').text
ok('css vars applied', '--ki-primary:       #fde047' in t and '--ki-btn-radius:    50rem' in t and '--ki-card-radius:   18px' in t)
ok('readable dark text on yellow header', '--ki-on-primary:    #111827' in t and 'navbar-light ki-navbar' in t)
ok('header style class', 'class="ki-header-solid"' in t)
ok('google font loaded', 'fonts.googleapis.com/css2?family=Poppins' in t)
ok('favicon follows theme', '#fde047' in c.get('/favicon.svg').text)

# Invalid values rejected
r = c.post('/admin/settings', data={'section': 'appearance', 'theme_primary': 'red;}body{display:none', 'theme_secondary': '#facc15',
     'theme_accent': '#0f766e', 'theme_background': '#fffdf5', 'theme_header': 'evil', 'theme_corners': 'soft',
     'theme_buttons': 'pill', 'theme_font': 'comic'}, follow_redirects=True)
ok('invalid colour/choices rejected', r.text.count('Invalid value') == 3)
ok('injection not rendered', 'display:none' not in c.get('/projects').text)
r = c.post('/admin/settings', data={'section': 'appearance', 'theme_primary': '#fde047', 'theme_secondary': '#facc15',
     'theme_accent': '#0f766e', 'theme_background': '#222222', 'theme_header': 'solid', 'theme_corners': 'soft',
     'theme_buttons': 'pill', 'theme_font': 'poppins'}, follow_redirects=True)
ok('dark background rejected', 'too dark' in r.text and '--ki-bg:            #fffdf5' in c.get('/projects').text)

# Logo upload (big JPEG → resized PNG), served, used in PDF
buf = io.BytesIO(); Image.new('RGB', (1600, 400), (200, 30, 30)).save(buf, 'JPEG'); buf.seek(0)
r = c.post('/admin/settings', data={'section': 'appearance', 'theme_primary': '#fde047', 'theme_secondary': '#facc15',
     'theme_accent': '#0f766e', 'theme_background': '#fffdf5', 'theme_header': 'solid', 'theme_corners': 'soft',
     'theme_buttons': 'pill', 'theme_font': 'poppins', 'logo': (buf, 'logo.jpg')},
     content_type='multipart/form-data', follow_redirects=True)
m = re.search(r'src="(/brand/logo\.png\?v=\w+)"', c.get('/projects').text)
ok('logo shown in navbar', bool(m))
lr = c.get(m.group(1)); im = Image.open(io.BytesIO(lr.data))
ok(f'logo served as PNG resized to {im.size}', lr.mimetype == 'image/png' and max(im.size) == 600 and 'immutable' in lr.headers['Cache-Control'])
ok('logo on login page (logged out)', app.test_client().get(m.group(1)).status_code == 200)
for u in ['/projects/1/pdf', '/projects/1/pdf/customer']:
    pdf = PdfReader(io.BytesIO(c.get(u).data)); txt = '\n'.join(p.extract_text() for p in pdf.pages)
    ok(f'{u}: logo + company + signatory', sum(len(p.images) for p in pdf.pages) == 1 and 'Acme Interiors' in txt and 'R. Acme' in txt and 'Director' in txt)
ok('themed PDF still renders', c.get('/projects/1/pdf').mimetype == 'application/pdf')

# Non-image upload rejected
r = c.post('/admin/settings', data={'section': 'appearance', 'theme_primary': '#fde047', 'theme_secondary': '#facc15',
     'theme_accent': '#0f766e', 'theme_background': '#fffdf5', 'theme_header': 'solid', 'theme_corners': 'soft',
     'theme_buttons': 'pill', 'theme_font': 'poppins', 'logo': (io.BytesIO(b'<svg onload=alert(1)>'), 'x.svg')},
     content_type='multipart/form-data', follow_redirects=True)
ok('svg/non-image rejected', 'not a readable image' in r.text or 'must be a PNG' in r.text)

# Documents + email tabs
c.post('/admin/settings', data={'section': 'documents', 'material_specs': 'Spec line', 'terms_conditions': '1. Term A'})
c.post('/admin/settings', data={'section': 'email', 'smtp_host': 'smtp.example.com', 'smtp_pass': 'secret1'})
c.post('/admin/settings', data={'section': 'email', 'smtp_host': 'smtp.example.com', 'smtp_pass': ''})
with app.app_context():
    ok('documents saved', AppSetting.get('terms_conditions') == '1. Term A')
    ok('email saved; blank password keeps old', AppSetting.get('smtp_pass') == 'secret1')

# Reset theme (logo kept), remove logo
c.post('/admin/settings', data={'section': 'appearance', 'reset_theme': '1'})
t = c.get('/projects').text
ok('reset restores default theme, keeps logo', '--ki-primary:       #1a237e' in t and 'ki-header-gradient' in t and '/brand/logo.png' in t)
c.post('/admin/settings', data={'section': 'appearance', 'theme_primary': '#1a237e', 'theme_secondary': '#283593',
     'theme_accent': '#f57f17', 'theme_background': '#f5f6fa', 'theme_header': 'gradient', 'theme_corners': 'rounded',
     'theme_buttons': 'standard', 'theme_font': 'system', 'remove_logo': '1'})
ok('logo removed', '/brand/logo.png' not in c.get('/projects').text and c.get('/brand/logo.png').status_code == 404)
with app.app_context():
    ok('defaults stored as blank (env still applies)', AppSetting.get('theme_primary') == '')

# Employee cannot access settings
e = app.test_client(); e.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
ok('employee blocked from settings', e.get('/admin/settings').status_code == 403)
