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
ok('step 1: one question, no menu, step 1 of 5, Skip for now and I\'ll explore on my own', 'Your business' in t
   and 'Step 1 of 5' in t and 'Skip for now' in t and 'explore on my own' in t and 'id="ki-navbar"' not in t)
r = c.post('/welcome/business', data={'name': 'Nest & Grain Interiors', 'phone': '90000 00021', 'confirm': '1'})
with app.app_context():
    ok('…saves the name and phone, then step 2', loc(r).endswith('/welcome/') and AppSetting.get('company_name') == 'Nest & Grain Interiors'
       and AppSetting.get('company_mobile') == '90000 00021' and W.step() == 'units')
r = c.get('/welcome/')
t = c.get('/welcome/units').text
ok('step 2: how you measure, four units', loc(r).endswith('/welcome/units') and 'Feet &amp; inches' in t and 'Millimetres' in t
   and 'Step 2 of 5' in t)
c.post('/welcome/units', data={'size_unit': 'mm', 'area_unit': 'sqft'})
with app.app_context():
    ok('…saved (mm, per sqft), then step 3', AppSetting.get('size_unit') == 'mm' and W.step() == 'rates')
r = c.get('/welcome/rates')
ok('step 3 without Bring your old quotation: straight to what you do', loc(r).endswith('/welcome/rates/kind'))
t = c.get('/welcome/rates/kind').text
ok('…four kinds of business', all(k in t for k in ('Full interiors', 'Modular kitchens', 'Turnkey', 'Something else')))
r = c.post('/welcome/rates/kind', data={'kind': 'interiors'})
with app.app_context():
    names = {b.name for b in BoqItem.query.all()}
    from app import boq
    ok('…typical interiors items, priced by item, not the services starter set', loc(r).endswith('/welcome/rates/check')
       and boq.enabled() and {'Wardrobe', 'TV Unit', 'Base Cabinet', 'False Ceiling'} <= names and 'Electric Wiring' not in names)
    wardrobe = BoqItem.query.filter_by(name='Wardrobe').first()
    bed = BoqItem.query.filter_by(name='Bed with Storage').first()
t = c.get('/welcome/rates/check').text
ok('"These are your rates": in groups, every rate there to change, an empty row to add', 'These are your rates' in t
   and 'Bedrooms' in t and f'name="rate_{wardrobe.id}"' in t and 'value="1600"' in t and 'name="new_name"' in t)
r = c.post('/welcome/rates/check', data={f'name_{wardrobe.id}': 'Wardrobe', f'unit_{wardrobe.id}': 'sqft',
                                         f'rate_{wardrobe.id}': '1,750', f'del_{bed.id}': '1',
                                         'new_name': 'Wall Panelling', 'new_unit': 'sqft', 'new_rate': '650',
                                         'new2_name': 'Wardrobe', 'new2_rate': '9'})
with app.app_context():
    ok('…saved: a changed rate, a removed item, a new one (not a second Wardrobe)', loc(r).endswith('/welcome/')
       and BoqItem.query.filter_by(name='Wardrobe').count() == 1 and BoqItem.query.filter_by(name='Wardrobe').first().rate == 1750
       and BoqItem.query.filter_by(name='Bed with Storage').first() is None
       and BoqItem.query.filter_by(name='Wall Panelling').first().rate == 650 and W.step() == 'quote')
    g = json.loads(AppSetting.get('setup_guide'))
    ok('…the setup guide\'s steps are done too (company, units, pricing, rates)', {'company', 'units', 'pricing', 'rates'} <= set(g['done']))
r = c.get('/welcome/', follow_redirects=True)
t = r.text
ok('step 4: the new quotation form, with the strip saying what to do', 'New Quotation' in t and 'step 4 of 5' in t
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
ok('step 5 on the saved quotation: its PDF and Send on WhatsApp, Finish', 'step 5 of 5' in t and 'Quotation PDF' in t
   and 'Finish' in t)
r = c.post('/welcome/skip/send', data={'done': '1'})
t = c.get('/welcome/done').text
with app.app_context():
    ok('Finish: "You\'re set up", with what\'s left for later', loc(r).endswith('/welcome/done') and "You're set up" in t
       and 'Payment details' in t and 'Terms &amp; conditions' in t and not W.active())
    ok('the console says it\'s finished', W.console_text(AppSetting.get(W.KEY)) == 'finished')
ok('the strip is gone once finished', 'Continue setting up' not in c.get('/projects').text
   and 'step 4 of 5' not in c.get('/projects/new').text)
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
t = c.get('/welcome/rates').text
ok('step 3 with Bring your old quotation: do you have a file?', 'old quotation or your rate list' in t and 'Yes, upload it' in t
   and 'No, start with typical rates' in t and 'already in' in t)
r = c.post('/welcome/rates', data={'file': 'yes'})
ok('…yes: the upload page, with the strip', loc(r).endswith('/admin/import') and 'step 3 of 5' in c.get('/admin/import').text)
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
ok('step 4 after a file: their old quotation, rebuilt here', loc(r).endswith(f'/projects/{rebuilt}')
   and 'step 5 of 5' in c.get(f'/projects/{rebuilt}').text)

# Not for staff, not for businesses already using the app
with app.app_context():
    db.session.add(User(username='rahul', password_hash=generate_password_hash('rahul-pass-123'), role='staff'))
    db.session.commit()
s = app.test_client()
r = s.post('/login', data={'username': 'rahul', 'password': 'rahul-pass-123'})
ok('staff never see it', loc(r).endswith('/projects') and s.get('/welcome/business').status_code == 404
   and 'Continue setting up' not in s.get('/projects').text)
