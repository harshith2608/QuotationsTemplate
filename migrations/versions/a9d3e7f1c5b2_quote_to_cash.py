"""quote to cash: revisions, online approval, invoices, payment reminders, cost rates

New tables only. Safe to run after deploy: until it runs, these features stay hidden.

Revision ID: a9d3e7f1c5b2
Revises: f2a6c8e0b4d1
Create Date: 2026-10-15 10:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a9d3e7f1c5b2'
down_revision = 'f2a6c8e0b4d1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('quote_revisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('total', sa.Text(), nullable=False),
        sa.Column('snapshot', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'number', name='uq_quote_revision'),
    )
    op.create_index('ix_quote_revisions_project_id', 'quote_revisions', ['project_id'])

    op.create_table('quote_shares',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('first_viewed_at', sa.DateTime(), nullable=True),
        sa.Column('last_viewed_at', sa.DateTime(), nullable=True),
        sa.Column('view_count', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_quote_shares_project_id', 'quote_shares', ['project_id'])
    op.create_index('ix_quote_shares_token', 'quote_shares', ['token'], unique=True)

    op.create_table('quote_responses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('share_id', sa.Integer(), sa.ForeignKey('quote_shares.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('total', sa.Text(), nullable=True),
        sa.Column('revision', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_quote_responses_project_id', 'quote_responses', ['project_id'])

    op.create_table('invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('number', sa.String(length=20), nullable=False),
        sa.Column('fy', sa.String(length=7), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('issued_on', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='issued'),
        sa.Column('total', sa.Text(), nullable=False),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('number'),
        sa.UniqueConstraint('fy', 'seq', name='uq_invoice_seq'),
    )
    op.create_index('ix_invoices_project_id', 'invoices', ['project_id'])

    op.create_table('payment_reminders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.Column('sent_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('amount', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payment_reminders_project_id', 'payment_reminders', ['project_id'])

    op.create_table('cost_rates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('cost', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'name', name='uq_cost_rate'),
    )


def downgrade():
    op.drop_table('cost_rates')
    op.drop_index('ix_payment_reminders_project_id', table_name='payment_reminders')
    op.drop_table('payment_reminders')
    op.drop_index('ix_invoices_project_id', table_name='invoices')
    op.drop_table('invoices')
    op.drop_index('ix_quote_responses_project_id', table_name='quote_responses')
    op.drop_table('quote_responses')
    op.drop_index('ix_quote_shares_token', table_name='quote_shares')
    op.drop_index('ix_quote_shares_project_id', table_name='quote_shares')
    op.drop_table('quote_shares')
    op.drop_index('ix_quote_revisions_project_id', table_name='quote_revisions')
    op.drop_table('quote_revisions')
