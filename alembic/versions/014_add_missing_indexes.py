"""Add missing performance indexes

Revision ID: 014
Revises: 013
Create Date: 2026-05-10

Без этих индексов при росте базы публичная лента грузов и кабинеты сделок тормозят.
Все индексы — IF NOT EXISTS, безопасно применять на рабочей БД.
"""
from alembic import op


revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Публичная лента грузов
    op.execute("CREATE INDEX IF NOT EXISTS ix_loads_status_demo ON loads (status, is_demo)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_loads_city_ids ON loads (from_city_id, to_city_id)")

    # Отклики
    op.execute("CREATE INDEX IF NOT EXISTS ix_responses_load_id ON responses (load_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_responses_load_status ON responses (load_id, status)")

    # Кабинеты сделок
    op.execute("CREATE INDEX IF NOT EXISTS ix_deals_shipper_id ON deals (shipper_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_deals_carrier_id ON deals (carrier_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_deals_load_id ON deals (load_id)")

    # Транспортные предложения
    op.execute("CREATE INDEX IF NOT EXISTS ix_transport_offers_demo ON transport_offers (status, is_demo)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_loads_status_demo")
    op.execute("DROP INDEX IF EXISTS ix_loads_city_ids")
    op.execute("DROP INDEX IF EXISTS ix_responses_load_id")
    op.execute("DROP INDEX IF EXISTS ix_responses_load_status")
    op.execute("DROP INDEX IF EXISTS ix_deals_shipper_id")
    op.execute("DROP INDEX IF EXISTS ix_deals_carrier_id")
    op.execute("DROP INDEX IF EXISTS ix_deals_load_id")
    op.execute("DROP INDEX IF EXISTS ix_transport_offers_demo")
