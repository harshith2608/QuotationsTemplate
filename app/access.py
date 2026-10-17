"""Who may see and edit a quotation.

Admins: everything. The person who made a quotation: view and edit. Other staff: what an admin gives them in the
Access pop-up on the quotations list: nothing, view, or view and edit. Deleting a quotation is always admin-only.
"""
from flask import g, has_app_context

from . import db

_ready_forever = {}


def edit_ready():
    """False until the database update that adds project_access.can_edit has run (checked once per request)."""
    from . import tenancy
    schema = tenancy.current_schema()
    if _ready_forever.get(schema):
        return True
    if has_app_context() and '_access_edit_ready' in g:
        return g._access_edit_ready
    from sqlalchemy import inspect
    try:
        ready = 'can_edit' in {c['name'] for c in inspect(db.session.connection()).get_columns('project_access', schema=schema)}
    except Exception:
        ready = False
    if ready:
        _ready_forever[schema] = True
    if has_app_context():
        g._access_edit_ready = ready
    return ready


def _grant(project, user):
    from .models import ProjectAccess
    q = ProjectAccess.query.filter_by(project_id=project.id, user_id=user.id)
    if edit_ready():
        from sqlalchemy.orm import undefer
        q = q.options(undefer(ProjectAccess.can_edit))
    return q.first()


def can_view(project, user):
    if user.is_admin or project.created_by == user.id:
        return True
    return _grant(project, user) is not None


def can_edit(project, user):
    if user.is_admin or project.created_by == user.id:
        return True
    grant = _grant(project, user) if edit_ready() else None
    return bool(grant and grant.can_edit)


def edit_ids(user, project_ids):
    """Of these quotations, the ones `user` may edit (for the list's Edit buttons: one query)."""
    from .models import Project, ProjectAccess
    if user.is_admin:
        return set(project_ids)
    own = {pid for (pid,) in db.session.query(Project.id).filter(Project.id.in_(project_ids), Project.created_by == user.id)}
    if not edit_ready():
        return own
    shared = {pid for (pid,) in db.session.query(ProjectAccess.project_id).filter(
        ProjectAccess.project_id.in_(project_ids), ProjectAccess.user_id == user.id, ProjectAccess.can_edit.is_(True))}
    return own | shared
