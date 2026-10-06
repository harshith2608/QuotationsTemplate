"""encrypted columns: customer details, amounts and rates become TEXT

Only changes column types; existing values stay readable as plain text.
`flask bootstrap` (or `flask encrypt-data`) then encrypts them using DATA_ENCRYPTION_KEY.

Revision ID: a7c41e0d9b21
Revises: 5511b5ca6f02
Create Date: 2026-10-06 22:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c41e0d9b21'
down_revision = '5511b5ca6f02'
branch_labels = None
depends_on = None

# table → [(column, old type, nullable)]
COLUMNS = {
    'projects': [('customer_name', sa.String(100), False), ('mobile', sa.String(20), False),
                 ('email', sa.String(100), True), ('grand_total', sa.Float(), True),
                 ('discount_value', sa.Float(), True)],
    'items': [('unit_price', sa.Float(), True)],
    'wood_rates': [('rate_per_sqft', sa.Float(), False)],
    'work_type_rates': [('rate_per_sqft', sa.Float(), False)],
    'item_rates': [('rate_per_sqft', sa.Float(), False)],
    'payments': [('amount', sa.Float(), False), ('note', sa.String(200), True)],
    'payment_links': [('amount', sa.Float(), False)],
    'notifications': [('title', sa.String(200), False)],
    'project_stage_changes': [('note', sa.String(200), True)],
    'price_list_items': [('price', sa.Float(), False)],
}


def upgrade():
    for table, cols in COLUMNS.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            for name, old, nullable in cols:
                batch_op.alter_column(name, existing_type=old, type_=sa.Text(), existing_nullable=nullable,
                                      postgresql_using=f'{name}::text')


def downgrade():
    # Only works on data that has not been encrypted yet (run with the key unset is not enough:
    # encrypted values must be decrypted first, which this migration cannot do).
    for table, cols in COLUMNS.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            for name, old, nullable in cols:
                using = f'{name}::double precision' if isinstance(old, sa.Float) else f'{name}::varchar'
                batch_op.alter_column(name, existing_type=sa.Text(), type_=old, existing_nullable=nullable,
                                      postgresql_using=using)
