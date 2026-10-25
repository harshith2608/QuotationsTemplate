"""Finishes for a business that prices by item: the same item costs more in another finish (a wardrobe at ₹1,800/sqft
in laminate, +25% in acrylic, veneer or membrane).

The business lists its finishes once (Admin → Rates → Finishes): the first is the base (the saved lines' rates are
for it), each other one is a % extra on that rate. Saved lines that come in these finishes are ticked ("Finish").
On a quotation such a line gets a Finish choice; picking one changes the line's rate (base rate × (1 + extra %)) and
the line prints as "Wardrobe (Acrylic finish)". The base finish prints nothing extra.

Stored in AppSetting 'boq_finishes' as {"options": [{"name", "extra"}], "lines": [BoqItem ids]}; a BOQ line on a
quotation keeps its finish name in items.wood_type (unused by BOQ lines otherwise), so no database update is needed.
"""
import json

KEY = 'boq_finishes'
NAME_MAX = 40
MAX_OPTIONS = 12


def _load():
    from .models import AppSetting
    try:
        data = json.loads(AppSetting.get(KEY, '') or '{}')
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def options():
    """[{'name', 'extra'}]: the base finish first (extra 0). Empty if fewer than two (nothing to choose)."""
    opts = [o for o in _load().get('options') or [] if isinstance(o, dict) and o.get('name')]
    if len(opts) < 2:
        return []
    return [{'name': str(o['name'])[:NAME_MAX], 'extra': 0.0 if n == 0 else float(o.get('extra') or 0)}
            for n, o in enumerate(opts)]


def all_options():
    """The saved list as it is (for Admin → Rates), even with only one."""
    return [{'name': str(o['name'])[:NAME_MAX], 'extra': 0.0 if n == 0 else float(o.get('extra') or 0)}
            for n, o in enumerate(o for o in _load().get('options') or [] if isinstance(o, dict) and o.get('name'))]


def line_ids():
    """Ids of the saved lines that come in these finishes."""
    return {int(i) for i in _load().get('lines') or [] if str(i).isdigit()}


def save(opts, ids):
    """opts: [(name, extra)] with the base first; ids: saved line ids. Returns error messages (nothing saved then)."""
    from .models import AppSetting
    clean, seen, errors = [], set(), []
    for n, (name, extra) in enumerate(opts):
        name = ' '.join(str(name or '').split())[:NAME_MAX]
        if not name:
            continue
        if name.lower() in seen:
            errors.append(f'"{name}" is in the finishes twice.')
            continue
        seen.add(name.lower())
        try:
            extra = 0.0 if not clean else float(extra or 0)
        except (TypeError, ValueError):
            errors.append(f'"{name}": the % extra should be a number.')
            continue
        if extra < -90 or extra > 500:
            errors.append(f'"{name}": the % extra should be between -90 and 500.')
            continue
        clean.append({'name': name, 'extra': round(extra, 2)})
    if len(clean) > MAX_OPTIONS:
        errors.append(f'Up to {MAX_OPTIONS} finishes.')
    if errors:
        return errors
    AppSetting.set(KEY, json.dumps({'options': clean, 'lines': sorted({int(i) for i in ids})}))
    return []


def base():
    opts = options()
    return opts[0]['name'] if opts else ''


def extra(name):
    """The % extra for a finish name (0 for the base or an unknown one)."""
    key = (name or '').strip().lower()
    for o in options():
        if o['name'].lower() == key:
            return o['extra']
    return 0.0


def clean(name):
    """The finish to keep on a quotation line: '' for none or the base; otherwise the name as chosen (kept even if
    the finish was renamed or removed since, so an old quotation still says what was quoted)."""
    name = ' '.join(str(name or '').split())[:NAME_MAX]
    return '' if not name or name.lower() == base().lower() else name


def base_rate(rate, name):
    """The base finish's rate for a line priced in `name` (for "Save as my default")."""
    pct = extra(name)
    return round(rate / (1 + pct / 100), 2) if pct > -100 else rate


def label(name, finish):
    """'Wardrobe (Acrylic finish)', or the name alone when there's no finish."""
    if not finish:
        return name
    return f"{name} ({finish}{'' if finish.lower().endswith('finish') else ' finish'})"


def for_form():
    """For the quotation form: {'options': [...], 'base': name} or None when the business has no finishes."""
    opts = options()
    return {'options': opts, 'base': opts[0]['name']} if opts else None


def set_from_price_list(opts, line_names):
    """From a price list file: the finishes, and the saved lines (by name) that come in them, added to the ones
    already ticked (a file with only a few new lines doesn't untick the others)."""
    from sqlalchemy import func
    from . import db
    from .models import BoqItem
    keys = [n.lower() for n in line_names]
    ids = [b.id for b in db.session.query(BoqItem).filter(func.lower(BoqItem.name).in_(keys)).all()] if keys else []
    return save([(o['name'], o.get('extra', 0)) for o in opts], set(ids) | line_ids())
