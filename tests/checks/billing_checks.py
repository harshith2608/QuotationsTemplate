"""Quote to cash: revisions, GST invoices, payment reminders, online approval, costs & profit."""
import io, json, re
from datetime import date
from urllib.parse import unquote
from pypdf import PdfReader
from sqlalchemy import text
from app import create_app, db, billing
from app.models import (AppSetting, Invoice, Notification, Payment, PaymentReminder, Project, QuoteRevision,
                        QuoteShare, CostRate, User, ProjectAccess, Material)
ok = lambda label, cond: print(('PASS ' if cond else 'FAIL ') + label)
app = create_app('development'); app.config['WTF_CSRF_ENABLED'] = False
c = app.test_client(); c.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
staff = app.test_client(); staff.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
pdftext = lambda client, u: '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(client.get(u).data)).pages)
FY = billing.financial_year(date.today())

def new_quote(name='Billing Test', mobile='9000000111', rooms=None, discount=('none', '0')):
    rooms = rooms or [{'name': 'Hall', 'items': [
        {'name': 'TV Unit', 'length': 10, 'width': 5, 'wood_type': 'Laminates', 'work_type': 'Box Work'},      # 50 × 850
        {'name': 'Magic Corner', 'type': 'fixed', 'quantity': 1, 'unit_price': 7500}]}]
    c.post('/projects/new', data={'customer_name': name, 'mobile': mobile, 'rooms_data': json.dumps(rooms),
                                  'discount_type': discount[0], 'discount_value': discount[1]})
    with app.app_context():
        return Project.query.order_by(Project.id.desc()).first().id

# ── Helpers ──
ok('amount in words, Indian style', billing.words_indian(1234567) == 'Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven'
   and billing.rupees_in_words(50150.5) == 'Rupees Fifty Thousand One Hundred Fifty and Fifty Paise Only'
   and billing.words_indian(150000000) == 'Fifteen Crore')
ok('financial year April–March', billing.financial_year(date(2026, 3, 31)) == '2025-26' and billing.financial_year(date(2026, 4, 1)) == '2026-27')

# ── Revisions ──
pid = new_quote()
with app.app_context():
    revs = QuoteRevision.query.filter_by(project_id=pid).all()
    ok('new quotation saved as revision 1', [r.number for r in revs] == [1] and revs[0].total == 50 * 850 + 7500)
edit = lambda rooms, disc=('none', '0'), name='Billing Test': c.post(f'/projects/{pid}/edit', data={
    'customer_name': name, 'mobile': '9000000111', 'rooms_data': json.dumps(rooms), 'discount_type': disc[0], 'discount_value': disc[1]},
    follow_redirects=True)
rooms2 = [{'name': 'Hall', 'items': [
    {'name': 'TV Unit', 'length': 12, 'width': 5, 'wood_type': 'Laminates', 'work_type': 'Box Work'},          # 60 sqft now
    {'name': 'Magic Corner', 'type': 'fixed', 'quantity': 1, 'unit_price': 7500},
    {'name': 'Shoe Rack', 'length': 4, 'width': 3, 'wood_type': 'Acrylic', 'work_type': 'Box Work'}]}]
r = edit(rooms2, ('fixed', '1000'))
ok('edit → "Saved as revision 2"', 'Saved as revision 2' in r.text)
edit(rooms2, ('fixed', '1000'))
with app.app_context():
    ok('saving without changes adds no revision', QuoteRevision.query.filter_by(project_id=pid).count() == 2)
t = c.get(f'/projects/{pid}').text
ok('quotation page: Rev 2 badge and revision list with changes', 'Rev 2</a>' in t and 'id="revisions"' in t
   and 'TV Unit changed from 10 ft × 5 ft' in t and 'added Shoe Rack' in t)
t = c.get(f'/projects/{pid}/revisions/1').text
ok('revision 1 still shows the old version', '10 ft × 5 ft' in t and '12 ft' not in t and 'older version' in t)
t = c.get(f'/projects/{pid}/revisions/2').text
ok('revision 2 lists what changed', 'Changes from revision 1' in t and 'Discount ₹0 → ₹1,000' in t)
ok('PDFs show the revision number', 'Rev 2' in pdftext(c, f'/projects/{pid}/pdf') and 'Rev 2' in pdftext(c, f'/projects/{pid}/pdf/customer'))
with app.app_context():
    old = next(p for p in Project.query.all() if p.customer_name == 'Kavya Demo')   # names are encrypted
    QuoteRevision.query.filter_by(project_id=old.id).delete(); db.session.commit()
    old_id, old_total = old.id, old.final_total
