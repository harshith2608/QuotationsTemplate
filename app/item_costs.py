"""Your cost on each line of a quotation (admins only): typed while making the quotation, next to the price, so the
business sees its profit as it quotes, for a firm that charges each customer differently.

Turned on per business from the console (Features → Your cost on each item), off by default. A line's own cost
(items.cost_price, encrypted like prices) replaces the cost from Admin → Costs & profit for that line; a line without
one still uses Costs & profit. Measured items: cost per area unit (stored per sqft, like rates); fittings and BOQ lines:
cost per unit. Never printed, never on the customer's link, the WhatsApp text or a revision.
Admins always see and type costs; the admin chooses which staff may too (Admin → Costs & profit, STAFF_KEY: their user
ids). Staff not allowed never see costs or profit, and a quotation they save keeps the costs already typed (matched by
section and item name).
Needs the database update that adds items.cost_price (ready()).
"""
from flask import g, has_app_context

from . import db

KEY = 'feature_item_costs'
STAFF_KEY = 'item_costs_staff'           # comma-separated user ids of staff allowed to see and type costs

_ready_forever = {}


def ready():
    """False until the database update that adds items.cost_price has run (checked once per request)."""
    from . import tenancy
    schema = tenancy.current_schema()
    if _ready_forever.get(schema):
        return True
    if has_app_context() and '_cost_ready' in g:
        return g._cost_ready
    found = _column_ready(schema)
    if found:
        _ready_forever[schema] = True
    if has_app_context():
        g._cost_ready = found
    return found


def _column_ready(schema):
    from sqlalchemy import inspect
    try:
        return 'cost_price' in {c['name'] for c in inspect(db.session.connection()).get_columns('items', schema=schema)}
    except Exception:
        return False


def enabled():
    from .models import AppSetting
    return AppSetting.get(KEY, '') == '1' and ready()


def console_status():
    """{'ready', 'on'} checked afresh (the console opens many businesses in one process)."""
    from . import tenancy
    from .models import AppSetting
    return {'ready': _column_ready(tenancy.current_schema()), 'on': AppSetting.get(KEY, '') == '1'}


def set_enabled(on):
    from .models import AppSetting
    AppSetting.set(KEY, '1' if on else '')


def staff_ids():
    """User ids of the staff the admin allows to see and type costs."""
    from .models import AppSetting
    return {int(x) for x in (AppSetting.get(STAFF_KEY, '') or '').split(',') if x.strip().isdigit()}


def set_staff(ids):
    from .models import AppSetting
    AppSetting.set(STAFF_KEY, ','.join(str(i) for i in sorted(set(ids))))


def allowed(user):
    """This user may see and type costs on lines (and see the profit): an admin, or staff the admin allowed."""
    from .models import User
    user = getattr(user, '_get_current_object', lambda: user)()
    if not isinstance(user, User) or not user.is_authenticated:     # e.g. the console's own login
        return False
    return user.is_admin or (user.id in staff_ids())


def can_edit():
    """The signed-in user may see and type costs on lines, now (database ready, and allowed)."""
    from flask import has_request_context
    from flask_login import current_user
    return has_request_context() and ready() and allowed(current_user)


def clean(raw):
    """A typed cost → a number ≥ 0, or None (empty / not a number)."""
    try:
        value = float(str(raw).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def own_costs(project):
    """{(section, item name) lower-case: cost_price} of the lines already saved, to keep them when someone who can't
    see costs saves the quotation."""
    if not ready() or project.id is None:
        return {}
    from .models import Item, Room
    rows = (db.session.query(Room.name, Item.name, Item.cost_price).join(Item, Item.room_id == Room.id)
            .filter(Room.project_id == project.id).all())
    return {(r.lower(), i.lower()): c for r, i, c in rows if c is not None}


def form_data(item_rates):
    """For the quotation form: the cost of each material / fitting from Costs & profit (the default for a line), per
    the business's area unit, and what to divide the total by to take GST out (GST-inclusive quoting)."""
    from . import billing, plywood, units
    costs = billing.cost_rates()
    materials = {}
    for key in item_rates:
        c = plywood.cost_for(costs, key)
        if c is not None:
            materials[key] = round(units.rate_value(c), 2)
    fittings = {name: c for (kind, name), c in costs.items() if kind == 'fitting'}
    settings = billing.invoice_settings()
    rate = settings['gst_rate']
    inclusive = (bool(billing.business_state_code()) and settings['with_gst']
                 and settings['prices'] == billing.PRICES_INCLUSIVE and rate)
    return {'materials': materials, 'fittings': fittings,
            'gstDivisor': (1 + rate / 100) if inclusive else 1}
