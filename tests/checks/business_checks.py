"""What kind of business it is (app/business.py) and the words that follow: an interiors business (and one that never
said) sees what it always saw; a uPVC or construction business sees its own examples, suggestions and section word,
no interiors tagline, a neutral thank-you, and AI helpers told what it does. The trial form offers every kind."""
import json
from app import create_app, db, business, boq
from app.models import AppSetting, BoqItem, Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client()
c.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
c.post('/welcome/exit')


def kind(value):
    with app.app_context():
        business.set_kind(value) if value else AppSetting.set(business.KEY, '')
        db.session.commit()


# ── Never said: interiors, as before ──
with app.app_context():
    ok('a business that never said is interiors', business.kind() == 'interiors' and business.is_interiors())
new = c.get('/projects/new').text
ok('interiors: the tagline, "e.g. Wardrobe", Rooms, the interiors suggestions',
   'Interior Design &amp; Furnishing Solutions' in new and 'placeholder="e.g. Wardrobe"' in new
   and 'Rooms &amp; Items' in new and '<option value="Wardrobe">' in new)

# ── uPVC ──
kind('upvc')
with app.app_context():
    boq.set_enabled(True, starter=False)
    db.session.add(BoqItem(name='Sliding Window (2 track)', unit='sqft', rate=550)); db.session.commit()
    p = business.profile()
ok('uPVC: its own examples, room by room', p['kind'] == 'upvc' and p['section'] == 'Room'
   and p['item_example'] == 'Sliding Window (2 track)' and not p['interiors'])
new = c.get('/projects/new').text
ok('…no interiors tagline in the footer', 'Interior Design' not in new)
ok('…its own item example and suggestions (its lines, not wardrobes)', 'placeholder="e.g. Sliding Window (2 track)"' in new
   and '<option value="Wardrobe">' not in new and '<option value="Sliding Window (2 track)">' in new)
ok('…the section words for the form', '"section": "Room"' in new and '"example": "Hall"' in new)
ok('…login page without "Interior Design"', 'Interior Design' not in app.test_client().get('/login').text)
st = c.get('/admin/settings?tab=company').text
ok('…no interiors tagline as the Settings placeholder', 'Interior Design &amp; Furnishing' not in st)
setup = c.get('/admin/setup').text
ok('…Setup guide examples are its own', 'wardrobe, false ceiling' not in setup and 'sliding window' in setup.lower())

from app import ai_tools, pdf_utils
with app.test_request_context():
    draft = ai_tools._for_business(ai_tools.DRAFT_PROMPT, ai_tools.DRAFT_OTHER)
    check = ai_tools._for_business(ai_tools.CHECK_PROMPT, ai_tools.CHECK_OTHER)
    thanks = pdf_utils._thank_you_text()
ok('…AI helpers told what it does (no interior designer, no hob and chimney)', "interior designer" not in draft
   and 'upvc windows' in draft.lower() and 'hob' not in check and 'mosquito mesh' in check)
ok('…a neutral thank-you on the PDF', 'working with you' in thanks and 'transforming' not in thanks)

save = c.post('/projects/new', data={'customer_name': 'Window Home', 'mobile': '9000000777', 'discount_type': 'none',
                                     'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Hall', 'items': [
                                         {'name': 'Sliding Window (2 track)', 'type': 'boq', 'quantity': 24,
                                          'unit': 'sqft', 'unit_price': 550}]}])})
with app.app_context():
    pid = Project.query.order_by(Project.id.desc()).first().id
view = c.get(f'/projects/{pid}').text
ok('…the quotation page: Room by room, no "Summary by material" on a by-item invoice',
   'Room-by-Room Breakdown' in view and 'Summary by material' not in view)

# ── Construction: Areas ──
kind('construction')
new = c.get('/projects/new').text
ok('construction: Areas, its own section suggestions', 'Areas &amp; Items' in new and 'Add First Area' in new
   and '<option value="Ground Floor">' in new and '<option value="Master Bedroom">' not in new)
with app.test_request_context():
    check = ai_tools._for_business(ai_tools.CHECK_PROMPT, ai_tools.CHECK_OTHER)
ok('…the AI check: its own often-missed things', 'waterproofing' in check)

# ── Back to interiors ──
kind('interiors')
new = c.get('/projects/new').text
ok('interiors chosen: as before', 'Interior Design &amp; Furnishing Solutions' in new and 'placeholder="e.g. Wardrobe"' in new)
kind('kitchens')
with app.app_context():
    ok('an old kind (modular kitchens) is interiors', business.kind() == 'interiors')

# ── The trial form ──
from app import marketing, signup
ok('the trial form offers every kind, and each can set up its own app',
   {'tiles', 'construction', 'painting', 'ceiling', 'fabrication', 'curtains', 'turnkey'} <= set(marketing.BUSINESS_TYPES)
   and set(marketing.BUSINESS_TYPES) - {'other'} == signup.ELIGIBLE)

# ── Kinds of business offered (the console's Features → Kinds of business) ──
with app.app_context():
    ok('not saved yet: the kinds offered before (interiors, furniture, uPVC, glass, something else)',
       business.kinds_offered() == ['interiors', 'furniture', 'upvc', 'glass', 'other'])
    AppSetting.set(business.KINDS_KEY, json.dumps(['tiles', 'painting'])); db.session.commit()
with app.app_context():
    ok('saved: those kinds, with interiors and something else always',
       business.kinds_offered() == ['interiors', 'tiles', 'painting', 'other'])
    ok('…the trial form\'s types follow (modular kitchens is interiors)', business.offered('tiles')
       and business.offered('kitchens') and not business.offered('upvc') and not business.offered('construction'))
with app.test_request_context():
    types = [k for k, _ in marketing._context()['business_types']]
ok('…the website\'s trial form shows only those', types == ['interiors', 'kitchens', 'tiles', 'painting', 'other'])
c.post('/welcome/restart')
kp = c.get('/welcome/work').text
ok('…the guided setup offers only those', 'value="tiles"' in kp and 'value="painting"' in kp and 'value="upvc"' not in kp
   and 'value="interiors"' in kp)
kind('upvc')
with app.app_context():
    from app import welcome as W
    s = W.state(); s['kind'] = 'upvc'; W._store(s); db.session.commit()
ok('…a business that chose a kind since switched off still sees it', 'value="upvc"' in c.get('/welcome/work').text)

from app import seed
with app.app_context():
    seed._clear_all_tables()
    ok('the website keeps the choice on the demo\'s nightly reset', AppSetting.get(business.KINDS_KEY) is not None
       and AppSetting.get(business.KEY) is None)
