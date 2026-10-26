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
t1 = c.get(f'/projects/{pid}/revisions/1').text
ok('an old revision offers its PDF and Compare with the current one', f'/projects/{pid}/revisions/1/pdf' in t1
   and 'Compare with the current one (Rev 2)' in t1)
r1pdf = pdftext(c, f'/projects/{pid}/revisions/1/pdf').replace('\n', ' ')
ok('the PDF of revision 1 is the quotation as it was (its total, no Shoe Rack, "Rev 1")', 'Rev 1' in r1pdf
   and '50,000.00' in r1pdf and 'Shoe Rack' not in r1pdf and 'Billing Test' in r1pdf)
cmp_ = c.get(f'/projects/{pid}/revisions/1/compare').text
ok('Compare: revision 1 and the current one side by side, what changed highlighted', 'Revision 1 vs revision 2' in cmp_
   and 'ki-cmp-changed' in cmp_ and 'ki-cmp-added' in cmp_ and 'Shoe Rack' in cmp_ and '10 ft × 5 ft' in cmp_
   and '12 ft × 5 ft' in cmp_ and '1 added · 0 removed · 1 changed' in cmp_ and 'size' in cmp_ and 'Discount' in cmp_)
with app.app_context():
    _r = {r.number: json.loads(r.snapshot) for r in QuoteRevision.query.filter_by(project_id=pid)}
    back = billing.compare_snapshots(_r[2], _r[1])          # the other way round: the Shoe Rack is removed
ok('…the other way round, an item that\'s gone is "removed"', back['counts']['removed'] == 1 and back['counts']['added'] == 0)
ok('…any two revisions (with=), not a revision with itself', c.get(f'/projects/{pid}/revisions/2/compare?with=1').status_code == 200
   and c.get(f'/projects/{pid}/revisions/1/compare?with=1').status_code == 404)
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

# Times on the quotation page are Indian time (stored as UTC)
from datetime import datetime as _dt
with app.app_context():
    p_ = db.session.get(Project, pid); saved = p_.created_at; p_.created_at = _dt(2026, 1, 1, 20, 0); db.session.commit()
ok('quotation page shows times in IST (20:00 UTC → 01:30 AM next day)', '02 January 2026, 01:30 AM' in c.get(f'/projects/{pid}').text)
with app.app_context():
    p_ = db.session.get(Project, pid); p_.created_at = saved; db.session.commit()

# Shared access is view-only: no Edit button for staff who didn't make the quotation
with app.app_context():
    st_id = User.query.filter_by(username='demo-staff').first().id
    db.session.add(ProjectAccess(project_id=pid, user_id=st_id, granted_by=User.query.filter_by(username='demo-admin').first().id))
    db.session.commit()
t = staff.get(f'/projects/{pid}').text
ok('staff with shared access can view, but see no Edit button and can\'t edit',
   'Billing Test' in t and f'/projects/{pid}/edit' not in t and f'/projects/{pid}/edit' not in staff.get('/projects').text
   and staff.get(f'/projects/{pid}/edit').status_code == 403)
ok('admin still sees Edit', f'/projects/{pid}/edit' in c.get(f'/projects/{pid}').text)
with app.app_context():
    ProjectAccess.query.filter_by(project_id=pid, user_id=st_id).delete(); db.session.commit()

# Access levels from the list's Access pop-up: no access / can view / can edit; delete stays admin-only
st_id_ = None
with app.app_context():
    st_id_ = User.query.filter_by(username='demo-staff').first().id
lst = c.get('/projects').text
ok('quotations list: no WhatsApp button in Actions; Access pop-up offers view/edit', 'whatsapp' not in lst.split('<table', 1)[-1].split('</table>', 1)[0].lower()
   and "opt('edit'" in lst and "name=\"access_${emp.id}\"" in lst)
r = c.post(f'/projects/{pid}/access', data={f'access_{st_id_}': 'edit'}, follow_redirects=True)
ok('give staff edit access', 'Access updated: 1 can edit' in r.text)
t = staff.get(f'/projects/{pid}').text
ok('staff with edit access see Edit, can open and save the edit form', f'/projects/{pid}/edit' in t
   and f'/projects/{pid}/edit' in staff.get('/projects').text and staff.get(f'/projects/{pid}/edit').status_code == 200)
