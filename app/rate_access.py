"""Rates and line amounts for employees (the business admin decides, on the Users page).

An employee (any user who isn't an admin) doesn't see rates or line amounts unless their admin ticked "Can see rates"
for them. They still see sizes, quantities, areas and totals, and can make and send quotations: the PDF, link and
WhatsApp they send leave rates and line amounts out. When a customer asks for them, the employee taps "Ask admin for
rates" on the quotation: the admin gets an email (from QuoteRoom, hello@quote-room.co.in) and a notification (Approve / Decline on it), opens
the request and approves it; that employee then sees that one quotation's rates and line amounts (screen, PDF, link,
WhatsApp). Kept in app_settings (no database update):
  user_rates         JSON {user_id: true}: employees allowed to see rates everywhere
  rate_grants        JSON {project_id: [user_id, …]}: approved for one quotation
  rate_requests      JSON [{id, project_id, user_id, at, status: pending/approved/declined, by}]
On screen it hides them (an employee who can see the total could still work a rate out by changing a size).
"""
import json
from datetime import datetime

USERS_KEY, GRANTS_KEY, REQUESTS_KEY = 'user_rates', 'rate_grants', 'rate_requests'


def _load(key, empty):
    from .models import AppSetting
    try:
        v = json.loads(AppSetting.get(key, '') or 'null')
    except ValueError:
        v = None
    return v if isinstance(v, type(empty)) else empty


def _save(key, value):
    from .models import AppSetting
    AppSetting.set(key, json.dumps(value))


def allowed_everywhere(user):
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    return user.is_admin or bool(_load(USERS_KEY, {}).get(str(user.id)))


def set_allowed(user_id, on):
    users = _load(USERS_KEY, {})
    if on:
        users[str(int(user_id))] = True
    else:
        users.pop(str(int(user_id)), None)
    _save(USERS_KEY, users)


def can_see(user, project_id=None):
    """Rates and line amounts for this user (on this quotation, when given)."""
    if allowed_everywhere(user):
        return True
    if project_id and user is not None and getattr(user, 'is_authenticated', False):
        return user.id in (_load(GRANTS_KEY, {}).get(str(int(project_id))) or [])
    return False


def current_can_see(project_id=None):
    """For the signed-in user of this request (outside a request, e.g. the customer's link: True)."""
    from flask import has_request_context
    if not has_request_context():
        return True
    from flask_login import current_user
    if not getattr(current_user, 'is_authenticated', False):
        return True                       # the customer on the link: what the quotation shows
    return can_see(current_user, project_id)


# ── Requests: an employee asks, the admin approves for that one quotation ──

def requests(status=None):
    rows = _load(REQUESTS_KEY, [])
    return [r for r in rows if status is None or r.get('status') == status]


def pending_for(project_id, user_id):
    return next((r for r in requests('pending') if r['project_id'] == int(project_id) and r['user_id'] == int(user_id)), None)


def ask(project, user):
    """A request from this employee for this quotation (one pending at a time). Returns it."""
    found = pending_for(project.id, user.id)
    if found:
        return found
    rows = _load(REQUESTS_KEY, [])
    req = {'id': max([r.get('id', 0) for r in rows] + [0]) + 1, 'project_id': project.id, 'user_id': user.id,
           'at': datetime.utcnow().isoformat(timespec='seconds'), 'status': 'pending'}
    rows.append(req)
    _save(REQUESTS_KEY, rows[-200:])
    return req


def decide(req_id, approve, admin):
    rows = _load(REQUESTS_KEY, [])
    req = next((r for r in rows if r.get('id') == int(req_id)), None)
    if not req or req.get('status') != 'pending':
        return None
    req.update(status='approved' if approve else 'declined', by=admin.id, decided=datetime.utcnow().isoformat(timespec='seconds'))
    _save(REQUESTS_KEY, rows)
    if approve:
        grants = _load(GRANTS_KEY, {})
        users = set(grants.get(str(req['project_id'])) or [])
        users.add(req['user_id'])
        grants[str(req['project_id'])] = sorted(users)
        _save(GRANTS_KEY, grants)
    return req


SCREEN_KEY = 'hide_rates_on_screen'


def hidden_on_screen():
    """Settings → Pricing: rates (per sqft, per No., per rft…) hidden on screen while making a quotation, for everyone
    (admins too: e.g. quoting in front of the customer). Only the rates: line amounts and totals stay; the PDF, link
    and WhatsApp are as before. A Show rates button on the page shows them until it's left."""
    from .models import AppSetting
    try:
        return AppSetting.get(SCREEN_KEY, '') == '1'
    except Exception:
        return False


def admin_email():
    """Where requests go: the admin email in Settings (else the company email)."""
    from .models import AppSetting
    return (AppSetting.get('admin_email', '') or AppSetting.get('company_email', '') or '').strip()


def mark_request():
    """before_request: g.no_rates for an employee who can't see this page's rates (its quotation, if it is one)."""
    from flask import g, request
    from flask_login import current_user
    if not getattr(current_user, 'is_authenticated', False) or current_user.is_admin:
        return
    pid = (request.view_args or {}).get('project_id')
    try:
        g.no_rates = not can_see(current_user, pid)
    except Exception:
        g.no_rates = False
