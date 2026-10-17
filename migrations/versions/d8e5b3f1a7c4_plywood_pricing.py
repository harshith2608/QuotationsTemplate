"""plywood pricing: plywood_options, materials.uses_plywood, projects.plywood, items.plywood

Safe to run after deploy: until it runs, quotations work as before (no plywood pricing; the old
plywood list is shown). Board materials (those with Box/Frame Work) start as priced on plywood.
The options themselves are added by the app on first use (their amounts are encrypted).

Revision ID: d8e5b3f1a7c4
Revises: c7d4a2e8f6b9
Create Date: 2026-10-17 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'd8e5b3f1a7c4'
down_revision = 'c7d4a2e8f6b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('plywood_options',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('adjustment', sa.Text(), nullable=False),
        sa.Column('cost_adjustment', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    with op.batch_alter_table('materials') as b:
        b.add_column(sa.Column('uses_plywood', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute('UPDATE materials SET uses_plywood = uses_work_types')
    with op.batch_alter_table('projects') as b:
        b.add_column(sa.Column('plywood', sa.String(length=60), nullable=True))
    with op.batch_alter_table('items') as b:
        b.add_column(sa.Column('plywood', sa.String(length=60), nullable=True))


def downgrade():
    with op.batch_alter_table('items') as b:
        b.drop_column('plywood')
    with op.batch_alter_table('projects') as b:
        b.drop_column('plywood')
    with op.batch_alter_table('materials') as b:
        b.drop_column('uses_plywood')
    op.drop_table('plywood_options')
