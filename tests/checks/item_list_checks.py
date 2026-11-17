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

# Rich text in the quotation sections (Settings → Quotation PDFs): kept formatted, cleaned, printed on the PDF
html_terms = ('<p><strong>Payment</strong> as below<script>alert(1)</script></p><ol><li data-list="ordered">10% advance '
              'with <span style="color: rgb(230, 0, 0);">order</span></li><li data-list="ordered">Board: {plywood}</li></ol>')
c.post('/admin/settings', data={'section': 'documents', 'payment_terms': html_terms,
                                'important_notes': 'Plain note one\nPlain note two'})
with app.app_context():
    saved_pt = AppSetting.get('payment_terms')
    sec = {t: (lines, html) for t, lines, html in
           layout.sections({'payment_terms': saved_pt, 'important_notes': AppSetting.get('important_notes')}, '',
                           {'plywood': 'Ply & Co <18mm>'})}
ok('rich text saved cleaned: formatting kept, the script dropped', '<strong>Payment</strong>' in saved_pt
   and 'script' not in saved_pt and 'alert' not in saved_pt and 'color' in saved_pt)
ok('…{plywood} filled in (escaped), plain sections still lines', 'Ply &amp; Co &lt;18mm&gt;' in sec['Payment Terms'][1]
   and sec['Important Notes'][1] is None and sec['Important Notes'][0] == ['Plain note one', 'Plain note two'])
pt_pdf = pdftext(f'/projects/{pid}/pdf/customer')
ok('…printed on the PDF: the formatted section and the plain one', 'Payment as below' in pt_pdf and '10% advance with order'
   in pt_pdf and 'Plain note one' in pt_pdf and 'alert' not in pt_pdf)
page = c.get('/admin/settings?tab=documents').text
ok('…the settings page opens them in editors (plain text as a numbered list)', 'data-for="sec_payment_terms"' in page
   and 'data-for="sec_terms_conditions"' in page and '&lt;li data-list=&#34;ordered&#34;&gt;Plain note one' in page)

# Choose what the PDF shows (app/pdf_choices.py): off unless switched on; tick-boxes before the PDF; kept per quotation
from app import pdf_choices as PC
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'boq', 'boq_rate_shown': '1',
                                'boq_room_totals': '0', 'boq_board_shown': '1'})
view = c.get(f'/projects/{pid}').text
ok('PDF choices off (an existing business): Quotation PDF opens straight away, no tick-boxes',
   'id="pdfPickModal"' not in view and f'/projects/{pid}/pdf/customer' in view)
with app.app_context():
    PC.set_enabled(True); db.session.commit()
view = c.get(f'/projects/{pid}').text
ok('…switched on: the button opens the tick-boxes, ticked as the business prints today', 'id="pdfPickModal"' in view
   and 'data-bs-target="#pdfPickModal"' in view and 'id="pp_rate" checked' in view and 'id="pp_amount" checked' in view
   and 'id="pp_description" checked' in view)
full_before = pdftext(f'/projects/{pid}/pdf/customer')
r = c.post(f'/projects/{pid}/pdf/choose', data={'description': '1', 'room_total': '1'})   # no qty, rate, amount, material
after = pdftext(f'/projects/{pid}/pdf/customer')
with app.app_context():
    chosen = PC.for_project(pid)
ok('…a choice: kept for the quotation, then its PDF', r.status_code == 302 and r.headers['Location'].endswith(f'/projects/{pid}/pdf/customer')
   and chosen['description'] and not chosen['qty'] and not chosen['rate'] and not chosen['amount'])
ok('…the PDF shows only that: no Qty, Rate or line amounts; the room total and the description stay',
   'Qty' in full_before and 'Qty' not in after and ' Rate ' not in after and inr(tv_amount) not in after
   and 'Glass door in the side' in after and inr(room_total) in after)
with app.app_context():
    sh2 = QuoteShare.query.filter_by(project_id=pid, active=True).first()
if sh2:
    pub2 = app.test_client().get(f'/q/{sh2.token}').text
    ok('…the customer\'s link the same', inr(tv_amount) not in pub2 and 'Glass door in the side' in pub2)
