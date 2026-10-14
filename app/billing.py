"""
Quote to cash: quotation revisions, tax invoices, amounts due, payment reminders and profit.

Everything here lives in its own tables (QuoteRevision, Invoice, PaymentReminder, CostRate…), added by
one database update. Until that update has run (right after a deploy), ready() is False and the
features stay hidden, so a deploy never breaks a business that hasn't been updated yet.

Amounts are encrypted in the database, so totals are worked out in Python, never in SQL.
"""
import json
import re
from datetime import date, datetime

from . import db, tenancy

_ready_forever = {}


def ready():
    """True once the 'quote to cash' tables exist in this business's database."""
    schema = tenancy.current_schema() or ''
    if _ready_forever.get(schema):
        return True
    from flask import g, has_app_context
    if has_app_context() and '_billing_ready' in g:
        return g._billing_ready
    from sqlalchemy import inspect
    try:
        # the newest quote-to-cash column: everything before it exists too
        cols = inspect(db.session.connection()).get_columns('quote_shares', schema=tenancy.current_schema())
        found = any(c['name'] == 'detail' for c in cols)
    except Exception:
        found = False
    if found:
        _ready_forever[schema] = True
    if has_app_context():
        g._billing_ready = found
    return found


# ── Quotation snapshot (revisions, invoices, online approval) ───────────────

def _item_rates():
    from .models import ItemRate
    return {f'{r.wood_type}|{r.work_type}': r.rate_per_sqft for r in ItemRate.query.all()}


def quotation_snapshot(project, rooms=None):
    """Everything the customer is quoted, as plain data: customer, rooms and items with rates and amounts,
    the material summary and the totals. Uses the current rates (as the quotation pages do)."""
    from . import materials as M
    from .catalog import FIXED_ITEMS_LABEL
    rates = _item_rates()
    rooms = rooms if rooms is not None else project.rooms_with_items()
    out_rooms = []
    for room in rooms:
        items = []
        for i in room.item_list:
            if i.is_fixed:
                items.append({'name': i.name, 'type': 'fixed', 'quantity': round(i.quantity or 0, 4),
                              'unit_price': round(i.unit_price or 0, 2),
                              'amount': round((i.quantity or 0) * (i.unit_price or 0), 2)})
            else:
                rate = rates.get(f'{i.wood_type}|{i.work_type}', 0.0)
                items.append({'name': i.name, 'type': 'measured', 'length': i.length, 'width': i.width,
                              'area': round(i.area, 4), 'wood_type': i.wood_type, 'work_type': i.work_type,
                              'material': M.label(i.wood_type, i.work_type), 'rate': rate,
                              'amount': round(i.area * rate, 2)})
        out_rooms.append({'name': room.name, 'items': items})
    summary = []
    area_totals = project.get_item_totals(rooms)
    for key in M.ordered_keys(area_totals):
        area = area_totals.get(key, 0.0)
        if area > 0:
            rate = rates.get(key, 0.0)
            summary.append({'key': key, 'label': M.label_of(key), 'area': round(area, 2), 'rate': rate,
                            'amount': round(area * rate, 2)})
    fixed_total = project.fixed_items_total(rooms)
    return {
        'customer': {'name': project.customer_name, 'mobile': project.mobile,
                     'email': project.email or '', 'address': project.address or ''},
        'rooms': out_rooms,
        'summary': summary,
        'fittings_label': FIXED_ITEMS_LABEL,
        'fittings_total': round(fixed_total, 2),
        'subtotal': round(project.grand_total or 0, 2),
        'discount': {'type': project.discount_type or 'none', 'value': project.discount_value or 0,
                     'amount': project.discount_amount},
        'total': project.final_total,
        'plywood': project.plywood_thickness or '',
    }


# ── Revisions ────────────────────────────────────────────────────────────────

def revisions(project):
    from .models import QuoteRevision
    from sqlalchemy.orm import joinedload
    if not ready():
        return []
    return (QuoteRevision.query.options(joinedload(QuoteRevision.user)).filter_by(project_id=project.id)
            .order_by(QuoteRevision.number.desc()).all())


