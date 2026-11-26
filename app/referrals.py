"""Refer & earn: paying customers bring in new businesses and earn a share of what those businesses pay.

How it works
  1. A paying business that has paid for at least `min_months` (console setting) applies from Admin → Refer & earn:
     name, phone, city, business (filled in from its app, editable), email, UPI or bank details and PAN. Nothing
     starts until the operator approves it in the console (Refer & earn).
  2. Approved, it gets a code (QR + 4 digits, e.g. QR2345; the operator can change it) and a link to the website's
     trial form with the code filled in. A business that signs up with the code gets a longer free trial
     (`trial_days`, 14) and is linked to the partner (public.partner_referrals).
  3. Every payment a referred business makes (public.platform_payments) for `earn_months` months from its first
     payment (the partner's own, else the default; 0 = no limit) earns the partner `pct` % of it (the partner's own %, else the default 30), while
     the partner's own plan is active. sync() records each payment once (public.partner_earnings), with why one
     didn't count; the operator can leave any out (misuse) with a reason the partner sees.
  4. At the end of each month a partner owed at least `payout_min` (₹1,000) is paid by the operator (UPI / bank),
     who marks it paid (public.partner_payouts). Less than that carries over.

Amounts: the payment as charged (no GST is charged today). When GST is charged, the commission is worked out on the
amount before GST if `before_gst` is on (console setting; the payment's GST is then left out).

A partner's own signup with its code doesn't count (same phone number), and a business already linked keeps its
first partner. All tables live in the trials database's public schema, which the console and the shared app (trials
and paying customers on shared hosting) both use. Postgres only (the shared app is).
"""
import json
import random
import re
from datetime import date, datetime

from sqlalchemy import text

from . import db

LEAD_REF_KEY = 'lead_ref_{}'           # the website's app_settings: the code typed on a trial request
KEY = 'referrals'                     # public.console_state (the console, the shared app) / the website's app_settings
DEFAULTS = {'on': False, 'pct': 30.0, 'earn_months': 12, 'min_months': 2, 'payout_min': 1000, 'trial_days': 14,
            'before_gst': True}
CODE_RE = re.compile(r'^[A-Z0-9]{4,10}$')
PAN_RE = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')
IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
UPI_RE = re.compile(r'^[\w.\-]{2,256}@[A-Za-z][\w.\-]{1,64}$')
STATUSES = {'applied': 'Waiting for approval', 'approved': 'Approved', 'rejected': 'Not approved',
            'stopped': 'Stopped'}
EARNING = {'earned': 'Counts', 'outside': 'After the earning period', 'inactive': 'Your plan wasn\'t active',
           'excluded': 'Left out', 'refunded': 'Refunded'}

DDL = [
    """CREATE TABLE IF NOT EXISTS public.partners (
        slug        VARCHAR(40)  PRIMARY KEY,
        status      VARCHAR(12)  NOT NULL DEFAULT 'applied',
        code        VARCHAR(12)  UNIQUE,
        pct         NUMERIC(5,2),
        name        VARCHAR(80)  NOT NULL DEFAULT '',
        phone       VARCHAR(20)  NOT NULL DEFAULT '',
        city        VARCHAR(60)  NOT NULL DEFAULT '',
        business    VARCHAR(120) NOT NULL DEFAULT '',
        email       VARCHAR(120) NOT NULL DEFAULT '',
        payout      TEXT,
        note        TEXT,
        applied_at  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
        decided_at  TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS public.partner_referrals (
        slug        VARCHAR(40)  PRIMARY KEY,
        partner     VARCHAR(40)  NOT NULL,
        code        VARCHAR(12)  NOT NULL,
        business    VARCHAR(120) NOT NULL DEFAULT '',
        lead_id     INTEGER,
        created_at  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
    )""",
    """CREATE TABLE IF NOT EXISTS public.partner_earnings (
        id            SERIAL       PRIMARY KEY,
        payment_id    INTEGER      NOT NULL UNIQUE,
        partner       VARCHAR(40)  NOT NULL,
        slug          VARCHAR(40)  NOT NULL,
        paid_at       TIMESTAMP,
        amount_paise  INTEGER      NOT NULL DEFAULT 0,
        pct           NUMERIC(5,2) NOT NULL DEFAULT 0,
        earned_paise  INTEGER      NOT NULL DEFAULT 0,
        status        VARCHAR(12)  NOT NULL DEFAULT 'earned',
        reason        TEXT,
        created_at    TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
    )""",
    """CREATE TABLE IF NOT EXISTS public.partner_waivers (
        slug        VARCHAR(40)  PRIMARY KEY,
        created_at  TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
    )""",
    """CREATE TABLE IF NOT EXISTS public.partner_payouts (
        id            SERIAL       PRIMARY KEY,
        partner       VARCHAR(40)  NOT NULL,
        amount_paise  INTEGER      NOT NULL,
        paid_on       DATE         NOT NULL,
        reference     VARCHAR(80)  NOT NULL DEFAULT '',
        note          TEXT,
        created_at    TIMESTAMP    NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
    )""",
]

