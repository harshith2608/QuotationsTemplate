"""material_rules, material_lists, material_list_lines: the material list of a quotation (what to buy, with wastage)

Safe to run after deploy: until it runs, the Material list button isn't shown.

Revision ID: a3c7e9b5d1f4
Revises: f7c3a9e5b1d4
Create Date: 2026-11-02 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3c7e9b5d1f4'
down_revision = 'f7c3a9e5b1d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('material_rules',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('name', sa.String(100), nullable=False),
                    sa.Column('category', sa.String(60), nullable=False),
                    sa.Column('materials', sa.Text(), nullable=True),
                    sa.Column('work_type', sa.String(50), nullable=True),
                    sa.Column('per_sqft', sa.Float(), nullable=False, server_default='0'),
                    sa.Column('unit', sa.String(30), nullable=True),
                    sa.Column('wastage', sa.Float(), nullable=False, server_default='0'),
                    sa.Column('round_up', sa.Boolean(), nullable=False, server_default=sa.true()),
                    sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
                    sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('material_lists',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'),
                              nullable=False, unique=True),
                    sa.Column('signature', sa.String(64), nullable=True),
                    sa.Column('built_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_table('material_list_lines',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('list_id', sa.Integer(), sa.ForeignKey('material_lists.id', ondelete='CASCADE'),
                              nullable=False, index=True),
                    sa.Column('kind', sa.String(10), nullable=False, server_default='manual'),
                    sa.Column('key', sa.String(200), nullable=True),
                    sa.Column('category', sa.String(60), nullable=False),
                    sa.Column('name', sa.String(150), nullable=False),
                    sa.Column('quantity', sa.Float(), nullable=True),
                    sa.Column('unit', sa.String(30), nullable=True),
                    sa.Column('source', sa.Text(), nullable=True),
                    sa.Column('edited', sa.Boolean(), nullable=False, server_default=sa.false()),
                    sa.Column('removed', sa.Boolean(), nullable=False, server_default=sa.false()),
                    sa.Column('ordered', sa.Boolean(), nullable=False, server_default=sa.false()),
                    sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_table('material_list_lines')
    op.drop_table('material_lists')
    op.drop_table('material_rules')
