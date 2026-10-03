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