_ready = False


class ReferralError(Exception):
    pass


def ensure_tables():
    global _ready
    if not _ready:
        with db.engine.begin() as conn:
            for ddl in DDL:
                conn.execute(text(ddl))
            conn.execute(text('ALTER TABLE public.partners ADD COLUMN IF NOT EXISTS earn_months INTEGER'))   # their own period
        _ready = True


# ── Settings (the console's Refer & earn) ─────────────────────────────────────

def _num(value, default, lo, hi, cast=float):
    try:
        v = cast(str(value).strip())
    except (TypeError, ValueError):
        return default
    return v if lo <= v <= hi else default


def parse(found):
    found = found if isinstance(found, dict) else {}
    return {'on': bool(found.get('on', DEFAULTS['on'])),
            'pct': _num(found.get('pct'), DEFAULTS['pct'], 0, 100),
            'earn_months': _num(found.get('earn_months'), DEFAULTS['earn_months'], 0, 120, int),
            'min_months': _num(found.get('min_months'), DEFAULTS['min_months'], 0, 60, int),
            'payout_min': _num(found.get('payout_min'), DEFAULTS['payout_min'], 0, 1_000_000, int),
            'trial_days': _num(found.get('trial_days'), DEFAULTS['trial_days'], 1, 90, int),
            'before_gst': bool(found.get('before_gst', DEFAULTS['before_gst']))}


def settings():
    """The console's settings: in the console and the shared app from public.console_state, on the website from its
    own copy."""
    from . import platform_switch
    try:
        raw = platform_switch.shared(KEY)
        return parse(json.loads(raw) if raw else {})
    except Exception:
        return parse({})


def validate(form):
    """(settings, errors) from the console's form."""
    errors = []
    out = {'on': form.get('on') == '1', 'before_gst': form.get('before_gst') == '1'}
    for field, lo, hi, cast, label in (('pct', 0, 100, float, 'Default share (%)'),
                                       ('earn_months', 0, 120, int, 'Months a partner earns from a business'),
                                       ('min_months', 0, 60, int, 'Months paid before applying'),
                                       ('payout_min', 0, 1_000_000, int, 'Smallest payout (₹)'),
                                       ('trial_days', 1, 90, int, 'Free trial days with a code')):
        try:
            v = cast(str(form.get(field, '')).strip())
            if not lo <= v <= hi:
                raise ValueError
            out[field] = v
        except (TypeError, ValueError):
            errors.append(f'{label}: enter a number from {lo} to {hi}.')
    return parse(out), errors


def available():
    """Refer & earn is offered in this app: the shared app, switched on in the console."""
    from . import tenancy
    return tenancy.tenant_mode() and settings()['on']


# ── Codes ─────────────────────────────────────────────────────────────────────

def clean_code(raw):
    """'qr 2345' → 'QR2345'; '' when it isn't a code's shape."""
    code = re.sub(r'[\s\-]', '', str(raw or '')).upper()[:12]
    return code if CODE_RE.match(code) else ''


def new_code():
    """QR + 4 digits not taken yet (QR1212, QR2345…)."""
    ensure_tables()
    with db.engine.connect() as conn:
        taken = {r[0] for r in conn.execute(text('SELECT code FROM public.partners WHERE code IS NOT NULL'))}
    for _ in range(2000):
        code = f'QR{random.randint(1000, 9999)}'
        if code not in taken:
            return code
    raise ReferralError('No free code left: type one.')


# ── Partners ──────────────────────────────────────────────────────────────────

def _row(r):
    if not r:
        return None
    d = dict(r._mapping)
    d['pct'] = float(d['pct']) if d.get('pct') is not None else None
    return d