def latest_revision_number(project):
    from .models import QuoteRevision
    if not ready():
        return None
    last = (QuoteRevision.query.filter_by(project_id=project.id)
            .order_by(QuoteRevision.number.desc()).first())
    return last.number if last else None


def record_revision(project, user, when=None):
    """Save the quotation as it is now as the next revision, unless nothing changed since the last one.
    Returns the revision (new or unchanged latest) or None when the feature isn't ready."""
    from .models import QuoteRevision
    if not ready() or project.status == 'draft':
        return None
    snap = quotation_snapshot(project)
    last = (QuoteRevision.query.filter_by(project_id=project.id)
            .order_by(QuoteRevision.number.desc()).first())
    if last and json.loads(last.snapshot) == json.loads(json.dumps(snap)):
        return last
    rev = QuoteRevision(project_id=project.id, number=(last.number + 1) if last else 1,
                        created_by=user.id if user else None, created_at=when or datetime.utcnow(),
                        total=snap['total'], snapshot=json.dumps(snap))
    db.session.add(rev)
    db.session.flush()
    return rev


def ensure_first_revision(project, user):
    """Before a quotation made before revisions existed is edited, keep how it was as R1."""
    if ready() and project.status != 'draft' and latest_revision_number(project) is None:
        record_revision(project, project.creator or user, when=project.updated_at or project.created_at)


def _fmt_dim(feet):
    whole = int(feet)
    inches = round((feet - whole) * 12)
    if inches == 12:
        whole, inches = whole + 1, 0
    return f'{whole} ft' if not inches else f'{whole} ft {inches} in'


def _describe(item):
    if item['type'] == 'fixed':
        return f"{item['quantity']:g} × ₹{item['unit_price']:,.0f}"
    return f"{_fmt_dim(item['length'])} × {_fmt_dim(item['width'])}, {item['material']}"


def diff_snapshots(old, new):
    """Readable list of what changed between two snapshots."""
    changes = []
    old_rooms = {r['name']: r for r in old.get('rooms', [])}
    new_rooms = {r['name']: r for r in new.get('rooms', [])}
    for name in new_rooms:
        if name not in old_rooms:
            changes.append(f'Added room {name}')
    for name in old_rooms:
        if name not in new_rooms:
            changes.append(f'Removed room {name}')
    for name, room in new_rooms.items():
        if name not in old_rooms:
            continue
        before = {}
        for it in old_rooms[name]['items']:
            before.setdefault(it['name'], []).append(it)
        after = {}
        for it in room['items']:
            after.setdefault(it['name'], []).append(it)
        for item_name, items in after.items():
            prev = before.get(item_name, [])
            for idx, it in enumerate(items):
                if idx >= len(prev):
                    changes.append(f'{name}: added {item_name} ({_describe(it)})')
                elif _describe(prev[idx]) != _describe(it):
                    changes.append(f'{name}: {item_name} changed from {_describe(prev[idx])} to {_describe(it)}')
            for it in prev[len(items):]:
                changes.append(f'{name}: removed {item_name}')
    od, nd = old.get('discount', {}), new.get('discount', {})
    if round(od.get('amount', 0), 2) != round(nd.get('amount', 0), 2):
        changes.append(f"Discount ₹{od.get('amount', 0):,.0f} → ₹{nd.get('amount', 0):,.0f}")
    oc, nc = old.get('customer', {}), new.get('customer', {})
    for key, label in (('name', 'Customer name'), ('mobile', 'Mobile'), ('email', 'Email'), ('address', 'Address')):
        if (oc.get(key) or '') != (nc.get(key) or ''):
            changes.append(f'{label} changed')
    if not changes and round(old.get('total', 0), 2) != round(new.get('total', 0), 2):
        changes.append('Rates changed')
    if round(old.get('total', 0), 2) != round(new.get('total', 0), 2):
        changes.append(f"Total ₹{old.get('total', 0):,.2f} → ₹{new.get('total', 0):,.2f}")
    return changes


