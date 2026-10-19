"""Room-by-room Initial Quotation: No's per item, room descriptions, Hardware row per room, sections, layout setting."""
import io, json, re
from pypdf import PdfReader
from sqlalchemy import text
from app import create_app, db, billing, layout
from app.models import Item, ItemRate, Project, QuoteRevision, Room
from sqlalchemy.orm import undefer

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pdftext = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))
money = lambda v: f'{v:,.2f}'


def rate(wood, work):
    with app.app_context():
        return ItemRate.query.filter_by(wood_type=wood, work_type=work).first().rate_per_sqft


LAM, ACR = rate('Laminates', 'Box Work'), rate('Acrylic', 'Box Work')
rooms = [
    {'name': 'Kitchen', 'description': 'Carcass: BWP 710 ply · Shutters: 1.5mm Acrylic', 'items': [
        {'name': 'Base Cabinet', 'length': 8, 'width': 2.5, 'wood_type': 'Laminates', 'work_type': 'Box Work'},        # 20 sqft
        {'name': 'Glass Shutters', 'length': 6, 'width': 1.5, 'count': 2, 'wood_type': 'Acrylic', 'work_type': 'Box Work'},  # 9 × 2 = 18
        {'name': 'Tandem Drawer', 'type': 'fixed', 'quantity': 3, 'unit_price': 4500}]},
    {'name': 'Master Bedroom', 'items': [
        {'name': 'Wardrobe', 'length': 8, 'width': 7, 'wood_type': 'Laminates', 'work_type': 'Box Work'},             # 56 sqft
        {'name': 'Soft-close Hinge', 'type': 'fixed', 'quantity': 8, 'unit_price': 350}]}]
c.post('/projects/new', data={'customer_name': 'Layout Test', 'mobile': '9000000888', 'rooms_data': json.dumps(rooms),
                              'discount_type': 'fixed', 'discount_value': '1000'})
kitchen_measured = 20 * LAM + 18 * ACR
bedroom_measured = 56 * LAM
subtotal = kitchen_measured + 3 * 4500 + bedroom_measured + 8 * 350
with app.app_context():
    p = Project.query.order_by(Project.id.desc()).first(); pid = p.id
    items = {i.name: i for i in Item.query.join(Item.room).filter(Room.project_id == pid)}
    kroom = Room.query.options(undefer(Room.description)).filter_by(project_id=pid, name='Kitchen').first()
    ok("No's: 2 pieces of 6 ft × 1 ft 6 in = 18 sqft, priced as 18", items['Glass Shutters'].count == 2
       and items['Glass Shutters'].area == 18 and items['Wardrobe'].count == 1)
    ok('total includes the count; room description saved', round(p.grand_total, 2) == round(subtotal, 2)
       and kroom.description == 'Carcass: BWP 710 ply · Shutters: 1.5mm Acrylic')
    snap = billing.quotation_snapshot(p)
    rows = layout.room_rows(snap)
ok('room rows: room, its Hardware row, next room, its Hardware row', [r['title'] for r in rows] ==
   ['Kitchen', 'Kitchen – Hardware', 'Master Bedroom', 'Master Bedroom – Hardware'] and [r['no'] for r in rows] == [1, 2, 3, 4])
ok('room rows: one amount each, adding up to the subtotal exactly',
   [round(r['amount'], 2) for r in rows] == [round(kitchen_measured, 2), 13500, round(bedroom_measured, 2), 2800]
   and round(sum(r['amount'] for r in rows), 2) == round(snap['subtotal'], 2) == round(subtotal, 2))
ok('descriptions: the room\'s own, else its materials', rows[0]['description'] == 'Carcass: BWP 710 ply · Shutters: 1.5mm Acrylic'
   and 'Laminates – Box Work' in rows[2]['description'] and rows[1]['description'] == '')
ok("hardware rows list each fitting with its count", [(i['name'], i['count']) for i in rows[1]['items']] == [('Tandem Drawer', 3)])

cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('Initial Quotation PDF is room by room by default', 'Kitchen – Hardware' in cust and "No's" in cust
   and 'Material Description' in cust and 'Carcass: BWP 710 ply' in cust and 'Basic Total' in cust)
ok('…with sizes, one amount per room, discount and total; no rates or areas', '8 ft' in cust and money(kitchen_measured) in cust
   and money(subtotal) in cust and money(subtotal - 1000) in cust and f'{LAM:,.0f}' not in cust.replace(money(subtotal), '')
   and 'sqft' not in cust)
full = pdftext(f'/projects/{pid}/pdf')
ok('Full Quotation keeps every rate and shows the count', 'Glass Shutters × 2' in full and money(subtotal - 1000) in full)
ok('Full Quotation: each item\'s material as a finish (Laminates Finish), work types only in the Cost Summary',
   'Laminates Finish' in full and 'Acrylic Finish' in full and 'Laminates – Box Work' in full.split('Cost Summary')[1]
   and 'Laminates – Box Work' not in full.split('Cost Summary')[0])
ok('Full Quotation Cost Summary: area and amount per material, no rate per area', 'Total Area' in full
   and 'Rate (Rs.' not in full and f'{LAM:,.0f}' not in full.split('Cost Summary')[1].split('Subtotal')[0].replace(money(LAM * 20), ''))

# Sections
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms', 'material_specs': 'BWP 710 ply for carcass',
                                'payment_terms': '1. 10% advance with order\n2) 50% after design finalisation\n40% on delivery',
                                'delivery_terms': '45 to 60 working days', 'important_notes': '', 'terms_conditions': 'GST extra as applicable'})
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('sections: numbered, own numbering removed, empty ones left out', 'Payment Terms' in cust and '1. 10% advance with order' in cust
   and '2. 50% after design finalisation' in cust and '3. 40% on delivery' in cust and 'Delivery Terms' in cust
   and 'Important Notes' not in cust and 'Material Specifications' in cust and 'Terms & Conditions' in cust)
ok('the Full Quotation has the sections too', 'Payment Terms' in pdftext(f'/projects/{pid}/pdf'))
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms',
                                'room_descriptions': 'Carcass: BWP 710 ply · Shutters: 1mm laminate\n\n  Carcass: BWP 710 ply · Shutters: 1.5mm Acrylic \nCarcass: BWP 710 ply · Shutters: 1mm laminate'})
with app.app_context():
    opts = layout.description_options()
ok('room descriptions: the admin\'s list, one per line, tidied, no duplicates',
   opts == ['Carcass: BWP 710 ply · Shutters: 1mm laminate', 'Carcass: BWP 710 ply · Shutters: 1.5mm Acrylic'])
f = c.get('/projects/new').text
ok('quotation form offers them as a dropdown per room, with an Edit list link for admins',
   json.loads(re.search(r'roomDescriptions: (\[.*?\]),', f).group(1)) == opts and 'room-descriptions' in f)
s_ = c.get(f'/projects/{pid}/edit').text
ok('a room keeps a description that isn\'t on the list (kept selectable)', '1.5mm Acrylic' in s_)
t = c.get('/admin/settings?tab=documents').text
ok('Settings → Quotation PDFs: layout choice and the new sections', 'name="initial_layout"' in t and 'name="payment_terms"' in t
   and 'name="room_descriptions"' in t
   and 'name="delivery_terms"' in t and 'name="important_notes"' in t)

# Placeholders in the sections: filled in from each quotation (plywood details from Admin → Rates)
from app.models import PlywoodOption
with app.app_context():
    d = PlywoodOption.query.filter_by(is_default=True).first(); d_id, d_name = d.id, d.name
t = c.get('/admin/rates').text
ok('Rates → Plywood has a Details box per plywood', f'name="ply_details_{d_id}"' in t)
form = {'plywood_submit': '1', 'ply_default': str(d_id)}
with app.app_context():
    for o in PlywoodOption.query.all():
        form[f'ply_name_{o.id}'] = o.name; form[f'ply_adj_{o.id}'] = '0'; form[f'ply_active_{o.id}'] = '1'
