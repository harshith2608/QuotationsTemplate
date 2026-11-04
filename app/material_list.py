"""The material list of a quotation: what to buy for the job, with wastage, by group (Wood, Hardware, Electrical…), to
copy or send on WhatsApp to each supplier. No prices anywhere on it.

Built from the quotation's lines:
  * measured items, by the rules (Admin → Material rules): every sqft of an item in these materials (and work type)
    needs so much of an item to buy, e.g. 0.11 sheets of plywood per sqft of Box Work, plus wastage %. The starting
    rules are estimates for the business to adjust. A rule's name may use {material} and {plywood} (the line's).
  * fittings, as they are (their quantity, plus the spare % in Admin → Material rules); services (a 'job' or a lump
    sum) are left out.
  * BOQ lines: by the rules made for that line (1 bag of putty for every 100 sqft of Painting), in place of the line;
    a BOQ line with no rules goes on as it is (quantity and unit); lump sums are left out. Typical starting rules are
    added once for BOQ lines with a usual name (painting, tiles, gypsum ceiling, electrical points: BOQ_STARTERS).
Lines with the same name and unit add up; quantities from rules round up to whole units (sheets, rolls…).

Groups are the business's own (add, rename, remove). A fitting or BOQ line goes to the group the business last put it
in (remembered by name when they move it on a list, or set in Admin → Material rules), else one guessed from its name.

The list is saved per quotation and edited there (quantities, units, groups, lines added or removed). When the
quotation changes, Rebuild works it out again and keeps the edits: lines added by hand, quantities changed by hand and
lines removed by hand. Needs the database update that adds the material_* tables (ready()).

Off until switched on, for every business at once (app/platform_switch.py): the console's switch (dashboard → Material
list) for the shared app, MATERIAL_LIST=1 for a single-business deployment. Turning it off hides it everywhere; the
lists and rules stay, ready for when it's back on.
"""
import hashlib
import json
import math
import re
from datetime import datetime

from flask import g, has_app_context

from . import db

GROUPS_KEY = 'material_list_groups'          # JSON list of the business's groups, in order
ITEM_GROUPS_KEY = 'material_list_items'      # JSON {item name lower-case: group, or '' = leave off the list}
SPARE_KEY = 'material_list_spare'            # % added to fittings
SEEDED_KEY = 'material_rules_seeded'
DEFAULT_GROUPS = ['Wood', 'Hardware', 'Electrical', 'Paint', 'Other']
NAME_MAX = 150
GROUP_MAX = 60
UNIT_MAX = 30
SERVICE_UNITS = {'job', 'lump sum', 'ls'}

# Words that suggest a group, for a fitting or BOQ line the business hasn't put in one yet
GUESS = [
    ('Electrical', r'electric|wire|wiring|switch|socket|light|led\b|lamp|fan\b|points?\b|mcb|cable|conduit|bulb|'
                   r'chandelier|db\b'),
    ('Paint', r'paint|putty|primer|polish|emulsion|texture|enamel|distemper|duco|\bpu\b'),
    ('Hardware', r'hinge|channel|handle|drawer|basket|lock|knob|tandem|corner|pull-?out|mechanism|lift|runner|'
                 r'screw|bracket|profile'),
    ('Wood', r'ply|laminate|veneer|board|mdf|hdf|wood|carpentry|wardrobe|cabinet|shutter'),
]
NOT_BOARD = re.compile(r'glass|mirror|wallpaper|paint|fabric|stone|granite|quartz|marble|tile|metal|steel', re.I)

