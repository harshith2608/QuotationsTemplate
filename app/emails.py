"""Emails to trials and trial requests, and whether they were opened: the console's own emails (console → Email), the
stage emails (app/followups.py) and the website's set-up link email (app/signup.py).

Each email goes as text plus an HTML copy of the same words. The HTML copy carries a tiny image from the console
(/e/o/<token>.gif): when the mail app shows images, the email counts as opened. Its links go through the console
(/e/c/<token>/<n>), which notes the click and sends the reader on. Opens are a good sign, not proof (some mail apps
never load images, Apple Mail loads them for everyone); a click is certain. The set-up link already goes to the
console's /start page, so opening it is the click.

Kept in the console's database: public.console_emails, one row per email. The website (another database) can't add
rows, so its set-up email carries a token signed with SIGNUP_SECRET (open_token): the console checks it and adds the
row on the first open or click.
"""
import html as html_lib
import json
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import text

from . import db

DDL = [
    """CREATE TABLE IF NOT EXISTS public.console_emails (
        id         SERIAL PRIMARY KEY,
        token      VARCHAR(60) NOT NULL UNIQUE,
        kind       VARCHAR(20) NOT NULL,          -- 'setup' (website) / 'stage' (daily) / 'console' (sent by you)
        lead_id    INTEGER,
        slug       VARCHAR(40),
        to_addr    VARCHAR(200),
        subject    VARCHAR(200),
        sent_at    TIMESTAMP,
        opened_at  TIMESTAMP,
        opens      INTEGER NOT NULL DEFAULT 0,
        clicked_at TIMESTAMP,
        clicks     INTEGER NOT NULL DEFAULT 0,
        links      TEXT)""",
    'CREATE INDEX IF NOT EXISTS console_emails_slug ON public.console_emails (slug)',
    'CREATE INDEX IF NOT EXISTS console_emails_lead ON public.console_emails (lead_id)',
    # when tracking started: set-up emails sent before can't be seen opened, so the numbers count from here
    'CREATE TABLE IF NOT EXISTS public.console_emails_since (since TIMESTAMP NOT NULL)',
    "INSERT INTO public.console_emails_since (since) SELECT (now() AT TIME ZONE 'utc') "
    'WHERE NOT EXISTS (SELECT 1 FROM public.console_emails_since)',
]
URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')
GIF = (b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,'
       b'\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;')

_ready = False


def ensure_tables():
    global _ready
    if not _ready:
        with db.engine.begin() as conn:
            for ddl in DDL:
                conn.execute(text(ddl))
        _ready = True


def _now():
    return datetime.utcnow()


# ── Building the email ───────────────────────────────────────────────────────

def to_html(body, base, token, links):
    """The text as simple HTML: paragraphs, links through the console (base/e/c/token/n), the open image."""
    out = []

    def link(m):
        url = m.group(0).rstrip('.,;:!?')
        tail = m.group(0)[len(url):]
        links.append(url)
        href = f'{base}/e/c/{token}/{len(links) - 1}' if base else url
        return (f'<a href="{html_lib.escape(href)}">{html_lib.escape(url)}</a>{html_lib.escape(tail)}')

    for para in re.split(r'\n\s*\n', body.strip()):
        parts, last = [], 0
        for m in URL_RE.finditer(para):
            parts.append(html_lib.escape(para[last:m.start()]))
            parts.append(link(m))
            last = m.end()
        parts.append(html_lib.escape(para[last:]))
        out.append('<p>' + ''.join(parts).replace('\n', '<br>') + '</p>')
    pixel = f'<img src="{base}/e/o/{token}.gif" width="1" height="1" alt="" style="display:block;border:0">' if base else ''
    return ('<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5;color:#1f2937">'
            + ''.join(out) + pixel + '</div>')


def base_url():
    """The console's address, for the open image and the links: CONSOLE_URL if set, else this request's host on the
    console (not a *.vercel.app address: the daily task may come in on one), else SIGNUP_URL (the website's setting)."""
    import os
    from flask import has_request_context, request
    from .console import console_mode
    url = (os.environ.get('CONSOLE_URL') or '').strip().rstrip('/')
    if url:
        return url
    if has_request_context() and console_mode() and not request.host.endswith('.vercel.app'):
        return request.url_root.rstrip('/')
    return (os.environ.get('SIGNUP_URL') or '').strip().rstrip('/')


def send(to, subject, body, kind='console', slug=None, lead_id=None, bcc=True):
    """Send an email (text + HTML) and keep a row to see if it's opened. True if sent."""
    from . import mailer
    ensure_tables()
    token = secrets.token_urlsafe(18)
    base = base_url()
    links = []
    page = to_html(body, base, token, links)
    ok = mailer.send(to, subject, body, html=page, bcc=mailer.sender() if bcc else None)
    if ok:
        with db.engine.begin() as conn:
            conn.execute(text('INSERT INTO public.console_emails (token, kind, lead_id, slug, to_addr, subject, sent_at, links) '
                              'VALUES (:t, :k, :l, :s, :a, :sub, :at, :links)'),
                         {'t': token, 'k': kind, 'l': lead_id, 's': slug, 'a': to[:200], 'sub': subject[:200],
                          'at': _now(), 'links': json.dumps(links)})
    return ok


# ── The website's set-up email (signed token, row added on first open or click) ─

def open_token(lead_id):
    """'L<id>.<signature>' for the set-up email of this trial request (SIGNUP_SECRET, shared by website and console)."""
    from . import signup
    return f'L{int(lead_id)}.{signup._sign(f"open.{int(lead_id)}")}'