c.post(f'/projects/{old_id}/edit', data={'customer_name': 'Kavya Demo', 'mobile': '9000000005', 'discount_type': 'fixed',
       'discount_value': '500', 'rooms_data': c.get(f'/projects/{old_id}/edit').text.split('id="existing-rooms-data"', 1)[1]
       .split('>', 1)[1].split('</script>', 1)[0]})
with app.app_context():
    revs = QuoteRevision.query.filter_by(project_id=old_id).order_by(QuoteRevision.number).all()
    ok('a quotation from before revisions keeps its old version as R1 when edited',
       [r.number for r in revs] == [1, 2] and revs[0].total == old_total and revs[1].total == old_total - 500)
r = staff.get(f'/projects/{pid}/revisions/1')
ok("staff can't open revisions of quotations they can't see", r.status_code == 403)

# ── GST invoice ──
c.post('/admin/settings', data={'section': 'invoices', 'invoice_prefix': 'qr-9x!', 'invoice_gst_rate': '18',
                                'invoice_hsn': '9403', 'invoice_prices': 'exclusive', 'invoice_notes': 'Pay within 7 days.'})
with app.app_context():
    st = billing.invoice_settings()
ok('invoice settings saved (prefix cleaned to 4 characters)', st['prefix'] == 'QR9X' and st['gst_rate'] == 18 and st['hsn'] == '9403')
with app.app_context():
    total_q = db.session.get(Project, pid).final_total          # 60×850 + 7500 + 12×1200 − 1000 = 71,900
ok(f'quotation total for the invoice tests ({total_q})', total_q == 71900)
r = staff.post(f'/projects/{pid}/invoice', data={})
ok('employees cannot issue invoices', r.status_code == 403)
with app.app_context():
    n0 = Invoice.query.filter_by(fy=FY).count()      # the demo data already has an invoice this year
num = lambda k: f'QR9X/{FY}/{n0 + k:03d}'
r = c.post(f'/projects/{pid}/invoice', data={'gst_rate': '18', 'prices': 'exclusive', 'place_code': '29', 'layout': 'summary'},
           follow_redirects=True)
with app.app_context():
    inv = Invoice.query.filter_by(project_id=pid).one()
    d = billing.invoice_data(inv)
    inv_id, inv_total = inv.id, inv.total
ok(f'invoice number {inv.number}: prefix / financial year / next number', inv.number == num(1) and 'issued for' in r.text)
ok('in-state customer: CGST 9% + SGST 9% on top, rounded to the rupee',
   [t['label'] for t in d['taxes']] == ['CGST @ 9%', 'SGST @ 9%'] and d['taxable'] == 71900
   and inv_total == round(71900 * 1.18) and d['title'] == 'TAX INVOICE')
ok('summary invoice: one line per material & work + fittings, with HSN', [(l['description'], l['qty']) for l in d['lines']]
   == [('Acrylic – Box Work', 12.0), ('Laminates – Box Work', 60.0), ('Magic Corner', 1)] and d['lines'][0]['hsn'] == '9403')
txt = pdftext(c, f'/projects/{pid}/invoices/{inv_id}/pdf')
ok('invoice PDF: number, GST lines, total in words, notes', num(1) in txt and 'CGST @ 9%' in txt
   and 'Rupees Eighty Four Thousand Eight Hundred Forty Two Only' in txt and 'Pay within 7 days.' in txt and 'TAX INVOICE' in txt)
ok('staff with access can download the invoice, others cannot', staff.get(f'/projects/{pid}/invoices/{inv_id}/pdf').status_code == 403)
t = c.get(f'/projects/{pid}').text
ok('balance now uses the invoice total (incl. GST)', 'Invoice total' in t and '84,842.00' in t)
r = c.post(f'/projects/{pid}/invoice', data={'gst_rate': '18'}, follow_redirects=True)
ok('a second invoice is refused while one is active', 'already has an invoice' in r.text)
r = c.post(f'/projects/{pid}/delete', follow_redirects=True)
with app.app_context():
    ok('a quotation with invoices can\'t be deleted', db.session.get(Project, pid) is not None and "can&#39;t be deleted" in r.text)
