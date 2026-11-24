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
    from . import welcome
    s = AppSetting.get_many([LAST_ACTIVE_KEY, LAST_LOGIN_KEY, FIELDS['name'][0], 'company_name_prefilled', 'company_mobile',
                             welcome.KEY])
    from . import sample_quote
    sample = sample_quote.untouched_id()                         # the first-sign-in sample, until they edit it
    own = (lambda q: q.where(Project.id != sample)) if sample else (lambda q: q)
    last_quote = db.session.scalar(own(select(func.max(Project.updated_at))))
    out = dict(
        quotations=db.session.scalar(own(select(func.count(Project.id)))) or 0,
        last_quotation_at=last_quote,
        users=db.session.scalar(select(func.count(User.id))) or 0,
        payments=db.session.scalar(select(func.count(Payment.id))) or 0,
        # the customer's own name: one filled in from their trial request (ops.create_trial) doesn't count
        company_set=bool((s[FIELDS['name'][0]] or '').strip()) and s[FIELDS['name'][0]] != s['company_name_prefilled'],
        company_prefilled=bool((s['company_name_prefilled'] or '').strip()) and s[FIELDS['name'][0]] == s['company_name_prefilled'],
        logo_set=db.session.scalar(select(func.count()).select_from(AppSetting).where(
            AppSetting.key == LOGO_DATA_KEY, AppSetting.value != '')) > 0,
        last_login_at=when(s[LAST_LOGIN_KEY]),
        last_active_at=when(s[LAST_ACTIVE_KEY]),
        company_name=(s[FIELDS['name'][0]] or '').strip(),        # for the console's search
        phone=''.join(ch for ch in (s['company_mobile'] or '') if ch.isdigit()),
        setup_tour=welcome.console_text(s[welcome.KEY]),          # where they are in the guided first setup
    )
    seen = [d for d in (out['last_active_at'], out['last_login_at'], last_quote) if d]
    out['last_seen_at'] = max(seen) if seen else None
    out['used'] = bool(out['quotations'] or out['company_set'] or out['logo_set'] or out['last_login_at'])
    return out


# Tables counted on the console's Usage page: (key, model name in app.models). Missing in an older database: None.
COUNTED = (('invoices', 'Invoice'), ('payments', 'Payment'), ('links', 'QuoteShare'), ('responses', 'QuoteResponse'),
           ('revisions', 'QuoteRevision'), ('photos', 'ItemImage'), ('saved_lines', 'BoqItem'),
           ('fittings', 'PriceListItem'), ('materials', 'Material'), ('material_lists', 'MaterialList'))
WON_STAGES = ('confirmed', 'ongoing', 'completed')


def details():
    """Everything the console's Usage page shows for the current business (inside its app/tenant context):
    usage() plus users by role, quotations (all time, last 7 and 30 days, drafts, confirmed or further), templates and
    the counts in COUNTED. Through the models, so a trial's own schema is used."""
    from datetime import timedelta
    from sqlalchemy import func, inspect, select
    from . import db, models, quote_templates, sample_quote, tenancy
    from .models import Project, User
    out = usage()
    sample = sample_quote.untouched_id()
    own = (lambda q: q.where(Project.id != sample)) if sample else (lambda q: q)
    count = lambda q: db.session.scalar(q) or 0
    now = datetime.utcnow()
    done = Project.status == 'complete'
    out.update(
        admins=count(select(func.count(User.id)).where(User.role == 'admin')),
        quotations=count(own(select(func.count(Project.id)).where(done))),
        drafts=count(own(select(func.count(Project.id)).where(Project.status == 'draft'))),
        quotes_7d=count(own(select(func.count(Project.id)).where(done, Project.created_at >= now - timedelta(days=7)))),
        quotes_30d=count(own(select(func.count(Project.id)).where(done, Project.created_at >= now - timedelta(days=30)))),
        won=count(own(select(func.count(Project.id)).where(done, Project.stage.in_(WON_STAGES)))),
        templates=len(quote_templates._load()),
    )
    out['staff'] = max(out['users'] - out['admins'], 0)
    try:
        tables = set(inspect(db.session.connection()).get_table_names(schema=tenancy.current_schema()))
    except Exception:
        tables = None
    for key, name in COUNTED:
        model = getattr(models, name)
        if tables is not None and model.__tablename__ not in tables:
            out[key] = None
            continue
        out[key] = count(select(func.count()).select_from(model))
    return out
