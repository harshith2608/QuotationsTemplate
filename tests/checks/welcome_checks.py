"""The guided first setup (app/welcome.py) on a brand-new business (bootstrap: one admin 'owner', no quotations):
the first sign-in opens it, one question a page with Skip for now, typical rates to check and change, the app's own
quotation pages with the tour's strip, the last page, leaving and starting again, the console's line. Bring your old
quotation comes back to "These are your rates" (the AI is replaced by a fake, so nothing leaves the machine)."""
import io
import json
import os

from werkzeug.security import generate_password_hash

from app import create_app, db, welcome as W, ai_import as AI
from app.models import AppSetting, BoqItem, Project, User

for k in ['DEMO_MODE', 'MARKETING_SITE', 'AI_IMPORT', 'ANTHROPIC_API_KEY']:
    os.environ.pop(k, None)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
loc = lambda r: r.headers.get('Location', '')

c = app.test_client()
r = c.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
ok('first sign-in of a new business\'s admin opens the guided setup', r.status_code == 302 and loc(r).endswith('/welcome/'))
r = c.get('/welcome/')
ok('…at step 1, your business', loc(r).endswith('/welcome/business'))
t = c.get('/welcome/business').text
ok('step 1: one question, no menu, step 1 of 6, Skip for now and I\'ll explore on my own', 'Your business' in t
   and 'Step 1 of 6' in t and 'Skip for now' in t and 'explore on my own' in t and 'id="ki-navbar"' not in t)
r = c.post('/welcome/business', data={'name': 'Nest & Grain Interiors', 'phone': '90000 00021'}, follow_redirects=True)
with app.app_context():
    ok('"These details are correct" must be ticked (required on the page, and nothing saved without it)',
       'name="confirm" id="wConfirm" value="1" required' in t and 'Tick &#34;These details are correct&#34; to continue' in r.text
       and not AppSetting.get('company_mobile') and W.step() == 'business')
r = c.post('/welcome/business', data={'name': 'Nest & Grain Interiors', 'phone': '90000 00021', 'confirm': '1'})
with app.app_context():
    ok('…saves the name and phone, then step 2', loc(r).endswith('/welcome/') and AppSetting.get('company_name') == 'Nest & Grain Interiors'
       and AppSetting.get('company_mobile') == '+91 90000 00021' and W.step() == 'units')
r = c.post('/welcome/business', data={'name': 'Nest & Grain Interiors', 'phone': 'call me 98abc', 'confirm': '1'}, follow_redirects=True)
with app.app_context():
    ok('…a phone with letters (or too short) is refused, the saved one kept', 'digits only' in r.text
       and AppSetting.get('company_mobile') == '+91 90000 00021')
    W.go_to('units'); db.session.commit()
r = c.get('/welcome/')
t = c.get('/welcome/units').text
ok('step 2: how you measure, four units', loc(r).endswith('/welcome/units') and 'Feet &amp; inches' in t and 'Millimetres' in t
   and 'Step 2 of 6' in t)
c.post('/welcome/units', data={'size_unit': 'mm', 'area_unit': 'sqft'})
with app.app_context():
    ok('…saved (mm, per sqft), then step 3', AppSetting.get('size_unit') == 'mm' and W.step() == 'pricing')
with app.app_context():                     # every kind switched on (console → Features → Kinds of business)
    from app import business
    AppSetting.set(business.KINDS_KEY, json.dumps(list(W.KINDS))); db.session.commit()
t = c.get('/welcome/work').text
ok('step 3 asks what you mostly do first: interiors and the businesses that measure', 'Step 3 of 6' in t and all(k in t for k in (
   'Interiors, modular kitchens &amp; wardrobes', 'Turnkey', 'uPVC windows', 'Tiles, flooring', 'Construction', 'Painting',
   'False ceiling', 'Steel fabrication', 'Curtains', 'Glass &amp; aluminium', 'Something else')))
r = c.post('/welcome/work', data={'kind': 'upvc'})
with app.app_context():
    from app import boq as B
    ok('…uPVC (not interiors): priced by item without being asked, on to step 4', loc(r).endswith('/welcome/')
       and B.enabled() and W.step() == 'rates' and W.state()['pricing'] == 'item' and W.state()['kind'] == 'upvc')