edit(rooms2, ('fixed', '2000'))
ok('changing the quotation after invoicing shows a warning', 'was changed after invoice' in c.get(f'/projects/{pid}').text)
c.post(f'/projects/{pid}/invoices/{inv_id}/cancel')
r = c.post(f'/projects/{pid}/invoice', data={'gst_rate': '18', 'customer_gstin': '27AAPFU0939F1ZV', 'prices': 'exclusive'},
           follow_redirects=True)
with app.app_context():
    invs = Invoice.query.filter_by(project_id=pid).order_by(Invoice.seq).all()
    d2 = billing.invoice_data(invs[-1])
ok('cancel keeps the number; the next invoice gets the next one', [(i.seq, i.status) for i in invs] == [(n0 + 1, 'cancelled'), (n0 + 2, 'issued')])
ok('customer GSTIN from another state → IGST 18%, place of supply Maharashtra', [t['label'] for t in d2['taxes']] == ['IGST @ 18%']
   and d2['place_of_supply']['state'] == 'Maharashtra' and d2['buyer']['gstin'] == '27AAPFU0939F1ZV')
r = c.post(f'/projects/{old_id}/invoice', data={'gst_rate': '18', 'customer_gstin': 'BAD'}, follow_redirects=True)
ok('invalid customer GSTIN refused', "doesn&#39;t look like a valid GSTIN" in r.text or "doesn't look like a valid GSTIN" in r.text)
c.post(f'/projects/{old_id}/invoice', data={'gst_rate': '18', 'prices': 'inclusive'})
with app.app_context():
    inc = Invoice.query.filter_by(project_id=old_id).one()
    dinc = billing.invoice_data(inc)
    kavya = db.session.get(Project, old_id)
    ok('GST-inclusive prices: invoice total = quoted total, tax worked out inside it',
       inc.total == round(kavya.final_total) and abs(dinc['taxable'] * 1.18 - kavya.final_total) < 1)
c.post(f'/projects/{old_id}/invoices/{inc.id}/cancel')
r = c.post(f'/projects/{old_id}/invoice', data={'with_gst': '0', 'gst_rate': '18', 'customer_gstin': '27AAPFU0939F1ZV',
                                                'hsn': '9403', 'notes': 'Thank you for your business.'}, follow_redirects=True)
with app.app_context():
    plain = Invoice.query.filter_by(project_id=old_id, status='issued').one()
    dpl = billing.invoice_data(plain)
    kavya = db.session.get(Project, old_id)
    ok('"Without GST" invoice: no tax, total = quoted total', not dpl['gst'] and not dpl['taxes'] and dpl['total'] == round(kavya.final_total)
       and dpl['title'] == 'INVOICE' and not plain.with_gst)
    plain_id = plain.id
ptxt = pdftext(c, f'/projects/{old_id}/invoices/{plain_id}/pdf')
ok('room-by-room is the default: every item with its size under its room', dpl['layout'] == 'rooms'
   and [(l['room'], l['description']) for l in dpl['lines']][:2] == [('Study Room', 'Study Table'), ('Study Room', 'Display Unit')]
   and dpl['lines'][0]['detail'].startswith('5 ft × 2 ft 6 in · '))
ok('room-by-room invoice PDF: room headings, item sizes and room totals', 'STUDY ROOM' in ptxt and '5 ft × 2 ft 6 in' in ptxt
   and 'Study Room total' in ptxt)
ok('"Without GST" invoice PDF never mentions GST, GSTIN, HSN or tax', 'GST' not in ptxt and 'HSN' not in ptxt
   and 'tax' not in ptxt.lower() and 'Place of supply' not in ptxt and 'INVOICE' in ptxt and 'Thank you for your business.' in ptxt)
ok('quotation page marks it "without GST"', 'without GST</span>' in c.get(f'/projects/{old_id}').text)
c.post('/admin/settings', data={'section': 'invoices', 'invoice_prefix': 'QR9X', 'invoice_gst_rate': '18', 'invoice_prices': 'exclusive',
                                'invoice_with_gst': 'no'})
