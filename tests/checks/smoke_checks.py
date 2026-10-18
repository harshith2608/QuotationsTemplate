"""Smoke checks with env-var branding: every main page renders, branding/logo/colours apply,
PDFs carry branding, invalid colours fall back, admin overrides fall back to env when cleared."""
import os, re, zlib, struct
from io import BytesIO
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.normpath(os.path.join(HERE, '..', '..', 'static', 'brand'))
LOGO = os.path.join(STATIC, '_test_logo.png')

def _png(path, w=60, h=20):
    raw = b''.join(b'\x00' + bytes([200, 30, 30]) * w for _ in range(h))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

os.makedirs(STATIC, exist_ok=True)
_png(LOGO)
os.environ.update(BRAND_PRIMARY='#7b1fa2', BRAND_ACCENT='#00897b', BRAND_SECONDARY='not-a-colour',
                  COMPANY_NAME='Env Name Co', COMPANY_TAGLINE='Kitchens & Wardrobes',
                  SIGNATORY_NAME='A. Demo', SIGNATORY_TITLE='Director', LOGO_FILE='brand/_test_logo.png',
                  LOCK_COMPANY_DETAILS='0')
for k in ['DEMO_MODE', 'MARKETING_SITE']:
    os.environ.pop(k, None)
try:
    from app import create_app
    from pypdf import PdfReader
    ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
    app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
    c = app.test_client()
    r = c.get('/login')
    ok('login page: saved company name, env colour, logo', r.status_code == 200 and 'Demo Interiors' in r.text
       and '#7b1fa2' in r.text and '_test_logo.png' in r.text)
    r = c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'}, follow_redirects=True)
    ok('login works', r.status_code == 200 and 'Quotation' in r.text)
    ok('invalid env colour falls back to default', re.search(r'--ki-secondary: +#283593', r.text) is not None)
    pages = ['/projects', '/projects/new', '/projects/1', '/projects/1/edit', '/admin/dashboard', '/admin/users',
             '/admin/rates', '/admin/payment-settings', '/admin/notifications', '/favicon.svg']
    bad = [u for u in pages if c.get(u).status_code != 200 or 'kundan' in c.get(u).text.lower()]
    ok(f'all main pages render, no old branding {bad}', not bad)
    t = c.get('/projects/new').text
    ok('form uses material catalogue', 'value="Acrylic|' in t and 'Laminates|Box Work" selected' in t and 'KI_CATALOG' in t)
    v = c.get('/projects/1').text
    ok('quotation page: both PDF buttons open to view in a new tab (no forced download)',
       'href="/projects/1/pdf" target="_blank"' in v and 'href="/projects/1/pdf/customer" target="_blank"' in v
       and 'pdf?download=1"' not in v and 'customer?download=1"' not in v)
    r = c.get('/projects/1/pdf')
    ok('PDF served inline with a proper file name (for Save / Share from the viewer)',
       r.headers.get('Content-Disposition', '').startswith('inline') and '.pdf' in r.headers.get('Content-Disposition', ''))
    ok('favicon uses brand colour', '#7b1fa2' in c.get('/favicon.svg').text)
    for u in ['/projects/1/pdf', '/projects/1/pdf/customer']:
        r = c.get(u)
        pdf = PdfReader(BytesIO(r.data)); txt = '\n'.join(p.extract_text() for p in pdf.pages)
        ok(f'{u}: branding, GSTIN, logo, no signature block', r.status_code == 200 and 'Demo Interiors' in txt
           and 'GSTIN: 29ABCDE1234F1Z5' in txt and 'A. Demo' not in txt and 'Director' not in txt
           and sum(len(p.images) for p in pdf.pages) == 1)
    r = c.get('/projects/1/whatsapp')
    ok('WhatsApp share uses company name', r.status_code == 302 and 'Demo Interiors' in unquote(r.headers.get('Location', '')))
    c.post('/admin/settings', data={'section': 'company', 'company_name': '', 'company_gstin': '', 'company_tagline': ''})
    import hashlib, hmac, time as _t
    ts = str(int(_t.time())); key = app.config['SECRET_KEY'].encode()
    sig = hmac.new(key, f'healthz:{ts}'.encode(), hashlib.sha256).hexdigest()
    h = app.test_client().get(f'/healthz?ts={ts}&sig={sig}')
    ok('/healthz: signed request reports the database and admins', h.status_code == 200 and h.json['admins'] == ['demo-admin']
       and h.json['revision'])
    ok('/healthz: unsigned / wrong / old signatures get 404', app.test_client().get('/healthz').status_code == 404
       and app.test_client().get(f'/healthz?ts={ts}&sig=bad').status_code == 404
       and app.test_client().get('/healthz?ts=1000&sig=' + hmac.new(key, b'healthz:1000', hashlib.sha256).hexdigest()).status_code == 404)
    t = c.get('/projects').text
    ok('cleared admin values fall back to env', 'Env Name Co' in t and 'Kitchens &amp; Wardrobes' in t)
    txt = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(c.get('/projects/1/pdf').data)).pages)
    ok('PDF falls back to env name, no GSTIN', 'Env Name Co' in txt and 'GSTIN' not in txt)

    # Add to Home screen: the business's own name, colour and icon, without logging in (phones fetch them cookie-less)
    from PIL import Image
    anon = app.test_client()
    m = anon.get('/manifest.webmanifest')
    ok('manifest: business name, colour, opens on quotations, no login needed', m.status_code == 200
       and m.mimetype == 'application/manifest+json' and m.json['name'] == 'Env Name Co'
       and m.json['theme_color'] == '#7b1fa2' and m.json['start_url'] == '/projects' and m.json['display'] == 'standalone')
    icon_urls = [i['src'] for i in m.json['icons']]
    imgs = [Image.open(BytesIO(anon.get(u).data)) for u in icon_urls]
    ok(f'manifest icons are real square PNGs {[i.size for i in imgs]}', all(i.format == 'PNG' and i.width == i.height for i in imgs)
       and {i.width for i in imgs} == {192, 512})
    logo_icon = Image.open(BytesIO(anon.get('/app-icon-180.png').data)).convert('RGB')
    ok('icon: the logo centred on white', logo_icon.getpixel((2, 2)) == (255, 255, 255) and logo_icon.getpixel((90, 90))[0] > 150
       and logo_icon.getpixel((90, 90))[1] < 80)
    ok('icon: other sizes refused', anon.get('/app-icon-64.png').status_code == 404)
    head = c.get('/projects').text
    ok('pages link the manifest and the iPhone icon and title', 'rel="manifest"' in head and 'rel="apple-touch-icon"' in head
       and 'apple-mobile-web-app-title" content="Env Name Co"' in head)
    os.environ['LOGO_FILE'] = ''
    from app import app_icon
    with app.test_request_context():
        plain = Image.open(BytesIO(app_icon.icon_png(192))).convert('RGB')
    ok('icon without a logo: initials on the brand colour', plain.getpixel((3, 3)) == (0x7b, 0x1f, 0xa2)
       and app_icon.initials('Env Name Co') == 'EN' and app_icon.initials('A & B Interiors') == 'AB')
finally:
    if os.path.exists(LOGO):
        os.remove(LOGO)