rooms_now = staff.get(f'/projects/{pid}/edit').text.split('id="existing-rooms-data"', 1)[1].split('>', 1)[1].split('</script>', 1)[0]
r = staff.post(f'/projects/{pid}/edit', data={'customer_name': 'Billing Test', 'mobile': '9000000111', 'rooms_data': rooms_now,
                                             'discount_type': 'fixed', 'discount_value': '1000'})
ok('…and their save goes through', r.status_code == 302)
r = staff.post(f'/projects/{pid}/delete')
with app.app_context():
    ok('…but they can never delete it', db.session.get(Project, pid) is not None and r.status_code in (302, 403))
c.post(f'/projects/{pid}/access', data={f'access_{st_id_}': 'view'})
ok('view access: no Edit, edit page refused', f'/projects/{pid}/edit' not in staff.get(f'/projects/{pid}').text
   and staff.get(f'/projects/{pid}/edit').status_code == 403 and staff.get(f'/projects/{pid}').status_code == 200)
c.post(f'/projects/{pid}/access', data={f'access_{st_id_}': ''})
ok('no access: the quotation is hidden from them', staff.get(f'/projects/{pid}').status_code == 403)
c.post(f'/projects/{pid}/access', data={'user_ids': str(st_id_)})
ok('older pop-up (user_ids) still means view', staff.get(f'/projects/{pid}').status_code == 200
   and staff.get(f'/projects/{pid}/edit').status_code == 403)
c.post(f'/projects/{pid}/access', data={})

# ── Restore an older revision ──
rid = new_quote(name='Restore Test', mobile='9000000222')                     # Rev 1: 50 × 850 + 7,500 = 50,000
c.post(f'/projects/{rid}/edit', data={'customer_name': 'Restore Test', 'mobile': '9000000222', 'rooms_data': json.dumps(rooms2),
       'discount_type': 'fixed', 'discount_value': '1000'})                     # Rev 2
t = c.get(f'/projects/{rid}').text
ok('quotation page says revisions can be downloaded, compared and restored', 'compare it side by side' in t and 'or restore it' in t)
t = c.get(f'/projects/{rid}/revisions/1').text
ok('older revision offers Restore, saved as a new revision, with both totals', 'Restore revision 1' in t and '(Rev 3)' in t
   and 'After restoring' in t and '50,000.00' in t and 'rates have changed' not in t)
ok('the current revision has no Restore button', 'Restore revision' not in c.get(f'/projects/{rid}/revisions/2').text)
ok('staff can\'t restore', 'Restore revision' not in staff.get(f'/projects/{rid}/revisions/1').text
   and staff.post(f'/projects/{rid}/revisions/1/restore').status_code in (302, 403))
with app.app_context():
    ok('…and nothing changed when they tried', QuoteRevision.query.filter_by(project_id=rid).count() == 2)
r = c.post(f'/projects/{rid}/revisions/1/restore', follow_redirects=True)
with app.app_context():
    p_ = db.session.get(Project, rid)
    revs = QuoteRevision.query.filter_by(project_id=rid).order_by(QuoteRevision.number).all()
    s1, s3 = json.loads(revs[0].snapshot), json.loads(revs[-1].snapshot)
    ok('restore → Rev 3 with exactly Rev 1\'s rooms, items and discount; history kept',
       [r_.number for r_ in revs] == [1, 2, 3] and s3['rooms'] == s1['rooms'] and s3['discount'] == s1['discount']
       and s3['restored_from'] == 1 and p_.final_total == 50000 and revs[-1].total == 50000)
ok('removing an item completely is listed as removed', billing.diff_snapshots(
    {'rooms': [{'name': 'Bedroom', 'items': [{'name': 'Wardrobe', 'type': 'fixed', 'quantity': 1, 'unit_price': 5},
                                             {'name': 'Loft', 'type': 'fixed', 'quantity': 1, 'unit_price': 3}]}], 'total': 8},
    {'rooms': [{'name': 'Bedroom', 'items': [{'name': 'Wardrobe', 'type': 'fixed', 'quantity': 1, 'unit_price': 5}]}], 'total': 5})
   [:1] == ['Bedroom: removed Loft'])
