"""No's on area lines as a factor on the rate (Settings → Pricing, app/boq.py nos_on_rate) and page breaks before the
PDF's sections (Settings → Quotation PDFs, app/layout.py page_breaks)."""
import io, json, re
from pypdf import PdfReader
from reportlab.platypus import CondPageBreak, PageBreak
from app import create_app, db, boq, layout
from app.models import AppSetting, Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pdftext = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))

with app.app_context():
    boq.set_pricing(boq.ITEM); AppSetting.set(layout.LAYOUT_KEY, layout.LAYOUT_BOQ); db.session.commit()


def quote(name, count):
    rooms = [{'name': 'Entrance Foyer', 'items': [{'type': 'boq', 'name': 'False Ceiling', 'unit': 'sqft', 'quantity': 0,
                                                   'unit_price': 120, 'length': 900, 'width': 1, 'count': count}]}]
    c.post('/projects/new', data={'customer_name': name, 'mobile': '9000000444', 'rooms_data': json.dumps(rooms),
                                  'discount_type': 'none', 'discount_value': '0'})
    with app.app_context():
        p = Project.query.order_by(Project.id.desc()).first()
        it = p.rooms_with_items()[0].item_list[0]
        return p.id, it.quantity, p.grand_total

pid, qty, total = quote('Nos Pieces', 2)
ok('off (the default): No\'s counts pieces (900 × 1 × 2 = 1,800 sqft)', qty == 1800 and total == 216000)

c.post('/admin/settings', data={'section': 'pricing', 'pricing_mode': 'item', 'nos_on_rate_shown': '1', 'nos_on_rate': '1'})
with app.app_context():
    ok('Settings → Pricing turns it on', boq.nos_on_rate())
ok('the switch is on the Pricing tab', 'name="nos_on_rate"' in c.get('/admin/settings?tab=pricing').text)
pid, qty, total = quote('Nos Factor', 1.25)
ok('on: No\'s 1.25 multiplies the rate (900 sqft × ₹120 × 1.25 = ₹1,35,000)', qty == 1125 and total == 135000)
v = c.get(f'/projects/{pid}').text
ok('the quotation page shows the measured 900 sqft at ₹150', '>900<' in v.replace(' ', '') and '150' in v and '1125' not in v)
t = pdftext(f'/projects/{pid}/pdf/customer')
ok('the PDF: 900 at 150, no No\'s', '900' in t and '150' in t and '1,125' not in t and '1.25' not in t and 'Nos.' not in t.split('False Ceiling', 1)[1][:80])
form = c.get(f'/projects/{pid}/edit').text
ok('the form gets No\'s back as 1.25 (and the rate as typed, 120)', '"count": 1.25' in form and '"unit_price": 120' in form
   and 'nosOnRate:   true' in form)
with app.app_context():
    from app import billing
    snap = billing.quotation_snapshot(db.session.get(Project, pid))
    row = snap['rooms'][0]['items'][0]
ok('the link / revision snapshot: 900 × 150, same amount', row['quantity'] == 900 and row['unit_price'] == 150
   and row['amount'] == 135000 and row.get('count', 1) == 1)
wa = c.get(f'/projects/{pid}/whatsapp').headers.get('Location', '')
from urllib.parse import unquote
ok('WhatsApp: 900 at Rs.150, the same amount', 'False Ceiling: 900 ' in unquote(wa) and ('Rs.150' in unquote(wa) or 'Rs.1,35,000' in unquote(wa))
   and '1125' not in unquote(wa))
pid2, qty2, total2 = quote('Nos Whole', 2)
ok('whole No\'s on: still the same amount (900 × 120 × 2)', total2 == 216000)
c.post('/admin/settings', data={'section': 'pricing', 'pricing_mode': 'item', 'nos_on_rate_shown': '1'})
with app.app_context():
    ok('turned off again', not boq.nos_on_rate())

# page breaks before the sections
with app.app_context():
    for k in ('payment_terms', 'important_notes', 'terms_conditions'):
        if not AppSetting.get(k):
            AppSetting.set(k, 'Something to print')
    db.session.commit()


def flow():
    from app import pdf_utils
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    with app.test_request_context():
        return pdf_utils._section_elements(getSampleStyleSheet(), colors.black)

with app.app_context():
    ok('never chosen: automatic (new page only with less than half a page left)', layout.page_breaks() is None)
el = flow()
ok('… one conditional break before the sections', any(isinstance(e, CondPageBreak) for e in el)
   and not any(type(e) is PageBreak for e in el))
s = c.get('/admin/settings?tab=documents').text
ok('Settings → Quotation PDFs: a new-page tick on each section', s.count('Start on a new page in the PDF</label>') == 5)
c.post('/admin/settings', data={'section': 'documents', 'page_breaks_shown': '1', 'page_break': ['payment_terms', 'terms_conditions']})
with app.app_context():
    ok('ticked ones saved', layout.page_breaks() == ['payment_terms', 'terms_conditions'])
el = flow()
ok('the PDF breaks before those two only (no automatic break)', sum(type(e) is PageBreak for e in el) == 2
   and not any(isinstance(e, CondPageBreak) and type(e) is not PageBreak for e in el))
c.post('/admin/settings', data={'section': 'documents', 'quote_valid_days': '30'})
with app.app_context():
    ok('saving something else on the tab keeps them', layout.page_breaks() == ['payment_terms', 'terms_conditions'])
c.post('/admin/settings', data={'section': 'documents', 'page_breaks_shown': '1'})
el = flow()
ok('none ticked: the sections follow straight on (no gap)', not any(isinstance(e, (PageBreak, CondPageBreak)) for e in el))
ok('the PDF still opens', c.get(f'/projects/{pid}/pdf/customer').status_code == 200)
