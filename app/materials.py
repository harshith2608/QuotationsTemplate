"""Materials catalogue (per business) and the combo keys used everywhere: 'Material|Work Type', or 'Glass|' for
materials priced with one rate per sqft (no work type)."""
from . import db
from .catalog import DEFAULT_WOOD, DEFAULT_WORK, WORK_TYPES

NAME_MAX = 60


def label(wood, work):
    return f'{wood} – {work}' if work else (wood or '')


def key(wood, work):
    return f'{wood}|{work or ""}'


def _materials(include_hidden):
    from .models import Material
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


def default_combo():
    """'Material|Work' preselected for new items: the usual default if available, else the first one."""
    active = combos()
    for w, k, _ in active:
        if w == DEFAULT_WOOD and k == DEFAULT_WORK:
            return w, k
    return (active[0][0], active[0][1]) if active else (DEFAULT_WOOD, DEFAULT_WORK)


def form_catalog(extra=()):
    """What the quotation form needs: active combos, plus any `extra` (wood, work) already used on this quotation
    (e.g. a material hidden since), so editing an old quotation never loses its material."""
    rows = [{'value': key(w, k), 'label': l, 'wood': w, 'work': k} for w, k, l in combos()]
    known = {r['value'] for r in rows}
    for w, k in extra:
        if key(w, k) not in known and w:
            rows.append({'value': key(w, k), 'label': label(w, k) + ' (hidden)', 'wood': w, 'work': k or ''})
            known.add(key(w, k))
    dw, dk = default_combo()
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
    return db.session.query(Item.id).filter(Item.wood_type == name).first() is not None


def ordered_keys(totals):
    """Combo keys of `totals` ({'Material|Work': area}) in catalogue order, unknown ones last."""
    keys = [key(w, k) for w, k, _ in combos(include_hidden=True)]
    return [k for k in keys if k in totals] + [k for k in totals if k not in keys]


def label_of(combo_key):
    wood, _, work = combo_key.partition('|')
    return label(wood, work)
