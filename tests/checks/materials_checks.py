"""Custom materials: each business manages its own (Glass, PU, Wallpaper…), with or without work types."""
import io, json, re
from pypdf import PdfReader
from app import create_app, db
from app.models import Material, ItemRate, Item, Project
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pdftext = lambda u: '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages)

with app.app_context():
    names = [(m.name, m.uses_work_types) for m in Material.query.order_by(Material.sort_order)]
    glass_rate = ItemRate.query.filter_by(wood_type='Glass', work_type='').first()
ok(f'new businesses start with Glass as a one-rate material {names}', ('Glass', False) in names
   and ('Acrylic', True) in names and glass_rate and glass_rate.rate_per_sqft == 450)

t = c.get('/admin/rates').text
ok('rates page lists materials with one-rate input for Glass', 'value="Glass"' in t and 'one rate' in t and 'Add a material' in t)

# Add materials
c.post('/admin/rates', data={'material_add': '1', 'mat_name': '  Wallpaper ', 'mat_rate': '120'})
c.post('/admin/rates', data={'material_add': '1', 'mat_name': 'PU Finish', 'mat_rate': '1500', 'mat_uses_work': '1'})
r = c.post('/admin/rates', data={'material_add': '1', 'mat_name': 'wallpaper', 'mat_rate': '1'}, follow_redirects=True)
ok('duplicate name refused (case-insensitive)', 'already exists' in r.text)
r = c.post('/admin/rates', data={'material_add': '1', 'mat_name': 'Bad|Name'}, follow_redirects=True)
ok('"|" in a name refused', "can&#39;t contain" in r.text or "can't contain" in r.text)
with app.app_context():
    wp = Material.query.filter_by(name='Wallpaper').first()
    pu = Material.query.filter_by(name='PU Finish').first()
    pu_rates = {r.work_type: r.rate_per_sqft for r in ItemRate.query.filter_by(wood_type='PU Finish')}
    ok('one-rate material added with its rate', wp and not wp.uses_work_types
       and ItemRate.query.filter_by(wood_type='Wallpaper', work_type='').first().rate_per_sqft == 120)
    ok(f'work-type material gets a rate per work type {pu_rates}', pu and pu.uses_work_types
       and pu_rates == {'Box Work': 1500, 'Frame Work': 1500})
    wp_id, pu_id = wp.id, pu.id

# Set a different Frame Work rate for PU in the table
c.post('/admin/rates', data={'item_rates_submit': 'save', f'name_{pu_id}': 'PU Finish', f'rate_{pu_id}_0': '1500',
                             f'rate_{pu_id}_1': '1250'})
with app.app_context():
    ok('table saves per-work-type rates', ItemRate.query.filter_by(wood_type='PU Finish', work_type='Frame Work').first().rate_per_sqft == 1250)

# The quotation form offers them
f = c.get('/projects/new').text
ok('rates card shows one-rate materials without a dangling dash', '>Glass</span>' in f and 'Glass – ' not in f)
ok('form offers Glass, Wallpaper and PU combos', '<option value="Glass|"' in f and '>Wallpaper</option>' in f
   and 'value="PU Finish|Frame Work"' in f and 'value="Laminates|Box Work" selected' in f)
ok('script catalogue has the combos', '"value": "Glass|"' in f or '"value":"Glass|"' in f)

