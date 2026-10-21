"""BOQ lines (turnkey): off by default; on per business; description, quantity, unit and rate per line; the BOQ
layout of the Initial Quotation; Full Quotation, customer link, WhatsApp text, invoice lines, revisions."""
import io, json, re
from pypdf import PdfReader
from app import create_app, db, billing, boq, layout
from app.models import AppSetting, BoqItem, Item, ItemRate, Project, Room

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pdftext = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))


def setting(key, value):
    with app.app_context():
        AppSetting.set(key, value); db.session.commit()


with app.app_context():
    LAM = ItemRate.query.filter_by(wood_type='Laminates', work_type='Box Work').first().rate_per_sqft
    ok('database ready for BOQ lines (items.description, items.unit)', boq.ready())

# ── Off by default ──
t = c.get('/projects/new').text
ok('off by default: no BOQ line option or descriptions on the form', 'modal_type_boq' not in t and 'modal_item_desc' not in t
   and '"boq": false' not in t)
c.post('/projects/new', data={'customer_name': 'BOQ Off', 'mobile': '9000000701', 'rooms_data': json.dumps([
    {'name': 'Site', 'items': [{'name': 'Demolition', 'type': 'boq', 'quantity': 1, 'unit': 'lump sum', 'unit_price': 25000,
                                'description': 'Debris removal'}]}])})
with app.app_context():
    off_pid = Project.query.order_by(Project.id.desc()).first().id      # names are encrypted: newest quotation
    it = Item.query.join(Item.room).filter(Room.project_id == off_pid).first()
    ok('off: a BOQ line sent anyway is kept as a fixed-price line (same amount)', it.item_type == 'fixed'
       and it.quantity * it.unit_price == 25000)
s = c.get('/admin/settings?tab=documents').text
ok('off: no BOQ layout in Settings → Quotation PDFs', 'il_boq' not in s)

# ── On ──
with app.app_context():
    boq.set_enabled(True); db.session.commit()
    n = BoqItem.query.count()
    fc0 = BoqItem.query.filter_by(name='False Ceiling').first()
    ok('starter lines come grouped (Services, Electrical Fitting, Lights & Points…)', BoqItem.query.filter_by(name='Fan Fitting').first().category
       == 'Electrical Fitting' and BoqItem.query.filter_by(name='COB Light 12 W').first().category == 'Lights & Points')
    ok('no woodwork in the starter lines (wardrobes, kitchen units… are measured items, priced by material)',
       not BoqItem.query.filter(BoqItem.name.in_(['Wardrobe', 'TV Unit', 'Kitchen Below Platform', 'Bed with Storage'])).count()
       and BoqItem.query.filter_by(name='False Ceiling').first() is not None)
    ok('turning BOQ lines on gives the starter lines (False Ceiling, Electric Wiring, Fan Fitting…)', n == len(boq.starter_lines())
       and fc0 and fc0.unit == 'sqft' and fc0.rate == 120 and BoqItem.query.filter_by(name='Electric Wiring').first().unit == 'point')
    boq.set_enabled(False); boq.set_enabled(True); db.session.commit()
    ok('…only once: turning it on again adds nothing', BoqItem.query.count() == n)
    # the rest of these checks start from no saved lines
    BoqItem.query.delete(); db.session.commit()
t = c.get('/projects/new').text
ok('on: BOQ line option, description box and units on the form', 'modal_type_boq' in t and 'modal_item_desc' in t
   and '<option value="lump sum">' in t)
