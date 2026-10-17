"""project_access.can_edit: staff can be given edit access to a quotation (not just view)

Safe to run after deploy: until it runs, shared access is view-only as before.

Revision ID: a2b8e4f6c1d3
Revises: f1a7d3c9e5b2
Create Date: 2026-10-18 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a2b8e4f6c1d3'
down_revision = 'f1a7d3c9e5b2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('project_access') as b:
        b.add_column(sa.Column('can_edit', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('project_access') as b:
        b.drop_column('can_edit')
