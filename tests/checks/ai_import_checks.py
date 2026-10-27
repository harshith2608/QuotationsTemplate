"""Bring your old quotation (app/ai_import.py): off unless switched on (AI_IMPORT=1 here; the console's switch in the
shared app) with the API key; PDF/Excel text only (scans and .xls refused); the AI's reading tidied for the review;
the reviewed lines set up the business like Load price list; a limit per business. The AI itself is replaced by a
fixed reading, so no request leaves the machine."""
import io
import os
from app import create_app, db, ai_import as AI
from app.models import AppSetting, BoqItem, Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
for k in ('AI_IMPORT', 'ANTHROPIC_API_KEY', 'DEMO_MODE'):
    os.environ.pop(k, None)


def pdf(text_lines):
    from reportlab.pdfgen.canvas import Canvas
    buf = io.BytesIO()
    c = Canvas(buf)
    y = 800
    for line in text_lines:
        c.drawString(40, y, line)
        y -= 14
    c.save()
    return buf.getvalue()


QUOTE = pdf(['SHARMA INTERIORS - QUOTATION', 'Customer: Mr. Real Person, 9876543210, Flat 4 Real Street'] +
            [f'{n}. Item number {n} for the bedroom, laminate finish, sqft 10 x 1450 = 14500' for n in range(1, 12)])
BLANK = pdf([])

READING = AI.Quote(
    job_title='2 BHK interiors',
    sections=[AI.Section(name='A. Master Bedroom', lines=[
                  AI.Line(name='1.1 Wardrobe', description='Laminate finish', size="7'6\" x 9'6\"", unit='Sq.ft',
                          quantity=71.25, rate=1450, amount=103312.5),
                  AI.Line(name='1.2 Loft', description='Loft', size='', unit='sft', quantity=20, rate=None, amount=24000),
                  AI.Line(name='1.3 Side table', description='', size='', unit='Nos.', quantity=None, rate=None, amount=15000)]),
              AI.Section(name='B. Kitchen', lines=[
                  AI.Line(name='Wardrobe', description='Utility', size='', unit='Sq.ft', quantity=10, rate=1300, amount=13000),
                  AI.Line(name='Tandem drawer', description='Hettich', size='', unit='Nos', quantity=4, rate=4500, amount=18000),
                  AI.Line(name='False ceiling', description='', size='696', unit='Sq.ft', quantity=1, rate=120, amount=83520),
                  AI.Line(name='Rotating chair', description='', size='', unit='Nos.', quantity=2, rate=40000, amount=None)])],
    charges=[AI.Charge(name='Design fee', amount=17331)],
    subtotal=173312.5, discount=5000, gst_percent=18, grand_total=None,
    payment_terms='50% advance, 40% before installation, 10% on handover.', notes_and_terms='Prices valid for 30 days.')
calls = []


def fake_read(body):
    calls.append(body)
    return READING, {'in': 2000, 'out': 1500}


AI.read = fake_read

# ── Off (default) ──
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
admin = app.test_client(); admin.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
ok('off by default: no page, no menu item, no setup card', admin.get('/admin/import').status_code == 404
   and 'Import a quotation' not in admin.get('/projects').text and 'bring your old quotation' not in admin.get('/admin/setup').text)
os.environ['AI_IMPORT'] = '1'
ok('switched on but no API key: still off', admin.get('/admin/import').status_code == 404)
os.environ['ANTHROPIC_API_KEY'] = 'test-key-not-real'
t = admin.get('/admin/import').text
ok('on: the upload page (PDF or Excel), the menu item and the setup guide card', 'Read my quotation' in t
   and 'accept=".pdf,.xlsx' in t and 'Import a quotation' in admin.get('/projects').text
   and 'bring your old quotation' in admin.get('/admin/setup').text
   and ('5 imports left (5 during your free trial)' in t or '20 imports left (20 a month)' in t))
staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
ok('staff can\'t import', staff.get('/admin/import').status_code == 403)


