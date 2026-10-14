"""
Database seeding.

bootstrap()  — idempotent setup for a fresh deployment: first admin user
               (from ADMIN_USERNAME / ADMIN_PASSWORD) and reference data
               (rates, room names, item names). Safe to run on every deploy.

seed_demo()  — fills the database with fictional "Demo Interiors" data for
               demos and local development. All names, numbers and addresses
               are made up.
"""
import os
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from . import db, catalog
from .models import (User, Project, ProjectAccess, Payment, AppSetting, WoodRate,
                     WorkTypeRate, ItemRate, MasterRoom, MasterItem, ProjectStageChange,
                     PriceListItem, Material)


class SeedError(Exception):
    pass


def _hash(password):
    return generate_password_hash(password, method='pbkdf2:sha256')


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def seed_reference_data():
    """Insert default rates, rooms and items into empty tables. Returns list of what was seeded."""
    seeded = []
    if not WoodRate.query.first():
        db.session.add_all(WoodRate(wood_type=w, rate_per_sqft=r)
                           for w, r in catalog.DEFAULT_WOOD_RATES.items())
        seeded.append('wood rates')
    if not WorkTypeRate.query.first():
        db.session.add_all(WorkTypeRate(work_type=w, rate_per_sqft=r)
                           for w, r in catalog.DEFAULT_WORK_TYPE_RATES.items())
        seeded.append('work type rates')
    from .materials import table_ready
    fresh_rates = not ItemRate.query.first()
    if table_ready() and not Material.query.first():
        db.session.add_all(Material(name=n, uses_work_types=w, active=True, sort_order=i)
                           for i, (n, w, _) in enumerate(catalog.DEFAULT_MATERIALS))
        seeded.append('materials')
    if fresh_rates:
        rows = []
        for name, uses_work, rate in catalog.DEFAULT_MATERIALS:
            for work in (catalog.WORK_TYPES if uses_work else ['']):
                rows.append(ItemRate(wood_type=name, work_type=work, rate_per_sqft=rate))
        db.session.add_all(rows)
        seeded.append('item rates')
    if not MasterRoom.query.first():
        db.session.add_all(MasterRoom(name=n) for n in catalog.DEFAULT_ROOMS)
        seeded.append('room names')
    if not MasterItem.query.first():
        db.session.add_all(MasterItem(name=n) for n in catalog.DEFAULT_ITEMS)
        seeded.append('item names')
    if not PriceListItem.query.first():
        db.session.add_all(PriceListItem(name=n, price=p, unit=u) for n, p, u in catalog.DEFAULT_PRICE_LIST)
        seeded.append('fittings price list')
    db.session.commit()
    return seeded


def bootstrap(username=None, password=None):
    """Create the first admin (if none) and seed reference data. Returns a list of log lines."""
    log = []
    if not User.query.filter_by(role='admin').first():
        username = (username or os.environ.get('ADMIN_USERNAME') or 'admin').strip()
        password = password or os.environ.get('ADMIN_PASSWORD') or ''
        if len(password) < 8:
            raise SeedError('No admin user exists. Set ADMIN_PASSWORD (min 8 characters) '
                            'and optionally ADMIN_USERNAME, then run this again.')
        db.session.add(User(username=username, password_hash=_hash(password), role='admin'))
        db.session.commit()
        log.append(f'Created admin user "{username}".')
    else:
        log.append('Admin user already exists — skipped.')

    seeded = seed_reference_data()
    log.append(f'Seeded: {", ".join(seeded)}.' if seeded else 'Reference data already present — skipped.')
    log.append(encrypt_existing_data())
    return log


def encrypt_existing_data():
    """Encrypt any data still stored in plain text (after upgrading an older database). Returns a log line."""
    from . import crypto
    if not crypto.enabled():
        return f'Encryption: {crypto.ENV} not set — data is stored unencrypted (fine for local development only).'
    changed = crypto.encrypt_existing(db.session, db.metadata, AppSetting.ENCRYPTED_KEYS)
    db.session.commit()
    if not changed:
        return 'Encryption: all data already encrypted.'
    return 'Encryption: encrypted rows in ' + ', '.join(f'{t} ({n})' for t, n in changed.items()) + '.'


