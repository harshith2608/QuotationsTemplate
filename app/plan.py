"""
Subscription plan and expiry.

Each deployment (or trial) stores its plan in app_settings, set by the operator
with `flask plan ...` — never editable from the web UI. A deployment with no end
date has no limits (marketing site, demo, legacy setups).

Timeline after the end date:
  paid plans : 7-day grace (full access) → read-only → data deleted 30 days after the end date
  trial      : read-only immediately     → data deleted 30 days after the end date
Before the end date, admins see a reminder (trials: throughout; paid: last 15 days).
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from flask import g, has_app_context

PLAN_KEY, STARTED_KEY, ENDS_KEY = 'plan_name', 'plan_started_on', 'plan_ends_on'

PLANS = {
    'trial':  'Free trial',
    '6m':     '6-month plan',
    '1y':     '12-month plan',
    'custom': 'Plan',
}
DEFAULT_LENGTH = {'trial': '7d', '6m': '6m', '1y': '1y'}

REMIND_DAYS = 15        # paid plans: reminder banner this many days before the end
GRACE_DAYS = 7          # paid plans: full access this many days after the end
DELETE_AFTER_DAYS = 30  # data deleted this many days after the end date

IST = timedelta(hours=5, minutes=30)   # India has no DST


def today():
    """Today's date in India (the server runs on UTC)."""
    return (datetime.utcnow() + IST).date()


def parse_length(text):
    """'7d' / '6m' / '1y' / '2w' → (n, unit). Raises ValueError."""
    m = re.fullmatch(r'\s*(\d+)\s*([dwmy])\s*', (text or '').lower())
    if not m:
        raise ValueError(f'Use a length like 7d, 2w, 6m or 1y (got "{text}").')
    return int(m.group(1)), m.group(2)