ok('…and not offered the by material page', loc(c.get('/welcome/pricing')).endswith('/welcome/work'))
r = c.post('/welcome/work', data={'kind': 'interiors'})
ok('…interiors: asked how they price', loc(r).endswith('/welcome/pricing'))
t = c.get('/welcome/pricing').text
ok('how you price: the quotation PDF each makes (in their units: mm)', 'Step 3 of 6' in t
   and 'By item' in t and 'By material' in t and 'Laminates – Box Work' in t and '2,134 mm' in t
   and 'Bill of Quantities' in t and 'CUSTOMER QUOTATION' in t)
with app.app_context():
    eg = W.pricing_examples('interiors')
    ok('…by item: each item its own rate (the loft cheaper); by material: one rate for Laminates – Box Work',
       [r['rate'] for r in eg['item'][0]['rows']] == ['1,600', '1,100']
       and eg['material'][0]['material'] == 'Laminates – Box Work'
       and [i['name'] for i in eg['material'][0]['items']] == ['Wardrobe', 'Loft']
       and eg['material'][0]['amount'] == '1,12,000.00'
       and [(x['name'], [r['name'] for r in x['rows']]) for x in eg['item']] == [
           ('Master Bedroom', ['Wardrobe', 'Loft']), ('Living Room', ['TV Unit']), ('Design & Services', ['3D Design'])]
       and eg['item_total'] == '1,83,600.00')
r = c.post('/welcome/pricing', data={'mode': 'item'})
with app.app_context():
    ok('…by item chosen: priced by item, on to step 4', B.enabled() and W.step() == 'rates' and W.state()['pricing'] == 'item')
with app.app_context():
    before = AppSetting.query.count(), BoqItem.query.count()
r = c.post('/welcome/rates', data={'kind': 'upvc'})
r2 = c.post('/welcome/rates', data={'kind': 'tiles'})
with app.app_context():
    ok('choosing a business (and changing it) saves nothing: it goes to "These are your rates" with the choice',
       loc(r).endswith('/welcome/rates/check?kind=upvc') and loc(r2).endswith('/welcome/rates/check?kind=tiles')
       and (AppSetting.query.count(), BoqItem.query.count()) == before)
t = c.get('/welcome/rates/check?kind=tiles').text
ok('…each business shows its own typical items, marked as not saved yet', 'value="Floor Tiles (2 x 2, with laying)"' in t
   and 'value="Sliding Window (2 track)"' not in t and 'nothing is saved until you tap Save my rates' in t)
t = c.get('/welcome/rates/check?kind=interiors').text
ok('"These are your rates" for interiors: in sections, the typical items (kitchens and wardrobes too), an empty row in '
   'each, Add a section', 'name="grp_0" value="Bedrooms"' in t and 'name="s0y1_name" value="Wardrobe"' in t
   and 'value="1600"' in t and 'value="Sliding Wardrobe"' in t and 'value="Magic Corner"' in t
   and 'value="Countertop (Granite)"' in t and 'name="n0x_name"' in t and 'name="n1x_name"' in t and 'Add a section' in t)
with app.app_context():
    ok('…still nothing saved', BoqItem.query.count() == before[1])
    ok('…one choice for interiors and modular kitchens', 'kitchens' not in W.KINDS)
import re as _re
form = {}
for m in _re.finditer(r'name="((?:s|grp|grpold)[^"]*)" value="([^"]*)"', t):
    if not m.group(1).endswith('_skip'):          # (unticked boxes aren't sent)
        form[m.group(1)] = m.group(2).replace('&amp;', '&')
for m in _re.finditer(r'name="(s\d+y\d+_unit)"[^>]*>(.*?)</select>', t, _re.S):
    form[m.group(1)] = _re.search(r'<option selected>([^<]*)', m.group(2)).group(1)
key = lambda n: next(k for k, v in form.items() if k.endswith('_name') and v == n)[:-len('name')]
form[key('Wardrobe') + 'rate'] = '1,750'
form[key('Bed with Storage') + 'skip'] = '1'
form.update({'grp_1': 'Living Room', 'n0x_name': 'Wall Panelling', 'n0x_unit': 'sqft', 'n0x_rate': '650',
             'n0x2_name': 'Wardrobe', 'n0x2_rate': '9', 'grp_9': 'Bathrooms', 'n9x_name': 'Vanity Unit', 'n9x_unit': 'sqft',
             'n9x_rate': '1500', 'n9x2_name': 'Mirror Cabinet', 'n9x2_unit': 'nos', 'n9x2_rate': '6000'})
