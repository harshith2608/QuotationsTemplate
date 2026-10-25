"""Photos on quotation lines (app/item_images.py): off by default, turned on per business; upload (checked, resized,
JPEG), on a line of any kind, on the quotation page, in every PDF layout, on the customer's link, in revisions,
Duplicate and templates; a photo that isn't this business's is ignored."""
import io, json, re
from PIL import Image
from pypdf import PdfReader
from app import create_app, db, billing, boq, item_images, layout
from app.models import AppSetting, Item, ItemImage, Project, Room

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})


def png(w, h, alpha=False):
    out = io.BytesIO()
    Image.new('RGBA' if alpha else 'RGB', (w, h), (200, 120, 40, 0 if alpha else 255)).save(out, format='PNG')
    return out.getvalue()


def upload(data, name='photo.png'):
    return c.post('/item-images', data={'photo': (io.BytesIO(data), name)}, content_type='multipart/form-data')


def pdf_images(url):
    return sum(len(p.images) for p in PdfReader(io.BytesIO(c.get(url).data)).pages)


with app.app_context():
    ok('database ready for photos (item_images, items.image_id)', item_images.ready())
    ok('off by default', not item_images.enabled())
f = c.get('/projects/new?blank=1').text
ok('off: the form has no Photo button', 'itemImages:  false' in f)
ok('off: uploading is refused', upload(png(50, 50)).status_code == 403)

with app.app_context():
    item_images.set_enabled(True); db.session.commit()
ok('on: the form offers photos', 'itemImages:  true' in c.get('/projects/new?blank=1').text)
r = upload(png(2400, 1200, alpha=True))
pid_img = r.get_json().get('id') if r.status_code == 200 else None
with app.app_context():
    row = db.session.get(ItemImage, pid_img) if pid_img else None
    ok('a big transparent PNG is stored as a JPEG, at most 900 px, white behind', row is not None and row.mime == 'image/jpeg'
       and max(row.width, row.height) == 900 and Image.open(io.BytesIO(row.data)).format == 'JPEG'
       and Image.open(io.BytesIO(row.data)).getpixel((5, 5))[0] > 240)
g = c.get(f'/item-images/{pid_img}')
ok('…and shown to the business (cached, it never changes)', g.status_code == 200 and g.mimetype == 'image/jpeg'
   and 'immutable' in g.headers.get('Cache-Control', ''))
bad = upload(b'not an image', 'notes.txt')
ok('not a photo: refused with a reason', bad.status_code == 400 and 'photo' in bad.get_json()['error'])
second = upload(png(300, 300)).get_json()['id']

with app.app_context():
    from app.models import ItemRate
    combo = ItemRate.query.filter(ItemRate.work_type != '').first()
c.post('/projects/new', data={'customer_name': 'Photo Home', 'mobile': '9000000801', 'discount_type': 'none',
                              'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Living', 'items': [
    {'name': 'Sofa Wall', 'length': 10, 'width': 8, 'wood_type': combo.wood_type, 'work_type': combo.work_type,
     'image_id': pid_img},
    {'name': 'Coffee Table', 'type': 'fixed', 'quantity': 1, 'unit_price': 15000, 'image_id': second},
    {'name': 'Rug', 'type': 'fixed', 'quantity': 1, 'unit_price': 5000, 'image_id': 999999}]}])})
with app.app_context():
    p = Project.query.order_by(Project.id.desc()).first()
    pid = p.id
    its = {i.name: i for i in Item.query.join(Item.room).filter(Room.project_id == pid).all()}
    ok('saved: a measured item and a fixed-price item keep their photo; an unknown photo id is ignored',
       its['Sofa Wall'].image_id == pid_img and its['Coffee Table'].image_id == second and its['Rug'].image_id is None)
    snap = billing.quotation_snapshot(p)
    ok('…kept in the revision', sorted(i.get('image_id') or 0 for r in snap['rooms'] for i in r['items']) == sorted([0, pid_img, second]))
lib = c.get('/item-images/library').get_json()['photos']
byid = {x['id']: x for x in lib}
ok('"My photos": every photo of the business, newest first, with the items it\'s on', [x['id'] for x in lib][:2] == [second, pid_img]
   and byid[pid_img]['names'] == ['Sofa Wall'] and byid[second]['names'] == ['Coffee Table']
   and byid[second]['url'].endswith(f'/item-images/{second}'))
