"""demo_stats.site_visitors: anonymous count of browsers opening the marketing site for the first time

Safe to run after deploy: until it runs, the site works and visitors just aren't counted.
The earlier demo counts are cleared, so the whole funnel (site → demo → quotation → PDF → trial request) starts
counting on the same day. Trial requests themselves (leads) are kept.

Revision ID: e6b2c8d4f0a1
Revises: d4e0a6b8c2f5
Create Date: 2026-10-19 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6b2c8d4f0a1'
down_revision = 'd4e0a6b8c2f5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('demo_stats', schema=None) as batch_op:
        batch_op.add_column(sa.Column('site_visitors', sa.Integer(), nullable=False, server_default='0'))
    op.execute('DELETE FROM demo_stats')        # anonymous counts only: start the funnel from zero


def downgrade():
    with op.batch_alter_table('demo_stats', schema=None) as batch_op:
        batch_op.drop_column('site_visitors')