# Starting rules (estimates): name, group, work type ('' = any), per sqft of the item, unit, wastage %, round up,
# 'board' (materials made on plywood) / 'other' (the rest)
STARTER_RULES = [
    ('Plywood ({plywood})', 'Wood', 'Box Work', 0.11, 'sheets (8×4)', 10, True, 'board'),
    ('Plywood ({plywood})', 'Wood', 'Frame Work', 0.06, 'sheets (8×4)', 10, True, 'board'),
    ('Back panel plywood 8 mm', 'Wood', 'Box Work', 0.032, 'sheets (8×4)', 10, True, 'board'),
    ('{material} (outer finish)', 'Wood', '', 0.036, 'sheets (8×4)', 10, True, 'board'),
    ('Inner liner laminate 0.8 mm', 'Wood', 'Box Work', 0.12, 'sheets (8×4)', 10, True, 'board'),
    ('Inner liner laminate 0.8 mm', 'Wood', 'Frame Work', 0.04, 'sheets (8×4)', 10, True, 'board'),
    ('Edge banding tape', 'Wood', '', 1.0, 'm', 10, True, 'board'),
    ('Wood adhesive', 'Wood', '', 0.04, 'kg', 5, True, 'board'),
    ('Screws (box of 100)', 'Hardware', '', 0.025, 'boxes', 0, True, 'board'),
    ('{material}', 'Other', '', 1.0, 'sqft', 10, True, 'other'),
]

# Starting rules for BOQ lines with a usual name (estimates): name pattern, names to leave out, the line's units, and
# (item to buy, group, amount, for every so many sqft / points, unit, wastage %). Added once per BOQ line.
BOQ_SEEDED_KEY = 'material_rules_boq_seeded'      # JSON list of BOQ line names (lower-case) already given rules
BOQ_STARTERS = [
    (r'wardrobe|loft|cabinet|tall unit|tv unit|crockery|shoe rack|pooja|dressing|study table', r'', 'area',
     [('Plywood ({plywood})', 'Wood', 1, 9, 'sheets (8×4)', 10), ('Laminate (outer finish)', 'Wood', 1, 28, 'sheets (8×4)', 10),
      ('Inner liner laminate 0.8 mm', 'Wood', 1, 8, 'sheets (8×4)', 10), ('Edge banding tape', 'Wood', 1, 1, 'm', 10),
      ('Screws (box of 100)', 'Hardware', 1, 40, 'boxes', 0)]),
    (r'paint|emulsion', r'texture|polish|enamel', 'area',
     [('Wall putty (40 kg bag)', 'Paint', 1, 400, 'bags', 5), ('Primer', 'Paint', 1, 100, 'litres', 5),
      ('Emulsion paint', 'Paint', 1, 50, 'litres', 10)]),
    (r'tile|tiling', r'remov|grout', 'area',
     [('Tiles', 'Other', 1, 1, 'sqft', 10), ('Tile adhesive (20 kg bag)', 'Other', 1, 50, 'bags', 5),
      ('Tile grout (1 kg)', 'Other', 1, 40, 'kg', 5)]),
    (r'gypsum|^false ceiling$', r'paint', 'area',
     [('Gypsum board (6×4 ft)', 'Other', 1, 22, 'boards', 10), ('Ceiling channels (12 ft)', 'Hardware', 1, 10, 'nos', 5),
      ('Jointing compound (20 kg)', 'Other', 1, 300, 'bags', 0), ('Ceiling screws (box of 1000)', 'Hardware', 1, 250, 'boxes', 0)]),
    (r'electrical point|light point|wiring', r'', 'point',
     [('Wire 1.5 sq mm (90 m coil)', 'Electrical', 1, 8, 'coils', 0), ('PVC conduit pipe (3 m)', 'Electrical', 3, 1, 'pipes', 5)]),
]

SWITCH_KEY = 'material_list'
SWITCH_ENV = 'MATERIAL_LIST'

_ready_forever = {}


def switched_on():
    from . import platform_switch
    return platform_switch.is_on(SWITCH_KEY, SWITCH_ENV)


def available():
    """Shown and usable in this app: switched on (for every business) and the database updated."""
    return switched_on() and ready()


def ready():
    """False until the database update that adds the material list tables has run (checked once per request)."""
    from . import tenancy
    schema = tenancy.current_schema()
    if _ready_forever.get(schema):
        return True
    if has_app_context() and '_matlist_ready' in g:
        return g._matlist_ready
    from sqlalchemy import inspect
    try:
        found = inspect(db.session.connection()).has_table('material_list_lines', schema=schema)
    except Exception:
        found = False
    if found:
        _ready_forever[schema] = True
    if has_app_context():
        g._matlist_ready = found
    return found


