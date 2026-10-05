import re
from sqlalchemy import event
from app import create_app, db
from app.models import Project, User
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)

with app.app_context():
    priya = Project.query.filter(Project.customer_name.like('Priya%')).first()
    priya_final, priya_gross = priya.final_total, priya.grand_total
    uid = User.query.filter_by(username='demo-admin').first().id
    for gt, dt, dv in [(1000, 'fixed', 5000), (1000, 'percentage', 150), (1000, 'percentage', None),
                       (500, 'none', 99), (800, 'bogus', 10)]:
        db.session.add(Project(customer_name='Edge', mobile='0', created_by=uid, grand_total=gt,
                               discount_type=dt, discount_value=dv, status='draft'))
    db.session.commit()
    rows = db.session.query(Project, Project.final_total_sql()).all()
    bad = [(p.id, p.final_total, sql) for p, sql in rows if abs(p.final_total - sql) > 0.01]
    ok(f'SQL final total matches Python for all {len(rows)} projects (incl. edge discounts) {bad}', not bad)
    py_sum = round(sum(p.final_total for p, _ in rows), 2)

c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
m = re.search(r'ki-kpi-value">&#8377;([\d,]+)', c.get('/admin/dashboard').text)
ok('dashboard KPI uses discounted totals', m and m.group(1) == f'{py_sum:,.0f}')
l = c.get('/projects').text
ok('list shows discounted total, not pre-discount', f'{priya_final:,.2f}' in l and f'{priya_gross:,.2f}' not in l)

# Query budget: pages must not issue one query per room/item (N+1)
stmts = []
with app.app_context():
    event.listen(db.engine, 'before_cursor_execute', lambda conn, cur, st, *a: stmts.append(st))
for url, budget in [(f'/projects/{priya.id}', 15), ('/projects', 15), ('/admin/dashboard', 20),
                    (f'/projects/{priya.id}/edit', 20)]:
    stmts.clear(); r = c.get(url)
    ok(f'{url}: {len(stmts)} queries (budget {budget})', r.status_code == 200 and len(stmts) <= budget)
