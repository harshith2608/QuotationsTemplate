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


REMINDERS_DDL = """
CREATE TABLE IF NOT EXISTS public.plan_reminders (
    slug     VARCHAR(40) NOT NULL,
    kind     VARCHAR(20) NOT NULL,
    ends_on  DATE        NOT NULL,
    sent_at  TIMESTAMP   NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (slug, kind, ends_on)
)
"""


def ensure_table():
    global _table_ready
    if not _table_ready:
        with db.engine.begin() as conn:
            conn.execute(text(DDL))
            conn.execute(text('ALTER TABLE public.platform_payments ADD COLUMN IF NOT EXISTS email VARCHAR(120)'))
            conn.execute(text("ALTER TABLE public.platform_payments ADD COLUMN IF NOT EXISTS kind VARCHAR(10) "
                              "NOT NULL DEFAULT 'checkout'"))          # checkout (in the app) / link / new (a new customer)
            conn.execute(text('ALTER TABLE public.platform_payments ADD COLUMN IF NOT EXISTS link_url TEXT'))
            conn.execute(text('ALTER TABLE public.platform_payments ADD COLUMN IF NOT EXISTS phone VARCHAR(20)'))
            conn.execute(text('ALTER TABLE public.platform_payments ADD COLUMN IF NOT EXISTS payer_name VARCHAR(120)'))
            conn.execute(text(REMINDERS_DDL))
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

def create_order(slug, plan, business_name='', paid_by='', email='', payer_name=''):
    """A Razorpay order for `plan` ('6m' / '1y'), remembered as "created". Returns the order row (dict)."""
    if plan not in LENGTHS:
        raise PaymentError('Choose the 6-month or 12-month plan.')
    ensure_table()
    amount = prices()[plan] * 100
    order = _api('POST', '/orders', {'amount': amount, 'currency': 'INR',
                                     'receipt': f'{slug}-{plan}-{int(datetime.utcnow().timestamp())}'[:40],
                                     'notes': {'slug': slug, 'plan': plan}})
    with db.engine.begin() as conn:
        conn.execute(text('INSERT INTO public.platform_payments (slug, plan, amount_paise, order_id, business_name, paid_by, '
                          'email, payer_name) VALUES (:s, :p, :a, :o, :n, :u, :e, :pn)'),
                     {'s': slug, 'p': plan, 'a': amount, 'o': order['id'], 'n': (business_name or '')[:120],
                      'u': (paid_by or '')[:80], 'e': (email or '')[:120] or None, 'pn': (payer_name or '').strip()[:120] or None})
    return get_by_order(order['id'])


def links_enabled():
    """The console can make payment links once it has the platform's Razorpay keys."""
    return bool(_env('PLATFORM_RAZORPAY_KEY_ID') and _env('PLATFORM_RAZORPAY_KEY_SECRET'))


def create_payment_link(slug, plan, business_name='', phone='', email='', kind='link', paid_by='console', payer_name='',
                        callback_url=None):
    """A Razorpay payment link for `plan` (sent by the operator on WhatsApp / email, or opened straight away by a
    business buying on the website). kind 'new': a customer whose app is made once they pay. callback_url: where
    Razorpay sends the payer back after paying. Returns the payment row (dict, with link_url)."""
    if plan not in LENGTHS:
        raise PaymentError('Choose the 6-month or 12-month plan.')
    if not links_enabled():
        raise PaymentError('Set PLATFORM_RAZORPAY_KEY_ID and PLATFORM_RAZORPAY_KEY_SECRET on the console first.')
    ensure_table()
    amount = prices()[plan] * 100
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    payer_name = (payer_name or '').strip()[:120]
    customer = {k: v for k, v in (('name', (payer_name or business_name or slug)[:60]), ('email', email or ''),
                                  ('contact', ('+' + digits) if digits else '')) if v}
    link = _api('POST', '/payment_links', {
        'amount': amount, 'currency': 'INR', 'accept_partial': False,
        'description': f'QuoteRoom {plan_mod.PLANS.get(plan, plan)} for {business_name or slug}'[:2048],
        'customer': customer, 'notify': {'sms': False, 'email': False}, 'reminder_enable': False,
        'notes': {'slug': slug, 'plan': plan, 'kind': kind},
        'expire_by': int(datetime.utcnow().timestamp()) + 7 * 86400,
        **({'callback_url': callback_url, 'callback_method': 'get'} if callback_url else {})})
    with db.engine.begin() as conn:
        conn.execute(text('INSERT INTO public.platform_payments (slug, plan, amount_paise, order_id, business_name, paid_by, '
                          'email, kind, link_url, phone, payer_name) VALUES (:s, :p, :a, :o, :n, :u, :e, :k, :l, :ph, :pn)'),
                     {'s': slug, 'p': plan, 'a': amount, 'o': link['id'], 'n': (business_name or '')[:120],
                      'u': paid_by[:80], 'e': (email or '')[:120] or None, 'k': kind, 'l': link.get('short_url'),
                      'ph': digits[:20] or None, 'pn': payer_name or None})
    return get_by_order(link['id'])