def revision_history(project):
    """[(revision, snapshot, changes vs previous)] newest first."""
    revs = list(reversed(revisions(project)))
    out, prev = [], None
    for r in revs:
        snap = json.loads(r.snapshot)
        out.append((r, snap, diff_snapshots(prev, snap) if prev is not None else []))
        prev = snap
    return list(reversed(out))


# ── Indian GST helpers ───────────────────────────────────────────────────────

STATES = {
    '01': 'Jammu and Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab', '04': 'Chandigarh', '05': 'Uttarakhand',
    '06': 'Haryana', '07': 'Delhi', '08': 'Rajasthan', '09': 'Uttar Pradesh', '10': 'Bihar', '11': 'Sikkim',
    '12': 'Arunachal Pradesh', '13': 'Nagaland', '14': 'Manipur', '15': 'Mizoram', '16': 'Tripura',
    '17': 'Meghalaya', '18': 'Assam', '19': 'West Bengal', '20': 'Jharkhand', '21': 'Odisha',
    '22': 'Chhattisgarh', '23': 'Madhya Pradesh', '24': 'Gujarat', '26': 'Dadra and Nagar Haveli and Daman and Diu',
    '27': 'Maharashtra', '29': 'Karnataka', '30': 'Goa', '31': 'Lakshadweep', '32': 'Kerala', '33': 'Tamil Nadu',
    '34': 'Puducherry', '35': 'Andaman and Nicobar Islands', '36': 'Telangana', '37': 'Andhra Pradesh',
    '38': 'Ladakh', '97': 'Other Territory',
}
GST_RATES = (0, 5, 12, 18, 28)
GSTIN_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')

# Invoice settings (Admin → Settings → Invoices), stored in app_settings
INVOICE_KEYS = ('invoice_prefix', 'invoice_gst_rate', 'invoice_hsn', 'invoice_prices', 'invoice_notes', 'invoice_with_gst',
                'invoice_layout')
DEFAULT_PREFIX = 'INV'
DEFAULT_GST_RATE = 18
PRICES_EXCLUSIVE = 'exclusive'      # quotation amounts are before GST (GST added on top)
PRICES_INCLUSIVE = 'inclusive'      # quotation amounts already include GST


def invoice_settings(values=None):
    """Invoice settings; `values` = already loaded app_settings (from get_many) to save a query."""
    from .models import AppSetting
    s = {k: (values or {}).get(k, '') for k in INVOICE_KEYS} if values is not None else AppSetting.get_many(list(INVOICE_KEYS))
    try:
        rate = float(s['invoice_gst_rate']) if s['invoice_gst_rate'] != '' else DEFAULT_GST_RATE
    except ValueError:
        rate = DEFAULT_GST_RATE
    return {
        'prefix': clean_prefix(s['invoice_prefix']) or DEFAULT_PREFIX,
        'gst_rate': rate if rate in GST_RATES else DEFAULT_GST_RATE,
        'hsn': (s['invoice_hsn'] or '').strip()[:10],
        'prices': s['invoice_prices'] if s['invoice_prices'] in (PRICES_EXCLUSIVE, PRICES_INCLUSIVE) else PRICES_EXCLUSIVE,
        'notes': (s['invoice_notes'] or '').strip(),
        'with_gst': s['invoice_with_gst'] != 'no',          # the usual choice; each invoice can still pick
        'layout': s['invoice_layout'] if s['invoice_layout'] in ('rooms', 'summary') else 'rooms',
    }


def clean_prefix(raw):
    """Invoice number prefix: up to 4 letters/digits, so numbers stay within GST's 16 characters."""
    return re.sub(r'[^A-Za-z0-9]', '', raw or '').upper()[:4]


def financial_year(day):
    """Indian financial year (April–March), e.g. 15 Oct 2026 → '2026-27'."""
    start = day.year if day.month >= 4 else day.year - 1
    return f'{start}-{(start + 1) % 100:02d}'


def next_invoice_number(day, prefix):
    from sqlalchemy import func, select
    from .models import Invoice
    fy = financial_year(day)
    seq = (db.session.scalar(select(func.max(Invoice.seq)).where(Invoice.fy == fy)) or 0) + 1
    return fy, seq, f'{prefix}/{fy}/{seq:03d}'


