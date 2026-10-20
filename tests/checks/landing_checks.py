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
ok('1-minute demo video at the top: thumbnail only, YouTube loads on tap (no-cookie)',
   'data-yt="cJgZoWVaB80"' in t and t.index('class="hero-video"') < t.index('id="try"') and '<iframe' not in t
   and 'youtube-nocookie.com/embed/' in t)
ok('sample quote card still on the page', 'id="qcForm"' in t and 'id="qcTotal"' in t)
ok('unit-neutral steps', 'in ft and in; sqft' not in t and 'your own unit' in t)
ok('demo button → this site login', 'href="/login" data-demo>Try the live demo' in t)
ok('click events: StartTrialClick on trial buttons, DemoClick on demo, Lead on submit',
   "track('StartTrialClick')" in t and "track('DemoClick')" in t and "track('Lead', true, { value: T.leadValue, currency: 'INR', content_category: btype })" in t and "'trackCustom'" in t)
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

# Tutorials page: hidden until YouTube links are set; then a click-to-play page and header link
import os as _os
from app import marketing as _mk
ok('YouTube links and IDs are understood', _mk.youtube_id('https://youtu.be/AbCdEfGhIjK') == 'AbCdEfGhIjK'
   and _mk.youtube_id('https://www.youtube.com/watch?v=AbCdEfGhIjK&t=3') == 'AbCdEfGhIjK'
   and _mk.youtube_id('https://youtube.com/shorts/AbCdEfGhIjK?si=x') == 'AbCdEfGhIjK' and _mk.youtube_id('AbCdEfGhIjK') == 'AbCdEfGhIjK'
   and _mk.youtube_id('') == '')
from app import db as _db
from app.models import Tutorial as _Tut
from datetime import datetime as _dt
with c.application.app_context():
    _db.session.add_all([_Tut(position=i, title=t, about='About ' + t, length='1 min', updated_at=_dt.utcnow())
                         for i, t in enumerate(['Full walkthrough', '1 · Your company details', '2 · Your rates', '3 · Hidden one'])])
    _db.session.commit()
_mk._tutorials_cache.clear()
ok('no links → no Tutorials page or header link', c.get('/tutorials').status_code == 404 and 'Tutorials</a>' not in c.get('/').text)
with c.application.app_context():
    rows = _db.session.scalars(_db.select(_Tut).order_by(_Tut.position)).all()
    rows[0].youtube_id, rows[2].youtube_id = 'AAAAAAAAAAA', 'BBBBBBBBBBB'
    rows[3].youtube_id, rows[3].hidden = 'CCCCCCCCCCC', True
    _db.session.commit()
ok('changes show after the short cache', c.get('/tutorials').status_code == 404)
_mk._tutorials_cache.clear()
t = c.get('/tutorials').text
ok('tutorials page lists linked, shown videos in order (no link / hidden skipped), click-to-play', 'data-yt="AAAAAAAAAAA"' in t
   and 'data-yt="BBBBBBBBBBB"' in t and 'CCCCCCCCCCC' not in t and t.index('AAAAAAAAAAA') < t.index('BBBBBBBBBBB')
   and 'Full walkthrough' in t and '2 · Your rates' in t and '1 · Your company' not in t
   and 'youtube-nocookie.com/embed/' in t and '<iframe' not in t)
ok('header and footer link to Tutorials', c.get('/').text.count('/tutorials">Tutorials</a>') == 2)
with c.application.app_context():
    rows = _db.session.scalars(_db.select(_Tut).order_by(_Tut.position)).all()
    rows[2].wide = True
    _db.session.commit()
_mk._tutorials_cache.clear()
t = c.get('/tutorials').text
ok('a landscape video is shown wide (16:9), phone ones tall', t.count('tut-card wide') == 1
   and t.index('tut-card wide') > t.index('AAAAAAAAAAA') and 'aspect-ratio: 16 / 9' in t)
with c.application.app_context():
    _db.session.execute(_db.text('alter table tutorials drop column wide'))
    _db.session.commit()
_mk._tutorials_cache.clear()
t = c.get('/tutorials').text
ok('before the database update that adds Landscape: the page still lists the videos, all tall',
   'data-yt="BBBBBBBBBBB"' in t and 'tut-card wide' not in t)
with c.application.app_context():
    _db.session.execute(_db.text('alter table tutorials add column wide boolean not null default 0'))
    _db.session.commit()
with c.application.app_context():
    for r in _db.session.scalars(_db.select(_Tut)):
        r.youtube_id = None
    _db.session.commit()
_mk._tutorials_cache.clear()