def _link_text(row, after=''):
    from . import texts
    return texts.render('pay_link', plan=plan_mod.PLANS.get(row['plan'], row['plan']),
                        amount=f'₹{row["amount_paise"] / 100:,.0f}', link=row['link_url'], after=after)


def link_message(row):
    """The WhatsApp / email text that goes with a payment link (console → Messages: "Payment link")."""
    after = ('Once it\'s paid we set up your app and send you your login.' if row.get('kind') == 'new' else
             'Once it\'s paid, your plan is active straight away: same address, same login, all your quotations.')
    return _link_text(row, after)[1]


def email_link(row, to):
    from . import mailer
    subject = _link_text(row)[0]
    return mailer.send(to, subject, 'Hello,\n\n' + link_message(row).replace('Hi! ', '') + '\n\nQuoteRoom\n',
                       bcc=mailer.sender())


def verify_checkout(order_id, payment_id, signature):
    """Razorpay Checkout's signature: HMAC-SHA256(order_id|payment_id) with the key secret."""
    secret = _env('PLATFORM_RAZORPAY_KEY_SECRET')
    expected = hmac.new(secret.encode(), f'{order_id}|{payment_id}'.encode(), hashlib.sha256).hexdigest()
    return bool(secret) and hmac.compare_digest(expected, signature or '')


def verify_link_callback(args):
    """The signature Razorpay adds when it sends a payer back from a payment link (callback_url):
    HMAC-SHA256(link id|reference id|status|payment id) with the key secret."""
    secret = _env('PLATFORM_RAZORPAY_KEY_SECRET')
    body = '|'.join(args.get(k, '') for k in ('razorpay_payment_link_id', 'razorpay_payment_link_reference_id',
                                                'razorpay_payment_link_status', 'razorpay_payment_id'))
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return bool(secret) and hmac.compare_digest(expected, args.get('razorpay_signature', ''))


def open_link(slug, plan):
    """An unpaid payment link made in the last 6 days for this business and plan (reused when they come back to pay)."""
    ensure_table()
    with db.engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM public.platform_payments WHERE slug = :s AND plan = :p AND status = 'created' "
                                "AND link_url IS NOT NULL AND created_at > (now() AT TIME ZONE 'utc') - INTERVAL '6 days' "
                                "ORDER BY id DESC LIMIT 1"), {'s': slug, 'p': plan}).mappings().first()
    return dict(row) if row else None


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


# ── Payments recorded by hand (paid outside Razorpay: UPI to you, bank transfer, cash) ──

MANUAL_METHODS = ['UPI', 'Bank transfer', 'Cash', 'Cheque', 'Other']


def _business_details(slug):
    """(company name, company email) from the business's own settings, or ('', '')."""
    from . import customers
    from .models import AppSetting
    target = tenancy.lookup(slug)
    try:
        if target and target[0] == 'schema':
            with tenancy.tenant_context(slug, target[1]):
                got = AppSetting.get_many(['company_name', 'company_email'])
        elif (customers.get(slug) or {}).get('status') == 'active':
            with customers.open_customer(slug):
                got = AppSetting.get_many(['company_name', 'company_email'])
        else:
            return '', ''
    except Exception:
        return '', ''
    return got.get('company_name') or '', got.get('company_email') or ''


