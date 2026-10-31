"""The setup guide on a brand-new business (bootstrap: one admin 'owner', no quotations)."""
import os, re
from werkzeug.security import generate_password_hash
from app import create_app, db
from app.models import AppSetting, User
for k in ['DEMO_MODE', 'MARKETING_SITE', 'AI_IMPORT', 'ANTHROPIC_API_KEY']: os.environ.pop(k, None)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)

c = app.test_client()
r = c.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
ok('first sign-in of a new business\'s admin opens the setup guide', r.status_code == 302 and r.headers['Location'].endswith('/admin/setup'))
t = c.get('/admin/setup').text
ok('guide lists the steps, none done, with Start', '0 of 8 done' in t and 'Start: Your company details' in t
   and 'Your rates, materials &amp; plywood' in t and 'Optional, when you need them' in t)
ok('…with starting quotations among the optional steps; no quick way while bring your old quotation is off',
   'Your starting quotations' in t and 'Save as template' in t and 'The quick way' not in t and 'step-import' not in t)
os.environ['AI_IMPORT'], os.environ['ANTHROPIC_API_KEY'] = '1', 'test-key-not-real'
t = c.get('/admin/setup').text
ok('bring your old quotation on: the quick way comes first, not counted among the steps', 'id="step-import"' in t
   and t.index('step-import') < t.index('step-company') and 'Quick way' in t and 'Upload a quotation' in t
   and '0 of 8 done' in t and 'Start: Your company details' in t)
r = c.get('/admin/setup/import/open')
ok('…Open → the upload page, with the guide\'s banner', r.headers['Location'].endswith('/admin/import')
   and 'Setup guide · the quick way' in c.get('/admin/import').text and 'Not now, next step' in c.get('/admin/import').text)
c.post('/admin/setup/stop')
c.get('/logout')
r = c.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
ok('later sign-ins go to the quotations as usual', r.status_code == 302 and r.headers['Location'].endswith('/projects'))
t = c.get('/projects').text
ok('quotations list: "Finish setting up" card, and the guide is in the menu', 'Finish setting up your app' in t
   and '0 of 8 steps done' in t and '/admin/setup">' in t and 'Setup guide' in t)

# Following a step: its page shows the banner; saving the page completes the step
r = c.get('/admin/setup/units/open')
ok('Open a step → its page', r.status_code == 302 and r.headers['Location'].endswith('/admin/settings?tab=units'))
t = c.get('/admin/settings?tab=units').text
ok('banner on the step\'s page while following the guide', 'Setup guide · step 3 of 8' in t and 'Units of measurement' in t
   and 'Done, next step' in t)
ok('no banner on other pages', 'Setup guide · step' not in c.get('/admin/rates').text)
c.get('/admin/setup/costs/open')
ok('optional steps are labelled as such', 'Setup guide · optional step' in c.get('/admin/costs').text)
c.get('/admin/setup/units/open')
c.post('/admin/settings', data={'section': 'units', 'size_unit': 'ft_in', 'area_unit': 'sqft'})
t = c.get('/admin/setup').text
ok('saving the page marks its step done', '1 of 8 done' in t)
r = c.post('/admin/setup/units/done', data={'next': '1'})
ok('"Done, next step" goes to the next step not done yet (company)', r.status_code == 302
   and r.headers['Location'].endswith('/admin/settings?tab=company'))
ok('…with the banner for that step', 'Setup guide · step 1 of 8' in c.get('/admin/settings?tab=company').text)
c.post('/admin/setup/stop')
ok('closing the guide removes the banner', 'Setup guide · step' not in c.get('/admin/settings?tab=company').text)

# Mark done / not done; the app's own signs (UPI saved, a second login, a quotation) count too
c.post('/admin/setup/company/done')
c.post('/admin/setup/logo/done')
ok('mark as done', '3 of 8 done' in c.get('/admin/setup').text)
c.post('/admin/setup/logo/done', data={'undo': '1'})
ok('mark as not done', '2 of 8 done' in c.get('/admin/setup').text)
c.post('/admin/payment-settings', data={'upi_id': 'owner@okbank'})
c.post('/admin/users/new', data={'username': 'rahul', 'password': 'rahul-pass-123', 'confirm_password': 'rahul-pass-123', 'role': 'employee'})
with app.app_context():
    from app.models import Project
    u = User.query.filter_by(username='owner').first()
    db.session.add(Project(customer_name='First Customer', mobile='9000000001', created_by=u.id, grand_total=1000,
                           discount_type='none', discount_value=0, status='complete'))
    db.session.commit()
    from app import quote_templates
    quote_templates.put('2 BHK', [{'name': 'Kitchen', 'items': []}])
    db.session.commit()
t = c.get('/admin/setup').text
ok('done from what the app sees: payments, first quotation (and the optional team and starting quotation steps)',
   '4 of 8 done' in t and re.search(r'id="step-team".*?bi-check-lg', t, re.S) is not None
   and re.search(r'id="step-templates".*?bi-check-lg', t, re.S) is not None)

# Hide / show the card; the guide stays in the menu
c.post('/admin/setup/hide')
t = c.get('/projects').text
ok('Hide removes the card, guide still in the menu', 'Finish setting up your app' not in t and 'Setup guide' in t)
c.post('/admin/setup/hide', data={'show': '1', 'back': 'setup'})
ok('Show it again', 'Finish setting up your app' in c.get('/projects').text)

# Finishing: the last required step → "complete", the card goes
for key in ('logo', 'pricing', 'rates', 'pdf'):
    c.post(f'/admin/setup/{key}/done')
t = c.get('/admin/setup').text
ok('all steps done → setup complete, card gone, guide still reachable', '8 of 8 done' in t and 'Your setup is complete' in t
   and 'Finish setting up your app' not in c.get('/projects').text)

# Staff: no guide
s = app.test_client()
r = s.post('/login', data={'username': 'rahul', 'password': 'rahul-pass-123'})
ok('staff never see the guide', r.headers['Location'].endswith('/projects') and s.get('/admin/setup').status_code == 403
   and 'Finish setting up' not in s.get('/projects').text and 'Setup guide' not in s.get('/projects').text)

# A business already using the app (quotations made) isn't sent to the guide, and gets no card; the menu has it
with app.app_context():
    u = User.query.filter_by(username='owner').first()
    for i in range(3):
        db.session.add(Project(customer_name=f'Customer {i}', mobile='9000000002', created_by=u.id, grand_total=1000,
                               discount_type='none', discount_value=0, status='complete'))
    AppSetting.set('setup_guide', '{}')            # as before the guide existed
    db.session.commit()
e = app.test_client()
r = e.post('/login', data={'username': 'owner', 'password': 'owner-pass-123'})
ok('established business: no redirect to the guide after the update, no card', r.headers['Location'].endswith('/projects')
   and 'Finish setting up your app' not in e.get('/projects').text and e.get('/admin/setup').status_code == 200)
