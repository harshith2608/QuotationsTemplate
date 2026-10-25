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

# ── Finishes: the same item in another finish costs a % more (Laminate base, Acrylic +25%) ──
FIN = {'finishes': [{'name': 'Laminate'}, {'name': 'Acrylic', 'extra': 25}, {'name': 'Veneer', 'extra': 40}],
       'lines': [{'name': 'Wardrobe', 'unit': 'sqft', 'rate': 1800, 'finish': True},
                 {'name': 'Site Cleaning', 'unit': 'LS', 'rate': 9000}]}
ok('a price list with finishes is checked: one finish alone, or lines with "finish" but no finishes',
   'at least one other' in bad({'finishes': [{'name': 'Laminate'}], 'lines': [{'name': 'A'}]})
   and 'no "finishes"' in bad({'lines': [{'name': 'A', 'finish': True}]}))
with app.app_context():
    from app import finishes
    res = price_list.apply(price_list.parse(json.dumps(FIN).encode()))
    saved = {b['name']: b for b in boq.saved_lines()}
    ok('loaded: the finishes (base first) and which lines come in them', res['finishes'] == 3
       and [o['name'] for o in finishes.options()] == ['Laminate', 'Acrylic', 'Veneer'] and finishes.extra('acrylic') == 25
       and saved['Wardrobe'].get('finish') and not saved['Site Cleaning'].get('finish')
       and '3 finishes' in price_list.summary_text(res))
    more = {'finishes': FIN['finishes'], 'lines': [{'name': 'Janitor Unit', 'unit': 'sqft', 'rate': 2350, 'finish': True}]}
    price_list.apply(price_list.parse(json.dumps(more).encode()))
    saved = {b['name']: b for b in boq.saved_lines()}
    ok('a later file with a few new lines in finishes adds their tick and keeps the others', saved['Janitor Unit'].get('finish')
       and saved['Wardrobe'].get('finish'))
f = c.get('/projects/new?blank=1').text
ok('the form gets the finishes', '"Acrylic"' in f and 'boqFinishes' in f
   and 'onBoqFinish' in c.get('/static/js/project_form.js').text)
c.post('/projects/new', data={'customer_name': 'Acrylic Home', 'mobile': '9000000902', 'discount_type': 'none',
                              'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Bedroom', 'items': [
    {'name': 'Wardrobe', 'type': 'boq', 'quantity': 0, 'unit': 'sqft', 'unit_price': 2250, 'length': 7, 'width': 8,
     'count': 1, 'finish': 'Acrylic', 'save_default': True},
    {'name': 'Wardrobe', 'type': 'boq', 'quantity': 10, 'unit': 'sqft', 'unit_price': 1800, 'finish': 'Laminate'}]}])})
with app.app_context():
    fp = Project.query.order_by(Project.id.desc()).first()
    fid = fp.id
    its = sorted(Item.query.join(Item.room).filter(Room.project_id == fid).all(), key=lambda i: i.id)
    snap = billing.quotation_snapshot(fp)
    ok('saved: the acrylic line keeps its finish and rate, the laminate (base) line has none; total right',
       its[0].finish == 'Acrylic' and its[0].unit_price == 2250 and its[1].finish == ''
       and its[0].display_name == 'Wardrobe (Acrylic finish)' and its[1].display_name == 'Wardrobe'
       and abs(fp.grand_total - (56 * 2250 + 10 * 1800)) < 0.01)
    ok('"Save as my default" on an acrylic line saves the laminate rate (2,250 ÷ 1.25 = 1,800)',
       BoqItem.query.filter_by(name='Wardrobe').first().rate == 1800)
    ok('the snapshot and invoice say the finish', any(i.get('finish') == 'Acrylic' for r in snap['rooms'] for i in r['items'])
       and [l['description'] for l in billing.invoice_lines(snap, '9403')] == ['Wardrobe (Acrylic finish)', 'Wardrobe'])
    from app import layout as _lay
    ok('the BOQ rows say it', [l['title'] for s_ in _lay.boq_rows(snap) for l in s_['lines']] == ['Wardrobe (Acrylic finish)', 'Wardrobe'])
