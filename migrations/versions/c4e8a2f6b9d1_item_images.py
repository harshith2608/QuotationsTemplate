"""item_images: a photo on a quotation line (a reference image for each item); items.image_id

Turned on per business from the console (app_settings feature_item_images). A photo is stored once (resized JPEG) and
never changed; lines, starting quotations and revisions point to it by id, so copying a quotation copies no bytes.

Safe to run after deploy: until it runs, photos can't be turned on and items save as before.

Revision ID: c4e8a2f6b9d1
Revises: b8d4f0a6c2e3
Create Date: 2026-10-25 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e8a2f6b9d1'
down_revision = 'b8d4f0a6c2e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('item_images',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('data', sa.LargeBinary(), nullable=False),
                    sa.Column('mime', sa.String(20), nullable=False, server_default='image/jpeg'),
                    sa.Column('width', sa.Integer(), nullable=True),
                    sa.Column('height', sa.Integer(), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('items') as b:
        b.add_column(sa.Column('image_id', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('items') as b:
        b.drop_column('image_id')
    op.drop_table('item_images')