def record_manual(slug, plan, amount, method, reference='', paid_on=None, add_plan=True, payer_name=''):
    """A payment received outside Razorpay, recorded from the console: counted under Payments with a receipt
    number like any other, and (add_plan) the plan added to their app the same way. Returns the payment row."""
    from datetime import time
    from . import customers
    if plan not in LENGTHS:
        raise PaymentError('Choose the 6-month or 12-month plan.')
    try:
        paise = int(round(float(amount) * 100))
    except (TypeError, ValueError):
        raise PaymentError('The amount should be a number.')
    if paise <= 0:
        raise PaymentError('The amount should be more than 0.')
    target = tenancy.lookup(slug)
    if not (target and target[0] == 'schema') and (customers.get(slug) or {}).get('status') != 'active':
        raise PaymentError(f'No trial or customer "{slug}".')
    method = method if method in MANUAL_METHODS else 'Other'
    when = datetime.combine(paid_on or plan_mod.today(), time(6, 30))          # 12:00 IST that day
    name, email = _business_details(slug)
    ensure_table()
    if not email:                                   # the email from their earlier payment or payment link
        with db.engine.connect() as conn:
            email = conn.execute(text("SELECT email FROM public.platform_payments WHERE slug = :s AND email IS NOT NULL "
                                      "ORDER BY id DESC LIMIT 1"), {'s': slug}).scalar() or ''
    with db.engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO public.platform_payments (slug, plan, amount_paise, order_id, payment_id, status, business_name, "
            "paid_by, source, paid_at, email, kind, payer_name) VALUES (:s, :p, :a, :o, :ref, 'paid', :n, :m, 'manual', "
            ":t, :e, 'manual', :pn) RETURNING id"),
            {'s': slug, 'p': plan, 'a': paise, 'o': 'manual_' + base64.b32encode(os.urandom(10)).decode().lower(),
             'ref': (reference or '').strip()[:40] or None, 'n': (name or slug)[:120], 'm': method, 't': when,
             'e': (email or '')[:120] or None, 'pn': (payer_name or '').strip()[:120] or None}).first()
        conn.execute(text('UPDATE public.platform_payments SET receipt_no = :r WHERE id = :i'),
                     {'r': f'QR{when:%y%m}-{row[0]:04d}', 'i': row[0]})
    pay = get(row[0])
    if add_plan:
        apply_plan_for(slug, pay)
    return get(row[0])


def set_payer_name(payment_row_id, name):
    with db.engine.begin() as conn:
        conn.execute(text('UPDATE public.platform_payments SET payer_name = :n WHERE id = :i'),
                     {'n': (name or '').strip()[:120] or None, 'i': payment_row_id})


def delete_payment(payment_row_id):
    """Remove a payment record (a test payment, one recorded by mistake). Their plan isn't changed. Returns the row."""
    row = get(payment_row_id)
    if row:
        with db.engine.begin() as conn:
            conn.execute(text('DELETE FROM public.platform_payments WHERE id = :i'), {'i': payment_row_id})
    return row


# ── Webhook (console) and moving paid trials ─────────────────────────────────

def handle_webhook(payload):
    """order.paid / payment.captured from Razorpay. Records the payment (once) and adds the plan. Returns a
    short result for the log. Moving the trial is separate (move_paid_trials)."""
    event = payload.get('event', '')
    pay = (payload.get('payload', {}).get('payment') or {}).get('entity') or {}
    order = (payload.get('payload', {}).get('order') or {}).get('entity') or {}
    plink = (payload.get('payload', {}).get('payment_link') or {}).get('entity') or {}
    if event == 'payment_link.paid':
        key = plink.get('id')                              # links are remembered by their own id
    elif event in ('order.paid', 'payment.captured'):
        key = order.get('id') or pay.get('order_id')
    else:
        return 'ignored'
    row = get_by_order(key) if key else None
    if row is None and pay.get('order_id') and key != pay.get('order_id'):
        row = get_by_order(pay['order_id'])
    if row is None:
        return 'not ours'
    row, newly = settle(row, pay.get('id') or row.get('payment_id') or '', 'webhook', payer_email=pay.get('email'))
    if not newly:
        return 'already recorded'
    return f'paid: {row["slug"]} {row["plan"]}'


