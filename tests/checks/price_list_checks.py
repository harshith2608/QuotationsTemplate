"""A firm's own price list (app/price_list.py) and the number checks on BOQ lines: "Price to follow", lines from a
starting quotation still waiting for their size, the form's Add line."""
import io, json, re, urllib.parse
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
    from app import layout as _lay0
    ok('BOQ sections carry their total (without "Price to follow" or rate-only lines)',
       [sec['total'] for sec in _lay0.boq_rows(snap)] == [56 * 1950])
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
# The Rate column: some firms show quantities and amounts only
with app.app_context():
    AppSetting.set('boq_hide_rate', '1'); db.session.commit()
nr = pdftext(f'/projects/{pid}/pdf/customer')
ok('Rate column off: the PDF has no Rate column, amounts and the rate-only line\'s rate still shown',
   ' Rate ' not in nr.split('Bill of Quantities')[1].split('Wardrobe')[0] and 'Amount' in nr and '1,09,200' in nr.replace('109,200', '1,09,200')
   and 'Rate 520' in nr)
ok('…the WhatsApp text gives amounts, not rates', '× Rs.1,950' not in urllib.parse.unquote(c.get(f'/projects/{pid}/whatsapp').headers.get('Location', '')))
s_ = c.get('/admin/settings?tab=documents').text
ok('…a "Show the Rate column" setting (unticked now) in Settings → Quotation PDFs', 'name="boq_rate_shown"' in s_
   and not re.search(r'id="boq_rate_shown" value="1"\s+checked', s_))
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'boq', 'boq_rate_shown': ['0', '1']})
with app.app_context():
    ok('…ticked again: the Rate column is back', AppSetting.get('boq_hide_rate') == '')
ok('…on the PDF too', ' Rate ' in pdftext(f'/projects/{pid}/pdf/customer').split('Bill of Quantities')[1].split('Wardrobe')[0])

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
       and '3 item options' in price_list.summary_text(res))
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
ok('Admin → Rates: each line\'s unit is a list (sqft, sqm, rft, rmt, no\'s, lump sum), not typed',
   'name="bq_unit" class="form-select' in r and '>sqm</option>' in r and 'no&#39;s</option>' in r
   and 'name="bq_unit" class="form-control' not in r)
with app.app_context():
    from app import boq as _boq
    used = _boq.own_units()
ok(f'…an Edit units dialog, starting with the units the items already use {used}', 'id="unitsModal"' in r
   and 'onclick="addUnit()"' in r and 'placeholder="Add a unit' not in r
   and all(f'name="unit_name" class="form-control" value="{u}"' in r for u in used))
c.post('/admin/rates', data={'units_submit': '1', 'unit_name': used + ['Kg', 'Sq.m', 'kg', ''], 'unit_delete': ['0'] if used else []})
with app.app_context():
    now = _boq.own_units()
ok(f'…they add (kg; Sq.m is the standard sqm, typed twice once) and remove units {now}', now == used[1:] + ['Kg'])
r = c.get('/admin/rates').text
ok('…and every item\'s list has them', '<option value="Kg" >Kg</option>' in r)
ok('Admin → Rates: an Item options card (section Finish, base rate, % extra) and a Finish tick per item', 'id="finishes"' in r
   and 'Item options' in r and 'value="Finish"' in r and 'Base rate' in r and 'name="bq_opt"' in r and 'value="25"' in r)
c.post('/admin/rates', data={'finish_submit': '1', 'sec_name': ['Finish', ''],
                             'opt_name_0': ['Laminate', 'Acrylic', 'Veneer', 'Membrane', ''],
                             'opt_val_0': ['0', '30', '40', '25', ''], 'opt_kind_0': ['pct'] * 5, 'opt_delete_0': ['2'],
                             'opt_name_1': ['', '', ''], 'opt_val_1': ['0', '', ''], 'opt_kind_1': ['pct'] * 3})
with app.app_context():
    ok('…they can change the %, add one and remove one', [(o['name'], o['extra']) for o in finishes.options()]
       == [('Laminate', 0), ('Acrylic', 30), ('Membrane', 25)] and finishes.line_ids() and len(finishes.all_sections()) == 1)
