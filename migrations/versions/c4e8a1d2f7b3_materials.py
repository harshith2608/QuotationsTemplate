"""materials: each business manages its own materials (glass, PU, wallpaper…)

Existing businesses keep their three materials (Acrylic, Laminates, Veneer, with work types) and rates.
New databases get their starting materials from `flask bootstrap` / seed data instead.

Revision ID: c4e8a1d2f7b3
Revises: b3d9f2c61e04
Create Date: 2026-10-13 20:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e8a1d2f7b3'
down_revision = 'b3d9f2c61e04'
branch_labels = None
depends_on = None

LEGACY = ['Acrylic', 'Laminates', 'Veneer']


def upgrade():
    materials = op.create_table('materials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('uses_work_types', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    # An existing business (it already has rates): keep its fixed materials as editable rows
    conn = op.get_bind()
    if conn.execute(sa.text('SELECT COUNT(*) FROM item_rates')).scalar():
        op.bulk_insert(materials, [{'name': n, 'uses_work_types': True, 'active': True, 'sort_order': i}
                                   for i, n in enumerate(LEGACY)])


def downgrade():
    op.drop_table('materials')
