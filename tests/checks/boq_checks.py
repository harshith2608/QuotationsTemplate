"""BOQ lines (turnkey): off by default; on per business; description, quantity, unit and rate per line; the BOQ
layout of the Initial Quotation; Full Quotation, customer link, WhatsApp text, invoice lines, revisions."""
import io, json, re
from pypdf import PdfReader
from app import create_app, db, billing, boq, layout
from app.models import AppSetting, Item, ItemRate, Project, Room

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
setting(boq.KEY, '1')
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
with app.app_context():
    ok('off again: the BOQ layout falls back to room by room', layout.initial_layout() == layout.LAYOUT_ROOMS)
e = c.get(f'/projects/{pid}/edit').text
ok('off again: a quotation that has BOQ lines can still edit them', 'modal_type_boq' in e)
ok('off again: new quotations don\'t offer them', 'modal_type_boq' not in c.get('/projects/new').text)
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('off again: room-by-room PDF lists BOQ lines with quantity and unit', 'False Ceiling' in cust and '696 Sq.ft' in cust)
