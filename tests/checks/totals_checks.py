import re
from sqlalchemy import event
from app import create_app, db
from app.models import Project, User
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)

with app.app_context():
    priya = next(p for p in Project.query.all() if p.customer_name.startswith('Priya'))
    priya_final, priya_gross = priya.final_total, priya.grand_total
    uid = User.query.filter_by(username='demo-admin').first().id
    for gt, dt, dv in [(1000, 'fixed', 5000), (1000, 'percentage', 150), (1000, 'percentage', None),
                       (500, 'none', 99), (800, 'bogus', 10)]:
        db.session.add(Project(customer_name='Edge', mobile='0', created_by=uid, grand_total=gt,
                               discount_type=dt, discount_value=dv, status='draft'))
    db.session.commit()
    rows = Project.query.all()
    expect = {1000: {'fixed': 0, 'percentage': 0}, 500: {'none': 500}, 800: {'bogus': 800}}
    edge = [(p.grand_total, p.discount_type, p.discount_value, p.final_total) for p in rows if p.customer_name == 'Edge']
    ok(f'edge discounts: over-discount floors at 0, missing/unknown discount ignored {edge}',
       sorted(e[3] for e in edge) == [0.0, 0.0, 500.0, 800.0, 1000.0])
    py_sum = round(sum(p.final_total for p in rows), 2)

c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
m = re.search(r'ki-kpi-value">&#8377;([\d,]+)', c.get('/admin/dashboard').text)
ok('dashboard KPI uses discounted totals', m and m.group(1) == f'{py_sum:,.0f}')
l = c.get('/projects').text
ok('list shows discounted total, not pre-discount', f'{priya_final:,.2f}' in l and f'{priya_gross:,.2f}' not in l)

# Query budget: pages must not issue one query per room/item (N+1)
stmts = []
with app.app_context():
    event.listen(db.engine, 'before_cursor_execute', lambda conn, cur, st, *a: stmts.append(st))
# (the quotation page also loads its invoice, revisions, approval link, reminders and costs: a fixed few more)
for url, budget in [(f'/projects/{priya.id}', 22), ('/projects', 15), ('/admin/dashboard', 20),
                    (f'/projects/{priya.id}/edit', 20)]:
    stmts.clear(); r = c.get(url)
    ok(f'{url}: {len(stmts)} queries (budget {budget})', r.status_code == 200 and len(stmts) <= budget)
