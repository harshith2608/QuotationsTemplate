"""tutorials: the marketing site's tutorial videos, managed from the ops console

Safe to run after deploy: until it runs, the Tutorials page is simply hidden.
Only the marketing (demo) database uses it; the console adds the first six videos with one button.

Revision ID: c7d4a2e8f6b9
Revises: b6e2f9a4d8c1
Create Date: 2026-10-16 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c7d4a2e8f6b9'
down_revision = 'b6e2f9a4d8c1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('tutorials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('about', sa.String(length=300), nullable=False, server_default=''),
        sa.Column('length', sa.String(length=20), nullable=False, server_default=''),
        sa.Column('youtube_id', sa.String(length=11), nullable=True),
        sa.Column('hidden', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('tutorials')
