"""items.description and items.unit: BOQ lines (and a description on any item)

A BOQ line is an item with its own description, quantity, unit (sqft, rft, nos, lump sum…) and rate, for turnkey
work priced per line. Turned on per business from the console (app_settings feature_boq).

Safe to run after deploy: until it runs, BOQ lines can't be turned on and items save as before.

Revision ID: a7c3e9b5d1f2
Revises: e6b2c8d4f0a1
Create Date: 2026-10-21 20:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c3e9b5d1f2'
down_revision = 'e6b2c8d4f0a1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('items') as b:
        b.add_column(sa.Column('description', sa.Text(), nullable=True))
        b.add_column(sa.Column('unit', sa.String(20), nullable=True))


def downgrade():
    with op.batch_alter_table('items') as b:
        b.drop_column('unit')
        b.drop_column('description')