def get(slug):
    ensure_tables()
    with db.engine.connect() as conn:
        return _row(conn.execute(text('SELECT * FROM public.partners WHERE slug = :s'), {'s': slug}).first())


def by_code(code):
    code = clean_code(code)
    if not code:
        return None
    ensure_tables()
    with db.engine.connect() as conn:
        return _row(conn.execute(text("SELECT * FROM public.partners WHERE code = :c"), {'c': code}).first())


def all_partners():
    ensure_tables()
    with db.engine.connect() as conn:
        return [_row(r) for r in conn.execute(text('SELECT * FROM public.partners ORDER BY applied_at DESC'))]


def pct_of(partner):
    return partner['pct'] if partner and partner.get('pct') is not None else settings()['pct']


def months_of(partner):
    """How many months (from a referred business's first payment) this partner earns from it: theirs, else the
    default; 0 = no limit."""
    return partner['earn_months'] if partner and partner.get('earn_months') is not None else settings()['earn_months']


def earning_text(partner=None):
    """'50% of every payment, for 12 months from the business's first payment' (or 'for as long as it pays')."""
    pct = pct_of(partner) if partner else settings()['pct']
    months = months_of(partner) if partner else settings()['earn_months']
    p = f'{pct:g}%'
    span = (f'for {months} month{"s" if months != 1 else ""} from its first payment' if months
            else 'for as long as it keeps paying')
    return p, span


def _seal_keys():
    """Keys that seal payout details, first used to seal: the console's vault key, else the trials database's own
    key (DATA_ENCRYPTION_KEY; the console and the trials app share both, and QA has no vault key)."""
    import os
    return [k for k in ((os.environ.get('CONSOLE_VAULT_KEY') or '').strip(),
                        (os.environ.get('DATA_ENCRYPTION_KEY') or '').strip()) if k]


def seal(data):
    from . import crypto
    keys = _seal_keys()
    if not keys:
        raise ReferralError('Payout details can\'t be stored here (no encryption key).')
    with crypto.using_key(keys[0]):
        return crypto.encrypt(json.dumps(data))


def unseal(blob):
    from . import crypto
    for key in _seal_keys():
        try:
            with crypto.using_key(key):
                return json.loads(crypto.decrypt(blob))
        except Exception:
            continue
    return {}


def payout_details(partner):
    """{'upi', 'bank_name', 'account_name', 'account_number', 'ifsc', 'pan'} (sealed: seal())."""
    try:
        return unseal(partner.get('payout')) if partner and partner.get('payout') else {}
    except Exception:
        return {}


def _paid_rows(conn, slug):
    """A business's paid plan payments (not AI add-ons), oldest first."""
    return conn.execute(text(
        "SELECT id, plan, amount_paise, COALESCE(refunded_paise, 0) AS refunded, paid_at, plan_start, plan_end "
        "FROM public.platform_payments WHERE slug = :s AND status = 'paid' ORDER BY paid_at, id"), {'s': slug}).all()


def plan_active(slug, on=None):
    """Is this business's own plan paid up today (or on `on`)? From its payments' plan dates, and the console's
    customer record (a plan renewed by hand)."""
    on = on or _today()
    with db.engine.connect() as conn:
        rows = _paid_rows(conn, slug) if _has('platform_payments', conn) else []
        end = max([r.plan_end for r in rows if r.plan_end and r.plan != 'ai40' and r.refunded < r.amount_paise]
                  or [None], default=None)
        if _has('customers', conn):
            c = conn.execute(text('SELECT ends_on, status FROM public.customers WHERE slug = :s'), {'s': slug}).first()
            if c and c.ends_on and c.status == 'active' and (end is None or c.ends_on > end):
                end = c.ends_on
    return bool(end and end >= on)


def paid_since(slug):
    """The day this business's first paid plan started, or None."""
    with db.engine.connect() as conn:
        if not _has('platform_payments', conn):
            return None
        rows = [r for r in _paid_rows(conn, slug) if r.plan != 'ai40' and r.refunded < r.amount_paise]
    starts = [r.plan_start or (r.paid_at.date() if r.paid_at else None) for r in rows]
    starts = [s for s in starts if s]
    return min(starts) if starts else None


def _today():
    """Today in India."""
    from datetime import timedelta
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


def _months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


def waived(slug):
    """The operator let this business apply before its months on a paid plan are up."""
    ensure_tables()
    with db.engine.connect() as conn:
        return conn.execute(text('SELECT 1 FROM public.partner_waivers WHERE slug = :s'), {'s': slug}).first() is not None


