"""A firm's own price list (app/price_list.py) and the number checks on BOQ lines: "Price to follow", lines from a
starting quotation still waiting for their size, the form's Add line."""
import io, json, re
from pypdf import PdfReader
from app import create_app, db, billing, boq, price_list
from app.models import AppSetting, BoqItem, Item, Project, Room

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pdftext = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))

FILE = {'lines': [{'name': 'Wardrobe', 'unit': 'Sq.ft', 'rate': 1950, 'group': 'Bedroom',
                   'description': 'BWR ply, laminate inside and outside'},
                  {'name': 'Site Cleaning', 'unit': 'LS', 'rate': 9000, 'group': 'Services'},
                  {'name': 'COB Light', 'unit': 'nos', 'rate': 520, 'group': 'Light rates'}],
        'templates': [{'name': 'Firm 2 BHK', 'rooms': [
            {'name': 'Bedroom', 'items': ['Wardrobe', 'Site Cleaning']},
            {'name': 'Light rates', 'description': ['Rates as per final design'], 'items': [{'name': 'COB Light', 'rate_only': True}]}]}],
        'settings': {'payment_terms': 'Half before work starts.', 'important_notes': 'Final bill as per measurement.'}}


def bad(data):
    try:
        price_list.parse(json.dumps(data).encode() if not isinstance(data, bytes) else data)
    except price_list.PriceListError as exc:
        return str(exc)
    return ''


ok('a price list file is checked: not JSON, no name, a rate that isn\'t a number, a name twice',
   "isn't a price list" in bad(b'hello') and 'has no name' in bad({'lines': [{'rate': 5}]})
   and 'should be a number' in bad({'lines': [{'name': 'A', 'rate': 'x'}]})
   and 'twice' in bad({'lines': [{'name': 'A'}, {'name': 'a'}]}))

with app.app_context():
    AppSetting.set('payment_terms', 'Our own terms'); db.session.commit()
    result = price_list.apply(price_list.parse(json.dumps(FILE).encode()), remove_starter=True)
    lines = {b.name: (b.unit, b.rate, b.category, b.description) for b in BoqItem.query.all()}
    ok('loaded into this business: BOQ lines on, its lines (units cleaned), starter lines gone',
       boq.enabled() and AppSetting.get('initial_layout') == 'boq' and len(lines) == 3
       and lines['Wardrobe'] == ('sqft', 1950, 'Bedroom', 'BWR ply, laminate inside and outside')
       and lines['Site Cleaning'][0] == 'lump sum' and result['templates'] == ['Firm 2 BHK'])
    ok('a section\'s notes: on the starting quotation and added to the room descriptions',
       json.loads(AppSetting.get('quote_templates'))[0]['rooms'][1]['description'] == 'Rates as per final design'
       and 'Rates as per final design' in AppSetting.get('room_descriptions'))
    ok('settings: filled in only where never saved', AppSetting.get('payment_terms') == 'Our own terms'
       and AppSetting.get('important_notes') == 'Final bill as per measurement.')
    tid = json.loads(AppSetting.get('quote_templates'))[0]['id']
    again = price_list.apply(price_list.parse(json.dumps(FILE).encode()))
    ok('loading again updates by name (no duplicates, one template)', again['added'] == 0 and again['updated'] == 3
       and BoqItem.query.count() == 3 and len(json.loads(AppSetting.get('quote_templates'))) == 1)
    tid = json.loads(AppSetting.get('quote_templates'))[0]['id']

t = c.get(f'/projects/new?template={tid}').text
rooms = json.loads(re.search(r'id="existing-rooms-data"[^>]*>(.*?)</script>', t, re.S).group(1))
items = {i['name']: i for r in rooms for i in r['items']}
ok('New Quotation from the starting quotation: lines with their rate and description, waiting for a size',
   items['Wardrobe']['unit_price'] == 1950 and items['Wardrobe']['pending'] and items['Wardrobe']['quantity'] == 0
   and items['Wardrobe']['description'].startswith('BWR ply') and items['Site Cleaning']['quantity'] == 1
   and not items['COB Light'].get('pending'))
ok('the form offers Add line (no window) and Price to follow', 'addBoqLine' in c.get('/static/js/project_form.js').text
   and 'Price to follow' in c.get('/static/js/project_form.js').text)

