"""BOMs: a home's room-wise measurements (Foyer 5 × 4.5 = 22.5 sqft, Living room 6 × 5 = 30…, total), taken before
quoting and saved on their own (BOMs page, New BOM), with the customer's name, mobile and optionally email and address.
A quotation is made from a BOM (Create quotation): its customer, and a room for each area ticked; one BOM can give
several quotations (a basic and a premium one). Never printed or shown to the customer.

Turned on per business in Settings → Pricing (KEY, off by default; the same switch the earlier Room areas table used).
Staff use BOMs too unless the admin turns that off (STAFF_OFF_KEY). The table is the Bom model (needs the database
update that adds it: ready()). A quotation made from a BOM is linked in app_settings (LINK_PREFIX + quotation id →
BOM id), shown on the BOM and, for reference, on the quotation form. Rows of the earlier Room areas table
(LEGACY_PREFIX + quotation id) still show there, read-only.
"""
import json
from datetime import datetime

from flask import g, has_app_context

from . import db

KEY = 'room_areas_on'
STAFF_OFF_KEY = 'boms_staff_off'
LINK_PREFIX = 'bom_link:'
LEGACY_PREFIX = 'room_areas:'
MAX_AREAS = 100
NAME_MAX = 60
SIZE_MAX = 100000.0          # feet; anything bigger is a typing mistake

_ready_forever = {}


def enabled():
    from .models import AppSetting
    return AppSetting.get(KEY) == '1'


def staff_allowed():
    from .models import AppSetting
    return AppSetting.get(STAFF_OFF_KEY) != '1'


def ready():
    """False until the database update that adds the boms table has run (checked once per request)."""
    from . import tenancy
    schema = tenancy.current_schema()
    if _ready_forever.get(schema):
        return True
    if has_app_context() and '_boms_ready' in g:
        return g._boms_ready
    from sqlalchemy import inspect
    try:
        found = inspect(db.session.connection()).has_table('boms', schema=schema)
    except Exception:
        found = False
    if found:
        _ready_forever[schema] = True
    if has_app_context():
        g._boms_ready = found
    return found


def can_use(user):
    """BOMs page, New BOM and Create quotation: switched on, and an admin or (unless turned off) staff."""
    if not getattr(user, 'is_authenticated', False) or not enabled():
        return False
    return bool(user.is_admin or staff_allowed())


# ── Areas ────────────────────────────────────────────────────────────────────

