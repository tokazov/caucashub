"""019 ads table

Revision ID: 019
Revises: 018
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('advertiser', sa.String(200), nullable=False),
        sa.Column('image_url', sa.String(500), nullable=True),
        sa.Column('link_url', sa.String(500), nullable=False),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('cta_text', sa.String(100), nullable=True),
        sa.Column('placement', sa.String(50), nullable=False),
        sa.Column('clicks', sa.Integer(), default=0),
        sa.Column('impressions', sa.Integer(), default=0),
        sa.Column('active', sa.Boolean(), default=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_ads_placement_active', 'ads', ['placement', 'active'])


def downgrade():
    op.drop_index('ix_ads_placement_active', table_name='ads')
    op.drop_table('ads')
