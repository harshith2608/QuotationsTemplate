"""Quotation approvals (app/approvals.py): with the console switch on, an employee can look at their quotation's PDF
(marked "Draft – not approved") but downloading the clean PDF and sharing it with the customer wait until they tap
Send for approval and an admin approves; the admin approves, rejects or asks for changes from the notification or
the quotation. Rate requests get Approve / Decline on their notification too."""
import io, json
from pypdf import PdfReader
from app import create_app, db, approvals, rate_access
from app.models import Notification, Project, QuoteShare, User

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
admin, staff, cust = app.test_client(), app.test_client(), app.test_client()
admin.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
ROOMS = [{'name': 'Hall', 'items': [{'name': 'Magic Corner', 'type': 'fixed', 'quantity': 1, 'unit_price': 7500}]}]


def new_quote(client, name):
    client.post('/projects/new', data={'customer_name': name, 'mobile': '9000000333', 'rooms_data': json.dumps(ROOMS),
                                       'discount_type': 'none', 'discount_value': '0'})
    with app.app_context():
        return Project.query.order_by(Project.id.desc()).first().id


def edit(client, pid, name):
    rooms = client.get(f'/projects/{pid}/edit').text.split('id="existing-rooms-data"', 1)[1].split('>', 1)[1].split('</script>', 1)[0]
    return client.post(f'/projects/{pid}/edit', data={'customer_name': name, 'mobile': '9000000333', 'rooms_data': rooms,
                                                      'discount_type': 'none', 'discount_value': '0'})


SHARES = lambda pid: [f'/projects/{pid}/whatsapp']


def draft(client, url):
    """Opens (200), inline, marked Draft on every page."""
    r = client.get(url)
    if r.status_code != 200 or 'attachment' in r.headers.get('Content-Disposition', ''):
        return False
    pages = PdfReader(io.BytesIO(r.data)).pages
    return all('Draft for checking only' in p.extract_text() for p in pages)


def clean(client, url):
    r = client.get(url)
    return r.status_code == 200 and 'Draft for checking only' not in ' '.join(
        p.extract_text() for p in PdfReader(io.BytesIO(r.data)).pages)

# off (the default): nothing waits
off_id = new_quote(staff, 'Approvals Off')
ok('off by default: an employee\'s quotation opens as PDF', staff.get(f'/projects/{off_id}/pdf/customer').status_code == 200
   and 'quote-approval' not in staff.get(f'/projects/{off_id}').text)

staff.post(f'/projects/{off_id}/share')
with app.app_context():
    old_tok = QuoteShare.query.filter_by(project_id=off_id, active=True).first().token
    approvals.set_enabled(True); db.session.commit()

# made before approvals were on: employees can't send it until it's approved; the link already sent keeps working
v = staff.get(f'/projects/{off_id}').text
ok('older employee quotation: not sent, with Send for approval; its PDF opens marked Draft', 'Not sent for approval' in v
   and 'Send for approval' in v and draft(staff, f'/projects/{off_id}/pdf/customer')
   and staff.get(f'/projects/{off_id}/whatsapp').status_code == 302)
ok('… its customer\'s link still works', 'being updated' not in cust.get(f'/q/{old_tok}').text)
v = admin.get(f'/projects/{off_id}').text
ok('… the admin can approve it from the quotation', f'/admin/approvals/{off_id}' in v
   and admin.get(f'/projects/{off_id}/pdf/customer').status_code == 200)
admin.post(f'/admin/approvals/{off_id}', data={'action': 'approve'})
ok('… approved: the employee gets the clean PDF', clean(staff, f'/projects/{off_id}/pdf/customer'))
with app.app_context():
    from app.models import AppSetting
    rows = json.loads(AppSetting.get(approvals.STATE_KEY)); rows.pop(str(off_id)); AppSetting.set(approvals.STATE_KEY, json.dumps(rows))
    db.session.commit()
staff.post(f'/projects/{off_id}/approval/submit')
with app.app_context():
    ok('… or the employee taps Send for approval (the admin is told)', approvals.state(off_id)['status'] == 'pending'
       and Notification.query.filter(Notification.project_id == off_id).count() == 1)

pid = new_quote(staff, 'Approvals Test')
with app.app_context():
    ok('on: an employee\'s new quotation isn\'t sent for approval by itself', approvals.state(pid) is None
       and Notification.query.filter(Notification.project_id == pid).count() == 0)
v = staff.get(f'/projects/{pid}').text
ok('the employee sees Not sent for approval, with the PDF buttons and Send for approval', 'Not sent for approval' in v
   and f'/projects/{pid}/pdf/customer' in v and 'Download &amp; share after approval' in v and 'Send for approval' in v)
ok('… the PDFs open for them to check, marked Draft on every page (also with ?download=1, and a revision\'s)',
   draft(staff, f'/projects/{pid}/pdf') and draft(staff, f'/projects/{pid}/pdf/customer')
   and draft(staff, f'/projects/{pid}/pdf/customer?download=1') and draft(staff, f'/projects/{pid}/revisions/1/pdf'))
ok('WhatsApp, the email and the customer\'s link are refused (back to the quotation)',
   all(staff.get(u).status_code == 302 and f'/projects/{pid}' in staff.get(u).headers['Location'] for u in SHARES(pid))
   and staff.post(f'/projects/{pid}/email', data={'to': 'x@example.com'}).status_code == 302
   and staff.post(f'/projects/{pid}/share').status_code == 302)
with app.app_context():
    ok('… no link was made', QuoteShare.query.filter_by(project_id=pid, active=True).count() == 0)
