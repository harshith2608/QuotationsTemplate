"""Other companies (app/profiles.py): off by default; the console sets how many a business may add; a quotation from
another company prints that company's name, contact, GSTIN and logo on its PDF, link and invoice, while the app keeps
the main company; name and GSTIN lock once saved; a company in use can't be deleted; turning it off keeps quotations."""
import io, json
from pypdf import PdfReader
from PIL import Image
from app import create_app, db, profiles
from app.models import AppSetting, Project, QuoteShare
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
pdftext = lambda u: '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages)


def png(color):
    out = io.BytesIO(); Image.new('RGB', (120, 60), color).save(out, format='PNG'); out.seek(0); return out


with app.app_context():
    main_name = AppSetting.get('company_name', '') or 'Your Company Name'
    AppSetting.set('company_name', main_name); db.session.commit()

c.post('/projects/new', data={'customer_name': 'Profile Test', 'mobile': '9000000555', 'discount_type': 'none',
                              'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Hall', 'items': [
                                  {'name': 'TV Unit', 'length': 10, 'width': 5, 'wood_type': 'Laminates', 'work_type': 'Box Work'}]}])})
with app.app_context():
    pid = Project.query.order_by(Project.id.desc()).first().id

# ── Off by default ──
ok('off by default: no menu item, no page, no picker', 'Other companies' not in c.get('/projects').text
   and c.get('/admin/companies').status_code == 404 and 'companyPicker' not in c.get(f'/projects/{pid}').text)

# ── The operator allows 1 ──
with app.app_context():
    profiles.set_limit(1); db.session.commit()
ok('on: in the admin menu', 'Other companies' in c.get('/projects').text)
ok('staff can\'t open it', staff.get('/admin/companies').status_code == 403)
r = c.post('/admin/companies', data={'action': 'add', 'name': main_name}, follow_redirects=True)
ok('the main company\'s name is refused', 'already have a company' in r.text)
r = c.post('/admin/companies', data={'action': 'add', 'name': 'Sister Concern', 'gstin': 'BADGSTIN'}, follow_redirects=True)
ok('a wrong GSTIN is refused', "doesn&#39;t look like a valid GSTIN" in r.text or "doesn't look like a valid GSTIN" in r.text)
r = c.post('/admin/companies', data={'action': 'add', 'name': 'Sister Concern', 'gstin': '29ABCDE1234F1Z5',
                                     'phone': '9111122222', 'email': 'hello@sister.example', 'address': '12 MG Road',
                                     'tagline': 'Modular Kitchens', 'logo': (png('red'), 'logo.png'), 'confirm_logo': '1'},
           content_type='multipart/form-data', follow_redirects=True)
with app.app_context():
    rows = profiles.all_profiles()
ok('a company added with its logo', len(rows) == 1 and rows[0]['name'] == 'Sister Concern' and rows[0]['logo_version'])
spid = rows[0]['id']
r = c.post('/admin/companies', data={'action': 'add', 'name': 'Third Firm'}, follow_redirects=True)
with app.app_context():
    ok('no more than the limit', len(profiles.all_profiles()) == 1 and 'up to 1' in r.text)
c.post('/admin/companies', data={'action': 'save', 'id': spid, 'name': 'Renamed', 'gstin': '', 'phone': '9333344444',
                                 'address': '12 MG Road', 'upi_id': 'sister@upi', 'account_name': 'Sister Concern LLP',
                                 'account_number': '99990000111', 'ifsc_code': 'hdfc0001234'})
with app.app_context():
    p = profiles.get(spid)
ok('its account number is stored encrypted', '99990000111' not in json.dumps(p) and profiles.payment_details(p)['ifsc_code'] == 'HDFC0001234')
ok('name and GSTIN locked once saved; phone can change', p['name'] == 'Sister Concern' and p['gstin'] == '29ABCDE1234F1Z5'
   and p['phone'] == '9333344444')
ok('its logo is served', c.get(f'/brand/logo.png?p={spid}').status_code == 200)

# ── A quotation from it ──
view = c.get(f'/projects/{pid}').text
ok('the picker on the quotation, main company chosen', 'companyPicker' in view and 'Sister Concern' in view)
c.post(f'/projects/{pid}/company', data={'profile': spid})
view = c.get(f'/projects/{pid}').text
ok('the quotation is now from it; the app header still shows the main company',
   f'value="{spid}" selected' in view and f'{main_name}\n    </a>' in view.replace('</i>', '').replace('\r', '') or
   (f'value="{spid}" selected' in view and 'ki-navbar' in view and main_name in view.split('ki-navbar')[1][:2000]))
text_ = pdftext(f'/projects/{pid}/pdf')
ok('its PDF: the other company\'s name, phone and GSTIN, not the main one',
   'Sister Concern' in text_ and '9333344444' in text_ and '29ABCDE1234F1Z5' in text_ and main_name not in text_)
ok('…and its own payment details', 'sister@upi' in text_ and '99990000111' in text_ and 'demo-interiors@example' not in text_)
c.post(f'/projects/{pid}/share')
with app.app_context():
    token = QuoteShare.query.filter_by(project_id=pid, active=True).one().token
anon = app.test_client()
link = anon.get(f'/q/{token}').text
ok('its link shows the other company and its logo', 'Sister Concern' in link and f'p={spid}' in link)
ok('the link\'s PDF too', 'Sister Concern' in '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(anon.get(f'/q/{token}/pdf').data)).pages))
wa = c.get(f'/projects/{pid}/whatsapp', follow_redirects=False)
ok('WhatsApp text names it', 'Sister' in (wa.headers.get('Location') or '') + wa.get_data(as_text=True))
other = c.get('/projects').text
ok('other pages stay the main company', 'Sister Concern' not in other)
with app.app_context():
    ok('the main payment details are untouched', AppSetting.get('upi_id') == 'demo-interiors@example')

# ── Invoice from it ──
c.post(f'/projects/{pid}/stage', data={'stage': 'confirmed'})
r = c.post(f'/projects/{pid}/invoice', data={'gst_rate': '18', 'prices': 'exclusive', 'place_code': '29'}, follow_redirects=True)
with app.app_context():
    from app.models import Invoice
    inv = Invoice.query.filter_by(project_id=pid).first()
    seller = json.loads(__import__('app.billing', fromlist=['x']).invoice_data(inv)['seller'] and json.dumps(
        __import__('app.billing', fromlist=['x']).invoice_data(inv)['seller'])) if inv else {}
ok('the invoice is from the other company, with its GSTIN', seller.get('name') == 'Sister Concern'
   and seller.get('gstin') == '29ABCDE1234F1Z5')
c.post(f'/projects/{pid}/company', data={'profile': 0})
with app.app_context():
    ok('with an invoice, the company can\'t be changed', profiles.for_project(pid)['id'] == spid)

r = c.post('/admin/companies', data={'action': 'delete', 'id': spid}, follow_redirects=True)
with app.app_context():
    ok('a company with quotations can\'t be deleted', profiles.get(spid) is not None)

# ── Turned off: quotations keep it, the menu goes ──
with app.app_context():
    profiles.set_limit(0); db.session.commit()
ok('off again: no menu item', 'Other companies' not in c.get('/projects').text)
ok('…the quotation keeps its company', 'Sister Concern' in pdftext(f'/projects/{pid}/pdf'))
