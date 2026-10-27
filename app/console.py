"""
Operator console: manage trials (and trial requests) with buttons instead of terminal commands.

Runs as its OWN Vercel project (never inside a customer or trials app):

    CONSOLE_MODE=1
    DATABASE_URL=<trials pooled URL>          DATA_ENCRYPTION_KEY=<trials key>
    TENANT_BASE_DOMAIN=quote-room.co.in
    CONSOLE_PASSWORD_HASH=...  CONSOLE_TOTP_SECRET=...   (from `flask console-setup`)
    LEADS_DATABASE_URL=<demo pooled URL>      LEADS_DATA_ENCRYPTION_KEY=<demo key>   (optional: trial requests)
    MARKETING_PRODUCT_NAME=QuoteRoom          (optional, used in the welcome message)
    MARKETING_SITE_URL=https://www.quote-room.co.in   (optional, for "View on the site" links)

Tutorials (the marketing site's videos) live in the demo database too, so they need LEADS_DATABASE_URL.

Sign-in needs the password AND a 6-digit code from an authenticator app (TOTP, RFC 6238).
5 failed sign-ins in 15 minutes lock sign-in for 15 minutes. Every action is written to
public.console_audit in the trials database. In console mode the app serves nothing else.
"""
import base64
import hashlib
import hmac
import os
import re
import struct
import time
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, session,
                   url_for)
from sqlalchemy import create_engine, text
from werkzeug.security import check_password_hash

from . import db, ops, tenancy
from . import plan as plan_mod

console_bp = Blueprint('console', __name__, template_folder='../templates')

SESSION_HOURS = 12
MAX_FAILURES, LOCK_MINUTES = 5, 15
EXTEND_CHOICES = ['3d', '7d', '14d', '30d']

CONSOLE_DDL = [
    """CREATE TABLE IF NOT EXISTS public.signups (
        lead_id    INTEGER PRIMARY KEY,
        slug       VARCHAR(40) NOT NULL,
        ip_hash    VARCHAR(64),
        created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
    )""",
    """CREATE TABLE IF NOT EXISTS public.console_audit (
        id      SERIAL PRIMARY KEY,
        at      TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
        action  VARCHAR(40) NOT NULL,
        target  VARCHAR(80),
        detail  TEXT,
        ip      VARCHAR(64))""",
    """CREATE TABLE IF NOT EXISTS public.console_state (
        key     VARCHAR(40) PRIMARY KEY,
        value   TEXT)""",
    """CREATE TABLE IF NOT EXISTS public.console_lead_links (
        lead_id    INTEGER PRIMARY KEY,
        status     VARCHAR(20) NOT NULL,          -- 'trial' or 'dismissed'
        slug       VARCHAR(40),
        updated_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'))""",
]


