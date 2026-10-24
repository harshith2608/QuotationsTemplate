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
        by_day.setdefault(d, {'day': d, 'starts': 0, 'quotations': 0, 'pdfs': 0})
    rows = sorted(by_day.values(), key=lambda r: r['day'], reverse=True)
    for r in rows:
        r.setdefault('site_visitors', None)
        r['requests'] = requests_by_day.get(r['day'], 0)
    keys = ('site_visitors', 'starts', 'quotations', 'pdfs', 'requests')

    def total(n):
        picked = [r for r in rows if r['day'] > today - timedelta(days=n)]
        out = {k: sum(r[k] or 0 for r in picked) for k in keys}
        out['pct'] = {k: (round(out[k] / out['site_visitors'] * 100) if out['site_visitors'] else None)
                      for k in ('starts', 'requests')}
        out['pct'].update({k: (round(out[k] / out['starts'] * 100) if out['starts'] else None) for k in ('quotations', 'pdfs')})
        return out
    return {'pending': False, 'visitors_ready': 'site_visitors' in present, 'today': total(1), 'week': total(7),
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
    hello = f'Hi {name}!' if name else 'Hi!'
    whose = f' for {company}' if company else ''
    ready = (f"I've already put in {company} and your contact details, so your quotations carry your name. "
             "Add your logo, full address and GSTIN in Settings → Company, and your own rates in Rates.\n\n") if company else ''
    return (f"{hello} Your {_product()} free trial{whose} is ready.\n\n"
            f"Open: {url}\nUsername: {username}\nPassword: {password}\n\n"
            "When you sign in, a short setup guide takes you through your rates and settings step by step.\n\n"
            + ready + _tutorials_line() +
            f"Your trial runs until {ends_on.strftime('%d %b %Y')}. On your phone, add the page to your home screen "
            "for one-tap access. Reply here if you need any help!")


def _wa_link(phone, message):
    return f"https://wa.me/{phone}?text={quote(message)}" if phone else ''


# ── Follow-up messages on WhatsApp ───────────────────────────────────────────
# Drafts for the trial page's "Message on WhatsApp" card. {name} is filled in on the page (it can be edited there);
# the rest when the page is built. The message opens in the operator's own WhatsApp (wa.me): nothing is sent from here.

PLAN_PRICES = '6 months ₹4,999 or 12 months ₹8,999, one price for your whole team'

FOLLOW_UPS = [
    ('signin', 'Not signed in yet',
     "Hi {name}, this is {sender} from {product}. Just checking you got the login I sent. If you have any trouble "
     "signing in, tell me and I'll sort it out right away.\n\nOpen: {url}\n\nIt takes about 10 minutes to set up your "
     "rates and make your first quotation."),
    ('rates', 'Help with rates (offer a call)',
     "Hi {name}, good to see you've started on {product} 👍 The next step is your rates for each material and work "
     "type. Once they're in, every quotation works itself out. If it's easier, I can set up your rates with you on a "
     "10-minute call, whenever suits you."),
    ('quote', 'Going well: make a real quotation',
     "Hi {name}, great to see you're set up on {product}! Try making a quotation for one of the customers you're "
     "quoting this week. You can send it on WhatsApp as a PDF, or as a link they can accept online. If you send me "
     "your logo, I'll add it so the PDF is in your brand. Anything you need, just message me."),
    ('checkin', 'Quiet for a while: check in',
     "Hi {name}, {sender} from {product} here. How is the trial going? If something got in the way or didn't work "
     "the way you quote, tell me. I'm happy to set it up with you on a quick call."),
    ('ending', 'Trial ending soon (plans)',
     "Hi {name}, your {product} trial ends on {ends_on}. Everything you've set up (rates, logo, quotations) stays "
     "when you continue. Plans: {prices}. Which one suits you? Happy to answer any questions on a quick call."),
    ('ended', 'Trial ended: continue or feedback',
     "Hi {name}, your {product} trial ended on {ends_on}. Your data is kept until {delete_on}, so you can continue "
     "right where you left off: {prices}. If it wasn't the right fit, could you tell me what was missing? It really "
     "helps."),
    ('custom', 'Custom message', 'Hi {name}, '),
]


def _first_name(name):
    words = (name or '').split()
    return words[0].title() if words and len(words[0]) > 1 else (name or '').strip()


def trial_contact(t):
    """{'name', 'phone', 'company'} for a trial: from the trial request it was made from (console_lead_links), else
    the phone and company name filled in on the trial."""
    from . import crypto
    from .models import AppSetting, Lead
    out = {'name': '', 'phone': '', 'company': ''}
    with db.engine.connect() as conn:
        lead_id = conn.execute(text("SELECT lead_id FROM public.console_lead_links WHERE slug = :s AND status = 'trial' "
                                    'ORDER BY lead_id DESC LIMIT 1'), {'s': t['slug']}).scalar()
    engine = _leads_engine_or_none() if lead_id else None
    if engine is not None:
        try:
            from sqlalchemy import inspect, select
            lt = Lead.__table__
            with crypto.using_key(_env('LEADS_DATA_ENCRYPTION_KEY')), engine.connect() as conn:
                present = {c['name'] for c in inspect(conn).get_columns('leads')}
                cols = [lt.c.name, lt.c.phone] + ([lt.c.company_name] if 'company_name' in present else [])
                row = conn.execute(select(*cols).where(lt.c.id == lead_id)).mappings().first()
            if row:
                out.update(name=row['name'] or '', phone=row['phone'] or '', company=row.get('company_name') or '')
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
    drafts = [(k, label, body.replace('{name}', '\0').format(**values).replace('\0', '{name}'))
              for k, label, body in FOLLOW_UPS]
    if st and st.has_limit and st.days_left < 0:
        pick = 'ended'
    elif st and st.has_limit and st.days_left <= 2:
        pick = 'ending'
    elif not u.get('last_login_at') and not u.get('used'):
        pick = 'signin'
    elif not u.get('quotations'):
        pick = 'rates'
    elif u.get('last_seen_at') and (datetime.utcnow() - u['last_seen_at'].replace(tzinfo=None)).days >= 3:
        pick = 'checkin'
    else:
        pick = 'quote'
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
    leads = load_leads()
    new_leads = [l for l in (leads or []) if not l['link_status']]
    try:
        demo_stats = load_demo_stats()
    except Exception as exc:                 # the demo database being unreachable shouldn't break the dashboard
        demo_stats = {'error': str(exc)}
    from . import signup
    return render_template('console/dashboard.html', trials=trials, leads=leads, new_leads=new_leads, demo_stats=demo_stats,
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
    try:
        days = int(days)
        t = ops.create_trial(slug, username, None, days, company=company, phone=phone, city=city, email=email)
    except (ops.OpsError, ValueError) as exc:
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
    return render_template('console/trial.html', t=t, admins=admins, locked=locked, history=history,
                           extend_choices=EXTEND_CHOICES, contact=contact, drafts=drafts, suggested=suggested,
                           boq=boq_state, links=subscription.links_enabled(), pay_email=pay_email,
                           prices=subscription.prices())


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
    if password:
        message = (f"Hi! Your {_product()} app is ready.\n\nOpen: {c.app_url(slug)}\nUsername: {username}\n"
                   f"Password: {password}\n\n" + _tutorials_line() + "On your phone, add the page to your home screen for one-tap access. "
                   "Reply here if you need any help!")
    elif row['status'] == 'active' and row['source_trial']:
        message = (f"Hi! Thank you for subscribing to {_product()}. Your app is now on your paid plan: same address "
                   f"({c.app_url(slug)}), same login and all your quotations. Reply here if you need any help!")
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
    return render_template('console/customer.html', row=row, c=c, steps=c.steps_for(row), step_labels=c.STEP_LABELS,
                           links=subscription.links_enabled(), pending_link=pending_link, pay_email=pay_email,
                           prices=subscription.prices(),
                           next_step=c.next_step(row) if row['status'] in ('provisioning', 'failed') else None,
                           username=username, password=password, message=message,
                           wa_url=_wa_link(row['phone'], message) if message else '', live=live, rev=rev,
                           head=c.head_revision(), admins=admins, locked=locked, live_error=live_error,
                           pooler_note=secrets_.get('pooler_note'), history=history, url=c.app_url(slug),
                           badge=c.plan_badge(row), boq=boq_state)


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
    return render_template('console/payments.html', rows=rows, total=total, this_month=this_month,
                           pending=subscription.paid_trials(), keys_set=bool(os.environ.get('PLATFORM_RAZORPAY_WEBHOOK_SECRET')),
                           auto=subscription.auto_move(), base_domain=tenancy.base_domain())


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
    with db.engine.connect() as conn:
        return conn.execute(text('SELECT slug FROM public.signups WHERE lead_id = :i'), {'i': lead_id}).scalar()


@console_bp.route('/start', methods=['GET', 'POST'])
def start_trial():
    """Public: the business that asked for a trial on the website sets up its own app (signed, single-use link)."""
    from . import signup
    token = request.values.get('t', '')
    lead_id = signup.read_token(token)
    lead = load_lead(lead_id) if lead_id else None
    if not lead or lead.get('business_type') not in signup.ELIGIBLE:
        return render_template('console/start.html', problem='This link has expired or isn\'t valid. Request a free '
                               'trial again on the website, or message us on WhatsApp.', site=_site_url()), 404
    done = _signup(lead_id)
    if done:
        return render_template('console/start.html', ready=done, base=tenancy.base_domain(), site=_site_url())
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
            audit('trial_self_start', t['slug'], f'lead #{lead_id}, {form["company"]}')
            return render_template('console/start.html', ready=t['slug'], base=tenancy.base_domain(),
                                   username=form['username'], site=_site_url(), new=True)
    return render_template('console/start.html', form=form, errors=errors, token=token, lead=lead,
                           address=_free_address(form['company'] or lead['name']), base=tenancy.base_domain(),
                           site=_site_url(), turnstile=signup.turnstile_site_key())


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
                                               phone, request.form.get('email', '').strip())
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
