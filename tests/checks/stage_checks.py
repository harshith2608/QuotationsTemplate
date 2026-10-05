import re
from app import create_app, db
from app.models import Project, ProjectStageChange, User
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})

with app.app_context():
    stages = {p.customer_name: p.stage for p in Project.query.all()}
    ok(f'demo stages seeded {stages}', stages == {'Priya Example': 'confirmed', 'Rahul Sample': 'ongoing',
       'Meera Test': 'pending', 'Arjun Placeholder': 'on_hold', 'Kavya Demo': 'completed'})
    ok('demo history rows', ProjectStageChange.query.count() == 8)

t = c.get('/projects').text
ok('filter pills with counts', re.search(r'All <span class="count">5', t) and re.search(r'Confirmed\s*<span class="count">1', t))
ok('stage column + menus', '<th>Stage</th>' in t and t.count('Move to…') == 10)  # desktop + mobile per row
t = c.get('/projects?stage=ongoing').text
ok('filter by stage', 'Rahul Sample' in t and 'Priya Example' not in t)
t = c.get('/projects?stage=cancelled').text
ok('empty filtered state', 'No quotations are "Cancelled" right now.' in t)
ok('bogus stage ignored', 'Priya Example' in c.get('/projects?stage=nope').text)

# Quick change from the list, returning to the filtered list
r = c.post('/projects/3/stage', data={'stage': 'confirmed', 'next': '/projects?stage=pending'})
ok('quick change redirects back to list', r.status_code == 302 and r.headers['Location'].endswith('/projects?stage=pending'))
r = c.post('/projects/3/stage', data={'stage': 'ongoing', 'note': 'Material ordered'}, follow_redirects=True)
ok('change from view page + flash', 'moved to &#34;Ongoing&#34;' in r.text or 'moved to "Ongoing"' in r.text)
with app.app_context():
    p = db.session.get(Project, 3)
    last = p.stage_changes.first()
    ok('history recorded with note & user', p.stage == 'ongoing' and last.from_stage == 'confirmed'
       and last.note == 'Material ordered' and last.user.username == 'demo-admin' and p.stage_changed_at is not None)
    n = p.stage_changes.count()
c.post('/projects/3/stage', data={'stage': 'ongoing'})
c.post('/projects/3/stage', data={'stage': 'hacked'})
with app.app_context():
    ok('same/invalid stage → no history row', db.session.get(Project, 3).stage_changes.count() == n
       and db.session.get(Project, 3).stage == 'ongoing')
r = c.post('/projects/3/stage', data={'stage': 'completed', 'next': '//evil.example.com/x'})
ok('open redirect blocked', r.headers['Location'].endswith('/projects/3'))

# View page: stepper, history, off-path (on hold) display
v = c.get('/projects/4').text
ok('view: stepper + on-hold state + history', 'ki-stepper is-off' in v and 'Work is paused.' in v
   and 'Customer travelling, resume next month' in v and v.count('ki-step done') == 1 and 'ki-step current' in v)
v = c.get('/projects/5').text
ok('view: completed shows all steps done', v.count('ki-step done') == 3 and 'ki-step current' in v)

# Dashboard pipeline
d = c.get('/admin/dashboard').text
ok('dashboard pipeline', 'Quotation Pipeline' in d and '/projects?stage=on_hold' in d)

# Permissions
e = app.test_client(); e.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
ok('staff can change own quotation', e.post('/projects/1/stage', data={'stage': 'ongoing'}).status_code == 302)
ok('staff blocked on quotation without access', e.post('/projects/2/stage', data={'stage': 'cancelled'}).status_code == 403)
ok('staff list only shows own counts', re.search(r'All <span class="count">3', e.get('/projects').text) is not None)
with app.app_context():
    d = Project(customer_name='Draft X', mobile='1', created_by=User.query.first().id, status='draft')
    db.session.add(d); db.session.commit(); did = d.id
ok('draft cannot change stage', c.post(f'/projects/{did}/stage', data={'stage': 'confirmed'}).status_code == 403)
t = c.get('/projects').text
ok('draft shows Draft badge, excluded from stage counts', 'bi-pencil-square me-1"></i>Draft' in t
   and re.search(r'All <span class="count">6', t))

# Delete cascades history
with app.app_context():
    before = ProjectStageChange.query.filter_by(project_id=5).count()
    db.session.delete(db.session.get(Project, 5)); db.session.commit()
    ok(f'delete removes stage history ({before} rows)', before > 0 and ProjectStageChange.query.filter_by(project_id=5).count() == 0)