def console_mode():
    return (os.environ.get('CONSOLE_MODE') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _env(name, default=''):
    return (os.environ.get(name) or default).strip()


# ── TOTP (authenticator app codes) ───────────────────────────────────────────

def _b32(secret):
    secret = re.sub(r'\s', '', secret).upper()
    return base64.b32decode(secret + '=' * (-len(secret) % 8))


def totp_code(secret, counter):
    digest = hmac.new(_b32(secret), struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f'{value % 1_000_000:06d}'


def totp_match(secret, code, now=None, window=1):
    """The time-step counter the code matches (±1 step of 30 s), or None."""
    code = re.sub(r'\D', '', code or '')
    if len(code) != 6:
        return None
    counter = int((now or time.time()) // 30)
    for c in range(counter - window, counter + window + 1):
        if hmac.compare_digest(totp_code(secret, c), code):
            return c
    return None


def new_totp_secret():
    return base64.b32encode(os.urandom(20)).decode().rstrip('=')


# ── Storage in the trials database (public schema) ───────────────────────────

_tables_ready = False


def ensure_tables():
    global _tables_ready
    if _tables_ready:
        return
    with db.engine.begin() as conn:
        for ddl in CONSOLE_DDL:
            conn.execute(text(ddl))
    _tables_ready = True


def _client_ip():
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()[:64]


def audit(action, target=None, detail=None):
    with db.engine.begin() as conn:
        conn.execute(text('INSERT INTO public.console_audit (action, target, detail, ip) VALUES (:a, :t, :d, :ip)'),
                     {'a': action, 't': target, 'd': detail, 'ip': _client_ip()})


def _state(key):
    with db.engine.connect() as conn:
        return conn.execute(text('SELECT value FROM public.console_state WHERE key = :k'), {'k': key}).scalar()


def _set_state(key, value):
    with db.engine.begin() as conn:
        conn.execute(text('DELETE FROM public.console_state WHERE key = :k'), {'k': key})
        conn.execute(text('INSERT INTO public.console_state (key, value) VALUES (:k, :v)'), {'k': key, 'v': value})


def _recent_failures():
    with db.engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM public.console_audit WHERE action = 'login_failed' "
                                 "AND at > (now() AT TIME ZONE 'utc') - make_interval(mins => :m)"),
                            {'m': LOCK_MINUTES}).scalar()


# ── Auth ─────────────────────────────────────────────────────────────────────

def _configured():
    return bool(_env('CONSOLE_PASSWORD_HASH') and _env('CONSOLE_TOTP_SECRET'))


def _session_tag():
    """Changes when the password or 2FA secret changes, which signs out every existing session."""
    raw = (_env('CONSOLE_PASSWORD_HASH') + '|' + _env('CONSOLE_TOTP_SECRET')).encode()
    return hmac.new(current_app.config['SECRET_KEY'].encode(), raw, hashlib.sha256).hexdigest()[:24]


def _signed_in():
    t = session.get('console_at')
    return (bool(t) and time.time() - t < SESSION_HOURS * 3600
            and hmac.compare_digest(session.get('console_tag', ''), _session_tag()))


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _signed_in():
            return redirect(url_for('console.login'))
        return view(*args, **kwargs)
    return wrapper


@console_bp.before_app_request
def _only_console():
    """In console mode the deployment serves the console and nothing else."""
    if request.endpoint == 'static':                      # the console's own icon files
        return None
    if request.endpoint is None or not request.endpoint.startswith('console.'):
        abort(404)
    if not _configured():
        abort(503, 'Console not configured: set CONSOLE_PASSWORD_HASH and CONSOLE_TOTP_SECRET.')
    ensure_tables()


@console_bp.after_app_request
def _headers(resp):
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    # same-origin, not no-referrer: Flask-WTF's HTTPS CSRF check needs the Referer on our own form posts
    resp.headers['Referrer-Policy'] = 'same-origin'
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return resp


@console_bp.route('/login', methods=['GET', 'POST'])
def login():
    if _signed_in():
        return redirect(url_for('console.dashboard'))
    error = None
    if request.method == 'POST':
        if _recent_failures() >= MAX_FAILURES:
            error = f'Too many failed attempts. Sign-in is locked for {LOCK_MINUTES} minutes.'
        else:
            pw_ok = check_password_hash(_env('CONSOLE_PASSWORD_HASH'), request.form.get('password', ''))
            counter = totp_match(_env('CONSOLE_TOTP_SECRET'), request.form.get('code', ''))
            last = int(_state('totp_last') or 0)
            if pw_ok and counter is not None and counter > last:
                _set_state('totp_last', str(counter))       # each code works once
                session.clear()
                session.permanent = True
                session['console_at'] = time.time()
                session['console_tag'] = _session_tag()
                audit('login')
                return redirect(url_for('console.dashboard'))
            audit('login_failed')
            error = 'Wrong password or code.' if not (pw_ok and counter is not None) else \
                'That code was already used. Wait for the next one.'
    return render_template('console/login.html', error=error)


@console_bp.route('/logout', methods=['POST'])
def logout():
    if _signed_in():
        audit('logout')
    session.clear()
    return redirect(url_for('console.login'))


# ── Trial requests (leads) from the marketing site ───────────────────────────

_leads_engine = None


def _leads_engine_or_none():
    global _leads_engine
    url = _env('LEADS_DATABASE_URL')
    if not url:
        return None
    if _leads_engine is None:
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql+psycopg2://', 1)
        elif url.startswith('postgresql://'):
            url = url.replace('postgresql://', 'postgresql+psycopg2://', 1)
        _leads_engine = create_engine(url, pool_pre_ping=True)
    return _leads_engine


def load_leads(limit=100):
    """Newest trial requests with their console status. [] if LEADS_DATABASE_URL isn't set."""
    from . import crypto
    from .marketing import BUSINESS_TYPES
    from .models import Lead
    engine = _leads_engine_or_none()
    if engine is None:
        return None
    from sqlalchemy import inspect, select
    t = Lead.__table__
    with crypto.using_key(_env('LEADS_DATA_ENCRYPTION_KEY')), engine.connect() as conn:
        present = {c['name'] for c in inspect(conn).get_columns('leads')}   # company_name arrives with an update
        cols = [c for c in t.c if c.name in present]
        rows = [dict(r) for r in conn.execute(select(*cols).order_by(t.c.created_at.desc()).limit(limit)).mappings()]
    with db.engine.connect() as conn:
        links = {r.lead_id: r for r in conn.execute(text('SELECT lead_id, status, slug FROM public.console_lead_links'))}
    for r in rows:
        r['business'] = r['business_other'] if r['business_type'] == 'other' and r['business_other'] \
            else BUSINESS_TYPES.get(r['business_type'], r['business_type'])
        link = links.get(r['id'])
        r['link_status'], r['link_slug'] = (link.status, link.slug) if link else (None, None)
        for later in ('company_name', 'city', 'email'):   # columns added by later database updates
            r.setdefault(later, None)
        r['suggested_slug'] = suggest_slug(r['company_name'] or r['business_other'] or r['name'])
    return rows


def load_demo_stats(days=30):
    """Anonymous live-demo counts from the demo database: totals for today / 7 / 30 days and daily rows.
    None if not connected; {'pending': True} before the database update that adds the table."""
    from sqlalchemy import func, inspect, select
    from .models import DemoStat
    engine = _leads_engine_or_none()
    if engine is None:
        return None
    from .models import Lead
    t = DemoStat.__table__
    today = datetime.utcnow().date()
    since = today - timedelta(days=days)
    with engine.connect() as conn:
        if not inspect(conn).has_table('demo_stats'):
            return {'pending': True}
        present = {c['name'] for c in inspect(conn).get_columns('demo_stats')}   # site_visitors: a later update
        cols = [c for c in t.c if c.name in present]
        rows = [dict(r) for r in conn.execute(select(*cols).where(t.c.day > since).order_by(t.c.day.desc())).mappings()]
        # trial requests per day (only their dates are read: nothing encrypted is needed), from the day counting started
        # (the funnel's first day), so every column covers the same days
        started = conn.execute(select(func.min(t.c.day))).scalar()
        lead_days = [] if started is None else [
            d.date() for (d,) in conn.execute(select(Lead.__table__.c.created_at).where(
                Lead.__table__.c.created_at >= datetime.combine(max(since + timedelta(days=1), started), datetime.min.time())))]
    requests_by_day = {}
    for d in lead_days:
        requests_by_day[d] = requests_by_day.get(d, 0) + 1
    by_day = {r['day']: r for r in rows}
    for d, n in requests_by_day.items():                  # a day with requests but no demo use still shows
        by_day.setdefault(d, {'day': d, 'starts': 0, 'quotations': 0, 'pdfs': 0, 'sample_pdfs': 0, 'tried': 0})
    rows = sorted(by_day.values(), key=lambda r: r['day'], reverse=True)
    for r in rows:
        r.setdefault('site_visitors', None)
        r.setdefault('sample_pdfs', None)              # the guide's steps: a later update
        r.setdefault('tried', None)
        r['requests'] = requests_by_day.get(r['day'], 0)
    keys = ('site_visitors', 'starts', 'sample_pdfs', 'tried', 'quotations', 'pdfs', 'requests')

    def total(n):
        picked = [r for r in rows if r['day'] > today - timedelta(days=n)]
        out = {k: sum(r[k] or 0 for r in picked) for k in keys}
        out['pct'] = {k: (round(out[k] / out['site_visitors'] * 100) if out['site_visitors'] else None)
                      for k in ('starts', 'requests')}
        out['pct'].update({k: (round(out[k] / out['starts'] * 100) if out['starts'] else None)
                           for k in ('sample_pdfs', 'tried', 'quotations', 'pdfs')})
        return out
    return {'pending': False, 'visitors_ready': 'site_visitors' in present, 'steps_ready': 'tried' in present, 'today': total(1), 'week': total(7),
            'month': total(30), 'days': rows[:14], 'started': started}


# ── Tutorials on the marketing site (stored in the demo database) ──────────

_TUTORIALS_NARROW = None


def _tutorials_table():
    """(engine, table) or (None, reason) when not connected / before the database update. Before the update that
    adds tutorials.wide, the table is given without that column, so nothing reads or writes it."""
    global _TUTORIALS_NARROW
    from sqlalchemy import MetaData, Table, inspect
    from .models import Tutorial
    engine = _leads_engine_or_none()
    if engine is None:
        return None, 'not_connected'
    with engine.connect() as conn:
        if not inspect(conn).has_table('tutorials'):
            return None, 'pending'
        if 'wide' in {c['name'] for c in inspect(conn).get_columns('tutorials')}:
            return engine, Tutorial.__table__
    if _TUTORIALS_NARROW is None:
        _TUTORIALS_NARROW = Table('tutorials', MetaData(), *[c._copy() for c in Tutorial.__table__.columns if c.name != 'wide'])
    return engine, _TUTORIALS_NARROW


STARTER_TUTORIALS = [   # the first videos (tools/tutorials), offered when the list is empty
    ('Full walkthrough', 'Everything from setup to getting paid, in one video.', '4 min'),
    ('1 · Your company details', 'Log in, add your company name, contact details, logo and colours.', '1 min'),
    ('2 · Your rates & materials', 'Set your rates, add your own materials and fittings.', '33 sec'),
    ('3 · Your first quotation', 'Rooms, items in feet and inches, fittings and a discount.', '1.5 min'),
    ('4 · Send it & get it accepted', 'Share the PDFs and let your customer accept online.', '31 sec'),
    ('5 · Get paid', 'Record payments, issue a GST invoice and see who owes you.', '38 sec'),
]


def load_tutorials():
    engine, t = _tutorials_table()
    if engine is None:
        return t, []
    from sqlalchemy import select
    with engine.connect() as conn:
        return None, [dict(r) for r in conn.execute(select(t).order_by(t.c.position, t.c.id)).mappings()]


def _tutorial_values(form, t=None):
    """(values, error) from the add/edit form. `t`: the table, to include Landscape once that column exists."""
    from .marketing import youtube_id
    title = ' '.join((form.get('title') or '').split())[:120]
    link = (form.get('youtube') or '').strip()
    vid = youtube_id(link) if link else ''
    if len(title) < 2:
        return None, 'Give the video a title.'
    if link and not vid:
        return None, "That doesn't look like a YouTube link (e.g. https://youtu.be/AbCdEfGhIjK)."
    values = dict(title=title, about=' '.join((form.get('about') or '').split())[:300],
                  length=' '.join((form.get('length') or '').split())[:20], youtube_id=vid or None,
                  hidden=form.get('shown') != 'on', updated_at=datetime.utcnow())
    if t is not None and 'wide' in t.c:
        values['wide'] = form.get('wide') == 'on'
    return values, None


def _site_url():
    return _env('MARKETING_SITE_URL', 'https://www.quote-room.co.in').rstrip('/')


def _link_lead(lead_id, status, slug=None):
    with db.engine.begin() as conn:
        conn.execute(text('DELETE FROM public.console_lead_links WHERE lead_id = :i'), {'i': lead_id})
        conn.execute(text('INSERT INTO public.console_lead_links (lead_id, status, slug) VALUES (:i, :s, :g)'),
                     {'i': lead_id, 's': status, 'g': slug})


def suggest_slug(text_):
    words = re.sub(r'[^a-z0-9 ]', ' ', (text_ or '').lower()).split()
    stop = {'interiors', 'interior', 'designs', 'design', 'designer', 'the', 'and', 'pvt', 'ltd', 'works', 'furniture'}
    base = '-'.join([w for w in words if w not in stop][:2] or words[:2])[:24].strip('-')
    if not base or not base[0].isalpha():
        base = 'trial-' + base if base else 'trial'
    return base


# ── Pages ────────────────────────────────────────────────────────────────────

def _product():
    return _env('MARKETING_PRODUCT_NAME', 'QuoteRoom')


def _tutorials_line():
    """'New here? …/tutorials' for welcome messages, only while the website shows at least one video."""
    try:
        problem, rows = load_tutorials()
    except Exception:                         # the demo database being unreachable mustn't block a welcome
        return ''
    if problem or not any(r['youtube_id'] and not r['hidden'] for r in rows):
        return ''
    return f"New here? Short setup videos (start with the 4-minute walkthrough): {_site_url()}/tutorials\n\n"


def _welcome_message(name, url, username, password, ends_on, company=''):
    from . import texts
    ready = (f"I've already put in {company} and your contact details, so your quotations carry your name. "
             "Add your logo, full address and GSTIN in Settings → Company, and your own rates in Rates.\n\n") if company else ''
    return texts.render('trial_welcome', hello=f'Hi {name}!' if name else 'Hi!', product=_product(),
                        for_company=f' for {company}' if company else '', url=url, username=username, password=password,
                        company_note=ready, tutorials=_tutorials_line(), ends_on=ends_on.strftime('%d %b %Y'))[1]


def _wa_link(phone, message):
    return f"https://wa.me/{phone}?text={quote(message)}" if phone else ''


# ── Follow-up messages on WhatsApp ───────────────────────────────────────────
# Drafts for the trial page's "Message on WhatsApp" card. {name} is filled in on the page (it can be edited there);
# the rest when the page is built. The message opens in the operator's own WhatsApp (wa.me): nothing is sent from here.

PLAN_PRICES = '6 months ₹4,999 or 12 months ₹8,999, one price for your whole team'

def _follow_up_texts():
    """[(key, label, text)] for the WhatsApp drafts (console → Messages can change them)."""
    from . import texts
    return [(k[3:], texts.TEXTS[k][1], texts.get(k)[1]) for k in texts.TEXTS if k.startswith('fu_')]


def _first_name(name):
    words = (name or '').split()
    return words[0].title() if words and len(words[0]) > 1 else (name or '').strip()


CONTACT_KEYS = ['company_name', 'company_mobile', 'company_email', 'company_address', 'company_gstin',
                'signatory_name', 'signatory_title']


def full_contact(slugs, open_app=None, extra_phone=''):
    """Everything known about a business, for the top of its trial / customer page: [(label, value, kind, source)],
    kind 'wa' / 'tel' / 'mail' / '' (how to show it). slugs: its trial and customer addresses (the request is linked by
    either). open_app: a context manager into its app (company details, admins), or None. Values seen once only."""
    from . import crypto, subscription
    from .marketing import BUSINESS_TYPES
    from .models import Lead
    rows, seen = [], set()

    def add(label, value, kind='', source=''):
        value = ' '.join(str(value or '').split()) if kind != 'multi' else str(value or '').strip()
        key = (kind if kind in ('wa', 'tel', 'mail') else label, re.sub(r'\D', '', value)[-10:] if kind in ('wa', 'tel') else value.lower())
        if value and key not in seen:
            seen.add(key)
            rows.append((label, value, kind, source))

    slugs = [x for x in dict.fromkeys(slugs) if x]
    lead = None
    with db.engine.connect() as conn:
        lead_id = conn.execute(text("SELECT lead_id FROM public.console_lead_links WHERE slug = ANY(:s) AND status = 'trial' "
                                    'ORDER BY lead_id DESC LIMIT 1'), {'s': slugs}).scalar() if slugs else None
    if lead_id:
        try:
            lead = load_lead(lead_id)
        except Exception:
            lead = None
    if lead:
        src = 'trial request'
        add('Name', lead.get('name'), '', src)
        add('WhatsApp', lead.get('phone'), 'wa', src)
        add('Email', lead.get('email'), 'mail', src)
        add('Company', lead.get('company_name'), '', src)
        add('City', lead.get('city'), '', src)
        bt = lead.get('business_type')
        add('Business', lead.get('business_other') if bt == 'other' and lead.get('business_other') else BUSINESS_TYPES.get(bt, bt), '', src)
        add('Came from', lead.get('source'), '', src)
        if lead.get('created_at'):
            add('Asked for a trial', ist(lead['created_at']), '', src)
    if open_app is not None:
        try:
            from .models import AppSetting, User
            with open_app:
                st = AppSetting.get_many(CONTACT_KEYS)
                admins = [(u.username, u.full_name) for u in User.query.filter_by(role='admin').order_by(User.id)]
            src = 'their app'
            add('Company', st['company_name'], '', src)
            add('Phone', st['company_mobile'], 'tel', src)
            add('Email', st['company_email'], 'mail', src)
            add('Address', st['company_address'], '', src)
            add('GSTIN', st['company_gstin'], '', src)
            if st['signatory_name']:
                add('Signs as', f"{st['signatory_name']}{', ' + st['signatory_title'] if st['signatory_title'] else ''}", '', src)
            add('Admin logins', ', '.join(f'{u}{f" ({n})" if n else ""}' for u, n in admins), '', src)
        except Exception:                         # an unreachable app mustn't break the page
            pass
    add('Phone', extra_phone, 'tel', 'customer record')
    if slugs:
        try:
            subscription.ensure_table()
            with db.engine.connect() as conn:
                pay = conn.execute(text("SELECT payer_name, business_name, email, phone FROM public.platform_payments "
                                        "WHERE slug = ANY(:s) ORDER BY (status = 'paid') DESC, created_at DESC LIMIT 1"),
                                   {'s': slugs}).mappings().first()
            if pay:
                src = 'payment'
                add('Paid by', pay['payer_name'], '', src)
                add('Billing name', pay['business_name'], '', src)
                add('Email', pay['email'], 'mail', src)
                add('Phone', pay['phone'], 'tel', src)
        except Exception:
            pass
    return rows


def contact_name(slug):
    """The person's name from the trial request this business came from (console_lead_links), or ''."""
    try:
        return trial_contact({'slug': slug, 'status': ''})['name'] or ''
    except Exception:
        return ''


def trial_contacts(trials):
    """{slug: {'name', 'phone', 'company'}} for many trials, in one query to the trial requests (and each trial's own
    phone and company name where the request didn't have them)."""
    from . import crypto
    from .models import Lead
    out = {t['slug']: {'name': '', 'phone': (t.get('usage') or {}).get('phone') or '', 'company': ''} for t in trials}
    with db.engine.connect() as conn:
        links = {r[0]: r[1] for r in conn.execute(text(
            "SELECT DISTINCT ON (slug) slug, lead_id FROM public.console_lead_links WHERE status = 'trial' "
            "ORDER BY slug, lead_id DESC")) if r[0] in out}
    engine = _leads_engine_or_none() if links else None
    if engine is not None:
        try:
            from sqlalchemy import inspect, select
            lt = Lead.__table__
            with crypto.using_key(_env('LEADS_DATA_ENCRYPTION_KEY')), engine.connect() as conn:
                present = {c['name'] for c in inspect(conn).get_columns('leads')}
                cols = [lt.c.id, lt.c.name, lt.c.phone] + ([lt.c.company_name] if 'company_name' in present else [])
                by_id = {r['id']: r for r in conn.execute(select(*cols).where(lt.c.id.in_(list(links.values())))).mappings()}
            for slug, lead_id in links.items():
                r = by_id.get(lead_id)
                if r:
                    out[slug].update(name=r['name'] or '', phone=r['phone'] or out[slug]['phone'],
                                     company=r.get('company_name') or '')
        except Exception:                       # the leads database being unreachable mustn't break the page
            pass
    return out


def _followup_trials():
    """Running trials with their usage, phone and company (one pass over the trials) and their contacts."""
    from .models import AppSetting
    trials = [t for t in ops.list_trials() if t['status'] == 'active']
    for t in trials:
        try:
            with tenancy.tenant_context(t['slug'], t['schema_name']):
                s = AppSetting.get_many(['company_mobile', 'company_name'])
            t.setdefault('usage', {})
            if t['usage'] is not None:
                t['usage']['phone'] = ''.join(ch for ch in s['company_mobile'] if ch.isdigit())
            t['company_name'] = s['company_name'] or ''
        except Exception:
            t['company_name'] = ''
    contacts = trial_contacts(trials)
    for t in trials:
        t['contact'] = contacts.get(t['slug'], {})
    return trials, contacts


def _followup_message(row, key=None):
    """The follow-up draft for a trial on the board (its stage's, or `key`), with their first name filled in."""
    drafts, _ = follow_ups(row)
    key = key or row['draft_key']
    body = next((b for k, _, b in drafts if k == key), drafts[0][2])
    return body.replace('{name}', _first_name(row['contact'].get('name')) or 'there')


def trial_contact(t):
    """{'name', 'phone', 'company'} for a trial: from the trial request it was made from (console_lead_links), else
    the phone and company name filled in on the trial."""
    from . import crypto
    from .models import AppSetting, Lead
    out = {'name': '', 'phone': '', 'company': '', 'email': '', 'lead_id': None}
    with db.engine.connect() as conn:
        lead_id = out['lead_id'] = conn.execute(text("SELECT lead_id FROM public.console_lead_links WHERE slug = :s AND status = 'trial' "
                                    'ORDER BY lead_id DESC LIMIT 1'), {'s': t['slug']}).scalar()
    engine = _leads_engine_or_none() if lead_id else None
    if engine is not None:
        try:
            from sqlalchemy import inspect, select
            lt = Lead.__table__
            with crypto.using_key(_env('LEADS_DATA_ENCRYPTION_KEY')), engine.connect() as conn:
                present = {c['name'] for c in inspect(conn).get_columns('leads')}
                cols = [lt.c.name, lt.c.phone] + [getattr(lt.c, c) for c in ('company_name', 'email') if c in present]
                row = conn.execute(select(*cols).where(lt.c.id == lead_id)).mappings().first()
            if row:
                out.update(name=row['name'] or '', phone=row['phone'] or '', company=row.get('company_name') or '',
                           email=row.get('email') or '')
        except Exception:                     # the leads database being unreachable mustn't break the trial page
            pass
    if t['status'] == 'active' and not (out['phone'] and out['company']):
        with tenancy.tenant_context(t['slug'], t['schema_name']):
            s = AppSetting.get_many(['company_mobile', 'company_name'])
        out['phone'] = out['phone'] or s['company_mobile'] or ''
        out['company'] = out['company'] or s['company_name'] or ''
    digits = re.sub(r'\D', '', out['phone'])
    out['phone'] = '91' + digits if len(digits) == 10 else digits
    out['name'] = _first_name(out['name'])
    return out


def follow_ups(t):
    """([(key, label, draft)], suggested key) for a trial, from its plan dates and usage."""
    st, u = t.get('status_obj'), t.get('usage') or {}
    fmt = lambda d: d.strftime('%d %b') if d else ''
    values = dict(product=_product(), sender=_env('CONSOLE_SENDER_NAME', 'Harshith'), url=t['url'], prices=PLAN_PRICES,
                  ends_on=fmt(st.ends_on) if st and st.has_limit else '',
                  delete_on=fmt(st.delete_on) if st and st.has_limit else '')
    from . import texts
    drafts = [(k, label, texts.fill(body, **values)) for k, label, body in _follow_up_texts()]   # {name}: on the page
    from . import followups                      # the same stages as Follow-ups
    stage = followups.stage_of(dict(t, status='active')) if t.get('status', 'active') == 'active' else None
    if stage == 'quoting':
        quiet = u.get('last_seen_at') and (datetime.utcnow() - u['last_seen_at'].replace(tzinfo=None)).days >= 3
        pick = 'checkin' if quiet else 'quote'
    elif stage:
        pick = followups.STAGES[stage][2]
    else:
        pick = 'signin'
    return drafts, pick


def _with_badges(trials):
    """(label, css class) per trial: running / ends today / ended / read-only / due for deletion."""
    today = plan_mod.today()
    for t in trials:
        st = t['status_obj']
        if t['status'] != 'active':
            t['badge'] = (t['status'], 'b-other')
        elif not (st and st.has_limit):
            t['badge'] = ('no plan', 'b-other')
        elif st.delete_on <= today:
            t['badge'] = ('due for deletion', 'b-due')
        elif st.state == 'read_only':
            t['badge'] = ('ended · read-only', 'b-read_only')
        elif st.state == 'grace':
            t['badge'] = ('ended · grace', 'b-grace')
        elif st.days_left <= 1:
            t['badge'] = ('ends today' if st.days_left == 0 else 'ends tomorrow', 'b-reminder')
        else:
            t['badge'] = ('running', 'b-active')
    return trials


@console_bp.route('/')
@login_required
def dashboard():
    trials = _with_badges(ops.list_trials())
    trials.sort(key=lambda t: t.get('created_at') or datetime.min, reverse=True)      # newest first
    try:
        contacts = trial_contacts(trials)       # name, phone, company: shown and searched
    except Exception:
        contacts = {}
    leads = load_leads()
    new_leads = [l for l in (leads or []) if not l['link_status']]
    try:
        demo_stats = load_demo_stats()
    except Exception as exc:                 # the demo database being unreachable shouldn't break the dashboard
        demo_stats = {'error': str(exc)}
    from . import emails, signup
    try:
        email_seen = emails.by_lead() if new_leads else {}
        email_since = emails.tracking_since() if new_leads else None
    except Exception:
        email_seen, email_since = {}, None
    from . import texts
    return render_template('console/dashboard.html', trials=trials, leads=leads, new_leads=new_leads, demo_stats=demo_stats,
                           lead_wa=texts.get('lead_whatsapp')[1],
                           email_seen=email_seen, email_since=email_since, contacts=contacts,
                           extend_choices=EXTEND_CHOICES, base_domain=tenancy.base_domain(),
                           spares=ops.spare_count(), self_serve=bool(signup._env('SIGNUP_SECRET')))


@console_bp.route('/spares', methods=['POST'])
@login_required
def top_up_spares():
    try:
        made = ops.top_up_spares()
    except ops.OpsError as exc:
        flash(f'Could not make ready-made trials: {exc}', 'error')
    else:
        audit('spares_top_up', None, f'{made} made')
        flash(f'{made} ready-made trial(s) made; {ops.spare_count()} ready.' if made else 'Already enough ready-made trials.', 'ok')
    return redirect(url_for('console.dashboard'))


@console_bp.route('/trials', methods=['POST'])
@login_required
def create_trial():
    slug = request.form.get('slug', '').strip().lower()
    username = request.form.get('admin_username', '').strip() or 'admin'
    days = request.form.get('days', '7')
    lead_id = request.form.get('lead_id', type=int)
    name = request.form.get('name', '').strip()[:80]
    company = request.form.get('company', '').strip()[:80]
    city = ' '.join(request.form.get('city', '').split())[:60]
    email = request.form.get('email', '').strip()[:120]
    phone = re.sub(r'\D', '', request.form.get('phone', ''))[:15]
    if lead_id:                                   # set up already, e.g. by them from the emailed link meanwhile
        with db.engine.connect() as conn:
            done = conn.execute(text("SELECT slug FROM public.console_lead_links WHERE lead_id = :i AND status = 'trial'"),
                                {'i': lead_id}).scalar()
        if done:
            flash(f'This request already has a trial: "{done}" (they may have set it up themselves from the email '
                  'link). Here it is.', 'ok')
            return redirect(url_for('console.trial_detail', slug=done))
    try:
        days = int(days)
        t = ops.create_trial(slug, username, None, days, company=company, phone=phone, city=city, email=email)
    except (ops.OpsError, ValueError) as exc:
        with db.engine.connect() as conn:
            existing = conn.execute(text('SELECT status FROM public.tenants WHERE slug = :s'), {'s': slug}).scalar()
        if existing == 'active':
            flash(f'"{slug}" is already a trial (here it is). For this request, choose another address name.', 'error')
            return redirect(url_for('console.trial_detail', slug=slug))
        if existing:
            flash(f'Could not create trial: "{slug}" is taken by an app that is {existing} '
                  f'({"stopped half-way while being made: delete it on its page, then try again" if existing == "creating" else "see Customers"}).',
                  'error')
        else:
            flash(f'Could not create trial: {exc}', 'error')
        return redirect(url_for('console.dashboard'))
    if lead_id:
        _link_lead(lead_id, 'trial', t['slug'])
    audit('trial_create', t['slug'], f'{days} days' + (f', lead #{lead_id}' if lead_id else ''))
    message = _welcome_message(name, t['url'], t['username'], t['password'], t['ends_on'], company)
    return render_template('console/result.html', title=f'Trial "{t["slug"]}" is ready', trial=t,
                           message=message, wa_url=_wa_link(phone, message), phone=phone)


def _trial_or_404(slug):
    match = [t for t in _with_badges(ops.list_trials()) if t['slug'] == slug]
    if not match:
        abort(404)
    return match[0]


@console_bp.route('/trials/<slug>')
@login_required
def trial_detail(slug):
    t = _trial_or_404(slug)
    admins, locked, boq_state = [], set(), None
    if t['status'] == 'active':
        from . import branding
        admins = ops.admin_usernames(slug)
        with tenancy.tenant_context(slug, t['schema_name']):
            locked = branding.locked_fields()
        boq_state = ops.boq_status(slug)
    with db.engine.connect() as conn:
        history = conn.execute(text('SELECT at, action, detail FROM public.console_audit WHERE target = :s '
                                    'ORDER BY at DESC LIMIT 30'), {'s': slug}).mappings().all()
    contact = trial_contact(t)
    drafts, suggested = follow_ups(t)
    from . import subscription
    pay_email = ''
    if t['status'] == 'active':
        from .models import AppSetting
        with tenancy.tenant_context(slug, t['schema_name']):
            pay_email = AppSetting.get('company_email', '') or ''
    fu = None
    if t['status'] == 'active':
        from . import activity, followups
        try:
            with tenancy.tenant_context(slug, t['schema_name']):
                t2 = dict(t, status_obj=plan_mod.load_status(on=plan_mod.today()), usage=activity.usage())
            st_key = followups.stage_of(t2)
            fu = {'stage': st_key, 'label': followups.STAGES[st_key][0] if st_key else '',
                  'next': followups.STAGES[st_key][1] if st_key else '', 'history': followups.history(slug),
                  'mark': followups.marks().get(slug, {})}
        except Exception:
            fu = None
    info = full_contact([slug], tenancy.tenant_context(slug, t['schema_name']) if t['status'] == 'active' else None)
    from . import emails
    try:
        sent_emails = emails.for_trial(slug, contact.get('lead_id'))
    except Exception:
        sent_emails = []
    return render_template('console/trial.html', t=t, admins=admins, locked=locked, history=history, fu=fu,
                           sent_emails=sent_emails, info=info,
                           extend_choices=EXTEND_CHOICES, contact=contact, drafts=drafts, suggested=suggested,
                           boq=boq_state, links=subscription.links_enabled(), pay_email=pay_email,
                           prices=subscription.prices())


@console_bp.route('/follow-ups')
@login_required
def followups_page():
    from . import followups
    trials, contacts = _followup_trials()
    b = followups.board(trials, contacts)
    stage = request.args.get('stage', '')
    rows = [r for r in b['rows'] if r['stage'] == stage] if stage in followups.STAGES else b['rows']
    for r in b['due'][:200]:
        r['message'] = _followup_message(r)
        phone = re.sub(r'\D', '', r['contact'].get('phone') or '')
        r['phone'] = phone
    from . import emails
    try:
        email_stats = emails.stats(load_leads(500))
    except Exception:
        email_stats = None
    return render_template('console/followups.html', board=b, rows=rows, stage=stage, stages=followups.STAGES,
                           email_stats=email_stats,
                           order=followups.ORDER, base_domain=tenancy.base_domain())


@console_bp.route('/follow-ups/queue')
@login_required
def followups_queue():
    """One due trial at a time: the message to check, Open WhatsApp (logged), Skip, Next."""
    from . import followups
    trials, contacts = _followup_trials()
    b = followups.board(trials, contacts)
    skip = set(request.args.getlist('skip'))
    due = [r for r in b['due'] if r['slug'] not in skip]
    row = due[0] if due else None
    if row:
        row['message'] = _followup_message(row)
        row['phone'] = re.sub(r'\D', '', row['contact'].get('phone') or '')
    return render_template('console/followups_queue.html', row=row, left=len(due), skip=sorted(skip),
                           stages=followups.STAGES, base_domain=tenancy.base_domain())


@console_bp.route('/follow-ups/<slug>/whatsapp', methods=['POST'])
@login_required
def followups_whatsapp(slug):
    """Log the follow-up and open it in the operator's WhatsApp (nothing is sent from here)."""
    from . import followups
    _trial_or_404(slug)
    phone = re.sub(r'\D', '', request.form.get('phone', ''))[:15]
    message = request.form.get('message', '')[:3000]
    if not phone:
        flash('No WhatsApp number for this trial.', 'error')
        return redirect(url_for('console.followups_page'))
    followups.log(slug, request.form.get('stage', '')[:20], 'whatsapp', message[:300])
    audit('followup_whatsapp', slug, request.form.get('stage', ''))
    return redirect(_wa_link(phone, message))


# ── Messages: every draft and email text, editable ───────────────────────────

@console_bp.route('/messages')
@login_required
def messages_page():
    from . import texts
    return render_template('console/messages.html', groups=texts.listing())


@console_bp.route('/messages/<key>', methods=['POST'])
@login_required
def messages_save(key):
    from . import texts
    if key not in texts.TEXTS:
        abort(404)
    has_subject = texts.TEXTS[key][3] is not None
    subject = ' '.join((request.form.get('subject') or '').split())[:200] if has_subject else None
    body = (request.form.get('body') or '').replace('\r', '')[:5000]
    bad = texts.unknown_fields(key, subject, body)
    if not body.strip():
        flash('The message can\'t be empty (use Reset to go back to the original).', 'error')
    elif bad:
        flash(f'Not saved: {", ".join("{" + b + "}" for b in bad)} isn\'t a placeholder this message can use. '
              f'It can use: {", ".join("{" + f + "}" for f in texts.TEXTS[key][5])}.', 'error')
    else:
        texts.save(key, subject, body)
        audit('message_edit', None, f'{key}: {texts.TEXTS[key][1]}'[:300])
        flash(f'Saved "{texts.TEXTS[key][1]}". It\'s used from now on.', 'ok')
    return redirect(url_for('console.messages_page') + f'#m-{key}')


@console_bp.route('/messages/<key>/reset', methods=['POST'])
@login_required
def messages_reset(key):
    from . import texts
    if key not in texts.TEXTS:
        abort(404)
    texts.reset(key)
    audit('message_reset', None, key)
    flash(f'"{texts.TEXTS[key][1]}" is back to the original wording.', 'ok')
    return redirect(url_for('console.messages_page') + f'#m-{key}')


# ── Email from the console ───────────────────────────────────────────────────

def _email_signoff():
    from . import texts
    return texts.render('email_signoff', sender=_env('CONSOLE_SENDER_NAME', 'Harshith'), product=_product())[1]


def _email_drafts_trial(t):
    """([(key, label, subject, body)], suggested) for a trial: the WhatsApp follow-ups, as emails."""
    from . import activity
    with tenancy.tenant_context(t['slug'], t['schema_name']):
        t2 = dict(t, status_obj=plan_mod.load_status(on=plan_mod.today()), usage=activity.usage())
    drafts, pick = follow_ups(t2)
    st = t2['status_obj']
    ends = st.ends_on.strftime('%d %b') if st and st.has_limit else ''
    out = []
    from . import texts
    for key, label, body in drafts:
        subject = texts.render(f'fu_{key}', product=_product(), ends_on=ends)[0] or ''
        out.append((key, label, subject, (body.rstrip() + '\n\n' if key == 'custom' else body) + _email_signoff()))
    from . import followups
    return out, pick, followups.stage_of(t2) or ''


def _email_drafts_lead(lead):
    from . import emails, signup, texts
    out = []
    if lead.get('business_type') in signup.ELIGIBLE and signup._env('SIGNUP_SECRET'):
        link = signup.setup_url(lead['id'], base=emails.base_url() or None)
        subject, body = texts.render('lead_setup', product=_product(), link=link, days=signup.TOKEN_HOURS // 24)
        out.append(('setup', 'Set-up link again', subject, body + _email_signoff()))
    subject, body = texts.render('lead_hello', product=_product())
    out.append(('hello', 'Thanks for your interest', subject, body + _email_signoff()))
    out.append(('custom', 'Custom message', '', 'Hi {name},\n\n' + _email_signoff()))
    return out, out[0][0]


@console_bp.route('/email', methods=['GET', 'POST'])
@login_required
def email_compose():
    """Write an email to a trial (?slug=), a trial request (?lead=) or anyone; sent from hello@ with a copy there,
    and you can see if it's opened (app/emails.py)."""
    from . import emails, mailer
    slug = (request.values.get('slug') or '').strip()
    lead_id = request.values.get('lead', type=int)
    t = _trial_or_404(slug) if slug else None
    lead = load_lead(lead_id) if lead_id else None
    if lead_id and not lead:
        abort(404)
    to, name, drafts, suggested, sent, back, stage = '', '', [], 'custom', [], url_for('console.dashboard'), ''

    if t:
        contact = trial_contact(t)
        name = contact['name']
        if t['status'] == 'active':
            from .models import AppSetting
            with tenancy.tenant_context(slug, t['schema_name']):
                to = AppSetting.get('company_email', '') or ''
        to = to or contact['email']
        lead_id = lead_id or contact['lead_id']
        drafts, suggested, stage = _email_drafts_trial(t) if t['status'] == 'active' else ([], 'custom', '')
        sent = emails.for_trial(slug, contact['lead_id'])
        back = url_for('console.trial_detail', slug=slug)
    elif lead:
        to, name = lead.get('email') or '', _first_name(lead.get('name'))
        drafts, suggested = _email_drafts_lead(lead)
        sent = emails.for_lead(lead_id)
    if not (t or lead):
        to = (request.args.get('to') or '').strip()[:200]           # e.g. a paying customer's email
        name = (request.args.get('name') or '').strip()[:60]
    if not drafts:
        drafts = [('custom', 'Custom message', '', 'Hi {name},\n\n' + _email_signoff())]
    if request.method == 'POST':
        to = (request.form.get('to') or '').strip()[:200]
        subject = ' '.join((request.form.get('subject') or '').split())[:200]
        body = (request.form.get('body') or '').replace('\r', '').strip()[:10000]
        problem = None
        if not mailer.enabled():
            problem = 'Email isn\'t set up on the console (PLATFORM_SMTP_* in Vercel).'
        elif not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', to):
            problem = 'Enter a valid email address.'
        elif not subject or not body:
            problem = 'Write a subject and a message.'
        if problem:
            flash(problem, 'error')
        elif emails.send(to, subject, body, kind='console', slug=slug or None, lead_id=lead_id):
            if t:
                from . import followups
                followups.log(slug, stage, 'email', subject)
            audit('email_sent', slug or (f'lead {lead_id}' if lead_id else None), f'{mailer.mask(to)}: {subject}'[:300])
            flash(f'Email sent to {to}. You\'ll see here when it\'s opened.', 'ok')
            return redirect(request.full_path if (t or lead) else url_for('console.email_compose'))
        else:
            flash('The email could not be sent. Check the mail settings and try again.', 'error')
        return render_template('console/email.html', t=t, lead=lead, to=to, name=name, drafts=drafts, suggested=suggested,
                               sent=sent, back=back, form={'subject': subject, 'body': body})
    return render_template('console/email.html', t=t, lead=lead, to=to, name=name, drafts=drafts, suggested=suggested,
                           sent=sent, back=back, form=None)


@console_bp.route('/follow-ups/<slug>/mark', methods=['POST'])
@login_required
def followups_mark(slug):
    """Snooze, hot / not interested, a note, or "messaged another way"."""
    from . import followups
    _trial_or_404(slug)
    f = request.form
    if f.get('snooze'):
        followups.snooze(slug, max(1, min(int(f.get('snooze') or 1), 60)))
    if 'mark' in f:
        followups.set_mark(slug, mark=f.get('mark') if f.get('mark') in ('hot', 'lost', '') else '')
    if 'note' in f:
        followups.set_mark(slug, note=f.get('note', '').strip()[:500])
    if f.get('contacted'):
        followups.log(slug, f.get('stage', '')[:20], f.get('contacted')[:10], f.get('what', '')[:300])
    audit('followup_mark', slug, ', '.join(f'{k}={f.get(k)}' for k in ('snooze', 'mark', 'contacted') if f.get(k) is not None))
    nxt = f.get('next', '')
    return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('console.followups_page'))


@console_bp.route('/trials/<slug>/extend', methods=['POST'])
@login_required
def extend_trial(slug):
    length = request.form.get('length', '')
    if length not in EXTEND_CHOICES:
        abort(400)
    try:
        st = ops.extend_trial(slug, length)
    except ops.OpsError as exc:
        flash(str(exc), 'error')
    else:
        audit('trial_extend', slug, f'+{length} → ends {st.ends_on.isoformat()}')
        flash(f'"{slug}" now ends {st.ends_on.strftime("%d %b %Y")} ({st.days_left} days left).', 'ok')
    return redirect(request.form.get('back') == 'detail' and url_for('console.trial_detail', slug=slug)
                    or url_for('console.dashboard'))


@console_bp.route('/trials/<slug>/reset-password', methods=['POST'])
@login_required
def reset_password(slug):
    t = _trial_or_404(slug)
    try:
        username, password = ops.reset_admin_password(slug, request.form.get('username') or None)
    except ops.OpsError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('console.trial_detail', slug=slug))
    audit('trial_reset_password', slug, username)
    st = t['status_obj']
    message = (f"Hi! Your new {_product()} password is ready.\n\nOpen: {t['url']}\nUsername: {username}\n"
               f"Password: {password}")
    return render_template('console/result.html', title=f'New password for "{slug}"',
                           trial=dict(t, username=username, password=password, ends_on=st.ends_on if st else None),
                           message=message, wa_url='', phone='')


