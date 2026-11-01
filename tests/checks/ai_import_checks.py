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
    subtotal=173312.5, discount=-5000, gst_percent=18, grand_total=None,
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
ok('on: the upload page (PDF or Excel), the menu item and the setup guide card', 'Read my file' in t
   and 'the Excel file you make your quotations' in t and 'or your Excel rates' in admin.get('/admin/setup').text
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
ok('…a discount printed as "- 5,000" comes in as 5,000 (the form takes no minus)',
   'id="discount" name="discount" type="number" step="0.01" min="0" value="5000"' in t)
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

# The Excel format they quote from (a rate list): rates only, no totals, nothing rebuilt
RATES = AI.Quote(
    is_rate_list=True, job_title='Interiors rate list',
    sections=[AI.Section(name='Kitchen', lines=[
                  AI.Line(name='Base unit', description='BWP ply, acrylic', size='', unit='rft', quantity=None, rate=2600, amount=None),
                  AI.Line(name='Loft shutter', description='', size='', unit='sqft', quantity=None, rate=1100, amount=None)]),
              AI.Section(name='Bedroom', lines=[
                  AI.Line(name='Sliding wardrobe', description='', size='', unit='sqft', quantity=None, rate=1650, amount=None)])],
    charges=[], subtotal=None, discount=None, gst_percent=None, grand_total=None, payment_terms='', notes_and_terms='')
READING, saved_reading = RATES, READING
t = upload(QUOTE, 'rates.xlsx').text
ok('a rate list: "Check your rates", no "No amount" warnings and no lines total', 'Check your rates' in t
   and 'No amount in your file' not in t and 'id="linesTotal"' not in t and 'name="rate_list" value="1"' in t)
with app.app_context():
    plain = AI.tidy(AI.Quote(job_title='x', sections=RATES.sections, charges=[], subtotal=None, discount=None,
                             gst_percent=None, grand_total=None, payment_terms='', notes_and_terms=''))
ok('…also taken as a rate list when no line has a quantity or an amount', plain['rate_list'])
with app.app_context():
    n_projects = Project.query.count()
r = admin.post('/admin/import/set-up', data={
    'rate_list': '1', 'job_title': 'Interiors rate list', 'discount': '', 'gst': '', 'sections': '2', 'charges': '0',
    's0_name': 'Kitchen', 's0_lines': '2',
    's0_0_keep': '1', 's0_0_name': 'Base unit', 's0_0_unit': 'rft', 's0_0_quantity': '', 's0_0_rate': '2600',
    's0_1_keep': '1', 's0_1_name': 'Loft shutter', 's0_1_unit': 'sqft', 's0_1_quantity': '', 's0_1_rate': '1100',
    's1_name': 'Bedroom', 's1_lines': '1',
    's1_0_keep': '1', 's1_0_name': 'Sliding wardrobe', 's1_0_unit': 'sqft', 's1_0_quantity': '', 's1_0_rate': '1650',
    'payment_terms': '', 'notes': ''}, follow_redirects=True)
with app.app_context():
    lines = {b.name: b for b in BoqItem.query.all()}
    tpl = next((quote_templates.get(t_['id']) for t_ in quote_templates.all_templates() if t_['name'] == 'Interiors rate list'), None)
    made = Project.query.count() - n_projects
ok('…set up: every item with its rate and a starting quotation with all of them; no quotation rebuilt',
   lines.get('Base unit') and lines['Base unit'].rate == 2600 and lines.get('Sliding wardrobe') and tpl is not None
   and [rm['name'] for rm in tpl['rooms']] == ['Kitchen', 'Bedroom'] and made == 0 and 'set up from your rates' in r.text)
READING = saved_reading

# By material: the AI thinks they price by material; the review offers it; set up into Rates and fittings
MATS = AI.Quote(
    pricing='material', pricing_reason='Every laminate item is ₹1,450 per sqft, whatever the item.',
    job_title='3 BHK interiors',
    sections=[AI.Section(name='Kitchen', lines=[
                  AI.Line(name='Base unit', description='', size='', unit='sqft', quantity=30, rate=1850, amount=55500,
                          material='Acrylic', work_type='Box work'),
                  AI.Line(name='Shutters', description='', size='', unit='sqft', quantity=20, rate=1500, amount=30000,
                          material='Acrylic', work_type='Frame work (shutters)'),
                  AI.Line(name='Tall unit', description='', size='', unit='sqft', quantity=12, rate=1850, amount=22200,
                          material='acrylic'),
                  AI.Line(name='Tandem drawer', description='Hettich', size='', unit='Nos', quantity=4, rate=4500, amount=18000)]),
              AI.Section(name='Bedroom', lines=[
                  AI.Line(name='Wardrobe', description='', size='', unit='sqft', quantity=50, rate=1450, amount=72500,
                          material='Laminate', work_type='Box Work'),
                  AI.Line(name='Loft', description='', size='', unit='sqft', quantity=16, rate=1450, amount=23200,
                          material='Laminate'),
                  AI.Line(name='Dresser', description='', size='', unit='sqft', quantity=10, rate=1650, amount=16500,
                          material='Laminate'),
                  AI.Line(name='False ceiling', description='', size='', unit='sqft', quantity=120, rate=120, amount=14400)])],
    charges=[AI.Charge(name='Design fee', amount=10000)],
    subtotal=252300, discount=None, gst_percent=None, grand_total=None, payment_terms='', notes_and_terms='')
READING = MATS
t = upload(QUOTE, 'mats.xlsx').text
ok('by material: the review says so, with their reason, and offers by material (chosen) or by item',
   'It looks like you price by material' in t and 'whatever the item' in t
   and 'id="pricingMaterial" value="material" checked' in t and 'id="pricingItem" value="item"' in t)
ok('…a preview of the materials and rates: Acrylic box and frame work, Laminate at its most common rate, the '
   'false ceiling as a material of its own', '<td>Acrylic</td><td class="text-muted">Box Work</td><td class="text-end">₹1,850</td>' in t
   and '<td>Acrylic</td><td class="text-muted">Frame Work</td><td class="text-end">₹1,500</td>' in t
   and '<td>Laminate</td><td class="text-muted">–</td><td class="text-end">₹1,450</td>' in t and '<td>False ceiling</td>' in t)
ok('…the line at another rate is pointed out; each line shows its material and work type to correct',
   'Laminate: ₹1,650 (Dresser)' in t and 'name="s0_0_material" value="Acrylic"' in t
   and '<option value="Frame Work" selected>' in t)
with app.app_context():
    m = AI.by_material(AI.tidy(MATS))
    rooms = {r['name']: r['items'] for r in m['rooms']}
ok('…the template: area items in their material (unsaid work type is box work; one-rate materials none), the rest '
   'as fittings, the charges too', rooms['Kitchen'][2] == {'name': 'Tall unit', 'material': 'Acrylic', 'work': 'Box Work'}
   and rooms['Bedroom'][0] == {'name': 'Wardrobe', 'material': 'Laminate', 'work': ''}
   and rooms['Kitchen'][3] == {'name': 'Tandem drawer', 'type': 'fitting'} and rooms['Other charges'][0]['type'] == 'fitting')

form = {'pricing': 'material', 'job_title': '3 BHK interiors', 'discount': '', 'gst': '', 'sections': '2', 'charges': '1',
        'c0_keep': '1', 'c0_name': 'Design fee', 'c0_amount': '10000', 'payment_terms': '', 'notes': ''}
for i, sec in enumerate(MATS.sections):
    form[f's{i}_name'], form[f's{i}_lines'] = sec.name, str(len(sec.lines))
    for j, l in enumerate(sec.lines):
        p = f's{i}_{j}_'
        form.update({p + 'keep': '1', p + 'name': l.name, p + 'unit': l.unit, p + 'quantity': str(l.quantity),
                     p + 'rate': str(l.rate), p + 'material': l.material, p + 'work': l.work_type})
form['s1_2_material'] = 'Laminate premium'          # the admin keeps the dresser's own rate
with app.app_context():
    n_projects = Project.query.count()
r = admin.post('/admin/import/set-up', data=form)
with app.app_context():
    from app import boq
    from app.models import ItemRate, Material, PriceListItem
    mats = {x.name: x for x in Material.query.all()}
    rates = {(x.wood_type, x.work_type): x.rate_per_sqft for x in ItemRate.query.all()}
    fits = {x.name.lower(): x for x in PriceListItem.query.all()}
    tpl = next((quote_templates.get(t_['id']) for t_ in quote_templates.all_templates() if t_['name'] == '3 BHK interiors'), None)
    items = {it['name']: it for rm in (tpl or {}).get('rooms', []) for it in rm['items']}
    by_item, made = boq.enabled(), Project.query.count() - n_projects
ok('…set up: pricing by material, Acrylic per work type, Laminate and Laminate premium at one rate each, false ceiling',
   not by_item and mats['Acrylic'].uses_work_types and rates[('Acrylic', 'Box Work')] == 1850
   and rates[('Acrylic', 'Frame Work')] == 1500 and not mats['Laminate'].uses_work_types and rates[('Laminate', '')] == 1450
   and rates[('Laminate premium', '')] == 1650 and rates[('False ceiling', '')] == 120)
ok('…fittings with their prices (the design fee as a lump sum); starter materials and fittings they never changed '
   'hidden or removed', fits['tandem drawer'].price == 4500 and fits['design fee'].unit == 'lump sum'
   and not mats['Veneer'].active and not mats['Glass'].active and 'pull-out basket' not in fits)
ok('…a starting quotation of measured items and fittings; no quotation rebuilt; on to Rates',
   items.get('Wardrobe', {}).get('wood_type') == 'Laminate' and items.get('Shutters', {}).get('work_type') == 'Frame Work'
   and items.get('Dresser', {}).get('wood_type') == 'Laminate premium' and items.get('Tandem drawer', {}).get('type') == 'fixed'
   and made == 0 and r.status_code == 302 and r.headers['Location'].endswith('/admin/rates'))
READING = saved_reading
t = upload(QUOTE, 'again-item.pdf').text
ok('a file the AI thinks is priced by item: no by-material card, set up by item as before',
   'It looks like you price by material' not in t and 'name="pricing" value="item"' in t)

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
