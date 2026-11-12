"""Pricing by material with the BOQ table (every item on its own line): one amount per room, no plywood on each line,
the material before the business's own description."""
import io, json, re
from urllib.parse import unquote
from pypdf import PdfReader
from app import create_app, db, billing, layout
from app.models import AppSetting, ItemRate, Material, Project, QuoteShare
from app.numbers import inr

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pdftext = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))

rooms = [{'name': 'Living Room', 'description': 'Carcass: BWP 710 ply', 'items': [
    {'name': 'TV Unit', 'length': 8, 'width': 1, 'wood_type': 'Laminates', 'work_type': 'Box Work',
     'description': 'Glass door in the side', 'plywood': '12mm 8*4'},
    {'name': 'Tandem Drawer', 'type': 'fixed', 'quantity': 2, 'unit_price': 4500}]}]
c.post('/projects/new', data={'customer_name': 'Item List', 'mobile': '9000000777', 'plywood': '12mm 8*4', 'rooms_data': json.dumps(rooms),
                              'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    p = Project.query.order_by(Project.id.desc()).first(); pid = p.id
    snap = billing.quotation_snapshot(p)
    tv = snap['rooms'][0]['items'][0]
    material = tv['material']
    tv_amount, room_total = tv['amount'], snap['subtotal']
    board = material.partition(' · ')[2]

s = c.get('/admin/settings?tab=documents').text
ok('pricing by material: the BOQ table can be chosen', 'il_boq' in s and 'boq_room_totals' in s)
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'boq', 'boq_rate_shown': '1',
                                'boq_room_totals': '0', 'boq_board_shown': '1'})
with app.app_context():
    ok('…and is used', layout.initial_layout() == layout.LAYOUT_BOQ)
    sec = layout.boq_rows(billing.quotation_snapshot(db.session.get(Project, pid)))[0]
ok('a line says its material and size first, then the description',
   sec['lines'][0]['description'].split('\n')[1] == 'Glass door in the side'
   and sec['lines'][0]['description'].split('\n')[0].startswith('Laminate Finish'))
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('PDF: per-line amounts and rates by default', inr(tv_amount) in cust and 'Rate' in cust)
ok('PDF: the board is on the line by default' + (f' ({board})' if board else ' (no board in this seed)'),
   not board or board in cust)

c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'boq', 'boq_rate_shown': '1',
                                'boq_room_totals': '1', 'boq_board_shown': '0',
                                'terms_conditions': 'Board: {plywood}'})
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('room totals: the room amount, no line amount, no Rate column', inr(room_total) in cust and inr(tv_amount) not in cust
   and inr(9000) not in cust and ' Rate ' not in cust and 'Glass door in the side' in cust)
ok('no board on the line' + (', but in the Terms' if board else ''),
   not board or (cust.count(board) >= 1 and f'Laminate Finish · {board}' not in cust))
with app.app_context():
    sh = QuoteShare.query.filter_by(project_id=pid, active=True).first()
if not sh:
    c.post(f'/projects/{pid}/share')
    with app.app_context():
        sh = QuoteShare.query.filter_by(project_id=pid, active=True).first()
if sh:
    pub = app.test_client().get(f'/q/{sh.token}').text
    ok('customer link: room total, no line amounts', inr(room_total) in pub and inr(tv_amount) not in pub)
wa = c.get(f'/projects/{pid}/whatsapp')
msg = unquote(wa.headers.get('Location', ''))
ok('WhatsApp: room amount, no per-line or per-material prices', inr(room_total, 0) in msg and inr(tv_amount, 0) not in msg
   and 'Material Summary' not in msg and 'TV Unit' in msg)

with app.app_context():
    from app import boq
    AppSetting.set(boq.KEY, '1'); db.session.commit()
    boq.set_enabled(False); db.session.commit()
    ok('leaving pricing by item goes back to room by room', layout.initial_layout() == layout.LAYOUT_ROOMS)

# Price list file: boards, materials on plywood or hidden, the BOQ-table options
from app import price_list
from app.models import Material, PlywoodOption
from sqlalchemy.orm import undefer
f = {'pricing': 'material', 'materials': [{'name': 'TV Unit (Laminate)', 'rate': 2400, 'on_plywood': True},
                                          {'name': 'Putty', 'rate': 20, 'on_plywood': False},
                                          {'name': 'Veneer Panel', 'rate': 4000, 'shown': False}],
     'boards': [{'name': '16mm Sainik', 'default': True, 'details': 'Century Sainik 710'},
                {'name': '16mm Bond', 'difference': 100}],
     'lines': [{'name': '3D Design', 'unit': 'lump sum', 'rate': 45000}],
     'options': {'layout': 'boq', 'room_totals': False, 'show_board': True}}