with app.app_context():
    wid = str(BoqItem.query.filter_by(name='Wardrobe').first().id)
    rows = [(str(b.id), b.name, b.description or '', b.unit, str(b.rate), b.category or '') for b in BoqItem.query.all()]
c.post('/admin/rates', data={'boq_submit': '1', 'bq_secname': ['Finish'], 'bq_id': [x[0] for x in rows], 'bq_name': [x[1] for x in rows],
                             'bq_desc': [x[2] for x in rows], 'bq_unit': [x[3] for x in rows], 'bq_rate': [x[4] for x in rows],
                             'bq_cat': [x[5] for x in rows], 'bq_opt': []})
with app.app_context():
    ok('…and untick an item (no Finish choice for it any more)', not finishes.line_ids()
       and not any(b.get('finish') for b in boq.saved_lines()))
ok('…a new line\'s row has its own Finish tick', 'name="bq_new_0"' in c.get('/admin/rates').text)
c.post('/admin/rates', data={'boq_submit': '1', 'bq_secname': ['Finish'],
                             'bq_id': [x[0] for x in rows] + ['', '', ''], 'bq_name': [x[1] for x in rows] + ['Study Table', 'Shoe Rack', ''],
                             'bq_desc': [x[2] for x in rows] + ['', '', ''], 'bq_unit': [x[3] for x in rows] + ['sqft'] * 3,
                             'bq_rate': [x[4] for x in rows] + ['1500', '1200', ''], 'bq_cat': [x[5] for x in rows] + [''] * 3,
                             'bq_opt': [f'Finish|{wid}'], 'bq_new_0': ['0', '0', '1', '0']})
with app.app_context():
    ticked = {BoqItem.query.get(i).name for i in finishes.line_ids()}
    ok(f'…new lines saved with their tick: only the one ticked comes in finishes {ticked}', ticked == {'Wardrobe', 'Shoe Rack'})

# ── Item options in sections: Finish (%), and Board (₹ per unit, a cheaper one takes off) ──
c.post('/admin/rates', data={'finish_submit': '1', 'sec_name': ['Finish', 'Board'],
                             'opt_name_0': ['Laminate', 'Acrylic', 'Membrane', '', ''], 'opt_val_0': ['0', '30', '25', '', ''],
                             'opt_kind_0': ['pct'] * 5,
                             'opt_name_1': ['16mm 8*4 Century Sainik 710', '16mm 8*4 Century Bond 710', '16mm 8*4 Gurjan'],
                             'opt_val_1': ['0', '400', '-100'], 'opt_kind_1': ['pct', 'amt', 'amt'], 'sec_quote': ['1']})
r = c.get('/admin/rates').text
ok('a second section, Board, with ₹ per unit extras: its own tick column', 'value="Board"' in r and 'value="Board|' in r
   and '₹ per unit' in r and 'name="bq_new_1"' in r)
ok('…Add option and Add section buttons in place of empty rows', 'onclick="addOption(1)"' in r and 'id="addSectionBtn"' in r
   and 'placeholder="Add an option"' not in r)
c.post('/admin/rates', data={'boq_submit': '1', 'bq_secname': ['Finish', 'Board'], 'bq_id': [x[0] for x in rows],
                             'bq_name': [x[1] for x in rows], 'bq_desc': [x[2] for x in rows], 'bq_unit': [x[3] for x in rows],
                             'bq_rate': [x[4] for x in rows], 'bq_cat': [x[5] for x in rows],
                             'bq_opt': [f'Finish|{wid}', f'Board|{wid}']})