with app.app_context():
    ok('setting: usually without GST', billing.invoice_settings()['with_gst'] is False)
c.post('/admin/settings', data={'section': 'invoices', 'invoice_prefix': 'QR9X', 'invoice_gst_rate': '18', 'invoice_prices': 'exclusive',
                                'invoice_with_gst': 'yes'})
with app.app_context():
    # A business without a GSTIN issues plain invoices
    AppSetting.set('company_gstin', ''); db.session.commit()
pid_plain = new_quote('No GST Customer', '9000000112')
c.post(f'/projects/{pid_plain}/invoice', data={'gst_rate': '18'})
with app.app_context():
    dp = billing.invoice_data(Invoice.query.filter_by(project_id=pid_plain).one())
    ok('no GSTIN → plain INVOICE without GST', dp['title'] == 'INVOICE' and not dp['taxes'] and not dp['gst'] and dp['total'] == 50 * 850 + 7500)
    AppSetting.set('company_gstin', '29ABCDE1234F1Z5'); db.session.commit()

# ── Payment reminders & balances due ──
r = c.post(f'/projects/{pid}/remind', data={'amount': '20000'})
msg = unquote(r.headers.get('Location', ''))
ok('reminder opens WhatsApp with the amount, invoice number and payment details', r.status_code == 302
   and msg.startswith('https://wa.me/919000000111?text=') and 'Amount due: Rs.20,000.00' in msg and num(2) in msg
   and 'UPI: demo-interiors@example' in msg)
with app.app_context():
    ok('reminder recorded', PaymentReminder.query.filter_by(project_id=pid).count() == 1)
r = c.post(f'/projects/{pid}/remind', data={'amount': '99999999'}, follow_redirects=True)
ok('reminder for more than the balance refused', 'between ₹1 and the balance due' in r.text)
r = c.post(f'/projects/{pid}/remind', data={'with_link': '1'}, follow_redirects=True)
ok('payment link without Razorpay keys → clear message, no WhatsApp', 'Razorpay is not configured' in r.text)
t = c.get('/payments/due').text
ok('Balances due lists invoiced and confirmed quotations with what is left', 'Billing Test' in t and 'Rahul Sample' in t
   and 'last reminded' in t and 'Meera Test' not in t)          # Meera is still awaiting confirmation
ts = staff.get('/payments/due').text
ok('staff only see balances of their own quotations', 'Rahul Sample' not in ts and 'Priya Example' in ts)
r = c.get(f'/projects/{pid}').text
ok('quotation page has the reminder form and last-sent date', 'Payment reminder' in r and 'Last sent' in r)

# ── Online approval ──
mid = new_quote('Approval Customer', '9000000113')
c.post(f'/projects/{mid}/share')
with app.app_context():
    token = QuoteShare.query.filter_by(project_id=mid, active=True).one().token
anon = app.test_client()
r = anon.get(f'/q/{token}')
ok('link shows the material breakdown by default: no sizes, no per-item amounts', "What's included" in r.text
   and '10 ft × 5 ft' not in r.text and 'Laminates – Box Work' in r.text)
ok('…and its PDF is the Initial (customer) quotation', 'Room-by-Room' not in pdftext(anon, f'/q/{token}/pdf'))
c.post(f'/projects/{mid}/share/detail', data={'detail': 'full'})
rf = anon.get(f'/q/{token}')
ok('switched to full detail: every item with size and amount, room totals', '10 ft × 5 ft' in rf.text and 'Hall total' in rf.text
   and 'Room-by-Room' in pdftext(anon, f'/q/{token}/pdf'))
c.post(f'/projects/{mid}/share/detail', data={'detail': 'summary'})
ok('customer opens the link without logging in', r.status_code == 200 and 'Approval Customer' in r.text and 'Accept quotation' in r.text
   and r.headers.get('X-Robots-Tag', '').startswith('noindex') and r.headers.get('Cache-Control') == 'no-store')
ok('customer page never shows costs or profit', 'profit' not in r.text.lower() and 'your cost' not in r.text.lower())
ok('customer can download the PDF', anon.get(f'/q/{token}/pdf').status_code == 200 and anon.get(f'/q/{token}/pdf').mimetype == 'application/pdf')
with app.app_context():
    views = QuoteShare.query.filter_by(token=token).one().view_count