ok('flash says which revision it is now', 'saved as revision 3' in r.text and 'restored from Rev 1' in r.text)
ok('revision page shows where it came from', 'restored from Rev 1' in c.get(f'/projects/{rid}/revisions/3').text)
r = c.post(f'/projects/{rid}/revisions/3/restore', follow_redirects=True)
ok('restoring the current version does nothing', 'already the current version' in r.text)
c.post(f'/projects/{rid}/edit', data={'customer_name': 'Restore Test', 'mobile': '9000000222', 'rooms_data': c.get(f'/projects/{rid}/edit').text
       .split('id="existing-rooms-data"', 1)[1].split('>', 1)[1].split('</script>', 1)[0], 'discount_type': 'none', 'discount_value': '0'})
with app.app_context():
    ok('saving a restored quotation unchanged adds no revision', QuoteRevision.query.filter_by(project_id=rid).count() == 3)
    from app.models import ItemRate
    lam = ItemRate.query.filter_by(wood_type='Laminates', work_type='Box Work').first(); lam.rate_per_sqft = 900; db.session.commit()
t = c.get(f'/projects/{rid}/revisions/2').text
ok('restore preview warns about changed rates and shows the total at today\'s rates',
   'rates have changed' in t and 'Laminates – Box Work &#8377;850 → &#8377;900/sqft' in t)
with app.app_context():
    s2 = json.loads(QuoteRevision.query.filter_by(project_id=rid, number=2).first().snapshot)
    expect = round(sum(round(i['length'] * i['width'], 4) * (900 if i['wood_type'] == 'Laminates' else i['rate']) if i['type'] == 'measured'
                       else i['quantity'] * i['unit_price'] for i in s2['rooms'][0]['items']) - 1000, 2)
c.post(f'/projects/{rid}/revisions/2/restore')
with app.app_context():
    p_ = db.session.get(Project, rid)
    ok('restore at today\'s rates: total matches the preview', p_.final_total == expect and f"{expect:,.2f}" in t)
    lam = ItemRate.query.filter_by(wood_type='Laminates', work_type='Box Work').first(); lam.rate_per_sqft = 850; db.session.commit()

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
r = c.post(f'/projects/{pid}/revisions/1/restore', follow_redirects=True)
with app.app_context():
    ok('restore is blocked while an invoice is active', 'Cancel it first' in r.text
       and QuoteRevision.query.filter_by(project_id=pid).count() == 2)
ok('…and the revision page says why', 'Cancel it first' in c.get(f'/projects/{pid}/revisions/1').text)
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

# ── Sharing invoices online (WhatsApp, email, link) ──
with app.app_context():
    active = Invoice.query.filter_by(project_id=pid, status='issued').one()
    act_id, act_no = active.id, active.number
txt = pdftext(c, f'/projects/{pid}/invoices/{act_id}/pdf')
ok('invoice PDF has no signature block', 'Signatory' not in txt and 'Proprietor' not in txt and 'needs no signature' in txt)
r = c.get(f'/projects/{pid}/invoices/{act_id}/whatsapp')
wa = unquote(r.headers.get('Location', ''))
link = re.search(r'(http://[^\s]+/i/[^\s]+)', wa)
ok('WhatsApp: invoice number, total and a link to view it', wa.startswith('https://wa.me/919000000111?text=') and act_no in wa
   and link is not None)
ilink = link.group(1).replace('http://localhost', '')
anon_i = app.test_client()
r = anon_i.get(ilink)
ok('customer opens the invoice link without logging in', r.status_code == 200 and act_no in r.text and 'IGST @ 18%' in r.text
   and r.headers.get('X-Robots-Tag', '').startswith('noindex') and 'needs no signature' in r.text)
ok('…and downloads the PDF', anon_i.get(ilink + '/pdf').mimetype == 'application/pdf')
ok('a tampered invoice link → 404', anon_i.get(ilink[:-3] + 'abc').status_code == 404 and anon_i.get('/i/nonsense').status_code == 404)
t = c.get(f'/projects/{pid}').text
ok('quotation page: WhatsApp and copy-link for the invoice', f'/invoices/{act_id}/whatsapp' in t and ilink.split('/i/')[1] in t
   and "copyText(" in t)
ok('no email settings → no Email buttons', 'emailQuoteModal' not in t and f'/invoices/{act_id}/email' not in t)
r = c.post(f'/projects/{pid}/invoices/{act_id}/email', data={'to': 'buyer@example.com'}, follow_redirects=True)
ok('no email settings → nothing sent, explains where to set it up', 'Set up email in Admin' in r.text)
import app.projects as _projects
sent = []
_orig_send = _projects._send_email
_projects._send_email = lambda to, subject, body, raise_errors=False, attachments=None: sent.append((to, subject, body, attachments)) or True
with app.app_context():
    for k, v in (('smtp_host', 'smtp.example.com'), ('smtp_user', 'me@example.com'), ('smtp_pass', 'test-only')):
        AppSetting.set(k, v)
    db.session.commit()
