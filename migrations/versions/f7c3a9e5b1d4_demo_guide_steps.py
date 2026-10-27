"""demo_stats.sample_pdfs and .tried: the demo guide's steps (opened the sample quotation's PDF, opened "Make your own")

Safe to run after deploy: until it runs, the demo works and these two steps just aren't counted.

Revision ID: f7c3a9e5b1d4
Revises: d5b9e1f3a7c2
Create Date: 2026-10-27 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'f7c3a9e5b1d4'
down_revision = 'd5b9e1f3a7c2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('demo_stats', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sample_pdfs', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('tried', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('demo_stats', schema=None) as batch_op:
        batch_op.drop_column('tried')
        batch_op.drop_column('sample_pdfs')