# ── Demo data ─────────────────────────────────────────────────────────────────

DEMO_SETTINGS = {
    'company_name':    'Demo Interiors',
    'company_address': '42, Sample Street, Demo Nagar\nBengaluru - 560001',
    'company_mobile':  '+91 90000 00000',
    'company_email':   'hello@demo-interiors.example',
    'company_gstin':   '29ABCDE1234F1Z5',
    'upi_id':          'demo-interiors@example',
    'bank_name':       'Example Bank',
    'account_name':    'Demo Interiors',
    'account_number':  '000012345678',
    'ifsc_code':       'EXMP0000001',
    'material_specs':  '● Plywood: BWR grade, 18mm carcass\n'
                       '● Hardware: soft-close hinges and telescopic channels\n'
                       '● Edge banding: 2mm PVC, matched to laminate',
}

DEMO_USERS = [
    # username, full name, role
    ('demo-admin', 'Asha Demo',   'admin'),
    ('demo-staff', 'Ravi Sample', 'employee'),
]

# customer, mobile, email, address, created_by, days_ago, discount, rooms, payments
# rooms: [(room_name, [(item, length_ft, width_ft, wood, work), ...]), ...]
DEMO_PROJECTS = [
    ('Priya Example', '9000000001', 'priya@example.com', 'Flat 101, Example Residency, Bengaluru',
     'demo-staff', 2, ('percentage', 5),
     [('Master Bedroom', [('Wardrobe', 8, 7, 'Laminates', 'Box Work'),
                          ('Loft', 8, 2, 'Laminates', 'Box Work'),
                          ('Dressing Table', 3, 6, 'Acrylic', 'Frame Work')]),
      ('Kitchen', [('Base Cabinet', 10, 2.75, 'Acrylic', 'Box Work'),
                   ('Overhead Cabinet', 10, 2.5, 'Acrylic', 'Box Work'),
                   ('Magic Corner', 'fixed', 1, 18000),
                   ('Tandem Drawer', 'fixed', 4, 4500)])],
     [(50000, 'Advance payment')]),
    ('Rahul Sample', '9000000002', 'rahul@example.com', 'Villa 7, Placeholder Gardens, Bengaluru',
     'demo-admin', 9, ('none', 0),
     [('Living Room', [('TV Unit', 9, 7, 'Veneer', 'Frame Work'),
                       ('Wall Paneling', 12, 9, 'Veneer', 'Frame Work')]),
      ('Pooja Room', [('Pooja Unit', 4, 6, 'Veneer', 'Box Work')])],
     [(75000, 'Advance via UPI'), (40000, 'Second instalment')]),
    ('Meera Test', '9000000003', 'meera@example.com', '',
     'demo-staff', 15, ('fixed', 10000),
     [('Kids Room', [('Study Table', 4, 2.5, 'Laminates', 'Frame Work'),
                     ('Wardrobe', 6, 7, 'Laminates', 'Box Work'),
                     ('Bed Box', 6.5, 5, 'Laminates', 'Box Work')])],
     []),
    ('Arjun Placeholder', '9000000004', 'arjun@example.com', 'House 12, Test Layout, Mysuru',
     'demo-staff', 24, ('none', 0),
     [('Entrance Foyer', [('Shoe Rack', 4, 3.5, 'Laminates', 'Box Work')]),
      ('Dining Room', [('Crockery Unit', 5, 7, 'Acrylic', 'Frame Work')]),
      ('Guest Bedroom', [('Wardrobe', 6, 7, 'Laminates', 'Box Work'),
                         ('Headboard', 6, 3.5, 'Veneer', 'Frame Work')])],
     [(30000, 'Token advance')]),
    ('Kavya Demo', '9000000005', None, 'Apt 5B, Mock Towers, Bengaluru',
     'demo-admin', 40, ('none', 0),
     [('Study Room', [('Study Table', 5, 2.5, 'Veneer', 'Box Work'),
                      ('Display Unit', 4, 6, 'Acrylic', 'Frame Work')]),
      ('Bathroom', [('Vanity Cabinet', 3, 2.5, 'Acrylic', 'Box Work')])],
     [(20000, 'Advance'), (29050, 'Balance — fully settled')]),
]

