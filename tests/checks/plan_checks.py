import os, re, html
from datetime import timedelta
from urllib.parse import unquote
from app import create_app, db
from app import plan as P
from app.models import Project, AppSetting
for k in ['DEMO_MODE', 'MARKETING_SITE']: os.environ.pop(k, None)
os.environ['SUPPORT_WHATSAPP'] = '919876543210'
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
runner = app.test_cli_runner()
T = P.today()
admin = app.test_client(); admin.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
anon = app.test_client()
def setplan(plan, start, end):
    with app.app_context():
        P.save_plan(plan, start, end); db.session.commit()
def can_edit(c=admin):
    r = c.post('/projects/1/stage', data={'stage': 'ongoing'})
    with app.app_context():
        changed = db.session.get(Project, 1).stage == 'ongoing'
        p = db.session.get(Project, 1); p.stage = 'confirmed'; db.session.commit()
    return changed

# Unit: date maths
ok('add_length 6m / 1y / month-end clamp', P.add_length(T.replace(day=1), '6m').day == 1
   and str(P.add_length(__import__('datetime').date(2026, 8, 31), '6m')) == '2027-02-28'
   and P.add_length(T, '1y').year == T.year + 1 and P.add_length(T, '7d') == T + timedelta(days=7))

# No plan → unlimited, no banner
t = admin.get('/projects').text
ok('no plan: no banner, editing works', 'ki-plan-banner' not in t and can_edit())

# Trial, 3 days left
setplan('trial', T - timedelta(days=4), T + timedelta(days=3))
t = admin.get('/projects').text
ok('trial: admin sees "Free trial ends in 3 days"', 'Free trial</strong> ends in 3 days' in t and 'Choose a plan' in t)
ok('trial: staff does not see trial reminder', 'ki-plan-banner' not in staff.get('/projects').text)
ok('trial: editing allowed', can_edit())
m = re.search(r'href="(https://wa\.me/919876543210\?text=[^"]+)"', t)
msg = unquote(html.unescape(m.group(1)).split('?text=')[1]) if m else ''
ok('renew WhatsApp message has company, app, plan', 'subscribe after my free trial' in msg and 'Company: Demo Interiors' in msg
   and 'App: http://localhost/' in msg and 'Free trial, ends' in msg and 'Plan I want: 6 months / 12 months' in msg)

# Trial ended yesterday → read-only immediately (no grace for trials)
setplan('trial', T - timedelta(days=8), T - timedelta(days=1))
t = anon.get('/login').text
delete_on = (T - timedelta(days=1) + timedelta(days=30)).strftime('%d %b %Y')
ok('trial ended: read-only banner incl. deletion date on login page', 'Your free trial has ended.' in t and delete_on in t
   and 'permanently deleted and you will no longer have access to this website' in t)
ok('trial ended: changes blocked', not can_edit())
r = admin.get('/projects/new'); r2 = admin.get('/projects/1/edit')
ok('read-only: create/edit pages redirect', r.status_code == 302 and r2.status_code == 302)
r = admin.post('/api/draft', json={'customer_name': 'X', 'mobile': '1'})
ok('read-only: JSON API answers 403', r.status_code == 403 and 'read-only' in r.get_json()['error'])
ok('read-only: viewing + PDFs still work', admin.get('/projects/1').status_code == 200 and admin.get('/projects/1/pdf').status_code == 200
   and admin.get('/projects/1/pdf/customer').mimetype == 'application/pdf')
ok('read-only: staff sees banner + "ask your admin"', 'Ask your admin to subscribe' in staff.get('/projects').text)
ok('read-only: logout still works', staff.get('/logout').status_code == 302)
r = admin.post('/admin/settings', data={'section': 'company', 'company_tagline': 'x'}, follow_redirects=True)
ok('read-only: settings save blocked with message', 'read-only' in r.text)
r = app.test_client().post('/webhook/razorpay', data=b'{}', headers={'Content-Type': 'application/json'})
ok('read-only: Razorpay webhook still reachable (not blocked by plan)', r.status_code == 400)  # 400 = no secret configured, i.e. it ran

# Paid plan, 10 days left → reminder for admin only, full access
setplan('1y', T - timedelta(days=355), T + timedelta(days=10))
t = admin.get('/projects').text
ok('paid: reminder 10 days before', '12-month plan</strong> ends in 10 days' in t and can_edit())
setplan('1y', T - timedelta(days=300), T + timedelta(days=60))
ok('paid: no banner when > 15 days left', 'ki-plan-banner' not in admin.get('/projects').text)

# Paid plan ended 3 days ago → grace: banner for everyone, still editable
setplan('6m', T - timedelta(days=186), T - timedelta(days=3))
t = staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'}, follow_redirects=True).text
ok('grace: everyone sees "keep working until"', 'You can keep working until' in t)
ok('grace: editing still allowed', can_edit())

# Paid plan ended 10 days ago → read-only
setplan('6m', T - timedelta(days=193), T - timedelta(days=10))
ok('paid ended beyond grace: read-only', not can_edit() and 'Your plan has ended.' in admin.get('/projects').text)

# CLI: renewal
out = runner.invoke(args=['plan', 'extend', '1y']).output
with app.app_context():
    st = P.load_status(on=T)
ok('late renewal extends from today → editable again', st.plan == '1y' and st.ends_on == P.add_length(T, '1y') and can_edit())
setplan('1y', T - timedelta(days=360), T + timedelta(days=5))
runner.invoke(args=['plan', 'extend', '1y'])
with app.app_context():
    st = P.load_status(on=T)
ok('on-time renewal extends from current end (no days lost)', st.ends_on == P.add_length(T + timedelta(days=5), '1y'))
setplan('trial', T - timedelta(days=5), T + timedelta(days=2))
runner.invoke(args=['plan', 'extend', '7d'])
with app.app_context():
    st = P.load_status(on=T)
ok('extending a trial by days keeps it a trial', st.plan == 'trial' and st.ends_on == T + timedelta(days=9))
runner.invoke(args=['plan', 'extend', '6m'])
with app.app_context():
    st = P.load_status(on=T)
ok('trial → 6m conversion', st.plan == '6m' and st.ends_on == P.add_length(T + timedelta(days=9), '6m'))
out = runner.invoke(args=['plan', 'set', '--plan', 'trial']).output
ok('plan set --plan trial → 7 days', 'Free trial' in out and P.add_length(T, '7d').strftime('%d %b %Y') in out)
ok('bad length rejected', runner.invoke(args=['plan', 'extend', 'forever']).exit_code != 0)
out = runner.invoke(args=['plan', 'status']).output
ok('plan status prints dates', 'Delete on:' in out and 'Read-only:   no' in out)
ok('settings shows plan badge', 'Free trial</span>' in admin.get('/admin/settings').text)
runner.invoke(args=['plan', 'clear'])
ok('plan clear → unlimited', 'ki-plan-banner' not in admin.get('/projects').text and can_edit())