def business_state_code():
    from .branding import get_brand
    gstin = (get_brand().get('gstin') or '').strip().upper()
    return gstin[:2] if GSTIN_RE.match(gstin) and gstin[:2] in STATES else ''


_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve',
         'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _two(n):
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else ''))


def _three(n):
    out = []
    if n >= 100:
        out.append(_ONES[n // 100] + ' Hundred')
        n %= 100
    if n:
        out.append(_two(n))
    return ' '.join(out)


def words_indian(n):
    """Integer → words in the Indian system (lakh, crore): 1234567 → 'Twelve Lakh Thirty Four Thousand…'."""
    n = int(n)
    if n == 0:
        return 'Zero'
    parts = []
    crore, n = divmod(n, 10 ** 7)
    if crore:
        parts.append(words_indian(crore) + ' Crore')
    lakh, n = divmod(n, 10 ** 5)
    if lakh:
        parts.append(_two(lakh) + ' Lakh')
    thousand, n = divmod(n, 1000)
    if thousand:
        parts.append(_two(thousand) + ' Thousand')
    if n:
        parts.append(_three(n))
    return ' '.join(parts)


def rupees_in_words(amount):
    amount = round(float(amount or 0), 2)
    rupees = int(amount)
    paise = int(round((amount - rupees) * 100))
    text = f'Rupees {words_indian(rupees)}'
    if paise:
        text += f' and {words_indian(paise)} Paise'
    return text + ' Only'


# ── Invoices ─────────────────────────────────────────────────────────────────

class InvoiceError(Exception):
    pass


LAYOUT_ROOMS = 'rooms'          # every item, grouped by room (like the full quotation)
LAYOUT_SUMMARY = 'summary'      # one line per material & work, plus fittings


def invoice_lines(snapshot, hsn='', layout=LAYOUT_ROOMS):
    """Invoice lines from a quotation snapshot. Room by room: each item with its size, under its room
    ('room' on the line). Summary: one line per material & work (sqft) and one per fitting."""
    if layout == LAYOUT_ROOMS:
        lines = []
        for room in snapshot['rooms']:
            for it in room['items']:
                if it['type'] == 'fixed':
                    lines.append({'room': room['name'], 'description': it['name'], 'detail': '', 'hsn': hsn,
                                  'qty': it['quantity'], 'unit': 'nos', 'rate': it['unit_price'], 'amount': it['amount']})
                else:
                    lines.append({'room': room['name'], 'description': it['name'],
                                  'detail': f"{_fmt_dim(it['length'])} × {_fmt_dim(it['width'])} · {it['material']}",
                                  'hsn': hsn, 'qty': round(it['area'], 2), 'unit': 'sqft', 'rate': it['rate'],
                                  'amount': it['amount']})
        return lines
    lines = [{'description': s['label'], 'hsn': hsn, 'qty': s['area'], 'unit': 'sqft', 'rate': s['rate'],
              'amount': s['amount']} for s in snapshot['summary']]
    fittings = {}
    for room in snapshot['rooms']:
        for it in room['items']:
            if it['type'] == 'fixed':
                key = (it['name'], it['unit_price'])
                fittings[key] = fittings.get(key, 0) + it['quantity']
    for (name, price), qty in fittings.items():
        lines.append({'description': name, 'hsn': hsn, 'qty': round(qty, 4), 'unit': 'nos', 'rate': price,
                      'amount': round(qty * price, 2)})
    return lines


def build_invoice(project, issued_on, gst_rate, prices, customer_gstin='', place_code='', hsn='', notes='',
                  with_gst=True, layout=LAYOUT_ROOMS):
    """Work out an invoice for the quotation as it is now. Returns the frozen data dict.
    Without GST (chosen, or no GSTIN on the business) the invoice carries no GST details at all."""
    from .branding import get_brand
    brand = get_brand()
    snap = quotation_snapshot(project)
    seller_state = business_state_code()
    gst_registered = bool(seller_state) and with_gst
    if not gst_registered:
        customer_gstin, place_code, hsn = '', '', ''
    customer_gstin = (customer_gstin or '').strip().upper().replace(' ', '')
    if customer_gstin and not GSTIN_RE.match(customer_gstin):
        raise InvoiceError(f'"{customer_gstin}" doesn\'t look like a valid GSTIN (15 characters, e.g. 29ABCDE1234F1Z5).')
    if customer_gstin:
        place_code = customer_gstin[:2]
    place_code = (place_code if place_code in STATES else seller_state) if gst_registered else ''
    rate = float(gst_rate) if gst_registered else 0.0
    if rate not in GST_RATES:
        raise InvoiceError('Choose a GST rate.')

    layout = layout if layout in (LAYOUT_ROOMS, LAYOUT_SUMMARY) else LAYOUT_ROOMS
    lines = invoice_lines(snap, hsn, layout)
    gross = round(sum(l['amount'] for l in lines), 2)
    discount = round(snap['discount']['amount'] or 0, 2)
    after_discount = round(max(gross - discount, 0), 2)
    if rate and prices == PRICES_INCLUSIVE:
        taxable = round(after_discount / (1 + rate / 100), 2)
    else:
        taxable = after_discount
    intra = gst_registered and place_code == seller_state
    if not rate:
        taxes = []
    elif intra:
        half = round(taxable * rate / 200, 2)
        taxes = [{'label': f'CGST @ {rate / 2:g}%', 'amount': half}, {'label': f'SGST @ {rate / 2:g}%', 'amount': half}]
    else:
        taxes = [{'label': f'IGST @ {rate:g}%', 'amount': round(taxable * rate / 100, 2)}]
    before_round = round(taxable + sum(t['amount'] for t in taxes), 2)
    # Rounded to the rupee; with GST-inclusive prices the customer pays exactly the quoted price
    total = float(round(after_discount if rate and prices == PRICES_INCLUSIVE else before_round))
    return {
        'seller': {'name': brand['name'], 'address': brand.get('address') or '', 'phone': brand.get('phone') or '',
                   'email': brand.get('email') or '', 'gstin': (brand.get('gstin') or '') if gst_registered else '',
                   'state_code': seller_state if gst_registered else '',
                   'state': STATES.get(seller_state, '') if gst_registered else ''},
        'buyer': dict(snap['customer'], gstin=customer_gstin),
        'place_of_supply': {'code': place_code, 'state': STATES.get(place_code, '')},
        'title': 'TAX INVOICE' if gst_registered else 'INVOICE',
        'gst': gst_registered,
        'issued_on': issued_on.isoformat(),
        'quotation_id': project.id,
        'revision': latest_revision_number(project),
        'lines': lines,
        'gross': gross,
        'discount': discount,
        'discount_label': (f"Discount ({snap['discount']['value']:g}%)" if snap['discount']['type'] == 'percentage'
                           else 'Discount'),
        'taxable': taxable,
        'gst_rate': rate,
        'prices': prices,
        'layout': layout,
        'taxes': taxes,
        'round_off': round(total - before_round, 2),
        'total': total,
        'total_words': rupees_in_words(total),
        'notes': (notes or '').strip(),
        'signatory': {'name': brand.get('signatory_name') or '', 'title': brand.get('signatory_title') or ''},
    }


def issue_invoice(project, user, **kwargs):
    from .models import Invoice
    if not ready():
        raise InvoiceError('Invoices are available after the next database update.')
    if project.status == 'draft':
        raise InvoiceError('Save the quotation before invoicing it.')
    if active_invoice(project):
        raise InvoiceError('This quotation already has an invoice. Cancel it first to issue a new one.')
    if (project.final_total or 0) <= 0:
        raise InvoiceError('The quotation total is zero.')
    issued_on = kwargs.pop('issued_on', None) or date.today()
    settings = invoice_settings()
    data = build_invoice(project, issued_on, **kwargs)
    fy, seq, number = next_invoice_number(issued_on, settings['prefix'])
    inv = Invoice(project_id=project.id, number=number, fy=fy, seq=seq, issued_on=issued_on,
                  total=data['total'], data=json.dumps(data), created_by=user.id if user else None)
    db.session.add(inv)
    db.session.flush()
    return inv


def invoices(project):
    from .models import Invoice
    if not ready():
        return []
    return Invoice.query.filter_by(project_id=project.id).order_by(Invoice.created_at.desc()).all()


def active_invoice(project):
    from .models import Invoice
    if not ready():
        return None
    return (Invoice.query.filter_by(project_id=project.id, status='issued')
            .order_by(Invoice.created_at.desc()).first())


def invoice_data(invoice):
    data = json.loads(invoice.data)
    data.setdefault('gst', data.get('gst_registered', bool(data.get('taxes'))))   # invoices made before 'gst' existed
    return data


def invoice_message(project, invoice, url):
    """WhatsApp / email text sending the invoice link."""
    from .branding import get_brand
    from .demo import demo_enabled
    brand = get_brand()
    due = balance(project, invoice) if invoice.status == 'issued' else 0
    lines = [f'Hello {project.customer_name},', '',
             f'Here is your invoice {invoice.number} from {brand["name"]} for Rs.{invoice.total:,.2f}.']
    if due and due < invoice.total:
        lines.append(f'Amount due: Rs.{due:,.2f}')
    lines += ['', 'View and download it here:', url, '', 'Thank you for your business!']
    if demo_enabled():
        lines = ['*DEMO — NOT A REAL INVOICE*', ''] + lines
    return '\n'.join(lines)


def email_ready(values=None):
    """True when Admin → Settings → Email has an SMTP server, username and password."""
    from .models import AppSetting
    keys = ('smtp_host', 'smtp_user', 'smtp_pass')
    vals = values if values is not None else AppSetting.get_many(list(keys))
    return all((vals.get(k) or '').strip() for k in keys)


def quotation_email_text(project, link=''):
    from .branding import get_brand
    brand = get_brand()
    lines = [f'Hello {project.customer_name},', '',
             f'Thank you for considering {brand["name"]}. Please find your quotation #{project.id} attached '
             f'(total Rs.{project.final_total:,.2f}).']
    if link:
        lines += ['', 'You can also view it and accept it online:', link]
    lines += ['', 'Please reply to this email if you have any questions.', '', f'Regards,', brand['name']]
    if brand.get('phone'):
        lines.append(brand['phone'])
    return '\n'.join(lines)


# ── Amount due, payments, reminders ──────────────────────────────────────────

def amount_due_total(project, invoice=None):
    """What the customer owes in total: the invoice total once invoiced (it may include GST), else the quotation."""
    inv = invoice if invoice is not None else active_invoice(project)
    return round(inv.total, 2) if inv else project.final_total


def paid_total(project):
    from .models import Payment
    return round(sum(p.amount for p in Payment.query.filter_by(project_id=project.id)), 2)


def balance(project, invoice=None):
    return round(max(amount_due_total(project, invoice) - paid_total(project), 0), 2)


DUE_STAGES = ('confirmed', 'ongoing', 'completed', 'on_hold')


def balances_due(user):
    """Quotations with money still to collect (confirmed or later, or invoiced), biggest balance first."""
    from .models import Invoice, Payment, PaymentReminder, Project, ProjectAccess
    q = Project.query.filter(Project.status != 'draft')
    if not user.is_admin:
        ids = db.session.query(ProjectAccess.project_id).filter_by(user_id=user.id)
        q = q.filter(Project.id.in_(ids))
    projects = q.all()
    if not projects:
        return []
    ids = [p.id for p in projects]
    paid = {}
    for pay in Payment.query.filter(Payment.project_id.in_(ids)):
        paid[pay.project_id] = paid.get(pay.project_id, 0) + pay.amount
    invoiced, reminded = {}, {}
    if ready():
        for inv in Invoice.query.filter(Invoice.project_id.in_(ids), Invoice.status == 'issued'):
            if inv.project_id not in invoiced or inv.created_at > invoiced[inv.project_id].created_at:
                invoiced[inv.project_id] = inv
        for r in PaymentReminder.query.filter(PaymentReminder.project_id.in_(ids)):
            if r.project_id not in reminded or r.sent_at > reminded[r.project_id]:
                reminded[r.project_id] = r.sent_at
    rows = []
    for p in projects:
        inv = invoiced.get(p.id)
        if p.stage not in DUE_STAGES and not inv:
            continue
        total = round(inv.total, 2) if inv else p.final_total
        bal = round(max(total - paid.get(p.id, 0), 0), 2)
        if bal <= 0:
            continue
        rows.append({'project': p, 'invoice': inv, 'total': total, 'paid': round(paid.get(p.id, 0), 2),
                     'balance': bal, 'last_reminder': reminded.get(p.id)})
    rows.sort(key=lambda r: -r['balance'])
    return rows


def last_reminder(project):
    from .models import PaymentReminder
    if not ready():
        return None
    return (PaymentReminder.query.filter_by(project_id=project.id)
            .order_by(PaymentReminder.sent_at.desc()).first())


def whatsapp_number(mobile):
    digits = re.sub(r'\D', '', mobile or '')
    if len(digits) == 10:
        digits = '91' + digits
    return digits


def reminder_message(project, amount, pay_link='', pay_settings=None):
    from .branding import get_brand
    from .demo import demo_enabled
    brand = get_brand()
    inv = active_invoice(project)
    total = amount_due_total(project, inv)
    paid = paid_total(project)
    ref = f'Invoice {inv.number}' if inv else f'Quotation #{project.id}'
    lines = [f'Hello {project.customer_name},', '',
             f'This is a friendly reminder from *{brand["name"]}* about the payment for {ref}.', '',
             f'Total: Rs.{total:,.2f}']
    if paid:
        lines.append(f'Received so far: Rs.{paid:,.2f}')
    lines.append(f'*Amount due: Rs.{amount:,.2f}*')
    if pay_link:
        lines += ['', f'Pay online: {pay_link}']
    ps = pay_settings or {}
    if ps.get('upi_id'):
        lines.append(f'UPI: {ps["upi_id"]}')
    if ps.get('account_number'):
        lines.append(f'Bank: {ps.get("bank_name", "")} | {ps.get("account_name", "")} | '
                     f'A/C: {ps["account_number"]} | IFSC: {ps.get("ifsc_code", "")}')
    lines += ['', 'Please ignore this message if you have already paid. Thank you!']
    if demo_enabled():
        lines = ['*DEMO — NOT A REAL PAYMENT REQUEST*', ''] + lines
    return '\n'.join(lines)


# ── Costs & profit (admins only) ─────────────────────────────────────────────

def cost_rates():
    """{('material', 'Wood|Work'): cost per sqft, ('fitting', name lower-case): cost per unit}"""
    from .models import CostRate
    if not ready():
        return {}
    return {(c.kind, c.name if c.kind == 'material' else c.name.lower()): c.cost for c in CostRate.query.all()}


def profit(project, rooms=None):
    """Estimated cost and profit of a quotation, from Admin → Costs. None when no costs are set."""
    costs = cost_rates()
    if not costs:
        return None
    rooms = rooms if rooms is not None else project.rooms_with_items()
    total_cost, missing = 0.0, []
    for room in rooms:
        for i in room.item_list:
            if i.is_fixed:
                c = costs.get(('fitting', i.name.lower()))
                if c is None:
                    missing.append(f'{room.name}: {i.name}')
                else:
                    total_cost += (i.quantity or 0) * c
            else:
                c = costs.get(('material', f'{i.wood_type}|{i.work_type}'))
                if c is None:
                    missing.append(f'{room.name}: {i.name} ({i.wood_type}{" – " + i.work_type if i.work_type else ""})')
                else:
                    total_cost += i.area * c
    selling = project.final_total
    profit_ = round(selling - total_cost, 2)
    return {'selling': selling, 'cost': round(total_cost, 2), 'profit': profit_,
            'margin': round(profit_ / selling * 100, 1) if selling else 0.0, 'missing': missing}
