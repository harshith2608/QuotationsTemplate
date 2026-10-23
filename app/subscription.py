"""Paid plans bought inside the app: the business pays QuoteRoom (the platform's own Razorpay account) for 6 or 12
months, and the plan is active straight away. A trial that pays is then moved to its own database by the console
(customers.py, shared hosting), with the plan it bought.

Shared trials app (TENANT_MODE) settings:
    PLATFORM_RAZORPAY_KEY_ID, PLATFORM_RAZORPAY_KEY_SECRET     the platform's Razorpay API keys (live or test)
    PLATFORM_LEGAL_NAME, PLATFORM_ADDRESS, PLATFORM_EMAIL, PLATFORM_PHONE   who issues the receipt
    PLAN_PRICE_6M=4999, PLAN_PRICE_1Y=8999                   optional: prices in rupees (no GST: not registered)
Console settings:
    PLATFORM_RAZORPAY_WEBHOOK_SECRET    the webhook (order.paid → /billing/razorpay-webhook on the console) records a
                                        payment whose browser closed before returning, and starts the move
    AUTO_MOVE_PAID_TRIALS=0             optional: don't move paid trials automatically (move them from Payments)

Payments are kept in public.platform_payments (the trials database). A payment counts once: it turns from
"created" to "paid" in one UPDATE, whichever of the browser or the webhook gets there first.
"""
import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from io import BytesIO

from sqlalchemy import text

from . import db, tenancy
from . import plan as plan_mod

API = 'https://api.razorpay.com/v1'
LENGTHS = {'6m': '6m', '1y': '1y'}
DDL = """
CREATE TABLE IF NOT EXISTS public.platform_payments (
    id            SERIAL       PRIMARY KEY,
    slug          VARCHAR(40)  NOT NULL,
    plan          VARCHAR(10)  NOT NULL,
    amount_paise  INTEGER      NOT NULL,
    order_id      VARCHAR(40)  NOT NULL UNIQUE,
    payment_id    VARCHAR(40)  UNIQUE,
    status        VARCHAR(12)  NOT NULL DEFAULT 'created',     -- created / paid
    receipt_no    VARCHAR(30)  UNIQUE,
    business_name VARCHAR(120),
    paid_by       VARCHAR(80),
    plan_start    DATE,
    plan_end      DATE,
    source        VARCHAR(12),                                 -- app / webhook
    created_at    TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    paid_at       TIMESTAMP
)
"""


class PaymentError(Exception):
    pass


def _env(name, default=''):
    return (os.environ.get(name) or default).strip()


def prices():
    """{'6m': 4999, '1y': 8999} in rupees."""
    return {'6m': int(_env('PLAN_PRICE_6M', '4999')), '1y': int(_env('PLAN_PRICE_1Y', '8999'))}


def enabled():
    """Paying in the app is on in the shared app once the platform's Razorpay keys are set."""
    return tenancy.tenant_mode() and bool(_env('PLATFORM_RAZORPAY_KEY_ID') and _env('PLATFORM_RAZORPAY_KEY_SECRET'))


_table_ready = False


def ensure_table():
    global _table_ready
    if not _table_ready:
        with db.engine.begin() as conn:
            conn.execute(text(DDL))
        _table_ready = True


def _api(method, path, payload=None):
    key, secret = _env('PLATFORM_RAZORPAY_KEY_ID'), _env('PLATFORM_RAZORPAY_KEY_SECRET')
    auth = base64.b64encode(f'{key}:{secret}'.encode()).decode()
    req = urllib.request.Request(API + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={'Content-Type': 'application/json', 'Authorization': f'Basic {auth}'},
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read()).get('error', {}).get('description')
        except ValueError:
            message = None
        raise PaymentError(message or f'Razorpay error (HTTP {exc.code}).')
    except urllib.error.URLError as exc:
        raise PaymentError(f'Could not reach Razorpay ({exc.reason}).')


# ── Buying ───────────────────────────────────────────────────────────────────

def create_order(slug, plan, business_name='', paid_by=''):
    """A Razorpay order for `plan` ('6m' / '1y'), remembered as "created". Returns the order row (dict)."""
    if plan not in LENGTHS:
        raise PaymentError('Choose the 6-month or 12-month plan.')
    ensure_table()
    amount = prices()[plan] * 100
    order = _api('POST', '/orders', {'amount': amount, 'currency': 'INR',
                                     'receipt': f'{slug}-{plan}-{int(datetime.utcnow().timestamp())}'[:40],
                                     'notes': {'slug': slug, 'plan': plan}})
    with db.engine.begin() as conn:
        conn.execute(text('INSERT INTO public.platform_payments (slug, plan, amount_paise, order_id, business_name, paid_by) '
                          'VALUES (:s, :p, :a, :o, :n, :u)'),
                     {'s': slug, 'p': plan, 'a': amount, 'o': order['id'], 'n': (business_name or '')[:120],
                      'u': (paid_by or '')[:80]})
    return get_by_order(order['id'])