rooms = [
    {'name': 'Other Service', 'items': [
        {'name': 'False Ceiling', 'type': 'boq', 'quantity': 696, 'unit': 'Sq.ft', 'unit_price': 120,
         'description': 'Living Room, Kitchen, passage and both Bedroom\n1. Living Room: 192+104=296'},
        {'name': 'Electric wiring', 'type': 'boq', 'quantity': 71, 'unit': 'Nos.', 'unit_price': 850,
         'description': 'Conduit, polycab wire considered'},
        {'name': 'Other Light and Fitting Charges', 'type': 'boq', 'quantity': 1, 'unit': 'nos', 'unit_price': 0,
         'description': 'COB 12 Watt 3 inch Rs 420/-, Panel Lights 15 watt Rs 500/-'},
        {'name': '3D Design', 'type': 'boq', 'quantity': 1, 'unit': 'LS', 'unit_price': 45000}]},
    {'name': 'Master Bedroom', 'items': [
        {'name': 'Wardrobe', 'length': 8, 'width': 7, 'wood_type': 'Laminates', 'work_type': 'Box Work',
         'description': 'Openable, laminate finish inside and outside'},
        {'name': 'Side Table', 'type': 'fixed', 'quantity': 1, 'unit_price': 15000, 'description': 'Two drawers'}]}]
c.post('/projects/new', data={'customer_name': 'Nazima BOQ', 'mobile': '9000000702', 'rooms_data': json.dumps(rooms),
                              'discount_type': 'fixed', 'discount_value': '10577'})
subtotal = 696 * 120 + 71 * 850 + 45000 + 56 * LAM + 15000
with app.app_context():
    p = Project.query.order_by(Project.id.desc()).first(); pid = p.id
    items = {i.name: i for i in Item.query.join(Item.room).filter(Room.project_id == pid)}
    fc, ls, info = items['False Ceiling'], items['3D Design'], items['Other Light and Fitting Charges']
    ok('BOQ line saved with its quantity, unit, rate and description', fc.item_type == 'boq' and fc.quantity == 696
       and fc.unit == 'sqft' and fc.unit_price == 120 and fc.description.startswith('Living Room, Kitchen')
       and '\n1. Living Room' in fc.description)
    ok('units cleaned: Nos. → nos, LS → lump sum; info line with rate 0 kept', items['Electric wiring'].unit == 'nos'
       and ls.unit == 'lump sum' and info.unit_price == 0)
    ok('descriptions on a measured item and a fitting', items['Wardrobe'].description.startswith('Openable')
       and items['Side Table'].description == 'Two drawers')
    ok('total: BOQ lines + measured + fittings, discount', round(p.grand_total, 2) == round(subtotal, 2)
       and round(p.final_total, 2) == round(subtotal - 10577, 2))
    ok('totals split: fittings vs BOQ lines', p.fixed_items_total() == 15000 and p.boq_items_total() == 696 * 120 + 71 * 850 + 45000)
    snap = billing.quotation_snapshot(p)
    s_items = {i['name']: i for r in snap['rooms'] for i in r['items']}
    ok('snapshot: BOQ lines with unit and description; boq total', s_items['False Ceiling']['type'] == 'boq'
       and s_items['False Ceiling']['unit'] == 'sqft' and s_items['Wardrobe']['description'].startswith('Openable')
       and snap['boq_total'] == 696 * 120 + 71 * 850 + 45000)
    secs = layout.boq_rows(snap)
    ok('BOQ rows: sections A, B with numbered lines', [(s_['letter'], s_['name'], len(s_['lines'])) for s_ in secs]
       == [('A', 'Other Service', 4), ('B', 'Master Bedroom', 2)] and [l_['no'] for l_ in secs[0]['lines']] == [1, 2, 3, 4])
    l3d, linfo, lward = secs[0]['lines'][3], secs[0]['lines'][2], secs[1]['lines'][0]
    ok('BOQ rows: lump sum has no rate; info line no amount; measured shows area, rate, size',
       l3d['unit'] == 'LS' and l3d['rate'] is None and l3d['amount'] == 45000 and linfo['amount'] == 0
       and lward['qty'] == 56 and lward['rate'] == LAM and '8 ft' in lward['description'] and 'Openable' in lward['description'])
    inv = billing.invoice_lines(snap)
    ok('invoice lines carry the unit', any(l_['description'] == 'False Ceiling' and l_['unit'] == 'sqft' and l_['qty'] == 696
                                          for l_ in inv))
    prev = billing.restore_preview(p, snap)
    ok('restoring a revision keeps BOQ lines and their totals', round(prev['subtotal'], 2) == round(subtotal, 2)
       and any(i['type'] == 'boq' and i['unit'] == 'sqft' for r in prev['rooms'] for i in r['items']))

