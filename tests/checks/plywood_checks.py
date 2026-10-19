"""Plywood pricing: options in Admin → Rates, quotation + item plywood, prices everywhere, profit, revisions, safety."""
import io, json, re
from pypdf import PdfReader
from sqlalchemy import text
from app import create_app, db, billing, plywood
from app.models import (CostRate, Item, ItemRate, Material, PlywoodOption, Project, QuoteRevision)
from sqlalchemy.orm import undefer

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
pdftext = lambda u: '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages)
money = lambda v: f'{v:,.2f}'


def rate(wood, work):
    with app.app_context():
        return ItemRate.query.filter_by(wood_type=wood, work_type=work).first().rate_per_sqft


def opts():
    with app.app_context():
        return {o.name: o for o in PlywoodOption.query.all()}


# ── Starting point: the classic list, all at ₹0, so no price changes ──
with app.app_context():
    rows = PlywoodOption.query.order_by(PlywoodOption.sort_order).all()
    mats = {m.name: m.uses_plywood for m in Material.query.options(undefer(Material.uses_plywood))}
ok('new business: the classic plywood list, first one default, all ₹0',
   [r.name for r in rows][:2] == ['18mm 8*4', '12mm 8*4'] and rows[0].is_default and all((r.adjustment or 0) == 0 for r in rows))
ok('board materials are priced on plywood, Glass isn\'t', mats.get('Laminates') and mats.get('Acrylic') and not mats.get('Glass'))
t = c.get('/admin/rates').text
ok('Rates page has the Plywood card and an On plywood column', 'id="plywood"' in t and 'On plywood' in t
   and 'your rates are for this one' in t)

# ── Admin sets it up: add 18mm BWP at +150, 12mm at -200, rename 6mm ──
o = opts()
form = {'plywood_submit': '1', 'ply_default': str(o['18mm 8*4'].id), 'ply_new_name': '18mm BWP', 'ply_new_adj': '+150'}
for name, row in o.items():
    form[f'ply_name_{row.id}'] = '6mm Back Panel' if name == '6mm 8*4' else name
    form[f'ply_adj_{row.id}'] = '-200' if name == '12mm 8*4' else '0'
    form[f'ply_active_{row.id}'] = '1'
r = c.post('/admin/rates', data=form, follow_redirects=True)
o = opts()
ok('save plywood: new one added, price differences and rename saved', 'Plywood updated' in r.text
   and o['18mm BWP'].adjustment == 150 and o['12mm 8*4'].adjustment == -200 and '6mm Back Panel' in o and '6mm 8*4' not in o)
r = c.post('/admin/rates', data=dict(form, **{f'ply_adj_{o["12mm 8*4"].id}': 'abc', 'ply_new_name': ''}), follow_redirects=True)
ok('a price difference that isn\'t a number is refused', 'as a number' in r.text and opts()['12mm 8*4'].adjustment == -200)

LAM, ACR, GLASS = rate('Laminates', 'Box Work'), rate('Acrylic', 'Box Work'), rate('Glass', '')
with app.app_context():
    rm = plywood.rate_map()
ok('rate map: plywood materials get rate + difference on other plywood; Glass never',
   rm['Laminates|Box Work|18mm BWP'] == LAM + 150 and rm['Laminates|Box Work|12mm 8*4'] == LAM - 200
   and rm['Laminates|Box Work'] == LAM and 'Glass||18mm BWP' not in rm)

# ── A quotation on 18mm BWP, one item back on the default, glass unaffected ──
rooms = [{'name': 'Kitchen', 'items': [
    {'name': 'Base Cabinet', 'length': 10, 'width': 5, 'wood_type': 'Laminates', 'work_type': 'Box Work'},       # 50 sqft, BWP
    {'name': 'Shutters', 'length': 4, 'width': 3, 'wood_type': 'Acrylic', 'work_type': 'Box Work', 'plywood': '18mm 8*4'},  # 12, default
    {'name': 'Back Glass', 'length': 4, 'width': 2, 'wood_type': 'Glass', 'work_type': '', 'plywood': '18mm BWP'},  # 8, glass
    {'name': 'Magic Corner', 'type': 'fixed', 'quantity': 1, 'unit_price': 9000}]}]