form[f'ply_details_{d_id}'] = '12 Years Brand warranty Century Sainik 710 grade BWP ply of 16mm thickness'
c.post('/admin/rates', data=form)
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms',
       'material_specs': '{plywood_details} for all the carcass and shutters\nMaterials: {materials}\nPrepared for {customer} by {company}, quotation #{quotation_no}\nKeep {this} as typed',
       'terms_conditions': 'GST extra as applicable'})
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('placeholders filled: plywood details, materials, customer, company, quotation no.',
   '12 Years Brand warranty Century Sainik 710 grade BWP ply of 16mm thickness for all the carcass and shutters' in cust
   and 'Laminates – Box Work' in cust and f'Prepared for Layout Test by Demo Interiors, quotation #{pid}' in cust)
ok('unknown {words} are left as typed', 'Keep {this} as typed' in cust)
ok('the Full Quotation fills them too', '16mm thickness for all the carcass' in pdftext(f'/projects/{pid}/pdf'))
t = c.get('/admin/settings?tab=documents').text
ok('Settings offers the placeholders as Insert buttons', '"plywood_details"' in t and 'ki-var-bar' in t)

# Several descriptions on one room (multi-select): kept one per line, duplicates dropped, each printed
multi = [{'name': 'Study', 'description': 'Carcass: BWP 710 ply\nShutters:   1mm laminate\nCarcass: BWP 710 ply', 'items': [
    {'name': 'Study Table', 'length': 4, 'width': 2, 'wood_type': 'Laminates', 'work_type': 'Box Work'}]}]
c.post('/projects/new', data={'customer_name': 'Multi Desc', 'mobile': '9000000890', 'rooms_data': json.dumps(multi),
                              'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    mp = Project.query.order_by(Project.id.desc()).first()
    mroom = Room.query.options(undefer(Room.description)).filter_by(project_id=mp.id).first()
    ok('multi-select descriptions saved one per line, tidied, no duplicates',
       mroom.description == 'Carcass: BWP 710 ply\nShutters: 1mm laminate')
mc = pdftext(f'/projects/{mp.id}/pdf/customer')
ok('…and both printed for the room', 'Carcass: BWP 710 ply' in mc and 'Shutters: 1mm laminate' in mc)
ok('…and both kept on the edit form', json.loads(c.get(f'/projects/{mp.id}/edit').text.split('id="existing-rooms-data"', 1)[1]
   .split('>', 1)[1].split('</script>', 1)[0])[0]['description'] == 'Carcass: BWP 710 ply\nShutters: 1mm laminate')

# Terms & Conditions: defaults until first saved; an emptied box stays empty (and the section is left out)
from app.models import AppSetting
with app.app_context():
    row = db.session.get(AppSetting, 'terms_conditions'); saved_terms = row.value if row else None
    if row: db.session.delete(row); db.session.commit()
t = c.get('/admin/settings?tab=documents').text
ok('never saved: the default terms are offered', 'This quotation is valid for 30 days' in t)
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms', 'terms_conditions': '   ',
                                'material_specs': 'BWP 710 ply for carcass'})
t = c.get('/admin/settings?tab=documents').text
ok('emptied and saved: stays empty (no defaults put back)', 'This quotation is valid for 30 days' not in t)
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('…and the PDFs leave Terms & Conditions out', 'Terms & Conditions' not in cust and 'valid for 30 days' not in cust
   and 'Material Specifications' in cust and 'Terms & Conditions' not in pdftext(f'/projects/{pid}/pdf'))

# Customer's link follows the same layout
r = c.post(f'/projects/{pid}/share', data={'detail': 'summary'}, follow_redirects=True)
with app.app_context():
    from app.models import QuoteShare
    token = QuoteShare.query.filter_by(project_id=pid).first().token
