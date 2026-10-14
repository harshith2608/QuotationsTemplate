"""leads: company name on free-trial requests

Safe to run after deploy: until it runs, the form works and just doesn't store the company name.

Revision ID: e5f1b7c9a3d2
Revises: c4e8a1d2f7b3
Create Date: 2026-10-14 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f1b7c9a3d2'
down_revision = 'c4e8a1d2f7b3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('company_name', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_column('company_name')