pdf = pdftext(f'/projects/{fid}/pdf/customer')
ok('the PDF prints "Wardrobe (Acrylic finish)" at 2,250', 'Wardrobe (Acrylic finish)' in pdf and '2,250' in pdf)
ok('the quotation page and WhatsApp text too', 'Wardrobe (Acrylic finish)' in c.get(f'/projects/{fid}').text
   and 'Wardrobe (Acrylic finish)' in urllib.parse.unquote(c.get(f'/projects/{fid}/whatsapp').headers.get('Location', '')))
e = c.get(f'/projects/{fid}/edit').text
ok('editing brings the finish back', '"finish": "Acrylic"' in e)
r = c.get('/admin/rates').text
ok('Admin → Rates: a Finishes card (base rate, % extra) and a Finishes tick per item', 'id="finishes"' in r
   and 'Base rate' in r and 'name="bq_finish"' in r and 'value="25"' in r)
c.post('/admin/rates', data={'finish_submit': '1', 'fin_name': ['Laminate', 'Acrylic', 'Veneer', 'Membrane', ''],
                             'fin_extra': ['0', '30', '40', '25', ''], 'fin_delete': ['2']})
with app.app_context():
    ok('…they can change the %, add one and remove one', [(o['name'], o['extra']) for o in finishes.options()]
       == [('Laminate', 0), ('Acrylic', 30), ('Membrane', 25)] and finishes.line_ids())
with app.app_context():
    wid = str(BoqItem.query.filter_by(name='Wardrobe').first().id)
    rows = [(str(b.id), b.name, b.description or '', b.unit, str(b.rate), b.category or '') for b in BoqItem.query.all()]
c.post('/admin/rates', data={'boq_submit': '1', 'bq_finish_on': '1', 'bq_id': [x[0] for x in rows], 'bq_name': [x[1] for x in rows],
                             'bq_desc': [x[2] for x in rows], 'bq_unit': [x[3] for x in rows], 'bq_rate': [x[4] for x in rows],
                             'bq_cat': [x[5] for x in rows], 'bq_finish': []})
with app.app_context():
    ok('…and untick an item (no Finish choice for it any more)', not finishes.line_ids()
       and not any(b.get('finish') for b in boq.saved_lines()))
    finishes.save([], []); db.session.commit()
    ok('no finishes: nothing changes (no choice offered)', finishes.for_form() is None
       and not any(b.get('finish') for b in boq.saved_lines()))

# ── Quotations from the firm's own sheets, loaded as real quotations ──
QF = {'quotations': [{'customer_name': 'Sheet Home (2 BHK)', 'address': 'Sheet Towers', 'total': 47000,
                      'rooms': [{'name': 'Other Services', 'items': [
                          {'name': '3D Design', 'unit': 'lump sum', 'quantity': 1, 'rate': 25000},
                          {'name': 'Vanity Storage', 'description': 'BWP ply\n6 Sq.ft × 2 Nos', 'unit': 'Sq.ft', 'quantity': 12, 'rate': 1500},
                          {'name': 'Electric Wiring', 'unit': 'point', 'quantity': 4, 'rate': 1000}]}]}]}
ok('a quotation whose lines don\'t add up to its total is refused',
   'adds up to' in bad(dict(QF, quotations=[dict(QF['quotations'][0], total=50000)])))
with app.app_context():
    before_lines = BoqItem.query.count()
    mode_before = boq.pricing_mode()
    res = price_list.apply(price_list.parse(json.dumps(QF).encode()))
    q = next(p for p in Project.query.all() if p.customer_name == 'Sheet Home (2 BHK)')
    qits = {i.name: i for i in Item.query.join(Item.room).filter(Room.project_id == q.id).all()}
    from app.models import QuoteRevision
    ok('loaded as a real quotation (lines, units, total, its first revision), how they price unchanged, saved lines untouched',
       res['quotations'] == ['Sheet Home (2 BHK)'] and abs(q.grand_total - 47000) < 0.01 and q.address == 'Sheet Towers'
       and qits['Vanity Storage'].unit == 'sqft' and qits['Vanity Storage'].quantity == 12 and qits['3D Design'].unit == 'lump sum'
       and q.status == 'complete' and boq.pricing_mode() == mode_before and BoqItem.query.count() == before_lines
       and QuoteRevision.query.filter_by(project_id=q.id).count() == 1 and 'quotation added' in price_list.summary_text(res))
    again = price_list.apply(price_list.parse(json.dumps(QF).encode()))
    ok('loading the file again adds it only once', again['quotations'] == []
       and sum(1 for p in Project.query.all() if p.customer_name == 'Sheet Home (2 BHK)') == 1)