t = app.test_client().get(f'/q/{token}').text
ok("customer's link: room by room with Hardware rows, Basic Total and Total", 'Room by room' in t and 'Kitchen – Hardware' in t
   and "2 No's" in t and "Tandem Drawer · 3 No's" in t and 'Basic Total' in t and money(subtotal - 1000) in t and '/sqft' not in t)

# By material: as before
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'materials'})
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('layout "By material": the old amount-per-material table', 'Material & Work Type' in cust and 'Hardware' not in cust
   and money(subtotal - 1000) in cust)
t = app.test_client().get(f'/q/{token}').text
ok("…and the customer's link too", 'Room by room' not in t and "What's included" in t)
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms'})

# Edit keeps No's and descriptions; changing a count is a revision with what changed
s = c.get(f'/projects/{pid}/edit').text
data = json.loads(s.split('id="existing-rooms-data"', 1)[1].split('>', 1)[1].split('</script>', 1)[0])
ok('edit form gets the count and the room description', data[0]['description'].startswith('Carcass')
   and [i.get('count') for i in data[0]['items']][:2] == [1, 2] and 'id="modal_item_count"' in s)
data[0]['items'][1]['count'] = 3
c.post(f'/projects/{pid}/edit', data={'customer_name': 'Layout Test', 'mobile': '9000000888', 'rooms_data': json.dumps(data),
                                      'discount_type': 'fixed', 'discount_value': '1000'})
with app.app_context():
    p = db.session.get(Project, pid)
    ok('count 2 → 3 adds 9 sqft of Acrylic', round(p.grand_total, 2) == round(subtotal + 9 * ACR, 2))
ok('the revision says what changed', '1 ft 6 in × 2' in c.get(f'/projects/{pid}').text and '× 3' in c.get(f'/projects/{pid}').text)
c.post(f'/projects/{pid}/revisions/1/restore')
with app.app_context():
    p = db.session.get(Project, pid)
    i = next(i for i in Item.query.join(Item.room).filter(Room.project_id == pid) if i.name == 'Glass Shutters')
    kroom = Room.query.options(undefer(Room.description)).filter_by(project_id=pid, name='Kitchen').first()
    ok('restore brings back the count and the description', i.count == 2 and round(p.grand_total, 2) == round(subtotal, 2)
       and kroom.description.startswith('Carcass'))

c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms',
                                'material_specs': '{plywood_details} for all the carcass and shutters'})
# Before the database update: rooms save and quotations print without descriptions
with app.app_context():
    db.session.execute(text('ALTER TABLE rooms DROP COLUMN description'))
    db.session.execute(text('ALTER TABLE plywood_options DROP COLUMN details')); db.session.commit()
layout._ready_forever.clear()
from app import plywood as _ply
_ply._details_ready.clear()
c2 = app.test_client(); c2.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
c2.post('/projects/new', data={'customer_name': 'Pre Desc', 'mobile': '9000000889', 'rooms_data': json.dumps(rooms),
                               'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    pre = db.session.execute(text('select id from projects order by id desc limit 1')).scalar()
    pre_p = db.session.get(Project, pre)
    ok('before the update: saving works (count kept, no description)', pre_p.customer_name == 'Pre Desc'
       and round(pre_p.grand_total, 2) == round(subtotal, 2))
cust = re.sub(r'\s+', ' ', ' '.join(pg.extract_text() for pg in PdfReader(io.BytesIO(c2.get(f'/projects/{pre}/pdf/customer').data)).pages))
ok('before the update: Initial Quotation prints, rooms described from materials', 'Kitchen – Hardware' in cust
   and 'Laminates – Box Work' in cust and c2.get(f'/projects/{pre}').status_code == 200 and c2.get(f'/projects/{pre}/edit').status_code == 200)
ok('before the update: {plywood_details} prints the plywood name', f'{d_name} for all the carcass and shutters' in cust)
