"""Room areas (Settings → Pricing, app/room_areas.py): the home's measurement sheet on the quotation form, saved with
the quotation and never printed."""
import io, json, re
from pypdf import PdfReader
from app import create_app, db, room_areas
from app.models import AppSetting, Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pdftext = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))

ROOMS = [{'name': 'Kitchen', 'items': [{'type': 'fixed', 'name': 'Chimney', 'quantity': 1, 'unit_price': 15000}]}]
AREAS = [{'name': 'Foyer Area', 'length': 5, 'width': 4.5}, {'name': 'Vestibule', 'length': 20.5, 'width': 11},
         {'name': '', 'length': 0, 'width': 0}, {'name': 'Passage Area', 'length': 0, 'width': 0},
         {'name': 'Bad', 'length': -3, 'width': 'x'}]


def new_quote(name, extra=None):
    data = {'customer_name': name, 'mobile': '9000000555', 'rooms_data': json.dumps(ROOMS),
            'discount_type': 'none', 'discount_value': '0', **(extra or {})}
    c.post('/projects/new', data=data)
    with app.app_context():
        return Project.query.order_by(Project.id.desc()).first().id

ok('off by default: no Room areas on the form', 'room-areas-card' not in c.get('/projects/new').text)
pid = new_quote('Areas Off', {'room_areas': json.dumps(AREAS)})
with app.app_context():
    ok('off: rows sent are not saved', room_areas.get(pid) == [])

ok('the switch is on Settings → Pricing', 'name="room_areas_on"' in c.get('/admin/settings?tab=pricing').text)
c.post('/admin/settings', data={'section': 'pricing', 'pricing_mode': 'material', 'room_areas_shown': '1', 'room_areas_on': '1'})
with app.app_context():
    ok('Settings → Pricing turns it on', room_areas.enabled())
form = c.get('/projects/new').text
ok('on: the form has Room areas', 'room-areas-card' in form and 'name="room_areas"' in form)

pid = new_quote('Areas On', {'room_areas': json.dumps(AREAS)})
with app.app_context():
    rows = room_areas.get(pid)
ok('saved: named or sized rows only, bad sizes as 0', [r['name'] for r in rows] == ['Foyer Area', 'Vestibule', 'Passage Area', 'Bad']
   and rows[3]['length'] == 0 and rows[3]['width'] == 0)
ok('areas and total (22.5 + 225.5 = 248)', room_areas.area(rows[0]) == 22.5 and room_areas.total(rows) == 248)
edit = c.get(f'/projects/{pid}/edit').text
ok('the edit form gets them back', '"Vestibule"' in edit and 'room-areas-data' in edit)
t = pdftext(f'/projects/{pid}/pdf/customer')
ok('never on the PDF', 'Vestibule' not in t and 'Foyer Area' not in t)
ok('never on the quotation page shown to the customer', 'Vestibule' not in c.get(f'/projects/{pid}').text)

c.post(f'/projects/{pid}/edit', data={'customer_name': 'Areas On', 'mobile': '9000000555', 'rooms_data': json.dumps(ROOMS),
                                       'discount_type': 'none', 'discount_value': '0',
                                       'room_areas': json.dumps([{'name': 'Bedroom 1', 'length': 15, 'width': 12}])})
with app.app_context():
    ok('editing replaces them', [r['name'] for r in room_areas.get(pid)] == ['Bedroom 1'])
c.post(f'/projects/{pid}/edit', data={'customer_name': 'Areas On', 'mobile': '9000000555', 'rooms_data': json.dumps(ROOMS),
                                       'discount_type': 'none', 'discount_value': '0', 'room_areas': '[]'})
with app.app_context():
    ok('emptied: removed', room_areas.get(pid) == [] and db.session.get(AppSetting, f'room_areas:{pid}') is None)

r = c.post('/api/draft', json={'customer_name': 'Draft Areas', 'mobile': '9000000556', 'rooms_data': ROOMS,
                               'room_areas': [{'name': 'Balcony', 'length': 6, 'width': 4}]})
did = r.get_json()['draft_id']
with app.app_context():
    ok('the draft auto-save keeps them', [r['name'] for r in room_areas.get(did)] == ['Balcony'])

pid = new_quote('Areas Delete', {'room_areas': json.dumps(AREAS)})
c.post(f'/projects/{pid}/delete')
with app.app_context():
    ok('deleting the quotation removes them', db.session.get(AppSetting, f'room_areas:{pid}') is None)
ok('Help has the article', 'room areas' in c.get('/help').text.lower())
