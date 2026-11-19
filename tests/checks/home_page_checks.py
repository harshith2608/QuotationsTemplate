"""Home page (Settings → Appearance): admins can land on the Dashboard instead of Quotations; employees don't."""
from app import create_app

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
admin, staff = app.test_client(), app.test_client()
login = lambda c, u: c.post('/login', data={'username': u, 'password': 'demo1234'}).headers.get('Location', '')

ok('by default admins land on Quotations', login(admin, 'demo-admin').endswith('/projects'))
ok('the choice is on Settings → Appearance', 'name="home_page"' in admin.get('/admin/settings?tab=appearance').text)
admin.post('/admin/settings', data={'section': 'appearance', 'home_page': 'dashboard'})
ok('chosen: / opens the Dashboard', admin.get('/').headers.get('Location', '').endswith('/admin/dashboard'))
admin.get('/logout')
ok('… and signing in lands there', login(admin, 'demo-admin').endswith('/admin/dashboard'))
ok('… a ?next= link still wins', admin.get('/logout') and admin.post('/login?next=/projects', data={
    'username': 'demo-admin', 'password': 'demo1234'}).headers.get('Location', '').endswith('/projects'))
ok('employees still start on Quotations', login(staff, 'demo-staff').endswith('/projects')
   and staff.get('/').headers.get('Location', '').endswith('/projects'))
ok('the Dashboard opens', admin.get('/admin/dashboard').status_code == 200)
admin.post('/admin/settings', data={'section': 'appearance', 'home_page': ''})
ok('back to Quotations', admin.get('/').headers.get('Location', '').endswith('/projects'))
