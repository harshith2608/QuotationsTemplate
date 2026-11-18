"""Pricing by material, choosing what the PDF shows (console switch): one Quotation PDF (the item table) with the
tick-boxes, instead of Full and Initial Quotation; switched off, both as before."""
import io, re
from pypdf import PdfReader
from app import create_app, db, boq, layout, pdf_choices
from app.models import Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
text = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))

with app.app_context():
    ok('the demo prices by material', not boq.enabled())
    pid = Project.query.filter(Project.status != 'draft').order_by(Project.id).first().id
v = c.get(f'/projects/{pid}').text
ok('switch off: Full Quotation and Initial Quotation as before', 'Full Quotation' in v and 'Initial Quotation' in v
   and 'id="pdfPickModal"' not in v)

with app.app_context():
    pdf_choices.set_enabled(True); db.session.commit()
    ok('switch on: one quotation PDF, the item table', layout.single_pdf() and layout.initial_layout() == layout.LAYOUT_BOQ)
v = c.get(f'/projects/{pid}').text
ok('…the quotation page has one Quotation PDF button with the tick-boxes', 'Full Quotation' not in v
   and 'Initial Quotation' not in v and 'id="pdfPickModal"' in v and 'Quotation PDF' in v)
s = c.get('/admin/settings?tab=documents').text
ok('…Settings explains it (no layout to pick)', 'One quotation PDF: every item on its own numbered line' in s
   and 'name="initial_layout"' not in s)
full = text(f'/projects/{pid}/pdf/customer')
ok('…the PDF: the item table with sizes and rates', 'Bill of Quantities' in full and ' ft ' in full and 'Rate' in full)
c.post(f'/projects/{pid}/pdf/choose', data={'description': '1', 'material': '1', 'qty': '1', 'room_total': '1'})
with app.app_context():
    chosen = pdf_choices.for_project(pid)
ok('…choices saved for the quotation (size, rate, amount unticked)', not chosen['size'] and not chosen['rate']
   and not chosen['amount'] and chosen['room_total'])
picked = text(f'/projects/{pid}/pdf/customer')
ok('…and the PDF follows them: no sizes, no Rate column', 'Bill of Quantities' in picked and ' × ' not in picked
   and 'Rate' not in picked)
ok('…the Full Quotation link gives the same one PDF', 'Rate' not in text(f'/projects/{pid}/pdf'))
with app.app_context():
    pdf_choices.set_enabled(False); db.session.commit()
ok('switched off again: both PDFs back', 'Full Quotation' in c.get(f'/projects/{pid}').text)
