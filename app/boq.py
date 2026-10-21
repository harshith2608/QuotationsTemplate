"""BOQ lines: for turnkey work priced line by line (false ceiling 696 sqft × ₹120, 71 electrical points × ₹850,
3D design ₹45,000 lump sum…).

A BOQ line is an Item of type 'boq' with its own description, quantity, unit and rate (amount = quantity × rate;
rate 0 prints no amount, for a note such as a rate card). Any item can also carry a description. The "BOQ" layout of
the Initial Quotation (Settings → Quotation PDFs) prints every line with Sr. No., Description, Qty, Unit, Rate and
Amount, sections A, B, C… being the quotation's rooms.

Off by default; turned on per business from the console (trial or customer page). Needs the database update that
adds items.description and items.unit (ready()).
"""
from flask import g, has_app_context

from . import db

KEY = 'feature_boq'
UNITS = ['sqft', 'rft', 'nos', 'point', 'sq m', 'rmt', 'set', 'lump sum']
LUMP_SUM = 'lump sum'
DESCRIPTION_MAX = 2000
UNIT_MAX = 20

_ready_forever = {}


def ready():
    """False until the database update that adds items.description and items.unit has run (checked once per
    request, then remembered)."""
    from . import tenancy
    schema = tenancy.current_schema()
    if _ready_forever.get(schema):
        return True
    if has_app_context() and '_boq_ready' in g:
        return g._boq_ready
    found = _columns_ready(schema)
    if found:
        _ready_forever[schema] = True
    if has_app_context():
        g._boq_ready = found
    return found


def _columns_ready(schema):
    """items.description and items.unit, and the boq_items table, exist (the database update has run)."""
    from sqlalchemy import inspect
    try:
        insp = inspect(db.session.connection())
        cols = {c['name'] for c in insp.get_columns('items', schema=schema)}
        return {'description', 'unit'} <= cols and insp.has_table('boq_items', schema=schema)
    except Exception:
        return False


def enabled():
    """BOQ lines are on for this business (and its database is ready for them)."""
    from .models import AppSetting
    return AppSetting.get(KEY, '') == '1' and ready()


def set_enabled(on):
    from .models import AppSetting
    AppSetting.set(KEY, '1' if on else '')


def console_status():
    """{'ready', 'on'} for the console, checked afresh (the console opens many businesses' databases in one process,
    so the per-schema memory in ready() can't be trusted there)."""
    from . import tenancy
    from .models import AppSetting
    return {'ready': _columns_ready(tenancy.current_schema()), 'on': AppSetting.get(KEY, '') == '1'}


def clean_unit(value):
    """'Sq.ft' → 'sqft', 'Nos.' → 'nos', 'LS' → 'lump sum'; anything else as typed (short)."""
    v = ' '.join(str(value or '').split())[:UNIT_MAX]
    key = v.lower().replace('.', '').replace(' ', '')
    aliases = {'sqft': 'sqft', 'sft': 'sqft', 'squarefeet': 'sqft', 'rft': 'rft', 'runningft': 'rft', 'rf': 'rft',
               'nos': 'nos', 'no': 'nos', 'numbers': 'nos', 'pcs': 'nos', 'piece': 'nos', 'pieces': 'nos',
               'point': 'point', 'points': 'point', 'pt': 'point', 'sqm': 'sq m', 'rmt': 'rmt', 'set': 'set',
               'ls': LUMP_SUM, 'lumpsum': LUMP_SUM, 'lumsum': LUMP_SUM, 'job': LUMP_SUM}
    return aliases.get(key, v) or 'nos'


def clean_description(value):
    lines = [' '.join(line.split()) for line in str(value or '').splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return '\n'.join(lines)[:DESCRIPTION_MAX] or None


def unit_text(unit):
    """How a unit is printed in a BOQ: 'Sq.ft', 'R.ft', 'Nos.', 'Point', 'LS'…"""
    return {'sqft': 'Sq.ft', 'rft': 'R.ft', 'nos': 'Nos.', 'point': 'Point', 'sq m': 'Sq.m', 'rmt': 'Rmt',
            'set': 'Set', LUMP_SUM: 'LS'}.get(unit or '', unit or '')


def qty_text(quantity):
    return f'{quantity:,.2f}'.rstrip('0').rstrip('.') if quantity else '—'


# ── Saved BOQ lines (Admin → Rates → BOQ lines) ──────────────────────────────

def saved_lines():
    """[{name, description, unit, rate}] for the quotation form, by name."""
    from .models import BoqItem
    return [{'name': b.name, 'description': b.description or '', 'unit': b.unit or 'nos', 'rate': b.rate or 0}
            for b in BoqItem.query.order_by(BoqItem.name).all()]


def remember(lines):
    """After a quotation is saved: a BOQ line used for the first time is saved with its description, unit and rate;
    one already saved keeps its defaults unless the line asked to update them ("Save as my default").
    lines: [(name, description, unit, rate, save_default)]."""
    from sqlalchemy import func
    from .models import BoqItem
    done = set()
    for name, description, unit, rate, save_default in lines:
        key = name.strip().lower()
        if not key or key in done:
            continue
        done.add(key)
        row = BoqItem.query.filter(func.lower(BoqItem.name) == key).first()
        if row is None:
            db.session.add(BoqItem(name=name.strip()[:100], description=description, unit=unit, rate=rate))
        elif save_default:
            row.description, row.unit, row.rate = description, unit, rate
