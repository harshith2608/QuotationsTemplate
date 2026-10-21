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
# Units whose quantity can come from a size: area (length × width × No's) and running length (length × No's).
# Values: the unit per square foot / per foot (sizes are kept in feet, like every size in the app).
AREA_UNITS = {'sqft': 1.0, 'sq m': 0.09290304}
LENGTH_UNITS = {'rft': 1.0, 'rmt': 0.3048}
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
    """Turn BOQ lines on or off; turning on gives a business with no saved lines the starter set."""
    from . import tenancy
    from .models import AppSetting
    AppSetting.set(KEY, '1' if on else '')
    if on and _columns_ready(tenancy.current_schema()):
        add_starter_lines()


def console_status():
    """{'ready', 'on'} for the console, checked afresh (the console opens many businesses' databases in one process,
    so the per-schema memory in ready() can't be trusted there)."""
    from . import tenancy
    from .models import AppSetting
    return {'ready': _columns_ready(tenancy.current_schema()), 'on': AppSetting.get(KEY, '') == '1'}


def units_for_business():
    """The unit list with the business's own area and running-length units first (Settings → Units)."""
    from . import units
    first = ['sq m', 'rmt'] if units.area_unit() == 'sqm' else ['sqft', 'rft']
    return first + [u for u in UNITS if u not in first]


def size_mode(unit):
    """'area' (length × width), 'length' (running length) or None (a count, a point, a lump sum…)."""
    return 'area' if unit in AREA_UNITS else 'length' if unit in LENGTH_UNITS else None


def quantity_from_size(unit, length, width, count=1):
    """The quantity in `unit` for a size in feet, e.g. 14 ft × 12 ft → 168 sqft (15.61 sq m); 12 ft → 12 rft."""
    count = max(int(count or 1), 1)
    if unit in AREA_UNITS:
        return round(length * width * count * AREA_UNITS[unit], 2)
    if unit in LENGTH_UNITS:
        return round(length * count * LENGTH_UNITS[unit], 2)
    return None


def size_text(item):
    """'14 ft × 12 ft × 2 No's' (area) or '12 ft × 4 No's' (running length) in the business's size unit, or ''."""
    from . import units
    length, width = item.get('length') or 0, item.get('width') or 0
    if not length:
        return ''
    text = units.length(length) + (f' × {units.length(width)}' if width else '')
    count = item.get('count') or 1
    return text + (f" × {count} No's" if count > 1 else '')


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
    return [{'name': b.name, 'description': b.description or '', 'unit': b.unit or 'nos', 'rate': b.rate or 0,
             'category': b.category or 'Other'}
            for b in BoqItem.query.order_by(BoqItem.id).all()]             # groups in the order they were added


def remember(lines):
    """After a quotation is saved: a BOQ line used for the first time is saved with its description, unit and rate;
    one already saved keeps its defaults unless the line asked to update them ("Save as my default").
    lines: [(name, description, unit, rate, save_default, category)] — category: the section it was used in."""
    from sqlalchemy import func
    from .models import BoqItem
    done = set()
    for name, description, unit, rate, save_default, category in lines:
        key = name.strip().lower()
        if not key or key in done:
            continue
        done.add(key)
        row = BoqItem.query.filter(func.lower(BoqItem.name) == key).first()
        if row is None:
            db.session.add(BoqItem(name=name.strip()[:100], description=description, unit=unit, rate=rate,
                                   category=(category or '').strip()[:60] or None))
        elif save_default:
            row.description, row.unit, row.rate = description, unit, rate


