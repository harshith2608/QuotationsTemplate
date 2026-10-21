"""boq_items: remove the woodwork starter lines (wardrobes, kitchen units, beds…) that nobody changed

Woodwork is priced by material as measured items; the starter BOQ lines now cover services, electrical fitting and
lights only. Businesses that already turned BOQ lines on got woodwork starter lines too: those still exactly as the
starter set made them (same name, unit, group and description) are removed. Lines a business edited or added stay.
Quotations keep their own copy of every line, so none changes. The rate isn't compared (it's stored encrypted).

Revision ID: b8d4f0a6c2e3
Revises: a7c3e9b5d1f2
Create Date: 2026-10-22 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b8d4f0a6c2e3'
down_revision = 'a7c3e9b5d1f2'
branch_labels = None
depends_on = None

# (group, name, unit, description) as the starter set added them
WOODWORK = [
    ('Living Room & Passage', 'Safety Door', 'sqft', 'Safety door in block board, both sides laminate finish, including safety grill (lock, handle and grill at base price)'),
    ('Living Room & Passage', 'Safety Door Paneling', 'sqft', 'Safety door paneling in 12 mm ply with laminate finish'),
    ('Living Room & Passage', 'Shoe Rack', 'sqft', 'Shoe rack in 18 mm BWR ply, laminate finish inside and outside, with all hardware'),
    ('Living Room & Passage', 'TV Unit', 'sqft', 'TV unit in BWR ply with drawers and ply paneling'),
    ('Living Room & Passage', 'AC Paneling', 'sqft', 'AC paneling in 12 mm BWR ply + 4 mm HDMR'),
    ('Living Room & Passage', 'Wall Paneling', 'sqft', 'Wall paneling with fluted sheet / mirror / metal strips as per design'),
    ('Living Room & Passage', 'Loft Shutter', 'sqft', 'Loft shutters in BWR ply with laminate finish'),
    ('Living Room & Passage', 'Sofa', 'nos', 'Fabric cost extra as per selection'),
    ('Kitchen', 'Kitchen Below Platform', 'sqft', 'Below-platform units in BWP ply with laminate finish, tandem drawers, masala pull-out and profile handles'),
    ('Kitchen', 'Kitchen Above Platform', 'sqft', 'Middle and upper units in BWR ply, laminate finish inside and outside, with shelves'),
    ('Kitchen', 'Kitchen Balcony Storage', 'sqft', 'Balcony storage in BWP ply with laminate finish'),
    ('Bathrooms', 'Vanity Storage', 'sqft', 'Below-counter vanity storage in BWP ply with laminate finish'),
    ('Bedrooms', 'Wardrobe', 'sqft', 'Wardrobe in BWR ply, laminate finish inside and outside, soft-close drawer channels, shutters, drawers and shelves'),
    ('Bedrooms', 'Bed with Storage', 'sqft', 'Bed in 18 mm BWR ply, laminate finish, top-open storage on hydraulic fittings'),
    ('Bedrooms', 'Designer Headboard', 'sqft', 'Headboard in 12 mm BWR ply with cushioning'),
    ('Bedrooms', 'Side Table', 'nos', 'Side table in BWR ply with laminate finish, 2 drawers'),
    ('Bedrooms', 'Dresser Unit', 'sqft', 'Dresser in BWR ply, laminate finish, soft-close drawers and mirror'),
    ('Bedrooms', 'Mirror (Miralite 5 mm)', 'sqft', 'Saint-Gobain 5 mm silver mirror (Miralite), non-toughened'),
]


def upgrade():
    conn = op.get_bind()
    for category, name, unit, description in WOODWORK:
        conn.execute(sa.text("DELETE FROM boq_items WHERE name = :n AND COALESCE(unit, '') = :u "
                             "AND COALESCE(category, '') = :c AND COALESCE(description, '') = :d"),
                     {'n': name, 'u': unit, 'c': category, 'd': description})


def downgrade():
    pass                                   # removed starter lines aren't put back (businesses add their own)
