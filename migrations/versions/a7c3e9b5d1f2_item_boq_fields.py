"""items.description and items.unit: BOQ lines (and a description on any item); boq_items: saved BOQ lines

A BOQ line is an item with its own description, quantity, unit (sqft, rft, nos, lump sum…) and rate, for turnkey
work priced per line. Turned on per business from the console (app_settings feature_boq). boq_items keeps each BOQ
line the business has used (name, description, unit, rate) to offer it again on the next quotation.

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
    op.create_table('boq_items',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('name', sa.String(100), nullable=False, unique=True),
                    sa.Column('description', sa.Text(), nullable=True),
                    sa.Column('unit', sa.String(20), nullable=True),
                    sa.Column('rate', sa.Text(), nullable=False))      # EncryptedFloat (stored encrypted)


def downgrade():
    op.drop_table('boq_items')
    with op.batch_alter_table('items') as b:
        b.drop_column('unit')
        b.drop_column('description')