def waivers():
    ensure_tables()
    with db.engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text('SELECT * FROM public.partner_waivers ORDER BY created_at DESC'))]


def set_waiver(slug, on):
    ensure_tables()
    with db.engine.begin() as conn:
        if on:
            conn.execute(text('INSERT INTO public.partner_waivers (slug) VALUES (:s) ON CONFLICT (slug) DO NOTHING'),
                         {'s': slug})
        else:
            conn.execute(text('DELETE FROM public.partner_waivers WHERE slug = :s'), {'s': slug})


def eligibility(slug, today=None):
    """(can apply, why not). A waived business needs only an active paid plan, not the months."""
    today = today or _today()
    need = settings()['min_months']
    since = paid_since(slug)
    if since and plan_active(slug, today) and waived(slug):
        return True, ''
    if not since:
        return False, f'Refer & earn opens once you\'ve been on a paid plan for {need} month{"s" if need != 1 else ""}.'
    if not plan_active(slug, today):
        return False, 'Refer & earn is for businesses on an active paid plan. Renew your plan to apply.'
    done = _months_between(since, today)
    if done < need:
        left = need - done
        return False, (f'You can apply after {need} month{"s" if need != 1 else ""} on a paid plan: '
                       f'{left} more month{"s" if left != 1 else ""} to go.')
    return True, ''


def _has(table, conn):
    return conn.execute(text(f"SELECT to_regclass('public.{table}')")).scalar() is not None


def clean_application(form):
    """(values, {field: error}) from the application form."""
    v = {k: ' '.join(str(form.get(k) or '').split()) for k in ('name', 'city', 'business', 'email', 'upi', 'bank_name',
                                                                 'account_name', 'account_number', 'ifsc', 'pan')}
    from .marketing import normalise_phone
    v['phone'] = normalise_phone(form.get('phone'))
    v['upi'] = v['upi'].replace(' ', '')
    v['account_number'] = re.sub(r'\D', '', v['account_number'])
    v['ifsc'] = v['ifsc'].replace(' ', '').upper()
    v['pan'] = v['pan'].replace(' ', '').upper()
    e = {}
    if len(v['name']) < 2:
        e['name'] = 'Enter your name.'
    if not v['phone']:
        e['phone'] = 'Enter your 10-digit mobile number.'
    if len(v['city']) < 2:
        e['city'] = 'Enter your city.'
    if len(v['business']) < 2:
        e['business'] = 'Enter your business name.'
    if v['email'] and not re.match(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$', v['email']):
        e['email'] = 'Check your email address.'
    if v['upi'] and not UPI_RE.match(v['upi']):
        e['upi'] = 'Check your UPI ID (like name@okbank).'
    bank = v['account_number'] or v['ifsc']
    if bank and not (6 <= len(v['account_number']) <= 20):
        e['account_number'] = 'Check the account number.'
    if bank and not IFSC_RE.match(v['ifsc']):
        e['ifsc'] = 'Check the IFSC code (11 characters, like HDFC0001234).'
    if not v['upi'] and not bank:
        e['upi'] = 'Add a UPI ID or bank account, so we can pay you.'
    if not PAN_RE.match(v['pan']):
        e['pan'] = 'Enter your PAN (like ABCDE1234F): needed for payouts.'
    if form.get('agree') != '1':
        e['agree'] = 'Please accept the Refer & earn terms.'
    for k, n in (('name', 80), ('city', 60), ('business', 120), ('email', 120), ('bank_name', 80), ('account_name', 80)):
        v[k] = v[k][:n]
    return v, e


def apply(slug, values):
    """Save (or update, while waiting) an application. A rejected or stopped partner can apply again."""
    ensure_tables()
    current = get(slug)
    if current and current['status'] == 'approved':
        raise ReferralError('You\'re already a partner.')
    payout = seal({k: values.get(k, '') for k in ('upi', 'bank_name', 'account_name', 'account_number',
                                                   'ifsc', 'pan')})
    params = {'s': slug, 'n': values['name'], 'p': values['phone'], 'c': values['city'], 'b': values['business'],
              'e': values.get('email') or '', 'pay': payout}
    with db.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO public.partners (slug, status, name, phone, city, business, email, payout) "
            "VALUES (:s, 'applied', :n, :p, :c, :b, :e, :pay) ON CONFLICT (slug) DO UPDATE SET status = 'applied', "
            "name = :n, phone = :p, city = :c, business = :b, email = :e, payout = :pay, note = NULL, "
            "applied_at = (now() AT TIME ZONE 'utc'), decided_at = NULL"), params)
    return get(slug)


