"""BOMs (app/boms.py): room-wise measurements saved on their own, and quotations made from them."""
import io, json, re
from pypdf import PdfReader
from sqlalchemy import text
from app import create_app, db, boms, quote_templates
from app.models import AppSetting, Bom, Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
pdftext = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))

AREAS = [{'name': 'Foyer Area', 'length': 5, 'width': 4.5}, {'name': 'Vestibule', 'length': 20.5, 'width': 11},
         {'name': 'Kitchen', 'length': 16.5, 'width': 11}, {'name': '', 'length': 0, 'width': 0},
         {'name': 'Passage Area', 'length': 9, 'width': 4}]

ok('off by default: no BOMs page or menu', c.get('/boms').status_code == 404 and 'bi-rulers' not in c.get('/projects').text)
c.post('/admin/settings', data={'section': 'pricing', 'pricing_mode': 'material', 'boms_shown': '1', 'boms_on': '1', 'boms_staff': '1'})
with app.app_context():
    ok('Settings → Pricing turns BOMs on, staff allowed', boms.enabled() and boms.staff_allowed() and boms.ready())
ok('the BOMs menu item and page', '>BOMs<' in c.get('/projects').text and c.get('/boms').status_code == 200)

r = c.post('/boms/new', data={'customer_name': 'Khushbu Shah', 'mobile': '9000000701', 'email': '', 'address': 'Flat 4B',
                              'areas': json.dumps(AREAS)})
with app.app_context():
    bom = Bom.query.order_by(Bom.id.desc()).first()
    bid = bom.id
    rows = boms.areas_of(bom)
    raw = db.session.execute(text('SELECT customer_name FROM boms WHERE id = :i'), {'i': bid}).scalar()
ok('New BOM saves the customer and areas (empty row dropped)', r.status_code == 302 and [a['name'] for a in rows]
   == ['Foyer Area', 'Vestibule', 'Kitchen', 'Passage Area'])
ok('total 22.5 + 225.5 + 181.5 + 36 = 465.5', boms.total(rows) == 465.5)
ok('the customer is encrypted in the database', 'Khushbu' not in (raw or ''))
ok('a BOM needs a name and mobile', 'Mobile number is required' in c.post('/boms/new', data={'customer_name': 'X', 'mobile': '',
                                                                                          'areas': '[]'}, follow_redirects=True).text)
lst = c.get('/boms').text
ok('the BOMs page lists it with its total', 'Khushbu Shah' in lst and '465.50' in lst)
ok('search finds it, and not others', 'Khushbu' in c.get('/boms?q=khush').text and 'Khushbu' not in c.get('/boms?q=nobody').text)
v = c.get(f'/boms/{bid}').text
ok('the BOM page: areas, total, Create quotation', 'Vestibule' in v and '465.50' in v and 'Create quotation' in v)

form = c.get(f'/projects/new?bom={bid}&areas=0,2&blank=1').text
existing = json.loads(re.search(r'id="existing-rooms-data" type="application/json">(.*?)</script>', form, re.S).group(1))
ok('Create quotation: the customer and the ticked areas as rooms', 'Khushbu Shah' in form and '9000000701' in form
   and [r['name'] for r in existing] == ['Foyer Area', 'Kitchen'])
ok('the form links the BOM and shows its measurements', f'name="bom_id" value="{bid}"' in form and f'Measurements from BOM #{bid}' in form)

rooms = [{'name': 'Kitchen', 'items': [{'type': 'fixed', 'name': 'Chimney', 'quantity': 1, 'unit_price': 15000}]}]
c.post('/projects/new', data={'customer_name': 'Khushbu Shah', 'mobile': '9000000701', 'rooms_data': json.dumps(rooms),
                              'discount_type': 'none', 'discount_value': '0', 'bom_id': str(bid)})
with app.app_context():
    pid = Project.query.order_by(Project.id.desc()).first().id
    ok('saved: linked to the BOM', boms.linked_bom(pid).id == bid)
ok('the BOM lists the quotation', f'/projects/{pid}' in c.get(f'/boms/{bid}').text)
ok('the edit form shows the BOM for reference', f'Measurements from BOM #{bid}' in c.get(f'/projects/{pid}/edit').text)
t = pdftext(f'/projects/{pid}/pdf/customer')
ok('the PDF\'s first page shows the total as Built-up area, not the rooms', 'Built-up area 465.50 sqft' in t and 'Vestibule' not in t)
t = pdftext(f'/projects/{pid}/pdf')
ok('the full PDF too', 'Built-up area 465.50 sqft' in t)

dup = c.get(f'/projects/new?from={pid}').text
ok('a copy of it (premium) stays linked to the BOM', f'name="bom_id" value="{bid}"' in dup)
with app.app_context():
    quote_templates._store(quote_templates._load() + [{'id': 'bomtpl', 'name': 'Premium', 'rooms': [
        {'name': 'kitchen', 'items': [{'type': 'fixed', 'name': 'Hob', 'quantity': 1, 'unit_price': 9000}]}]}])
    db.session.commit()
form = c.get(f'/projects/new?bom={bid}&areas=0,2&template=bomtpl').text
existing = json.loads(re.search(r'id="existing-rooms-data" type="application/json">(.*?)</script>', form, re.S).group(1))
ok('with a starting quotation: its rooms, then the BOM\'s not already there', [r['name'] for r in existing] == ['kitchen', 'Foyer Area']
   and 'Khushbu Shah' in form)
c.post('/projects/new', data={'customer_name': 'Khushbu Shah', 'mobile': '9000000701', 'rooms_data': json.dumps(rooms),
                              'discount_type': 'none', 'discount_value': '0', 'bom_id': str(bid)})
lst = c.get('/boms').text
ok('two quotations from one BOM', re.search(r'text-end">2</td>', lst) is not None)

ok('staff use BOMs by default', staff.get('/boms').status_code == 200 and '>BOMs<' in staff.get('/projects').text)
ok('staff can\'t delete a BOM', staff.post(f'/boms/{bid}/delete').status_code == 403)
c.post('/admin/settings', data={'section': 'pricing', 'pricing_mode': 'material', 'boms_shown': '1', 'boms_on': '1'})
ok('Staff can use BOMs off: admins only', staff.get('/boms').status_code == 403 and '>BOMs<' not in staff.get('/projects').text
   and c.get('/boms').status_code == 200)

with app.app_context():
    AppSetting.set(f'{boms.LEGACY_PREFIX}{pid}', json.dumps([{'name': 'Old Hall', 'length': 10, 'width': 10}]))
    AppSetting.set(f'{boms.LINK_PREFIX}{pid}', '999999')
    db.session.commit()
ok('rows from the earlier Room areas table still show, read-only', 'Old Hall' in c.get(f'/projects/{pid}/edit').text)

c.post(f'/boms/{bid}/delete')
with app.app_context():
    ok('deleting the BOM keeps its quotations, drops the links', db.session.get(Project, pid) is not None and db.session.get(Bom, bid) is None
       and not boms._link_rows(bid))
c.post(f'/projects/{pid}/delete')
with app.app_context():
    ok('deleting a quotation removes its link and old rows', db.session.get(AppSetting, f'{boms.LINK_PREFIX}{pid}') is None
       and db.session.get(AppSetting, f'{boms.LEGACY_PREFIX}{pid}') is None)
ok('Help has the BOM articles', 'New BOM' in c.get('/help').text)
