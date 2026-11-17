"""Rates for employees (app/rate_access.py): an employee doesn't see rates or line amounts (screen, form, PDF, link,
WhatsApp) unless the admin ticks "Can see rates" on the Users page; they can ask for one quotation's rates, the admin
gets a notification and approves on the Users page, and then only that quotation shows them its rates."""
import io, re, urllib.parse
from pypdf import PdfReader
from app import create_app, db, rate_access, layout
from app.models import AppSetting, Project, ProjectAccess, User, Notification

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
admin, staff = app.test_client(), app.test_client()
admin.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
pdftext = lambda cl, u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(cl.get(u).data)).pages))

with app.app_context():
    AppSetting.set(layout.LAYOUT_KEY, layout.LAYOUT_BOQ); db.session.commit()   # the layout with a Rate column
    emp = User.query.filter_by(username='demo-staff').first()
    mine = [a.project_id for a in ProjectAccess.query.filter_by(user_id=emp.id).all()]
    quotes = [p for p in Project.query.filter(Project.id.in_(mine), Project.status != 'draft').all() if p.final_total > 0]
    pid, other = quotes[0].id, (quotes[1].id if len(quotes) > 1 else None)
    emp_id = emp.id
    ok('employees are restricted by default; the admin always sees rates',
       not rate_access.can_see(emp, pid) and rate_access.can_see(User.query.filter_by(username='demo-admin').first()))

v = staff.get(f'/projects/{pid}').text
ok('quotation page: marked to hide rates (body class) with the ask button', 'ki-no-rates' in v and 'Ask admin for rates' in v)
ok('the admin sees it plainly', 'ki-no-rates' not in admin.get(f'/projects/{pid}').text)
ok('the form is told to hide rates', 'noRates:     true' in staff.get(f'/projects/{pid}/edit').text
   and 'noRates:     false' in admin.get(f'/projects/{pid}/edit').text)
full_admin = pdftext(admin, f'/projects/{pid}/pdf/customer')
full_staff = pdftext(staff, f'/projects/{pid}/pdf/customer')
ok("the employee's PDF has no Rate / Amount columns (the admin's has)", 'Rate' in full_admin and 'Rate' not in full_staff)
ok("the employee's Full Quotation is the customer PDF without rates", 'Rate' not in pdftext(staff, f'/projects/{pid}/pdf'))

users = admin.get('/admin/users').text
ok('Users page: a Can see rates switch for the employee', 'Can see rates' in users and f'/admin/users/{emp_id}/rates' in users)

# ask → notification → approve → only that quotation
r = staff.post(f'/projects/{pid}/ask-rates')
with app.app_context():
    req = rate_access.pending_for(pid, emp_id)
    ok('asking makes a request and notifies the admin', req is not None
       and Notification.query.filter(Notification.project_id == pid).count() > 0)
    req_id = req['id']
ok('the button then says the rates were asked for', 'Rates asked for' in staff.get(f'/projects/{pid}').text)
staff.post(f'/projects/{pid}/ask-rates')
with app.app_context():
    ok('asking twice keeps one request', len([x for x in rate_access.requests('pending') if x['project_id'] == pid]) == 1)
ok('the request is on the Users page with Approve', 'Asking to see rates' in admin.get('/admin/users').text)
ok('an employee cannot approve it', staff.post(f'/admin/rate-requests/{req_id}', data={'approve': '1'}).status_code == 403)
admin.post(f'/admin/rate-requests/{req_id}', data={'approve': '1'})
v = staff.get(f'/projects/{pid}').text
ok('approved: that quotation shows the rates', 'ki-no-rates' not in v and 'Rate' in pdftext(staff, f'/projects/{pid}/pdf/customer'))
if other:
    ok('other quotations still hide them', 'ki-no-rates' in staff.get(f'/projects/{other}').text)

# the customer's link follows its creator: made while hidden, shows rates once allowed
if other:
    with app.app_context():
        from app.models import QuoteShare
        QuoteShare.query.filter_by(project_id=other).update({'active': False}); db.session.commit()   # (the demo's own)
    staff.post(f'/projects/{other}/share')
    with app.app_context():
        from app import share
        tok = share._active_share(db.session.get(Project, other)).token
    cust = app.test_client()
    page = cust.get(f'/q/{tok}').text
    ok("the link an employee made leaves the rates out (page and its PDF)", '× ₹900' not in page and '₹900' not in page
       and 'Rate' not in pdftext(cust, f'/q/{tok}/pdf'))
    with app.app_context():
        rate_access.set_allowed(emp_id, True); db.session.commit()
    ok('... and shows them once that employee may see rates', 'Rate' in pdftext(cust, f'/q/{tok}/pdf'))
    with app.app_context():
        rate_access.set_allowed(emp_id, False); db.session.commit()
    wa = urllib.parse.unquote(staff.get(f'/projects/{other}/whatsapp').headers.get('Location', ''))
    ok('WhatsApp text from the employee: no per-line amounts (room totals)', ' x Rs.' not in wa and ' × ₹' not in wa)

admin.post(f'/admin/users/{emp_id}/rates', data={'on': '1'})
with app.app_context():
    ok('Can see rates ticked: every quotation', rate_access.allowed_everywhere(db.session.get(User, emp_id)))
ok('... and the page shows them', 'ki-no-rates' not in staff.get(f'/projects/{other or pid}').text)
admin.post(f'/admin/users/{emp_id}/rates', data={'on': '0'})
with app.app_context():
    ok('unticked again', not rate_access.allowed_everywhere(db.session.get(User, emp_id)))
