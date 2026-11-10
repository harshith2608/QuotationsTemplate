"""Pricing by material with the BOQ table (every item on its own line): one amount per room, no plywood on each line,
the material before the business's own description."""
import io, json, re
from urllib.parse import unquote
from pypdf import PdfReader
from app import create_app, db, billing, layout
from app.models import AppSetting, Project, QuoteShare
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
