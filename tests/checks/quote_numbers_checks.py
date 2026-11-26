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

# the business's own format (Settings → Quotation PDFs → Quotation numbers)
ok('formats: the count is needed once; odd characters refused', QN.check('QT-{YYYY}') and QN.check('{NN}{NN}')
   and QN.check('QT<{NNN}>') and QN.check('QT/{FY}/{NNN}') is None)
ok('when the count starts again', QN.resets('{YYYY}{MM}{DD}{NN}') == 'day' and QN.resets('Q{YY}{MM}-{NNN}') == 'month'
   and QN.resets('QT/{FY}/{NNN}') == 'financial year' and QN.resets('QT-{NNN}') is None)
s = c.get('/admin/settings?tab=documents').text
ok('Settings → Quotation PDFs has Quotation numbers', 'id="numbering"' in s and 'name="quote_number_format"' in s)
r = c.post('/admin/settings', data={'section': 'documents', 'quote_number_format': 'QT-{YYYY}', 'quote_number_start': '1'},
           follow_redirects=True)
ok('a format without the count is refused', 'needs the count once' in r.text)
c.post('/admin/settings', data={'section': 'documents', 'quote_number_format': 'QT-{NNN}', 'quote_number_start': '245'})
with app.app_context():
    order = [p.id for p in Project.query.filter(Project.status != 'draft').order_by(Project.created_at, Project.id).all()]
lst = c.get('/projects').text
with app.app_context():
    nums = QN.known()
ok('running number from 245, all numbered again in the order made', nums[order[0]] == 'QT-245' and nums[order[1]] == 'QT-246'
   and sorted(nums.values()) == [f'QT-{245 + i}' for i in range(len(order))])
ok('… shown on the Quotations page', 'QT-245/Rev' in lst)
c.post('/admin/settings', data={'section': 'documents', 'quote_number_format': 'SP/{FY}/{NN}', 'quote_number_start': '1'})
with app.app_context():
    nums = QN.assign()
    p = db.session.get(Project, new_id)
    fy = QN._fy(QN._local(p.created_at))
ok('financial year format', nums[new_id].startswith(f'SP/{fy}/') and len(set(nums.values())) == len(nums))
with app.app_context():
    newer = Project(customer_name='Newer', mobile='9000000998', created_by=maker, created_at=datetime.utcnow())
    db.session.add(newer); db.session.commit()
    n4 = QN.assign(); newer_id = newer.id
ok('a new quotation gets the next number in that format', n4[newer_id] != n4[new_id] and n4[newer_id].startswith('SP/'))
c.post('/admin/settings', data={'section': 'documents', 'quote_number_format': '{YYYY}{MM}{DD}{NN}', 'quote_number_start': '1'})
with app.app_context():
    ok('back to the default: date + count again', QN.assign()[ids[1]] == '2026111801')

# On the PDF: "Quotation No: 2026111801/Rev2" beside the date; the Settings tick takes it off again
import io, re as _re
from pypdf import PdfReader
pdftext = lambda u: _re.sub(r'\s+', ' ', ' '.join(pg.extract_text() for pg in PdfReader(io.BytesIO(c.get(u).data)).pages))
with app.app_context():
    want = QN.for_pdf(db.session.get(Project, ids[1]))
t = pdftext(f'/projects/{ids[1]}/pdf/customer')
ok(f'the customer PDF prints "Quotation No: {want}"', want.startswith('2026111801/Rev') and f'Quotation No: {want}' in t)
ok('…the internal PDF too', f'Quotation No: {want}' in pdftext(f'/projects/{ids[1]}/pdf'))
with app.app_context():
    from app import layout
    ok('{quotation_no} in the PDF sections is the same number', layout.variables(db.session.get(Project, ids[1]))['quotation_no'] == want)
ok('Settings has the tick, on by default', 'name="quote_number_on_pdf" value="1" checked' in c.get('/admin/settings?tab=documents').text)
c.post('/admin/settings', data={'section': 'documents', 'quote_number_format': '{YYYY}{MM}{DD}{NN}', 'quote_number_start': '1',
                                'quote_number_on_pdf_shown': '1'})
ok('…untick it: the PDF has no number again', 'Quotation No' not in pdftext(f'/projects/{ids[1]}/pdf/customer'))
c.post('/admin/settings', data={'section': 'documents', 'quote_number_format': '{YYYY}{MM}{DD}{NN}', 'quote_number_start': '1',
                                'quote_number_on_pdf_shown': '1', 'quote_number_on_pdf': '1'})