with app.app_context():
    r = price_list.apply(price_list.parse(json.dumps(f).encode()), remove_starter=True)
    mats = {m.name: m for m in Material.query.options(undefer(Material.uses_plywood)).all()}
    boards = {b.name: b for b in PlywoodOption.query.all()}
    ok('price list: materials on plywood / not / hidden', mats['TV Unit (Laminate)'].uses_plywood
       and not mats['Putty'].uses_plywood and not mats['Veneer Panel'].active and mats['Putty'].active)
    ok('price list: boards (default at 0, the other its difference; others hidden)',
       boards['16mm Sainik'].is_default and boards['16mm Bond'].adjustment == 100 and boards['16mm Bond'].active
       and sum(b.is_default for b in boards.values()) == 1
       and all(not b.active for n, b in boards.items() if n not in ('16mm Sainik', '16mm Bond')))
    ok('price list: options set the layout and the BOQ table settings', layout.initial_layout() == layout.LAYOUT_BOQ
       and not layout.room_totals_only() and layout.show_board() and r['boards'] == 2)
    ok('price list: a lump sum with pricing by material', r['added'] >= 1)
for bad in ({'boards': [{'name': 'A1', 'difference': 50, 'default': True}]},
            {'boards': [{'name': 'A1', 'default': True}, {'name': 'B1', 'default': True}]},
            {'options': {'room_totals': 'yes'}}):
    try:
        price_list.parse(json.dumps(bad).encode()); ok(f'price list refuses {bad}', False)
    except price_list.PriceListError:
        ok(f'price list refuses {list(bad)[0]} mistakes', True)

# Materials that are items: no "Finish" added, and an item named after its material doesn't repeat it
from app.materials import finish_name
ok('finish names: Laminates → Laminate Finish, Acrylic → Acrylic Finish, Glass → Glass Finish',
   finish_name('Laminates') == 'Laminate Finish' and finish_name('Acrylic') == 'Acrylic Finish' and finish_name('Glass') == 'Glass Finish')
ok('…an item-like material stays as it is', finish_name('Sliding Wardrobe (Laminate Finish)') == 'Sliding Wardrobe (Laminate Finish)'
   and finish_name('Kitchen Acrylic Finish - Base Unit') == 'Kitchen Acrylic Finish - Base Unit'
   and finish_name('Dressing Storage Unit') == 'Dressing Storage Unit')
with app.app_context():
    snap = {'rooms': [{'name': 'Hall', 'items': [
        {'name': 'TV Unit (Laminate)', 'type': 'measured', 'length': 1, 'width': 8, 'area': 8, 'rate': 2400, 'amount': 19200,
         'material': 'TV Unit (Laminate) · 16mm Bond'},
        {'name': 'TV Unit', 'type': 'measured', 'length': 1, 'width': 8, 'area': 8, 'rate': 2400, 'amount': 19200,
         'material': 'TV Unit (Laminate) · 16mm Bond'}]}]}
    l1, l2 = layout.boq_rows(snap)[0]['lines']
ok('an item named after its material: size (and board) only, not the name twice',
   'TV Unit (Laminate)' not in l1['description'] and '16mm Bond' in l1['description'])
ok('…another name still says its material', l2['description'].startswith('TV Unit (Laminate) · 16mm Bond'))

# A description per material (Admin → Rates): saved, follows a rename, offered to the form; loaded from a price list
from app import materials as MM
with app.app_context():
    m = Material.query.filter_by(name='Putty').first(); mid = m.id
    price_list.apply(price_list.parse(json.dumps({'pricing': 'material', 'materials': [
        {'name': 'TV Unit (Laminate)', 'rate': 2400, 'description': 'Ledge box with glass door'}]}).encode()), remove_starter=False)
    ok('price list: a material description', MM.descriptions().get('TV Unit (Laminate)') == 'Ledge box with glass door')
r = c.post('/admin/rates', data={'item_rates_submit': 'save', f'name_{mid}': 'Wall Putty', f'desc_{mid}': 'Two coats\nSanded'},
           follow_redirects=True)
with app.app_context():
    d = MM.descriptions()
    ok('Rates: a description saved with the material', d.get('Wall Putty') == 'Two coats\nSanded' and 'Putty' not in d)
    ok('…kept across a rename, and the others stay', d.get('TV Unit (Laminate)') == 'Ledge box with glass door')
form = c.get('/projects/new').text
ok('the quotation form gets the descriptions', 'materialDescs' in form and 'Ledge box with glass door' in form)
rates_page = c.get('/admin/rates').text
ok('the Rates page shows the description box', f'name="desc_{mid}"' in rates_page and 'Two coats' in rates_page)

# Measured items' descriptions print on the room-by-room layout too
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms'})
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('room by room: the item description prints under it', 'Glass door in the side' in cust)