r = c.post('/welcome/rates/check?kind=interiors', data=form)
with app.app_context():
    from app import boq
    names = {b.name for b in BoqItem.query.all()}
    ok('Save my rates: the typical items saved (a changed rate, one left out), priced by item, not the services set',
       loc(r).endswith('/welcome/') and boq.enabled() and BoqItem.query.filter_by(name='Wardrobe').count() == 1
       and BoqItem.query.filter_by(name='Wardrobe').first().rate == 1750 and 'Bed with Storage' not in names
       and {'TV Unit', 'Base Cabinet', 'Magic Corner', 'False Ceiling'} <= names and 'Electric Wiring' not in names
       and BoqItem.query.filter_by(name='Wardrobe').first().description.startswith('Carcass') and W.step() == 'quote')
    ok('…new rows in their sections (not a second Wardrobe)', BoqItem.query.filter_by(name='Wall Panelling').first().rate == 650
       and BoqItem.query.filter_by(name='Wall Panelling').first().category == 'Bedrooms')
    ok('…a renamed section; a new section with its items',
       BoqItem.query.filter_by(name='TV Unit').first().category == 'Living Room'
       and not BoqItem.query.filter_by(category='Living & Dining').count()
       and {b.name for b in BoqItem.query.filter_by(category='Bathrooms')} == {'Vanity Unit', 'Mirror Cabinet'})
    g = json.loads(AppSetting.get('setup_guide'))
    ok('…the setup guide\'s steps are done too (company, units, pricing, rates)', {'company', 'units', 'pricing', 'rates'} <= set(g['done']))
    ok('…and what they do, for the console', W.state()['kind'] == 'interiors')
ok('Back on every step after the first (keeping the business chosen)', 'id="wBack"' not in c.get('/welcome/business').text
   and 'href="/welcome/business" class="text-decoration-none me-2" id="wBack"' in c.get('/welcome/units').text
   and 'href="/welcome/units" class="text-decoration-none me-2" id="wBack"' in c.get('/welcome/work').text
   and 'href="/welcome/work" class="text-decoration-none me-2" id="wBack"' in c.get('/welcome/pricing').text
   and 'href="/welcome/pricing" class="text-decoration-none me-2" id="wBack"' in c.get('/welcome/rates/check?kind=interiors').text)
with app.app_context():
    ok('…opening a step again puts the tour back on it', W.step() == 'rates')
t = c.get('/welcome/rates/check?kind=upvc').text
ok('after saving, another business: its typical items shown beside the saved ones (to keep or remove)',
   'value="Sliding Window (2 track)"' in t and 'name="name_' in t and 'value="Base Cabinet"' in t)
with app.app_context():
    W.go_to('quote'); db.session.commit()
r = c.get('/welcome/', follow_redirects=True)
t = r.text
ok('…and the strip on the quotation form goes back to the rates', 'href="/welcome/rates/check"' in t and '> Back</a>' in t)
ok('step 5: the new quotation form, with the strip saying what to do', 'New Quotation' in t and 'step 5 of 6' in t
   and 'Your first quotation' in t and 'Save quotation' in t)
ok('…the app\'s menu is there on the real pages', 'id="ki-navbar"' in t)
t = c.get('/projects').text
ok('elsewhere: the strip offers to continue setting up', 'Continue setting up' in t)
with app.app_context():
    u = User.query.filter_by(username='owner').first()
    p = Project(customer_name='Ravi Example', mobile='9000000021', created_by=u.id, grand_total=1000,
                discount_type='none', discount_value=0, status='complete')
    db.session.add(p); db.session.commit()
    pid = p.id
t = c.get(f'/projects/{pid}').text
ok('step 6 on the saved quotation: its PDF and Send on WhatsApp, Finish', 'step 6 of 6' in t and 'Quotation PDF' in t
   and 'Finish' in t)
r = c.post('/welcome/skip/send', data={'done': '1'})
t = c.get('/welcome/done').text
with app.app_context():
    ok('Finish: "You\'re set up", with what\'s left for later', loc(r).endswith('/welcome/done') and "You're set up" in t
       and 'Payment details' in t and 'Terms &amp; conditions' in t and not W.active())
    ok('the console says it\'s finished, and what they do', W.console_text(AppSetting.get(W.KEY)) == 'finished · Interiors, modular kitchens & wardrobes (plywood, PVC or WPC)')