ok('the admin gets the clean PDF', clean(admin, f'/projects/{pid}/pdf/customer'))
staff.post(f'/projects/{pid}/approval/submit')
with app.app_context():
    ok('Send for approval: it waits', approvals.state(pid)['status'] == 'pending')
    n = Notification.query.filter(Notification.project_id == pid).order_by(Notification.id.desc()).first()
    ok('… and the admin gets a notification', n is not None and 'for approval' in n.title)
ok('… still a draft PDF for the employee while it waits', draft(staff, f'/projects/{pid}/pdf/customer')
   and 'Waiting for approval' in staff.get(f'/projects/{pid}').text)

# from the notification: Approve / Make changes / Reject
notes = admin.get('/admin/notifications').text
ok('the notification has Approve, Make changes and Reject', f'/admin/approvals/{pid}' in notes and 'Make changes' in notes
   and 'Reject' in notes)
page = admin.get(f'/projects/{pid}').text
ok('… and so does the quotation (for the admin)', f'/admin/approvals/{pid}' in page and 'sent this quotation for your approval' in page)
ok('an employee can\'t approve', staff.post(f'/admin/approvals/{pid}', data={'action': 'approve'}).status_code == 403)
r = admin.post(f'/admin/approvals/{pid}', data={'action': 'changes', 'note': ''})
with app.app_context():
    ok('Make changes needs a note', approvals.state(pid)['status'] == 'pending')
admin.post(f'/admin/approvals/{pid}', data={'action': 'changes', 'note': 'Add the loft', 'next': '/admin/notifications'})
v = staff.get(f'/projects/{pid}').text
ok('changes asked: the employee sees the note and can send it again', 'Changes asked' in v and 'Add the loft' in v
   and 'Send for approval again' in v)
ok('… still a draft', draft(staff, f'/projects/{pid}/pdf/customer'))
ok('the Quotations page shows it', 'Changes asked' in staff.get('/projects').text)
edit(staff, pid, 'Approvals Test')
with app.app_context():
    ok('saving the changes doesn\'t send it by itself', approvals.state(pid)['status'] == 'unsent'
       and Notification.query.filter(Notification.project_id == pid).count() == 1)
staff.post(f'/projects/{pid}/approval/submit')
with app.app_context():
    ok('… Send for approval again (a new notification)', approvals.state(pid)['status'] == 'pending'
       and Notification.query.filter(Notification.project_id == pid).count() == 2)
admin.post(f'/admin/approvals/{pid}', data={'action': 'approve'})
ok('approved: the employee can download and send it', clean(staff, f'/projects/{pid}/pdf/customer')
   and staff.get(f'/projects/{pid}/whatsapp').status_code == 302
   and 'wa.me' in staff.get(f'/projects/{pid}/whatsapp').headers.get('Location', ''))
staff.post(f'/projects/{pid}/share')
with app.app_context():
    tok = QuoteShare.query.filter_by(project_id=pid, active=True).first().token
ok('… and make the customer\'s link', cust.get(f'/q/{tok}').status_code == 200 and 'being updated' not in cust.get(f'/q/{tok}').text)
ok('notification shows the outcome', 'Approved' in admin.get('/admin/notifications').text)

# changing an approved quotation: it waits again, and the customer's link holds
edit(staff, pid, 'Approvals Test 2')
with app.app_context():
    ok('an employee\'s change needs approval again', approvals.state(pid)['status'] == 'unsent')
ok('… back to a draft PDF for them', draft(staff, f'/projects/{pid}/pdf/customer'))
ok('the customer\'s link says it\'s being updated (page and PDF)', 'being updated' in cust.get(f'/q/{tok}').text
   and 'being updated' in cust.get(f'/q/{tok}/pdf').text)
admin.post(f'/admin/approvals/{pid}', data={'action': 'reject', 'note': 'Wrong customer'})   # (not sent: the admin can still decide)
v = staff.get(f'/projects/{pid}').text
ok('rejected: shown to the employee with the note', 'Rejected' in v and 'Wrong customer' in v)
staff.post(f'/projects/{pid}/approval/submit')
with app.app_context():
    ok('Send for approval again', approvals.state(pid)['status'] == 'pending')
admin.post(f'/admin/approvals/{pid}', data={'action': 'approve'})
ok('approved again: the link shows it', 'being updated' not in cust.get(f'/q/{tok}').text)

# admins' own quotations don't wait; an admin's change leaves it as it was
mine = new_quote(admin, 'Admin Own')
with app.app_context():
    ok('an admin\'s quotation doesn\'t wait', approvals.state(mine) is None)
edit(admin, pid, 'Approvals Test 3')
with app.app_context():
    ok('an admin changing an approved one keeps it approved', approvals.state(pid)['status'] == 'approved')

# rate requests: Approve / Decline on the notification
with app.app_context():
    emp_id = User.query.filter_by(username='demo-staff').first().id
staff.post(f'/projects/{pid}/ask-rates')
notes = admin.get('/admin/notifications').text
with app.app_context():
    req = rate_access.pending_for(pid, emp_id)
ok('rate request: Approve / Decline on the notification', req is not None and f'/admin/rate-requests/{req["id"]}' in notes)
r = admin.post(f'/admin/rate-requests/{req["id"]}', data={'approve': '1', 'next': '/admin/notifications'})
ok('… approving from there comes back to Notifications', r.headers['Location'].endswith('/admin/notifications'))
with app.app_context():
    ok('… and the employee sees that quotation\'s rates', rate_access.can_see(db.session.get(User, emp_id), pid))
ok('… the notification then shows it approved', 'Rates approved' in admin.get('/admin/notifications').text)

# off again: nothing locked
with app.app_context():
    approvals.set_enabled(False); db.session.commit()
edit(staff, pid, 'Approvals Test 4')
ok('switched off: employees send freely again', staff.get(f'/projects/{pid}/pdf/customer').status_code == 200
   and 'being updated' not in cust.get(f'/q/{tok}').text)