def add_length(start, text):
    n, unit = parse_length(text)
    if unit == 'd':
        return start + timedelta(days=n)
    if unit == 'w':
        return start + timedelta(weeks=n)
    months = n if unit == 'm' else n * 12
    y, m = divmod(start.month - 1 + months, 12)
    year, month = start.year + y, m + 1
    # clamp the day (e.g. 31 Aug + 6m → 28/29 Feb)
    for day in (start.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue


@dataclass
class PlanStatus:
    plan: Optional[str] = None
    started_on: Optional[date] = None
    ends_on: Optional[date] = None
    today: Optional[date] = None

    @property
    def has_limit(self):
        return self.ends_on is not None

    @property
    def is_trial(self):
        return self.plan == 'trial'

    @property
    def label(self):
        return PLANS.get(self.plan or 'custom', 'Plan')

    @property
    def grace_until(self):
        if not self.has_limit:
            return None
        return self.ends_on if self.is_trial else self.ends_on + timedelta(days=GRACE_DAYS)

    @property
    def delete_on(self):
        return self.ends_on + timedelta(days=DELETE_AFTER_DAYS) if self.has_limit else None

    @property
    def days_left(self):
        """Days until the end date (0 on the last day, negative after)."""
        return (self.ends_on - self.today).days if self.has_limit else None

    @property
    def state(self):
        """none | active | reminder | grace | read_only"""
        if not self.has_limit:
            return 'none'
        if self.today <= self.ends_on:
            if self.is_trial or self.days_left < REMIND_DAYS:
                return 'reminder'
            return 'active'
        if self.today <= self.grace_until:
            return 'grace'
        return 'read_only'

    @property
    def read_only(self):
        return self.state == 'read_only'


def _parse_date(value):
    try:
        return date.fromisoformat((value or '').strip())
    except ValueError:
        return None


def load_status(on=None):
    """Read the plan from app_settings (cached per request)."""
    if on is None and 'plan_status' in g:
        return g.plan_status
    from .models import AppSetting
    try:
        rows = AppSetting.get_many([PLAN_KEY, STARTED_KEY, ENDS_KEY])
    except Exception:
        rows = {}
    status = PlanStatus(plan=(rows.get(PLAN_KEY) or None), started_on=_parse_date(rows.get(STARTED_KEY)),
                        ends_on=_parse_date(rows.get(ENDS_KEY)), today=on or today())
    if on is None:
        g.plan_status = status
    return status


def save_plan(plan, started_on, ends_on):
    from .models import AppSetting
    AppSetting.set(PLAN_KEY, plan or '')
    AppSetting.set(STARTED_KEY, started_on.isoformat() if started_on else '')
    AppSetting.set(ENDS_KEY, ends_on.isoformat() if ends_on else '')


def renew(length, plan_name=None):
    """Add 6m / 1y / 7d… to this deployment's plan. On time (within grace) it extends from the end date,
    so no days are lost; late or with no plan it starts from today. 6m / 1y renewals become that plan
    (this is also how a trial becomes paid); other lengths keep the current plan. Returns the new status.
    Caller commits."""
    parse_length(length)                     # raises ValueError for bad input
    status = load_status(on=today())
    start = today()
    base = status.ends_on if status.has_limit and start <= status.grace_until else start
    key = length.strip().lower()
    new_plan = plan_name or {'6m': '6m', '1y': '1y', '12m': '1y'}.get(key) or status.plan or 'custom'
    save_plan(new_plan, base, add_length(base, length))
    if has_app_context():
        g.pop('plan_status', None)
    return load_status(on=start)


def renew_message_url(status, user=None, host_url=''):
    """WhatsApp link to the operator, pre-filled with this customer's details."""
    from urllib.parse import quote
    from .branding import support_contact, get_brand
    _, base = support_contact()
    if not base:
        return ''
    brand = get_brand()
    fmt = lambda d: d.strftime('%d %b %Y') if d else '—'
    lines = [
        "Hi! I'd like to " + ('subscribe after my free trial.' if status.is_trial else 'renew my plan.'),
        '',
        f'Company: {brand["name"]}',
        f'Phone: {brand["phone"] or "—"}',
        f'App: {host_url or "—"}',
        f'Current: {status.label}, ends {fmt(status.ends_on)}',
    ]
    if user is not None and getattr(user, 'is_authenticated', False):
        who = user.username if user.display_name == user.username else f'{user.display_name} ({user.username})'
        lines.append(f'Requested by: {who}')
    lines += ['', 'Plan I want: 6 months / 12 months']
    return f'{base}?text={quote(chr(10).join(lines))}'


# ── Read-only enforcement ─────────────────────────────────────────────────────

# Still allowed when read-only: signing in/out, and Razorpay recording payments
# from the business's own customers.
ALWAYS_ALLOWED = {'auth.login', 'auth.logout', 'projects.razorpay_webhook', 'static',
                  'main.favicon', 'main.brand_logo',
                  'share.view', 'share.pdf', 'share.respond'}   # the business's customers answering a quotation
# Pages that only exist to edit — redirect away from them when read-only
EDIT_PAGES = {'projects.create_project', 'projects.edit_project'}

READ_ONLY_MESSAGE = 'Your plan has ended, so this app is read-only. Renew to create or edit quotations.'


def enforce_read_only():
    """before_request hook: block changes once the plan is past its grace period."""
    from flask import flash, jsonify, redirect, request, url_for
    if request.endpoint in ALWAYS_ALLOWED or request.endpoint is None:
        return None
    status = load_status()
    if not status.read_only:
        return None
    if request.method in ('GET', 'HEAD', 'OPTIONS') and request.endpoint not in EDIT_PAGES:
        return None
    if request.is_json or request.accept_mimetypes.best == 'application/json' or request.path.startswith('/api/'):
        return jsonify({'error': READ_ONLY_MESSAGE}), 403
    flash(READ_ONLY_MESSAGE, 'warning')
    back = request.referrer if request.method == 'POST' and request.referrer else None
    return redirect(back or url_for('projects.list_projects'))
