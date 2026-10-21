"""Duplicate a quotation and quotation templates: start a new quotation from an earlier one, not from blank."""
import html, json, re
from app import create_app, db
from app.models import AppSetting, Item, Project, Room

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})


def rooms_of(html):
    m = re.search(r'id="existing-rooms-data"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else []


def shape(rooms):
    return [(r['name'], [(i['name'], i.get('type'), i.get('quantity'), i.get('unit_price'), i.get('wood_type'))
                         for i in r['items']]) for r in rooms]


with app.app_context():
    src = Project.query.filter(Project.status != 'draft', Project.discount_type == 'fixed').first()
    src_id, src_name, src_disc = src.id, src.customer_name, src.discount_value
    n_projects = Project.query.count()
src_rooms = rooms_of(c.get(f'/projects/{src_id}/edit').text)

v = c.get(f'/projects/{src_id}').text
ok('quotation page: Duplicate and (admin) Save as template', f'/projects/new?from={src_id}' in v and 'Save as template' in v)
t = c.get(f'/projects/new?from={src_id}').text
ok('Duplicate: a new quotation with every room and line, the customer left empty', shape(rooms_of(t)) == shape(src_rooms)
   and src_rooms and f'Copied from quotation #{src_id}' in t and 'value="' + src_name + '"' not in t)
ok('…and its discount', f'id="discount_value_field"\n         value="{src_disc}"' in t or f'value="{src_disc}"' in t)
with app.app_context():
    ok('nothing is saved until the new quotation is', Project.query.count() == n_projects)

r = c.post(f'/projects/{src_id}/template', data={'name': '  2 BHK   turnkey '}, follow_redirects=True)
ok('Save as template', 'Saved as the template "2 BHK turnkey"' in html.unescape(r.text))
with app.app_context():
    tpl = json.loads(AppSetting.get('quote_templates'))
    ok('a template is kept in settings, not as a quotation', len(tpl) == 1 and tpl[0]['name'] == '2 BHK turnkey'
       and Project.query.count() == n_projects)
    tid = tpl[0]['id']
t = c.get('/projects/new').text
ok('New Quotation offers "Start from" with the template', 'id="startFrom"' in t and '2 BHK turnkey (' in t)
t = c.get(f'/projects/new?template={tid}').text
ok('starting from the template copies its rooms and lines', shape(rooms_of(t)) == shape(src_rooms)
   and 'Copied from the "2 BHK turnkey" template' in html.unescape(t))

# Save a new quotation from it
c.post('/projects/new', data={'customer_name': 'From template', 'mobile': '9000000801',
                              'rooms_data': json.dumps(rooms_of(t)), 'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    new = Project.query.order_by(Project.id.desc()).first()
    ok('the new quotation has the same lines and total', new.customer_name == 'From template'
       and abs(new.grand_total - Project.query.get(src_id).grand_total) < 0.01)

# Editing the original later doesn't change the template
c.post(f'/projects/{src_id}/edit', data={'customer_name': src_name, 'mobile': '9000000001', 'discount_type': 'none',
                                         'discount_value': '0', 'rooms_data': json.dumps(src_rooms[:1])})
ok('the template keeps what it was saved with', shape(rooms_of(c.get(f'/projects/new?template={tid}').text)) == shape(src_rooms))

m = c.get('/templates').text
ok('Manage templates lists it', '2 BHK turnkey' in m and 'New quotation from it' in m)
c.post('/templates', data={'id': tid, 'action': 'rename', 'name': '2 BHK standard'})
ok('rename', '2 BHK standard' in c.get('/projects/new').text)
c.post(f'/projects/{src_id}/template', data={'name': '3 BHK'})
r = c.post('/templates', data={'id': tid, 'action': 'rename', 'name': '3 bhk'}, follow_redirects=True)
ok('names stay unique', 'Choose a name' in r.text)
c.post('/templates', data={'id': tid, 'action': 'delete'})
t = c.get('/projects/new').text
ok('delete', '2 BHK standard' not in t and '3 BHK (' in t)

staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
ok('staff can start from a template but not save or manage them', '3 BHK (' in staff.get('/projects/new').text
   and staff.post(f'/projects/{src_id}/template', data={'name': 'x'}).status_code == 403
   and staff.get('/templates').status_code == 403)
r = staff.get('/projects/new?from=999999').text
ok('Duplicate of an unknown quotation: just a blank one', 'Copied from' not in r)