def upload(raw, name):
    return admin.post('/admin/import', data={'file': (io.BytesIO(raw), name)}, content_type='multipart/form-data',
                      follow_redirects=True)


r = upload(BLANK, 'scan.pdf')
ok('a scanned PDF (no text) is refused: upload the original', 'is a scan' in r.text and not calls)
r = upload(b'\xd0\xcf\x11\xe0 old excel', 'quote.xls')
ok('an old .xls: save it as .xlsx', 'Save As' in r.text and not calls)
r = upload(b'hello', 'notes.txt')
ok('anything else: PDF or Excel only', 'Upload a PDF or an Excel file' in r.text and not calls)

r = upload(QUOTE, 'Sharma quote.pdf')
t = r.text
ok('a PDF: only its text goes to the AI', len(calls) == 1 and 'Item number 3 for the bedroom' in calls[0])
ok('review: sections and lines, serial numbers taken off the names, units tidied', 'value="Master Bedroom"' in t
   and 'value="Kitchen"' in t and 'value="Wardrobe"' in t and 'value="1.1 Wardrobe"' not in t and 'value="sqft"' in t
   and 'value="nos"' in t)
ok('…a rate worked out from amount ÷ quantity when only the amount is printed (loft 24,000 ÷ 20 = 1,200)',
   'name="s0_1_rate" type="number" step="any" min="0" value="1200"' in t)
ok('…a lump amount with no quantity becomes 1 × the amount; the size kept in the description', 'name="s0_2_quantity" type="number" step="any" min="0" value="1"' in t
   and 'Size: 7&#39;6&#34; x 9&#39;6&#34;' in t)
ok('…area and count columns: the printed amount wins (1 × ₹120 printed as ₹83,520 → 696 sqft)',
   'name="s1_2_quantity" type="number" step="any" min="0" value="696"' in t)
ok('…a line with a rate but no amount printed is pointed out (maybe not in their total)',
   t.count('No amount in your file') == 1)
ok('…the printed total for the add-up check, GST 18% picked, charges, terms', 'const printed = 173312.5' in t
   and '<option value="18" selected>' in t and 'value="Design fee"' in t and '50% advance' in t
   and 'value="2 BHK interiors"' in t)
with app.app_context():
    ok('one import counted for the trial', AI.left()[0] == 4 if AI.left()[1].startswith('5') else AI.left()[0] == 19)

# The admin corrects a rate and unticks a line, then sets up the app
form = {'job_title': '2 BHK interiors', 'discount': '5000', 'gst': '18', 'sections': '2', 'charges': '1',
        's0_name': 'Master Bedroom', 's0_lines': '3',
        's0_0_keep': '1', 's0_0_name': 'Wardrobe', 's0_0_description': 'Laminate finish', 's0_0_unit': 'sqft',
        's0_0_quantity': '71.25', 's0_0_rate': '1450',
        's0_1_keep': '1', 's0_1_name': 'Loft', 's0_1_description': '', 's0_1_unit': 'sqft', 's0_1_quantity': '20', 's0_1_rate': '1250',
        's0_2_name': 'Side table', 's0_2_unit': 'nos', 's0_2_quantity': '1', 's0_2_rate': '15000',       # unticked
        's1_name': 'Kitchen', 's1_lines': '2',
        's1_0_keep': '1', 's1_0_name': 'Wardrobe', 's1_0_description': 'Utility', 's1_0_unit': 'sqft', 's1_0_quantity': '10', 's1_0_rate': '1300',
        's1_1_keep': '1', 's1_1_name': 'Tandem drawer', 's1_1_description': 'Hettich', 's1_1_unit': 'nos', 's1_1_quantity': '4', 's1_1_rate': '4500',
        'c0_keep': '1', 'c0_name': 'Design fee', 'c0_amount': '17331',
        'payment_terms': '50% advance, 40% before installation, 10% on handover.', 'notes': 'Prices valid for 30 days.'}