@console_bp.route('/trials/<slug>/unlock', methods=['POST'])
@login_required
def unlock_company(slug):
    from .branding import LOCKABLE
    fields = [f for f in request.form.getlist('fields') if f in LOCKABLE]
    if not fields:
        flash('Choose what to unlock.', 'error')
    else:
        try:
            ops.unlock_company(slug, fields)
        except ops.OpsError as exc:
            flash(str(exc), 'error')
        else:
            audit('trial_unlock', slug, ', '.join(fields))
            flash(f'Unlocked {", ".join(fields)} for one change.', 'ok')
    return redirect(url_for('console.trial_detail', slug=slug))


@console_bp.route('/trials/<slug>/boq', methods=['POST'])
@login_required
def trial_boq(slug):
    _trial_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        ops.set_boq(slug, on)
    except ops.OpsError as exc:
        flash(str(exc), 'error')
    else:
        audit('trial_boq', slug, 'on' if on else 'off')
        flash(f'"{slug}" now prices {"by item (BOQ lines)" if on else "by material"}.', 'ok')
    return redirect(url_for('console.trial_detail', slug=slug) + '#features')


@console_bp.route('/trials/<slug>/costs', methods=['POST'])
@login_required
def trial_costs(slug):
    _trial_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        ops.set_item_costs(slug, on)
    except ops.OpsError as exc:
        flash(str(exc), 'error')
    else:
        audit('trial_costs', slug, 'on' if on else 'off')
        flash(f'"Your cost" on each item is now {"on" if on else "off"} for "{slug}".', 'ok')
    return redirect(url_for('console.trial_detail', slug=slug) + '#features')