# Starter lines, from typical turnkey 2 BHK quotations: offered when BOQ lines are turned on for a business with none
# saved yet. Rates are examples to change (Admin → Rates → BOQ lines).
STARTER = [
    ('#', 'Services'),
    ('False Ceiling', 'sqft', 120, 'Gypsum false ceiling with framework, as per design (living room, kitchen, passage, bedrooms)'),
    ('Electric Wiring', 'point', 850, 'Conduit, Polycab wire (1.5 sq.mm considered); excluding switches, sockets & plates'),
    ('Paint Work', 'sqft', 45, 'Royale Luxury Emulsion / Asian Royale on all indoor walls, with putty, primer and 2 coats of colour'),
    ('3D Design', LUMP_SUM, 45000, '3D design for reference (living room, kitchen & bedrooms), one revision, 10-12 views'),
    ('Floor Protection', LUMP_SUM, 7500, 'Floor protection sheet on all areas during work'),
    ('Debris Removal and Deep Cleaning', LUMP_SUM, 22000, 'Debris removal\nDeep cleaning with machine'),
    ('Door Laminate Change', 'nos', 12000, 'Removing and pasting laminate on both sides (single laminate); same hardware'),
    ('Door Frame Paneling', 'nos', 12500, 'Door frame paneling with laminate finish'),
    ('Laminate Variation Cost', LUMP_SUM, 25000, 'Approximate, for the laminates finally selected'),
    ('#', 'Electrical Fitting'),
    ('Fan Fitting', 'nos', 500, 'Fan fitting including bracket'),
    ('Exhaust Fan Fixing', 'nos', 350, ''),
    ('Switch Board Shifting', 'nos', 350, ''),
    ('New Switch Board', 'nos', 850, ''),
    ('Switch Board Replacement', 'nos', 500, 'Removing old switch board and fitting new'),
    ('Profile Light Fitting', 'rft', 100, ''),
    ('Cove Light Fitting', 'rft', 75, ''),
    ('COB Light Fitting', 'nos', 150, ''),
    ('Hanging Light Fitting', 'nos', 250, 'Hanging lights as per design and selection, priced separately'),
    ('#', 'Lights & Points'),
    ('COB Light 12 W', 'nos', 420, '3 inch'),
    ('Panel Light 15 W', 'nos', 500, '3-in-1'),
    ('Profile Light 17 mm', 'rft', 550, ''),
    ('Profile Light 35 mm', 'rft', 850, ''),
    ('Strip Light', 'rft', 150, ''),
    ('Wardrobe / Cabinet Profile Light', 'rft', 550, 'Micro switch Rs 700 extra'),
    ('Laser Light', 'nos', 900, '5 nos with 3 W LED each'),
    ('Switch / Socket Point', 'point', 1150, 'With switch or socket (GM base level switches and plates)'),
    ('Point Looping', 'point', 550, 'With material'),
    ('#', 'Living Room & Passage'),
    ('Safety Door', 'sqft', 1500, 'Safety door in block board, both sides laminate finish, including safety grill '
     '(lock, handle and grill at base price)'),
    ('Safety Door Paneling', 'sqft', 850, 'Safety door paneling in 12 mm ply with laminate finish'),
    ('Shoe Rack', 'sqft', 1950, 'Shoe rack in 18 mm BWR ply, laminate finish inside and outside, with all hardware'),
    ('TV Unit', 'sqft', 1450, 'TV unit in BWR ply with drawers and ply paneling'),
    ('AC Paneling', 'sqft', 750, 'AC paneling in 12 mm BWR ply + 4 mm HDMR'),
    ('Wall Paneling', 'sqft', 950, 'Wall paneling with fluted sheet / mirror / metal strips as per design'),
    ('Loft Shutter', 'sqft', 950, 'Loft shutters in BWR ply with laminate finish'),
    ('Sofa', 'nos', 55000, 'Fabric cost extra as per selection'),
    ('#', 'Kitchen'),
    ('Kitchen Below Platform', 'sqft', 2450, 'Below-platform units in BWP ply with laminate finish, tandem drawers, '
     'masala pull-out and profile handles'),
    ('Kitchen Above Platform', 'sqft', 1850, 'Middle and upper units in BWR ply, laminate finish inside and outside, '
     'with shelves'),
    ('Kitchen Balcony Storage', 'sqft', 1750, 'Balcony storage in BWP ply with laminate finish'),
    ('#', 'Bathrooms'),
    ('LED Mirror', 'nos', 9500, 'Bathroom LED mirror with single light'),
    ('Vanity Storage', 'sqft', 2100, 'Below-counter vanity storage in BWP ply with laminate finish'),
    ('Bathroom PVC Ceiling', 'sqft', 500, 'PVC ceiling in bathroom'),
    ('#', 'Bedrooms'),
    ('Wardrobe', 'sqft', 1850, 'Wardrobe in BWR ply, laminate finish inside and outside, soft-close drawer channels, '
     'shutters, drawers and shelves'),
    ('Bed with Storage', 'sqft', 1850, 'Bed in 18 mm BWR ply, laminate finish, top-open storage on hydraulic fittings'),
    ('Designer Headboard', 'sqft', 1250, 'Headboard in 12 mm BWR ply with cushioning'),
    ('Side Table', 'nos', 15000, 'Side table in BWR ply with laminate finish, 2 drawers'),
    ('Dresser Unit', 'sqft', 1650, 'Dresser in BWR ply, laminate finish, soft-close drawers and mirror'),
    ('Mirror (Miralite 5 mm)', 'sqft', 320, 'Saint-Gobain 5 mm silver mirror (Miralite), non-toughened'),
]


def starter_lines():
    """[(category, name, unit, rate, description)] from STARTER (its ('#', category) rows start a group)."""
    out, cat = [], 'Other'
    for row in STARTER:
        if row[0] == '#':
            cat = row[1]
            continue
        out.append((cat,) + tuple(row))
    return out


def add_starter_lines():
    """Give a business with no saved BOQ lines the starter set. Returns how many were added."""
    from .models import BoqItem
    if BoqItem.query.first() is not None:
        return 0
    lines = starter_lines()
    for category, name, unit, rate, description in lines:
        db.session.add(BoqItem(name=name, unit=unit, rate=rate, description=description, category=category))
    return len(lines)
