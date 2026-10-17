"""plywood_options.details: brand, grade, thickness, warranty for {plywood_details} in quotation sections

Safe to run after deploy: until it runs, {plywood_details} prints the plywood's name.

Revision ID: f1a7d3c9e5b2
Revises: e9f6c4a2b8d5
Create Date: 2026-10-18 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a7d3c9e5b2'
down_revision = 'e9f6c4a2b8d5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('plywood_options') as b:
        b.add_column(sa.Column('details', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('plywood_options') as b:
        b.drop_column('details')