def verify_checkout(order_id, payment_id, signature):
    """Razorpay Checkout's signature: HMAC-SHA256(order_id|payment_id) with the key secret."""
    secret = _env('PLATFORM_RAZORPAY_KEY_SECRET')
    expected = hmac.new(secret.encode(), f'{order_id}|{payment_id}'.encode(), hashlib.sha256).hexdigest()
    return bool(secret) and hmac.compare_digest(expected, signature or '')


def verify_webhook(body, signature):
    secret = _env('PLATFORM_RAZORPAY_WEBHOOK_SECRET')
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(secret) and hmac.compare_digest(expected, signature or '')


def get_by_order(order_id):
    ensure_table()
    with db.engine.connect() as conn:
        row = conn.execute(text('SELECT * FROM public.platform_payments WHERE order_id = :o'), {'o': order_id}).mappings().first()
    return dict(row) if row else None


def get(payment_row_id):
    ensure_table()
    with db.engine.connect() as conn:
        row = conn.execute(text('SELECT * FROM public.platform_payments WHERE id = :i'), {'i': payment_row_id}).mappings().first()
    return dict(row) if row else None


def history(slug=None, limit=200):
    ensure_table()
    sql = 'SELECT * FROM public.platform_payments WHERE status = \'paid\'' + (' AND slug = :s' if slug else '') + \
          ' ORDER BY paid_at DESC LIMIT :l'
    with db.engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), {'s': slug, 'l': limit}).mappings()]


def mark_paid(order_id, payment_id, source):
    """Record the payment once. Returns (row, newly_paid): newly_paid is False if it was already recorded."""
    ensure_table()
    with db.engine.begin() as conn:
        row = conn.execute(text("UPDATE public.platform_payments SET status = 'paid', payment_id = :p, source = :src, "
                                "paid_at = (now() AT TIME ZONE 'utc') WHERE order_id = :o AND status = 'created' "
                                "RETURNING id, paid_at"), {'o': order_id, 'p': payment_id, 'src': source}).first()
        if row:
            conn.execute(text('UPDATE public.platform_payments SET receipt_no = :r WHERE id = :i'),
                         {'r': f'QR{row[1]:%y%m}-{row[0]:04d}', 'i': row[0]})
    return get_by_order(order_id), row is not None


def apply_plan(row):
    """Add the paid plan to the business open now (the current request's database; caller has app context).
    On time it extends from the end date, so remaining trial days or plan days are not lost. Commits."""
    status = plan_mod.renew(LENGTHS[row['plan']])
    db.session.commit()
    with db.engine.begin() as conn:
        conn.execute(text('UPDATE public.platform_payments SET plan_start = :a, plan_end = :b WHERE id = :i'),
                     {'a': status.started_on, 'b': status.ends_on, 'i': row['id']})
    return status


def apply_plan_for(slug, row):
    """apply_plan for a business from the console: a trial (its schema) or a paying customer (their database)."""
    from . import customers
    target = tenancy.lookup(slug)
    if target and target[0] == 'schema':
        with tenancy.tenant_context(slug, target[1]):
            return apply_plan(row)
    c = customers.get(slug)
    if c and c['status'] == 'active':
        with customers.open_customer(slug):
            status = plan_mod.renew(LENGTHS[row['plan']])
            db.session.commit()
        with db.engine.begin() as conn:
            conn.execute(text('UPDATE public.platform_payments SET plan_start = :a, plan_end = :b WHERE id = :i'),
                         {'a': status.started_on, 'b': status.ends_on, 'i': row['id']})
        customers._update(slug, ends_on=status.ends_on, plan=status.plan)
        return status
    raise PaymentError(f'No trial or customer "{slug}" to add the plan to.')


# ── Webhook (console) and moving paid trials ─────────────────────────────────

def handle_webhook(payload):
    """order.paid / payment.captured from Razorpay. Records the payment (once) and adds the plan. Returns a
    short result for the log. Moving the trial is separate (move_paid_trials)."""
    event = payload.get('event', '')
    pay = (payload.get('payload', {}).get('payment') or {}).get('entity') or {}
    order = (payload.get('payload', {}).get('order') or {}).get('entity') or {}
    order_id = order.get('id') or pay.get('order_id')
    if event not in ('order.paid', 'payment.captured') or not order_id:
        return 'ignored'
    row = get_by_order(order_id)
    if row is None:
        return 'not our order'
    row, newly = mark_paid(order_id, pay.get('id') or row.get('payment_id') or '', 'webhook')
    if newly:
        apply_plan_for(row['slug'], row)
        return f'paid: {row["slug"]} {row["plan"]}'
    return 'already recorded'


def paid_trials():
    """Slugs of trials that have paid but still run as a trial (to move to their own database)."""
    ensure_table()
    tenancy.ensure_registry()
    with db.engine.connect() as conn:
        return [r[0] for r in conn.execute(text(
            "SELECT DISTINCT p.slug FROM public.platform_payments p JOIN public.tenants t ON t.slug = p.slug "
            "WHERE p.status = 'paid' AND t.status IN ('active', 'moving')"))]


