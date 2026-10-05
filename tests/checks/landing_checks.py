import os, re
from app import create_app
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
def client(**env):
    for k in ['MARKETING_SITE','MARKETING_WHATSAPP','MARKETING_PRODUCT_NAME','META_PIXEL_ID','GOOGLE_ADS_ID','GOOGLE_ADS_CONVERSION','MARKETING_PRIVACY_URL']:
        os.environ.pop(k, None)
    os.environ.update(env)
    return create_app('development').test_client()

c = client()
ok('off by default → 404 (client deployments)', c.get('/landingpage').status_code == 404)

c = client(MARKETING_SITE='1', MARKETING_WHATSAPP='+91 98765-43210', MARKETING_PRODUCT_NAME='Sitequote')
r = c.get('/landingpage'); t = r.text
ok('on → 200 without login', r.status_code == 200)
ok('WhatsApp number in every CTA, no placeholder number', t.count('https://wa.me/919876543210?text=') >= 5 and '919999999999' not in t)
ok('display number formatted', '+91 98765 43210' in t)
ok('product name applied everywhere', 'QuoteRoom' not in t and t.count('Sitequote') >= 8 and 'free%20trial%20of%20Sitequote' in t)
ok('demo button → this site login', 'href="/login">Try the live demo' in t)
ok('no ad tags unless configured', 'fbq(' not in t.split('<style>')[0] and 'googletagmanager' not in t)
ok('footer links to built-in legal pages', 'href="/privacy">Privacy policy' in t and 'href="/terms">Terms of service' in t)
ok('full HTML document', t.lstrip().startswith('<!doctype html>') or t.lstrip().startswith('{#') is False and '<!doctype html>' in t[:200])

c = client(MARKETING_SITE='1', META_PIXEL_ID='1234567890', GOOGLE_ADS_ID='AW-111222', GOOGLE_ADS_CONVERSION='AW-111222/AbC-d_1',
           MARKETING_PRIVACY_URL='https://example.com/privacy')
t = c.get('/landingpage').text
ok('Meta Pixel rendered', "fbq('init', \"1234567890\")" in t)
ok('Google tag rendered', 'gtag/js?id=AW-111222' in t and 'googleSendTo: "AW-111222/AbC-d_1"' in t)
ok('privacy link rendered', 'href="https://example.com/privacy">Privacy policy' in t)

c = client(MARKETING_SITE='1', META_PIXEL_ID="1');alert(1);//", GOOGLE_ADS_ID='AW-1"><script>x', GOOGLE_ADS_CONVERSION='bad')
t = c.get('/landingpage').text
ok('malformed IDs ignored / sanitised', 'alert(1)' not in t and '<script>x' not in t and 'googletagmanager' not in t)
