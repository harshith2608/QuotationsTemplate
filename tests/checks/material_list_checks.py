"""The material list (app/material_list.py): built from a quotation by the rules (wastage, rounded up to whole sheets),
fittings and BOQ lines as they are (services and lump sums left out), grouped; edited (quantities, removed and added
lines, a line moved to another group is remembered); Rebuild keeps the edits; per-group WhatsApp text with no prices;
Admin → Material rules (rules, groups renamed or removed, the business's area unit); who may see and change it.
Off until switched on for every business."""
import json
import os
from urllib.parse import unquote
from app import create_app, db, boq, plywood
from app import material_list as ML
from app.models import AppSetting, MaterialList, MaterialRule, Project, User

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
os.environ.pop('MATERIAL_LIST', None)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})

# ── Off until switched on, for every business (MATERIAL_LIST=1 here; the console's switch in the shared app) ──
with app.app_context():
    first = Project.query.first().id
ok('off: no Material list button, no Material rules link', '/materials' not in c.get(f'/projects/{first}').text
   and 'material-rules' not in c.get('/admin/rates').text)
ok('off: its pages are not there', c.get(f'/projects/{first}/materials').status_code == 404
   and c.get('/admin/material-rules').status_code == 404)
os.environ['MATERIAL_LIST'] = '1'
ok('on: the Material rules link on Rates', 'material-rules' in c.get('/admin/rates').text)

with app.app_context():
    ok('database ready for material lists', ML.ready())
    boq.set_enabled(True); db.session.commit()
    ply = plywood.project_plywood(Project.query.first()) or ''
PLY = ML.render_name('Plywood ({plywood})', '', ply)


def rooms(width=7, tandem=4):
    return json.dumps([
        {'name': 'Master Bedroom', 'items': [
            {'name': 'Wardrobe', 'length': 9, 'width': width, 'wood_type': 'Laminates', 'work_type': 'Box Work'},
            {'name': 'Mirror', 'length': 5, 'width': 3, 'wood_type': 'Glass', 'work_type': ''},
            {'name': 'Tandem Drawer', 'type': 'fixed', 'quantity': tandem, 'unit_price': 4500},
            {'name': 'Hob & Chimney Installation', 'type': 'fixed', 'quantity': 1, 'unit_price': 1500}]},
        {'name': 'Whole House', 'items': [
            {'name': 'Electrical points', 'type': 'boq', 'quantity': 20, 'unit': 'point', 'unit_price': 850},
            {'name': 'Wall painting', 'type': 'boq', 'quantity': 400, 'unit': 'sqft', 'unit_price': 22},
            {'name': 'Site Cleaning', 'type': 'boq', 'quantity': 1, 'unit': 'lump sum', 'unit_price': 9000}]}])


def save_quote(url, name, rooms_json):
    return c.post(url, data={'customer_name': name, 'mobile': '9000000951', 'address': 'Flat 803, Sample Towers',
                             'discount_type': 'none', 'discount_value': '0', 'rooms_data': rooms_json})


def lines(pid, removed=False):
    with app.app_context():
        lst = MaterialList.query.filter_by(project_id=pid).first()
        return {ln.name: ln for ln in lst.lines if ln.removed == removed} if lst else {}


save_quote('/projects/new', 'Material Home', rooms())
with app.app_context():
    pid = Project.query.order_by(Project.id.desc()).first().id

ok('the quotation page has the Material list button', f'/projects/{pid}/materials' in c.get(f'/projects/{pid}').text)
page = c.get(f'/projects/{pid}/materials')
ok('the list opens and is made from the quotation', page.status_code == 200 and 'Material list' in page.text and lines(pid))
with app.app_context():
    ok('the starting rules are set up once', MaterialRule.query.count() > 5 and AppSetting.get(ML.SEEDED_KEY) == '1')
L = lines(pid)
q = lambda n: (L[n].quantity, L[n].unit, L[n].category) if n in L else None
# Wardrobe 9 × 7 = 63 sqft of Laminates, Box Work
ok('plywood: 63 × 0.11 + 10% = 7.6 → 8 whole sheets', q(PLY) == (8, 'sheets (8×4)', 'Wood'))
ok('back panel, outer laminate, liner: rounded up after wastage',
   q('Back panel plywood 8 mm')[0] == 3 and q('Laminates (outer finish)')[0] == 3 and q('Inner liner laminate 0.8 mm')[0] == 9)
ok('edge banding 70 m, adhesive 3 kg (Wood), screws 2 boxes (Hardware)',
   q('Edge banding tape') == (70, 'm', 'Wood') and q('Wood adhesive')[0] == 3 and q('Screws (box of 100)') == (2, 'boxes', 'Hardware'))