def settle(row, payment_id, source, payer_email=None):
    """A payment Razorpay confirmed (webhook, or the payer sent back from a payment link): record it once, add the
    plan (or make a new customer's app), send the receipt. Returns (row, newly_paid)."""
    row, newly = mark_paid(row['order_id'], payment_id, source)
    if not newly:
        return row, False
    if not row.get('email') and '@' in (payer_email or ''):           # the payer's email from Razorpay, for the receipt
        with db.engine.begin() as conn:
            conn.execute(text('UPDATE public.platform_payments SET email = :e WHERE id = :i'),
                         {'e': payer_email[:120], 'i': row['id']})
    if row.get('kind') == 'new':                           # a new customer: make their app now (plan from today)
        from . import customers
        c = customers.activate_pending(row['slug'])
        if c and c.get('ends_on'):
            with db.engine.begin() as conn:
                conn.execute(text('UPDATE public.platform_payments SET plan_start = :a, plan_end = :b WHERE id = :i'),
                             {'a': plan_mod.today(), 'b': c['ends_on'], 'i': row['id']})
    else:
        apply_plan_for(row['slug'], row)
    notify_paid(get(row['id']))
    return get(row['id']), True


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
    """Move every paid trial (console tick, the webhook, Payments → Move now). Returns {slug: result}. Nothing until
    shared hosting is set up (customers.shared_ready): the paid trial keeps working as a trial meanwhile."""
    from . import customers
    out = {}
    if not customers.shared_ready():
        return out
    for slug in paid_trials():
        try:
            row = move_paid_trial(slug, log=log)
            out[slug] = row['status'] if row else 'not started'
        except Exception as exc:                        # keep going; the console shows what's left
            out[slug] = f'failed: {exc}'
    return out


# ── Emails: paid, reminders ──────────────────────────────────────────────────

def _app_link(slug, path=''):
    return f'https://{slug}.{tenancy.base_domain()}{path}'


def receipt_email(row):
    """Where the receipt goes: the email on the payment, else the business's email in its app."""
    if row.get('email') and '@' in row['email']:
        return row['email']
    from .models import AppSetting
    from . import ops
    try:
        with tenancy.tenant_context(row['slug'], ops.schema_of(row['slug'])):        # a trial (shared database)
            return AppSetting.get('company_email', '') or ''
    except Exception:
        pass
    try:
        from . import customers
        with customers.open_customer(row['slug']):                                   # a paying customer (console)
            return AppSetting.get('company_email', '') or ''
    except Exception:
        return ''


def send_receipt(row, to=None):
    """Email the receipt (with a copy to hello@, as app emails don't show in the mailbox's Sent folder). True if sent.
    to: another address (console → Payments → Email receipt)."""
    from . import mailer, texts
    to = to or receipt_email(row)
    if not to or not mailer.enabled():
        return False
    fmt = lambda d: d.strftime('%d %b %Y') if d else '—'
    first = (row.get('payer_name') or '').split(' ')[0]
    subject, body = texts.render('pay_receipt', hello=f'Hello {first}' if first else 'Hello',
                                 amount=f'₹{row["amount_paise"] / 100:,.0f}', plan=plan_mod.PLANS.get(row['plan'], row['plan']),
                                 business=row.get('business_name') or row['slug'], app=_app_link(row['slug']),
                                 plan_start=fmt(row.get('plan_start')), plan_end=fmt(row.get('plan_end')),
                                 receipt_no=row.get('receipt_no'))
    return mailer.send(to, subject, body, bcc=mailer.sender(),
                       attachments=[(f'QuoteRoom-receipt-{row["receipt_no"]}.pdf', receipt_pdf(row).read(), 'application/pdf')])


def notify_paid(row):
    """"You're on your paid plan" with the receipt (to the business's email), and a note to the operator."""
    from . import mailer
    if not row or not mailer.enabled():
        return
    fmt = lambda d: d.strftime('%d %b %Y') if d else '—'
    plan_label = plan_mod.PLANS.get(row['plan'], row['plan'])
    amount = f'₹{row["amount_paise"] / 100:,.0f}'
    name = row.get('business_name') or row['slug']
    sent = send_receipt(row)
    mailer.send(mailer.operator(), f'Payment: {amount} from {name}',
                f'{name} ({row["slug"]}){" · " + row["payer_name"] if row.get("payer_name") else ""} paid {amount} for the {plan_label}.\n'
                f'Receipt {row.get("receipt_no")} · payment {row.get("payment_id")} · via {row.get("source")}\n'
                f'Plan until {fmt(row.get("plan_end"))}.\n'
                + (f'Receipt emailed to {receipt_email(row)} (a copy is in this mailbox).\n' if sent else
                   'No email address to send the receipt to: send it from console → Payments.\n'))


