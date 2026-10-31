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
    pid, inv_url, cname, ctotal = p.id, f'/projects/{inv.project_id}/invoices/{inv.id}/pdf', p.customer_name, p.final_total
    presentation.set_enabled(True); db.session.commit()
urls = [f'/projects/{pid}/pdf/customer', f'/projects/{pid}/pdf', inv_url]
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms',
                                'about_us': '<p>Our <span style="color: rgb(201, 162, 39);">story</span></p>', 'next_steps': ''})

s = c.get('/admin/settings?tab=documents').text
ok('Settings → Quotation PDFs: "How your PDF looks" with brand colours chosen by default',
   'How your PDF looks' in s and 'id="pdf_colours_brand" value="brand" checked' in s and 'id="pdf_colours_bw" value="bw" ' in s
   and 'id="pdf_font_modern" value="modern" checked' in s and 'id="pdf_header_centre" value="centre" checked' in s
   and '/pdf/customer" target="_blank"' in s)
before = {u: colours(u) for u in urls}
ok('brand colours: the PDFs have colour (customer, full, invoice)', all(not grey(cs) for cs in before.values()))

c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms', 'pdf_colours': 'bw'})
with app.app_context():
    ok('black & white saved', pdf_look.colours() == pdf_look.BW)
ok('the choice shows as chosen', 'id="pdf_colours_bw" value="bw" checked' in c.get('/admin/settings?tab=documents').text)
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

# Font: modern (Helvetica) by default, classic (Times) for every font on the page
FONT = re.compile(rb'/BaseFont /([A-Za-z-]+)')
def fonts(url):
    out = set()
    for page in PdfReader(io.BytesIO(c.get(url).data)).pages:
        for f in (page.get('/Resources') or {}).get('/Font', {}).values():
            out.add(f.get_object()['/BaseFont'].lstrip('/'))
    return out
ok('modern font: Helvetica', all(f.startswith('Helvetica') for u in urls for f in fonts(u)))
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms', 'pdf_font': 'classic'})
with app.app_context():
    ok('classic font saved', pdf_look.font() == pdf_look.CLASSIC)
ok('classic font: every font in the customer PDF, the full PDF and the invoice is Times (regular and bold)',
   all(fonts(u) and all(f.startswith('Times') for f in fonts(u)) for u in urls) and {'Times-Roman', 'Times-Bold'} <= fonts(urls[0]))
text = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))
ok('classic font: the quotation still reads the same (customer name and total)', cname in text(urls[0])
   and f'{ctotal:,.2f}' in text(urls[0]))

# Header: centred by default, or the logo on the left and the details on the right
first = lambda u: PdfReader(io.BytesIO(c.get(u).data)).pages
def name_x(url):
    """Where the company name starts on page 1 (of the quotation, after the presentation title page)."""
    pages = first(url)
    page = pages[1] if len(pages) > 2 and 'CUSTOMER QUOTATION' not in pages[0].extract_text() else pages[0]
    xs = []
    page.extract_text(visitor_text=lambda t, cm, tm, fd, fs: xs.append(round(cm[0] * tm[4] + cm[4], 1)) if 'Demo Interiors' in t else None)
    return xs[0] if xs else None
with app.app_context():
    presentation.set_enabled(False); db.session.commit()
x_centre = name_x(urls[0])
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms', 'pdf_header': 'left'})
with app.app_context():
    ok('header saved', pdf_look.header() == pdf_look.LEFT)
x_left = name_x(urls[0]); x_inv = name_x(inv_url)
ok(f'details on the right: the company name moves right on the quotation and the invoice ({x_centre} → {x_left}, {x_inv})',
   x_centre and x_left and x_inv and x_left > x_centre + 60 and x_inv > x_centre + 60)
ok('every choice can go back to the default', c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms',
   'pdf_colours': 'brand', 'pdf_font': 'modern', 'pdf_header': 'centre'}).status_code == 302)
with app.app_context():
    from app.models import AppSetting
    ok('defaults are stored as empty', [AppSetting.get(k, '') for k in (pdf_look.COLOURS_KEY, pdf_look.FONT_KEY, pdf_look.HEADER_KEY)] == ['', '', ''])
