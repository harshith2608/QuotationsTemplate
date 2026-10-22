"""A firm's own price list, loaded by the operator from the console (Load price list) into that one business.

When a firm shares its old quotations, its items (title, description, unit, rate, group), a ready-made starting
quotation or two, and its notes and payment terms are written into a JSON file — kept outside the repository, it is
the firm's business data — and uploaded on that firm's trial or customer page. Nothing here is shared between firms:
it goes into that business's own saved BOQ lines (boq_items), quotation templates and settings.

    {"lines": [{"name": "Wardrobe", "description": "...", "unit": "sqft", "rate": 1950, "group": "Bedroom"}, ...],
     "templates": [{"name": "2 BHK turnkey",
                    "rooms": [{"name": "Kitchen", "items": ["Loft Shutter", {"name": "Tall Unit"},
                                                           {"name": "COB Light 12 W", "rate_only": true}]}]}],
     "settings": {"important_notes": "...", "payment_terms": "..."}}

A template's items name lines from "lines" (or saved ones); they start with no size or quantity, so the quotation
highlights them until one is typed (a lump sum starts at 1). "rate_only": printed with its rate, not added.
"""
import json

from . import db

MAX_BYTES = 512 * 1024
SETTINGS = ('important_notes', 'payment_terms', 'terms_conditions', 'material_specs', 'delivery_terms')


class PriceListError(ValueError):
    pass


def _text(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def parse(raw):
    """The uploaded file (bytes) → {'lines', 'templates', 'settings'}, checked. Raises PriceListError."""
    from . import boq
    if not raw:
        raise PriceListError('Choose the price list file (.json).')
    if len(raw) > MAX_BYTES:
        raise PriceListError('That file is too large for a price list.')
    try:
        data = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError):
        raise PriceListError("That isn't a price list file (it should be the .json file prepared for this firm).")
    if not isinstance(data, dict) or not isinstance(data.get('lines', []), list):
        raise PriceListError("That isn't a price list file: it needs a list of \"lines\".")

    lines, seen = [], set()
    for n, row in enumerate(data.get('lines') or [], 1):
        if not isinstance(row, dict):
            raise PriceListError(f'Line {n} is not a line (name, description, unit, rate).')
        name = _text(row.get('name'), 100)
        if not name:
            raise PriceListError(f'Line {n} has no name.')
        if name.lower() in seen:
            raise PriceListError(f'"{name}" is in the list twice.')
        seen.add(name.lower())
        try:
            rate = float(row.get('rate') or 0)
        except (TypeError, ValueError):
            raise PriceListError(f'"{name}": the rate should be a number.')
        if rate < 0:
            raise PriceListError(f'"{name}": the rate can\'t be negative.')
        lines.append({'name': name, 'description': boq.clean_description(row.get('description')),
                      'unit': boq.clean_unit(row.get('unit')), 'rate': round(rate, 2),
                      'group': _text(row.get('group'), 60) or None})

    by_name = {l['name'].lower(): l for l in lines}
    templates = []
    for t in data.get('templates') or []:
        if not isinstance(t, dict) or not _text(t.get('name'), 60):
            raise PriceListError('Each starting quotation needs a name.')
        rooms = []
        for r in t.get('rooms') or []:
            if not isinstance(r, dict) or not _text(r.get('name'), 100):
                raise PriceListError(f'"{t["name"]}": each section needs a name.')
            items = []
            for it in r.get('items') or []:
                it = {'name': it} if isinstance(it, str) else it
                if not isinstance(it, dict) or not _text(it.get('name'), 100):
                    raise PriceListError(f'"{t["name"]} → {r["name"]}": a line has no name.')
                items.append({'name': _text(it['name'], 100), 'rate_only': bool(it.get('rate_only'))})
            rooms.append({'name': _text(r['name'], 100), 'items': items})
        templates.append({'name': _text(t['name'], 60), 'rooms': rooms})
    if not lines and not templates:
        raise PriceListError('The file has no lines.')

    settings = {}
    for key, value in (data.get('settings') or {}).items():
        if key in SETTINGS and isinstance(value, str):
            settings[key] = value.strip()[:5000]
    return {'lines': lines, 'templates': templates, 'settings': settings, '_by_name': by_name}