@console_bp.route('/trials/<slug>/photos', methods=['POST'])
@login_required
def trial_photos(slug):
    _trial_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        ops.set_photos(slug, on)
    except ops.OpsError as exc:
        flash(str(exc), 'error')
    else:
        audit('trial_photos', slug, 'on' if on else 'off')
        flash(f'Photos on items are now {"on" if on else "off"} for "{slug}".', 'ok')
    return redirect(url_for('console.trial_detail', slug=slug) + '#features')


@console_bp.route('/trials/<slug>/gst', methods=['POST'])
@login_required
def trial_gst(slug):
    _trial_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        ops.set_quote_gst(slug, on, request.form.get('rate', '18'))
    except ops.OpsError as exc:
        flash(str(exc), 'error')
    else:
        audit('trial_gst', slug, f"on {request.form.get('rate')}%" if on else 'off')
        flash(f'GST on quotations is now {"on at " + request.form.get("rate", "18") + "%" if on else "off"} for "{slug}".', 'ok')
    return redirect(url_for('console.trial_detail', slug=slug) + '#features')


@console_bp.route('/trials/<slug>/rate-column', methods=['POST'])
@login_required
def trial_rate_column(slug):
    _trial_or_404(slug)
    on = request.form.get('on') == '1'
    ops.set_show_rate(slug, on)
    audit('trial_rate_column', slug, 'shown' if on else 'hidden')
    flash(f'The Rate column is now {"shown" if on else "hidden"} on "{slug}"\'s quotations.', 'ok')
    return redirect(url_for('console.trial_detail', slug=slug) + '#features')


