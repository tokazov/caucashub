"""009 ADR-016: двусторонняя биржа — transport_offers, transport_requests,
transport_subscriptions, расширение deals

Revision ID: 009_adr016_transport_bilateral
Revises: 008_route_subscriptions
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa

revision = '009_adr016_transport_bilateral'
down_revision = '008_route_subscriptions'
branch_labels = None
depends_on = None


def upgrade():
    # ── transport_offers ──────────────────────────────────────────────────
    op.create_table(
        'transport_offers',
        sa.Column('id',           sa.Integer,  primary_key=True),
        sa.Column('user_id',      sa.Integer,  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('from_city',    sa.String(100), nullable=False),
        sa.Column('to_city',      sa.String(100), nullable=False),
        sa.Column('from_city_id', sa.Integer,  sa.ForeignKey('cities.id'), nullable=True),
        sa.Column('to_city_id',   sa.Integer,  sa.ForeignKey('cities.id'), nullable=True),
        sa.Column('truck_type',   sa.String(50),  nullable=False),
        sa.Column('capacity_kg',  sa.Float,    nullable=False),
        sa.Column('available_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('available_to',   sa.DateTime(timezone=True), nullable=True),
        sa.Column('price',        sa.Float,    nullable=True),
        sa.Column('price_usd',    sa.Float,    nullable=True),
        sa.Column('status',       sa.String(20), default='active'),
        sa.Column('urgent',       sa.Boolean,  default=False),
        sa.Column('notes',        sa.Text,     nullable=True),
        sa.Column('views',        sa.Integer,  default=0),
        sa.Column('is_demo',      sa.Boolean,  default=False),
        sa.Column('created_at',   sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',   sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_transport_offers_user_id', 'transport_offers', ['user_id'])
    op.create_index('ix_transport_offers_status',  'transport_offers', ['status'])

    # ── transport_requests ────────────────────────────────────────────────
    op.create_table(
        'transport_requests',
        sa.Column('id',                  sa.Integer, primary_key=True),
        sa.Column('transport_offer_id',  sa.Integer,
                  sa.ForeignKey('transport_offers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id',             sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('cargo_description',   sa.Text,    nullable=True),
        sa.Column('weight_kg',           sa.Float,   nullable=True),
        sa.Column('price',               sa.Float,   nullable=True),
        sa.Column('message',             sa.Text,    nullable=True),
        sa.Column('status',              sa.String(20), default='pending'),
        sa.Column('created_at',          sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_transport_requests_offer_id', 'transport_requests', ['transport_offer_id'])
    op.create_index('ix_transport_requests_user_id',  'transport_requests', ['user_id'])
    op.create_index('ix_transport_requests_status',   'transport_requests', ['status'])

    # ── transport_subscriptions ───────────────────────────────────────────
    op.create_table(
        'transport_subscriptions',
        sa.Column('id',           sa.Integer, primary_key=True),
        sa.Column('user_id',      sa.Integer,
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('from_city',    sa.String(100), nullable=False),
        sa.Column('to_city',      sa.String(100), nullable=False),
        sa.Column('notify_tg',    sa.Boolean, default=True),
        sa.Column('notify_email', sa.Boolean, default=False),
        sa.Column('truck_type',   sa.String(50), nullable=True),
        sa.Column('max_weight_t', sa.Integer,  nullable=True),
        sa.Column('is_active',    sa.Boolean, default=True),
        sa.Column('created_at',   sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_notified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_transport_sub_user',   'transport_subscriptions', ['user_id'])
    op.create_index('ix_transport_sub_active', 'transport_subscriptions', ['is_active'])
    op.create_index('ix_transport_sub_route',  'transport_subscriptions',
                    ['from_city', 'to_city', 'is_active'])

    # ── deals: расширение (ADR-016.1) ─────────────────────────────────────
    # load_id: NOT NULL → nullable (обратная совместимость через emergency migration)
    # transport_offer_id, transport_request_id: новые nullable колонки
    op.add_column('deals',
        sa.Column('transport_offer_id', sa.Integer,
                  sa.ForeignKey('transport_offers.id'), nullable=True))
    op.add_column('deals',
        sa.Column('transport_request_id', sa.Integer,
                  sa.ForeignKey('transport_requests.id'), nullable=True))
    # load_id делаем nullable через raw SQL (Alembic не умеет изменять nullable для всех БД)


def downgrade():
    op.drop_column('deals', 'transport_request_id')
    op.drop_column('deals', 'transport_offer_id')
    op.drop_index('ix_transport_sub_route',  table_name='transport_subscriptions')
    op.drop_index('ix_transport_sub_active', table_name='transport_subscriptions')
    op.drop_index('ix_transport_sub_user',   table_name='transport_subscriptions')
    op.drop_table('transport_subscriptions')
    op.drop_index('ix_transport_requests_status',   table_name='transport_requests')
    op.drop_index('ix_transport_requests_user_id',  table_name='transport_requests')
    op.drop_index('ix_transport_requests_offer_id', table_name='transport_requests')
    op.drop_table('transport_requests')
    op.drop_index('ix_transport_offers_status',  table_name='transport_offers')
    op.drop_index('ix_transport_offers_user_id', table_name='transport_offers')
    op.drop_table('transport_offers')