# ── Settings: groups, remembered items, spare ────────────────────────────────

def _json_setting(key, default):
    from .models import AppSetting
    try:
        value = json.loads(AppSetting.get(key, '') or 'null')
    except ValueError:
        value = None
    return value if isinstance(value, type(default)) else default


def clean_text(raw, limit):
    return ' '.join(str(raw or '').split())[:limit]


def groups():
    found = [clean_text(x, GROUP_MAX) for x in _json_setting(GROUPS_KEY, list(DEFAULT_GROUPS))]
    return [x for i, x in enumerate(found) if x and x.lower() not in {y.lower() for y in found[:i]}] or ['Other']


def fallback_group(names=None):
    names = names or groups()
    return next((x for x in names if x.lower() == 'other'), names[-1])


def _raw_item_groups():
    return {clean_text(k, NAME_MAX): clean_text(v, GROUP_MAX) for k, v in _json_setting(ITEM_GROUPS_KEY, {}).items()
            if clean_text(k, NAME_MAX)}


def item_groups():
    """{item name lower-case: group, or '' = leave off}."""
    return {k.lower(): v for k, v in _raw_item_groups().items()}


def item_group_rows():
    """[(item name as typed, group)] for Admin → Material rules."""
    return sorted(_raw_item_groups().items(), key=lambda kv: kv[0].lower())


def _save_item_groups(found):
    from .models import AppSetting
    AppSetting.set(ITEM_GROUPS_KEY, json.dumps(found))


def remember(name, group):
    """Put this fitting / BOQ line in `group` on every list from now on ('' = leave it off)."""
    name = clean_text(name, NAME_MAX)
    found = {k: v for k, v in _raw_item_groups().items() if k.lower() != name.lower()}
    found[name] = group
    _save_item_groups(found)


def forget(name):
    name = clean_text(name, NAME_MAX).lower()
    _save_item_groups({k: v for k, v in _raw_item_groups().items() if k.lower() != name})


def spare():
    from .models import AppSetting
    try:
        return max(float(AppSetting.get(SPARE_KEY, '') or 0), 0.0)
    except ValueError:
        return 0.0


def save_groups(rows):
    """rows: [(old name or '', new name, remove)] in order. Renames / removes them everywhere (rules, lists,
    remembered items); what was in a removed group moves to Other (or the last group)."""
    from .models import AppSetting, MaterialListLine, MaterialRule
    kept, renames, removed = [], {}, []
    for old, new, remove in rows:
        new = clean_text(new, GROUP_MAX)
        if remove or not new:
            if old:
                removed.append(old)
            continue
        if new.lower() in {k.lower() for k in kept}:
            continue
        kept.append(new)
        if old and old != new:
            renames[old] = new
    kept = kept or ['Other']
    fallback = fallback_group(kept)
    moves = dict(renames, **{r: fallback for r in removed})
    for old, new in moves.items():
        MaterialRule.query.filter_by(category=old).update({'category': new})
        MaterialListLine.query.filter_by(category=old).update({'category': new})
    _save_item_groups({k: moves.get(v, v) for k, v in _raw_item_groups().items()})
    AppSetting.set(GROUPS_KEY, json.dumps(kept))
    return kept


def guess_group(name, default, names=None):
    names = names or groups()
    lower = {x.lower(): x for x in names}
    text = (name or '').lower()
    for group, pattern in GUESS:
        if group.lower() in lower and re.search(pattern, text):
            return lower[group.lower()]
    return lower.get(default.lower()) or fallback_group(names)


# ── Rules ────────────────────────────────────────────────────────────────────

def _board_materials(names):
    from . import plywood
    on_ply = plywood.context()['materials']
    return [n for n in names if (n in on_ply if on_ply else not NOT_BOARD.search(n))]