ok('the strip is gone once finished', 'Continue setting up' not in c.get('/projects').text
   and 'step 5 of 6' not in c.get('/projects/new').text)
c.get('/logout')
r = c.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
ok('later sign-ins go to the quotations as usual', loc(r).endswith('/projects'))

# Skip for now, leaving, starting again
c.post('/welcome/restart')
r = c.post('/welcome/skip/business')
with app.app_context():
    ok('Skip for now: on to the next step, remembered', W.step() == 'units' and 'business' in W.state()['skipped'])
r = c.post('/welcome/exit')
with app.app_context():
    ok('I\'ll explore on my own: the quotations, the tour left, the console says where', loc(r).endswith('/projects')
       and not W.active() and W.console_text(AppSetting.get(W.KEY)).startswith('left at step 2, how you measure'))
ok('…the setup guide offers the guided setup again', 'Take the guided setup' in c.get('/admin/setup').text)
ok('…and no strip', 'Continue setting up' not in c.get('/projects').text)
c.post('/welcome/restart')
with app.app_context():
    ok('starting again: step 1', W.step() == 'business')

# Bring your old quotation: back to "These are your rates", then the quotation rebuilt
READING = AI.Quote(job_title='2 BHK interiors', sections=[AI.Section(name='Master Bedroom', lines=[
    AI.Line(name='Wardrobe', description='Laminate', size='', unit='sqft', quantity=70, rate=1450, amount=101500),
    AI.Line(name='Loft', description='', size='', unit='sqft', quantity=20, rate=1200, amount=24000)])],
    charges=[], subtotal=125500, discount=None, gst_percent=None, grand_total=None, payment_terms='', notes_and_terms='')
AI.read = lambda body: (READING, {'in': 100, 'out': 100})
os.environ['AI_IMPORT'], os.environ['ANTHROPIC_API_KEY'] = '1', 'test-key-not-real'
for key in ('business', 'units'):
    c.post(f'/welcome/skip/{key}')
def no_rates_yet():
    with app.app_context():
        from app import boq
        BoqItem.query.delete()
        boq.set_enabled(False)
        AppSetting.set('setup_guide', json.dumps({'seen': True}))
        st = W.state(); st.pop('added', None); AppSetting.set(W.KEY, json.dumps(st))
        db.session.commit()


no_rates_yet()
r = c.post('/welcome/rates', data={'kind': 'upvc'})
with app.app_context():
    ok('with Bring your old quotation on, uPVC (a business that measures) isn\'t asked for a file: its typical items',
       loc(r).endswith('/welcome/rates/check?kind=upvc') and BoqItem.query.count() == 0)
t = c.get('/welcome/rates/check?kind=upvc').text
ok('…in its sections (Windows, Doors, Extras)', all(f'value="{g}"' in t for g in ('Windows', 'Doors', 'Extras'))
   and 'value="Sliding Window (2 track)"' in t and 'value="Wardrobe"' not in t)
no_rates_yet()
r = c.post('/welcome/rates', data={'kind': 'interiors'})
t = c.get('/welcome/rates/file?kind=interiors').text
ok('interiors with Bring your old quotation on: do you have a file?', loc(r).endswith('/welcome/rates/file?kind=interiors')
   and 'old quotation or your rate list' in t and 'Yes, upload it' in t and 'No, start with typical rates' in t
   and 'href="/welcome/pricing" class="text-decoration-none me-2" id="wBack"' in t)
r = c.post('/welcome/rates/file?kind=interiors', data={'file': 'no'})
ok('…no: its typical items, not saved yet', loc(r).endswith('/welcome/rates/check?kind=interiors'))
r = c.post('/welcome/rates/file?kind=interiors', data={'file': 'yes'})
ok('…yes: the upload page, with the strip', loc(r).endswith('/admin/import') and 'step 4 of 6' in c.get('/admin/import').text)
form = {'job_title': '2 BHK interiors', 'discount': '0', 'gst': '', 'sections': '1', 'charges': '0', 's0_name': 'Master Bedroom',
        's0_lines': '2', 's0_0_keep': '1', 's0_0_name': 'Wardrobe', 's0_0_unit': 'sqft', 's0_0_quantity': '70', 's0_0_rate': '1450',
        's0_1_keep': '1', 's0_1_name': 'Loft', 's0_1_unit': 'sqft', 's0_1_quantity': '20', 's0_1_rate': '1200',
        'pricing': 'item', 'payment_terms': '', 'notes': ''}
