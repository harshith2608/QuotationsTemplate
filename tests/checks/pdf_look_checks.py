"""How your PDF looks (app/pdf_look.py): brand colours by default; black & white turns every colour the PDFs draw
(text, lines, shading, rich text colours) into black or grey, for the quotation PDFs, revisions and invoices."""
import io, re
from pypdf import PdfReader
from app import create_app, db, pdf_look, presentation
from app.models import Invoice, Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
COLOUR = re.compile(rb'(?<![\d.])([\d.]+) ([\d.]+) ([\d.]+) (rg|RG)\b')


def colours(url):
    """The fill / stroke colours set in the PDF's pages, as (r, g, b)."""
    r = c.get(url)
    assert r.status_code == 200, (url, r.status_code)
    out = set()
    for page in PdfReader(io.BytesIO(r.data)).pages:
        for m in COLOUR.finditer(page.get_contents().get_data()):
            out.add(tuple(round(float(m.group(i)), 3) for i in (1, 2, 3)))
    return out


grey = lambda cs: all(r == g == b for r, g, b in cs)
with app.app_context():
    p = next(x for x in Project.query.filter(Project.status != 'draft').all() if x.final_total > 0)
    inv = Invoice.query.first()
    pid, inv_url = p.id, f'/projects/{inv.project_id}/invoices/{inv.id}/pdf'
    presentation.set_enabled(True); db.session.commit()
urls = [f'/projects/{pid}/pdf/customer', f'/projects/{pid}/pdf', inv_url]
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms',
                                'about_us': '<p>Our <span style="color: rgb(201, 162, 39);">story</span></p>', 'next_steps': ''})

s = c.get('/admin/settings?tab=documents').text
ok('Settings → Quotation PDFs: "How your PDF looks" with brand colours chosen by default',
   'How your PDF looks' in s and 'id="pc_brand" value="brand" checked' in s and 'id="pc_bw" value="bw" ' in s)
before = {u: colours(u) for u in urls}
ok('brand colours: the PDFs have colour (customer, full, invoice)', all(not grey(cs) for cs in before.values()))

c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms', 'pdf_colours': 'bw'})
with app.app_context():
    ok('black & white saved', pdf_look.colours() == pdf_look.BW)
ok('the choice shows as chosen', 'id="pc_bw" value="bw" checked' in c.get('/admin/settings?tab=documents').text)
after = {u: colours(u) for u in urls}
ok('black & white: every colour in the customer PDF (with presentation pages and rich text colours), the full PDF and '
   'the invoice is black or grey', all(cs and grey(cs) for cs in after.values()))
ok('dark brand colours print as pure black', all((0.0, 0.0, 0.0) in cs for cs in after.values()))

with app.app_context():
    ok('grey(): hex, names, tuples and CMYK; dark → black, light kept as grey, white stays white',
       pdf_look.grey('#1a237e').red == 0 and pdf_look.grey('white').red == 1 and pdf_look.grey((1, 1, 0)).red == pdf_look.grey((1, 1, 0)).blue == 0.886
       and pdf_look.grey((0, 0, 0, 1)).red == 0 and abs(pdf_look.grey('#f5f5f5').green - 0.961) < 0.01)

c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms', 'pdf_colours': 'nonsense'})
with app.app_context():
    ok('an unknown choice is ignored', pdf_look.colours() == pdf_look.BW)
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms', 'pdf_colours': 'brand'})
ok('back to brand colours: colour again', not grey(colours(urls[0])))
