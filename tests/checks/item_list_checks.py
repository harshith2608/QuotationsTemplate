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