c.post('/projects/new', data={'customer_name': 'Plywood Test', 'mobile': '9000000555', 'plywood': '18mm BWP',
                              'rooms_data': json.dumps(rooms), 'discount_type': 'none', 'discount_value': '0'})
expect = 50 * (LAM + 150) + 12 * ACR + 8 * GLASS + 9000
with app.app_context():
    p = Project.query.options(undefer(Project.plywood)).order_by(Project.id.desc()).first()
    pid = p.id
    items = {i.name: i for i in Item.query.options(undefer(Item.plywood)).join(Item.room).filter_by(project_id=pid)}
    ok('quotation saved on its plywood; item override kept; total = 50×(rate+150) + 12×acrylic + 8×glass + fitting',
       p.plywood == '18mm BWP' and items['Shutters'].plywood == '18mm 8*4' and items['Base Cabinet'].plywood is None
       and round(p.grand_total, 2) == round(expect, 2))
    ok('glass keeps no plywood (not priced on plywood)', items['Back Glass'].plywood is None and
       plywood.item_key(items['Back Glass'], '18mm BWP') == 'Glass|')
t = c.get(f'/projects/{pid}').text
ok('quotation page: plywood shown, lines named with their plywood, total right',
   'Plywood: <strong>18mm BWP</strong>' in t and 'Laminates – Box Work · 18mm BWP' in t
   and 'Acrylic – Box Work · 18mm 8*4' in t and money(expect) in t and '>18mm 8*4</span>' in t)
full = pdftext(f'/projects/{pid}/pdf')
ok('Full Quotation PDF: priced with plywood, both plywoods named on their lines (no separate Plywood Used list), same total',
   'Plywood Used' not in full and '18mm BWP' in full and '18mm 8*4' in full and money(expect) in full)
cust = pdftext(f'/projects/{pid}/pdf/customer')
ok('Initial Quotation PDF: same total, plywood lines', money(expect) in cust and '18mm BWP' in cust)
wa = c.get(f'/projects/{pid}/whatsapp').headers.get('Location', '')
from urllib.parse import unquote
ok('WhatsApp summary names the plywood and the right total', 'Plywood: 18mm BWP' in unquote(wa) and f'{expect:,.2f}' in unquote(wa))
with app.app_context():
    snap = json.loads(QuoteRevision.query.filter_by(project_id=pid).first().snapshot)
ok('revision snapshot records the plywood and the item override', snap.get('plywood_choice') == '18mm BWP'
   and any(i.get('plywood') == '18mm 8*4' for i in snap['rooms'][0]['items']) and round(snap['total'], 2) == round(expect, 2))
s = c.get(f'/projects/{pid}/edit').text
ok('edit form: plywood radio pre-selected, live prices get the plywood keys',
   'name="plywood" value="18mm BWP" id="ply_' in s and re.search(r'value="18mm BWP" id="ply_\d+"\s+checked', s)
   and '"Laminates|Box Work|18mm BWP"' in s and 'window.KI_PLYWOOD' in s)

# ── Change the quotation to the default plywood: price drops, revision says so ──
c.post(f'/projects/{pid}/edit', data={'customer_name': 'Plywood Test', 'mobile': '9000000555', 'plywood': '18mm 8*4',
       'rooms_data': json.dumps(rooms), 'discount_type': 'none', 'discount_value': '0'})
expect2 = 50 * LAM + 12 * ACR + 8 * GLASS + 9000
with app.app_context():
    p = db.session.get(Project, pid)
    revs = QuoteRevision.query.filter_by(project_id=pid).order_by(QuoteRevision.number).all()
    ok('switch to the default plywood: total drops by 50×150', round(p.grand_total, 2) == round(expect2, 2)
       and round(expect - expect2, 2) == 7500)