def _size(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v != v or v <= 0 or v > SIZE_MAX:       # NaN, negative, absurd
        return 0.0
    return round(v, 6)


def clean_areas(raw):
    """The areas from the form (a JSON string or a list): named or sized rows only, at most MAX_AREAS."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or '[]')
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    rows = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        name = ' '.join(str(r.get('name') or '').split())[:NAME_MAX]
        length, width = _size(r.get('length')), _size(r.get('width'))
        if not name and not (length or width):
            continue
        rows.append({'name': name, 'length': length, 'width': width})
        if len(rows) >= MAX_AREAS:
            break
    return rows


def area(row):
    return round(row['length'] * row['width'], 4)


def total(rows):
    return round(sum(area(r) for r in rows), 4)


def areas_of(bom):
    return clean_areas(bom.areas or '[]')


# ── BOMs ─────────────────────────────────────────────────────────────────────

def get(bom_id):
    from .models import Bom
    try:
        return db.session.get(Bom, int(bom_id)) if ready() else None
    except (TypeError, ValueError):
        return None


def all_boms():
    from .models import Bom
    return Bom.query.order_by(Bom.updated_at.desc(), Bom.id.desc()).all() if ready() else []


def save(bom, form, user):
    """Fill `bom` (new or existing) from the form. Returns a list of problems (nothing saved when there are any)."""
    name = ' '.join((form.get('customer_name') or '').split())[:100]
    mobile = (form.get('mobile') or '').strip()[:15]
    email = (form.get('email') or '').strip()[:100]
    address = (form.get('address') or '').strip()[:300]
    errors = []
    if not name:
        errors.append('Customer name is required.')
    if not mobile:
        errors.append('Mobile number is required.')
    if errors:
        return errors
    from .models import Bom
    bom.customer_name, bom.mobile = name, mobile
    bom.email, bom.address = email or None, address or None
    bom.areas = json.dumps(clean_areas(form.get('areas')), separators=(',', ':'))
    bom.updated_at = datetime.utcnow()
    if bom.id is None:
        bom.created_by = user.id
        bom.created_at = bom.updated_at
        db.session.add(bom)
    return []


def delete(bom):
    """Removes the BOM and its links; quotations made from it stay as they are."""
    from .models import AppSetting
    for row in _link_rows(bom.id):
        db.session.delete(row)
    db.session.delete(bom)


# ── Quotations made from a BOM ───────────────────────────────────────────────

def _link_rows(bom_id):
    from .models import AppSetting
    return AppSetting.query.filter(AppSetting.key.like(LINK_PREFIX + '%'), AppSetting.value == str(int(bom_id))).all()


def link(project_id, bom_id):
    from .models import AppSetting
    AppSetting.set(f'{LINK_PREFIX}{int(project_id)}', str(int(bom_id)))


def linked_bom(project_id):
    """The BOM a quotation was made from (None: none, or deleted since)."""
    from .models import AppSetting
    if not project_id or not ready():
        return None
    value = AppSetting.get(f'{LINK_PREFIX}{int(project_id)}')
    return get(value) if value and value.isdigit() else None


def quotations_for(bom_id):
    """The quotations made from this BOM (saved ones and half-filled drafts), newest first."""
    from .models import Project
    ids = [int(r.key[len(LINK_PREFIX):]) for r in _link_rows(bom_id) if r.key[len(LINK_PREFIX):].isdigit()]
    if not ids:
        return []
    return Project.query.filter(Project.id.in_(ids)).order_by(Project.created_at.desc()).all()


def quotation_counts():
    """{bom id: number of quotations made from it} (for the BOMs list; one query)."""
    from .models import AppSetting, Project
    rows = AppSetting.query.filter(AppSetting.key.like(LINK_PREFIX + '%')).all()
    by_project = {int(r.key[len(LINK_PREFIX):]): int(r.value) for r in rows
                  if r.key[len(LINK_PREFIX):].isdigit() and (r.value or '').isdigit()}
    if not by_project:
        return {}
    alive = {p for (p,) in db.session.query(Project.id).filter(Project.id.in_(list(by_project)))}
    out = {}
    for pid, bid in by_project.items():
        if pid in alive:
            out[bid] = out.get(bid, 0) + 1
    return out


def forget_project(project_id):
    """A quotation is deleted: its link and any earlier Room areas rows go with it."""
    from .models import AppSetting
    for key in (f'{LINK_PREFIX}{int(project_id)}', f'{LEGACY_PREFIX}{int(project_id)}'):
        row = db.session.get(AppSetting, key)
        if row:
            db.session.delete(row)
            cache = AppSetting._cache()
            if cache is not None:
                cache[key] = None


def start_rooms(bom, picked):
    """[{'name', 'items': []}] for the new quotation: the ticked areas (indexes into its areas), named, once each."""
    rows = areas_of(bom)
    seen, out = set(), []
    for i in picked:
        if 0 <= i < len(rows) and rows[i]['name'] and rows[i]['name'].lower() not in seen:
            seen.add(rows[i]['name'].lower())
            out.append({'name': rows[i]['name'], 'items': []})
    return out


def picked_indexes(raw):
    return [int(v) for v in str(raw or '').split(',') if v.strip().isdigit()][:MAX_AREAS]


def reference(project):
    """For the quotation form: {'bom': Bom or None, 'rows': [...], 'total'} or None — the BOM it was made from, or rows
    typed in the earlier Room areas table. Read-only."""
    if project is None or not getattr(project, 'id', None) or not enabled():
        return None
    from .models import AppSetting
    link_key, legacy_key = f'{LINK_PREFIX}{int(project.id)}', f'{LEGACY_PREFIX}{int(project.id)}'
    found = AppSetting.prefetch([link_key, legacy_key])                    # one query for both
    bom = get(found[link_key]) if (found.get(link_key) or '').isdigit() else None
    if bom is not None:
        rows = areas_of(bom)
        return {'bom': bom, 'rows': rows, 'total': total(rows)}
    rows = clean_areas(found.get(legacy_key) or '[]')
    return {'bom': None, 'rows': rows, 'total': total(rows)} if rows else None