ok('it opens like any quotation', c.get(f'/projects/{q.id}').status_code == 200 and 'Vanity Storage' in c.get(f'/projects/{q.id}').text)

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

# ── Priced by material: one-off work as a lump sum (Add item → Lump sum) ──
f = c.get('/projects/new?blank=1').text
saved = json.loads(re.search(r'boqSaved:\s*(\[.*?\]),\n', f, re.S).group(1))
ok('by material: the Add item window has a Lump sum tab, offering only the saved lump sums',
   'id="modal_type_lump"' in f and 'lumpSum:     true' in f and 'id="modal_type_boq"' not in f
   and 'Site Cleaning' in [b['name'] for b in saved] and all(b['unit'] == 'lump sum' for b in saved))
c.post('/projects/new', data={'customer_name': 'Lump Home', 'mobile': '9000000903', 'discount_type': 'none',
                              'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Pooja Room', 'items': [
    {'name': 'Base Unit', 'length': 10, 'width': 2, 'wood_type': 'Laminates', 'work_type': 'Box Work'},
    {'name': 'Pooja Civil Works', 'type': 'boq', 'quantity': 1, 'unit': 'lump sum', 'unit_price': 30000,
     'description': 'Wall extension, plastering and painting'},
    {'name': 'Stray Line', 'type': 'boq', 'quantity': 2, 'unit': 'sqft', 'unit_price': 100}]}])})
with app.app_context():
    lp = Project.query.order_by(Project.id.desc()).first()
    lid = lp.id
    its = {i.name: i for i in Item.query.join(Item.room).filter(Room.project_id == lid).all()}
    ok('saved: the lump sum stays a lump sum (other BOQ lines become fixed-price items), total right',
       its['Pooja Civil Works'].is_boq and its['Pooja Civil Works'].unit == 'lump sum'
       and its['Stray Line'].is_fitting and abs(lp.grand_total - (20 * 900 + 30000 + 200)) < 0.01)
    ok('…and remembered for next time, with its description', BoqItem.query.filter_by(name='Pooja Civil Works').first().rate == 30000)
    snap = billing.quotation_snapshot(lp)
    ok('…on the invoice', 'Pooja Civil Works' in [l['description'] for l in billing.invoice_lines(snap, '9403')])
e = c.get(f'/projects/{lid}/edit').text
ok('editing it: still the by-material form (Lump sum tab, not BOQ lines)', 'lumpSum:     true' in e and 'id="modal_type_boq"' not in e)
v = c.get(f'/projects/{lid}').text
ok('the quotation page shows it as a Lump sum', '>Lump sum<' in v and 'Pooja Civil Works' in v)
for u in (f'/projects/{lid}/pdf', f'/projects/{lid}/pdf/customer'):
    t_ = pdftext(u)
    ok(f'{u.rsplit("/", 1)[-1]} PDF prints the lump sum and its amount', 'Pooja Civil Works' in t_ and '30,000' in t_)
r = c.get('/admin/rates').text
ok('Admin → Rates (by material): a Lump sums list', 'id="lump-sums"' in r and 'Pooja Civil Works' in r and 'Stray Line' not in r)
with app.app_context():
    rows = [(str(b.id), b.name, b.description or '', b.category or '') for b in BoqItem.query.filter_by(unit='lump sum').all()]
    wardrobe = BoqItem.query.filter_by(name='Wardrobe').first().rate
c.post('/admin/rates', data={'boq_submit': '1', 'bq_id': [x[0] for x in rows] + [''], 'bq_name': [x[1] for x in rows] + ['Debris Removal'],
                             'bq_desc': [x[2] for x in rows] + [''], 'bq_unit': ['lump sum'] * (len(rows) + 1),
                             'bq_rate': ['32000' if x[1] == 'Pooja Civil Works' else '9000' for x in rows] + ['50000'],
                             'bq_cat': [x[3] for x in rows] + ['']})
with app.app_context():
    ok('…they can change an amount and add one (other saved lines untouched)',
       BoqItem.query.filter_by(name='Pooja Civil Works').first().rate == 32000
       and BoqItem.query.filter_by(name='Debris Removal').first().unit == 'lump sum'
       and BoqItem.query.filter_by(name='Wardrobe').first().rate == wardrobe)

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