ok('glass is not on plywood: 15 sqft + 10% → 17 sqft, under Other', q('Glass') == (17, 'sqft', 'Other')
   and not any('Glass' in n and n != 'Glass' for n in L))
ok('fittings as they are (4 tandem drawers, Hardware); a service (Hob & Chimney Installation) left out',
   q('Tandem Drawer') == (4, 'nos', 'Hardware') and 'Hob & Chimney Installation' not in L)
ok('BOQ lines as they are, grouped by name; a lump sum left out',
   q('Electrical points') == (20, 'Point', 'Electrical') and q('Wall painting') == (400, 'Sq.ft', 'Paint')
   and 'Site Cleaning' not in L)
ok('where each line comes from', L[PLY].source == 'Wardrobe (Master Bedroom)')

# ── Sending: per group, no prices, no number chosen ──
wa = c.get(f'/projects/{pid}/materials/whatsapp?group=Wood')
txt = unquote(wa.headers.get('Location', ''))
ok('WhatsApp: a draft with no number (they choose the supplier)', wa.status_code == 302 and txt.startswith('https://wa.me/?text='))
ok('the Wood list only, with the customer and site', 'Wood list' in txt and f'{PLY} – 8 sheets (8×4)' in txt
   and 'Tandem' not in txt and 'Material Home, Flat 803, Sample Towers' in txt)
all_txt = unquote(c.get(f'/projects/{pid}/materials/whatsapp').headers['Location'])
ok('Send all: every group under its heading', all(f'*{g}*' in all_txt for g in ('Wood', 'Hardware', 'Electrical', 'Paint', 'Other')))
ok('no prices on any list', '₹' not in all_txt and '4500' not in all_txt and '850' not in all_txt and '₹' not in page.text)

# ── Editing ──
form = {f'{ln.id}_qty': ln.quantity for ln in L.values()}
form.update({f'{ln.id}_unit': ln.unit for ln in L.values()})
form.update({f'{ln.id}_name': ln.name for ln in L.values()})
form.update({f'{ln.id}_group': ln.category for ln in L.values()})
form[f'{L[PLY].id}_qty'] = '10'
form[f'{L["Screws (box of 100)"].id}_remove'] = 'on'
form[f'{L["Tandem Drawer"].id}_group'] = 'Wood'
form[f'{L["Edge banding tape"].id}_ordered'] = 'on'
form.update({'new_name': ['Wall putty', ''], 'new_qty': ['6', ''], 'new_unit': ['bags', ''], 'new_group': ['Paint', 'Paint']})
c.post(f'/projects/{pid}/materials', data=form)
L = lines(pid)
ok('a quantity changed by hand is kept (and marked edited)', L[PLY].quantity == 10 and L[PLY].edited)
ok('a removed line leaves the list (and can be put back)', 'Screws (box of 100)' not in L and 'Screws (box of 100)' in lines(pid, True))
ok('an item added by hand', L.get('Wall putty') and (L['Wall putty'].quantity, L['Wall putty'].unit, L['Wall putty'].category) == (6, 'bags', 'Paint'))
ok('ordered ticked', L['Edge banding tape'].ordered and not L[PLY].ordered)
with app.app_context():
    ok('moving a line to another group is remembered', ML.item_groups().get('tandem drawer') == 'Wood')

# ── The quotation changes → Rebuild keeps the edits ──
save_quote(f'/projects/{pid}/edit', 'Material Home', rooms(width=8, tandem=6))
ok('the list says the quotation changed', 'The quotation has changed' in c.get(f'/projects/{pid}/materials').text)
r = c.post(f'/projects/{pid}/materials/rebuild', follow_redirects=True)
L = lines(pid)
ok('rebuilt: new quantities from the new size (72 sqft: back panel 3 → 3, liner 9 → 10)', L['Inner liner laminate 0.8 mm'].quantity == 10)
ok('…the hand-typed plywood quantity kept, the removed line still removed, the added item kept',
   L[PLY].quantity == 10 and 'Screws (box of 100)' not in L and 'Wall putty' in L)
ok('…the fitting in the group it was moved to, with the new quantity', (L['Tandem Drawer'].category, L['Tandem Drawer'].quantity) == ('Wood', 6))
ok('…and it says what changed', 'Rebuilt from the quotation' in r.text and 'Inner liner laminate' in r.text
   and 'The quotation has changed' not in r.text)

save_quote('/projects/new', 'Second Home', rooms())
with app.app_context():
    pid2 = Project.query.order_by(Project.id.desc()).first().id
c.get(f'/projects/{pid2}/materials')
ok('a new list puts the remembered fitting in its group', lines(pid2)['Tandem Drawer'].category == 'Wood')