# ── Saved BOQ lines ──
with app.app_context():
    saved = {b.name: b for b in BoqItem.query.all()}
    fc_saved = saved.get('False Ceiling')
    ok('BOQ lines are remembered the first time they are used (name, description, unit, rate)',
       set(saved) == {'False Ceiling', 'Electric wiring', 'Other Light and Fitting Charges', '3D Design'}
       and fc_saved.rate == 120 and fc_saved.unit == 'sqft' and fc_saved.description.startswith('Living Room, Kitchen'))
t = c.get('/projects/new').text
ok('new quotation offers the saved lines with their defaults', '"name": "False Ceiling"' in t and '"rate": 120' in t
   and 'modal_boq_default' in t)
ok('"Add from my lines" checklist, lines grouped by the section they were first used in', 'id="boqPickModal"' in t
   and '"category": "Other Service"' in t)


def boq_quote(rate, save_default=False, name='Again'):
    line = {'name': 'False Ceiling', 'type': 'boq', 'quantity': 100, 'unit': 'sqft', 'unit_price': rate,
            'description': 'Hall only'}
    if save_default:
        line['save_default'] = True
    c.post('/projects/new', data={'customer_name': name, 'mobile': '9000000703',
                                  'rooms_data': json.dumps([{'name': 'Hall', 'items': [line]}])})


boq_quote(135)
with app.app_context():
    b = BoqItem.query.filter_by(name='False Ceiling').first()
    ok('a different rate on one quotation leaves the default alone', b.rate == 120 and b.description.startswith('Living Room'))
boq_quote(130, save_default=True)
with app.app_context():
    b = BoqItem.query.filter_by(name='False Ceiling').first()
    ok('"Save as my default" updates the saved line', b.rate == 130 and b.description == 'Hall only')
c.post('/api/draft', json={'customer_name': 'Draft', 'mobile': '9000000704', 'rooms_data': [
    {'name': 'Hall', 'items': [{'name': 'Half typ', 'type': 'boq', 'quantity': 1, 'unit': 'nos', 'unit_price': 10}]}]})
with app.app_context():
    ok('auto-saved drafts don\'t teach half-typed lines', BoqItem.query.filter_by(name='Half typ').first() is None)
r = c.get('/admin/rates').text
ok('Admin → Rates lists the saved BOQ lines', 'id="boq-lines"' in r and 'value="False Ceiling"' in r and 'name="boq_submit"' in r)
with app.app_context():
    ids = {b.name: str(b.id) for b in BoqItem.query.all()}
form = {'boq_submit': '1', 'bq_id': [], 'bq_name': [], 'bq_desc': [], 'bq_unit': [], 'bq_rate': [], 'bq_cat': [], 'bq_delete': [ids['3D Design']]}
for name, desc, unit, rate in (('False Ceiling', 'Gypsum, with cove', 'Sq.ft', '140'), ('Electric wiring', 'Conduit, polycab wire', 'nos', '900'),
                               ('Other Light and Fitting Charges', 'Rate card', 'nos', '0'), ('3D Design', '', 'LS', '45000')):
    form['bq_id'].append(ids[name]); form['bq_name'].append(name); form['bq_desc'].append(desc)
    form['bq_unit'].append(unit); form['bq_rate'].append(rate); form['bq_cat'].append('Services')
for k, v in (('bq_id', ''), ('bq_name', 'Painting'), ('bq_desc', 'Royale, 2 coats'), ('bq_unit', 'sqft'), ('bq_rate', '45'), ('bq_cat', 'Services')):
    form[k].append(v)
