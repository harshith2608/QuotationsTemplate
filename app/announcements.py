"""Announcements: a message you type in the console (Announcements), shown as a banner at the top of the apps in
the shared app, to trials, paying customers or both, to everyone there or only their admins.

Kept in public.console_announcements in the trials database (the console's), read by the shared app every TTL
seconds. A business on its own deployment (its own Vercel project) doesn't see them.
"""
import time
from datetime import date

from sqlalchemy import text

from . import db

AUDIENCES = {'both': 'Trials and customers', 'trials': 'Trials only', 'customers': 'Paying customers only'}
LEVELS = {'info': 'Information (blue)', 'success': 'Good news (green)', 'warning': 'Important (yellow)'}
MAX_LEN = 500
TTL = 30

DDL = """CREATE TABLE IF NOT EXISTS public.console_announcements (
    id          SERIAL PRIMARY KEY,
    message     TEXT NOT NULL,
    audience    VARCHAR(12) NOT NULL DEFAULT 'both',
    level       VARCHAR(10) NOT NULL DEFAULT 'info',
    admins_only BOOLEAN NOT NULL DEFAULT TRUE,
    ends_on     DATE,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'))"""

_cache = {'at': 0.0, 'rows': []}
_ready = False


def ensure_table():
    global _ready
    if not _ready:
        with db.engine.begin() as conn:
            conn.execute(text(DDL))
        _ready = True


def all_rows():
    """Every announcement, newest first (the console's list)."""
    ensure_table()
    with db.engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(
            'SELECT * FROM public.console_announcements ORDER BY id DESC')).mappings()]


def add(message, audience='both', level='info', admins_only=True, ends_on=None):
    ensure_table()
    with db.engine.begin() as conn:
        new_id = conn.execute(text(
            'INSERT INTO public.console_announcements (message, audience, level, admins_only, ends_on) '
            'VALUES (:m, :a, :l, :o, :e) RETURNING id'),
            {'m': message, 'a': audience, 'l': level, 'o': bool(admins_only), 'e': ends_on}).scalar()
    forget()
    return new_id


def set_active(ann_id, on):
    ensure_table()
    with db.engine.begin() as conn:
        conn.execute(text('UPDATE public.console_announcements SET active = :o WHERE id = :i'), {'o': bool(on), 'i': ann_id})
    forget()


def delete(ann_id):
    ensure_table()
    with db.engine.begin() as conn:
        conn.execute(text('DELETE FROM public.console_announcements WHERE id = :i'), {'i': ann_id})
    forget()


def forget():
    _cache['at'] = 0.0


def validate(form):
    """(values, errors) from the console's form."""
    message = ' '.join((form.get('message') or '').split())[:MAX_LEN]
    audience = form.get('audience') if form.get('audience') in AUDIENCES else 'both'
    level = form.get('level') if form.get('level') in LEVELS else 'info'
    ends_on, errors = None, []
    if len(message) < 3:
        errors.append('Type the announcement.')
    if (form.get('ends_on') or '').strip():
        try:
            ends_on = date.fromisoformat(form['ends_on'].strip())
        except ValueError:
            errors.append('The end date should look like 2026-12-31.')
    return {'message': message, 'audience': audience, 'level': level,
            'admins_only': bool(form.get('admins_only')), 'ends_on': ends_on}, errors


def showing(rows, is_trial, is_admin, today=None):
    """The announcements this person sees: on, not past their end date, for their kind of business and role."""
    today = today or date.today()
    kind = 'trials' if is_trial else 'customers'
    return [r for r in rows if r['active'] and (r['ends_on'] is None or r['ends_on'] >= today)
            and r['audience'] in ('both', kind) and (is_admin or not r['admins_only'])]


def current():
    """The announcements that are on (cached for TTL seconds); [] if the table can't be read."""
    if time.time() - _cache['at'] < TTL:
        return _cache['rows']
    try:
        with db.engine.connect() as conn:
            if conn.execute(text("SELECT to_regclass('public.console_announcements')")).scalar() is None:
                rows = []
            else:
                rows = [dict(r) for r in conn.execute(text(
                    'SELECT id, message, audience, level, admins_only, ends_on, active FROM '
                    'public.console_announcements WHERE active ORDER BY id DESC')).mappings()]
    except Exception:
        rows = []
    _cache.update(at=time.time(), rows=rows)
    return rows


def for_user(status, user):
    """What the signed-in person sees in the shared app (trials and customers with a plan), else []."""
    from . import plan, tenancy
    if not (tenancy.tenant_mode() and user.is_authenticated and status.has_limit):
        return []
    return showing(current(), status.is_trial, user.is_admin, today=plan.today())     # (India's date)
