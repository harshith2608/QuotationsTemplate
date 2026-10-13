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
ok('QuoteRoom logo as tab and home-screen icon', 'brand/quoteroom-icon.svg' in t and 'apple-touch-icon' in t
   and c.get('/static/brand/quoteroom-icon.svg').status_code == 200)
ok('plan buttons go to WhatsApp, no placeholder number', t.count('https://wa.me/919876543210?text=') >= 2 and '919999999999' not in t)
ok('every free-trial button opens the trial form', t.count('href="/free-trial" data-trial') >= 4 and 'start%20a%20free%20trial' not in t)
ok('trial pop-up with the form is on the page', 'id="trialDialog"' in t and 'name="business_type" value="other"' in t)
ok('display number formatted', '+91 98765 43210' in t)
ok('product name applied everywhere', 'QuoteRoom' not in t and t.count('Sitequote') >= 8 and 'Sitequote%206-month' in t)
ok('demo button → this site login', 'href="/login" data-demo>Try the live demo' in t)
ok('click events: StartTrialClick on trial buttons, DemoClick on demo, Lead on submit',
   "track('StartTrialClick')" in t and "track('DemoClick')" in t and "track('Lead', true)" in t and "'trackCustom'" in t)
ok('no cookie notice or tag config unless ads configured', 'id="cookieBanner"' not in t and 'pixel: ""' in t and 'type="button" data-cookie-settings' not in t)
ok('footer links to built-in legal pages', 'href="/privacy">Privacy policy' in t and 'href="/terms">Terms of service' in t)
ok('full HTML document', t.lstrip().startswith('<!doctype html>') or t.lstrip().startswith('{#') is False and '<!doctype html>' in t[:200])

c = client(MARKETING_SITE='1', META_PIXEL_ID='1234567890', GOOGLE_ADS_ID='AW-111222', GOOGLE_ADS_CONVERSION='AW-111222/AbC-d_1',
           MARKETING_PRIVACY_URL='https://example.com/privacy')
t = c.get('/landingpage').text
head = t.split('</head>')[0]
ok('ad tags NOT loaded before consent (nothing in <head>)', 'fbevents.js' not in head and 'googletagmanager' not in head and 'fbq(' not in head)
ok('cookie notice + Cookie settings link shown', 'id="cookieBanner"' in t and 'data-consent="granted"' in t
   and 'data-consent="denied"' in t and 'data-cookie-settings' in t)
ok('Pixel / Google IDs passed to the consent loader', 'pixel: "1234567890"' in t and 'gads: "AW-111222"' in t and 'gconv: "AW-111222/AbC-d_1"' in t)
ok('privacy link rendered', 'href="https://example.com/privacy">Privacy policy' in t)

c = client(MARKETING_SITE='1', META_PIXEL_ID="1');alert(1);//", GOOGLE_ADS_ID='AW-1"><script>x', GOOGLE_ADS_CONVERSION='bad')
t = c.get('/landingpage').text
ok('malformed IDs ignored / sanitised', 'alert(1)' not in t and '<script>x' not in t and 'gads: ""' in t and 'gconv: ""' in t)
