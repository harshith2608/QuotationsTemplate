"""
Single source of truth for the interior-work catalogue: materials, work types,
plywood options and the reference data seeded into a fresh database.
"""

WOOD_TYPES = ['Acrylic', 'Laminates', 'Veneer']
WORK_TYPES = ['Box Work', 'Frame Work']

DEFAULT_WOOD = 'Laminates'
DEFAULT_WORK = 'Box Work'

PLYWOOD_OPTIONS = ['18mm 8*4', '12mm 8*4', '6mm 8*4', '25mm Blackboard', '18mm Blackboard']

# Starting per-sqft rate for each material (applied to every work type).
# Admins change real rates from Admin → Rates after deployment.
DEFAULT_ITEM_RATES = {'Acrylic': 1200.0, 'Laminates': 850.0, 'Veneer': 900.0}

# Legacy per-material / per-work-type tables (still read by /api/wood-rates)
DEFAULT_WOOD_RATES = {'Acrylic': 1200.0, 'Laminates': 800.0, 'Veneer': 1500.0}
DEFAULT_WORK_TYPE_RATES = {'Box Work': 500.0, 'Frame Work': 300.0}

DEFAULT_ROOMS = [
    'Living Room', 'Master Bedroom', 'Bedroom', 'Guest Bedroom',
    'Kitchen', 'Dining Room', 'Study Room', 'Pooja Room',
    'Bathroom', 'Balcony', 'Entrance Foyer', 'Kids Room',
]

DEFAULT_ITEMS = [
    'Wardrobe', 'TV Unit', 'Kitchen Cabinet', 'Study Table',
    'Shoe Rack', 'Crockery Unit', 'False Ceiling', 'Partition',
    'Bed Box', 'Dressing Table', 'Loft', 'Overhead Cabinet',
    'Base Cabinet', 'Island Counter', 'Display Unit', 'Pooja Unit',
    'Vanity Cabinet', 'Wall Paneling', 'Headboard', 'Side Table',
]

# Quotation workflow stages, in pipeline order.
# key: (label, Bootstrap icon, text colour, background colour)
STAGES = {
    'pending':   ('Awaiting confirmation', 'hourglass-split', '#92400e', '#fef3c7'),
    'confirmed': ('Confirmed',             'check2-circle',   '#1e40af', '#dbeafe'),
    'ongoing':   ('Ongoing',               'hammer',          '#5b21b6', '#ede9fe'),
    'on_hold':   ('On hold',               'pause-circle',    '#334155', '#e2e8f0'),
    'completed': ('Completed',             'patch-check',     '#166534', '#dcfce7'),
    'cancelled': ('Cancelled',             'x-circle',        '#991b1b', '#fee2e2'),
}
DEFAULT_STAGE = 'pending'
# The main path shown as a progress stepper; on_hold / cancelled are side states
STAGE_PATH = ['pending', 'confirmed', 'ongoing', 'completed']

# Fixed-price items (fittings & accessories): priced per unit, no dimensions.
# Seeded into Admin → Rates → Price list for a new deployment; admins edit them there.
# (name, default price per unit, unit label)
DEFAULT_PRICE_LIST = [
    ('Magic Corner',               18000.0, 'piece'),
    ('Tandem Drawer',               4500.0, 'piece'),
    ('Pull-out Basket',             3500.0, 'piece'),
    ('Tall Unit Pantry Pull-out',  22000.0, 'piece'),
    ('Loft Lift-up Mechanism',      3200.0, 'piece'),
    ('Profile LED Light',            350.0, 'running ft'),
    ('Hob & Chimney Installation',  1500.0, 'job'),
]
FIXED_ITEMS_LABEL = 'Fittings & Accessories'