@console_bp.route('/trials/<slug>/presentation', methods=['POST'])
@login_required
def trial_presentation(slug):
    _trial_or_404(slug)
    on = request.form.get('on') == '1'
    ops.set_presentation(slug, on)
    audit('trial_presentation', slug, 'on' if on else 'off')
    flash(f'Presentation pages are now {"on" if on else "off"} for "{slug}".', 'ok')
    return redirect(url_for('console.trial_detail', slug=slug) + '#features')


@console_bp.route('/trials/<slug>/price-list', methods=['POST'])
@login_required
def trial_price_list(slug):
    _trial_or_404(slug)
    from . import price_list
    try:
        parsed = price_list.parse(request.files['file'].read() if 'file' in request.files else b'')
        result = ops.load_price_list(slug, parsed, request.form.get('remove_starter') == '1',
                                     request.form.get('replace_settings') == '1')
    except (price_list.PriceListError, ops.OpsError) as exc:
        flash(str(exc), 'error')
    else:
        audit('trial_price_list', slug, f"{result['added']} added, {result['updated']} updated")
        flash(f'Price list loaded for "{slug}": ' + price_list.summary_text(result), 'ok')
    return redirect(url_for('console.trial_detail', slug=slug) + '#features')


@console_bp.route('/trials/<slug>/delete', methods=['POST'])
@login_required
def delete_trial(slug):
    if request.form.get('confirm', '').strip().lower() != slug:
        flash(f'Type "{slug}" exactly to confirm the deletion.', 'error')
        return redirect(url_for('console.trial_detail', slug=slug))
    try:
        ops.delete_trial(slug)
    except ops.OpsError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('console.dashboard'))
    audit('trial_delete', slug)
    flash(f'Deleted trial "{slug}" and all its data.', 'ok')
    return redirect(url_for('console.dashboard'))


@console_bp.route('/leads/<int:lead_id>/dismiss', methods=['POST'])
@login_required
def dismiss_lead(lead_id):
    _link_lead(lead_id, 'dismissed')
    audit('lead_dismiss', f'lead #{lead_id}')
    return redirect(url_for('console.dashboard'))


@console_bp.route('/leads/<int:lead_id>/restore', methods=['POST'])
@login_required
def restore_lead(lead_id):
    with db.engine.begin() as conn:
        conn.execute(text('DELETE FROM public.console_lead_links WHERE lead_id = :i'), {'i': lead_id})
    audit('lead_restore', f'lead #{lead_id}')
    return redirect(url_for('console.dashboard'))


@console_bp.route('/tutorials')
@login_required
def tutorials():
    problem, rows = load_tutorials()
    engine, t = _tutorials_table()
    return render_template('console/tutorials.html', problem=problem, rows=rows, site_url=_site_url(),
                           live=sum(1 for r in rows if r['youtube_id'] and not r['hidden']),
                           wide_ready=engine is not None and 'wide' in t.c)


def _tutorial_or_404(engine, t, tid):
    with engine.connect() as conn:
        row = conn.execute(t.select().where(t.c.id == tid)).mappings().first()
    if not row:
        abort(404)
    return row


@console_bp.route('/tutorials/add', methods=['POST'])
@login_required
def tutorial_add():
    engine, t = _tutorials_table()
    if engine is None:
        abort(404)
    values, error = _tutorial_values(request.form, t)
    if error:
        flash(error, 'error')
        return redirect(url_for('console.tutorials'))
    from sqlalchemy import func, select
    with engine.begin() as conn:
        values['position'] = (conn.execute(select(func.max(t.c.position))).scalar() or 0) + 1   # at the end
        conn.execute(t.insert().values(**values))
    audit('tutorial_add', values['title'][:80], values['youtube_id'] or 'no link yet')
    flash(f'Added "{values["title"]}".' + ('' if values['youtube_id'] and not values['hidden'] else
                                          ' It shows on the site once it has a YouTube link and "Show" is ticked.'), 'ok')
    return redirect(url_for('console.tutorials'))


@console_bp.route('/tutorials/starters', methods=['POST'])
@login_required
def tutorial_starters():
    """Fill an empty list with the first six videos (no links yet: paste them in after uploading)."""
    engine, t = _tutorials_table()
    if engine is None:
        abort(404)
    from sqlalchemy import func, select
    with engine.begin() as conn:
        if not conn.execute(select(func.count()).select_from(t)).scalar():
            now = datetime.utcnow()
            conn.execute(t.insert(), [dict(position=i, title=a, about=b, length=n, youtube_id=None, hidden=False, updated_at=now)
                                      for i, (a, b, n) in enumerate(STARTER_TUTORIALS)])
            audit('tutorial_starters', None, f'{len(STARTER_TUTORIALS)} videos')
            flash('Added the first six videos. Paste each YouTube link and press Save.', 'ok')
    return redirect(url_for('console.tutorials'))


@console_bp.route('/tutorials/<int:tid>', methods=['POST'])
@login_required
def tutorial_save(tid):
    engine, t = _tutorials_table()
    if engine is None:
        abort(404)
    _tutorial_or_404(engine, t, tid)
    values, error = _tutorial_values(request.form, t)
    if error:
        flash(error, 'error')
        return redirect(url_for('console.tutorials') + f'#t{tid}')
    with engine.begin() as conn:
        conn.execute(t.update().where(t.c.id == tid).values(**values))
    audit('tutorial_save', values['title'][:80], ('hidden' if values['hidden'] else 'shown') + f', {values["youtube_id"] or "no link"}')
    flash(f'Saved "{values["title"]}". The site shows changes within a minute.', 'ok')
    return redirect(url_for('console.tutorials') + f'#t{tid}')


@console_bp.route('/tutorials/<int:tid>/move', methods=['POST'])
@login_required
def tutorial_move(tid):
    engine, t = _tutorials_table()
    if engine is None:
        abort(404)
    from sqlalchemy import select
    with engine.begin() as conn:
        ids = [r.id for r in conn.execute(select(t.c.id).order_by(t.c.position, t.c.id))]
        if tid not in ids:
            abort(404)
        i = ids.index(tid)
        j = i - 1 if request.form.get('dir') == 'up' else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for pos, rid in enumerate(ids):            # renumber, so the order is always clean
                conn.execute(t.update().where(t.c.id == rid).values(position=pos))
    return redirect(url_for('console.tutorials') + f'#t{tid}')


@console_bp.route('/tutorials/<int:tid>/delete', methods=['POST'])
@login_required
def tutorial_delete(tid):
    engine, t = _tutorials_table()
    if engine is None:
        abort(404)
    row = _tutorial_or_404(engine, t, tid)
    with engine.begin() as conn:
        conn.execute(t.delete().where(t.c.id == tid))
    audit('tutorial_delete', row['title'][:80])
    flash(f'Removed "{row["title"]}" from the site. (The video stays on YouTube.)', 'ok')
    return redirect(url_for('console.tutorials'))


@console_bp.route('/activity')
@login_required
def activity():
    with db.engine.connect() as conn:
        rows = conn.execute(text('SELECT at, action, target, detail, ip FROM public.console_audit '
                                 'ORDER BY at DESC LIMIT 200')).mappings().all()
    return render_template('console/activity.html', rows=rows)


@console_bp.app_template_filter('ago')
def ago(dt):
    """'today', 'yesterday', '5 days ago' (IST calendar days)."""
    if not isinstance(dt, datetime):
        return 'never'
    days = ((datetime.utcnow() + timedelta(hours=5, minutes=30)).date() - (dt + timedelta(hours=5, minutes=30)).date()).days
    return 'today' if days <= 0 else 'yesterday' if days == 1 else f'{days} days ago'