c.post(f'/projects/{pid}/pdf/choose', data={})                                  # everything unticked
bare = c.get(f'/projects/{pid}/pdf/customer')
ok('…everything unticked: still a PDF (item names and totals)', bare.status_code == 200 and bare.data[:4] == b'%PDF'
   and 'TV Unit' in pdftext(f'/projects/{pid}/pdf/customer'))
with app.app_context():
    PC.set_enabled(False); db.session.commit()
ok('…switched off again: back to the business\'s settings', 'Qty' in pdftext(f'/projects/{pid}/pdf/customer'))

# Photo pages (app/photo_pages.py): full-page pictures at the front of the PDF and link; copied with templates
from app import item_images as IMG, photo_pages as PP
from PIL import Image as _Img
def _page_png(colour):
    b = io.BytesIO(); _Img.new('RGB', (1414, 2000), colour).save(b, 'PNG'); return b.getvalue()
ok('cover & gallery: off unless switched on (its own switch, not Item photos or PDF choices)',
   'id="photoPages"' not in c.get(f'/projects/{pid}').text)
with app.app_context():
    PP.set_enabled(True); PC.set_enabled(True); db.session.commit()
ok('…switched on: the card on the quotation', 'id="photoPages"' in c.get(f'/projects/{pid}').text)
pages_before = len(PdfReader(io.BytesIO(c.get(f'/projects/{pid}/pdf/customer').data)).pages)
r = c.post(f'/projects/{pid}/pages', data={'pages': [(io.BytesIO(_page_png('teal')), 'cover.png'),
                                                     (io.BytesIO(_page_png('white')), 'about.png')]},
           content_type='multipart/form-data')
with app.app_context():
    ids = PP.for_project(pid)
    big = db.session.get(__import__('app.models', fromlist=['ItemImage']).ItemImage, ids[0])
ok('…two pages added, stored at print size (not the 900 px of line photos)', len(ids) == 2 and big.height > 1500)
pdf_pages = PdfReader(io.BytesIO(c.get(f'/projects/{pid}/pdf/customer').data)).pages
ok('…the PDF: the photos together on one gallery page in front, then the quotation', len(pdf_pages) == pages_before + 1
   and not (pdf_pages[0].extract_text() or '').strip() and 'TV Unit' in (pdf_pages[1].extract_text() or ''))
c.post(f'/projects/{pid}/cover', data={'print_seen': '1', 'print_cover': '1'})          # gallery unticked
ok('…unticked "Print the gallery" on the quotation: left out', len(PdfReader(io.BytesIO(c.get(f'/projects/{pid}/pdf/customer').data)).pages) == pages_before)
c.post(f'/projects/{pid}/cover', data={'print_seen': '1', 'print_cover': '1', 'print_gallery': '1'})
with app.app_context():
    sh3 = QuoteShare.query.filter_by(project_id=pid, active=True).first()
if sh3:
    pub3 = app.test_client().get(f'/q/{sh3.token}').text
    ok('…the customer\'s link shows them, and serves only this quotation\'s pictures',
       f'/q/{sh3.token}/photo/{ids[0]}' in pub3 and app.test_client().get(f'/q/{sh3.token}/photo/{ids[0]}').status_code == 200
       and app.test_client().get(f'/q/{sh3.token}/photo/999999').status_code == 404)
c.post(f'/projects/{pid}/pages/{ids[1]}', data={'do': 'up'})
with app.app_context():
    ok('…moved earlier', PP.for_project(pid) == [ids[1], ids[0]])
r = c.post(f'/projects/{pid}/template', data={'name': 'With pages'})
with app.app_context():
    from app import quote_templates as QT2
    tpl = next(t for t in QT2._load() if t['name'] == 'With pages')
ok('save as template: its photo pages copied (by id)', tpl.get('photo_pages') == [ids[1], ids[0]])
form = c.get(f'/projects/new?template={tpl["id"]}').text
ok('…a new quotation from it carries them', f'name="photo_pages" value="{ids[1]},{ids[0]}"' in form)
c.post('/projects/new', data={'customer_name': 'From Tpl', 'mobile': '9000000333', 'discount_type': 'none',
                              'discount_value': '0', 'photo_pages': f'{ids[1]},{ids[0]}',
                              'rooms_data': json.dumps([{'name': 'Hall', 'items': [{'name': 'Shelf', 'length': 3, 'width': 1,
                                                                                    'wood_type': wood, 'work_type': work}]}])})