def set_payout_details(slug, values):
    """An approved partner updates where they're paid (UPI / bank, PAN)."""
    payout = seal({k: values.get(k, '') for k in ('upi', 'bank_name', 'account_name', 'account_number',
                                                   'ifsc', 'pan')})
    with db.engine.begin() as conn:
        conn.execute(text('UPDATE public.partners SET payout = :p WHERE slug = :s'), {'p': payout, 's': slug})


def approve(slug, code=None, pct=None, months=None):
    """Approve: their code (given or a new QR####), their % and earning months (None: the defaults)."""
    p = get(slug)
    if not p:
        raise ReferralError('No application from this business.')
    code = clean_code(code) if code else (p.get('code') or new_code())
    if not code:
        raise ReferralError('A code is 4–10 letters or digits, like QR2345.')
    other = by_code(code)
    if other and other['slug'] != slug:
        raise ReferralError(f'{code} is already {other["business"] or other["slug"]}\'s code.')
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE public.partners SET status = 'approved', code = :c, pct = :p, earn_months = :m, "
                          "note = NULL, decided_at = (now() AT TIME ZONE 'utc') WHERE slug = :s"),
                     {'c': code, 'p': pct, 'm': months, 's': slug})
    return get(slug)


def decide(slug, status, note=''):
    """Reject an application, or stop / restart an approved partner (their code stops / starts working)."""
    if status not in ('rejected', 'stopped', 'approved'):
        raise ReferralError('Unknown status.')
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE public.partners SET status = :st, note = :n, decided_at = (now() AT TIME ZONE 'utc') "
                          "WHERE slug = :s"), {'st': status, 'n': (note or '').strip()[:500] or None, 's': slug})


def update(slug, code=None, pct=None, months=None):
    """Change a partner's code, % or earning months (pct / months None: the default)."""
    if code is not None:
        code = clean_code(code)
        if not code:
            raise ReferralError('A code is 4–10 letters or digits, like QR2345.')
        other = by_code(code)
        if other and other['slug'] != slug:
            raise ReferralError(f'{code} is already {other["business"] or other["slug"]}\'s code.')
    with db.engine.begin() as conn:
        if code is not None:
            conn.execute(text('UPDATE public.partners SET code = :c WHERE slug = :s'), {'c': code, 's': slug})
        conn.execute(text('UPDATE public.partners SET pct = :p, earn_months = :m WHERE slug = :s'),
                     {'p': pct, 'm': months, 's': slug})


# ── Signing up with a code ────────────────────────────────────────────────────

def check_signup(code, phone=''):
    """(the approved partner whose code this is, or None; why not)."""
    if not settings()['on']:
        return None, 'Refer & earn is switched off'
    p = by_code(code)
    if not p:
        return None, f'no partner has the code {clean_code(code) or code}'
    if p['status'] != 'approved':
        return None, f'{p["code"]} belongs to {p["business"] or p["slug"]}, who is {STATUSES[p["status"]].lower()}'
    from .marketing import normalise_phone
    if phone and p.get('phone') and normalise_phone(phone) == normalise_phone(p['phone']):
        return None, f'the same phone number as the partner {p["business"] or p["slug"]} (a self-referral)'
    if not plan_active(p['slug']):
        return None, f'the partner {p["business"] or p["slug"]}\'s own plan isn\'t active'
    return p, ''


def partner_for_signup(code, phone=''):
    """The approved partner whose code this is, or None (unknown or stopped code; the partner's own number; their
    own plan lapsed)."""
    return check_signup(code, phone)[0]


def link(slug, partner, business='', lead_id=None):
    """Link a new trial to the partner that referred it (a business already linked keeps its first partner)."""
    ensure_tables()
    if slug == partner['slug']:
        return False
    with db.engine.begin() as conn:
        made = conn.execute(text(
            'INSERT INTO public.partner_referrals (slug, partner, code, business, lead_id) VALUES (:s, :p, :c, :b, :l) '
            'ON CONFLICT (slug) DO NOTHING RETURNING slug'),
            {'s': slug, 'p': partner['slug'], 'c': partner['code'], 'b': (business or '')[:120], 'l': lead_id}).first()
    return bool(made)