def seed_rules():
    """The starting rules, once per business (deleting them all later doesn't bring them back)."""
    from . import units
    from .models import AppSetting, Material, MaterialRule
    if AppSetting.get(SEEDED_KEY) or MaterialRule.query.first():
        return
    names = [m.name for m in Material.query.filter_by(active=True).order_by(Material.sort_order, Material.id)]
    board = _board_materials(names)
    other = [n for n in names if n not in board]
    known = {x.lower() for x in groups()}
    for i, (name, group, work, per, unit, wastage, up, kind) in enumerate(STARTER_RULES):
        mats = board if kind == 'board' else other
        if not mats:
            continue
        if unit == 'sqft' and units.area_unit() == 'sqm':
            unit = 'sq m'
            per = per * units.SQM_PER_SQFT
        db.session.add(MaterialRule(name=name, category=group if group.lower() in known else fallback_group(),
                                    materials=json.dumps(mats), work_type=work, per_sqft=per, unit=unit,
                                    wastage=wastage, round_up=up, sort_order=i))
    AppSetting.set(SEEDED_KEY, '1')
    db.session.commit()


def seed():
    """The starting rules: for measured items once per business, then for BOQ lines once per line."""
    seed_rules()
    seed_boq_rules()


def seed_boq_rules():
    """Typical rules for each BOQ line with a usual name (BOQ_STARTERS), once per line (deleting them later doesn't
    bring them back). A line added later gets them the next time a list or the rules page is opened."""
    from . import boq, units
    from .models import AppSetting, BoqItem, MaterialRule
    if not boq.ready():
        return
    done = set(_json_setting(BOQ_SEEDED_KEY, []))
    fresh = [b for b in BoqItem.query.all() if b.name.lower() not in done]
    if not fresh:
        return
    known = {x.lower() for x in groups()}
    top = max([r.sort_order for r in rules()] or [0])
    for b in fresh:
        done.add(b.name.lower())
        unit = b.unit or ''
        for pattern, skip, kind, rows in BOQ_STARTERS:
            if not re.search(pattern, b.name, re.I) or (skip and re.search(skip, b.name, re.I)):
                continue
            if kind == 'area' and unit not in boq.AREA_UNITS or kind == 'point' and unit not in ('point', 'nos'):
                break
            for name, group, amount, every, buy_unit, wastage in rows:
                if kind == 'area':                     # 'for every so many sqft' → per one of the line's unit
                    every = every * boq.AREA_UNITS[unit]
                    if buy_unit == 'sqft' and units.area_unit() == 'sqm':
                        amount, buy_unit = amount * units.SQM_PER_SQFT, 'sq m'
                top += 1
                db.session.add(MaterialRule(name=name, category=group if group.lower() in known else fallback_group(),
                                            materials=json.dumps({'boq': b.name}), work_type='',
                                            per_sqft=amount / every, unit=buy_unit, wastage=wastage, round_up=True,
                                            sort_order=top))
            break
    AppSetting.set(BOQ_SEEDED_KEY, json.dumps(sorted(done)))
    db.session.commit()


def rules():
    from .models import MaterialRule
    return MaterialRule.query.order_by(MaterialRule.sort_order, MaterialRule.id).all()


def _rule_target(rule):
    try:
        return json.loads(rule.materials or '[]')
    except ValueError:
        return []


def rule_materials(rule):
    """The materials a rule for measured items is for ([] = every material; [] too for a rule on a BOQ line)."""
    found = _rule_target(rule)
    return [m for m in found if isinstance(m, str)] if isinstance(found, list) else []


def rule_boq(rule):
    """The BOQ line a rule is for (its name), or '' for a rule on measured items."""
    found = _rule_target(rule)
    return clean_text(found.get('boq'), NAME_MAX) if isinstance(found, dict) else ''


# How a rule is shown and typed: "1 sheet for every 9 sqft"; [ply] and [finish] in names
TOKENS = (('{plywood}', '[ply]'), ('{material}', '[finish]'))


def name_shown(name):
    for stored, shown in TOKENS:
        name = (name or '').replace(stored, shown)
    return name


def name_stored(name):
    for stored, shown in TOKENS:
        name = re.sub(re.escape(shown), stored, name or '', flags=re.I)
    return name


def coverage(per):
    """(amount, for every): 0.11 → (1, 9.09); 1.5 → (1.5, 1)."""
    if not per or per >= 1:
        return round(per or 0, 3), 1
    return 1, round(1 / per, 2)


