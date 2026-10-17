"""Plywood pricing: one place that decides what a measured item costs per sqft.

Material rates (Admin → Rates) are for the business's DEFAULT plywood. Each other plywood has an adjustment in ₹ per
sqft (+100, −200…). A quotation picks a plywood (the default is pre-selected) and any item can use its own. Materials
"priced on plywood" (board materials such as Acrylic, Laminates, Veneer; switchable per material) then cost
rate + adjustment; others (Glass, Wallpaper…) never change.

Price keys, used everywhere a rate is looked up (summaries, PDFs, totals):
    'Material|Work'          the material on the default plywood, or a material not priced on plywood
    'Material|Work|Plywood'  a plywood material on another plywood (its own rate in rate_map())
So quotations on the default plywood keep exactly the keys, labels and amounts they always had.

Before the database update adds the tables, nothing here touches the new columns and prices stay as they were.
"""
from flask import g, has_app_context

from . import db

NAME_MAX = 60
SEEDED_KEY = 'plywood_seeded'


def _schema():
    from . import tenancy
    return tenancy.current_schema()


_ready_forever = {}


def table_ready():
    """False until the database update that adds plywood pricing has run (checked once per request)."""
    if _ready_forever.get(_schema()):
        return True
    if has_app_context() and '_plywood_ready' in g:
        return g._plywood_ready
    from sqlalchemy import inspect
    try:
        ready = inspect(db.session.connection()).has_table('plywood_options', schema=_schema())
    except Exception:
        ready = False
    if ready:
        _ready_forever[_schema()] = True
    if has_app_context():
        g._plywood_ready = ready
    return ready


def _legacy_names():
    from .catalog import PLYWOOD_OPTIONS
    return list(PLYWOOD_OPTIONS)


def ensure_options():
    """Give a business the classic plywood list once (default: the first), all at ₹0 so no price changes.
    Called from the Rates page and the quotation form; never again after the admin edits the list."""
    from .models import AppSetting, PlywoodOption
    if not table_ready() or context()['from_db'] or AppSetting.get(SEEDED_KEY):
        return
    if not PlywoodOption.query.first():
        for i, name in enumerate(_legacy_names()):
            db.session.add(PlywoodOption(name=name, adjustment=0.0, is_default=(i == 0), active=True, sort_order=i))
    AppSetting.set(SEEDED_KEY, '1')
    db.session.commit()
    clear_cache()


def clear_cache():
    if has_app_context():
        g.pop('_plywood_ctx', None)


def context():
    """{'ready', 'options': [{'name', 'adjustment', 'cost_adjustment', 'default', 'active'}], 'default': name or None,
    'deltas': {name: ₹/sqft vs default}, 'cost_deltas': {...}, 'materials': {material names priced on plywood}}.
    Cached for the request."""
    if has_app_context() and '_plywood_ctx' in g:
        return g._plywood_ctx
    ctx = {'ready': table_ready(), 'options': [], 'default': None, 'deltas': {}, 'cost_deltas': {}, 'materials': set(),
           'material_rows': [], 'from_db': False}
    if ctx['ready']:
        from .models import AppSetting, Material, PlywoodOption
        rows = PlywoodOption.query.order_by(PlywoodOption.sort_order, PlywoodOption.id).all()
        if rows:
            default = next((r for r in rows if r.is_default), rows[0])
            base, cbase = default.adjustment or 0.0, _cost_adj(default)
            for r in rows:
                ctx['options'].append({'id': r.id, 'name': r.name, 'adjustment': round((r.adjustment or 0.0) - base, 6),
                                       'cost_adjustment': r.cost_adjustment, 'default': r is default, 'active': r.active})
                ctx['deltas'][r.name] = round((r.adjustment or 0.0) - base, 6)
                ctx['cost_deltas'][r.name] = round(_cost_adj(r) - cbase, 6)
            ctx['default'] = default.name
            ctx['from_db'] = True
        elif not AppSetting.get(SEEDED_KEY):           # not set up yet: the classic list, all at ₹0
            names = _legacy_names()
            ctx['options'] = [{'id': None, 'name': n, 'adjustment': 0.0, 'cost_adjustment': None, 'default': i == 0,
                               'active': True} for i, n in enumerate(names)]
            ctx['deltas'] = ctx['cost_deltas'] = {n: 0.0 for n in names}
            ctx['default'] = names[0] if names else None
        from . import materials as M
        if M.table_ready():
            from sqlalchemy.orm import undefer
            mats = Material.query.options(undefer(Material.uses_plywood)).all()
            ctx['materials'] = {m.name for m in mats if m.uses_plywood}
            ctx['material_rows'] = [(m.name, m.uses_work_types) for m in mats if m.uses_plywood]
    if has_app_context():
        g._plywood_ctx = ctx
    return ctx


def _cost_adj(row):
    return row.cost_adjustment if row.cost_adjustment is not None else (row.adjustment or 0.0)


def enabled():
    """True when the business has plywood options (the quotation form then asks for one)."""
    return bool(context()['options'])


def active_options():
    return [o for o in context()['options'] if o['active']]


def default_name():
    return context()['default']