r = admin.post('/admin/import/set-up', data=form)
with app.app_context():
    lines = {b.name: b for b in BoqItem.query.all()}
    p = next((p for p in Project.query.all() if p.customer_name == '2 BHK interiors (your old quotation)'), None)
    from app import quote_templates, quote_gst
    tpl = next((quote_templates.get(t['id']) for t in quote_templates.all_templates() if t['name'] == '2 BHK interiors'), None)
    pay = AppSetting.get('payment_terms')
    expect = 71.25 * 1450 + 20 * 1250 + 10 * 1300 + 4 * 4500 + 17331
ok('set up: their items with their rates (corrected rate kept; the unticked line left out)',
   lines.get('Wardrobe') and lines['Wardrobe'].rate == 1450 and lines.get('Loft') and lines['Loft'].rate == 1250
   and 'Side table' not in lines and lines.get('Tandem drawer') and lines['Tandem drawer'].unit == 'nos')
ok('…the same name at another rate keeps its section ("Wardrobe (Kitchen)"); charges as lump-sum lines',
   lines.get('Wardrobe (Kitchen)') and lines['Wardrobe (Kitchen)'].rate == 1300
   and lines.get('Design fee') and lines['Design fee'].unit == 'lump sum')
ok('…a starting quotation named after the job, with its sections', tpl is not None
   and [rm['name'] for rm in tpl['rooms']] == ['Master Bedroom', 'Kitchen', 'Other charges'])
ok(f'…their quotation rebuilt, no customer details, with the discount ({p.grand_total if p else None} vs {expect})',
   p is not None and abs(p.grand_total - expect) < 0.01 and p.discount_value == 5000 and not p.mobile
   and not p.address and r.status_code == 302 and r.headers['Location'].endswith(f'/projects/{p.id}'))
ok('…payment terms saved (they had none)', pay and pay.startswith('50% advance'))

# The limit
with app.app_context():
    AppSetting.set(AI.USAGE_KEY, '{"trial": 5, "' + __import__('datetime').datetime.utcnow().strftime('%Y-%m') + '": 20}')
    db.session.commit()
n = len(calls)
r = upload(QUOTE, 'again.pdf')
ok('limit reached: refused before anything is read', 'used all your quotation imports' in r.text and len(calls) == n)

# The demo never offers it
os.environ['DEMO_MODE'] = '1'
demo = create_app('development')
ok('never in the public demo', demo.test_client().get('/admin/import').status_code in (302, 404))
os.environ.pop('DEMO_MODE')

# Excel: the sheet's cells go to the AI
from openpyxl import Workbook
wb = Workbook(); ws = wb.active; ws.title = 'BOQ'
ws.append(['Sr', 'Item', 'Unit', 'Qty', 'Rate', 'Amount'])
for n_ in range(1, 15):
    ws.append([n_, f'Kitchen item {n_} with a long enough name', 'Sq.ft', 10, 1500.5, 15005])
buf = io.BytesIO(); wb.save(buf)
with app.app_context():
    kind, body = AI.file_text('quote.xlsx', buf.getvalue())
ok('Excel (.xlsx): read here, row by row, cells kept apart', kind == 'excel' and 'Sheet: BOQ' in body
   and 'Kitchen item 3 with a long enough name\tSq.ft\t10\t1500.5\t15005' in body)
ok('section headings tidied ("A MASTER BEDROOM" → "Master Bedroom"); whole numbers without ".0"',
   AI._section('A MASTER BEDROOM') == 'Master Bedroom' and AI._section('B. Kitchen') == 'Kitchen'
   and AI._section('Living & Dining') == 'Living & Dining' and AI._num('72.0') == 72 and AI._num('12.5') == 12.5)
ok('names lose their serial numbers, nothing else', AI._name('1.1 TV Unit') == 'TV Unit' and AI._name('a) Loft') == 'Loft'
   and AI._name('(iv) Shoe rack') == 'Shoe rack' and AI._name('2 BHK wardrobe') == '2 BHK wardrobe'
   and AI._name('12 Watt COB light') == '12 Watt COB light')