t = c.get(f'/projects/{pid}').text
ok('with email set up: Email buttons for the quotation and the invoice', 'emailQuoteModal' in t and f'/invoices/{act_id}/email' in t)
r = c.post(f'/projects/{pid}/invoices/{act_id}/email', data={'to': 'not-an-email'}, follow_redirects=True)
ok('invalid address refused', 'Enter a valid customer email address' in r.text)
r = c.post(f'/projects/{pid}/invoices/{act_id}/email', data={'to': 'buyer@example.com'}, follow_redirects=True)
ok('with email set up: sent with the PDF attached and the link in the message', sent and sent[0][0] == 'buyer@example.com'
   and act_no in sent[0][1] and '/i/' in sent[0][2] and sent[0][3][0][1][:4] == b'%PDF' and 'emailed to buyer@example.com' in r.text)
r = c.post(f'/projects/{pid}/email', data={'to': 'buyer@example.com', 'pdf': 'full', 'with_link': '1'}, follow_redirects=True)
q = sent[-1]
ok('quotation emailed: full PDF attached, link to accept online', 'Quotation emailed to buyer@example.com' in r.text
   and q[3][0][0].startswith('Quotation_') and q[3][0][1][:4] == b'%PDF' and '/q/' in q[2] and f'Quotation #{pid}' in q[1])
c.post(f'/projects/{pid}/email', data={'to': 'buyer@example.com', 'pdf': 'initial'})
ok('…or the Initial Quotation without a link', sent[-1][3][0][0].startswith('CustomerQuotation_') and '/q/' not in sent[-1][2])
_projects._send_email = _orig_send
with app.app_context():
    for k in ('smtp_host', 'smtp_user', 'smtp_pass'):
        AppSetting.set(k, '')
    db.session.commit()

# ── Online approval ──
mid = new_quote('Approval Customer', '9000000113')
c.post(f'/projects/{mid}/share')
with app.app_context():
    token = QuoteShare.query.filter_by(project_id=mid, active=True).one().token
anon = app.test_client()
r = anon.get(f'/q/{token}')
ok('link shows the Initial (room by room) view by default: sizes and room amounts, no rates or per-item amounts',
   'Room by room' in r.text and '10 ft × 5 ft' in r.text and 'Laminates – Box Work' in r.text and '= 50.00 sqft' not in r.text)
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

# ── Reports ──
t = c.get('/admin/reports').text
ok('reports: this year, projection, months and years', 'Won this year' in t and 'Projected for' in t and 'month by month' in t
   and f'>{FY}' in t and 'Till date' in t)
ok("employees can't open reports", staff.get('/admin/reports').status_code == 403)
from app import reports as R
with app.app_context():
    rep = R.build()
    won = [p for p in Project.query.all() if p.status != 'draft' and p.stage in R.WON]
    ok('reports: won value adds up the confirmed quotations', abs(rep['total']['won_value'] - sum(p.final_total for p in won)) < 0.01
       and rep['total']['collected'] == round(sum(x.amount for x in Payment.query.all()), 2))

# ── Profit is before GST, with exact amounts ──
def expected_cost(project):
    costs = billing.cost_rates(); total = 0.0
    for room in project.rooms_with_items():
        for i in room.item_list:
            if i.is_fixed:
                total += (i.quantity or 0) * costs.get(('fitting', i.name.lower()), 0)
            else:
                total += i.area * costs.get(('material', f'{i.wood_type}|{i.work_type}'), 0)
    return round(total, 2)