c.get(f'/q/{token}')
with app.app_context():
    ok(f'customer views counted ({views}), staff views not', views >= 2 and QuoteShare.query.filter_by(token=token).one().view_count == views)
ok('wrong token → 404', anon.get('/q/not-a-real-token').status_code == 404)
t = c.get(f'/projects/{mid}/whatsapp').headers['Location']
ok('WhatsApp summary includes the approval link', f'/q/{token}' in unquote(t))
r = anon.post(f'/q/{token}/respond', data={'kind': 'accepted', 'name': 'Approval Customer'}, follow_redirects=True)
ok('accepting needs the tick box', 'tick the box' in r.text)
r = anon.post(f'/q/{token}/respond', data={'kind': 'accepted', 'name': 'A. Customer', 'agree': '1'}, follow_redirects=True)
with app.app_context():
    p = db.session.get(Project, mid)
    n = Notification.query.filter_by(project_id=mid).first()
    ok('accept → quotation confirmed, admin notified', p.stage == 'confirmed' and n and 'accepted' in n.title)
ok('customer sees "Accepted" and no more buttons', 'Accepted by A. Customer' in r.text and 'name="agree"' not in r.text)
t = c.get(f'/projects/{mid}').text
ok('quotation page shows who accepted, and the stage note', 'Accepted</strong> by A. Customer' in t and 'Accepted online by A. Customer' in t
   and 'the customer, online' in t)
c.post(f'/projects/{mid}/edit', data={'customer_name': 'Approval Customer', 'mobile': '9000000113', 'discount_type': 'fixed',
       'discount_value': '1500', 'rooms_data': json.dumps([{'name': 'Hall', 'items': [
           {'name': 'TV Unit', 'length': 10, 'width': 5, 'wood_type': 'Laminates', 'work_type': 'Box Work'}]}])})
r = anon.get(f'/q/{token}')
ok('after an edit the customer can accept the new version', 'name="agree"' in r.text and 'Rev 2' in r.text)
r = anon.post(f'/q/{token}/respond', data={'kind': 'changes', 'note': 'Please add a loft.'}, follow_redirects=True)
with app.app_context():
    ok('change request recorded and notified', Notification.query.filter(Notification.project_id == mid).count() == 2)
ok('customer sees their change request noted', 'You asked for changes' in r.text)
c.post(f'/projects/{mid}/share/off')
ok('turned-off link no longer opens', anon.get(f'/q/{token}').status_code == 404)

# ── Costs & profit ──
t = c.get('/admin/costs').text
ok('costs page lists materials with selling rates', 'Laminates – Box Work' in t and 'You charge' in t)
ok("employees can't open costs", staff.get('/admin/costs').status_code == 403)
with app.app_context():
    from app import materials as M
    combos = [M.key(w, k) for w, k, _ in M.combos(include_hidden=True)]
    lam_i = combos.index('Laminates|Box Work')
    acr_i = combos.index('Acrylic|Box Work')
form = {f'm_{i}': '' for i in range(len(combos))}
form.update({f'm_{lam_i}': '500', f'm_{acr_i}': 'abc'})
r = c.post('/admin/costs', data=form, follow_redirects=True)
ok('invalid cost refused, nothing saved', 'Enter a number for Acrylic – Box Work' in r.text)
form[f'm_{acr_i}'] = '700'
with app.app_context():
    from app.models import PriceListItem
    listed = PriceListItem.query.filter(PriceListItem.name.ilike('Magic Corner')).first()
    extra = {r.id: r.name for r in CostRate.query.filter_by(kind='fitting')}
if listed:
    form[f'f_{listed.id}'] = '5000'
else:
    form.update({f'x_{i}': ('5000' if n.lower() == 'magic corner' else '') for i, n in extra.items()})
    if 'magic corner' not in [n.lower() for n in extra.values()]:
        form.update({'new_fitting': 'Magic Corner', 'new_fitting_cost': '5000'})
c.post('/admin/costs', data=form)
with app.app_context():
    costs = billing.cost_rates()
    ok('costs saved; empty boxes clear old ones', costs.get(('material', 'Laminates|Box Work')) == 500
       and ('material', 'Veneer|Box Work') not in costs and costs.get(('fitting', 'magic corner')) == 5000)
