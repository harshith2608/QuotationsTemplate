"""boms: room-wise measurements of a home, saved on their own and turned into quotations

Safe to run after deploy: until it runs, the BOMs page asks for the update.

Revision ID: b4e8c2a6d0f3
Revises: a3c7e9b5d1f4
Create Date: 2026-11-25 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b4e8c2a6d0f3'
down_revision = 'a3c7e9b5d1f4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'boms',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('customer_name', sa.Text(), nullable=False),
        sa.Column('mobile', sa.Text(), nullable=False),
        sa.Column('email', sa.Text(), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('areas', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('boms')