@console_bp.app_template_filter('ist')
def ist(dt):
    return (dt + timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M %p') if isinstance(dt, datetime) else '—'


# ── Paying customers ─────────────────────────────────────────────────────────

def _customers():
    from . import customers
    return customers


@console_bp.route('/customers')
@login_required
def customers_list():
    c = _customers()
    hosting = 'shared' if c.shared_ready() else 'own'
    rows = c.all_customers() if not c.missing_settings(hosting) else []
    for r in rows:
        r['badge'] = c.plan_badge(r)
        r['url'] = c.app_url(r['slug'])
    active_trials = [t for t in ops.list_trials() if t['status'] == 'active']
    return render_template('console/customers.html', rows=rows, missing=c.missing_settings(hosting),
                           missing_own=c.missing_settings('own'), shared_ready=c.shared_ready(),
                           links=__import__('app.subscription', fromlist=['links_enabled']).links_enabled(),
                           trials=active_trials, base_domain=tenancy.base_domain(), plans=c.PLANS)


@console_bp.route('/customers', methods=['POST'])
@login_required
def customers_create():
    c = _customers()
    source = request.form.get('source', 'new')
    trial = request.form.get('trial', '').strip() if source == 'trial' else None
    slug = trial or request.form.get('slug', '').strip().lower()
    phone = re.sub(r'\D', '', request.form.get('phone', ''))[:15]
    if request.form.get('collect') == 'link':        # pay first: the app is made when the payment arrives
        from . import subscription
        name, plan = request.form.get('name', '').strip(), request.form.get('plan', '')
        try:
            if trial:
                pay = subscription.create_payment_link(trial, plan, name, phone, request.form.get('email', '').strip())
            else:
                c.create_pending(slug, name, plan, request.form.get('admin_username', 'admin'), phone,
                                 hosting=request.form.get('hosting') or ('shared' if c.shared_ready() else 'own'))
                pay = subscription.create_payment_link(slug, plan, name, phone, request.form.get('email', '').strip(),
                                                       kind='new')
        except (c.CustomerError, subscription.PaymentError, tenancy.TenantError) as exc:
            flash(f'Could not make the payment link: {exc}', 'error')
            return redirect(url_for('console.customers_list'))
        audit('payment_link', pay['slug'], f'{plan}, {"new customer" if pay["kind"] == "new" else "trial"}')
        return redirect(url_for('console.payment_link', payment_id=pay['id']))
    try:
        row = c.start(slug, request.form.get('name', ''), request.form.get('plan', ''), source_trial=trial,
                      admin_username=request.form.get('admin_username', 'admin'), phone=phone,
                      hosting=request.form.get('hosting') or ('shared' if c.shared_ready() else 'own'))
    except (c.CustomerError, ops.OpsError, tenancy.TenantError) as exc:
        flash(f'Could not start: {exc}', 'error')
        return redirect(url_for('console.customers_list'))
    audit('customer_create', row['slug'], f'plan {row["plan"]}, {row.get("hosting") or "own"} app'
          + (f', from trial {trial}' if trial else ', new'))
    return redirect(url_for('console.customer_detail', slug=row['slug']))


def _customer_or_404(slug):
    row = _customers().get(slug)
    if not row:
        abort(404)
    return row


@console_bp.route('/customers/<slug>')
@login_required
def customer_detail(slug):
    c = _customers()
    row = _customer_or_404(slug)
    if row['status'] == 'provisioning':
        row = c.resume(slug)                      # continues, e.g. connects the address once the build is ready
        if row['status'] == 'active':
            audit('customer_ready', slug)
    # Only once setup is finished: the setup page refreshes itself, which would hide a one-time password
    username, password = (c.take_pending_password(slug) if row['status'] == 'active' and row['secrets'] else (None, None))
    live, rev, admins, locked, live_error, boq_state = None, None, [], set(), None, None
    if row['status'] == 'active':
        try:
            live, rev = c.live_status(slug)
            admins = c.admin_usernames(slug)
            locked = c.locked_fields(slug)
            boq_state = c.boq_status(slug)
        except Exception as exc:
            live_error = str(exc)
    secrets_ = c.unseal(row['secrets']) if row['secrets'] else {}
    message = ''
    from . import texts
    if password:
        message = texts.render('customer_ready', product=_product(), url=c.app_url(slug), username=username,
                               password=password, tutorials=_tutorials_line())[1]
    elif row['status'] == 'active' and row['source_trial']:
        message = texts.render('customer_subscribed', product=_product(), url=c.app_url(slug))[1]
    with db.engine.connect() as conn:
        history = conn.execute(text("SELECT at, action, detail FROM public.console_audit WHERE target = :s "
                                    "ORDER BY at DESC LIMIT 30"), {'s': slug}).mappings().all()
    from . import subscription
    pending_link, pay_email = None, ''
    if row['status'] == 'awaiting_payment':
        subscription.ensure_table()
        with db.engine.connect() as conn:
            pending_link = conn.execute(text("SELECT id FROM public.platform_payments WHERE slug = :s AND kind = 'new' "
                                             "ORDER BY created_at DESC LIMIT 1"), {'s': slug}).mappings().first()
    elif row['status'] == 'active' and live is not None:
        try:
            from .models import AppSetting
            with c.open_customer(slug):
                pay_email = AppSetting.get('company_email', '') or ''
        except Exception:
            pass
    info = full_contact([slug, row.get('source_trial')], c.open_customer(slug) if row['status'] == 'active' and live is not None
                        else None, extra_phone=row.get('phone') or '')
    return render_template('console/customer.html', row=row, c=c, steps=c.steps_for(row), step_labels=c.STEP_LABELS, info=info,
                           links=subscription.links_enabled(), pending_link=pending_link, pay_email=pay_email,
                           prices=subscription.prices(),
                           next_step=c.next_step(row) if row['status'] in ('provisioning', 'failed') else None,
                           username=username, password=password, message=message,
                           wa_url=_wa_link(row['phone'], message) if message else '', live=live, rev=rev,
                           head=c.head_revision(), admins=admins, locked=locked, live_error=live_error,
                           pooler_note=secrets_.get('pooler_note'), history=history, url=c.app_url(slug),
                           badge=c.plan_badge(row), boq=boq_state, contact_name=contact_name(slug))


@console_bp.route('/customers/<slug>/retry', methods=['POST'])
@login_required
def customer_retry(slug):
    _customer_or_404(slug)
    row = _customers().resume(slug)
    audit('customer_retry', slug, row['error'] or row['status'])
    return redirect(url_for('console.customer_detail', slug=slug))


@console_bp.route('/customers/<slug>/leftovers', methods=['POST'])
@login_required
def customer_leftovers(slug):
    c = _customers()
    try:
        c.remove_leftovers(slug)
    except Exception as exc:
        flash(str(exc), 'error')
    else:
        audit('customer_remove_leftovers', slug)
        flash('Removed the half-created database. Press Retry.', 'ok')
    return redirect(url_for('console.customer_detail', slug=slug))


@console_bp.route('/customers/<slug>/renew', methods=['POST'])
@login_required
def customer_renew(slug):
    c = _customers()
    try:
        st = c.renew(slug, request.form.get('length', ''))
    except Exception as exc:
        flash(f'Could not renew: {exc}', 'error')
    else:
        audit('customer_renew', slug, f'+{request.form.get("length")} → ends {st.ends_on.isoformat()}')
        flash(f'Renewed: plan {st.plan} now ends {st.ends_on.strftime("%d %b %Y")}.', 'ok')
    return redirect(url_for('console.customer_detail', slug=slug))


@console_bp.route('/customers/<slug>/reset-password', methods=['POST'])
@login_required
def customer_reset_password(slug):
    c = _customers()
    try:
        username, password = c.reset_admin_password(slug, request.form.get('username') or None)
    except Exception as exc:
        flash(str(exc), 'error')
        return redirect(url_for('console.customer_detail', slug=slug))
    audit('customer_reset_password', slug, username)
    message = (f"Hi! Your new {_product()} password is ready.\n\nOpen: {c.app_url(slug)}\nUsername: {username}\n"
               f"Password: {password}")
    row = c.get(slug)
    return render_template('console/result.html', title=f'New password for "{slug}"',
                           trial={'slug': slug, 'url': c.app_url(slug), 'username': username, 'password': password,
                                  'ends_on': row['ends_on']}, message=message,
                           wa_url=_wa_link(row['phone'], message), phone=row['phone'], manage_endpoint='customer_detail')


@console_bp.route('/customers/<slug>/unlock', methods=['POST'])
@login_required
def customer_unlock(slug):
    from .branding import LOCKABLE
    fields = [f for f in request.form.getlist('fields') if f in LOCKABLE]
    if fields:
        try:
            _customers().unlock_company(slug, fields)
        except Exception as exc:
            flash(str(exc), 'error')
        else:
            audit('customer_unlock', slug, ', '.join(fields))
            flash(f'Unlocked {", ".join(fields)} for one change.', 'ok')
    return redirect(url_for('console.customer_detail', slug=slug))


@console_bp.route('/customers/<slug>/costs', methods=['POST'])
@login_required
def customer_costs(slug):
    _customer_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        _customers().set_item_costs(slug, on)
    except Exception as exc:
        flash(str(exc), 'error')
    else:
        audit('customer_costs', slug, 'on' if on else 'off')
        flash(f'"Your cost" on each item is now {"on" if on else "off"} for "{slug}".', 'ok')
    return redirect(url_for('console.customer_detail', slug=slug) + '#features')


@console_bp.route('/customers/<slug>/photos', methods=['POST'])
@login_required
def customer_photos(slug):
    _customer_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        _customers().set_photos(slug, on)
    except Exception as exc:
        flash(str(exc), 'error')
    else:
        audit('customer_photos', slug, 'on' if on else 'off')
        flash(f'Photos on items are now {"on" if on else "off"} for "{slug}".', 'ok')
    return redirect(url_for('console.customer_detail', slug=slug) + '#features')


@console_bp.route('/customers/<slug>/gst', methods=['POST'])
@login_required
def customer_gst(slug):
    _customer_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        _customers().set_quote_gst(slug, on, request.form.get('rate', '18'))
    except Exception as exc:
        flash(str(exc), 'error')
    else:
        audit('customer_gst', slug, f"on {request.form.get('rate')}%" if on else 'off')
        flash(f'GST on quotations is now {"on at " + request.form.get("rate", "18") + "%" if on else "off"} for "{slug}".', 'ok')
    return redirect(url_for('console.customer_detail', slug=slug) + '#features')


@console_bp.route('/customers/<slug>/rate-column', methods=['POST'])
@login_required
def customer_rate_column(slug):
    _customer_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        _customers().set_show_rate(slug, on)
    except Exception as exc:
        flash(str(exc), 'error')
    else:
        audit('customer_rate_column', slug, 'shown' if on else 'hidden')
        flash(f'The Rate column is now {"shown" if on else "hidden"} on "{slug}"\'s quotations.', 'ok')
    return redirect(url_for('console.customer_detail', slug=slug) + '#features')


@console_bp.route('/customers/<slug>/presentation', methods=['POST'])
@login_required
def customer_presentation(slug):
    _customer_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        _customers().set_presentation(slug, on)
    except Exception as exc:
        flash(str(exc), 'error')
    else:
        audit('customer_presentation', slug, 'on' if on else 'off')
        flash(f'Presentation pages are now {"on" if on else "off"} for "{slug}".', 'ok')
    return redirect(url_for('console.customer_detail', slug=slug) + '#features')


@console_bp.route('/customers/<slug>/boq', methods=['POST'])
@login_required
def customer_boq(slug):
    _customer_or_404(slug)
    on = request.form.get('on') == '1'
    try:
        _customers().set_boq(slug, on)
    except Exception as exc:
        flash(str(exc), 'error')
    else:
        audit('customer_boq', slug, 'on' if on else 'off')
        flash(f'"{slug}" now prices {"by item (BOQ lines)" if on else "by material"}.', 'ok')
    return redirect(url_for('console.customer_detail', slug=slug) + '#features')


@console_bp.route('/customers/<slug>/price-list', methods=['POST'])
@login_required
def customer_price_list(slug):
    _customer_or_404(slug)
    from . import price_list
    try:
        parsed = price_list.parse(request.files['file'].read() if 'file' in request.files else b'')
        result = _customers().load_price_list(slug, parsed, request.form.get('remove_starter') == '1',
                                              request.form.get('replace_settings') == '1')
    except Exception as exc:
        flash(str(exc), 'error')
    else:
        audit('customer_price_list', slug, f"{result['added']} added, {result['updated']} updated")
        flash(f'Price list loaded for "{slug}": ' + price_list.summary_text(result), 'ok')
    return redirect(url_for('console.customer_detail', slug=slug) + '#features')


@console_bp.route('/customers/<slug>/delete', methods=['POST'])
@login_required
def customer_delete(slug):
    if request.form.get('confirm', '').strip().lower() != f'delete {slug}':
        flash(f'Type "delete {slug}" exactly to confirm.', 'error')
        return redirect(url_for('console.customer_detail', slug=slug))
    try:
        _customers().delete(slug)
    except Exception as exc:
        flash(f'Could not delete: {exc}', 'error')
        return redirect(url_for('console.customer_detail', slug=slug))
    audit('customer_delete', slug)
    flash(f'Deleted customer "{slug}": their app, database and login are gone.', 'ok')
    return redirect(url_for('console.customers_list'))


@console_bp.route('/customers/<slug>/reveal', methods=['POST'])
@login_required
def customer_reveal(slug):
    """Database link + key for manual jobs (data export, emergencies). Logged."""
    c = _customers()
    row = _customer_or_404(slug)
    s = c.unseal(row['secrets']) if row['secrets'] else {}
    if not s.get('direct_url'):
        flash('No database yet.', 'error')
        return redirect(url_for('console.customer_detail', slug=slug))
    audit('customer_reveal_secrets', slug)
    return render_template('console/reveal.html', row=row, direct_url=s['direct_url'], data_key=s['data_key'])


@console_bp.route('/customers/<slug>/diagnose', methods=['GET', 'POST'])
@login_required
def customer_diagnose(slug):
    row = _customer_or_404(slug)
    checks = None
    if request.method == 'POST':
        checks = _customers().diagnose(slug, request.form.get('password') or None)
        audit('customer_diagnose', slug)
    return render_template('console/diagnose.html', row=row, checks=checks)


# ── Database updates ─────────────────────────────────────────────────────────

@console_bp.route('/updates', methods=['GET', 'POST'])
@login_required
def updates():
    c = _customers()
    targets = c.update_targets()
    results = []
    if request.method == 'POST':
        wanted = request.form.get('target', 'all')
        keys = [k for k, _ in targets] if wanted == 'all' else [wanted]
        labels = dict(targets)
        started = time.time()
        for key in keys:
            if key not in labels:
                continue
            if time.time() - started > 40:                 # stay inside the function time limit
                results.append((labels[key], False, 'not run (time limit): press Update all again'))
                continue
            try:
                results.append((labels[key], True, c.run_update(key)))
            except Exception as exc:
                results.append((labels[key], False, str(exc)[:400]))
        audit('db_update', wanted, '; '.join(f'{l}: {"ok" if ok else "FAILED"}' for l, ok, _ in results))
    return render_template('console/updates.html', targets=targets, results=results, head=c.head_revision())


# ── Plans bought in the app (Razorpay, the platform's account): payments, moving paid trials ──────────────

@console_bp.route('/billing/razorpay-webhook', methods=['POST'])
def platform_webhook():
    """Razorpay → here on order.paid: record a payment whose browser closed before returning (once), add the plan,
    then move a paid trial to its own database. Signed with PLATFORM_RAZORPAY_WEBHOOK_SECRET; no sign-in."""
    import json
    from flask import jsonify
    from . import subscription
    body = request.get_data()
    if not subscription.verify_webhook(body, request.headers.get('X-Razorpay-Signature', '')):
        current_app.logger.warning('Platform webhook rejected: bad or missing signature')
        return jsonify({'error': 'invalid signature'}), 400
    try:
        result = subscription.handle_webhook(json.loads(body))
    except Exception:
        current_app.logger.exception('Platform webhook failed')
        return jsonify({'error': 'not recorded'}), 500              # Razorpay retries later
    moved = {}
    if result in ('already recorded',) or result.startswith('paid'):     # a retry carries on an unfinished move
        moved = subscription.move_all_paid() if subscription.auto_move() else {}
    audit('platform_payment', None, f'{result}' + (f'; moved {moved}' if moved else ''))
    return jsonify({'ok': True, 'result': result})


@console_bp.route('/cron/tick')
def cron_tick():
    """Daily safety net (Vercel Cron, Authorization: Bearer CRON_SECRET): move paid trials not moved yet and carry
    on any customer setup that stopped half-way."""
    from flask import jsonify
    from . import subscription
    secret = (os.environ.get('CRON_SECRET') or '').strip()
    if not secret or not hmac.compare_digest(request.headers.get('Authorization', ''), f'Bearer {secret}'):
        abort(404)
    out = subscription.move_all_paid() if subscription.auto_move() else {}
    from . import signup
    if signup._env('SIGNUP_SECRET'):                # ready-made trials, only once self-serve trials are set up
        try:
            made = ops.top_up_spares()
            if made:
                out['spares'] = made
        except Exception as exc:
            out['spares'] = f'failed: {exc}'
    try:
        from . import followups
        trials_f, _ = _followup_trials()
        stage_mails = followups.send_stage_emails(trials_f)   # not signed in / no details / no quotation (once each)
        if stage_mails:
            out['stage_emails'] = stage_mails
    except Exception as exc:
        out['stage_emails'] = f'failed: {exc}'
    try:
        sent = subscription.send_reminders()             # trial / plan ending emails (once each)
        if sent:
            out['reminders'] = sent
    except Exception as exc:
        out['reminders'] = f'failed: {exc}'
    c = _customers()
    for row in c.all_customers():
        if row['status'] == 'provisioning' and row.get('hosting') == 'shared':
            out[row['slug']] = (c.resume(row['slug']) or {}).get('status')
    if out:
        audit('cron_tick', None, str(out)[:500])
    return jsonify({'ok': True, 'moved': out})


@console_bp.route('/payments')
@login_required
def payments():
    from . import subscription
    rows = subscription.history(limit=300)
    total = sum(r['amount_paise'] for r in rows) / 100
    month = plan_mod.today().strftime('%Y-%m')
    this_month = sum(r['amount_paise'] for r in rows if r['paid_at'] and r['paid_at'].strftime('%Y-%m') == month) / 100
    businesses = [(t['slug'], 'trial') for t in ops.list_trials() if t['status'] == 'active']
    businesses += [(c['slug'], 'customer') for c in _customers().all_customers() if c['status'] == 'active']
    return render_template('console/payments.html', rows=rows, total=total, this_month=this_month,
                           pending=subscription.paid_trials(), keys_set=bool(os.environ.get('PLATFORM_RAZORPAY_WEBHOOK_SECRET')),
                           auto=subscription.auto_move(), base_domain=tenancy.base_domain(),
                           businesses=sorted(businesses), methods=subscription.MANUAL_METHODS, prices=subscription.prices(),
                           today=plan_mod.today().isoformat(), mail_ready=__import__('app.mailer', fromlist=['enabled']).enabled())


@console_bp.route('/payments/manual', methods=['POST'])
@login_required
def payments_manual():
    """Record a payment received outside Razorpay (UPI to you, bank transfer, cash)."""
    from datetime import date
    from . import subscription
    f = request.form
    try:
        paid_on = date.fromisoformat(f.get('paid_on', '')) if f.get('paid_on') else None
    except ValueError:
        paid_on = None
    try:
        row = subscription.record_manual(f.get('slug', ''), f.get('plan', ''), f.get('amount', ''), f.get('method', ''),
                                         f.get('reference', ''), paid_on, add_plan=f.get('add_plan') == '1',
                                         payer_name=f.get('payer', '').strip() or contact_name(f.get('slug', '')))
    except subscription.PaymentError as exc:
        flash(f'Could not record the payment: {exc}', 'error')
        return redirect(url_for('console.payments') + '#record')
    audit('payment_manual', row['slug'], f"{row['receipt_no']} ₹{row['amount_paise'] / 100:,.0f} {row['paid_by']}")
    if f.get('notify') == '1':
        subscription.notify_paid(row)
    moved = ''
    if f.get('add_plan') == '1' and subscription.auto_move():
        try:
            out = subscription.move_all_paid()
            moved = ' Moved to its own database.' if out.get(row['slug']) == 'active' else ''
        except Exception:
            pass
    flash(f"Payment recorded: {row['receipt_no']}, ₹{row['amount_paise'] / 100:,.0f} from {row['business_name'] or row['slug']}"
          + (f", plan until {row['plan_end']:%d %b %Y}." if row.get('plan_end') else '.') + moved, 'ok')
    return redirect(url_for('console.payments'))


@console_bp.route('/payments/<int:payment_id>/delete', methods=['POST'])
@login_required
def payments_delete(payment_id):
    """Remove a payment record (a test payment). Their plan isn't changed."""
    from . import subscription
    row = subscription.delete_payment(payment_id)
    if not row:
        abort(404)
    audit('payment_delete', row['slug'], f"{row.get('receipt_no') or row['order_id']} ₹{row['amount_paise'] / 100:,.0f}")
    flash(f"Removed payment {row.get('receipt_no') or ''} (₹{row['amount_paise'] / 100:,.0f}, {row['slug']}). "
          "Their plan wasn't changed.", 'ok')
    return redirect(url_for('console.payments'))


@console_bp.route('/payments/<int:payment_id>/receipt-email', methods=['POST'])
@login_required
def payments_receipt_email(payment_id):
    """Email (again) the receipt of a payment, to the address typed or the one on the payment / in their app."""
    from . import mailer, subscription
    row = subscription.get(payment_id)
    if not row or row['status'] != 'paid':
        abort(404)
    to = (request.form.get('to') or '').strip()[:120] or subscription.receipt_email(row)
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', to or ''):
        flash('No email address for this payment: type one next to "Email receipt".', 'error')
    elif not mailer.enabled():
        flash('Email isn\'t set up on the console (PLATFORM_SMTP_*).', 'error')
    elif subscription.send_receipt(row, to):
        if not row.get('email'):
            with db.engine.begin() as conn:
                conn.execute(text('UPDATE public.platform_payments SET email = :e WHERE id = :i'), {'e': to, 'i': row['id']})
        audit('payment_receipt_email', row['slug'], f"{row['receipt_no']} to {mailer.mask(to)}")
        flash(f"Receipt {row['receipt_no']} emailed to {to}, with a copy in hello@.", 'ok')
    else:
        flash('The receipt could not be sent. Check the mail settings and try again.', 'error')
    return redirect(url_for('console.payments'))


@console_bp.route('/payments/move/<slug>', methods=['POST'])
@login_required
def payments_move(slug):
    from . import subscription
    try:
        row = subscription.move_paid_trial(slug)
    except Exception as exc:
        flash(f'Could not move "{slug}": {exc}', 'error')
        return redirect(url_for('console.payments'))
    audit('payment_move', slug, (row or {}).get('status', ''))
    flash(f'"{slug}" moved to its own database.' if (row or {}).get('status') == 'active'
          else f'"{slug}": {(row or {}).get("error") or "not finished"}', 'ok' if (row or {}).get('status') == 'active' else 'error')
    return redirect(url_for('console.customer_detail', slug=slug) if (row or {}).get('status') else url_for('console.payments'))


@console_bp.route('/payments/<int:payment_id>/receipt')
@login_required
def payment_receipt(payment_id):
    from flask import send_file
    from . import subscription
    row = subscription.get(payment_id)
    if not row or row['status'] != 'paid':
        abort(404)
    if not row.get('payer_name'):                  # paid before names were kept: from their trial request, and keep it
        name = contact_name(row['slug'])
        if name:
            row['payer_name'] = name
            subscription.set_payer_name(row['id'], name)
    return send_file(subscription.receipt_pdf(row), mimetype='application/pdf',
                     download_name=f'QuoteRoom-receipt-{row["receipt_no"]}.pdf')


# ── Self-serve trials: the public /start page (app/signup.py) ────────────────────────────────────────────────

def load_lead(lead_id):
    """One trial request from the website's database (decrypted), or None."""
    from sqlalchemy import inspect, select
    from . import crypto
    from .models import Lead
    engine = _leads_engine_or_none()
    if engine is None:
        return None
    t = Lead.__table__
    with crypto.using_key(_env('LEADS_DATA_ENCRYPTION_KEY')), engine.connect() as conn:
        present = {c['name'] for c in inspect(conn).get_columns('leads')}
        row = conn.execute(select(*[c for c in t.c if c.name in present]).where(t.c.id == lead_id)).mappings().first()
    if not row:
        return None
    lead = dict(row)
    for later in ('company_name', 'city', 'email'):
        lead.setdefault(later, None)
    return lead


def address_problem(slug):
    """Why this web address can't be used, or ''."""
    try:
        slug = tenancy.validate_slug(slug)
    except tenancy.TenantError as exc:
        return str(exc)
    if slug.startswith(ops.SPARE_PREFIX):
        return 'Choose another address.'
    tenancy.ensure_registry()
    with db.engine.connect() as conn:
        taken = conn.execute(text('SELECT 1 FROM public.tenants WHERE slug = :s'), {'s': slug}).first()
        if not taken and conn.execute(text("SELECT to_regclass('public.customers')")).scalar():
            taken = conn.execute(text("SELECT 1 FROM public.customers WHERE slug = :s AND status <> 'deleted'"),
                                 {'s': slug}).first()
    return f'{slug}.{tenancy.base_domain()} is taken. Try another.' if taken else ''


def _free_address(text_):
    base = suggest_slug(text_)
    for n in range(0, 50):
        slug = base if n == 0 else f'{base[:26]}-{n + 1}'
        if not address_problem(slug):
            return slug
    return ''


def _signup(lead_id):
    """The app already made for this request: set up by them (/start) or by you from the console (Create trial on the
    request), so the emailed link opens it instead of making a second one."""
    with db.engine.connect() as conn:
        return (conn.execute(text('SELECT slug FROM public.signups WHERE lead_id = :i'), {'i': lead_id}).scalar()
                or conn.execute(text("SELECT slug FROM public.console_lead_links WHERE lead_id = :i AND status = 'trial' "
                                     "AND slug IS NOT NULL"), {'i': lead_id}).scalar())


@console_bp.route('/e/o/<token>.gif')
def email_opened(token):
    """Public: the open image in an email (app/emails.py)."""
    from flask import Response
    from . import emails
    if re.fullmatch(r'[A-Za-z0-9._-]{10,60}', token):
        try:
            emails.record_open(token)
        except Exception:
            pass
    return Response(emails.GIF, mimetype='image/gif',
                    headers={'Cache-Control': 'no-store, max-age=0', 'X-Robots-Tag': 'noindex'})


@console_bp.route('/e/c/<token>/<int:n>')
def email_clicked(token, n):
    """Public: a link in an email; noted, then on to where it points (only links that email had)."""
    from . import emails
    url = None
    if re.fullmatch(r'[A-Za-z0-9._-]{10,60}', token):
        try:
            url = emails.record_click(token, n)
        except Exception:
            url = None
    return redirect(url if url and url.startswith(('https://', 'http://')) else _site_url())


@console_bp.route('/start', methods=['GET', 'POST'])
def start_trial():
    """Public: the business that asked for a trial on the website sets up its own app (signed, single-use link).
    ?plan=6m|1y: they chose a plan on the website, so after the app is made they go on to pay for it."""
    from . import signup, subscription
    token = request.values.get('t', '')
    plan = request.values.get('plan') if request.values.get('plan') in signup.PLANS else None
    lead_id = signup.read_token(token)
    lead = load_lead(lead_id) if lead_id else None
    if not lead or (lead.get('business_type') not in signup.ELIGIBLE and not plan):
        return render_template('console/start.html', problem='This link has expired or isn\'t valid. Request a free '
                               'trial again on the website, or message us on WhatsApp.', site=_site_url()), 404
    if request.method == 'GET':
        from . import emails
        try:
            emails.setup_link_opened(lead_id)       # the set-up email worked: they opened its link
        except Exception:
            pass
    price = subscription.prices()[plan] if plan else None
    done = _signup(lead_id)
    if done:
        return render_template('console/start.html', ready=done, base=tenancy.base_domain(), site=_site_url(),
                               plan=plan, price=price, token=token, paid=_paid_plan(done))
    form = {'company': lead.get('company_name') or '', 'username': 'admin'}
    errors = {}
    if request.method == 'POST':
        form = {k: (request.form.get(k) or '').strip() for k in ('company', 'username')}
        password = request.form.get('password') or ''
        ip_hash = hashlib.sha256(_client_ip().encode()).hexdigest()
        with db.engine.connect() as conn:
            recent = conn.execute(text("SELECT COUNT(*) FROM public.signups WHERE ip_hash = :h AND created_at > "
                                       "(now() AT TIME ZONE 'utc') - INTERVAL '1 hour'"), {'h': ip_hash}).scalar()
        if recent >= signup.MAX_PER_IP_PER_HOUR:
            errors['form'] = 'Too many new apps from here in the last hour. Please try again later.'
        if len(form['company']) < 2:
            errors['company'] = 'Enter your company name.'
        if not re.fullmatch(r'[A-Za-z0-9._-]{3,40}', form['username']):
            errors['username'] = 'Use 3–40 letters, numbers, dots, dashes or underscores.'
        if len(password) < 8:
            errors['password'] = 'Use at least 8 characters.'
        elif password != request.form.get('password2'):
            errors['password2'] = 'The passwords don\'t match.'
        if not request.form.get('terms'):
            errors['terms'] = 'Please accept the terms to continue.'
        if not errors and not signup.turnstile_ok(request.form.get('cf-turnstile-response'), _client_ip()):
            errors['form'] = 'Please complete the check that you\'re not a robot.'
        t = None
        for _ in range(3) if not errors else ():   # the address comes from the firm's name (a number added if taken)
            slug = _free_address(form['company'])
            if not slug:
                errors['company'] = 'Could not make a web address from this name. Add a word or two.'
                break
            try:
                t = ops.claim_trial(slug, form['username'], password, 7, company=form['company'],
                                    phone=lead.get('phone'), city=lead.get('city'), email=lead.get('email'))
                break
            except ops.OpsError as exc:
                if 'is taken' not in str(exc):           # taken by someone else a moment ago: try the next one
                    errors['form'] = str(exc)
                    break
        if t is not None:
            with db.engine.begin() as conn:
                conn.execute(text('INSERT INTO public.signups (lead_id, slug, ip_hash) VALUES (:i, :s, :h)'),
                             {'i': lead_id, 's': t['slug'], 'h': ip_hash})
            _link_lead(lead_id, 'trial', t['slug'])
            audit('trial_self_start', t['slug'], f'lead #{lead_id}, {form["company"]}' + (f', buying {plan}' if plan else ''))
            if plan:
                return _go_pay(t['slug'], plan, lead, token, company=form['company'])
            return render_template('console/start.html', ready=t['slug'], base=tenancy.base_domain(),
                                   username=form['username'], site=_site_url(), new=True)
    return render_template('console/start.html', form=form, errors=errors, token=token, lead=lead, plan=plan, price=price,
                           address=_free_address(form['company'] or lead['name']), base=tenancy.base_domain(),
                           site=_site_url(), turnstile=signup.turnstile_site_key())


def _paid_plan(slug):
    """The plan this business has paid for (latest), or None."""
    from . import subscription
    subscription.ensure_table()
    with db.engine.connect() as conn:
        return conn.execute(text("SELECT plan FROM public.platform_payments WHERE slug = :s AND status = 'paid' "
                                 "ORDER BY paid_at DESC LIMIT 1"), {'s': slug}).scalar()


def _go_pay(slug, plan, lead, token, company=''):
    """Send a business buying on the website to Razorpay for its plan (a payment link, reused if they come back)."""
    from . import emails, subscription
    try:
        row = subscription.open_link(slug, plan) or subscription.create_payment_link(
            slug, plan, company or lead.get('company_name') or '', lead.get('phone') or '', lead.get('email') or '',
            paid_by='website', payer_name=lead.get('name') or '',
            callback_url=f'{emails.base_url()}{url_for("console.start_paid", t=token)}')
    except subscription.PaymentError as exc:
        current_app.logger.warning('Website plan payment link failed for %s: %s', slug, exc)
        audit('website_pay_failed', slug, str(exc)[:200])
        return render_template('console/start.html', ready=slug, base=tenancy.base_domain(), site=_site_url(), new=True,
                               plan=plan, pay_failed=True)
    return redirect(row['link_url'])


@console_bp.route('/start/pay', methods=['POST'])
def start_pay():
    """Public: pay for the plan chosen on the website, for the app already made from this request."""
    from . import signup
    lead_id = signup.read_token(request.form.get('t', ''))
    plan = request.form.get('plan')
    lead = load_lead(lead_id) if lead_id else None
    slug = _signup(lead_id) if lead else None
    if not slug or plan not in signup.PLANS:
        abort(404)
    return _go_pay(slug, plan, lead, request.form.get('t', ''))


@console_bp.route('/start/paid')
def start_paid():
    """Public: Razorpay sends the payer back here from the payment link. A valid, paid callback adds the plan now
    (the webhook does the same if this page is never reached; whichever comes first counts, once)."""
    from . import signup, subscription
    token = request.args.get('t', '')
    lead_id = signup.read_token(token)
    slug = _signup(lead_id) if lead_id else None
    row = subscription.get_by_order(request.args.get('razorpay_payment_link_id', ''))
    if not slug or not row or row['slug'] != slug:
        return render_template('console/start.html', problem='We couldn\'t match this payment to your app. If you were '
                               'charged, message us on WhatsApp and we\'ll sort it out straight away.', site=_site_url()), 404
    paid = (request.args.get('razorpay_payment_link_status') == 'paid' and subscription.verify_link_callback(request.args))
    if paid:
        try:
            subscription.settle(row, request.args.get('razorpay_payment_id', ''), 'callback')
        except Exception:
            current_app.logger.exception('Recording the website payment failed (the webhook will retry)')
        audit('website_paid', slug, row['plan'])
    return render_template('console/start.html', ready=slug, base=tenancy.base_domain(), site=_site_url(), token=token,
                           plan=row['plan'], price=row['amount_paise'] // 100, paid=row['plan'] if paid else _paid_plan(slug),
                           just_paid=paid)


@console_bp.route('/start/check')
def start_check():
    """Public: the web address this firm name gets (for the /start page as they type the name)."""
    from flask import jsonify
    from . import signup
    if not signup.read_token(request.args.get('t', '')):
        abort(404)
    slug = _free_address((request.args.get('company') or '').strip())
    return jsonify({'ok': bool(slug), 'slug': slug, 'address': f'{slug}.{tenancy.base_domain()}' if slug else ''})


# ── Payment links (the operator sends them on WhatsApp / email) ─────────────────────────────────────────────

@console_bp.route('/payments/link', methods=['POST'])
@login_required
def payment_link_create():
    """A payment link for a trial (to subscribe) or a customer (to renew), from their console page."""
    from . import subscription
    slug = request.form.get('slug', '')
    phone = re.sub(r'\D', '', request.form.get('phone', ''))[:15]
    try:
        pay = subscription.create_payment_link(slug, request.form.get('plan', ''), request.form.get('name', '').strip(),
                                               phone, request.form.get('email', '').strip(),
                                               payer_name=request.form.get('payer', '').strip() or contact_name(slug))
    except subscription.PaymentError as exc:
        flash(f'Could not make the payment link: {exc}', 'error')
        return redirect(request.referrer or url_for('console.payments'))
    audit('payment_link', slug, pay['plan'])
    return redirect(url_for('console.payment_link', payment_id=pay['id']))


@console_bp.route('/payments/<int:payment_id>/link')
@login_required
def payment_link(payment_id):
    from . import subscription
    row = subscription.get(payment_id)
    if not row or not row.get('link_url'):
        abort(404)
    message = subscription.link_message(row)
    return render_template('console/payment_link.html', row=row, message=message,
                           wa_url=_wa_link(row.get('phone') or '', message),
                           mail_ready=__import__('app.mailer', fromlist=['enabled']).enabled())


@console_bp.route('/payments/<int:payment_id>/proforma', methods=['POST'])
@login_required
def payment_proforma(payment_id):
    """A proforma invoice (PDF) for a payment link: for a customer who asks for an invoice before paying."""
    from flask import send_file
    from . import subscription
    row = subscription.get(payment_id)
    if not row:
        abort(404)
    bill_to = request.form.get('bill_to', '').strip()[:120]
    address = request.form.get('address', '').strip()[:400]
    buf = subscription.proforma_pdf(row, bill_to, address)
    audit('payment_proforma', row['slug'], subscription.proforma_no(row))
    return send_file(buf, mimetype='application/pdf', as_attachment=True,
                     download_name=f'QuoteRoom-proforma-{subscription.proforma_no(row)}.pdf')


@console_bp.route('/payments/<int:payment_id>/link/email', methods=['POST'])
@login_required
def payment_link_email(payment_id):
    from . import subscription
    row = subscription.get(payment_id)
    if not row or not row.get('link_url'):
        abort(404)
    to = request.form.get('email', '').strip()
    if subscription.email_link(row, to):
        audit('payment_link_email', row['slug'], to)
        flash(f'Payment link emailed to {to}.', 'ok')
    else:
        flash('Could not send the email (check the address, and the email settings: PLATFORM_SMTP_*).', 'error')
    return redirect(url_for('console.payment_link', payment_id=payment_id))
