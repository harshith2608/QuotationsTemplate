"""demo_stats: anonymous daily counts for the public demo

Safe to run after deploy: until it runs, the demo works and just isn't counted.

Revision ID: f2a6c8e0b4d1
Revises: e5f1b7c9a3d2
Create Date: 2026-10-14 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2a6c8e0b4d1'
down_revision = 'e5f1b7c9a3d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('demo_stats',
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('starts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('quotations', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pdfs', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('day'),
    )


def downgrade():
    op.drop_table('demo_stats')