def referrals(partner_slug):
    """The businesses a partner referred, newest first: [{slug, business, created_at, state}], state: 'trial' (not
    paid yet), 'paying' (plan active), 'ended' (paid before, not now) or 'closed' (the trial is gone)."""
    ensure_tables()
    with db.engine.connect() as conn:
        rows = conn.execute(text('SELECT * FROM public.partner_referrals WHERE partner = :p ORDER BY created_at DESC'),
                            {'p': partner_slug}).all()
        exists = {r[0] for r in conn.execute(text('SELECT slug FROM public.tenants'))} if _has('tenants', conn) else set()
        if _has('customers', conn):
            exists |= {r[0] for r in conn.execute(text("SELECT slug FROM public.customers WHERE status = 'active'"))}
    out = []
    for r in rows:
        d = dict(r._mapping)
        if paid_since(d['slug']):
            d['state'] = 'paying' if plan_active(d['slug']) else 'ended'
        else:
            d['state'] = 'trial' if d['slug'] in exists else 'closed'
        out.append(d)
    return out


# ── Earnings and payouts ──────────────────────────────────────────────────────

def _add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    import calendar
    y, m = d.year + y, m + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def _ist(when):
    """A stored UTC time's date in India (plan dates are India dates)."""
    from datetime import timedelta
    return (when + timedelta(hours=5, minutes=30)).date()


def sync():
    """Record every new paid payment by a referred business, once: what it earns the partner, or why it doesn't
    count. A refund since is noted on the earning (it no longer counts). Returns how many were added."""
    ensure_tables()
    s = settings()
    added = 0
    with db.engine.connect() as conn:
        if not _has('platform_payments', conn):
            return 0
        refs = conn.execute(text('SELECT slug, partner FROM public.partner_referrals')).all()
        known = {r[0]: r for r in conn.execute(text('SELECT payment_id, status, amount_paise FROM public.partner_earnings'))}
    partners = {p['slug']: p for p in all_partners()}
    for ref in refs:
        p = partners.get(ref.partner)
        if not p:
            continue
        with db.engine.connect() as conn:
            rows = _paid_rows(conn, ref.slug)
        if not rows:
            continue
        first = min((r.paid_at for r in rows if r.paid_at), default=None)
        months = months_of(p)
        until = _add_months(_ist(first), months) if first and months else None
        for r in rows:
            fully_refunded = r.refunded >= r.amount_paise
            if r.id in known:
                if fully_refunded and known[r.id].status == 'earned':
                    with db.engine.begin() as conn:
                        conn.execute(text("UPDATE public.partner_earnings SET status = 'refunded', earned_paise = 0, "
                                          "reason = 'The payment was refunded.' WHERE payment_id = :i"), {'i': r.id})
                continue
            amount = r.amount_paise - r.refunded
            pct = pct_of(p)
            status, reason = 'earned', None
            if fully_refunded:
                status, reason = 'refunded', 'The payment was refunded.'
            elif until and r.paid_at and _ist(r.paid_at) >= until:
                status, reason = 'outside', f'Paid after the {months} month{"s" if months != 1 else ""} you earn from this business.'
            elif not plan_active(p['slug'], _ist(r.paid_at) if r.paid_at else None):
                status, reason = 'inactive', 'Your own plan wasn\'t active when they paid.'
            elif p['status'] != 'approved':
                status, reason = 'inactive', 'You weren\'t an active partner when they paid.'
            earned = round(amount * pct / 100) if status == 'earned' else 0
            with db.engine.begin() as conn:
                made = conn.execute(text(
                    'INSERT INTO public.partner_earnings (payment_id, partner, slug, paid_at, amount_paise, pct, '
                    'earned_paise, status, reason) VALUES (:i, :p, :s, :at, :a, :pct, :e, :st, :r) '
                    'ON CONFLICT (payment_id) DO NOTHING RETURNING id'),
                    {'i': r.id, 'p': p['slug'], 's': ref.slug, 'at': r.paid_at, 'a': amount, 'pct': pct, 'e': earned,
                     'st': status, 'r': reason}).first()
            added += 1 if made else 0
    return added


def earnings(partner_slug):
    ensure_tables()
    with db.engine.connect() as conn:
        rows = conn.execute(text(
            'SELECT e.*, r.business FROM public.partner_earnings e LEFT JOIN public.partner_referrals r ON r.slug = e.slug '
            'WHERE e.partner = :p ORDER BY e.paid_at DESC, e.id DESC'), {'p': partner_slug}).all()
    return [dict(r._mapping, pct=float(r.pct)) for r in rows]