PLYWOOD_BY_PROJECT = ['18mm 8*4,12mm 8*4', '18mm 8*4,25mm Blackboard', '18mm 8*4', '', '12mm 8*4,6mm 8*4']

# Stage history per demo project: (stage, days after the quotation was created, note)
STAGE_FLOW_BY_PROJECT = [
    [('confirmed', 1, 'Advance received')],
    [('confirmed', 1, None), ('ongoing', 3, 'Site work started')],
    [],
    [('confirmed', 2, 'Token advance paid'), ('on_hold', 10, 'Customer travelling, resume next month')],
    [('confirmed', 1, None), ('ongoing', 5, None), ('completed', 30, 'Handed over to customer')],
]


# Real data that lives in the marketing/demo database and must survive the nightly demo reset
KEEP_ON_RESET = {'leads', 'demo_stats'}


def _clear_all_tables():
    """Delete every row from every app table except KEEP_ON_RESET (keeps the schema and alembic_version)."""
    for table in reversed(db.metadata.sorted_tables):
        if table.name not in KEEP_ON_RESET:
            db.session.execute(table.delete())
    db.session.commit()


def seed_demo(reset=False, password=None):
    """Populate the database with Demo Interiors data. Returns a list of log lines."""
    from .projects import _save_project_data  # imported here to avoid a circular import

    if Project.query.first() or User.query.first():
        if not reset:
            raise SeedError('Database already has data. Re-run with --reset to wipe it '
                            'and load the demo data (this deletes everything).')
        _clear_all_tables()

    password = password or os.environ.get('DEMO_PASSWORD') or 'demo1234'
    log = []

    seed_reference_data()
    for key, value in DEMO_SETTINGS.items():
        AppSetting.set(key, value)

    users = {}
    for username, full_name, role in DEMO_USERS:
        u = User(username=username, full_name=full_name, role=role, password_hash=_hash(password))
        db.session.add(u)
        users[username] = u
    db.session.flush()
    log.append(f'Users: {", ".join(users)} (password: {password})')

    now = datetime.utcnow()
    for idx, (customer, mobile, email, address, creator, days_ago,
              (disc_type, disc_value), rooms, payments) in enumerate(DEMO_PROJECTS):
        created = now - timedelta(days=days_ago)
        project = Project(customer_name=customer, mobile=mobile, email=email,
                          address=address or None, created_by=users[creator].id,
                          discount_type=disc_type, discount_value=disc_value,
                          plywood_thickness=PLYWOOD_BY_PROJECT[idx],
                          status='complete', created_at=created, updated_at=created)
        db.session.add(project)
        db.session.flush()

        def _item(row):
            if len(row) == 4 and row[1] == 'fixed':          # (name, 'fixed', quantity, unit price)
                return {'type': 'fixed', 'name': row[0], 'quantity': row[2], 'unit_price': row[3]}
            n, l, w, wood, work = row
            return {'name': n, 'length': l, 'width': w, 'wood_type': wood, 'work_type': work}
        rooms_data = [{'name': room, 'items': [_item(r) for r in items]} for room, items in rooms]
        project.grand_total = _save_project_data(project, rooms_data)

        if not users[creator].is_admin:
            db.session.add(ProjectAccess(project_id=project.id, user_id=users[creator].id,
                                         granted_by=users[creator].id))
        current = project.stage
        for to_stage, days_after, note in STAGE_FLOW_BY_PROJECT[idx]:
            when = created + timedelta(days=days_after)
            db.session.add(ProjectStageChange(project_id=project.id, from_stage=current, to_stage=to_stage,
                                              changed_by=users['demo-admin'].id, changed_at=when, note=note))
            current = to_stage
            project.stage, project.stage_changed_at = to_stage, when
        for p_idx, (amount, note) in enumerate(payments):
            db.session.add(Payment(project_id=project.id, amount=amount, note=note,
                                   recorded_by=users['demo-admin'].id, source='manual',
                                   recorded_at=created + timedelta(days=p_idx + 1)))

    db.session.commit()
    log.append(f'Projects: {len(DEMO_PROJECTS)} quotations with rooms, items, payments and stage history.')
    log.append('Company settings: Demo Interiors (fictional address, GSTIN, UPI and bank details).')
    return log
