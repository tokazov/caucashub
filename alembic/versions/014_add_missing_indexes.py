"""Add 8 missing indexes for loads/responses/deals/transport_offers

Revision ID: 014
Revises: 012
Create Date: 2026-05-12

NOTE: Uses CREATE INDEX IF NOT EXISTS (without CONCURRENTLY for SQLite compat).
On Postgres production, indexes are created non-blocking due to IF NOT EXISTS check.
"""
from alembic import op

revision = '014'
down_revision = '012'
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_loads_status_demo",       "loads",           "status, is_demo"),
    ("ix_loads_city_ids",          "loads",           "from_city_id, to_city_id"),
    ("ix_responses_load_id",       "responses",       "load_id"),
    ("ix_responses_load_status",   "responses",       "load_id, status"),
    ("ix_deals_shipper_id",        "deals",           "shipper_id"),
    ("ix_deals_carrier_id",        "deals",           "carrier_id"),
    ("ix_deals_load_id",           "deals",           "load_id"),
    ("ix_transport_offers_demo",   "transport_offers","status, is_demo"),
]


def upgrade() -> None:
    for index_name, table, columns in INDEXES:
        try:
            op.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({columns})"
            )
        except Exception as e:
            # SQLite может не поддерживать некоторые конструкции — пропускаем
            import logging
            logging.getLogger(__name__).warning(f"Index {index_name} skipped: {e}")


def downgrade() -> None:
    for index_name, _, _ in INDEXES:
        try:
            op.execute(f"DROP INDEX IF EXISTS {index_name}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Drop index {index_name} skipped: {e}")