with app.app_context():
    newp = Project.query.order_by(Project.id.desc()).first()
    ok('…saved with the same photo pages', PP.for_project(newp.id) == [ids[1], ids[0]])
c.post(f'/projects/{pid}/pages/{ids[0]}', data={'do': 'remove'})
with app.app_context():
    ok('…removing one from a quotation leaves the template and the other quotation as they were',
       PP.for_project(pid) == [ids[1]] and PP.for_project(newp.id) == [ids[1], ids[0]])

# The designed cover page: slogan / tagline in Settings, package name from the template, the cover photo copied
c.post('/admin/settings', data={'section': 'documents', 'cover_slogan': 'Luxury crafted for modern living',
                                'cover_tagline': 'Your dream home, professionally managed'})
with app.app_context():
    ok('cover: slogan and tagline saved in Settings → Quotation PDFs', PP.texts() == {
        'slogan': 'Luxury crafted for modern living', 'tagline': 'Your dream home, professionally managed'})
ok('…the settings card is there', 'id="cover-page"' in c.get('/admin/settings?tab=documents').text)
c.post(f'/projects/{pid}/cover', data={'print_seen': '1', 'print_cover': '1'})          # (the gallery off: just the cover)
before_cover = len(PdfReader(io.BytesIO(c.get(f'/projects/{pid}/pdf/customer').data)).pages)
c.post(f'/projects/{pid}/cover', data={'photo': (io.BytesIO(_page_png('olive')), 'door.png'), 'package': 'DIY Package'},
       content_type='multipart/form-data')
cov_pdf = PdfReader(io.BytesIO(c.get(f'/projects/{pid}/pdf/customer').data))
first = re.sub(r'\s+', ' ', cov_pdf.pages[0].extract_text() or '')
ok('…with a cover photo: the cover is the first page (name, slogan, tagline, package name)',
   len(cov_pdf.pages) == before_cover + 1 and 'LUXURY CRAFTED FOR MODERN LIVING' in first
   and 'Your dream home, professionally managed' in first and 'DIY PACKAGE' in first)
c.post(f'/projects/{pid}/cover', data={'print_seen': '1'})
ok('…unticked "Print the cover": left out', len(PdfReader(io.BytesIO(c.get(f'/projects/{pid}/pdf/customer').data)).pages) == before_cover
   and 'LUXURY' not in (PdfReader(io.BytesIO(c.get(f'/projects/{pid}/pdf/customer').data)).pages[0].extract_text() or ''))
c.post(f'/projects/{pid}/cover', data={'print_seen': '1', 'print_cover': '1', 'print_gallery': '1'})
with app.app_context():
    cover_id = PP.cover_photo(pid)
c.post(f'/projects/{pid}/template', data={'name': 'Premium Package'})
with app.app_context():
    tpl2 = next(t for t in QT2._load() if t['name'] == 'Premium Package')
ok('…Save as template copies the cover photo', tpl2.get('cover_photo') == cover_id)
form2 = c.get(f'/projects/new?template={tpl2["id"]}').text
ok('…a quotation from it: the same cover photo, the package named after the template',
   f'name="cover_photo" value="{cover_id}"' in form2 and 'name="package" value="Premium Package"' in form2)
c.post('/projects/new', data={'customer_name': 'Cover Copy', 'mobile': '9000000222', 'discount_type': 'none',
                              'discount_value': '0', 'cover_photo': str(cover_id), 'package': 'Premium Package',
                              'rooms_data': json.dumps([{'name': 'Hall', 'items': [{'name': 'Shelf', 'length': 3, 'width': 1,
                                                                                    'wood_type': wood, 'work_type': work}]}])})
with app.app_context():
    p3 = Project.query.order_by(Project.id.desc()).first()
    ok('…saved with them', PP.cover_photo(p3.id) == cover_id and PP.package(p3.id) == 'Premium Package')

# The approval link: the same "what should it show" window before creating it, and to change it after
with app.app_context():
    PC.set_enabled(True); db.session.commit()
