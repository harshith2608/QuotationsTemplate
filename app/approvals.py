"""Quotation approvals: a quotation an employee makes (or changes) waits for an admin before it can be sent or
downloaded: PDFs, the customer's link, WhatsApp and email. The admin gets a notification (and an email) with Approve,
Reject and Make changes on it, and the same buttons on the quotation. Changing an approved quotation sends it for
approval again. Admins' own quotations don't wait.

Off unless the operator turns it on for the business (console → Features). Stored in app_settings (no database
update):
  quote_approvals        '1': on
  quote_approvals_state  JSON {project_id: {status: pending/approved/changes/rejected, user_id, at, by, decided, note}}
  notif_kinds            JSON {notification_id: 'quote' | 'rates:<request id>'}: which notifications carry buttons
"""
import json
from datetime import datetime

SWITCH_KEY, STATE_KEY, KINDS_KEY = 'quote_approvals', 'quote_approvals_state', 'notif_kinds'
LABELS = {'unsent': 'Not approved yet', 'pending': 'Waiting for approval', 'approved': 'Approved', 'changes': 'Changes asked', 'rejected': 'Rejected'}
BADGES = {'unsent': 'bg-secondary', 'pending': 'bg-warning text-dark', 'approved': 'bg-success', 'changes': 'bg-info text-dark', 'rejected': 'bg-danger'}


def _load(key):
    from .models import AppSetting
    try:
        v = json.loads(AppSetting.get(key, '') or '{}')
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def _save(key, value):
    from .models import AppSetting
    AppSetting.set(key, json.dumps(value))


def enabled():
    from .models import AppSetting
    try:
        return AppSetting.get(SWITCH_KEY, '') == '1'
    except Exception:
        return False


def set_enabled(on):
    from .models import AppSetting
    AppSetting.set(SWITCH_KEY, '1' if on else '')


def state(project_id):
    """This quotation's approval ({status, …}), or None (an admin's, or made before approvals were on)."""
    if not project_id or not enabled():
        return None
    return _load(STATE_KEY).get(str(int(project_id)))


def states():
    """{project_id: status} for the Quotations page (with approvals on)."""
    if not enabled():
        return {}
    return {int(k): v.get('status') for k, v in _load(STATE_KEY).items() if isinstance(v, dict)}


def locked(project):
    """Not to be sent or downloaded yet: an employee's quotation not approved (the customer's link too)."""
    s = state(getattr(project, 'id', project))
    return bool(s) and s.get('status') != 'approved'


def unsent(project):
    """An employee's quotation from before approvals were turned on, never sent for approval: employees can't send or
    download it until it's approved (its customer's link, already sent, keeps working)."""
    if not enabled() or project is None or getattr(project, 'status', None) == 'draft' or state(project.id):
        return False
    from . import db
    from .models import User
    maker = db.session.get(User, project.created_by) if project.created_by else None
    return maker is not None and not maker.is_admin


def blocks(project):
    """For the signed-in user: admins can always open it (to check it before approving)."""
    from flask_login import current_user
    if getattr(current_user, 'is_authenticated', False) and current_user.is_admin:
        return False
    return locked(project) or unsent(project)


def submit(project, user):
    """After an employee saves the quotation (or taps Send for approval): it waits for the admin again. The admin is
    told (notification and email) unless it was already waiting. Returns True if it was sent for approval."""
    if not enabled() or user is None or user.is_admin or project.status == 'draft':
        return False
    rows = _load(STATE_KEY)
    key = str(project.id)
    was = (rows.get(key) or {}).get('status')
    rows[key] = {'status': 'pending', 'user_id': user.id, 'at': datetime.utcnow().isoformat(timespec='seconds')}
    _save(STATE_KEY, rows)
    if was != 'pending':
        _tell_admin(project, user, again=bool(was))
    return True


def _tell_admin(project, user, again=False):
    from flask import url_for
    from . import db, mailer, rate_access
    from .branding import get_brand
    from .models import Notification
    who = user.full_name or user.username
    n = Notification(title=f'{who} sent a quotation for approval – {project.customer_name}',
                     message=(f'{who} {"changed" if again else "made"} {project.customer_name}\'s quotation (#{project.id}). '
                              'It can be sent or downloaded once you approve it.'),
                     project_id=project.id)
    db.session.add(n)
    db.session.flush()
    tag(n.id, 'quote')
    try:
        link = url_for('projects.view_project', project_id=project.id, _external=True) + '#quote-approval'
        mailer.send(rate_access.admin_email(), f'Approve {project.customer_name}\'s quotation – {who}',
                    f'Hello,\n\n{who} sent {project.customer_name}\'s quotation (#{project.id}) in {get_brand()["name"]} '
                    f'for your approval. It can\'t be sent or downloaded until you approve it.\n\n'
                    f'Approve, reject or ask for changes here (sign in as admin):\n{link}\n\nQuoteRoom')
    except Exception:
        pass


def decide(project_id, action, admin, note=''):
    """approve / reject / changes, by an admin, on a waiting quotation. Returns the new state, or None."""
    status = {'approve': 'approved', 'reject': 'rejected', 'changes': 'changes'}.get(action)
    rows = _load(STATE_KEY)
    s = rows.get(str(int(project_id)))
    if not s and status:                                   # from before approvals: the admin can approve it as it is
        from . import db
        from .models import Project
        project = db.session.get(Project, int(project_id))
        if project is not None and unsent(project):
            s = rows[str(project.id)] = {'status': 'pending', 'user_id': project.created_by,
                                         'at': datetime.utcnow().isoformat(timespec='seconds')}
    if not status or not s or s.get('status') != 'pending':
        return None
    s.update(status=status, by=admin.id, decided=datetime.utcnow().isoformat(timespec='seconds'),
             note=' '.join((note or '').split())[:500])
    _save(STATE_KEY, rows)
    return s


def tag(notification_id, kind):
    kinds = _load(KINDS_KEY)
    kinds[str(int(notification_id))] = kind
    if len(kinds) > 400:                                  # the latest ones
        kinds = dict(sorted(kinds.items(), key=lambda kv: int(kv[0]))[-400:])
    _save(KINDS_KEY, kinds)


def actions(notifications):
    """{notification_id: {...}} for the Notifications page: the buttons (or the outcome) on each request."""
    from . import rate_access
    kinds = _load(KINDS_KEY)
    rate_reqs = {r.get('id'): r for r in rate_access.requests()}
    quotes = _load(STATE_KEY)
    out = {}
    for n in notifications:
        kind = kinds.get(str(n.id))
        if kind == 'quote' and n.project_id:
            s = quotes.get(str(n.project_id))
            if s:
                out[n.id] = {'kind': 'quote', 'status': s.get('status'), 'note': s.get('note', '')}
        elif kind and kind.startswith('rates:'):
            r = rate_reqs.get(int(kind.split(':', 1)[1] or 0))
            if r:
                out[n.id] = {'kind': 'rates', 'id': r['id'], 'status': r.get('status')}
    return out


def console_status():
    return enabled()
