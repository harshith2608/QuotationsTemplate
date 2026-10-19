"""leads: city and email on free-trial requests

Safe to run after deploy: until it runs, the form works and just doesn't store the city and email.

Revision ID: d4e0a6b8c2f5
Revises: b3c9f5a7d2e4
Create Date: 2026-10-19 15:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e0a6b8c2f5'
down_revision = 'b3c9f5a7d2e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('city', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('email', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_column('email')
        batch_op.drop_column('city')