# AI drafts: a business whose materials are its items (SP): the material is matched even when written a bit
# differently; one that isn't clear is listed to choose, not silently priced as the first material
from app import ai_tools
from app.ai_tools import Draft, DraftRoom, DraftItem
with app.app_context():
    price_list.apply(price_list.parse(json.dumps({'pricing': 'material', 'materials': [
        {'name': 'TV Unit Ledge box (Acrylic Finish)', 'rate': 2800, 'description': 'Acrylic ledge box'},
        {'name': 'TV Unit Ledge box (Laminate Finish)', 'rate': 2400},
        {'name': 'Sliding Wardrobe (Laminate Finish)', 'rates': {'Box Work': 2300, 'Frame Work': 1400}}]}).encode()),
        remove_starter=False)
    cat = ai_tools._catalog()
    d = Draft(job_title='2 BHK', questions=[], rooms=[DraftRoom(name='Living', items=[
        DraftItem(kind='measured', name='TV Unit', length_ft=8, width_ft=1, material='TV unit ledge box - acrylic finish'),
        DraftItem(kind='measured', name='TV Unit 2', length_ft=8, width_ft=1, material='laminate ledge box'),
        DraftItem(kind='measured', name='Wardrobe', length_ft=7, width_ft=8, material='Sliding Wardrobe (Laminate Finish)',
                  work_type='frame work'),
        DraftItem(kind='measured', name='Mystery', length_ft=2, width_ft=2, material='marble cladding')])])
    rooms, no_rate, unclear = ai_tools.to_form(d, cat)
    its = {i['name']: i for i in rooms[0]['items']}
ok('AI draft: material matched ignoring capitals and punctuation, with its description',
   its['TV Unit']['wood_type'] == 'TV Unit Ledge box (Acrylic Finish)' and its['TV Unit']['description'] == 'Acrylic ledge box')
ok('…matched by its words ("laminate ledge box")', its['TV Unit 2']['wood_type'] == 'TV Unit Ledge box (Laminate Finish)')
ok('…with the work type asked for', (its['Wardrobe']['wood_type'], its['Wardrobe']['work_type'])
   == ('Sliding Wardrobe (Laminate Finish)', 'Frame Work'))
ok('…a material that isn\'t clear is listed to choose', unclear == ['Mystery'])
with app.app_context():
    d2 = Draft(job_title='x', questions=[], rooms=[DraftRoom(name='Hall', items=[
        DraftItem(kind='measured', name='TV', length_ft=8, width_ft=1, material='laminate tv unit')])])
    _, _, unclear2 = ai_tools.to_form(d2, cat)
ok('…and one that fits two materials too ("laminate tv unit": two laminate TV units)', unclear2 == ['TV'])
ok('AI draft: the unclear line is flagged for the checklist, the matched ones aren\'t',
   its['Mystery'].get('check') == 'material' and 'check' not in its['TV Unit'])
with app.app_context():
    d3 = Draft(job_title='x', questions=['Which finish?'], rooms=[DraftRoom(name='Kitchen', items=[
        DraftItem(kind='fitting', name='Granite Sink'), DraftItem(kind='measured', name='Base', material='TV Unit Ledge box (Acrylic Finish)')])])
    r3, nr3, _ = ai_tools.to_form(d3, cat)
ok('…a fitting not in the rates is flagged "price"; a line with no size is pending',
   r3[0]['items'][0].get('check') == 'price' and r3[0]['items'][1].get('pending'))

# The sections (Material Specifications, Terms…) start on a new page when less than half a page is left
from reportlab.platypus import CondPageBreak
from app import pdf_utils
with app.test_request_context():
    AppSetting.set('payment_terms', '50% advance'); db.session.commit()
    els = pdf_utils._section_elements(pdf_utils._styles(), pdf_utils.colors.black, db.session.get(Project, pid))
ok('sections begin with a half-page conditional page break', isinstance(els[0], CondPageBreak)
   and abs(els[0].height - pdf_utils.SECTIONS_ROOM) < 1 and pdf_utils.SECTIONS_ROOM > 300)

# Templates can be edited (rooms, lines, descriptions, rates), keeping lines that have no size yet
from app import quote_templates as QT
with app.app_context():
    tid = QT.put('Base 2 BHK', [{'name': 'Kitchen', 'items': [
        {'name': 'Base Unit', 'wood_type': 'TV Unit Ledge box (Acrylic Finish)', 'work_type': '', 'pending': True}]}])
    db.session.commit()
page = c.get(f'/templates/{tid}/edit').text
ok('a template opens for editing: its lines, no customer box, "Save template"', 'Edit template: Base 2 BHK' in page
   and 'Base Unit' in page and 'id="customer_name"' not in page and 'Save template' in page
   and f'/templates/{tid}/save' in page)
