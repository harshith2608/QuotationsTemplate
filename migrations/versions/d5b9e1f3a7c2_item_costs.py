"""item_costs: your own cost on a quotation line (admins only); items.cost_price

Turned on per business from the console (app_settings feature_item_costs). Encrypted like prices (stored as text).
Safe to run after deploy: until it runs, costs can't be turned on and items save as before.

Revision ID: d5b9e1f3a7c2
Revises: c4e8a2f6b9d1
Create Date: 2026-10-26 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'd5b9e1f3a7c2'
down_revision = 'c4e8a2f6b9d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('items') as b:
        b.add_column(sa.Column('cost_price', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('items') as b:
        b.drop_column('cost_price')