REMINDERS = {   # kind → (subject, first line): the defaults; the texts sent are console → Messages (app/texts.py)
    'trial_2':   ('Your QuoteRoom free trial ends {when}',
                  'Your free trial ends {when} ({end}). Choose a plan to keep everything you have set up and keep quoting.'),
    'trial_end': ('Your QuoteRoom free trial has ended',
                  'Your free trial ended on {end}, so your app is now read-only. Choose a plan to carry on: everything is '
                  'still there until {delete}.'),
    'paid_15':   ('Your QuoteRoom plan ends on {end}',
                  'Your {plan} ends on {end}. Renew now and the new period starts when this one ends, so no days are lost.'),
    'paid_3':    ('Your QuoteRoom plan ends {when}',
                  'Your {plan} ends {when} ({end}). Renew to keep creating quotations without a break.'),
    'paid_end':  ('Your QuoteRoom plan has ended',
                  'Your {plan} ended on {end}. You can keep working until {grace}; after that your app becomes '
                  'read-only. Renew to carry on.'),
}


def due_reminder(status):
    """Which reminder (if any) this plan is due for today."""
    if not status.has_limit or status.days_left is None:
        return None
    d = status.days_left
    if status.is_trial:
        return 'trial_2' if 0 <= d <= 2 else 'trial_end' if -3 <= d < 0 else None
    return 'paid_3' if 0 <= d <= 3 else 'paid_15' if 3 < d <= 15 else 'paid_end' if -7 <= d < 0 else None


def send_reminders():
    """Daily (console tick): one email per business per reminder and plan end date. Returns {slug: kind}."""
    from . import customers, mailer
    from .models import AppSetting
    if not mailer.enabled():
        return {}
    ensure_table()
    targets = [(r['slug'], (lambda r=r: tenancy.tenant_context(r['slug'], r['schema_name'])))
               for r in tenancy.registry_rows() if r['status'] == 'active']
    if customers._env('CONSOLE_VAULT_KEY'):
        targets += [(c['slug'], (lambda c=c: customers.open_customer(c['slug'])))
                    for c in customers.all_customers() if c['status'] == 'active']
    out = {}
    for slug, opener in targets:
        try:
            with opener():
                st = plan_mod.load_status(on=plan_mod.today())
                kind = due_reminder(st)
                email = AppSetting.get('company_email', '') if kind else ''
            if not kind or not email:
                continue
            with db.engine.begin() as conn:
                fresh = conn.execute(text('INSERT INTO public.plan_reminders (slug, kind, ends_on) VALUES (:s, :k, :e) '
                                          'ON CONFLICT DO NOTHING RETURNING slug'),
                                     {'s': slug, 'k': kind, 'e': st.ends_on}).first()
            if not fresh:
                continue                                   # already sent for this end date
            fmt = lambda d: d.strftime('%d %b %Y') if d else ''
            when = 'today' if st.days_left == 0 else 'tomorrow' if st.days_left == 1 else f'in {st.days_left} days'
            words = dict(when=when, end=fmt(st.ends_on), plan=st.label, grace=fmt(st.grace_until),
                         delete=fmt(st.delete_on))
            p = prices()
            from . import texts
            subject, body = texts.render(f'remind_{kind}', plan_link=_app_link(slug, '/plan'), price_6m=f"{p['6m']:,}",
                                         price_1y=f"{p['1y']:,}", **words)
            mailer.send(email, subject, body)
            out[slug] = kind
        except Exception as exc:                           # one business's problem mustn't stop the others
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
            *([['Name', row['payer_name'], '', '']] if row.get('payer_name') else []),
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
           Paragraph((f'Paid by {escape(row.get("paid_by") or "transfer")}. ' if row.get('source') == 'manual'
                      else 'Paid online through Razorpay. ') + 'This is a payment receipt, not a tax invoice: '
                     f'{escape(who["name"])} is not registered under GST, so no GST is charged.', small),
           Spacer(1, 6), Paragraph('Thank you for choosing QuoteRoom.', small)]
    doc.build(el)
    buf.seek(0)
    return buf


def proforma_no(row):
    """'PF2610-0007': the proforma for payment link 7 (made in Oct 2026)."""
    made = row.get('created_at') or datetime.utcnow()
    return f"PF{made:%y%m}-{row['id']:04d}"