ok('the form offers New and My photos', 'imageLibrary' in c.get('/projects/new?blank=1').text
   and 'openPhotoLibrary' in c.get('/static/js/project_form.js').text and 'My photos' in c.get('/static/js/project_form.js').text)
c.post('/projects/new', data={'customer_name': 'Reuse Home', 'mobile': '9000000803', 'discount_type': 'none',
                              'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Hall', 'items': [
    {'name': 'Coffee Table', 'type': 'fixed', 'quantity': 1, 'unit_price': 15000, 'image_id': second}]}])})
with app.app_context():
    rid = Project.query.order_by(Project.id.desc()).first().id
    reused = Item.query.join(Item.room).filter(Room.project_id == rid).first().image_id
    n_images = ItemImage.query.count()
ok('a photo picked from My photos is used again (no new copy)', reused == second and n_images == 2
   and next(x for x in c.get('/item-images/library').get_json()['photos'] if x['id'] == second)['names'] == ['Coffee Table'])
v = c.get(f'/projects/{pid}').text
ok('the quotation page shows the photos', v.count('class="ki-line-photo"') == 2 and f'/item-images/{pid_img}' in v)
e = c.get(f'/projects/{pid}/edit').text
ok('editing brings the photos back', f'"image_id": {pid_img}' in e)
ok('Duplicate copies them (the same photo, no copy of the bytes)', f'"image_id": {second}' in c.get(f'/projects/new?from={pid}').text)
ok('Full Quotation PDF prints them', pdf_images(f'/projects/{pid}/pdf') == 2)
with app.app_context():
    AppSetting.set(layout.LAYOUT_KEY, layout.LAYOUT_ROOMS); db.session.commit()
ok('customer PDF (room by room) prints them', pdf_images(f'/projects/{pid}/pdf/customer') == 2)

# BOQ: a Photo column only when a line has a photo
with app.app_context():
    boq.set_enabled(True); db.session.commit()
c.post('/projects/new', data={'customer_name': 'BOQ Photos', 'mobile': '9000000802', 'discount_type': 'none',
                              'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Reception', 'items': [
    {'name': 'Reception Sofa', 'type': 'boq', 'quantity': 2, 'unit': 'nos', 'unit_price': 45000, 'image_id': second},
    {'name': 'Reception Chair', 'type': 'boq', 'quantity': 3, 'unit': 'nos', 'unit_price': 8000}]}])})
with app.app_context():
    bid = Project.query.order_by(Project.id.desc()).first().id
txt = re.sub(r'\s+', ' ', ' '.join(pg.extract_text() for pg in PdfReader(io.BytesIO(c.get(f'/projects/{bid}/pdf').data)).pages))
ok('BOQ PDF: a Photo column with the photo, totals unchanged', 'Photo' in txt and pdf_images(f'/projects/{bid}/pdf') == 1
   and '1,14,000' in txt.replace('114,000', '1,14,000'))
txt2 = re.sub(r'\s+', ' ', ' '.join(pg.extract_text() for pg in PdfReader(io.BytesIO(c.get(f'/projects/{pid}/pdf').data)).pages))

# Customer link
c.post(f'/projects/{bid}/share')
with app.app_context():
    from app import share
    tok = share._active_share(db.session.get(Project, bid)).token
anon = app.test_client()
q = anon.get(f'/q/{tok}').text
ok("customer's link shows the photo", f'/q/{tok}/photo/{second}' in q)
ok('…served to the customer', anon.get(f'/q/{tok}/photo/{second}').status_code == 200)
ok('…but not a photo that is on another quotation', anon.get(f'/q/{tok}/photo/{pid_img}').status_code == 404)
ok('photos need a login otherwise', anon.get(f'/item-images/{second}').status_code in (302, 401))

# Template keeps them; turning off hides the button, photos already on quotations stay
c.post(f'/projects/{bid}/template', data={'name': 'Reception set'})
with app.app_context():
    tpl = next(t for t in json.loads(AppSetting.get('quote_templates')) if t['name'] == 'Reception set')
    ok('Save as template keeps the photo', any(i.get('image_id') == second for r in tpl['rooms'] for i in r['items']))
    item_images.set_enabled(False); db.session.commit()
ok('off again: no Photo button on a new quotation', 'itemImages:  false' in c.get('/projects/new?blank=1').text)
ok('…a quotation that has photos keeps them (and shows them when edited)', 'itemImages:  true' in c.get(f'/projects/{bid}/edit').text
   and 'ki-line-photo' in c.get(f'/projects/{bid}').text)
