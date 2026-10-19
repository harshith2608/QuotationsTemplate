"""Materials catalogue (per business) and the combo keys used everywhere: 'Material|Work Type', or 'Glass|' for
materials priced with one rate per sqft (no work type)."""
from . import db
from .catalog import DEFAULT_WOOD, DEFAULT_WORK, WOOD_TYPES, WORK_TYPES

NAME_MAX = 60


def label(wood, work):
    return f'{wood} – {work}' if work else (wood or '')


def key(wood, work):
    return f'{wood}|{work or ""}'


class _Legacy:
    """Stand-in while the database hasn't had the materials update yet: the three classic materials."""
    def __init__(self, name, i):
        self.id, self.name, self.uses_work_types, self.active, self.sort_order = None, name, True, True, i


def table_ready():
    """False until the database update that adds the materials table has run (e.g. right after a deploy).
    Checked once per request; once the table exists it stays True for the life of the process."""
    global _ready_forever
    if _ready_forever.get(_schema()):
        return True
    from flask import g, has_app_context
    if has_app_context() and '_materials_ready' in g:
        return g._materials_ready
    from sqlalchemy import inspect
    try:
        # The session's own connection: no second connection (and no waiting on this request's transaction)
        ready = inspect(db.session.connection()).has_table('materials', schema=_schema())
    except Exception:
        ready = False
    if ready:
        _ready_forever[_schema()] = True
    if has_app_context():
        g._materials_ready = ready
    return ready


_ready_forever = {}


def _schema():
    from . import tenancy
    return tenancy.current_schema()                      # trials live in their own schema


def _materials(include_hidden):
    from .models import Material
    if not table_ready():
        return [_Legacy(n, i) for i, n in enumerate(WOOD_TYPES)]
    q = Material.query
    if not include_hidden:
        q = q.filter_by(active=True)
    return q.order_by(Material.sort_order, Material.id).all()


def combos(include_hidden=False):
    """[(wood, work, label)] in display order."""
    out = []
    for m in _materials(include_hidden):
        if m.uses_work_types:
            out += [(m.name, w, label(m.name, w)) for w in WORK_TYPES]
        else:
            out.append((m.name, '', m.name))
    return out


def is_valid(wood, work):
    return any(w == wood and k == (work or '') for w, k, _ in combos(include_hidden=True))


def default_combo(active=None):
    """'Material|Work' preselected for new items: the usual default if available, else the first one.
    `active`: combos() if already worked out."""
    active = combos() if active is None else active
    for w, k, _ in active:
        if w == DEFAULT_WOOD and k == DEFAULT_WORK:
            return w, k
    return (active[0][0], active[0][1]) if active else (DEFAULT_WOOD, DEFAULT_WORK)


def form_catalog(extra=()):
    """What the quotation form needs: active combos, plus any `extra` (wood, work) already used on this quotation
    (e.g. a material hidden since), so editing an old quotation never loses its material."""
    active = combos()
    rows = [{'value': key(w, k), 'label': l, 'wood': w, 'work': k} for w, k, l in active]
    known = {r['value'] for r in rows}
    for w, k in extra:
        if key(w, k) not in known and w:
            rows.append({'value': key(w, k), 'label': label(w, k) + ' (hidden)', 'wood': w, 'work': k or ''})
            known.add(key(w, k))
    dw, dk = default_combo(active)
    return {'material_combos': rows, 'default_combo': key(dw, dk)}


def clean_name(raw):
    name = ' '.join((raw or '').split())[:NAME_MAX]
    if '|' in name:
        raise ValueError('A material name can\'t contain "|".')
    if len(name) < 2:
        raise ValueError('Give the material a name (at least 2 characters).')
    return name


def in_use(name):
    from .models import Item
    if not table_ready():
        return True
    return db.session.query(Item.id).filter(Item.wood_type == name).first() is not None


def names_in_use():
    """Every material name used on some item, in one query (Admin → Rates), or None before the database update."""
    from .models import Item
    if not table_ready():
        return None
    return {n for (n,) in db.session.query(Item.wood_type).distinct()}


def ordered_keys(totals):
    """Price keys of `totals` ({'Material|Work' or 'Material|Work|Plywood': area}) in catalogue order, each
    material's plywood variants right after it; unknown ones last."""
    order = {key(w, k): i for i, (w, k, _) in enumerate(combos(include_hidden=True))}

    def rank(k):
        wood, work, *ply = k.split('|')
        base = key(wood, work)
        return (order.get(base, len(order)), base if base not in order else '', 1 if ply and ply[0] else 0, k)
    return sorted(totals, key=rank)


def finish_label_of(combo_key):
    """For the Full Quotation's items: 'Acrylic|Box Work' → 'Acrylic Finish', with a plywood 'Acrylic Finish · 18mm BWP';
    a material without work types keeps its name ('Glass')."""
    wood, work, *ply = combo_key.split('|')
    text = f'{wood} Finish' if work else wood
    return f'{text} · {ply[0]}' if ply and ply[0] else text


def label_of(combo_key):
    """'Laminates|Box Work' → 'Laminates – Box Work'; with a plywood: 'Laminates – Box Work · 18mm BWP'."""
    wood, work, *ply = combo_key.split('|')
    text = label(wood, work)
    return f'{text} · {ply[0]}' if ply and ply[0] else text