def exclude(earning_id, reason):
    """Leave a payment out (misuse, a business that left…): the partner sees the reason."""
    reason = (reason or '').strip()[:300] or 'Left out after review.'
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE public.partner_earnings SET status = 'excluded', earned_paise = 0, reason = :r "
                          "WHERE id = :i"), {'r': reason, 'i': earning_id})


def include(earning_id):
    """Count a payment left out by mistake again (at the % it was recorded at)."""
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE public.partner_earnings SET status = 'earned', reason = NULL, "
                          "earned_paise = ROUND(amount_paise * pct / 100) WHERE id = :i AND status = 'excluded'"),
                     {'i': earning_id})


def payouts(partner_slug=None):
    ensure_tables()
    with db.engine.connect() as conn:
        q = 'SELECT * FROM public.partner_payouts' + (' WHERE partner = :p' if partner_slug else '') + \
            ' ORDER BY paid_on DESC, id DESC'
        return [dict(r._mapping) for r in conn.execute(text(q), {'p': partner_slug})]


def totals(partner_slug, today=None):
    """{'earned', 'paid', 'balance', 'this_month'} in paise (this month: India's calendar month)."""
    from datetime import timedelta
    today = today or _today()
    ensure_tables()
    with db.engine.connect() as conn:
        earned = conn.execute(text("SELECT COALESCE(SUM(earned_paise), 0) FROM public.partner_earnings "
                                   "WHERE partner = :p AND status = 'earned'"), {'p': partner_slug}).scalar()
        month = conn.execute(text("SELECT COALESCE(SUM(earned_paise), 0) FROM public.partner_earnings WHERE partner = :p "
                                  "AND status = 'earned' AND paid_at >= :m"),
                             {'p': partner_slug, 'm': datetime(today.year, today.month, 1) - timedelta(hours=5, minutes=30)}).scalar()
        paid = conn.execute(text('SELECT COALESCE(SUM(amount_paise), 0) FROM public.partner_payouts WHERE partner = :p'),
                            {'p': partner_slug}).scalar()
    return {'earned': int(earned), 'paid': int(paid), 'balance': int(earned) - int(paid), 'this_month': int(month)}


def due(today=None):
    """Partners to pay now: approved, owed at least the smallest payout. [(partner, totals)]"""
    floor = settings()['payout_min'] * 100
    out = []
    for p in all_partners():
        if p['status'] != 'approved':
            continue
        t = totals(p['slug'], today)
        if t['balance'] >= max(floor, 1):
            out.append((p, t))
    return out


def mark_paid(partner_slug, amount_rupees, reference='', paid_on=None, note=''):
    try:
        paise = round(float(str(amount_rupees).replace(',', '')) * 100)
    except (TypeError, ValueError):
        raise ReferralError('Enter the amount paid.')
    if paise <= 0:
        raise ReferralError('Enter the amount paid.')
    with db.engine.begin() as conn:
        conn.execute(text('INSERT INTO public.partner_payouts (partner, amount_paise, paid_on, reference, note) '
                          'VALUES (:p, :a, :d, :r, :n)'),
                     {'p': partner_slug, 'a': paise, 'd': paid_on or _today(), 'r': (reference or '')[:80],
                      'n': (note or '').strip()[:300] or None})


def delete_payout(payout_id):
    with db.engine.begin() as conn:
        conn.execute(text('DELETE FROM public.partner_payouts WHERE id = :i'), {'i': payout_id})


def product():
    import os
    return (os.environ.get('MARKETING_PRODUCT_NAME') or 'QuoteRoom').strip()


def site_url():
    """The website (MARKETING_SITE_URL, else www. + the trials' base domain; on QA the base domain itself:
    qa.quote-room.co.in)."""
    import os
    from . import qa, tenancy
    base = tenancy.base_domain() if tenancy.tenant_mode() else ''
    www = '' if qa.enabled() else 'www.'
    site = os.environ.get('MARKETING_SITE_URL') or (f'https://{www}{base}' if base else 'https://www.quote-room.co.in')
    return site.strip().rstrip('/')


def signup_link(code):
    """The website's trial form with the code filled in."""
    return f'{site_url()}/free-trial?ref={code}'
