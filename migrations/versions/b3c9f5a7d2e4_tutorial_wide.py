"""tutorials.wide: landscape (16:9) videos are shown wide on the Tutorials page

Safe to run after deploy: until it runs, every video shows in the tall (phone) shape and the console hides the
Landscape tick box. Only the marketing (demo) database uses the tutorials table.

Revision ID: b3c9f5a7d2e4
Revises: a2b8e4f6c1d3
Create Date: 2026-10-19 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c9f5a7d2e4'
down_revision = 'a2b8e4f6c1d3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tutorials') as batch:
        batch.add_column(sa.Column('wide', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('tutorials') as batch:
        batch.drop_column('wide')
