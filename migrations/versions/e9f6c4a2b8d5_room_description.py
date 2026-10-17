"""rooms.description: what each room is made of, for the room-wise Initial Quotation

Safe to run after deploy: until it runs, rooms are described from their materials.

Revision ID: e9f6c4a2b8d5
Revises: d8e5b3f1a7c4
Create Date: 2026-10-17 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'e9f6c4a2b8d5'
down_revision = 'd8e5b3f1a7c4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('rooms') as b:
        b.add_column(sa.Column('description', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('rooms') as b:
        b.drop_column('description')