# ── Price to follow ──
c.post('/projects/new', data={'customer_name': 'Price Later', 'mobile': '9000000901', 'discount_type': 'none',
                              'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Bedroom', 'items': [
    {'name': 'Wardrobe', 'type': 'boq', 'quantity': 0, 'unit': 'sqft', 'unit_price': 1950, 'length': 7, 'width': 8, 'count': 1},
    {'name': 'Lights & Fittings', 'type': 'boq', 'quantity': 1, 'unit': 'lump sum', 'unit_price': 50000, 'tbc': True},
    {'name': 'COB Light', 'type': 'boq', 'quantity': 0, 'unit': 'nos', 'unit_price': 520}]}])})
with app.app_context():
    p = Project.query.order_by(Project.id.desc()).first()
    pid = p.id
    tbc = Item.query.join(Item.room).filter(Room.project_id == pid, Item.name == 'Lights & Fittings').first()
    snap = billing.quotation_snapshot(p)
    ok('a "Price to follow" line has no rate and isn\'t added: total = 7 × 8 × 1,950 only', tbc.price_to_follow
       and tbc.unit_price is None and abs(p.grand_total - 56 * 1950) < 0.01 and abs(snap['subtotal'] - 56 * 1950) < 0.01)
    ok('…kept in the snapshot', any(i.get('tbc') for r in snap['rooms'] for i in r['items']))
    lines = billing.invoice_lines(snap, '9403')
    ok('…and never billed on an invoice', [l['description'] for l in lines] == ['Wardrobe'])
pdf = pdftext(f'/projects/{pid}/pdf/customer')
ok('the BOQ PDF prints "Price to follow" for it, the rate card line with its rate, the total without it',
   'Price to follow' in pdf and '1,09,200' in pdf.replace('109,200', '1,09,200') and '520' in pdf)
v = c.get(f'/projects/{pid}').text
ok('priced by item: one "Quotation PDF" button (no Full / Initial), no "Customer sees" choice, nothing to pick when emailing',
   'Quotation PDF' in v and 'Full Quotation' not in v and 'Initial Quotation' not in v and 'Customer sees' not in v
   and 'id="eqFull"' not in v)
ok('…and the Full Quotation address gives that same BOQ', 'Bill of Quantities' in pdftext(f'/projects/{pid}/pdf')
   and 'Bill of Quantities' in pdftext(f'/projects/{pid}/pdf/customer'))
with app.test_request_context():
    from app.pdf_utils import generate_pdf
    fullq = re.sub(r'\s+', ' ', ' '.join(pg.extract_text() for pg in PdfReader(generate_pdf(Project.query.get(pid))).pages))
ok('(the Full Quotation itself, if they switch back: section totals, no areas, rate-only line with "—")',
   'Section Total' in fullq and 'Material & Work Type' not in fullq and 'sqft' not in fullq.replace('Sq.ft', '')
   and re.search(r'COB Light — Nos\. 520 —', fullq) is not None and 'price to follow' in fullq.lower())
ok('the quotation page shows Price to follow too', 'price to follow' in v)
ok('quotation page priced by item: Qty / Unit / Rate / Amount per section, section totals, no plywood or areas',
   'Section Total' in v and '<th>Section</th>' in v and 'Room Total:' not in v and 'id="quotePlywood"' not in v
   and 'rate only' in v)
e = c.get(f'/projects/{pid}/edit').text
ok('editing keeps it as Price to follow', '"tbc": true' in e)
import urllib.parse
wa = c.get(f'/projects/{pid}/whatsapp')
ok('WhatsApp text says price to follow', 'Lights & Fittings: price to follow' in urllib.parse.unquote(wa.headers.get('Location', '')))
c.post(f'/projects/{pid}/share')
with app.app_context():
    from app import share
    tok = share._active_share(Project.query.get(pid)).token
ok('customer link shows price to follow', 'price to follow' in c.get(f'/q/{tok}').text)

# ── Pricing: by item / by material (Settings → Pricing, a setup guide step) ──
from app import setup_guide
s = c.get('/admin/settings?tab=pricing').text
ok('Settings → Pricing: the two ways, "by item" chosen', 'name="pricing_mode"' in s
   and re.search(r'id="pm_item" value="item"\s+checked', s) is not None)
