"""Quotation numbers (app/quote_numbers.py): YYYYMMDD + that day's count, in the order made, kept when one is deleted;
shown with the latest revision (2026111801/Rev1) on the Quotations page and the quotation's page; searchable."""
from datetime import datetime, timedelta
from app import create_app, db, quote_numbers as QN
from app.models import Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})

with app.app_context():
    day = datetime(2026, 11, 18, 5, 0)                     # 10:30 India time
    ps = Project.query.filter(Project.status != 'draft').order_by(Project.id).all()[:3]
    for i, p in enumerate(ps):
        p.created_at = day + timedelta(minutes=i)
    db.session.commit()
    ids = [p.id for p in ps]
    maker = ps[1].created_by
    nums = QN.assign()
    ok('numbered by the day, in the order made', [nums[i] for i in ids] == ['2026111801', '2026111802', '2026111803'])
    ok('every saved quotation has a number, all different', len(set(nums.values())) == len(nums)
       == Project.query.filter(Project.status != 'draft').count())
lst = c.get('/projects').text
ok('Quotations page: the number with its latest revision', 'Quotation No.' in lst and '2026111801/Rev' in lst)
ok('the quotation\'s page shows it too', '2026111802/Rev' in c.get(f'/projects/{ids[1]}').text)
ok('search by number', '2026111803/Rev' in c.get('/projects?q=2026111803').text
   and '2026111801/Rev' not in c.get('/projects?q=2026111803').text)
c.post(f'/projects/{ids[1]}/share')                         # (a revision is kept when the link is made)
with app.app_context():
    from app import billing
    p = db.session.get(Project, ids[0])
    billing.record_revision(p, p.creator); p.customer_name = p.customer_name + ' X'; db.session.commit()
    billing.record_revision(p, p.creator); db.session.commit()
    rev = billing.latest_revision_number(p)
ok(f'the latest revision is shown (Rev{rev})', f'2026111801/Rev{rev}' in c.get('/projects').text and rev and rev >= 2)
c.post(f'/projects/{ids[0]}/delete')
with app.app_context():
    n2 = QN.assign()
    newp = Project(customer_name='New One', mobile='9000000999', created_by=maker, created_at=day + timedelta(hours=2))
    db.session.add(newp); db.session.commit()
    n3 = QN.assign()
    new_id = newp.id
ok('deleting one keeps the others\' numbers; the next one that day gets the next count',
   n2.get(ids[1]) == '2026111802' and n2.get(ids[2]) == '2026111803' and n3.get(new_id) == '2026111804')