with app.app_context():
    rahul = next(p for p in Project.query.all() if p.customer_name == 'Rahul Sample')
    rinv = billing.active_invoice(rahul)
    rd = billing.invoice_data(rinv)
    pr = billing.profit(rahul)
    ok(f'GST-inclusive invoice: profit uses the taxable value, not the quoted total ({pr["selling"]})',
       rd['prices'] == 'inclusive' and rd['taxable'] == round(175500 / 1.18, 2) == 148728.81 and pr['selling'] == 148728.81
       and pr['gst_removed'] and pr['quoted'] == 175500)
    ok(f'…profit = taxable value − costs, to the paisa ({pr["profit"]})', pr['cost'] == expected_cost(rahul)
       and pr['profit'] == round(148728.81 - expected_cost(rahul), 2) and pr['margin'] == round(pr['profit'] / 148728.81 * 100, 1))
    priya = next(p for p in Project.query.all() if p.customer_name == 'Priya Example')
    ok('not invoiced, prices before GST: profit on the quoted total', billing.active_invoice(priya) is None
       and billing.profit(priya)['selling'] == priya.final_total and not billing.profit(priya)['gst_removed'])
    for k, v in (('invoice_prices', 'inclusive'), ('invoice_with_gst', 'yes'), ('invoice_gst_rate', '18')):
        AppSetting.set(k, v)
    db.session.commit()
    pi = billing.profit(priya)
    ok(f'not invoiced, quotes include 18% GST: GST taken out ({pi["selling"]})', pi['selling'] == round(priya.final_total / 1.18, 2)
       and pi['gst_removed'] and pi['profit'] == round(pi['selling'] - expected_cost(priya), 2))
    AppSetting.set('invoice_with_gst', 'no'); db.session.commit()
    ok('…but businesses that usually invoice without GST keep the quoted total', billing.profit(priya)['selling'] == priya.final_total)
    AppSetting.set('company_gstin', ''); AppSetting.set('invoice_with_gst', 'yes'); db.session.commit()
    from flask import g as _g; _g.pop('brand', None)          # business details are read once per request
    ok('…and so do businesses without a GSTIN', billing.profit(priya)['selling'] == priya.final_total)
    AppSetting.set('company_gstin', '29ABCDE1234F1Z5'); AppSetting.set('invoice_prices', 'exclusive'); db.session.commit()
    _g.pop('brand', None)
    plain_inv = Invoice.query.filter_by(project_id=old_id, status='issued').one()      # the "without GST" invoice
    kav = db.session.get(Project, old_id)
    ok('invoice without GST: profit on its total (no GST in it)', billing.profit(kav)['selling'] == kav.final_total
       and not billing.invoice_data(plain_inv)['taxes'])
    rep = R.build()
    won = [p for p in Project.query.all() if p.status != 'draft' and p.stage in R.WON]
    exp_rev = round(sum(billing.profit(p)['selling'] for p in won), 2)
    exp_profit = round(sum(billing.profit(p)['profit'] for p in won), 2)
    ok(f'reports: profit and revenue are the sum of the quotations, before GST ({rep["total"]["profit"]} / {rep["total"]["revenue"]})',
       abs(rep['total']['profit'] - exp_profit) < 0.01 and abs(rep['total']['revenue'] - exp_rev) < 0.01
       and rep['total']['margin'] == round(exp_profit / exp_rev * 100, 1))
    ok('reports: GST column = GST on issued invoices', abs(rep['total']['gst'] - round(sum(
        sum(t['amount'] for t in billing.invoice_data(i)['taxes']) for i in Invoice.query.filter_by(status='issued')), 2)) < 0.01)
t = c.get(f'/projects/{rahul.id}').text
ok('quotation page: "Price before GST" and how GST was taken out', 'Price before GST' in t and '&#8377;1,48,729' not in t
   and '&#8377;148,729' in t and 'includes GST, so GST is taken out' in t)

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

# Before the database update that adds edit access: sharing works, view-only
with app.app_context():
    db.session.execute(text('ALTER TABLE project_access DROP COLUMN can_edit')); db.session.commit()
from app import access as _acc
_acc._ready_forever.clear()
c3 = app.test_client(); c3.post('/login', data={'username': 'demo-admin', 'password': 'demo1234'})
s3 = app.test_client(); s3.post('/login', data={'username': 'demo-staff', 'password': 'demo1234'})
qid = new_quote(name='Pre Access', mobile='9000000333')
r = c3.post(f'/projects/{qid}/access', data={f'access_{st_id_}': 'edit'}, follow_redirects=True)
ok('before the update: sharing saves (as view), list and pages work', r.status_code == 200 and 'Access updated' in r.text
   and s3.get(f'/projects/{qid}').status_code == 200 and s3.get(f'/projects/{qid}/edit').status_code == 403
   and c3.get('/projects').status_code == 200)
