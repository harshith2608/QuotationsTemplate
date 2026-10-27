"""Your cost on each line (app/item_costs.py): off by default, turned on per business; typed on the form (admins, and
staff the admin allows), used for the profit before Costs & profit, never printed or kept in a revision; staff not
allowed never see it and keep the costs already typed when they save."""
import json
from app import create_app, db, billing, item_costs
from app.models import Item, ItemRate, Project, Room, User

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
admin = app.test_client(); admin.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})

with app.app_context():
    ok('database ready for costs on lines (items.cost_price)', item_costs.ready())
    ok('off by default', not item_costs.enabled())
    combo = ItemRate.query.filter(ItemRate.work_type != '').first()
    wood, work, rate = combo.wood_type, combo.work_type, combo.rate_per_sqft
    staff_id = User.query.filter_by(username='demo-staff').first().id
ok('off: the form has no Your cost box', 'itemCosts:   null' in admin.get('/projects/new?blank=1').text)


def rooms(cost_wall=None, cost_table=None):
    wall = {'name': 'TV Wall', 'length': 10, 'width': 8, 'wood_type': wood, 'work_type': work}
    table = {'name': 'Coffee Table', 'type': 'fixed', 'quantity': 2, 'unit_price': 9000}
    if cost_wall is not None:
        wall['cost'] = cost_wall
    if cost_table is not None:
        table['cost'] = cost_table
    return json.dumps([{'name': 'Living', 'items': [wall, table]}])


def costs_of(pid):
    with app.app_context():
        return {i.name: i.cost_price for i in Item.query.join(Item.room).filter(Room.project_id == pid)}


def save(client, url, name, rooms_json):
    return client.post(url, data={'customer_name': name, 'mobile': '9000000901', 'discount_type': 'none',
                                  'discount_value': '0', 'rooms_data': rooms_json})


with app.app_context():
    item_costs.set_enabled(True); db.session.commit()
f = admin.get('/projects/new?blank=1').text
ok('on: the admin\'s form has the Your cost box and the profit', '"gstDivisor"' in f and 'id="profit-estimate"' in f)
ok('…but not a staff member\'s (not allowed yet)', 'itemCosts:   null' in staff.get('/projects/new?blank=1').text)

save(admin, '/projects/new', 'Cost Home', rooms(cost_wall='600', cost_table='5,000'))
with app.app_context():
    pid = Project.query.order_by(Project.id.desc()).first().id
c = costs_of(pid)
ok('saved: per sqft on a measured item, per unit on a fitting', c == {'TV Wall': 600.0, 'Coffee Table': 5000.0})
with app.app_context():
    p = db.session.get(Project, pid)
    pr = billing.profit(p)
    ok('profit uses the costs typed on the lines (80 sqft × 600 + 2 × 5,000)', pr and pr['cost'] == 58000 and pr['own'] == 2
       and pr['profit'] == round(80 * rate + 18000 - 58000, 2))
    snap = billing.quotation_snapshot(p)
    ok('never kept in a revision', all('cost' not in i and 'cost_price' not in i for r in snap['rooms'] for i in r['items']))
e = admin.get(f'/projects/{pid}/edit').text
ok('editing brings the costs back for the admin', '"cost": 600.0' in e and '"cost": 5000.0' in e)
ok('Duplicate doesn\'t copy them', '"cost"' not in admin.get(f'/projects/new?from={pid}').text)
v = admin.get(f'/projects/{pid}').text
ok('the quotation page shows the profit, noting the typed costs', 'id="profit"' in v and 'cost typed on the quotation' in v)
share_txt = admin.get(f'/projects/{pid}/whatsapp').text if admin.get(f'/projects/{pid}/whatsapp').status_code == 200 else ''
ok('not in the WhatsApp text', '5,000' not in share_txt and '600' not in share_txt.replace('9000000901', ''))

# Empty box: the line goes back to Costs & profit (none set: no cost)
save(admin, f'/projects/{pid}/edit', 'Cost Home', rooms(cost_wall='', cost_table='4500'))
ok('an emptied box clears the cost', costs_of(pid) == {'TV Wall': None, 'Coffee Table': 4500.0})