with app.app_context():
    w = {b['name']: b for b in boq.saved_lines()}['Wardrobe']
    ok('the wardrobe comes in both sections', w.get('sections') == ['Finish', 'Board'])
    ok('the rate: base × (1 + %) + ₹ (1,800 → Acrylic +30% → Bond +400 = 2,740; Gurjan −100 = 1,700)',
       finishes.rate_for(1800, 'Acrylic|16mm 8*4 Century Bond 710') == 2740 and finishes.rate_for(1800, '16mm 8*4 Gurjan') == 1700
       and finishes.base_rate(2740, 'Acrylic|16mm 8*4 Century Bond 710') == 1800)
    ok('one choice kept per section, base ones dropped', finishes.clean('Laminate|16mm 8*4 Century Bond 710|16mm 8*4 Gurjan')
       == '16mm 8*4 Century Bond 710')
    ok('printed: a finish says so, a board prints as it is', finishes.label('Wardrobe', 'Acrylic|16mm 8*4 Century Bond 710')
       == 'Wardrobe (Acrylic finish, 16mm 8*4 Century Bond 710)')
    form = finishes.for_form()
    ok('the form gets both sections with their bases', [s['name'] for s in form['sections']] == ['Finish', 'Board']
       and form['sections'][1]['base'] == '16mm 8*4 Century Sainik 710')
    ok('Board is chosen per quotation, Finish per line', [s['quote'] for s in form['sections']] == [False, True])
ok('…the quotation form has the "Item options for this quotation" card', 'id="quoteOptionsCard"' in c.get('/projects/new?blank=1').text
   and 'function onQuoteOption' in c.get('/static/js/project_form.js').text)
ok('…and Rates shows it ticked', 'name="sec_quote" value="1" checked' in c.get('/admin/rates').text)
c.post('/projects/new', data={'customer_name': 'Board Home', 'mobile': '9000000903', 'discount_type': 'none',
                              'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Bedroom', 'items': [
    {'name': 'Wardrobe', 'type': 'boq', 'quantity': 10, 'unit': 'sqft', 'unit_price': 2740,
     'finish': 'Acrylic|16mm 8*4 Century Bond 710', 'save_default': True}]}])})
with app.app_context():
    bp = Project.query.order_by(Project.id.desc()).first()
    bid = bp.id
    it = Item.query.join(Item.room).filter(Room.project_id == bid).first()
    ok('saved with both choices, the right total, and the default saved at the base rate',
       it.finish == 'Acrylic|16mm 8*4 Century Bond 710' and it.wood_type == it.finish and bp.grand_total == 27400
       and BoqItem.query.filter_by(name='Wardrobe').first().rate == 1800)
    long_ = 'A' * 38 + '|' + 'B' * 38
    class _I: wood_type = work_type = ''
    x = _I(); finishes.store(x, long_)
    ok('long choices are kept whole', len(x.wood_type) == 50 and x.work_type.startswith('+') and finishes.stored(x) == long_)
pdf = pdftext(f'/projects/{bid}/pdf/customer')
ok('the PDF prints "Wardrobe (Acrylic finish, 16mm 8*4 Century Bond 710)" at 2,740',
   'Wardrobe (Acrylic finish, 16mm 8*4 Century Bond 710)' in pdf and '2,740' in pdf)
ok('editing brings both choices back', '"finish": "Acrylic|16mm 8*4 Century Bond 710"' in c.get(f'/projects/{bid}/edit').text)
# ── {Board} in the Material Specifications: the board(s) chosen on the quotation ──
st = c.get('/admin/settings?tab=documents').text
ok('Settings → Quotation PDFs offers an Insert button per item options section', '["Board", "Board"]' in st and '["Finish", "Finish"]' in st)
with app.app_context():
    by_item = boq.pricing_mode() == boq.ITEM
ok('…priced by item: no Plywood / Plywood details / Materials used buttons, and the example uses a section',
   not by_item or ('["plywood_details",' not in st and '["materials",' not in st and '<code>{Finish} for all' in st))
with app.app_context():
    from app import layout
    v = layout.variables(Project.query.get(bid))
    ok('{Board} / {finish} fill in the quotation\'s choices; unknown words stay as typed',
       layout.fill('{Board} for all carcass, { finish } outside, {nothing}', v)
       == '16mm 8*4 Century Bond 710 for all carcass, Acrylic outside, {nothing}'
       and layout.fill_html('<p>{Board} &amp; {plywood}</p>', v) == '<p>16mm 8*4 Century Bond 710 &amp; ' + v['plywood'] + '</p>')
# ── Costs & profit priced by item: your items' costs and each option's extra cost ──
cp = c.get('/admin/costs').text
ok('Costs & profit (priced by item): your items, and a card per item option section', 'id="item-costs"' in cp
   and f'name="l_{wid}"' in cp and 'Board (extra cost vs 16mm 8*4 Century Sainik 710)' in cp and 'name="m_0"' not in cp)
