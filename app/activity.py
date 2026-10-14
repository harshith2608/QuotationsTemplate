"""When a business last used its app, for the operator console. Kept in app_settings (no schema change),
written at most once a day per business and process. Not recorded in the public demo."""
from datetime import datetime

from flask import request
from flask_login import current_user

LAST_ACTIVE_KEY = 'last_active_at'     # ISO UTC: last signed-in request (to the day)
LAST_LOGIN_KEY = 'last_login_at'       # ISO UTC: last password sign-in

_recorded = {}                         # schema → date already written by this process


def _skip():
    from .demo import demo_enabled
    return demo_enabled()


def _write(keys):
    from . import db, tenancy
    from .models import AppSetting
    now = datetime.utcnow().replace(microsecond=0).isoformat()
    try:
        for key in keys:
            AppSetting.set(key, now)
        db.session.commit()
    except Exception:                  # never get in the way of the request itself
        db.session.rollback()
        return False
    _recorded[tenancy.current_schema() or ''] = datetime.utcnow().date()
    return True


def record_login():
    if not _skip():
        _write([LAST_LOGIN_KEY, LAST_ACTIVE_KEY])


def touch():
    """before_request hook: note that a signed-in user is using the app today."""
    from . import tenancy
    if request.endpoint in (None, 'static') or request.path.startswith('/static/'):
        return
    if _recorded.get(tenancy.current_schema() or '') == datetime.utcnow().date():
        return
    if not current_user.is_authenticated or _skip():
        return
    _write([LAST_ACTIVE_KEY])


def usage():
    """Usage summary of the current business's database (call inside its app/tenant context)."""
    from sqlalchemy import func, select
    from . import db
    from .branding import FIELDS, LOGO_DATA_KEY
    from .models import AppSetting, Payment, Project, User

    def when(value):
        try:
            return datetime.fromisoformat(value) if value else None
        except ValueError:
            return None
    s = AppSetting.get_many([LAST_ACTIVE_KEY, LAST_LOGIN_KEY, FIELDS['name'][0]])
    last_quote = db.session.scalar(select(func.max(Project.updated_at)))
    out = dict(
        quotations=db.session.scalar(select(func.count(Project.id))) or 0,
        last_quotation_at=last_quote,
        users=db.session.scalar(select(func.count(User.id))) or 0,
        payments=db.session.scalar(select(func.count(Payment.id))) or 0,
        company_set=bool((s[FIELDS['name'][0]] or '').strip()),
        logo_set=db.session.scalar(select(func.count()).select_from(AppSetting).where(
            AppSetting.key == LOGO_DATA_KEY, AppSetting.value != '')) > 0,
        last_login_at=when(s[LAST_LOGIN_KEY]),
        last_active_at=when(s[LAST_ACTIVE_KEY]),
    )
    seen = [d for d in (out['last_active_at'], out['last_login_at'], last_quote) if d]
    out['last_seen_at'] = max(seen) if seen else None
    out['used'] = bool(out['quotations'] or out['company_set'] or out['logo_set'] or out['last_login_at'])
    return out
