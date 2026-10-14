"""quote_shares.detail: the customer's link shows the material breakdown or the full detailed quotation

Safe to run after deploy (quote-to-cash features stay hidden until it has run).

Revision ID: b6e2f9a4d8c1
Revises: a9d3e7f1c5b2
Create Date: 2026-10-15 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b6e2f9a4d8c1'
down_revision = 'a9d3e7f1c5b2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('quote_shares', schema=None) as batch_op:
        batch_op.add_column(sa.Column('detail', sa.String(length=10), nullable=False, server_default='summary'))


def downgrade():
    with op.batch_alter_table('quote_shares', schema=None) as batch_op:
        batch_op.drop_column('detail')