r = c.post('/admin/import/set-up', data=form)
with app.app_context():
    rebuilt = W.state().get('project')
    ok('…set up from it: back to "These are your rates", the rebuilt quotation remembered', loc(r).endswith('/welcome/rates/check')
       and rebuilt and Project.query.get(rebuilt) is not None
       and BoqItem.query.filter_by(name='Wardrobe').first().rate == 1450)
c.post('/welcome/rates/check', data={})
r = c.get('/welcome/quote')
ok('step 5 after a file: their old quotation, rebuilt here', loc(r).endswith(f'/projects/{rebuilt}')
   and 'step 6 of 6' in c.get(f'/projects/{rebuilt}').text)

# Not for staff, not for businesses already using the app
with app.app_context():
    db.session.add(User(username='rahul', password_hash=generate_password_hash('rahul-pass-123'), role='staff'))
    db.session.commit()
s = app.test_client()
r = s.post('/login', data={'username': 'rahul', 'password': 'rahul-pass-123'})
ok('staff never see it', loc(r).endswith('/projects') and s.get('/welcome/business').status_code == 404
   and 'Continue setting up' not in s.get('/projects').text)

# ── A trial's phone from the trial request, without the 91: shown as an Indian mobile, not "+7675801918" ──
from app.ops import phone_display
ok('trial phone: a 10-digit mobile → +91 98765 43210, with or without 91 / 0 / +',
   {phone_display(x) for x in ('9876543210', '919876543210', '09876543210', '+9876543210')} == {'+91 98765 43210'})
with app.app_context():
    AppSetting.set('company_mobile', '+9876543210'); db.session.commit()
c.post('/welcome/restart')
ok('…a number saved the old way is shown right on step 1', 'value="+91 98765 43210"' in c.get('/welcome/business').text)


# ── Priced by material: their materials and rates on step 4 ──
import re as _re
c.post('/welcome/restart')
r = c.post('/welcome/pricing', data={'mode': 'material'})
with app.app_context():
    from app import boq as B
    ok('by material chosen: priced by material', not B.enabled() and W.by_material() and W.step() == 'rates')
r = c.post('/welcome/rates', data={'kind': 'furniture'})
ok('…what you do → your materials and rates (not item lines)', loc(r).endswith('/welcome/rates/materials?kind=furniture'))
ok('…and the item lines page sends you there too', loc(c.get('/welcome/rates/check?kind=furniture')).endswith(
   '/welcome/rates/materials?kind=furniture'))
t = c.get('/welcome/rates/materials?kind=furniture').text
ids = dict((n, i) for i, n in _re.findall(r'name="m(\d+)_[^"]+"[^>]*aria-label="([^,"]+)', t))
ok('…each material with its Box Work and Frame Work rates, or one rate', 'Laminates' in ids and 'Box Work' in t
   and 'one rate' in t)
lam, ven = ids['Laminates'], ids.get('Veneer')
form = {f'm{lam}_Box Work': '1650', f'm{lam}_Frame Work': '1250', 'nm_name': 'PU', 'nm_rate': '2200', 'nm_type': 'work',
        'nm2_name': 'Wallpaper', 'nm2_rate': '120', 'nm2_type': 'one'}
if ven:
    form[f'm{ven}_hide'] = '1'
r = c.post('/welcome/rates/materials?kind=furniture', data=form)
with app.app_context():
    from app.models import ItemRate, Material
    rate = lambda w, k: (ItemRate.query.filter_by(wood_type=w, work_type=k).first() or ItemRate(rate_per_sqft=-1)).rate_per_sqft
    ok('…saved: rates changed, new materials (Box & Frame Work, one rate), a hidden one', rate('Laminates', 'Box Work') == 1650
       and rate('Laminates', 'Frame Work') == 1250 and rate('PU', 'Box Work') == 2200 and rate('PU', 'Frame Work') == 2200
       and rate('Wallpaper', '') == 120 and (not ven or not Material.query.filter_by(name='Veneer').first().active))
    ok('…still priced by material, on to the first quotation', not B.enabled() and W.step() == 'quote'
       and W.state()['kind'] == 'furniture')
t = c.get('/projects/new').text
ok('…the strip on the quotation form goes back to the materials', 'href="/welcome/rates/materials"' in t)
