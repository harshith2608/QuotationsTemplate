"""Room areas: the home's measurement sheet on the quotation form (Foyer 5 × 4.5 = 22.5 sqft, Living room 6 × 5 = 30…,
Total 1,185.25 sqft), for the business's own reference while quoting. Never printed: not on the PDF, the customer's
link, WhatsApp, invoices or revisions.

Turned on per business in Settings → Pricing (KEY), off by default. Each quotation's rows are kept as JSON in the
app settings (DATA_PREFIX + its id), so no database update is needed: [{'name', 'length', 'width'}], sizes in feet
like every size in the app (shown in the business's own unit); the area is worked out, never stored. Rooms here are
independent of the quotation's rooms (a passage or balcony with no work is still measured). Not copied to a duplicate
or a template (another home has other sizes); removed with the quotation.
"""
import json

from flask import request

from .models import AppSetting, db

KEY = 'room_areas_on'
DATA_PREFIX = 'room_areas:'
MAX_ROWS = 100
NAME_MAX = 60
SIZE_MAX = 100000.0          # feet; anything bigger is a typing mistake


def enabled():
    return AppSetting.get(KEY) == '1'


def _key(project_id):
    return f'{DATA_PREFIX}{int(project_id)}'


def _size(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v != v or v <= 0 or v > SIZE_MAX:       # NaN, negative, absurd
        return 0.0
    return round(v, 6)


def clean(raw):
    """The rows from the form (a JSON string or a list): named or sized rows only, at most MAX_ROWS."""
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
        if len(rows) >= MAX_ROWS:
            break
    return rows


def area(row):
    return round(row['length'] * row['width'], 4)


def total(rows):
    return round(sum(area(r) for r in rows), 4)


def get(project_id):
    if not project_id:
        return []
    return clean(AppSetting.get(_key(project_id)) or '[]')


def save(project_id, raw):
    """Saves the form's rows for the quotation (nothing sent: left as it was; an empty list clears them)."""
    if raw is None or not project_id:
        return
    rows = clean(raw)
    if rows:
        AppSetting.set(_key(project_id), json.dumps(rows, separators=(',', ':')))
    else:
        forget(project_id)


def save_from_form(project_id):
    """From a submitted quotation form: only when the business has room areas on (the form then sends them)."""
    if enabled() and 'room_areas' in request.form:
        save(project_id, request.form.get('room_areas'))


def forget(project_id):
    row = db.session.get(AppSetting, _key(project_id))
    if row:
        db.session.delete(row)
        cache = AppSetting._cache()
        if cache is not None:
            cache[_key(project_id)] = None


def for_form(project=None):
    """For the quotation form: None when off; else {'rows': [...]} (on a form sent back with a problem, what was typed)."""
    if not enabled():
        return None
    if request.method == 'POST' and 'room_areas' in request.form:
        rows = clean(request.form.get('room_areas'))
    else:
        rows = get(project.id) if project is not None and getattr(project, 'id', None) else []
    return {'rows': rows}
