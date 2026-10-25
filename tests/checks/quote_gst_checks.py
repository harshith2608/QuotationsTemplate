"""GST on quotations (app/quote_gst.py): off by default; turned on per business (with its rate) it shows Total, GST
and the grand total with GST on the quotation page, the list, every PDF layout, the customer's link, WhatsApp and the
form; what the customer owes includes it; a new invoice adds GST on the quoted prices at that rate."""
import io, re, urllib.parse
from pypdf import PdfReader
from app import create_app, db, billing, layout, quote_gst
from app.models import AppSetting, Payment, Project

ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
pdftext = lambda u: re.sub(r'\s+', ' ', ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(c.get(u).data)).pages))
money = lambda v: f'{v:,.2f}'
indian = lambda t: re.sub(r'(\d),(\d{2}),(\d{3})', r'\1\2\3', t)     # PDFs print 1,234,567.00; compare without commas


def numbers(text):
    return text.replace(',', '')


with app.app_context():
    p = next(x for x in Project.query.filter(Project.status != 'draft').all() if x.final_total > 0)
    pid, total = p.id, p.final_total
    ok('off by default: nothing added', not quote_gst.enabled() and p.gst_amount == 0 and p.total_payable == total)
v = c.get(f'/projects/{pid}').text
ok('off: the quotation page shows no GST', 'GST @' not in v and 'FINAL TOTAL' in v)

with app.app_context():
    quote_gst.set_gst(True, 18); db.session.commit()
    p = db.session.get(Project, pid)
    gst = round(total * 0.18, 2)
    ok('on at 18%: GST and the grand total', p.gst_amount == gst and p.total_payable == round(total + gst, 2))
    try:
        quote_gst.set_gst(True, 7)
        bad = False
    except ValueError:
        bad = True
    ok('a rate that isn\'t a GST rate is refused', bad)
    db.session.rollback()
v = c.get(f'/projects/{pid}').text
ok('quotation page: Total, GST @ 18%, GRAND TOTAL (incl. GST)', 'GST @ 18%' in v and 'GRAND TOTAL (incl. GST)' in v
   and money(gst) in v and money(total + gst) in v)
ok('the quotations list shows the total with GST', money(total + gst) in c.get('/projects').text)
ok('the form adds it live (rate passed to the form)', 'gstRate:     18' in c.get(f'/projects/{pid}/edit').text
   and 'Grand Total (incl. GST)' in c.get(f'/projects/{pid}/edit').text)
full = numbers(pdftext(f'/projects/{pid}/pdf'))
ok('Full Quotation PDF: GST @ 18% and the grand total', 'GST @ 18%' in full and 'GRAND TOTAL (incl. GST)' in full
   and f'{total + gst:.2f}' in full)
for lay in (layout.LAYOUT_ROOMS, layout.LAYOUT_MATERIALS, layout.LAYOUT_BOQ):
    with app.app_context():
        AppSetting.set(layout.LAYOUT_KEY, lay); db.session.commit()
    cust = numbers(pdftext(f'/projects/{pid}/pdf/customer'))
    ok(f'customer PDF ({lay}): GST and the grand total', 'GST @ 18%' in cust and f'{total + gst:.2f}' in cust)
wa = urllib.parse.unquote(c.get(f'/projects/{pid}/whatsapp').headers.get('Location', ''))
ok('WhatsApp text: GST and the grand total with GST', 'GST @ 18%' in wa and f'Rs.{total + gst:,.2f}' in wa)
c.post(f'/projects/{pid}/share')
with app.app_context():
    from app import share
    tok = share._active_share(db.session.get(Project, pid)).token
    snap = billing.quotation_snapshot(db.session.get(Project, pid))
ok('the revision keeps GST (rate, amount, grand total)', snap.get('gst_rate') == 18 and snap.get('gst') == gst
   and snap.get('payable') == round(total + gst, 2))
q = app.test_client().get(f'/q/{tok}').text
ok("customer's link: GST and the grand total, accepting for the total with GST", 'GST @ 18%' in q
   and q.count(money(total + gst)) >= 2 and '(incl. GST)' in q)
with app.app_context():
    p = db.session.get(Project, pid)
    paid = billing.paid_total(p)
    inv = billing.active_invoice(p)
    s = billing.invoice_settings()
    ok('what the customer owes includes GST (no invoice yet)', inv is not None or
       billing.balance(p) == round(max(total + gst - paid, 0), 2))
    ok('a new invoice adds GST on the quoted prices at this rate (not twice)', s['prices'] == billing.PRICES_EXCLUSIVE
       and s['with_gst'] and s['gst_rate'] == 18)
    quote_gst.set_gst(True, 12); db.session.commit()
    p = db.session.get(Project, pid)
    ok('rate changed to 12%', p.gst_amount == round(total * 0.12, 2))
    quote_gst.set_gst(False, 12); db.session.commit()
    p = db.session.get(Project, pid)
    ok('off again: no GST anywhere', p.gst_amount == 0 and p.total_payable == total
       and 'GST @' not in c.get(f'/projects/{pid}').text)