ok('revision lists the plywood change', 'Plywood 18mm BWP → 18mm 8*4' in c.get(f'/projects/{pid}').text)
c.post(f'/projects/{pid}/revisions/1/restore')
with app.app_context():
    p = Project.query.options(undefer(Project.plywood)).get(pid)
    ok('restoring revision 1 brings back its plywood and price', p.plywood == '18mm BWP' and round(p.grand_total, 2) == round(expect, 2))

# ── Profit: plywood costs follow the price difference unless set ──
with app.app_context():
    for key, cost in (('Laminates|Box Work', 500), ('Acrylic|Box Work', 700), ('Glass|', 250)):
        row = CostRate.query.filter_by(kind='material', name=key).first()
        if row:
            row.cost = cost
        else:
            db.session.add(CostRate(kind='material', name=key, cost=cost))
    row = CostRate.query.filter_by(kind='fitting', name='Magic Corner').first()
    if row:
        row.cost = 6000
    else:
        db.session.add(CostRate(kind='fitting', name='Magic Corner', cost=6000))
    db.session.commit()
    pr = billing.profit(db.session.get(Project, pid), invoice=None)
    ok('profit: BWP costs the material cost + 150 (same as the price difference) by default',
       round(pr['cost'], 2) == round(50 * 650 + 12 * 700 + 8 * 250 + 6000, 2))
page = c.get('/admin/costs').text
costs_form = {m.group(1): m.group(2) for m in re.finditer(r'<input[^>]*name="([a-z]_?\w*)"[^>]*value="([^"]*)"', page)}
costs_form.pop('csrf_token', None)
costs_form[f'pc_{opts()["18mm BWP"].id}'] = '100'
c.post('/admin/costs', data=costs_form)
with app.app_context():
    pr = billing.profit(db.session.get(Project, pid), invoice=None)
    ok('profit: with "costs you extra ₹100", BWP costs material + 100', round(pr['cost'], 2) == round(50 * 600 + 12 * 700 + 8 * 250 + 6000, 2))
ok('Costs page lists plywood extra costs', 'It costs you extra' in c.get('/admin/costs').text)

# ── Changing the default keeps every price ──
o = opts()
form = {'plywood_submit': '1', 'ply_default': str(o['18mm BWP'].id)}
for name, row in o.items():
    form[f'ply_name_{row.id}'] = name
    form[f'ply_adj_{row.id}'] = f'{row.adjustment:g}'
    form[f'ply_active_{row.id}'] = '1'
r = c.post('/admin/rates', data=form, follow_redirects=True)
o = opts()
with app.app_context():
    c.get(f'/projects/{pid}/edit')