r = c.post('/admin/rates', data=form, follow_redirects=True)
with app.app_context():
    saved = {b.name: b for b in BoqItem.query.all()}
    ok('Admin → Rates: edit a default, add a line, remove a line', 'BOQ lines updated' in r.text
       and saved['False Ceiling'].rate == 140 and saved['False Ceiling'].unit == 'sqft'
       and saved['Electric wiring'].rate == 900 and 'Painting' in saved and '3D Design' not in saved)

# ── Rate-only lines (no quantity): a rate card ──
c.post('/projects/new', data={'customer_name': 'Rate card', 'mobile': '9000000705', 'rooms_data': json.dumps([
    {'name': 'Lights & Fittings (rates)', 'description': 'Exact price once the design is final', 'items': [
        {'name': 'COB Light 12 W', 'type': 'boq', 'quantity': 0, 'unit': 'nos', 'unit_price': 420},
        {'name': 'Profile Light 17 mm', 'type': 'boq', 'quantity': 0, 'unit': 'rft', 'unit_price': 550}]},
    {'name': 'Work', 'items': [{'name': 'Fan Fitting', 'type': 'boq', 'quantity': 5, 'unit': 'nos', 'unit_price': 500}]}])})
with app.app_context():
    rp = Project.query.order_by(Project.id.desc()).first()
    rsnap = billing.quotation_snapshot(rp)
    rrows = layout.boq_rows(rsnap)
    cob = rrows[0]['lines'][0]
    ok('rate-only lines: saved with no quantity, shown with their rate, not added to the total',
       rp.grand_total == 2500 and cob['qty'] == 0 and cob['rate'] == 420 and cob['amount'] == 0
       and rrows[0]['description'] == 'Exact price once the design is final')
    ok('rate-only lines aren\'t billed on an invoice', [l_['description'] for l_ in billing.invoice_lines(rsnap)] == ['Fan Fitting'])
rv = c.get(f'/projects/{rp.id}').text
ok('quotation page shows "Rate ₹420 / Nos."', 'Rate &#8377;420 / Nos.' in rv)

# ── Sizes: the quantity worked out from length × width (area units) or length (running units) ──
c.post('/projects/new', data={'customer_name': 'Sizes', 'mobile': '9000000706', 'rooms_data': json.dumps([
    {'name': 'Hall', 'items': [
        {'name': 'False Ceiling', 'type': 'boq', 'quantity': 1, 'unit': 'sqft', 'unit_price': 120, 'length': 14, 'width': 12},
        {'name': 'Ceiling (metric)', 'type': 'boq', 'quantity': 1, 'unit': 'sq m', 'unit_price': 1300, 'length': 14, 'width': 12},
        {'name': 'Profile Light', 'type': 'boq', 'quantity': 1, 'unit': 'rft', 'unit_price': 550, 'length': 12, 'count': 4},
        {'name': 'Panel', 'type': 'boq', 'quantity': 1, 'unit': 'sqft', 'unit_price': 950, 'length': 3, 'width': 2.5, 'count': 2},
        {'name': 'Total typed', 'type': 'boq', 'quantity': 696, 'unit': 'sqft', 'unit_price': 120}]}])})
with app.app_context():
    sp = Project.query.order_by(Project.id.desc()).first()
    si = {i.name: i for i in Item.query.join(Item.room).filter(Room.project_id == sp.id)}
    ok('size → quantity: 14 ft × 12 ft = 168 sqft; 15.61 sq m; 12 ft × 4 = 48 rft; 3 × 2.5 × 2 = 15 sqft (the server works it out)',
       si['False Ceiling'].quantity == 168 and si['Ceiling (metric)'].quantity == 15.61 and si['Profile Light'].quantity == 48
       and si['Panel'].quantity == 15 and si['Panel'].boq_count == 2 and si['Profile Light'].boq_count == 4)
    ok('…or the quantity typed with no size', si['Total typed'].quantity == 696 and si['Total typed'].length == 0)
    ssnap = billing.quotation_snapshot(sp)
    lines = {l_['title']: l_ for sec in layout.boq_rows(ssnap) for l_ in sec['lines']}
    ok('BOQ rows print the size: "Size: 14 ft × 12 ft", "12 ft × 4 No\'s"', 'Size: 14 ft × 12 ft' in lines['False Ceiling']['description']
       and "Size: 12 ft × 4 No's" in lines['Profile Light']['description'] and 'Size' not in lines['Total typed']['description'])
    ok('total from the sizes', round(sp.grand_total, 2) == round(168 * 120 + 15.61 * 1300 + 48 * 550 + 15 * 950 + 696 * 120, 2))
