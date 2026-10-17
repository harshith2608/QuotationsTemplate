"""Units of measurement (Settings → Units): sizes in ft & in / mm / cm / in, areas & rates in sqft or sq m.
Stored values never change; only input and display do, so totals are identical in every unit."""
import io, json, re
from pypdf import PdfReader
from urllib.parse import unquote
from app import create_app, db, units
from app.models import AppSetting, ItemRate, Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pdftext = lambda u: '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages)
SQM = 0.09290304

with app.test_request_context():
    ok('formatting: 7.5 ft in each unit', units.length(7.5, 'ftin') == '7 ft 6 in' and units.length(7.5, 'mm') == '2,286 mm'
       and units.length(7.5, 'cm') == '228.6 cm' and units.length(7.5, 'in') == '90 in')
    ok('default units: ft & in, sqft', units.size_unit() == 'ftin' and units.area_unit() == 'sqft')

with app.app_context():
    LAM = ItemRate.query.filter_by(wood_type='Laminates', work_type='Box Work').first().rate_per_sqft
rooms = [{'name': 'Bedroom', 'items': [
    {'name': 'Wardrobe', 'length': 10, 'width': 7.5, 'wood_type': 'Laminates', 'work_type': 'Box Work'},   # 75 sqft
    {'name': 'Hinges', 'type': 'fixed', 'quantity': 4, 'unit_price': 350}]}]
c.post('/projects/new', data={'customer_name': 'Units Test', 'mobile': '9000000777', 'rooms_data': json.dumps(rooms),
                              'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    p = Project.query.order_by(Project.id.desc()).first(); pid, total = p.id, p.final_total
ok('quotation total = 75 sqft × rate + fittings', round(total, 2) == round(75 * LAM + 1400, 2))
t = c.get(f'/projects/{pid}').text
ok('ft & in / sqft (default): sizes and areas as before', '10 ft' in t and '7 ft 6 in' in t and '75.00 sqft' in t)

r = c.post('/admin/settings', data={'section': 'units', 'size_unit': 'mm', 'area_unit': 'sqm'}, follow_redirects=True)
ok('Settings → Units saves mm and sq m', 'Settings saved' in r.text and 'id="su_mm" value="mm" checked' in r.text)
t = c.get(f'/projects/{pid}').text
ok('quotation page in mm and sq m, same total', '3,048 mm' in t and '2,286 mm' in t and f'{75 * SQM:,.2f} sq m' in t
   and f'{total:,.2f}' in t and '/sq m' in t)
full = pdftext(f'/projects/{pid}/pdf')
ok('Full Quotation PDF in mm, sq m and ₹/sq m, same total', '3,048 mm' in full and 'sq m' in full and 'sqft' not in full
   and f'{LAM / SQM:,.0f}' in full and f'{total:,.2f}' in full)
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('Initial Quotation PDF: same total, area in sq m', f'{total:,.2f}' in cust and 'sq m' in cust)
wa = unquote(c.get(f'/projects/{pid}/whatsapp').headers.get('Location', ''))
ok('WhatsApp in mm and sq m', '3,048 mm × 2,286 mm' in wa and 'sq m' in wa and f'{total:,.2f}' in wa)

t = c.get('/admin/rates').text
ok('Rates page shows rates per sq m', f'value="{round(LAM / SQM, 2)}"' in t and '/sq m' in t)
form = {'item_rates_submit': 'save'}
for m in re.finditer(r'name="(rate_\d+_\d+|name_\d+)"[^>]*value="([^"]*)"', t):
    form[m.group(1)] = m.group(2)
for m in re.finditer(r'name="(name_\d+)"\s+class="[^"]*"\s+value="([^"]*)"', t):
    form[m.group(1)] = m.group(2)
lam_field = re.search(r'name="(rate_\d+_0)"[^>]*value="[^"]*" aria-label="Laminates Box Work rate"', t).group(1)
form[lam_field] = '10000'
c.post('/admin/rates', data=form)
with app.app_context():
    stored = ItemRate.query.filter_by(wood_type='Laminates', work_type='Box Work').first().rate_per_sqft
ok('a rate typed per sq m is stored per sqft, exactly', abs(stored - 10000 * SQM) < 1e-9)
ok('…and shows back as ₹10,000/sq m (no drift)', 'value="10000.0"' in c.get('/admin/rates').text)
f = c.get('/projects/new').text
ok('form: sizes in mm, areas in sq m', '"size": "mm"' in f and '"areaLabel": "sq m"' in f and 'Measured (sq m)' in f)

# Back to ft & in / sqft: everything as before, nothing changed
c.post('/admin/settings', data={'section': 'units', 'size_unit': 'ftin', 'area_unit': 'sqft'})
with app.app_context():
    p = db.session.get(Project, pid)
    ok('switching units never changed the stored sizes or total', round(p.final_total, 2) == round(total, 2))
t = c.get(f'/projects/{pid}').text
ok('back in ft & in and sqft', '7 ft 6 in' in t and '75.00 sqft' in t)
c.post('/admin/settings', data={'section': 'units', 'size_unit': 'cm', 'area_unit': 'sqft'})
ok('cm', '304.8 cm' in c.get(f'/projects/{pid}').text)
c.post('/admin/settings', data={'section': 'units', 'size_unit': 'in', 'area_unit': 'sqft'})
ok('inches', '120 in' in c.get(f'/projects/{pid}').text and '90 in' in c.get(f'/projects/{pid}').text)
r = c.post('/admin/settings', data={'section': 'units', 'size_unit': 'yards', 'area_unit': 'sqft'}, follow_redirects=True)
ok('an unknown unit is refused', 'Choose a unit' in r.text)
