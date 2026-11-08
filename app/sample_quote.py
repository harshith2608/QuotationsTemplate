"""A ready sample quotation on a new business's first sign-in: a 2 BHK in their company's name, priced at the rates
their app starts with, shown as the customer PDF with its title page (no About us or Next steps page). They see the
end result before doing any work (and can download it), then edit it into their own.

It's a normal quotation in their list ("Sample customer"). Until they edit it, it doesn't count as their own: not in
the console's trial stages (app/activity.py) nor the setup guide's "first quotation" (app/setup_guide.py).
"""
from . import db

KEY = 'sample_project_id'
CUSTOMER = 'Sample customer'

# Rooms and items (feet; the app shows them in the business's own unit), on materials every new app has.
# (name, length, width, material, work type) for measured items; ('fit', name, quantity) for fittings.
ROOMS = [
    ('Foyer & Living Room', [('Shoe Cabinet', 4, 3.5, 'Laminates', 'Box Work'),
                             ('TV Unit', 8, 6, 'Laminates', 'Box Work'),
                             ('fit', 'Profile LED Light', 8)]),
    ('Kitchen', [('Base Cabinets', 10, 2.75, 'Acrylic', 'Box Work'),
                 ('Wall Cabinets', 10, 2.5, 'Acrylic', 'Box Work'),
                 ('Loft', 10, 2, 'Laminates', 'Box Work'),
                 ('fit', 'Tandem Drawer', 3), ('fit', 'Magic Corner', 1), ('fit', 'Pull-out Basket', 2)]),
    ('Master Bedroom', [('Wardrobe', 7, 7, 'Laminates', 'Box Work'),
                        ('Loft', 7, 2, 'Laminates', 'Box Work'),
                        ('Dressing Unit', 3, 5, 'Laminates', 'Frame Work')]),
    ('Bedroom 2', [('Wardrobe', 6, 7, 'Laminates', 'Box Work'),
                   ('Loft', 6, 2, 'Laminates', 'Box Work'),
                   ('Study Table', 4, 2.5, 'Laminates', 'Box Work')]),
]
FIT_PRICES = {'Profile LED Light': 350, 'Tandem Drawer': 4500, 'Magic Corner': 18000, 'Pull-out Basket': 3500}


def project():
    """The sample quotation, if it's still there."""
    from .models import AppSetting, Project
    pid = AppSetting.get(KEY)
    return db.session.get(Project, int(pid)) if pid and str(pid).isdigit() else None


def untouched_id():
    """The sample's id while they haven't edited it (updated_at still its created_at), else None. Asked once per
    request (the quotations list and the setup guide both ask); the setting comes with the page's settings read.
    Through the models, so a trial's own schema is used (a plain SQL string would look in public)."""
    from flask import g, has_app_context
    from sqlalchemy import select
    from .models import AppSetting, Project
    seen = g.setdefault('_sample_untouched', {}) if has_app_context() else {}
    where = g.get('tenant_slug') if has_app_context() else None          # (the console asks for many trials at once)
    if where in seen:
        return seen[where]
    found = None
    pid = AppSetting.get(KEY)
    if pid and str(pid).isdigit():
        try:
            row = db.session.execute(select(Project.created_at, Project.updated_at).where(Project.id == int(pid))).first()
        except Exception:
            db.session.rollback()                # never leave the request's transaction broken
            row = None
        found = int(pid) if row and row[0] and row[0] == row[1] else None     # (an edit changes updated_at)
    seen[where] = found
    return found


def available():
    """For businesses whose app starts with interiors materials (the sample is a 2 BHK)."""
    from . import business
    from .demo import demo_enabled
    return not demo_enabled() and business.is_interiors()


def make(user):
    """Make the sample (once) and return it."""
    from .models import AppSetting, PriceListItem, Project
    from .projects import _save_project_data
    from . import materials as M
    existing = project()
    if existing:
        return existing
    combos = {(w, k) for w, k, _ in M.combos(include_hidden=True)}
    prices = {p.name: p.price for p in PriceListItem.query.all()}
    rooms = []
    for room, items in ROOMS:
        out = []
        for it in items:
            if it[0] == 'fit':
                out.append({'name': it[1], 'type': 'fixed', 'quantity': it[2],
                            'unit_price': prices.get(it[1]) or FIT_PRICES[it[1]]})
            elif (it[3], it[4]) in combos:
                out.append({'name': it[0], 'length': it[1], 'width': it[2], 'wood_type': it[3], 'work_type': it[4]})
        rooms.append({'name': room, 'items': out})
    p = Project(customer_name=CUSTOMER, mobile='9876543210', address=(AppSetting.get('company_address') or '').strip() or None,
                created_by=user.id, grand_total=0.0)
    db.session.add(p)
    db.session.flush()
    p.grand_total = _save_project_data(p, rooms, remember=False)
    p.updated_at = p.created_at
    AppSetting.set(KEY, str(p.id))
    db.session.commit()
    return p