def known(name):
    return any(o['name'] == name for o in context()['options'])


def clean_choice(raw):
    """A plywood name from a form: a known option, '' / unknown → None."""
    name = ' '.join((raw or '').split())[:NAME_MAX]
    return name if name and known(name) else None


def load_project(project_id):
    """Project by id (404 if missing), with its plywood loaded in the same query once the column exists."""
    from .models import Project
    q = Project.query
    if table_ready():
        from sqlalchemy.orm import undefer
        q = q.options(undefer(Project.plywood))
    return q.get_or_404(project_id)


def project_plywood(project):
    """The quotation's plywood (the default when it has none). None before the database update."""
    ctx = context()
    if not ctx['ready']:
        return None
    return project.plywood or ctx['default']


def item_plywood(item):
    """The item's own plywood, or None (= the quotation's). Never reads the column before the update."""
    if not context()['ready'] or item.is_fixed:
        return None
    return item.plywood


def key_for(wood, work, plywood_name):
    """Price key for a measured item of `wood|work` on `plywood_name` (the effective plywood)."""
    ctx = context()
    base = f'{wood}|{work or ""}'
    if (not ctx['ready'] or wood not in ctx['materials'] or not plywood_name
            or plywood_name == ctx['default'] or plywood_name not in ctx['deltas']):
        return base
    return f'{base}|{plywood_name}'


def item_key(item, project_ply=None):
    return key_for(item.wood_type, item.work_type, item_plywood(item) or project_ply or default_name())


def split_key(price_key):
    """'Material|Work|Plywood' → ('Material', 'Work', 'Plywood' or None)."""
    parts = price_key.split('|')
    wood = parts[0]
    work = parts[1] if len(parts) > 1 else ''
    return wood, work, (parts[2] if len(parts) > 2 and parts[2] else None)


def rate_map():
    """{price key: ₹ per sqft}: every material rate (default plywood), plus 'Material|Work|Plywood' for each plywood
    material on each other plywood (rate + adjustment, never below 0)."""
    from .models import ItemRate
    from .catalog import WORK_TYPES
    rates = {f'{r.wood_type}|{r.work_type}': r.rate_per_sqft for r in ItemRate.query.all()}
    ctx = context()
    others = [(n, d) for n, d in ctx['deltas'].items() if n != ctx['default']]
    for wood, uses_work in ctx['material_rows']:
        for work in (WORK_TYPES if uses_work else ['']):
            base = rates.get(f'{wood}|{work}', 0.0)
            for name, delta in others:
                rates[f'{wood}|{work}|{name}'] = round(max(base + delta, 0.0), 6)
    return rates


def cost_for(costs, price_key):
    """Cost per sqft for a price key from billing.cost_rates(): the material's cost on the default plywood, plus
    what the plywood costs extra (its cost adjustment, or the selling adjustment when not set). None = no cost."""
    wood, work, ply = split_key(price_key)
    base = costs.get(('material', f'{wood}|{work}'))
    if base is None or not ply:
        return base
    return max(base + context()['cost_deltas'].get(ply, 0.0), 0.0)


def used_on(project, rooms):
    """Plywoods this quotation uses, for the PDF: the quotation's own first, then items' own (plywood materials only).
    Before the update / without options: the old free list (plywood_thickness)."""
    ctx = context()
    if not ctx['ready'] or not ctx['options'] or (project.plywood is None and (project.plywood_thickness or '').strip()):
        return [p.strip() for p in (project.plywood_thickness or '').split(',') if p.strip()]
    main = project_plywood(project)
    names = [main] if main else []
    for room in rooms:
        for i in room.item_list:
            if not i.is_fixed and i.wood_type in ctx['materials'] and i.plywood and i.plywood not in names:
                names.append(i.plywood)
    return names


def in_use(name):
    from .models import Item, Project
    return (db.session.query(Project.id).filter(Project.plywood == name).first() is not None
            or db.session.query(Item.id).filter(Item.plywood == name).first() is not None)


def form_data():
    """What the quotation form's script needs to price items live."""
    ctx = context()
    return {'default': ctx['default'], 'materials': sorted(ctx['materials']),
            'options': [{'name': o['name'], 'delta': o['adjustment'], 'active': o['active']} for o in ctx['options']]}


def _named(price_key, project):
    """(price key with its plywood spelled out, or the plain key). Quotations with a chosen plywood always name the
    plywood of plywood materials, so changing the default plywood renames nothing; older quotations (no choice, or
    before the update) keep their plain names unless an item uses another plywood."""
    ctx = context()
    wood, work, ply = split_key(price_key)
    if ply or not ctx['ready'] or wood not in ctx['materials'] or not ctx['default'] or project is None:
        return price_key
    if project.plywood or project_plywood(project) != ctx['default']:
        return f'{wood}|{work}|{ctx["default"]}'
    return price_key


def label(price_key, project=None):
    """Summary label for a price key on `project`, e.g. 'Laminates – Box Work · 18mm BWP'."""
    from . import materials as M
    return M.label_of(_named(price_key, project))


def display_key(price_key, project=None):
    """The key a revision snapshot stores for a summary line: stable when the default plywood changes."""
    return _named(price_key, project)