f = c.get(f'/projects/new?template={tid}').text
ok('by item: the form has no plywood card or "Other item…", Rates lists the items first', '"byItem": true' in f.replace('byItem:      true', '"byItem": true')
   and 'Your items &amp; rates' in c.get('/admin/rates').text and 'Show them' in c.get('/admin/rates').text)
ok('New Quotation offers the starting quotations first', 'Start from one of your quotations' in c.get('/projects/new').text
   and 'Start from one of your quotations' not in c.get('/projects/new?blank=1').text)
r = c.post('/admin/settings', data={'section': 'pricing', 'pricing_mode': 'material'}, follow_redirects=True)
with app.app_context():
    ok('switching to by material: BOQ lines off, setup guide step done', not boq.enabled()
       and dict((st.key, d) for st, d in setup_guide.status()['steps'])['pricing'])
ok('by material: Full and Initial Quotation again', 'Full Quotation' in c.get(f'/projects/{pid}').text
   and 'Customer sees' in c.get(f'/projects/{pid}').text)
ok('by material: the rates step and the form are the material ones again', 'Your items &amp; rates' not in c.get('/admin/rates').text
   and 'byItem:      false' in c.get('/projects/new?blank=1').text)

MAT = {'pricing': 'material',
       'materials': [{'name': 'Laminates', 'rates': {'Box Work': 900, 'Frame Work': 700}}, {'name': 'Fluted Glass', 'rate': 650}],
       'fittings': [{'name': 'Magic Corner', 'price': 18000, 'unit': 'nos'}],
       'templates': [{'name': 'Modular kitchen', 'rooms': [{'name': 'Kitchen', 'items': [
           {'name': 'Base Unit', 'material': 'Laminates', 'work': 'Box Work'},
           {'name': 'Shutter Glass', 'material': 'Fluted Glass'},
           {'name': 'Magic Corner', 'type': 'fitting'},
           {'name': 'Ghost', 'material': 'Unobtainium'}]}]}]}
with app.app_context():
    from app.models import ItemRate, PriceListItem
    res = price_list.apply(price_list.parse(json.dumps(MAT).encode()))
    rates = {(r.wood_type, r.work_type): r.rate_per_sqft for r in ItemRate.query.all()}
    ok('a by-material price list: material rates, a new single-rate material, fittings; still by material',
       not boq.enabled() and rates[('Laminates', 'Box Work')] == 900 and rates[('Fluted Glass', '')] == 650
       and PriceListItem.query.filter_by(name='Magic Corner').first().price == 18000
       and res['missing'] == ['Ghost (Unobtainium)'])
    mk = next(t for t in json.loads(AppSetting.get('quote_templates')) if t['name'] == 'Modular kitchen')['id']
t = c.get(f'/projects/new?template={mk}').text
items = {i['name']: i for r in json.loads(re.search(r'id="existing-rooms-data"[^>]*>(.*?)</script>', t, re.S).group(1))
         for i in r['items']}
ok('its starting quotation: measured items with their material waiting for a size, the fitting at its price',
   items['Base Unit']['type'] == 'measured' and items['Base Unit']['pending'] and items['Base Unit']['wood_type'] == 'Laminates'
   and items['Shutter Glass']['work_type'] == '' and items['Magic Corner']['type'] == 'fixed'
   and items['Magic Corner']['unit_price'] == 18000 and items['Magic Corner']['pending'])

# ── Starter lines in the business's own units ──
with app.app_context():
    AppSetting.set('area_unit', 'sqm'); db.session.commit()
    from app import units
    units.clear_cache()
    m = {n: (u, r) for _, n, u, r, _ in boq.starter_lines()}
    i = {n: (u, r) for _, n, u, r, _ in boq.starter_lines(metric=False)}
    ok('a business in sq m gets its starter lines per sq m / per rmt (₹120/sqft → ₹1,290/sq m), others unchanged',
       i['False Ceiling'] == ('sqft', 120) and m['False Ceiling'] == ('sq m', 1290) and m['Paint Work'] == ('sq m', 480)
       and m['Fan Fitting'] == i['Fan Fitting'] and any(u == 'rmt' for u, _ in m.values()))
    AppSetting.set('area_unit', 'sqft'); db.session.commit(); units.clear_cache()
