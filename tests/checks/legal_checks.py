import os
from app import create_app
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
KEYS = ['MARKETING_SITE','MARKETING_WHATSAPP','MARKETING_PRODUCT_NAME','MARKETING_LEGAL_NAME','MARKETING_CONTACT_EMAIL',
        'MARKETING_ADDRESS','MARKETING_JURISDICTION','MARKETING_PRIVACY_URL','MARKETING_TERMS_URL']
def make(**env):
    for k in KEYS: os.environ.pop(k, None)
    os.environ.update(env)
    app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
    return app

# Client deployment (marketing off)
c = make().test_client()
r = c.get('/')
ok('off: / redirects to login', r.status_code == 302 and '/login' in r.headers['Location'])
c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
r = c.get('/')
ok('off + signed in: / → quotations', r.status_code == 302 and r.headers['Location'].endswith('/projects'))
r = c.get('/logout')
ok('off: logout → login page', r.headers['Location'].endswith('/login'))
ok('off: /privacy and /terms 404', c.get('/privacy').status_code == 404 and c.get('/terms').status_code == 404)

# Marketing deployment
app = make(MARKETING_SITE='1', MARKETING_WHATSAPP='919876543210', MARKETING_LEGAL_NAME='Harshith Ventures',
           MARKETING_CONTACT_EMAIL='hello@quoteroom.example', MARKETING_JURISDICTION='Hyderabad, Telangana')
c = app.test_client()
r = c.get('/'); t = r.text
ok('on: / shows landing to signed-out visitors', r.status_code == 200 and 'Send the quote' in t)
ok('landing nav uses plain anchors', 'href="#pricing"' in t)
ok('footer links to own legal pages', 'href="/privacy">Privacy policy' in t and 'href="/terms">Terms of service' in t)
ok('canonical points at domain root', 'rel="canonical" href="http://localhost/"' in t)
ok('/landingpage still works', c.get('/landingpage').status_code == 200)
p = c.get('/privacy'); pt = p.text
ok('privacy renders with details', p.status_code == 200 and 'Harshith Ventures' in pt and 'hello@quoteroom.example' in pt
   and 'Digital Personal Data Protection Act' in pt and '+91 98765 43210' in pt)
ok('legal page nav links back to home sections', 'href="/#pricing"' in pt)
tm = c.get('/terms').text
ok('terms renders, jurisdiction applied', 'courts of Hyderabad, Telangana, India' in tm and 'not refundable' in tm and 'Free trial:</strong> 7 days' in tm)
ok('terms links to privacy', 'href="/privacy">Privacy Policy' in tm)

# Signed-in user on the marketing deployment still lands in the app
c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
r = c.get('/')
ok('signed-in user: / still shows landing, with Open app', r.status_code == 200 and 'Send the quote' in r.text
   and 'href="/projects">Open app</a>' in r.text and 'data-cta>Start free trial</a>\n    </nav>' not in r.text)
r = c.get('/logout')
ok('logout → landing page', r.status_code == 302 and r.headers['Location'].endswith('/'))
ok('signed-out landing shows Start free trial', '>Start free trial</a>' in c.get('/').text)
r = c.post('/login?next=https://evil.example.com/x', data={'username': 'demo-admin', 'password': 'demo1234'})
ok('external ?next blocked', r.headers['Location'].endswith('/projects'))
c.get('/logout')
r = c.post('/login?next=/projects/2', data={'username': 'demo-admin', 'password': 'demo1234'})
ok('internal ?next followed', r.headers['Location'].endswith('/projects/2'))
c.get('/logout')
r = c.post('/login?next=//evil.example.com', data={'username': 'demo-admin', 'password': 'demo1234'})
ok('protocol-relative ?next blocked', r.headers['Location'].endswith('/projects'))

# Optional details missing → graceful fallbacks, no empty placeholders
c = make(MARKETING_SITE='1').test_client()
pt = c.get('/privacy').text; tm = c.get('/terms').text
ok('no email/address → omitted cleanly', 'Email:' not in pt and 'mailto:' not in pt)
ok('no jurisdiction → courts of India', 'courts of India.' in tm)
ok('legal name defaults to product', '© 2026 QuoteRoom' in pt)
