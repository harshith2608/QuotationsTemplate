import io, json, os, re
from urllib.parse import unquote
from pypdf import PdfReader
from app import create_app, db
from app.models import Project, Item, PriceListItem
for k in ['DEMO_MODE']: os.environ.pop(k, None)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
pdftext = lambda u: '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages)

with app.app_context():
    p = db.session.get(Project, 1)
    ok(f'demo: Priya total includes fittings ({p.grand_total})', p.grand_total == 181800.0 and p.fixed_items_total() == 36000.0)
    ok('price list seeded', PriceListItem.query.count() == 7)

v = c.get('/projects/1').text
ok('view: Fittings & Accessories summary line', 'Fittings &amp; Accessories' in v and '36,000.00' in v)
ok('view: itemised in room table', 'Magic Corner' in v and '1 &times; &#8377;18,000' in v and '4 &times; &#8377;4,500' in v)
full = pdftext('/projects/1/pdf')
ok('Full PDF: each fitting in its room', 'Magic Corner' in full and 'Tandem Drawer' in full and 'Fitting: 4 × Rs. 4,500' in full)
ok('Full PDF: fittings line in cost summary + subtotal', 'Fittings & Accessories' in full and '181,800.00' in full)
cust = pdftext('/projects/1/pdf/customer')
ok('Initial PDF: fittings in a Hardware row per room, with counts but no unit prices', 'Hardware' in cust
   and 'Magic Corner' in cust and 'Tandem Drawer' in cust and 'Rs. 4,500' not in cust and '181,800.00' in cust)
wa = unquote(c.get('/projects/1/whatsapp').headers['Location'])
ok('WhatsApp: fittings itemised + summary', 'Magic Corner: 1 × Rs.18,000' in wa and 'Fittings & Accessories: Rs.36,000' in wa
   and 'Acrylic – Box Work' in wa)

# Save through the edit form, incl. invalid fixed lines that must be ignored
rooms = [{'name': 'Kitchen', 'items': [
    {'name': 'Base Cabinet', 'length': 10, 'width': 2.75, 'wood_type': 'Acrylic', 'work_type': 'Box Work'},
    {'type': 'fixed', 'name': 'Magic Corner', 'quantity': 1, 'unit_price': 19500},
    {'type': 'fixed', 'name': 'Profile LED Light', 'quantity': 12.5, 'unit_price': 350},
    {'type': 'fixed', 'name': 'Zero qty', 'quantity': 0, 'unit_price': 100},
    {'type': 'fixed', 'name': 'Negative', 'quantity': 1, 'unit_price': -5},
]}]
r = c.post('/projects/3/edit', data={'customer_name': 'Meera Test', 'mobile': '9000000003', 'rooms_data': json.dumps(rooms),
                                     'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    p3 = db.session.get(Project, 3)
    items = [(i.name, i.item_type) for r_ in p3.rooms_with_items() for i in r_.item_list]
    ok(f'edit save: fixed items stored, invalid ones dropped {items}', ('Magic Corner', 'fixed') in items and ('Profile LED Light', 'fixed') in items
       and not any(n in ('Zero qty', 'Negative') for n, _ in items))
    ok(f'edit save: grand total = 27.5×1200 + 19500 + 12.5×350 ({p3.grand_total})', p3.grand_total == 33000 + 19500 + 4375)
e = c.get('/projects/3/edit').text
data = json.loads(re.search(r'<script id="existing-rooms-data" type="application/json">(.*?)</script>', e, re.S).group(1))
ok('edit page reloads fixed items with qty/price', any(i.get('type') == 'fixed' and i['unit_price'] == 19500 for i in data[0]['items']))
ok('price list delivered to form', '"Magic Corner"' in e and 'id="price-list-data"' in e)

# Draft API accepts fixed items
r = c.post('/api/draft', json={'customer_name': 'Draft Fittings', 'mobile': '1', 'rooms_data': [{'name': 'Kitchen', 'items': [
    {'type': 'fixed', 'name': 'Tandem Drawer', 'quantity': 2, 'unit_price': 4500}]}]})
with app.app_context():
    d = db.session.get(Project, r.get_json()['draft_id'])
    ok('draft auto-save keeps fixed items', d.grand_total == 9000)

# Stored XSS closed: item names can't break out of the embedded JSON
rooms_x = [{'name': 'Hall', 'items': [{'type': 'fixed', 'name': '</script><script>alert(1)</script>', 'quantity': 1, 'unit_price': 1}]}]
c.post('/projects/4/edit', data={'customer_name': 'Arjun Placeholder', 'mobile': '9000000004', 'rooms_data': json.dumps(rooms_x),
                                 'discount_type': 'none', 'discount_value': '0'})
e = c.get('/projects/4/edit').text
ok('stored XSS neutralised in edit page', '</script><script>alert(1)' not in e and '\\u003c/script>' in e)

# Price list management
c.post('/admin/rates', data={'price_list_submit': '1', 'pl_id': ['', ''], 'pl_name': ['Glass Shutter', ''], 'pl_price': ['2800', ''], 'pl_unit': ['sqft', '']})
with app.app_context():
    g = PriceListItem.query.filter_by(name='Glass Shutter').first(); gid = str(g.id) if g else ''
    mc = PriceListItem.query.filter_by(name='Magic Corner').first(); mcid = str(mc.id)
    ok('price list: add', g is not None and g.price == 2800 and g.unit == 'sqft')
c.post('/admin/rates', data={'price_list_submit': '1', 'pl_id': [mcid, gid], 'pl_name': ['Magic Corner', 'Glass Shutter'],
                              'pl_price': ['19999', '2800'], 'pl_unit': ['piece', 'sqft'], 'pl_delete': [gid]})
with app.app_context():
    ok('price list: edit + delete', db.session.get(PriceListItem, int(mcid)).price == 19999 and PriceListItem.query.filter_by(name='Glass Shutter').first() is None)
r = c.post('/admin/rates', data={'price_list_submit': '1', 'pl_id': ['', ''], 'pl_name': ['Hinge', 'hinge'], 'pl_price': ['1', '2'], 'pl_unit': ['', '']}, follow_redirects=True)
ok('price list: duplicate names rejected', 'appears twice' in r.text)
ok('rates page shows price list', 'Fittings &amp; Accessories Price List' in c.get('/admin/rates').text)

# Dashboard material chart ignores fittings (no empty-name slice)
d = c.get('/admin/dashboard').text
labels = json.loads(re.search(r'labels: (\[.*?\]),\n\s*datasets: \[\{\n\s*data: ', d, re.S).group(1)) if re.search(r'labels: (\[.*?\]),\n\s*datasets: \[\{\n\s*data: ', d, re.S) else None
ok(f'dashboard material chart has no blank label {labels}', labels is not None and '' not in labels)