def _template_rooms(template, saved):
    """A template's rooms as quotation rooms (the shape New Quotation starts from): each line from the saved lines,
    with no size or quantity yet (a lump sum: 1; a rate-only line: 0, printed with its rate)."""
    from . import boq
    rooms, missing = [], []
    for r in template['rooms']:
        items = []
        for it in r['items']:
            line = saved.get(it['name'].lower())
            if line is None:
                missing.append(it['name'])
                continue
            lump = line['unit'] == boq.LUMP_SUM
            items.append({'name': line['name'], 'type': 'boq', 'quantity': 1 if lump else 0, 'unit': line['unit'],
                          'unit_price': line['rate'], 'description': line['description'] or '',
                          'length': 0, 'width': 0, 'count': 1,
                          **({} if lump or it['rate_only'] else {'pending': True})})
        rooms.append({'name': r['name'], 'items': items, 'description': ''})
    return rooms, missing


def apply(parsed, remove_starter=True, replace_settings=False):
    """Load a parsed price list into the business open now (call inside its tenant context; commits).
    Lines are added or updated by name (other saved lines stay); remove_starter also removes the starter lines the
    business never changed. Starting quotations replace any with the same name. Settings: only ones never saved,
    unless replace_settings. BOQ lines are turned on (with the BOQ layout). Returns a summary dict."""
    from sqlalchemy import func
    from . import boq, quote_templates
    from .models import AppSetting, BoqItem
    from . import tenancy
    if not boq._columns_ready(tenancy.current_schema()):
        raise PriceListError('This business needs the latest database update first (Updates → Update all).')
    if AppSetting.get(boq.KEY, '') != '1':
        boq.set_enabled(True)
        db.session.flush()

    removed = 0
    if remove_starter:
        starter = {(name.lower(), unit, float(rate), description or '', category)
                   for category, name, unit, rate, description in boq.starter_lines()}
        mine = {l['name'].lower() for l in parsed['lines']}
        for row in BoqItem.query.all():
            key = (row.name.lower(), row.unit, float(row.rate or 0), row.description or '', row.category)
            if key in starter and row.name.lower() not in mine:
                db.session.delete(row)
                removed += 1

    added = updated = 0
    for l in parsed['lines']:
        row = BoqItem.query.filter(func.lower(BoqItem.name) == l['name'].lower()).first()
        if row is None:
            db.session.add(BoqItem(name=l['name'], description=l['description'], unit=l['unit'], rate=l['rate'],
                                   category=l['group']))
            added += 1
        else:
            row.name, row.description, row.unit, row.rate, row.category = (l['name'], l['description'], l['unit'],
                                                                           l['rate'], l['group'])
            updated += 1
    db.session.flush()

    saved = {r.name.lower(): {'name': r.name, 'description': r.description, 'unit': r.unit or 'nos',
                              'rate': float(r.rate or 0)} for r in BoqItem.query.all()}
    made, missing = [], []
    for t in parsed['templates']:
        rooms, miss = _template_rooms(t, saved)
        missing += miss
        quote_templates.put(t['name'], rooms)
        made.append(t['name'])

    settings = []
    for key, value in parsed['settings'].items():
        if replace_settings or AppSetting.get(key) is None:
            AppSetting.set(key, value)
            settings.append(key)
    db.session.commit()
    return {'added': added, 'updated': updated, 'removed': removed, 'templates': made,
            'missing': sorted(set(missing)), 'settings': settings}


def summary_text(result):
    parts = [f"{result['added']} lines added", f"{result['updated']} updated"]
    if result['removed']:
        parts.append(f"{result['removed']} unchanged starter lines removed")
    if result['templates']:
        parts.append('starting quotation' + ('s' if len(result['templates']) > 1 else '') + ': '
                     + ', '.join(f'"{n}"' for n in result['templates']))
    if result['settings']:
        parts.append('settings: ' + ', '.join(k.replace('_', ' ') for k in result['settings']))
    text = '; '.join(parts) + '.'
    if result['missing']:
        text += ' Not found, left out of the starting quotation: ' + ', '.join(result['missing']) + '.'
    return text
