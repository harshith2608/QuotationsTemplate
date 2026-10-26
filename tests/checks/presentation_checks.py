"""Presentation pages (app/presentation.py): off by default; on, the customer's PDF opens with a title page (the firm,
then "Prepared for" the client) and About us, and ends with Next steps and the thank-you; texts from Settings or a
price list file; an empty About us leaves its page out."""
import io, json, re
from pypdf import PdfReader
from app import create_app, db, presentation, price_list
from app.models import Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pages = lambda u: [re.sub(r'\s+', ' ', p.extract_text()) for p in PdfReader(io.BytesIO(c.get(u).data)).pages]

with app.app_context():
    p = next(x for x in Project.query.filter(Project.status != 'draft').all() if x.final_total > 0)
    pid, cname = p.id, p.customer_name
before = pages(f'/projects/{pid}/pdf/customer')
ok('off by default: the PDF starts with the quotation, no title / About / Next steps pages',
   'CUSTOMER QUOTATION' in before[0] and not any('Next steps' in t or 'Prepared for' in t for t in before)
   and 'id="presentation"' not in c.get('/admin/settings?tab=documents').text)

with app.app_context():
    presentation.set_enabled(True); db.session.commit()
s = c.get('/admin/settings?tab=documents').text
ok('on: Settings → Quotation PDFs has About us and Next steps', 'id="presentation"' in s and 'name="about_us"' in s
   and 'name="next_steps"' in s)
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms',
                                'about_us': 'We design homes in Pune since 2012.\n\n- 300+ homes\n- Own factory',
                                'next_steps': '1. Confirm the quotation\n2. Site measurement'})
after = pages(f'/projects/{pid}/pdf/customer')
ok('page 1: the firm, then "Prepared for" the client, quotation no. and date', 'Prepared for' in after[0]
   and cname in after[0] and 'Quotation no.' in after[0] and 'Demo Interiors' in after[0])
ok('page 2: About us, with the list', after[1].startswith('About ') and 'since 2012' in after[1] and '300+ homes' in after[1])
ok('page 3: the quotation (client details not repeated)', 'CUSTOMER QUOTATION' in after[2] and 'Customer Details' not in after[2])
ok('last page: Next steps (numbering cleaned) and the thank-you', 'Next steps' in after[-1] and 'Confirm the quotation' in after[-1]
   and '1. 1.' not in after[-1] and 'Thank you for choosing' in after[-1] and 'Thank you for choosing' not in after[-2])
c.post('/admin/settings', data={'section': 'documents', 'initial_layout': 'rooms', 'about_us': '', 'next_steps': ''})
empty = pages(f'/projects/{pid}/pdf/customer')
ok('no About us written: that page is left out; no steps: the usual ones', not any(t.startswith('About ') for t in empty)
   and 'booking advance' in empty[-1] and 'Prepared for' in empty[0] and 'CUSTOMER QUOTATION' in empty[1])
with app.app_context():
    r = price_list.apply(price_list.parse(json.dumps({'options': {'presentation': True},
                                                      'settings': {'about_us': 'From the file.'}}).encode()), replace_settings=True)
    ok('a price list file can turn them on and bring About us', presentation.enabled() and 'presentation pages on'
       in price_list.summary_text(r) and presentation.content()['about'] == ['From the file.'])
    presentation.set_enabled(False); db.session.commit()
ok('off again: back to the usual PDF', len(pages(f'/projects/{pid}/pdf/customer')) == len(before))
