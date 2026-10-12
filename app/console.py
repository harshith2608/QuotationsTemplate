"""
Operator console: manage trials (and trial requests) with buttons instead of terminal commands.

Runs as its OWN Vercel project (never inside a customer or trials app):

    CONSOLE_MODE=1
    DATABASE_URL=<trials pooled URL>          DATA_ENCRYPTION_KEY=<trials key>
    TENANT_BASE_DOMAIN=quote-room.co.in
    CONSOLE_PASSWORD_HASH=...  CONSOLE_TOTP_SECRET=...   (from `flask console-setup`)
    LEADS_DATABASE_URL=<demo pooled URL>      LEADS_DATA_ENCRYPTION_KEY=<demo key>   (optional: trial requests)
    MARKETING_PRODUCT_NAME=QuoteRoom          (optional, used in the welcome message)

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
    resp.headers['Referrer-Policy'] = 'no-referrer'
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
    t = Lead.__table__
    with crypto.using_key(_env('LEADS_DATA_ENCRYPTION_KEY')), engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(t.select().order_by(t.c.created_at.desc()).limit(limit)).mappings()]
    with db.engine.connect() as conn:
        links = {r.lead_id: r for r in conn.execute(text('SELECT lead_id, status, slug FROM public.console_lead_links'))}
    for r in rows:
        r['business'] = r['business_other'] if r['business_type'] == 'other' and r['business_other'] \
            else BUSINESS_TYPES.get(r['business_type'], r['business_type'])
        link = links.get(r['id'])
        r['link_status'], r['link_slug'] = (link.status, link.slug) if link else (None, None)
        r['suggested_slug'] = suggest_slug(r['business_other'] or r['name'])
    return rows


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


def _welcome_message(name, url, username, password, ends_on):
    hello = f'Hi {name}!' if name else 'Hi!'
    return (f"{hello} Your {_product()} free trial is ready.\n\n"
            f"Open: {url}\nUsername: {username}\nPassword: {password}\n\n"
            f"Your trial runs until {ends_on.strftime('%d %b %Y')}. On your phone, add the page to your home screen "
            "for one-tap access. Reply here if you need any help!")


def _wa_link(phone, message):
    return f"https://wa.me/{phone}?text={quote(message)}" if phone else ''


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
    return render_template('console/dashboard.html', trials=trials, leads=leads, new_leads=new_leads,
                           extend_choices=EXTEND_CHOICES, base_domain=tenancy.base_domain())


@console_bp.route('/trials', methods=['POST'])
@login_required
def create_trial():
    slug = request.form.get('slug', '').strip().lower()
    username = request.form.get('admin_username', '').strip() or 'admin'
    days = request.form.get('days', '7')
    lead_id = request.form.get('lead_id', type=int)
    name = request.form.get('name', '').strip()[:80]
    phone = re.sub(r'\D', '', request.form.get('phone', ''))[:15]
    try:
        days = int(days)
        t = ops.create_trial(slug, username, None, days)
    except (ops.OpsError, ValueError) as exc:
        flash(f'Could not create trial: {exc}', 'error')
        return redirect(url_for('console.dashboard'))
    if lead_id:
        _link_lead(lead_id, 'trial', t['slug'])
    audit('trial_create', t['slug'], f'{days} days' + (f', lead #{lead_id}' if lead_id else ''))
    message = _welcome_message(name, t['url'], t['username'], t['password'], t['ends_on'])
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
    admins, locked = [], set()
    if t['status'] == 'active':
        from . import branding
        admins = ops.admin_usernames(slug)
        with tenancy.tenant_context(slug, t['schema_name']):
            locked = branding.locked_fields()
    with db.engine.connect() as conn:
        history = conn.execute(text('SELECT at, action, detail FROM public.console_audit WHERE target = :s '
                                    'ORDER BY at DESC LIMIT 30'), {'s': slug}).mappings().all()
    return render_template('console/trial.html', t=t, admins=admins, locked=locked, history=history,
                           extend_choices=EXTEND_CHOICES)


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


@console_bp.route('/activity')
@login_required
def activity():
    with db.engine.connect() as conn:
        rows = conn.execute(text('SELECT at, action, target, detail, ip FROM public.console_audit '
                                 'ORDER BY at DESC LIMIT 200')).mappings().all()
    return render_template('console/activity.html', rows=rows)


@console_bp.app_template_filter('ist')
def ist(dt):
    return (dt + timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M %p') if isinstance(dt, datetime) else '—'