page3 = c.get(f'/projects/{p3.id}').text
ok('approval link: "Create approval link" opens the same window (pointed at creating the link)',
   f'data-pick-action="/projects/{p3.id}/share"' in page3 and 'data-pick-mode="create"' in page3)
r = c.post(f'/projects/{p3.id}/share', data={'pick': '1', 'description': '1', 'room_total': '1'})
with app.app_context():
    sh4 = QuoteShare.query.filter_by(project_id=p3.id, active=True).first()
    ch4 = PC.for_project(p3.id)
ok('…created with the choice (no rates or line amounts)', sh4 is not None and not ch4['rate'] and not ch4['amount']
   and ch4['description'] and r.headers['Location'].endswith('#approval'))
page3 = c.get(f'/projects/{p3.id}').text
ok('…then "What the link shows" changes it (same window, saving back to the link)', 'data-pick-mode="link"' in page3
   and 'What the link shows' in page3)
r = c.post(f'/projects/{p3.id}/pdf/choose', data={'then': 'link', **{k: '1' for k in PC.KEYS}})
with app.app_context():
    ch5 = PC.for_project(p3.id)
ok('…saved for the link: back to the link (not a PDF), now with rates and amounts', r.headers['Location'].endswith('#approval')
   and ch5['rate'] and ch5['amount'])
pub4 = app.test_client().get(f'/q/{sh4.token}').text
ok('…and the customer\'s link follows it', 'Shelf' in pub4)

# Defaults for quotations without their own cover / gallery (Settings → Cover & gallery): from scratch too
ok('defaults page: there with Cover & gallery on', c.get('/admin/cover-photos').status_code == 200)
c.post('/admin/cover-photos', data={'do': 'cover', 'photo': (io.BytesIO(_page_png('navy')), 'cover.png')},
       content_type='multipart/form-data')
c.post('/admin/cover-photos', data={'do': 'add', 'photos': [(io.BytesIO(_page_png('gray')), 'a.png'),
                                                            (io.BytesIO(_page_png('silver')), 'b.png')]},
       content_type='multipart/form-data')
with app.app_context():
    dcov, dgal = PP.default_cover(), PP.default_gallery()
ok('…a default cover photo and a gallery of two saved', dcov and len(dgal) == 2)
c.post('/projects/new', data={'customer_name': 'From Scratch', 'mobile': '9000000111', 'discount_type': 'none',
                              'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Hall', 'items': [
                                  {'name': 'Shelf', 'length': 3, 'width': 1, 'wood_type': wood, 'work_type': work}]}])})
with app.app_context():
    scratch = Project.query.order_by(Project.id.desc()).first()
    ok('…a quotation from scratch has none of its own', PP.cover_photo(scratch.id) is None and PP.for_project(scratch.id) == [])
sp_pdf = PdfReader(io.BytesIO(c.get(f'/projects/{scratch.id}/pdf/customer').data)).pages
ok('…yet its PDF opens with the cover and the default gallery', 'LUXURY CRAFTED' in (sp_pdf[0].extract_text() or '')
   and not (sp_pdf[1].extract_text() or '').strip() and 'Shelf' in ' '.join(p.extract_text() or '' for p in sp_pdf[2:]))
ok('…its page says it uses the defaults', 'your default' in c.get(f'/projects/{scratch.id}').text
   and 'Using your default gallery (2 photos)' in c.get(f'/projects/{scratch.id}').text)
c.post(f'/projects/{scratch.id}/share', data={})
with app.app_context():
    sh5 = QuoteShare.query.filter_by(project_id=scratch.id, active=True).first()
ok('…its link shows (and serves) the default gallery', sh5 and f'/q/{sh5.token}/photo/{dgal[0]}' in app.test_client().get(f'/q/{sh5.token}').text
   and app.test_client().get(f'/q/{sh5.token}/photo/{dgal[0]}').status_code == 200)
c.post(f'/projects/{scratch.id}/pages', data={'pages': [(io.BytesIO(_page_png('red')), 'own.png')]}, content_type='multipart/form-data')
with app.app_context():
    ok('…its own gallery replaces the default for it', len(PP.effective_gallery(scratch.id)) == 1
       and PP.effective_gallery(scratch.id)[0] not in dgal and PP.default_gallery() == dgal)