def move_paid_trial(slug, log=None):
    """Move a paid trial to its own database (shared hosting), keeping the plan it bought. Returns the customer row."""
    from . import customers
    from .models import AppSetting
    existing = customers.get(slug)
    if existing and existing['status'] not in ('deleted',):
        return customers.resume(slug, log=log)          # started before: carry on where it stopped
    with db.engine.connect() as conn:
        last = conn.execute(text("SELECT plan, business_name FROM public.platform_payments WHERE slug = :s AND "
                                 "status = 'paid' ORDER BY paid_at DESC LIMIT 1"), {'s': slug}).first()
    target = tenancy.lookup(slug)
    name, phone = (last[1] if last else '') or slug, ''
    if target and target[0] == 'schema':
        with tenancy.tenant_context(slug, target[1]):
            got = AppSetting.get_many(['company_name', 'company_mobile'])
            name = got['company_name'] or name
            phone = ''.join(ch for ch in got['company_mobile'] if ch.isdigit())[:15]
    return customers.start(slug, name, last[0] if last else '1y', source_trial=slug, phone=phone, hosting='shared',
                           keep_plan=True)


def auto_move():
    return _env('AUTO_MOVE_PAID_TRIALS', '1') not in ('0', 'false', 'no', 'off')


def move_all_paid(log=None):
    """Move every paid trial (console tick, the webhook, Payments → Move now). Returns {slug: result}."""
    from . import customers
    out = {}
    for slug in paid_trials():
        try:
            row = move_paid_trial(slug, log=log)
            out[slug] = row['status'] if row else 'not started'
        except Exception as exc:                        # keep going; the console shows what's left
            out[slug] = f'failed: {exc}'
    return out


# ── Receipt ──────────────────────────────────────────────────────────────────

def issuer():
    return {'name': _env('PLATFORM_LEGAL_NAME', 'QuoteRoom'), 'address': _env('PLATFORM_ADDRESS'),
            'email': _env('PLATFORM_EMAIL'), 'phone': _env('PLATFORM_PHONE')}


def receipt_pdf(row):
    """A payment receipt (not a GST invoice: the platform isn't registered under GST yet)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape
    who = issuer()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    st = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=st['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#455a64'))
    dark = colors.HexColor('#163a30')
    fmt = lambda d: d.strftime('%d %b %Y') if d else '—'
    rupees = lambda p: f'Rs. {p / 100:,.2f}'
    plan_label = plan_mod.PLANS.get(row['plan'], row['plan'])
    period = f'{fmt(row.get("plan_start"))} – {fmt(row.get("plan_end"))}' if row.get('plan_end') else '—'
    contact = ' · '.join(x for x in (who['address'], who['email'], who['phone']) if x)
    title = ParagraphStyle('t', parent=st['Normal'], fontSize=18, leading=24, textColor=colors.HexColor('#163a30'))
    el = [Paragraph(f'<b>{escape(who["name"])}</b>', title),
          Paragraph(escape(contact), small) if contact else Spacer(1, 1), Spacer(1, 18),
          Paragraph('<b>Payment receipt</b>', ParagraphStyle('h', parent=st['Normal'], fontSize=14, leading=18)),
          Spacer(1, 10)]
    info = [['Receipt no.', row.get('receipt_no') or '—', 'Date', fmt(row.get('paid_at'))],
            ['Received from', row.get('business_name') or row['slug'], 'App', f'{row["slug"]}.{tenancy.base_domain()}'],
            ['Payment ID', row.get('payment_id') or '—', 'Paid by', row.get('paid_by') or '—']]
    t = Table(info, colWidths=[3 * cm, 5.5 * cm, 2.5 * cm, 6 * cm])
    t.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('TEXTCOLOR', (0, 0), (0, -1), dark),
                           ('TEXTCOLOR', (2, 0), (2, -1), dark), ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                           ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    el += [t, Spacer(1, 16)]
    lines = [['Description', 'Period', 'Amount'],
             [f'QuoteRoom {plan_label}', period, rupees(row['amount_paise'])],
             ['', 'Total received', rupees(row['amount_paise'])]]
    lt = Table(lines, colWidths=[8 * cm, 5 * cm, 4 * cm])
    lt.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), dark), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 10),
                            ('ALIGN', (2, 0), (2, -1), 'RIGHT'), ('LINEBELOW', (0, 1), (-1, 1), 0.5, colors.grey),
                            ('FONTNAME', (1, 2), (-1, 2), 'Helvetica-Bold'), ('PADDING', (0, 0), (-1, -1), 7)]))
    el += [lt, Spacer(1, 18),
           Paragraph('Paid online through Razorpay. This is a payment receipt, not a tax invoice: '
                     f'{escape(who["name"])} is not registered under GST, so no GST is charged.', small),
           Spacer(1, 6), Paragraph('Thank you for choosing QuoteRoom.', small)]
    doc.build(el)
    buf.seek(0)
    return buf