def render_name(template, material='', plywood=''):
    name = (template or '').replace('{material}', material or '').replace('{plywood}', plywood or '')
    name = re.sub(r'\(\s*\)|\[\s*\]', '', name)
    return clean_text(name.strip(' -–,'), NAME_MAX)


# ── Building ─────────────────────────────────────────────────────────────────

def signature(project, rooms=None):
    """What the list is built from (the quotation's lines), to tell when the quotation changed."""
    from . import plywood
    rows = []
    ply = plywood.project_plywood(project) or ''
    for room in (rooms if rooms is not None else project.rooms_with_items()):
        for i in room.item_list:
            rows.append([room.name, i.name, i.item_type, i.wood_type, i.work_type, round(i.area or 0, 3),
                         round(i.quantity or 0, 3), i.unit_text if i.is_boq else '', plywood.item_plywood(i) or ply])
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _qty(value, up):
    if up:
        return float(math.ceil(round(value, 6)))
    return round(value, 2)


def build(project, rooms=None):
    """The lines of a fresh list: [{'key', 'kind', 'category', 'name', 'quantity', 'unit', 'source'}] in group order."""
    from . import boq, plywood
    from .models import PriceListItem
    rooms = rooms if rooms is not None else project.rooms_with_items()
    names = groups()
    lower = {x.lower(): x for x in names}
    remembered = item_groups()
    fittings_unit = {p.name.lower(): (p.unit or '') for p in PriceListItem.query.all()}
    extra = 1 + spare() / 100
    ply = plywood.project_plywood(project) or ''
    active = [r for r in rules() if r.active and r.per_sqft]
    by_line = {}
    for r in active:
        if rule_boq(r):
            by_line.setdefault(rule_boq(r).lower(), []).append(r)
    active = [r for r in active if not rule_boq(r)]
    rule_mats = {r.id: rule_materials(r) for r in active}
    out = {}

    def group_for(name, default):
        if name.lower() in remembered:
            group = remembered[name.lower()]
            return lower.get(group.lower(), fallback_group(names)) if group else None
        return default

    def add(key, kind, category, name, qty, unit, source, up=False):
        line = out.setdefault(key, {'key': key, 'kind': kind, 'category': category, 'name': name, 'raw': 0.0,
                                    'unit': unit, 'sources': [], 'up': up})
        line['raw'] += qty or 0
        if source not in line['sources']:
            line['sources'].append(source)

    for room in rooms:
        for i in room.item_list:
            source = f'{i.name} ({room.name})'
            if i.is_boq:
                if ((i.unit if boq.ready() else '') or '') == boq.LUMP_SUM:
                    continue
                if i.name.lower() in by_line:            # its own rules, in place of the line
                    for r in by_line[i.name.lower()]:
                        name = render_name(r.name, i.finish or '', plywood.item_plywood(i) or ply)
                        unit = clean_text(r.unit, UNIT_MAX)
                        group = group_for(name, lower.get((r.category or '').lower(), fallback_group(names)))
                        if name and group:
                            add(f'rule|{name.lower()}|{unit.lower()}', 'rule', group, name,
                                (i.quantity or 0) * r.per_sqft * (1 + (r.wastage or 0) / 100), unit, source,
                                up=r.round_up)
                    continue
                unit = i.unit_text
                name = clean_text(i.display_name, NAME_MAX)
                group = group_for(name, guess_group(name, 'Other', names))
                if group:
                    add(f'boq|{name.lower()}|{unit.lower()}', 'boq', group, name, i.quantity, unit, source)
            elif i.is_fitting:
                unit = fitting_unit(fittings_unit.get(i.name.lower(), ''))
                if unit is None:
                    continue
                name = clean_text(i.name, NAME_MAX)
                group = group_for(name, guess_group(name, 'Hardware', names))
                if group:
                    add(f'fitting|{name.lower()}|{unit.lower()}', 'fitting', group, name, (i.quantity or 0) * extra,
                        unit, source, up=extra != 1)
            else:
                item_ply = plywood.item_plywood(i) or ply
                for r in active:
                    if rule_mats[r.id] and i.wood_type not in rule_mats[r.id]:
                        continue
                    if r.work_type and r.work_type != i.work_type:
                        continue
                    name = render_name(r.name, i.wood_type, item_ply)
                    if not name:
                        continue
                    unit = clean_text(r.unit, UNIT_MAX)
                    group = group_for(name, lower.get((r.category or '').lower(), fallback_group(names)))
                    if group:
                        add(f'rule|{name.lower()}|{unit.lower()}', 'rule', group, name,
                            (i.area or 0) * r.per_sqft * (1 + (r.wastage or 0) / 100), unit, source, up=r.round_up)
    order = {x: n for n, x in enumerate(names)}
    lines = sorted(out.values(), key=lambda x: order.get(x['category'], len(order)))
    for line in lines:
        line['quantity'] = _qty(line.pop('raw'), line.pop('up'))
        line['source'] = source_text(line.pop('sources'))
    return lines