c.post('/admin/costs', data={f'l_{wid}': '1200', 'oc_Board|16mm 8*4 Century Bond 710': '300', 'oc_Finish|Acrylic': ''})
with app.app_context():
    from app import billing as _b
    pr = _b.profit(Project.query.get(bid))
    ok(f'the profit counts the line\'s options: 10 × (1,200 × 1.3 + 300) = 18,600 cost {pr and pr["cost"]}',
       pr and pr['cost'] == 18600 and not pr['missing'])
    ok('…an option with no cost of its own costs its price extra', finishes.cost_for(1200, '16mm 8*4 Gurjan') == 1100)
c.post('/admin/rates', data={'finish_submit': '1', 'sec_name': ['Finish', 'Board'],
                             'opt_name_0': ['Laminate', 'Acrylic', 'Membrane', '', ''], 'opt_val_0': ['0', '30', '25', '', ''],
                             'opt_kind_0': ['pct'] * 5,
                             'opt_name_1': ['16mm 8*4 Century Sainik 710', '16mm 8*4 Century Bond 710', '16mm 8*4 Gurjan'],
                             'opt_val_1': ['0', '400', '-100'], 'opt_kind_1': ['pct', 'amt', 'amt'], 'sec_quote': ['1']})
with app.app_context():
    ok('saving item options in Rates keeps their costs', finishes.cost_for(1000, '16mm 8*4 Century Bond 710') == 1300)
with app.app_context():
    out = price_list.export()
    ok('the price list download has the sections and each line\'s', [s['name'] for s in out.get('choices') or []] == ['Finish', 'Board']
       and out['choices'][1]['options'][1] == {'name': '16mm 8*4 Century Bond 710', 'amount': 400}
       and out['choices'][1].get('per_quotation') and not out['choices'][0].get('per_quotation')
       and next(l for l in out['lines'] if l['name'] == 'Wardrobe')['choices'] == ['Finish', 'Board'] and 'finishes' not in out)
    AppSetting.set(finishes.KEY, ''); db.session.commit()
    res = price_list.apply(price_list.parse(json.dumps(out).encode()), remove_starter=False)
    ok('…and loads back as it was', [(s['name'], s['quote']) for s in finishes.sections()] == [('Finish', False), ('Board', True)]
       and finishes.rate_for(1800, '16mm 8*4 Gurjan') == 1700
       and {b['name']: b for b in boq.saved_lines()}['Wardrobe'].get('sections') == ['Finish', 'Board'])
    ok('a line naming a section the file doesn\'t have is refused', 'no "choices" section' in
       bad({'lines': [{'name': 'A', 'choices': ['Hardware']}]}))
    # A business set up before sections: its one list of finishes reads as a section named Finish, nothing to redo
    AppSetting.set(finishes.KEY, json.dumps({'options': [{'name': 'Laminate', 'extra': 0}, {'name': 'Acrylic', 'extra': 25}],
                                             'lines': [int(wid)]})); db.session.commit()
    ok('a business set up before sections needs nothing: same choice, rate and print',
       [s['name'] for s in finishes.sections()] == ['Finish'] and finishes.rate_for(1800, 'Acrylic') == 2250
       and {b['name']: b for b in boq.saved_lines()}['Wardrobe'].get('sections') == ['Finish']
       and finishes.label('Wardrobe', 'Acrylic') == 'Wardrobe (Acrylic finish)')
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
ok('"options" are checked', 'GST rate' in bad({'options': {'gst': 7}}) and 'true or false' in bad({'options': {'show_rate': 'no'}}))
with app.app_context():
    from app import quote_gst as _qg2, layout as _lay2
    r_opt = price_list.apply(price_list.parse(json.dumps({'options': {'show_rate': False, 'gst': 18}}).encode()))
    ok('a file can hide the Rate column and turn GST on (and say so)', not _lay2.show_rate() and _qg2.rate() == 18
       and 'Rate column hidden' in price_list.summary_text(r_opt) and 'GST on quotations 18%' in price_list.summary_text(r_opt))
    price_list.apply(price_list.parse(json.dumps({'options': {'show_rate': True, 'gst': False}}).encode()))
    ok('…and back again', _lay2.show_rate() and _qg2.rate() == 0)
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

