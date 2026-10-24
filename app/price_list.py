"""A firm's own price list, loaded by the operator from the console (Load price list) into that one business.

When a firm shares its old quotations, how it prices, its items and rates, a ready-made starting quotation or two
(templates), and its notes and payment terms are written into a JSON file — kept outside the repository, it is the
firm's business data — and uploaded on that firm's trial or customer page. Nothing here is shared between firms: it
goes into that business's own saved lines, rates, templates and settings.

A firm that prices by item (turnkey, "pricing": "item", the default when there are "lines"):
    {"lines": [{"name": "Wardrobe", "description": "...", "unit": "sqft", "rate": 1950, "group": "Bedroom"}, ...],
     "templates": [{"name": "2 BHK turnkey",
                    "rooms": [{"name": "Kitchen", "description": ["Notes for this section"],
                               "items": ["Loft Shutter", {"name": "Tall Unit"},
                                                           {"name": "COB Light 12 W", "rate_only": true}]}]}],
     "settings": {"important_notes": "...", "payment_terms": "..."}}
A template's items name lines from "lines" (or saved ones); they start with no size or quantity, so the quotation
highlights them until one is typed (a lump sum starts at 1). "rate_only": printed with its rate, not added.
A section's "description" lines are its notes (printed under the section heading); they're also added to the
business's list of room descriptions (Settings → Quotation PDFs), so they can be ticked on other quotations.

Finishes (optional, by item): the same item in another finish costs a % more. The first is the base (the lines'
rates are for it); lines that come in them say "finish": true (app/finishes.py):
    {"finishes": [{"name": "Laminate"}, {"name": "Acrylic", "extra": 25}, {"name": "Veneer", "extra": 25}],
     "lines": [{"name": "Wardrobe", "unit": "sqft", "rate": 1800, "finish": true}, ...]}

A firm that prices by material ("pricing": "material"):
    {"pricing": "material",
     "materials": [{"name": "Laminates", "rates": {"Box Work": 850, "Frame Work": 650}}, {"name": "Glass", "rate": 400}],
     "fittings": [{"name": "Magic Corner", "price": 18000, "unit": "nos"}],
     "templates": [{"name": "2 BHK", "rooms": [{"name": "Kitchen", "items": [
         {"name": "Kitchen Base Unit", "material": "Laminates", "work": "Box Work"},
         {"name": "Magic Corner", "type": "fitting"}]}]}]}
Template items with a material are measured items (size typed on the quotation); "type": "fitting" items take the
fittings price.
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
    pricing = data.get('pricing') or ('item' if data.get('lines') else 'material')
    if pricing not in ('item', 'material'):
        raise PriceListError('"pricing" should be "item" or "material".')

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
                      'group': _text(row.get('group'), 60) or None, 'finish': bool(row.get('finish'))})

    finishes = []
    for n, f in enumerate(data.get('finishes') or []):
        name = _text(f.get('name') if isinstance(f, dict) else '', 40)
        if not name:
            raise PriceListError('Each finish needs a name (the first one is the base, e.g. Laminate).')
        try:
            extra = 0.0 if n == 0 else round(float(f.get('extra') or 0), 2)
        except (TypeError, ValueError):
            raise PriceListError(f'"{name}": the % extra should be a number.')
        finishes.append({'name': name, 'extra': extra})
    if len(finishes) == 1:
        raise PriceListError('Finishes: list the base finish and at least one other (e.g. Laminate, Acrylic +25%).')

    from .catalog import WORK_TYPES
    materials = []
    for m in data.get('materials') or []:
        name = _text(m.get('name') if isinstance(m, dict) else '', 60)
        if not name:
            raise PriceListError('Each material needs a name.')
        rates = m.get('rates')
        try:
            if isinstance(rates, dict):
                bad = [w for w in rates if w not in WORK_TYPES]
                if bad:
                    raise PriceListError(f'"{name}": work types are {", ".join(WORK_TYPES)} (not {", ".join(bad)}).')
                rates = {w: round(float(rates.get(w) or 0), 2) for w in WORK_TYPES}
            else:
                rates = {'': round(float(m.get('rate') or 0), 2)}
        except (TypeError, ValueError):
            raise PriceListError(f'"{name}": rates should be numbers.')
        materials.append({'name': name, 'rates': rates})
    fittings = []
    for f in data.get('fittings') or []:
        name = _text(f.get('name') if isinstance(f, dict) else '', 100)
        if not name:
            raise PriceListError('Each fitting needs a name.')
        try:
            price = round(float(f.get('price') or 0), 2)
        except (TypeError, ValueError):
            raise PriceListError(f'"{name}": the price should be a number.')
        fittings.append({'name': name, 'price': price, 'unit': _text(f.get('unit'), 30) or None})

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
                kind = 'measured' if it.get('material') else 'fitting' if it.get('type') in ('fitting', 'fixed') else 'line'
                items.append({'name': _text(it['name'], 100), 'rate_only': bool(it.get('rate_only')), 'kind': kind,
                              'material': _text(it.get('material'), 60), 'work': _text(it.get('work'), 50),
                              'description': boq.clean_description(it.get('description'))})
            desc = r.get('description') or []
            desc = [_text(d, 300) for d in ([desc] if isinstance(desc, str) else desc) if _text(d, 300)]
            rooms.append({'name': _text(r['name'], 100), 'items': items, 'description': desc})
        templates.append({'name': _text(t['name'], 60), 'rooms': rooms})
    if any(l['finish'] for l in lines) and not finishes:
        raise PriceListError('Some lines say "finish": true, but the file has no "finishes".')
    if not lines and not templates and not materials and not fittings:
        raise PriceListError('The file has no lines.')

    settings = {}
    for key, value in (data.get('settings') or {}).items():
        if key in SETTINGS and isinstance(value, str):
            settings[key] = value.strip()[:5000]
    return {'pricing': pricing, 'lines': lines, 'materials': materials, 'fittings': fittings, 'finishes': finishes,
            'templates': templates,
            'settings': settings, '_by_name': by_name}


def _template_rooms(template, saved, fittings, combos):
    """A template's rooms as quotation rooms (the shape New Quotation starts from): each line from the saved lines,
    with no size or quantity yet (a lump sum: 1; a rate-only line: 0, printed with its rate); measured items with
    their material and work type, and fittings with their price, waiting for a size or quantity."""
    from . import boq
    rooms, missing = [], []
    for r in template['rooms']:
        items = []
        for it in r['items']:
            if it['kind'] == 'measured':
                work = it['work'] if (it['material'], it['work']) in combos else ''
                if (it['material'], work) not in combos:
                    missing.append(f"{it['name']} ({' '.join(x for x in (it['material'], it['work']) if x)})")
                    continue
                items.append({'name': it['name'], 'type': 'measured', 'length': 0, 'width': 0, 'area': 0, 'count': 1,
                              'wood_type': it['material'], 'work_type': work, 'description': it['description'] or '',
                              'pending': True})
                continue
            if it['kind'] == 'fitting':
                price = fittings.get(it['name'].lower())
                if price is None:
                    missing.append(it['name'])
                    continue
                items.append({'name': it['name'], 'type': 'fixed', 'quantity': 0, 'unit_price': price,
                              'description': it['description'] or '', 'pending': True})
                continue
            line = saved.get(it['name'].lower())
            if line is None:
                missing.append(it['name'])
                continue
            lump = line['unit'] == boq.LUMP_SUM
            items.append({'name': line['name'], 'type': 'boq', 'quantity': 1 if lump else 0, 'unit': line['unit'],
                          'unit_price': line['rate'], 'description': line['description'] or '',
                          'length': 0, 'width': 0, 'count': 1,
                          **({} if lump or it['rate_only'] else {'pending': True})})
        rooms.append({'name': r['name'], 'items': items, 'description': '\n'.join(r.get('description') or [])})
    return rooms, missing


def apply(parsed, remove_starter=True, replace_settings=False):
    """Load a parsed price list into the business open now (call inside its tenant context; commits).
    Lines are added or updated by name (other saved lines stay); remove_starter also removes the starter lines the
    business never changed. Starting quotations replace any with the same name. Settings: only ones never saved,
    unless replace_settings. BOQ lines are turned on (with the BOQ layout). Returns a summary dict."""
    from sqlalchemy import func
    from . import boq, materials as M, quote_templates
    from .models import AppSetting, BoqItem, ItemRate, Material, PriceListItem
    from . import tenancy
    ready = boq._columns_ready(tenancy.current_schema())
    if parsed['pricing'] == 'item' and not ready:
        raise PriceListError('This business needs the latest database update first (Updates → Update all).')
    if (AppSetting.get(boq.KEY, '') == '1') != (parsed['pricing'] == 'item'):
        boq.set_pricing(boq.ITEM if parsed['pricing'] == 'item' else boq.MATERIAL)
        db.session.flush()
    else:
        from . import setup_guide
        setup_guide.mark('pricing')

    # Everything already saved, read once (not one query per line)
    have_mats = {r.name.lower(): r for r in Material.query.all()} if parsed['materials'] else {}
    have_rates = {(r.wood_type, r.work_type): r for r in ItemRate.query.all()} if parsed['materials'] else {}
    have_fits = {r.name.lower(): r for r in PriceListItem.query.all()}
    mats = 0
    for m in parsed['materials']:
        row = have_mats.get(m['name'].lower())
        if row is None:
            top = db.session.query(func.max(Material.sort_order)).scalar() or 0
            row = Material(name=m['name'], uses_work_types='' not in m['rates'], active=True, sort_order=top + 1)
            db.session.add(row)
        row.active = True
        for work, rate in m['rates'].items():
            r = have_rates.get((row.name, work))
            if r is None:
                db.session.add(ItemRate(wood_type=row.name, work_type=work, rate_per_sqft=rate))
            else:
                r.rate_per_sqft = rate
        mats += 1
    for f in parsed['fittings']:
        row = have_fits.get(f['name'].lower())
        if row is None:
            row = have_fits[f['name'].lower()] = PriceListItem(name=f['name'], price=f['price'], unit=f['unit'])
            db.session.add(row)
        else:
            row.price, row.unit = f['price'], f['unit']
    db.session.flush()

    have_lines = {r.name.lower(): r for r in BoqItem.query.all()} if ready else {}
    removed = 0
    if remove_starter and ready:
        starter = {(name.lower(), unit, float(rate), description or '', category)
                   for metric in (False, True)                     # added in sqft or in sq m (Settings → Units)
                   for category, name, unit, rate, description in boq.starter_lines(metric)}
        mine = {l['name'].lower() for l in parsed['lines']}
        for row in list(have_lines.values()):
            key = (row.name.lower(), row.unit, float(row.rate or 0), row.description or '', row.category)
            if key in starter and row.name.lower() not in mine:
                db.session.delete(row)
                del have_lines[row.name.lower()]
                removed += 1

    added = updated = 0
    for l in parsed['lines'] if ready else []:
        row = have_lines.get(l['name'].lower())
        if row is None:
            row = have_lines[l['name'].lower()] = BoqItem(name=l['name'], description=l['description'], unit=l['unit'],
                                                          rate=l['rate'], category=l['group'])
            db.session.add(row)
            added += 1
        else:
            row.name, row.description, row.unit, row.rate, row.category = (l['name'], l['description'], l['unit'],
                                                                           l['rate'], l['group'])
            updated += 1
    db.session.flush()
    if parsed.get('finishes') and ready:                   # Laminate (base), Acrylic +25%… and the lines in them
        from . import finishes
        errors = finishes.set_from_price_list(parsed['finishes'], [l['name'] for l in parsed['lines'] if l['finish']])
        if errors:
            raise PriceListError(' '.join(errors))

    saved = {k: {'name': r.name, 'description': r.description, 'unit': r.unit or 'nos', 'rate': float(r.rate or 0)}
             for k, r in have_lines.items()}
    fittings = {k: float(r.price or 0) for k, r in have_fits.items()}
    combos = {(w, k) for w, k, _ in M.combos(include_hidden=True)}
    made, missing = [], []
    for t in parsed['templates']:
        rooms, miss = _template_rooms(t, saved, fittings, combos)
        missing += miss
        quote_templates.put(t['name'], rooms)
        made.append(t['name'])

    # Section notes used by the starting quotations join the business's room descriptions (never removing any)
    from . import layout
    notes = [d for t in parsed['templates'] for r in t['rooms'] for d in r.get('description') or []]
    have = layout.description_options()
    new_notes = [d for d in dict.fromkeys(notes) if d not in have]
    settings = []
    if new_notes:
        AppSetting.set(layout.DESCRIPTIONS_KEY, '\n'.join(have + new_notes))
        settings.append(layout.DESCRIPTIONS_KEY)
    for key, value in parsed['settings'].items():
        if replace_settings or AppSetting.get(key) is None:
            AppSetting.set(key, value)
            settings.append(key)
    db.session.commit()
    return {'added': added, 'updated': updated, 'removed': removed, 'templates': made, 'materials': mats,
            'fittings': len(parsed['fittings']), 'pricing': parsed['pricing'], 'finishes': len(parsed.get('finishes') or []),
            'missing': sorted(set(missing)), 'settings': settings}


def summary_text(result):
    parts = ['priced by item' if result['pricing'] == 'item' else 'priced by material']
    if result['added'] or result['updated']:
        parts += [f"{result['added']} lines added", f"{result['updated']} updated"]
    if result['materials']:
        parts.append(f"{result['materials']} materials with their rates")
    if result['fittings']:
        parts.append(f"{result['fittings']} fittings")
    if result.get('finishes'):
        parts.append(f"{result['finishes']} finishes")
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