def proforma_pdf(row, bill_to='', address=''):
    """A proforma invoice for a payment link, before they pay: what the plan costs and how to pay. Not a tax invoice
    (the platform isn't registered under GST yet); the payment receipt follows by email once they pay."""
    from datetime import timedelta
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape
    who = issuer()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=f'Proforma invoice {proforma_no(row)}')
    st = getSampleStyleSheet()
    small = ParagraphStyle('s', parent=st['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#455a64'))
    body = ParagraphStyle('b', parent=st['Normal'], fontSize=10, leading=14)
    dark = colors.HexColor('#163a30')
    made = row.get('created_at') or datetime.utcnow()
    fmt = lambda d: d.strftime('%d %b %Y')
    rupees = lambda p: f'Rs. {p / 100:,.2f}'
    plan_label = plan_mod.PLANS.get(row['plan'], row['plan'])
    contact = ' · '.join(x for x in (who['address'], who['email'], who['phone']) if x)
    title = ParagraphStyle('t', parent=st['Normal'], fontSize=18, leading=24, textColor=dark)
    el = [Paragraph(f'<b>{escape(who["name"])}</b>', title),
          Paragraph(escape(contact), small) if contact else Spacer(1, 1), Spacer(1, 18),
          Paragraph('<b>Proforma invoice</b>', ParagraphStyle('h', parent=st['Normal'], fontSize=14, leading=18)),
          Paragraph('Not a GST invoice', ParagraphStyle('h2', parent=small, textColor=colors.HexColor('#b42318'))),
          Spacer(1, 10)]
    to = escape(bill_to or row.get('business_name') or row['slug'])
    if row.get('payer_name'):
        to += '<br/>' + escape(row['payer_name'])
    if address:
        to += '<br/>' + escape(address).replace('\n', '<br/>')
    info = [['Proforma no.', proforma_no(row), 'Date', fmt(made)],
            [Paragraph('<b>To</b>', ParagraphStyle('k', parent=body, fontSize=9, textColor=dark)),
             Paragraph(to, ParagraphStyle('v', parent=body, fontSize=9, leading=12)), 'Valid until', fmt(made + timedelta(days=7))],
            ['App', f'{row["slug"]}.{tenancy.base_domain()}', '', '']]
    t = Table(info, colWidths=[3 * cm, 7 * cm, 2.5 * cm, 4.5 * cm])
    t.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('TEXTCOLOR', (0, 0), (0, -1), dark),
                           ('TEXTCOLOR', (2, 0), (2, -1), dark), ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                           ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                           ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    el += [t, Spacer(1, 16)]
    months = '6 months' if row['plan'] == '6m' else '12 months'
    lines = [['Description', 'Amount'],
             [Paragraph(f'<b>QuoteRoom {escape(plan_label)}</b><br/><font size="8" color="#455a64">'
                        f'Quotation app for your whole team, all features, for {months}. '
                        'If you are on a free trial, the plan starts when the trial ends.</font>', body),
              rupees(row['amount_paise'])],
             ['GST', 'Not charged'],
             ['Total to pay', rupees(row['amount_paise'])]]
    lt = Table(lines, colWidths=[13 * cm, 4 * cm])
    lt.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), dark), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 10),
                            ('ALIGN', (1, 0), (1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                            ('LINEBELOW', (0, 1), (-1, 2), 0.5, colors.lightgrey),
                            ('FONTNAME', (0, 3), (-1, 3), 'Helvetica-Bold'), ('PADDING', (0, 0), (-1, -1), 7)]))
    el += [lt, Spacer(1, 16)]
    if row.get('link_url') and row.get('status') != 'paid':
        el += [Paragraph('<b>How to pay</b>', body),
               Paragraph(f'Online (UPI, card or net banking): <link href="{escape(row["link_url"])}" color="#1f4d3f">'
                         f'{escape(row["link_url"])}</link>', body), Spacer(1, 12)]
    el += [Paragraph('<b>Please note</b>', body),
           Paragraph('This is a proforma invoice: it shows what you will pay, before you pay. It is <b>not a GST '
                     f'(tax) invoice</b>. {escape(who["name"])} is not registered under GST, so no GST is charged and '
                     'there is no GST credit to claim on this payment.', small),
           Spacer(1, 4),
           Paragraph('Once you pay, you get a payment receipt by email.', small),
           Spacer(1, 10), Paragraph('Thank you for choosing QuoteRoom.', small)]
    doc.build(el)
    buf.seek(0)
    return buf
