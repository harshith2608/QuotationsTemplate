"""leads: free-trial requests from the marketing site

Revision ID: b3d9f2c61e04
Revises: a7c41e0d9b21
Create Date: 2026-10-11 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3d9f2c61e04'
down_revision = 'a7c41e0d9b21'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('leads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('phone', sa.Text(), nullable=False),
        sa.Column('business_type', sa.String(length=20), nullable=False),
        sa.Column('business_other', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=200), nullable=True),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.create_index('ix_leads_created_at', ['created_at'], unique=False)
        batch_op.create_index('ix_leads_ip_hash', ['ip_hash'], unique=False)


def downgrade():
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_index('ix_leads_ip_hash')
        batch_op.drop_index('ix_leads_created_at')
    op.drop_table('leads')