es = c.get(f'/projects/{sp.id}/edit').text
ok('edit form gets the size and No\'s back', '"length": 12.0' in es and '"count": 4' in es)

e = c.get(f'/projects/{pid}/edit').text
m = re.search(r'id="existing-rooms-data"[^>]*>(.*?)</script>', e, re.S)
data = json.loads(m.group(1)) if m else []
ok('edit form gets each line\'s type, unit and description back', any(i.get('type') == 'boq' and i.get('unit') == 'sqft'
   and i.get('description', '').startswith('Living') for r in data for i in r['items']))
v = c.get(f'/projects/{pid}').text
ok('quotation page: BOQ badge, unit, description, Other work total', 'ki-badge-boq' in v and '696 Sq.ft' in v
   and 'Conduit, polycab wire considered' in v and 'Other work (BOQ lines)' in v)

full = pdftext(f'/projects/{pid}/pdf')
ok('Full Quotation: BOQ lines with unit × rate and descriptions; Other work in the summary',
   '696 Sq.ft × Rs. 120' in full and 'Conduit, polycab wire considered' in full and 'Other work (BOQ lines)' in full
   and 'Openable, laminate finish' in full)

# ── BOQ layout ──
s = c.get('/admin/settings?tab=documents').text
ok('on: BOQ layout offered in Settings → Quotation PDFs', 'id="il_boq"' in s)
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'boq'})
with app.app_context():
    ok('BOQ layout chosen', layout.initial_layout() == layout.LAYOUT_BOQ)
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('customer PDF in BOQ layout: Sr. No., Qty, Unit, Rate, sections, descriptions',
   'Bill of Quantities' in cust and 'Sr. No.' in cust and 'Other Service' in cust and 'Living Room: 192+104=296' in cust
   and 'Sq.ft' in cust and '83,520.00' in cust and '60,350.00' in cust and '45,000.00' in cust and 'LS' in cust)
ok('…with Basic Total, discount and Total', 'Basic Total' in cust and '10,577.00' in cust and f'{subtotal - 10577:,.2f}' in cust)
r = c.post(f'/projects/{pid}/share', data={'detail': 'summary'}, follow_redirects=True)
with app.app_context():
    from app.models import QuoteShare
    sh = QuoteShare.query.filter_by(project_id=pid).order_by(QuoteShare.id.desc()).first()
pub = app.test_client().get(f'/q/{sh.token}').text if sh else ''
ok('customer link in BOQ layout: sections, lines, units, Basic Total', 'Bill of quantities' in pub and 'A. Other Service' in pub
   and '696 Sq.ft' in pub and 'Conduit, polycab wire considered' in pub and 'Basic Total' in pub)

# ── Off again ──
setting(boq.KEY, '')
ok('off: no BOQ lines list in Admin → Rates', 'id="boq-lines"' not in c.get('/admin/rates').text)
with app.app_context():
    ok('off again: the BOQ layout falls back to room by room', layout.initial_layout() == layout.LAYOUT_ROOMS)
e = c.get(f'/projects/{pid}/edit').text
ok('off again: a quotation that has BOQ lines can still edit them', 'modal_type_boq' in e)
ok('off again: new quotations don\'t offer them', 'modal_type_boq' not in c.get('/projects/new').text)
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('off again: room-by-room PDF lists BOQ lines with quantity and unit', 'False Ceiling' in cust and '696 Sq.ft' in cust)
