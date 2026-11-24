"""The console's Usage page counts (app/activity.py details()), read inside one business's app."""
import json
from app import create_app, db, activity, quote_templates
from app.models import Project, User

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})

with app.app_context():
    before = activity.details()
ok('details() has every column', all(k in before for k in ('users', 'admins', 'staff', 'quotations', 'quotes_7d', 'quotes_30d',
                                                           'drafts', 'won', 'templates', 'links', 'responses', 'invoices',
                                                           'payments', 'saved_lines', 'fittings', 'photos', 'material_lists',
                                                           'last_seen_at')))
ok('users = admins + staff', before['users'] == before['admins'] + before['staff'] and before['admins'] >= 1)

rooms = [{'name': 'Kitchen', 'items': [{'type': 'fixed', 'name': 'Chimney', 'quantity': 1, 'unit_price': 15000}]}]
c.post('/projects/new', data={'customer_name': 'Usage One', 'mobile': '9000000601', 'rooms_data': json.dumps(rooms),
                              'discount_type': 'none', 'discount_value': '0'})
c.post('/api/draft', json={'customer_name': 'Usage Draft', 'mobile': '9000000602', 'rooms_data': rooms})
with app.app_context():
    p = Project.query.filter_by(status='complete').order_by(Project.id.desc()).first()
    p.stage = 'confirmed'; db.session.commit()
    quote_templates._store(quote_templates._load() + [{'id': 'x1', 'name': 'Usage template', 'rooms': []}])
    db.session.commit()
    after = activity.details()
ok('a new quotation counts in all time, 7d and 30d', after['quotations'] == before['quotations'] + 1
   and after['quotes_7d'] == before['quotes_7d'] + 1 and after['quotes_30d'] == before['quotes_30d'] + 1)
ok('a draft counts as a draft, not a quotation', after['drafts'] == before['drafts'] + 1)
ok('Confirmed+ counts the confirmed one', after['won'] == before['won'] + 1)
ok('templates counted', after['templates'] == before['templates'] + 1)
ok('numbers are numbers (or None for a missing table)', all(isinstance(after[k], int) or after[k] is None
                                                           for k in ('links', 'invoices', 'payments', 'photos')))