# ── Admin → Material rules ──
rp = c.get('/admin/material-rules')
ok('the rules page opens, saying the numbers are estimates', rp.status_code == 200 and 'starting numbers are' in rp.text)
with app.app_context():
    rule = MaterialRule.query.filter_by(name='Plywood ({plywood})', work_type='Box Work').first()
    rid = rule.id
    rule_rows = {f'r{r.id}_name': r.name for r in ML.rules()}
    for r_ in ML.rules():
        rule_rows.update({f'r{r_.id}_group': r_.category, f'r{r_.id}_per': r_.per_sqft, f'r{r_.id}_unit': r_.unit,
                          f'r{r_.id}_wastage': r_.wastage, f'r{r_.id}_work': r_.work_type or '',
                          f'r{r_.id}_active': 'on', f'r{r_.id}_up': 'on' if r_.round_up else ''})
        rule_rows[f'r{r_.id}_mat'] = ML.rule_materials(r_)
rule_rows[f'r{rid}_per'] = '0.2'
rule_rows.update({'section': 'rules', 'new_name': 'Hinges', 'new_group': 'Hardware', 'new_per': '0.1', 'new_unit': 'nos',
                  'new_wastage': '0', 'new_work': 'Box Work', 'new_allmat': 'on', 'new_up': 'on', 'new_active': 'on',
                  'new2_name': 'Drawer channels', 'new2_group': 'Hardware', 'new2_per': '0.05', 'new2_unit': 'pairs',
                  'new2_wastage': '0', 'new2_work': '', 'new2_allmat': 'on', 'new2_up': 'on', 'new2_active': 'on',
                  'new3_name': ''})
ok('the rules page: its empty row grows (another appears while typing in the last one)',
   'data-grow data-grow-prefix="new"' in c.get('/admin/material-rules').text)
c.post('/admin/material-rules', data=rule_rows)
with app.app_context():
    ok('several new rules saved at once (new_, new2_…; an empty one skipped)',
       {'Hinges', 'Drawer channels'} <= {r_.name for r_ in ML.rules()} and '' not in {r_.name for r_ in ML.rules()})
save_quote('/projects/new', 'Third Home', rooms())
with app.app_context():
    pid3 = Project.query.order_by(Project.id.desc()).first().id
c.get(f'/projects/{pid3}/materials')
L3 = lines(pid3)
ok('a changed rule is used on the next list (63 × 0.2 + 10% → 14 sheets)', L3[PLY].quantity == 14)
ok('a new rule for every material (63 × 0.1 → 7 hinges)', (L3['Hinges'].quantity, L3['Hinges'].category) == (7, 'Hardware'))
ok('the earlier list is not changed by the rules until it is rebuilt', lines(pid2)[PLY].quantity == 8)

with app.app_context():
    olds = ML.groups()
news = ['Carpentry' if g == 'Wood' else g for g in olds]
c.post('/admin/material-rules', data={'section': 'groups', 'group_old': olds, 'group_new': news,
                                      'group_remove': [str(olds.index('Paint'))], 'group_add': 'Plumbing'})
with app.app_context():
    ok('groups: renamed, removed, added', ML.groups() == ['Carpentry', 'Hardware', 'Electrical', 'Other', 'Plumbing'])
    ok('a renamed group is renamed on rules, lists and remembered items',
       MaterialRule.query.filter_by(category='Wood').count() == 0 and ML.item_groups()['tandem drawer'] == 'Carpentry')
L = lines(pid)
ok('a removed group\'s lines move to Other', L['Wall putty'].category == 'Other' and L[PLY].category == 'Carpentry')

c.post('/admin/material-rules', data={'section': 'items', 'item_name': ['Tandem Drawer'], 'item_group': [''], 'spare': '10'})
save_quote('/projects/new', 'Fourth Home', rooms())
with app.app_context():
    pid4 = Project.query.order_by(Project.id.desc()).first().id
c.get(f'/projects/{pid4}/materials')
ok('an item set to "Leave off the list" is left off', 'Tandem Drawer' not in lines(pid4))

# ── The business's area unit ──
with app.app_context():
    AppSetting.set('area_unit', 'sqm'); db.session.commit()
rp = c.get('/admin/material-rules').text
ok('rules shown per sq m when the business uses sq m (0.2 per sqft = 2.1528 per sq m)', 'Per sq m' in rp and 'value="2.1528"' in rp)
with app.app_context():
    AppSetting.set('area_unit', 'sqft'); db.session.commit()

# ── Who ──
staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
ok('staff without access to the quotation can\'t open its list', staff.get(f'/projects/{pid}/materials').status_code == 403)
ok('…or the rules', staff.get('/admin/material-rules').status_code in (302, 403))
c.post(f'/projects/{pid4}/delete')
with app.app_context():
    ok('a quotation deleted → its list goes too', db.session.get(Project, pid4) is None
       and MaterialList.query.filter_by(project_id=pid4).count() == 0)