def fitting_unit(unit):
    """A fitting's unit on a list ('nos' for pieces), or None for a service (a job, a lump sum)."""
    unit = unit or ''
    if unit.lower() in SERVICE_UNITS:
        return None
    return 'nos' if unit.lower() in ('', 'piece', 'pieces', 'nos', 'no') else unit


def source_text(sources):
    if len(sources) <= 3:
        return ', '.join(sources)
    return ', '.join(sources[:3]) + f' and {len(sources) - 3} more'


# ── The saved list ───────────────────────────────────────────────────────────

def get(project):
    from .models import MaterialList
    return MaterialList.query.filter_by(project_id=project.id).first()


def delete_for(project):
    """With the quotation (the database also does it, but not every database enforces it)."""
    if ready():
        lst = get(project)
        if lst is not None:
            db.session.delete(lst)


def create(project):
    from .models import MaterialList, MaterialListLine
    rooms = project.rooms_with_items()
    lst = MaterialList(project_id=project.id, signature=signature(project, rooms))
    db.session.add(lst)
    db.session.flush()
    for n, line in enumerate(build(project, rooms)):
        db.session.add(MaterialListLine(list_id=lst.id, sort_order=n, **line))
    db.session.commit()
    return lst


def changed(lst, project):
    return lst.signature != signature(project)


def rebuild(lst, project):
    """Work the list out again from the quotation, keeping the edits. Returns {'added', 'gone', 'changed'}: names."""
    from .models import MaterialListLine
    rooms = project.rooms_with_items()
    fresh = build(project, rooms)
    old = {ln.key: ln for ln in lst.lines if ln.kind != 'manual'}
    report = {'added': [], 'gone': [], 'changed': []}
    order = {x: n for n, x in enumerate(groups())}
    for n, line in enumerate(fresh):
        row = old.pop(line['key'], None)
        if row is None:
            db.session.add(MaterialListLine(list_id=lst.id, sort_order=n, **line))
            report['added'].append(line['name'])
            continue
        row.source, row.sort_order = line['source'], n
        if not row.edited and not row.removed and row.quantity != line['quantity']:
            row.quantity, row.unit = line['quantity'], line['unit']
            report['changed'].append(row.name)
    for row in old.values():
        if not row.removed:
            report['gone'].append(row.name)
        db.session.delete(row)
    manual_at = len(fresh)
    for row in lst.lines.filter_by(kind='manual'):
        row.sort_order = manual_at + order.get(row.category, len(order))
    lst.signature, lst.built_at = signature(project, rooms), datetime.utcnow()
    lst.updated_at = lst.built_at
    db.session.commit()
    return report


def by_group(lst, removed=False):
    """[(group, [lines])] in the business's group order; a group no longer in the list comes last."""
    names = groups()
    found = {}
    for ln in lst.lines:
        if bool(ln.removed) == removed:
            found.setdefault(ln.category, []).append(ln)
    ordered = [g_ for g_ in names if g_ in found] + [g_ for g_ in found if g_ not in names]
    return [(g_, sorted(found[g_], key=lambda ln: (ln.kind == 'manual', ln.sort_order, ln.id))) for g_ in ordered]