# Save a quotation with them
rooms = [{'name': 'Living Room', 'items': [
    {'name': 'Glass Shutter', 'length': 6, 'width': 2, 'wood_type': 'Glass', 'work_type': ''},          # 12 sqft × 450
    {'name': 'Feature Wall', 'length': 10, 'width': 9, 'wood_type': 'Wallpaper', 'work_type': ''},     # 90 × 120
    {'name': 'TV Unit', 'length': 8, 'width': 6, 'wood_type': 'PU Finish', 'work_type': 'Frame Work'},  # 48 × 1250
    {'name': 'Bogus', 'length': 1, 'width': 1, 'wood_type': 'Glass', 'work_type': 'Box Work'},          # invalid combo
]}]
r = c.post('/projects/new', data={'customer_name': 'Material Test', 'mobile': '9000000099', 'rooms_data': json.dumps(rooms),
                                  'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    p = Project.query.order_by(Project.id.desc()).first()
    items = {i.name: (i.wood_type, i.work_type) for r_ in p.rooms_with_items() for i in r_.item_list}
    pid, total = p.id, p.grand_total
ok(f'items keep their material (empty work type for one-rate) {items}', items['Glass Shutter'] == ('Glass', '')
   and items['Feature Wall'] == ('Wallpaper', '') and items['TV Unit'] == ('PU Finish', 'Frame Work'))
ok('an invalid combo falls back to the default material', items['Bogus'] == ('Laminates', 'Box Work'))
ok(f'total = 12×450 + 90×120 + 48×1250 + 1×850 ({total})', total == 5400 + 10800 + 60000 + 850)

v = c.get(f'/projects/{pid}').text
ok('quotation page: one-rate materials show without a work type', '>Glass</span>' in v and 'Wallpaper' in v
   and '>Glass – ' not in v)
full = pdftext(f'/projects/{pid}/pdf')
ok('full PDF: item and summary lines labelled "Glass" / "PU Finish – Frame Work"',
   re.search(r'Glass\s+12\.00', full) and 'PU Finish – Frame Work' in full and 'Glass –' not in full and '10,800' in full)
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('customer PDF summary includes the new materials', 'Wallpaper' in cust and 'PU Finish – Frame Work' in cust)
e = c.get(f'/projects/{pid}/edit').text
ok('edit form re-selects the saved one-rate material', 'existing-rooms-data' in e and '"wood_type": "Glass"' in e.replace('":"', '": "'))

# Rename follows into quotations and rates
c.post('/admin/rates', data={'item_rates_submit': 'save', f'name_{wp_id}': 'Wall Paper', f'rate_{wp_id}_0': '130'})
with app.app_context():
    renamed = Item.query.filter_by(name='Feature Wall').first().wood_type
    ok('rename updates existing quotations and the rate', renamed == 'Wall Paper'
       and ItemRate.query.filter_by(wood_type='Wall Paper', work_type='').first().rate_per_sqft == 130
       and not ItemRate.query.filter_by(wood_type='Wallpaper').first())

# Hide: not offered for new items, still valid on the old quotation
c.post('/admin/rates', data={'item_rates_submit': f'toggle:{wp_id}'})
f = c.get('/projects/new').text
e = c.get(f'/projects/{pid}/edit').text
ok('hidden material not offered on new quotations (dropdown, script list, rates card)', 'value="Wall Paper|"' not in f
   and '"value": "Wall Paper|"' not in f and 'Wall Paper – ' not in f and '>Wall Paper</span>' not in f)
ok('…but the old quotation keeps it (marked hidden)', 'Wall Paper (hidden)' in e)
c.post(f'/projects/{pid}/edit', data={'customer_name': 'Material Test', 'mobile': '9000000099',
                                      'rooms_data': json.dumps([{'name': 'Living Room', 'items': [
                                          {'name': 'Feature Wall', 'length': 10, 'width': 9, 'wood_type': 'Wall Paper', 'work_type': ''}]}]),
                                      'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    ok('re-saving an old quotation with a hidden material keeps it', Item.query.filter_by(name='Feature Wall').first().wood_type == 'Wall Paper')

# Delete only when unused
r = c.post('/admin/rates', data={'item_rates_submit': f'delete:{wp_id}'}, follow_redirects=True)
with app.app_context():
    ok('a material used in quotations can\'t be deleted', db.session.get(Material, wp_id) is not None and 'Hide it instead' in r.text)
c.post('/admin/rates', data={'material_add': '1', 'mat_name': 'Temp', 'mat_rate': '1'})
with app.app_context():
    tid = Material.query.filter_by(name='Temp').first().id
c.post('/admin/rates', data={'item_rates_submit': f'delete:{tid}'})
with app.app_context():
    ok('an unused material can be deleted (with its rates)', db.session.get(Material, tid) is None
       and not ItemRate.query.filter_by(wood_type='Temp').first())

# Names are shown safely
c.post('/admin/rates', data={'material_add': '1', 'mat_name': "<b>Bold</b> & 'Co'", 'mat_rate': '10'})
t = c.get('/admin/rates').text
f = c.get('/projects/new').text
ok('material names are escaped on the rates page and form', '<b>Bold</b>' not in t and '<b>Bold</b>' not in f
   and '&lt;b&gt;Bold&lt;/b&gt;' in t)
