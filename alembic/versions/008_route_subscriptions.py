"""008 route_subscriptions — ADR-014

Revision ID: 008_route_subscriptions
Revises: 007_ux_fixes
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = '008_route_subscriptions'
down_revision = '007_ux_fixes'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'route_subscriptions',
        sa.Column('id',              sa.Integer,  primary_key=True),
        sa.Column('user_id',         sa.Integer,  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('from_city',       sa.String(100), nullable=False),
        sa.Column('to_city',         sa.String(100), nullable=False),
        sa.Column('notify_tg',       sa.Boolean,  default=True),
        sa.Column('notify_email',    sa.Boolean,  default=False),
        sa.Column('truck_type',      sa.String(50), nullable=True),
        sa.Column('max_weight_t',    sa.Integer,  nullable=True),
        sa.Column('is_active',       sa.Boolean,  default=True),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_notified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_route_subscriptions_user_id',  'route_subscriptions', ['user_id'])
    op.create_index('ix_route_subscriptions_is_active','route_subscriptions', ['is_active'])
    # Составной индекс для матчинга (from_city, to_city, is_active)
    op.create_index('ix_route_sub_route', 'route_subscriptions', ['from_city', 'to_city', 'is_active'])


def downgrade():
    op.drop_index('ix_route_sub_route',                table_name='route_subscriptions')
    op.drop_index('ix_route_subscriptions_is_active',  table_name='route_subscriptions')
    op.drop_index('ix_route_subscriptions_user_id',    table_name='route_subscriptions')
    op.drop_table('route_subscriptions')