manage = c.get('/templates').text
ok('the templates page has "Edit lines"', f'/templates/{tid}/edit' in manage)
new_rooms = [{'name': 'Kitchen', 'description': 'Carcass: BWP', 'items': [
    {'name': 'Base Unit', 'wood_type': 'TV Unit Ledge box (Acrylic Finish)', 'work_type': '', 'count': 1, 'pending': True,
     'description': 'Below the counter'},
    {'type': 'fixed', 'name': 'Magic Corner', 'quantity': 1, 'unit_price': 50000, 'cost': 30000}]},
    {'name': 'Bedroom', 'items': [{'name': 'Wardrobe', 'length': 8, 'width': 7, 'wood_type': 'TV Unit Ledge box (Acrylic Finish)',
                                    'work_type': '', 'count': 1, 'area': 56}]}]
r = c.post(f'/templates/{tid}/save', data={'rooms_data': json.dumps(new_rooms), 'discount_type': 'percentage',
                                           'discount_value': '5'})
with app.app_context():
    t = QT.get(tid)
ok('saving updates the template: rooms, the line still waiting for its size, a new line, the discount',
   r.status_code == 302 and [rm['name'] for rm in t['rooms']] == ['Kitchen', 'Bedroom']
   and t['rooms'][0]['items'][0].get('pending') and t['rooms'][0]['items'][0]['description'] == 'Below the counter'
   and t['rooms'][0]['items'][1]['name'] == 'Magic Corner' and 'cost' not in t['rooms'][0]['items'][1]
   and t['discount_type'] == 'percentage' and t['discount_value'] == 5)
r = c.post(f'/templates/{tid}/save', data={'rooms_data': '[]'})
with app.app_context():
    ok('an empty template is refused (it keeps its lines)', len(QT.get(tid)['rooms']) == 2)

# The console reads the prices saved in console → Pricing (it makes the website's payment links): not the defaults
import os
from app import platform_switch, pricing
saved = json.dumps({'plans': {'1m': {'price': 499, 'on': True}, '1y': {'price': 4699, 'on': True}}})
real = platform_switch.value
platform_switch.value = lambda key: saved if key == pricing.KEY else None
os.environ['CONSOLE_MODE'] = '1'
try:
    with app.app_context():
        p = pricing.prices()
finally:
    os.environ.pop('CONSOLE_MODE', None)
    platform_switch.value = real
ok('console: the saved prices (₹499 a month, ₹4,699 a year), not the defaults', p['1m'] == 499 and p['1y'] == 4699)

# A measured line by its area alone (no size): saved, priced, printed with its area
with app.app_context():
    m0 = Material.query.filter_by(active=True).first()
    wood = m0.name
    work = '' if not m0.uses_work_types else 'Box Work'
    rate0 = ItemRate.query.filter_by(wood_type=wood, work_type=work).first().rate_per_sqft
r = c.post('/projects/new', data={'customer_name': 'Area Only', 'mobile': '9000000444', 'discount_type': 'none',
                                  'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Hall', 'items': [
    {'name': 'Panelling', 'length': 0, 'width': 0, 'area': 42.5, 'size_mode': 'area', 'count': 3,
     'wood_type': wood, 'work_type': work},
    {'name': 'Bogus', 'length': 0, 'width': 0, 'area': 10, 'wood_type': wood, 'work_type': work}]}])})
with app.app_context():
    pa = Project.query.order_by(Project.id.desc()).first()
    its = {i.name: i for i in pa.rooms_with_items()[0].item_list}
ok('area typed directly: saved with no size, No\'s 1, priced on that area; without size_mode it\'s ignored',
   'Panelling' in its and its['Panelling'].length == 0 and its['Panelling'].area == 42.5 and its['Panelling'].count == 1
   and 'Bogus' not in its and round(pa.grand_total, 2) == round(42.5 * rate0, 2))
cust = pdftext(f'/projects/{pa.id}/pdf/customer')
ok('…its PDF shows the area, no "0 ft" size', '42.5' in cust and '0 ft ×' not in cust and '0 mm ×' not in cust)
full = pdftext(f'/projects/{pa.id}/pdf')
ok('…the full PDF too', '42.5' in full and '0 ft' not in full)
ok('…its page and edit page open', c.get(f'/projects/{pa.id}').status_code == 200
   and c.get(f'/projects/{pa.id}/edit').status_code == 200 and '"area": 42.5' in c.get(f'/projects/{pa.id}/edit').text)
wa = unquote(c.get(f'/projects/{pa.id}/whatsapp').headers.get('Location', ''))
ok('…WhatsApp gives its area', 'Panelling' in wa and '0 ft ×' not in wa)