# Staff, not allowed: no box, no profit, and saving keeps the admin's costs
save(staff, '/projects/new', 'Staff Home', rooms(cost_wall='999', cost_table='999'))
with app.app_context():
    sid = Project.query.order_by(Project.id.desc()).first().id
ok('staff not allowed: a cost they send is ignored', costs_of(sid) == {'TV Wall': None, 'Coffee Table': None})
save(admin, f'/projects/{sid}/edit', 'Staff Home', rooms(cost_wall='700', cost_table='4000'))
se = staff.get(f'/projects/{sid}/edit').text
ok('…don\'t see the costs on the form', '"cost"' not in se and 'itemCosts:   null' in se)
ok('…nor the profit on the quotation', 'id="profit"' not in staff.get(f'/projects/{sid}').text)
save(staff, f'/projects/{sid}/edit', 'Staff Home', rooms())
ok('…and saving keeps the costs the admin typed', costs_of(sid) == {'TV Wall': 700.0, 'Coffee Table': 4000.0})
ok('only admins choose who sees costs', staff.post('/admin/costs/staff', data={'staff': str(staff_id)}).status_code == 403)

# The admin allows them
cp = admin.get('/admin/costs').text
ok('Costs & profit lists the staff to allow', 'id="line-costs"' in cp and 'Ravi Sample' in cp)
admin.post('/admin/costs/staff', data={'staff': [str(staff_id), '999999']})
with app.app_context():
    ok('allowed: saved (an unknown id is dropped)', item_costs.staff_ids() == {staff_id})
se = staff.get(f'/projects/{sid}/edit').text
ok('allowed staff see the costs and the box', '"cost": 700.0' in se and '"gstDivisor"' in se)
save(staff, f'/projects/{sid}/edit', 'Staff Home', rooms(cost_wall='750', cost_table='4000'))
ok('…change them', costs_of(sid)['TV Wall'] == 750.0)
ok('…and see the profit', 'id="profit"' in staff.get(f'/projects/{sid}').text)
admin.post('/admin/costs/staff', data={})
with app.app_context():
    ok('unticked: only admins again', item_costs.staff_ids() == set())

# Turned off: no box; costs already typed stay in the profit
with app.app_context():
    item_costs.set_enabled(False); db.session.commit()
ok('off: no box on a new quotation', 'itemCosts:   null' in admin.get('/projects/new?blank=1').text)
save(admin, f'/projects/{sid}/edit', 'Staff Home', rooms())
with app.app_context():
    pr = billing.profit(db.session.get(Project, sid))
ok('off: costs already typed are kept and still counted', costs_of(sid)['TV Wall'] == 750.0 and pr and pr['own'] == 2)

# Reports: costs typed on lines count in the profit (no Costs & profit needed); with GST on quotations, won value
# includes GST (it compares with what was collected)
from app import reports, quote_gst
with app.app_context():
    from app.models import CostRate
    CostRate.query.delete()
    p = db.session.get(Project, sid); p.stage = 'confirmed'
    db.session.commit()
    rep = reports.build()
    cur = rep['current']
    exp = billing.profit(db.session.get(Project, sid))
    ok('Reports: the profit counts the costs typed on lines (no Costs & profit set)', rep['has_costs'] and cur['profit_jobs'] >= 1
       and exp and abs(cur['cost'] - exp['cost']) < 0.01 and exp['cost'] > 0)
    won_before = cur['won_value']
    quote_gst.set_gst(True, 18); db.session.commit()
    rep2 = reports.build()
    ok('Reports with GST on quotations: won value includes GST, profit stays without GST', rep2['gst_on']
       and abs(rep2['current']['won_value'] - round(won_before * 1.18, 2)) < 0.05
       and abs(rep2['current']['profit'] - cur['profit']) < 0.01)
r = admin.get('/admin/reports').text
ok('…and the page says so', 'including GST' in r and 'Won work (incl. GST)' in r)