def _lead_of(token):
    import hmac
    from . import signup
    m = re.fullmatch(r'L(\d{1,10})\.([0-9a-f]{32})', token or '')
    if not m or not signup._env('SIGNUP_SECRET'):
        return None
    return int(m.group(1)) if hmac.compare_digest(m.group(2), signup._sign(f'open.{m.group(1)}')) else None


def setup_html(body, lead_id):
    """The website's set-up email as HTML, with the open image (links stay as they are: /start is the console)."""
    from . import signup
    base = signup._env('SIGNUP_URL').rstrip('/')
    if not base or not signup._env('SIGNUP_SECRET'):
        return None
    page = to_html(body, '', '', [])
    pixel = f'<img src="{base}/e/o/{open_token(lead_id)}.gif" width="1" height="1" alt="" style="display:block;border:0">'
    return page[:-len('</div>')] + pixel + '</div>'


def _setup_row(conn, token, lead_id):
    conn.execute(text("INSERT INTO public.console_emails (token, kind, lead_id, subject) VALUES (:t, 'setup', :l, "
                      "'Set up your QuoteRoom app') ON CONFLICT (token) DO NOTHING"), {'t': token, 'l': lead_id})


# ── Opens and clicks (public routes on the console) ──────────────────────────

def record_open(token):
    ensure_tables()
    lead_id = _lead_of(token) if token.startswith('L') else None
    with db.engine.begin() as conn:
        if lead_id:
            _setup_row(conn, token, lead_id)
        conn.execute(text('UPDATE public.console_emails SET opens = opens + 1, opened_at = COALESCE(opened_at, :n) '
                          'WHERE token = :t'), {'t': token, 'n': _now()})


def record_click(token, n):
    """The link's address (only one the email had), or None."""
    ensure_tables()
    with db.engine.begin() as conn:
        row = conn.execute(text('SELECT links FROM public.console_emails WHERE token = :t'), {'t': token}).first()
        if not row:
            return None
        links = json.loads(row[0] or '[]')
        conn.execute(text('UPDATE public.console_emails SET clicks = clicks + 1, clicked_at = COALESCE(clicked_at, :n), '
                          'opened_at = COALESCE(opened_at, :n) WHERE token = :t'), {'t': token, 'n': _now()})
    return links[n] if 0 <= n < len(links) else None


def setup_link_opened(lead_id):
    """The set-up link (/start) was opened: the click on the website's set-up email."""
    ensure_tables()
    token = open_token(lead_id)
    with db.engine.begin() as conn:
        _setup_row(conn, token, lead_id)
        conn.execute(text('UPDATE public.console_emails SET clicks = clicks + 1, clicked_at = COALESCE(clicked_at, :n), '
                          'opened_at = COALESCE(opened_at, :n) WHERE token = :t'), {'t': token, 'n': _now()})


# ── What the console shows ───────────────────────────────────────────────────

def _rows(where, params):
    ensure_tables()
    with db.engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(
            'SELECT id, kind, lead_id, slug, to_addr, subject, sent_at, opened_at, opens, clicked_at, clicks '
            f'FROM public.console_emails WHERE {where} ORDER BY COALESCE(sent_at, opened_at) DESC'), params).mappings()]


def for_trial(slug, lead_id=None):
    """Emails to this trial (and to the request it came from), newest first."""
    if lead_id:
        return _rows('slug = :s OR lead_id = :l', {'s': slug, 'l': lead_id})
    return _rows('slug = :s', {'s': slug})


def for_lead(lead_id):
    return _rows('lead_id = :l', {'l': lead_id})


def by_lead():
    """{lead_id: {'opened_at', 'clicked_at', 'sent': n}} over all emails to trial requests."""
    out = {}
    for r in _rows('lead_id IS NOT NULL', {}):
        o = out.setdefault(r['lead_id'], {'opened_at': None, 'clicked_at': None, 'sent': 0})
        o['sent'] += 1 if r['sent_at'] or r['kind'] == 'setup' else 0
        for k in ('opened_at', 'clicked_at'):
            if r[k] and (o[k] is None or r[k] < o[k]):
                o[k] = r[k]
    return out


def stats(leads=None, days=30):
    """Opened / clicked over the last `days`: the set-up email (out of the requests with an email: the website sends
    it to each) and the emails sent from here (stage + console)."""
    since = _now() - timedelta(days=days)
    ensure_tables()
    with db.engine.connect() as conn:
        started = conn.execute(text('SELECT MIN(since) FROM public.console_emails_since')).scalar()
    lead_since = max(since, started) if started else since
    setup = {'sent': 0, 'opened': 0, 'clicked': 0}
    seen = by_lead()
    for l in leads or []:
        if l.get('email') and l.get('created_at') and l['created_at'] >= lead_since and l.get('business_type') in ('interiors', 'furniture'):
            setup['sent'] += 1
            s = seen.get(l['id'], {})
            setup['opened'] += 1 if s.get('opened_at') else 0
            setup['clicked'] += 1 if s.get('clicked_at') else 0
    sent = _rows("sent_at IS NOT NULL AND sent_at >= :d", {'d': since})
    ours = {'sent': len(sent), 'opened': sum(1 for r in sent if r['opened_at']),
            'clicked': sum(1 for r in sent if r['clicked_at'])}
    return {'setup': setup, 'ours': ours, 'days': days, 'since': lead_since}