def number(raw):
    try:
        value = float(str(raw).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    return round(value, 3) if value >= 0 and math.isfinite(value) else None


def save(lst, form):
    """Save the list page: each line's name, quantity, unit, group, ordered / removed / restored, and new lines.
    A built line moved to another group puts that item in the group from now on (remember)."""
    from .models import MaterialListLine
    names = groups()
    for ln in lst.lines.all():
        p = f'{ln.id}_'
        if form.get(p + 'restore'):
            ln.removed = False
            continue
        if ln.removed:
            continue
        if form.get(p + 'remove'):
            if ln.kind == 'manual':
                db.session.delete(ln)
            else:
                ln.removed = True
            continue
        if p + 'qty' not in form:
            continue
        qty = number(form.get(p + 'qty'))
        unit = clean_text(form.get(p + 'unit'), UNIT_MAX)
        name = clean_text(form.get(p + 'name'), NAME_MAX) or ln.name
        if ln.kind != 'manual' and (qty != ln.quantity or unit != (ln.unit or '') or name != ln.name):
            ln.edited = True
        ln.quantity, ln.unit, ln.name = qty, unit, name
        group = clean_text(form.get(p + 'group'), GROUP_MAX)
        if group in names and group != ln.category:
            ln.category = group
            if ln.kind != 'manual':
                remember(ln.name, group)
        ln.ordered = bool(form.get(p + 'ordered'))
    top = max([ln.sort_order for ln in lst.lines] or [0])
    for n, (name, qty, unit, group) in enumerate(zip(form.getlist('new_name'), form.getlist('new_qty'),
                                                     form.getlist('new_unit'), form.getlist('new_group'))):
        name = clean_text(name, NAME_MAX)
        if not name:
            continue
        db.session.add(MaterialListLine(list_id=lst.id, kind='manual', name=name, quantity=number(qty),
                                        unit=clean_text(unit, UNIT_MAX),
                                        category=group if group in names else fallback_group(names),
                                        sort_order=top + 1 + n))
    lst.updated_at = datetime.utcnow()
    db.session.commit()


# ── Select materials: tick what goes on the list ─────────────────────────────

CHOICES_MAX = 600


def catalogue(project):
    """Everything the business could put on a list, by name: [{'name', 'unit', 'group'}]. The material rules (one per
    plywood and per material when the rule names them), fittings (not services), BOQ lines (not lump sums) and items
    typed by hand on earlier lists."""
    from . import boq, plywood
    from .models import BoqItem, Material, MaterialListLine, PriceListItem
    names = groups()
    lower = {x.lower(): x for x in names}
    remembered = item_groups()
    out = {}

    def add(name, unit, default):
        name, unit = clean_text(name, NAME_MAX), clean_text(unit, UNIT_MAX)
        if not name or name.lower() in out:
            return
        group = remembered.get(name.lower()) or default
        out[name.lower()] = {'name': name, 'unit': unit, 'group': lower.get((group or '').lower()) or fallback_group(names)}

    mats = [m.name for m in Material.query.filter_by(active=True).order_by(Material.sort_order, Material.id)]
    plys = [o['name'] for o in plywood.context()['options'] if o.get('active', True)] or \
        [plywood.project_plywood(project) or '']
    for r in rules():
        if not r.active:
            continue
        for mat in ((rule_materials(r) or mats) if '{material}' in (r.name or '') else ['']):
            for ply in (plys if '{plywood}' in (r.name or '') else ['']):
                add(render_name(r.name, mat, ply), r.unit, r.category)
    for f in PriceListItem.query.order_by(PriceListItem.name):
        unit = fitting_unit(f.unit)
        if unit is not None:
            add(f.name, unit, guess_group(f.name, 'Hardware', names))
    if boq.ready():
        for b in BoqItem.query.order_by(BoqItem.name):
            if (b.unit or '') != boq.LUMP_SUM:
                add(b.name, boq.unit_text(b.unit or 'nos'), guess_group(b.name, 'Other', names))
    for ln in MaterialListLine.query.filter_by(kind='manual').order_by(MaterialListLine.id.desc()).limit(CHOICES_MAX):
        add(ln.name, ln.unit, ln.category)
    return list(out.values())[:CHOICES_MAX]


def choices(lst, project):
    """Select materials: [(group, [{'line' or None, 'name', 'unit', 'quantity', 'source', 'on'}])] in group order.
    The list's lines first (ticked unless removed), then the rest of the catalogue, not ticked."""
    names = groups()
    found, seen = {}, set()
    for ln in sorted(lst.lines, key=lambda ln: (ln.kind == 'manual', ln.sort_order, ln.id)):
        seen.add(ln.name.lower())
        found.setdefault(ln.category, []).append({'line': ln, 'name': ln.name, 'unit': ln.unit or '',
                                                  'quantity': ln.quantity, 'source': ln.source, 'on': not ln.removed})
    for c in catalogue(project):
        if c['name'].lower() not in seen:
            found.setdefault(c['group'], []).append({'line': None, 'name': c['name'], 'unit': c['unit'],
                                                     'quantity': None, 'source': '', 'on': False})
    ordered = [g_ for g_ in names if g_ in found] + [g_ for g_ in found if g_ not in names]
    return [(g_, found[g_]) for g_ in ordered]


def save_selection(lst, form):
    """Save Select materials: a list line ticked stays (with its quantity), unticked is removed (it stays a choice);
    a catalogue item ticked is added (kind 'manual'); new rows typed in are added."""
    from .models import MaterialListLine
    names = groups()
    for ln in lst.lines.all():
        p = f'l{ln.id}_'
        if p + 'seen' not in form:
            continue
        ln.removed = not form.get(p + 'on')
        if ln.removed:
            continue
        qty = number(form.get(p + 'qty'))
        if qty != ln.quantity:
            ln.quantity = qty
            ln.edited = ln.kind != 'manual'
    top = max([ln.sort_order for ln in lst.lines] or [0])
    picked = [(form.get(k[:-2] + 'name'), form.get(k[:-2] + 'qty'), form.get(k[:-2] + 'unit'), form.get(k[:-2] + 'group'))
              for k in form if re.fullmatch(r'c\d+_on', k)]
    picked += list(zip(form.getlist('new_name'), form.getlist('new_qty'), form.getlist('new_unit'),
                       form.getlist('new_group')))
    have = {ln.name.lower(): ln for ln in lst.lines}
    for n, (name, qty, unit, group) in enumerate(picked):
        name = clean_text(name, NAME_MAX)
        if not name:
            continue
        if name.lower() in have:                     # typed again: it's on the list (put back if removed)
            have[name.lower()].removed = False
            continue
        have[name.lower()] = MaterialListLine(list_id=lst.id, kind='manual', name=name, quantity=number(qty),
                                              unit=clean_text(unit, UNIT_MAX),
                                              category=group if group in names else fallback_group(names),
                                              sort_order=top + 1 + n)
        db.session.add(have[name.lower()])
    lst.updated_at = datetime.utcnow()
    db.session.commit()


# ── Sending ──────────────────────────────────────────────────────────────────

def qty_text(qty):
    if qty is None:
        return ''
    return f'{qty:,.2f}'.rstrip('0').rstrip('.')


def line_text(ln):
    amount = ' '.join(x for x in (qty_text(ln.quantity), ln.unit or '') if x)
    return f'{ln.name} – {amount}' if amount else ln.name


def text(lst, project, group=None):
    """The list for WhatsApp / copying: one group, or every group with its heading. No prices."""
    from .branding import get_brand
    parts = [p for p in (project.customer_name, ' '.join((project.address or '').split())) if p]
    title = f'{group} list' if group else 'Material list'
    out = [f'*{get_brand()["name"]}* – {title}', 'For: ' + ', '.join(parts), '']
    for name, lines in by_group(lst):
        if group and name != group:
            continue
        if not group:
            out.append(f'*{name}*')
        out += [f'{n}. {line_text(ln)}' for n, ln in enumerate(lines, 1)]
        if not group:
            out.append('')
    return '\n'.join(out).strip()
