"""Quotation approvals: an employee can make, change and look at a quotation's PDF themselves (marked "Draft – not
approved" on every page), but downloading the clean PDF or sharing it with the customer (the customer's link,
WhatsApp and email) waits for an admin. The employee taps Send for approval
when it's ready; the admin gets a notification (and an email) with Approve, Reject and Make changes on it, and the
same buttons on the quotation. An employee changing it afterwards needs approval again before sharing. Admins' own
quotations don't wait.

Off unless the operator turns it on for the business (console → Features). Stored in app_settings (no database
update):
  quote_approvals        '1': on
  quote_approvals_state  JSON {project_id: {status: unsent/pending/approved/changes/rejected, user_id, at, by, decided, note}}
  notif_kinds            JSON {notification_id: 'quote' | 'rates:<request id>'}: which notifications carry buttons
"""
import json
from datetime import datetime

SWITCH_KEY, STATE_KEY, KINDS_KEY = 'quote_approvals', 'quote_approvals_state', 'notif_kinds'
LABELS = {'unsent': 'Not sent for approval', 'pending': 'Waiting for approval', 'approved': 'Approved', 'changes': 'Changes asked', 'rejected': 'Rejected'}
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
    """Not to be downloaded or shared yet: an employee's quotation not approved (the customer's link holds too)."""
    s = state(getattr(project, 'id', project))
    return bool(s) and s.get('status') != 'approved'


def unsent(project):
    """An employee's quotation never sent for approval (new, or from before approvals were turned on): employees can't
    share it until it's approved (a customer's link already sent from before keeps working)."""
    if not enabled() or project is None or getattr(project, 'status', None) == 'draft' or state(project.id):
        return False
    from . import db
    from .models import User
    maker = db.session.get(User, project.created_by) if project.created_by else None
    return maker is not None and not maker.is_admin


def blocks(project):
    """Downloading and sharing are held for the signed-in user (admins never are)."""
    from flask_login import current_user
    if getattr(current_user, 'is_authenticated', False) and current_user.is_admin:
        return False
    return locked(project) or unsent(project)


def changed(project, user):
    """An employee saved it: it has to be approved (again) before it's shared. Left as it is while it's waiting (the
    admin sees the latest when they open it)."""
    if not enabled() or user is None or user.is_admin or project.status == 'draft':
        return
    rows = _load(STATE_KEY)
    key = str(project.id)
    if (rows.get(key) or {}).get('status') == 'pending':
        return
    if key not in rows and unsent(project):            # theirs and never sent: already counts as not sent
        return
    rows[key] = {'status': 'unsent', 'user_id': user.id, 'at': datetime.utcnow().isoformat(timespec='seconds')}
    _save(STATE_KEY, rows)


def submit(project, user):
    """The employee taps Send for approval: it waits for the admin. The admin is told (notification and email) unless
    it was already waiting. Returns True if it was sent for approval."""
    if not enabled() or user is None or user.is_admin or project.status == 'draft':
        return False
    rows = _load(STATE_KEY)
    key = str(project.id)
    was = (rows.get(key) or {}).get('status')
    rows[key] = {'status': 'pending', 'user_id': user.id, 'at': datetime.utcnow().isoformat(timespec='seconds')}
    _save(STATE_KEY, rows)
    if was != 'pending':
        _tell_admin(project, user, again=was not in (None, 'unsent'))
    return True


def _tell_admin(project, user, again=False):
    from flask import url_for
    from . import db, mailer, rate_access
    from .branding import get_brand
    from .models import Notification
    who = user.full_name or user.username
    n = Notification(title=f'{who} sent a quotation for approval – {project.customer_name}',
                     message=(f'{who} {"changed" if again else "made"} {project.customer_name}\'s quotation (#{project.id}). '
                              'It can be downloaded or shared with the customer once you approve it.'),
                     project_id=project.id)
    db.session.add(n)
    db.session.flush()
    tag(n.id, 'quote')
    try:
        link = url_for('projects.view_project', project_id=project.id, _external=True) + '#quote-approval'
        mailer.send(rate_access.admin_email(), f'Approve {project.customer_name}\'s quotation – {who}',
                    f'Hello,\n\n{who} sent {project.customer_name}\'s quotation (#{project.id}) in {get_brand()["name"]} '
                    f'for your approval. It can\'t be downloaded or shared with the customer until you approve it.\n\n'
                    f'Approve, reject or ask for changes here (sign in as admin):\n{link}\n\nQuoteRoom')
    except Exception:
        pass


def decide(project_id, action, admin, note=''):
    """approve / reject / changes, by an admin, on a waiting quotation. Returns the new state, or None."""
    status = {'approve': 'approved', 'reject': 'rejected', 'changes': 'changes'}.get(action)
    rows = _load(STATE_KEY)
    s = rows.get(str(int(project_id)))
    if s and s.get('status') == 'unsent' and status:       # not sent yet: the admin can approve it as it is
        s['status'] = 'pending'
    if not s and status:                                   # never sent: the admin can approve it as it is
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


DRAFT_MARK = 'DRAFT – NOT APPROVED'


def mark_draft(buf):
    """The PDF with "DRAFT – NOT APPROVED" across every page and a line at the foot: what an employee sees before the
    admin approves it (they can look at it, but it isn't one to send)."""
    import io
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas
    buf.seek(0)
    reader, writer = PdfReader(buf), PdfWriter()
    stamps = {}
    for page in reader.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        if (w, h) not in stamps:
            out = io.BytesIO()
            c = canvas.Canvas(out, pagesize=(w, h))
            c.saveState()
            c.setFillColor(Color(0.85, 0.1, 0.1, alpha=0.16))
            import math
            from reportlab.pdfbase.pdfmetrics import stringWidth
            text, angle = DRAFT_MARK.replace('–', '-'), math.degrees(math.atan2(h, w))
            size = 0.8 * math.hypot(w, h) / (stringWidth(text, 'Helvetica-Bold', 1) + 0.6)   # fits the diagonal
            c.setFont('Helvetica-Bold', size)
            c.translate(w / 2, h / 2)
            c.rotate(angle)
            c.drawCentredString(0, -size / 3, text)
            c.restoreState()
            c.setFillColor(Color(0.75, 0.1, 0.1))
            c.setFont('Helvetica-Bold', 8)
            c.drawCentredString(w / 2, 8, 'Draft for checking only: not approved to send to the customer.')
            c.save()
            out.seek(0)
            stamps[(w, h)] = PdfReader(out).pages[0]
        page.merge_page(stamps[(w, h)])
        writer.add_page(page)
    result = io.BytesIO()
    writer.write(result)
    result.seek(0)
    return result