c.post(f'/projects/{pid}/edit', data={'customer_name': 'Plywood Test', 'mobile': '9000000555', 'plywood': '18mm BWP',
       'rooms_data': c.get(f'/projects/{pid}/edit').text.split('id="existing-rooms-data"', 1)[1].split('>', 1)[1].split('</script>', 1)[0],
       'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    p = db.session.get(Project, pid)
    pr = billing.profit(p, invoice=None)
ok('new default: it becomes ₹0, others keep their difference to it', o['18mm BWP'].is_default and o['18mm BWP'].adjustment == 0
   and o['18mm 8*4'].adjustment == -150 and o['12mm 8*4'].adjustment == -350)
ok('…material rates move so every plywood keeps its price; glass untouched',
   rate('Laminates', 'Box Work') == LAM + 150 and rate('Glass', '') == GLASS and 'every quotation keeps the same price' in r.text)
ok('…and the quotation total and its cost are exactly the same', round(p.grand_total, 2) == round(expect, 2)
   and round(pr['cost'], 2) == round(50 * 600 + 12 * 700 + 8 * 250 + 6000, 2))
with app.app_context():
    revs_after = QuoteRevision.query.filter_by(project_id=pid).count()
ok('…so saving it unchanged adds no revision', revs_after == len(revs) + 1)

# ── Hide, delete, rename ──
o = opts()
form = {'plywood_submit': '1', 'ply_default': str(o['18mm BWP'].id), 'ply_delete': [str(o['18mm 8*4'].id)]}
for name, row in o.items():
    form[f'ply_name_{row.id}'] = name; form[f'ply_adj_{row.id}'] = f'{row.adjustment:g}'; form[f'ply_active_{row.id}'] = '1'
r = c.post('/admin/rates', data=form, follow_redirects=True)
ok('a plywood used on quotations can\'t be deleted', 'can&#39;t be deleted' in r.text and '18mm 8*4' in opts())
form['ply_delete'] = [str(o['6mm Back Panel'].id)]
c.post('/admin/rates', data=form)
ok('an unused one can', '6mm Back Panel' not in opts())
o = opts()
form = {'plywood_submit': '1', 'ply_default': str(o['18mm BWP'].id)}
for name, row in o.items():
    form[f'ply_name_{row.id}'] = '18mm BWP Marine' if name == '18mm BWP' else name
    form[f'ply_adj_{row.id}'] = f'{row.adjustment:g}'
    if name != '12mm 8*4':
        form[f'ply_active_{row.id}'] = '1'
c.post('/admin/rates', data=form)
with app.app_context():
    p = Project.query.options(undefer(Project.plywood)).get(pid)
    ok('rename: quotations follow', p.plywood == '18mm BWP Marine' and round(p.grand_total, 2) == round(expect, 2))
f = c.get('/projects/new').text
ok('hidden plywood isn\'t offered on new quotations', 'value="12mm 8*4"' not in f.split('name="plywood"', 1)[1].split('</div>', 1)[0]
   and 'value="18mm BWP Marine"' in f)

# ── Staff can use it too; no admin links ──
s = staff.get('/projects/new').text
ok('staff see the plywood choice but no Admin → Rates link', 'name="plywood"' in s and 'admin/rates' not in s.split('Plywood', 1)[1][:600])

# ── Before the database update: nothing breaks, prices as before ──
with app.app_context():
    db.session.execute(text('DROP TABLE plywood_options'))
    for tbl in ('items', 'projects', 'materials'):
        col = 'uses_plywood' if tbl == 'materials' else 'plywood'
        db.session.execute(text(f'ALTER TABLE {tbl} DROP COLUMN {col}'))
    db.session.commit()
plywood._ready_forever.clear()
c2 = app.test_client(); c2.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
f = c2.get('/projects/new')
ok('before the update: form works with the old plywood list', f.status_code == 200 and 'name="plywood_thickness"' in f.text
   and 'name="plywood"' not in f.text)
c2.post('/projects/new', data={'customer_name': 'Pre Ply', 'mobile': '9000000556', 'plywood_thickness': '18mm 8*4',
        'rooms_data': json.dumps([{'name': 'Hall', 'items': [{'name': 'TV', 'length': 8, 'width': 6,
                                                               'wood_type': 'Laminates', 'work_type': 'Box Work', 'plywood': 'x'}]}]),
        'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    pre = db.session.execute(text('select id from projects order by id desc limit 1')).scalar()
    pre_p = db.session.get(Project, pre)
    ok('before the update: saving works, priced at the plain rate', pre_p.customer_name == 'Pre Ply'
       and round(pre_p.grand_total, 2) == round(48 * rate('Laminates', 'Box Work'), 2))
ok('before the update: quotation page, PDFs, rates page work', c2.get(f'/projects/{pre}').status_code == 200
   and c2.get(f'/projects/{pre}/pdf').status_code == 200 and c2.get(f'/projects/{pre}/pdf/customer').status_code == 200
   and c2.get('/admin/rates').status_code == 200 and c2.get('/admin/costs').status_code in (200, 302)
   and c2.get(f'/projects/{pre}/edit').status_code == 200)
