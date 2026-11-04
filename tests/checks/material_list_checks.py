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


def rooms(width=7, tandem=4, boq_names=('Switch Board Shifting', 'Wall putty touch-up')):
    return json.dumps([
        {'name': 'Master Bedroom', 'items': [
            {'name': 'Wardrobe', 'length': 9, 'width': width, 'wood_type': 'Laminates', 'work_type': 'Box Work'},
            {'name': 'Mirror', 'length': 5, 'width': 3, 'wood_type': 'Glass', 'work_type': ''},
            {'name': 'Tandem Drawer', 'type': 'fixed', 'quantity': tandem, 'unit_price': 4500},
            {'name': 'Hob & Chimney Installation', 'type': 'fixed', 'quantity': 1, 'unit_price': 1500}]},
        {'name': 'Whole House', 'items': [
            {'name': boq_names[0], 'type': 'boq', 'quantity': 20, 'unit': 'point', 'unit_price': 850},
            {'name': boq_names[1], 'type': 'boq', 'quantity': 400, 'unit': 'sqft', 'unit_price': 22},
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

ok('the quotation page has the Select materials button', f'/projects/{pid}/materials/select' in c.get(f'/projects/{pid}').text
   and 'Select materials' in c.get(f'/projects/{pid}').text)
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
   q('Switch Board Shifting') == (20, 'Point', 'Electrical') and q('Wall putty touch-up') == (400, 'Sq.ft', 'Paint')
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

# ── Select materials: what the quotation needs ticked, everything else to tick ──
import re as _re
save_quote('/projects/new', 'Select Home', rooms())
with app.app_context():
    pid5 = Project.query.order_by(Project.id.desc()).first().id
    others = [o['name'] for o in plywood.context()['options'] if o['active'] and o['name'] != ply]
sp = c.get(f'/projects/{pid5}/materials/select').text
ok('select: the list is made and its lines are ticked', lines(pid5) and all(
    _re.search(rf'name="l{ln.id}_on" id="l{ln.id}_on" checked', sp) for ln in lines(pid5).values()))
ok('…the other plywoods are there to tick (not ticked)', not others or all(
    ML.render_name('Plywood ({plywood})', '', o) in sp for o in others))
ok('…fittings not on this quotation are there; a service is not', 'Hob &amp; Chimney Installation' not in sp)
ok('…no prices', '₹' not in sp and '4500' not in sp)
L5 = lines(pid5)
cat = {m.group(2): m.group(1) for m in _re.finditer(r'name="(c\d+)_name" value="([^"]+)"', sp)}
form = {f'l{ln.id}_seen': '1' for ln in L5.values()}
form.update({f'l{ln.id}_on': 'on' for ln in L5.values() if ln.name != 'Screws (box of 100)'})
form.update({f'l{ln.id}_qty': ln.quantity for ln in L5.values()})
form[f'l{L5["Tandem Drawer"].id}_qty'] = '5'
pick = next(n for n in cat if n not in L5)
form.update({f'{cat[pick]}_on': 'on', f'{cat[pick]}_name': pick, f'{cat[pick]}_qty': '2', f'{cat[pick]}_unit': 'nos',
             f'{cat[pick]}_group': 'Hardware'})
form.update({'new_name': ['Asian Royale emulsion', ''], 'new_qty': ['4', ''], 'new_unit': ['litres', ''],
             'new_group': ['Paint', 'Paint']})
r = c.post(f'/projects/{pid5}/materials/select', data=form, follow_redirects=True)
L5 = lines(pid5)
ok('select saved → the list page to copy', 'Copy all' in r.text and 'material list is ready' in r.text)
ok('…an unticked line is removed (and still a choice next time)', 'Screws (box of 100)' not in L5
   and 'Screws (box of 100)' in c.get(f'/projects/{pid5}/materials/select').text)
ok('…a quantity changed', L5['Tandem Drawer'].quantity == 5 and L5['Tandem Drawer'].edited)
ok('…a ticked choice and a typed item are added', (L5[pick].quantity, L5[pick].kind) == (2, 'manual')
   and (L5['Asian Royale emulsion'].quantity, L5['Asian Royale emulsion'].category) == (4, 'Paint'))
ok('…an item typed on one list is a choice on the next', 'Asian Royale emulsion' in c.get(f'/projects/{pid}/materials/select').text)

# ── Admin → Material rules: one sentence per rule ──
rp = c.get('/admin/material-rules')
ok('the rules page opens: plain sentences, no change needed', rp.status_code == 200 and "have to change anything" in rp.text
   and 'for every' in rp.text and '{plywood}' not in rp.text and '[ply]' in rp.text)
ok('…plywood shown as "1 sheet for every 9.09 sqft" (0.11 per sqft)', 'value="9.09"' in rp.text)


def card(r_, **change):
    """A rule card as the page posts it."""
    amount, every = ML.coverage(r_.per_sqft)
    target = f'b:{ML.rule_boq(r_)}' if ML.rule_boq(r_) else f'w:{r_.work_type or ""}'
    p = f'r{r_.id}_'
    row = {p + 'name': ML.name_shown(r_.name), p + 'group': r_.category, p + 'amount': amount, p + 'every': every,
           p + 'unit': r_.unit, p + 'wastage': r_.wastage, p + 'target': target, p + 'active': 'on',
           p + 'up': 'on' if r_.round_up else '', p + 'mat': ML.rule_materials(r_),
           p + 'allmat': '' if ML.rule_materials(r_) else 'on', p + 'remove': ''}
    row.update({p + k: v for k, v in change.items()})
    return row


with app.app_context():
    rule = MaterialRule.query.filter_by(name='Plywood ({plywood})', work_type='Box Work').first()
    rid = rule.id
    rule_rows = {}
    for r_ in ML.rules():
        rule_rows.update(card(r_, **({'amount': '1', 'every': '5'} if r_.id == rid else {})))
rule_rows.update({'section': 'rules', 'new_name': 'Hinges', 'new_group': 'Hardware', 'new_amount': '1', 'new_every': '10',
                  'new_unit': 'nos', 'new_wastage': '0', 'new_target': 'w:Box Work', 'new_allmat': 'on', 'new_up': 'on',
                  'new_active': 'on',
                  'new2_name': 'Drawer channels', 'new2_group': 'Hardware', 'new2_amount': '1', 'new2_every': '20',
                  'new2_unit': 'pairs', 'new2_wastage': '0', 'new2_target': 'w:', 'new2_allmat': 'on', 'new2_up': 'on',
                  'new2_active': 'on', 'new3_name': ''})
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
ok('a changed rule is used on the next list (1 sheet for every 5 sqft: 63 / 5 + 10% → 14 sheets)', L3[PLY].quantity == 14)
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
ok('rules shown per sq m when the business uses sq m (1 sheet for every 5 sqft = 2.153 sheets for every sq m)',
   'sq m</span>' in rp and 'value="2.153"' in rp)
with app.app_context():
    AppSetting.set('area_unit', 'sqft'); db.session.commit()

# ── Rules on BOQ lines: typical ones for usual names, in place of the line ──
from app.models import BoqItem
with app.app_context():
    for name, unit in (('Wall painting', 'sqft'), ('Floor tiling', 'sqft'), ('Electrical points', 'point'), ('Site Cleaning', 'lump sum')):
        if not BoqItem.query.filter_by(name=name).first():
            db.session.add(BoqItem(name=name, unit=unit, rate=10))
    db.session.commit()
rp = c.get('/admin/material-rules').text
with app.app_context():
    on_line = {}
    for r_ in ML.rules():
        if ML.rule_boq(r_):
            on_line.setdefault(ML.rule_boq(r_), []).append(r_.name)
ok('typical rules added for usual BOQ lines (painting, tiles, points); none for a lump sum',
   {'Wall putty (40 kg bag)', 'Primer', 'Emulsion paint'} <= set(on_line.get('Wall painting', []))
   and 'Tile adhesive (20 kg bag)' in on_line.get('Floor tiling', []) and on_line.get('Electrical points')
   and 'Site Cleaning' not in on_line)
ok('…the BOQ lines are choices on the rules page, with their unit', 'value="b:Wall painting"' in rp and 'data-unit="Point"' in rp)
save_quote('/projects/new', 'Paint Home', rooms(boq_names=('Electrical points', 'Wall painting')))
with app.app_context():
    pid6 = Project.query.order_by(Project.id.desc()).first().id
c.get(f'/projects/{pid6}/materials')
L6 = lines(pid6)
ok('a BOQ line with rules: what it needs, in place of the line (400 sqft: 1 bag putty, 5 L primer → 5, 8 L emulsion + 10% → 9)',
   'Wall painting' not in L6 and (L6['Wall putty (40 kg bag)'].quantity, L6['Primer'].quantity, L6['Emulsion paint'].quantity) == (2, 5, 9)
   and L6['Primer'].source == 'Wall painting (Whole House)')
ok('…20 points: 3 coils of wire, 63 conduit pipes; no line for the points', 'Electrical points' not in L6
   and L6['Wire 1.5 sq mm (90 m coil)'].quantity == 3 and L6['PVC conduit pipe (3 m)'].quantity == 63)
with app.app_context():
    putty = next(r_ for r_ in ML.rules() if r_.name == 'Wall putty (40 kg bag)' and ML.rule_boq(r_) == 'Wall painting')
    gone = [r_ for r_ in ML.rules() if ML.rule_boq(r_) == 'Electrical points']
    form = {}
    for r_ in ML.rules():
        form.update(card(r_, **({'every': '200'} if r_.id == putty.id else {'remove': '1'} if r_ in gone else {})))
form.update({'section': 'rules', 'new_name': 'Masking tape', 'new_group': 'Paint', 'new_amount': '1', 'new_every': '200',
             'new_unit': 'rolls', 'new_wastage': '0', 'new_target': 'b:Wall painting', 'new_up': 'on', 'new_active': 'on'})
c.post('/admin/material-rules', data=form)
with app.app_context():
    putty = next(r_ for r_ in ML.rules() if r_.name == 'Wall putty (40 kg bag)' and ML.rule_boq(r_) == 'Wall painting')
    tape = next((r_ for r_ in ML.rules() if r_.name == 'Masking tape'), None)
    ok('a BOQ rule changed (1 bag for every 200 sqft), a new one on a BOQ line, deleted ones stay deleted',
       abs(putty.per_sqft - 1 / 200) < 1e-9 and ML.rule_boq(putty) == 'Wall painting' and tape and ML.rule_boq(tape) == 'Wall painting'
       and not any(ML.rule_boq(r_) == 'Electrical points' for r_ in ML.rules()))
    ML.seed(); ok('…and typical rules are not added back', not any(ML.rule_boq(r_) == 'Electrical points' for r_ in ML.rules()))
c.post(f'/projects/{pid6}/materials/rebuild')
L6 = lines(pid6)
ok('rebuilt: 3 bags of putty (400 / 200 + 5%), 2 rolls of tape, and the points back as a line', L6['Wall putty (40 kg bag)'].quantity == 3
   and L6['Masking tape'].quantity == 2 and L6['Electrical points'].quantity == 20)

# ── Who ──
staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
ok('staff without access to the quotation can\'t open its list', staff.get(f'/projects/{pid}/materials').status_code == 403)
ok('…or the rules', staff.get('/admin/material-rules').status_code in (302, 403))
c.post(f'/projects/{pid4}/delete')
with app.app_context():
    ok('a quotation deleted → its list goes too', db.session.get(Project, pid4) is None
       and MaterialList.query.filter_by(project_id=pid4).count() == 0)