t = c.get(f'/projects/{pid}').text
# pid now: 60 sqft laminate box (500) + 12 sqft acrylic box (700) + magic corner (5000) = 43,400 cost; price 70,900
ok('admin sees estimated profit on the quotation', 'Estimated profit' in t and '&#8377;70,900' in t and '&#8377;43,400' in t and '&#8377;27,500' in t)
ts = staff.get('/projects/1').text
ok("staff never see costs or profit", 'Estimated profit' not in ts and 'Your cost' not in ts)
ok('profit never printed in PDFs', 'profit' not in pdftext(c, f'/projects/{pid}/pdf').lower())
with app.app_context():
    m = Material.query.filter_by(name='Laminates').first()
    mat_id = m.id
c.post('/admin/rates', data={'item_rates_submit': 'save', f'name_{mat_id}': 'Laminate', f'rate_{mat_id}_0': '850', f'rate_{mat_id}_1': '850'})
with app.app_context():
    ok('renaming a material keeps its cost', billing.cost_rates().get(('material', 'Laminate|Box Work')) == 500)

# ── Demo: invoice PDFs are marked and figures altered ──
import os
os.environ['DEMO_MODE'] = '1'
demo_app = create_app('development'); demo_app.config['WTF_CSRF_ENABLED'] = False
dc = demo_app.test_client(); dc.get('/demo', headers={'User-Agent': 'Mozilla/5.0'})
with demo_app.app_context():
    rahul_id = next(p.id for p in Project.query.all() if p.customer_name == 'Rahul Sample')
    rahul_inv = Invoice.query.filter_by(project_id=rahul_id).first()
dtxt = pdftext(dc, f'/projects/{rahul_inv.project_id}/invoices/{rahul_inv.id}/pdf')
ok('demo invoice PDF: DEMO notice, no amount in words', 'DEMO' in dtxt and 'Amount in words' not in dtxt)
ok('demo cannot save costs', 'disabled in the demo' in dc.post('/admin/costs', data={}, follow_redirects=True).text)
os.environ.pop('DEMO_MODE')

# ── Right after a deploy, before the database update: everything else keeps working ──
with app.app_context():
    for t_ in ['quote_responses', 'quote_shares', 'quote_revisions', 'invoices', 'payment_reminders', 'cost_rates']:
        db.session.execute(text(f'DROP TABLE {t_}'))
    db.session.commit()
billing._ready_forever.clear()
c2 = app.test_client(); c2.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
t = c2.get(f'/projects/{pid}')
ok('before the update: quotation page works, new cards hidden', t.status_code == 200 and 'id="invoice"' not in t.text
   and 'id="approval"' not in t.text and 'Estimated profit' not in t.text)
r = c2.post('/projects/new', data={'customer_name': 'Pre Update', 'mobile': '9000000114', 'discount_type': 'none', 'discount_value': '0',
            'rooms_data': json.dumps([{'name': 'Hall', 'items': [{'name': 'TV Unit', 'length': 8, 'width': 6, 'wood_type': 'Acrylic', 'work_type': 'Box Work'}]}])})
with app.app_context():
    pre = Project.query.order_by(Project.id.desc()).first()
ok('before the update: create, edit, PDF, WhatsApp and balances work', r.status_code == 302 and pre.customer_name == 'Pre Update'
   and c2.post(f'/projects/{pre.id}/edit', data={'customer_name': 'Pre Update', 'mobile': '9000000114', 'discount_type': 'none',
               'discount_value': '0', 'rooms_data': json.dumps([{'name': 'Hall', 'items': [{'name': 'TV Unit', 'length': 9, 'width': 6,
               'wood_type': 'Acrylic', 'work_type': 'Box Work'}]}])}).status_code == 302
   and c2.get(f'/projects/{pre.id}/pdf').status_code == 200 and c2.get(f'/projects/{pre.id}/whatsapp').status_code == 302
   and c2.get('/payments/due').status_code == 200)
ok('before the update: costs page explains, public links 404', c2.get('/admin/costs', follow_redirects=True).status_code == 200
   and app.test_client().get(f'/q/{token}').status_code == 404)
from app.seed import seed_demo
with app.app_context():
    seed_demo(reset=True)
    ok('before the update: the nightly demo reset still works', Project.query.count() == 5)