# ── Download price list (console): the firm's rates as they are, in the same format, loads back unchanged ──
with app.app_context():
    price_list.apply(price_list.parse(json.dumps(FIN).encode()), remove_starter=False)   # finishes again (cleared above)
    out = price_list.export('Test firm')
    again = price_list.parse(json.dumps(out).encode())
    ok('the export is a valid price list (parse accepts it)', again['pricing'] == out['pricing'])
    lines = {l['name']: l for l in out.get('lines') or []}
    ok('it has the saved lines with unit, rate, group and finish, and the finishes (base first)',
       lines.get('Wardrobe', {}).get('finish') and lines['Wardrobe']['rate'] == BoqItem.query.filter_by(name='Wardrobe').first().rate
       and [f['name'] for f in out.get('finishes') or []][:1] == ['Laminate'])
    ok('it has the materials with their rates, the fittings and the templates',
       all('rates' in m or 'rate' in m for m in out.get('materials') or [])
       and any(m.get('rates') for m in out.get('materials') or []) and out.get('fittings')
       and any(t['name'] == 'Firm 2 BHK' for t in out.get('templates') or []))
    ok('its notes and PDF options', out['settings'].get('payment_terms') and 'layout' in out['options'] and 'gst' in out['options'])
    strip = lambda d: {k: v for k, v in d.items() if k not in ('firm', 'templates')}
    price_list.apply(price_list.parse(json.dumps(out).encode()), remove_starter=False)
    back = price_list.export('Test firm')
    ok('loading the export back changes nothing (rates, lines, boards, fittings, settings the same)', strip(back) == strip(out))
    ok('…and the templates keep their rooms and items',
       [(t['name'], [(r['name'], [i['name'] for i in r['items']]) for r in t['rooms']]) for t in back.get('templates') or []]
       == [(t['name'], [(r['name'], [i['name'] for i in r['items']]) for r in t['rooms']]) for t in out.get('templates') or []]
       or sorted(t['name'] for t in back['templates']) == sorted(t['name'] for t in out['templates']))

# ── A line named "… – Box Work" / "… – Frame Work": two rates for one item; the customer sees the item's name alone ──
with app.app_context():
    from app import finishes
    from app.materials import SHOW_WORK_KEY
    ok('"Kitchen Base Unit – Box Work" prints as "Kitchen Base Unit" (and with a hyphen; other endings untouched)',
       finishes.label('Kitchen Base Unit – Box Work', '') == 'Kitchen Base Unit'
       and finishes.label('Kitchen Base Unit - Frame Work', 'Acrylic') == 'Kitchen Base Unit (Acrylic finish)'
       and finishes.label('Wall – Paint', '') == 'Wall – Paint' and finishes.label('Box Work', '') == 'Box Work')
    AppSetting.set(SHOW_WORK_KEY, '1'); db.session.commit()
    ok('…unless the business shows work types to customers', finishes.label('Kitchen Base Unit – Box Work', '') == 'Kitchen Base Unit – Box Work')
    AppSetting.set(SHOW_WORK_KEY, ''); db.session.commit()
c.post('/projects/new', data={'customer_name': 'Box Home', 'mobile': '9000000903', 'discount_type': 'none', 'discount_value': '0',
                              'rooms_data': json.dumps([{'name': 'Kitchen', 'items': [
    {'name': 'Kitchen Base Unit – Box Work', 'type': 'boq', 'quantity': 0, 'unit': 'sqft', 'unit_price': 2200, 'length': 10, 'width': 2, 'count': 1}]}])})
with app.app_context():
    bid = Project.query.order_by(Project.id.desc()).first().id
t_ = pdftext(f'/projects/{bid}/pdf/customer')
ok('the customer PDF prints the item without "Box Work"; the form keeps the full name',
   'Kitchen Base Unit' in t_ and 'Box Work' not in t_
   and any(x in c.get(f'/projects/{bid}/edit').text for x in ('Kitchen Base Unit – Box Work', 'Kitchen Base Unit \\u2013 Box Work')))
