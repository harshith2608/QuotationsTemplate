"""The sample quotation some trials got on their first sign-in (8–9 Nov 2026; no longer made): a normal quotation in
their list ("Sample customer"). Until they edit it, it doesn't count as their own: not in the console's trial stages
(app/activity.py) nor the setup guide's "first quotation" (app/setup_guide.py).
"""
from . import db

KEY = 'sample_project_id'
CUSTOMER = 'Sample customer'


def project():
    """The sample quotation, if it's still there."""
    from .models import AppSetting, Project
    pid = AppSetting.get(KEY)
    return db.session.get(Project, int(pid)) if pid and str(pid).isdigit() else None


def untouched_id():
    """The sample's id while they haven't edited it (updated_at still its created_at), else None. Asked once per
    request (the quotations list and the setup guide both ask); the setting comes with the page's settings read.
    Through the models, so a trial's own schema is used (a plain SQL string would look in public)."""
    from flask import g, has_app_context
    from sqlalchemy import select
    from .models import AppSetting, Project
    seen = g.setdefault('_sample_untouched', {}) if has_app_context() else {}
    where = g.get('tenant_slug') if has_app_context() else None          # (the console asks for many trials at once)
    if where in seen:
        return seen[where]
    found = None
    pid = AppSetting.get(KEY)
    if pid and str(pid).isdigit():
        try:
            row = db.session.execute(select(Project.created_at, Project.updated_at).where(Project.id == int(pid))).first()
        except Exception:
            db.session.rollback()                # never leave the request's transaction broken
            row = None
        found = int(pid) if row and row[0] and row[0] == row[1] else None     # (an edit changes updated_at)
    seen[where] = found
    return found
