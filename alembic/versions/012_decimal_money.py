"""Float to DECIMAL for monetary fields

Revision ID: 012
Revises: 011
Create Date: 2026-05-05

ADR: Float → NUMERIC(12,2) для всех денежных полей.
Backfill: ROUND(existing_value::numeric, 2)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011_enum_additions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── loads ─────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE loads
            ALTER COLUMN price_usd TYPE NUMERIC(12,2)
                USING ROUND(price_usd::numeric, 2),
            ALTER COLUMN price_gel TYPE NUMERIC(12,2)
                USING ROUND(price_gel::numeric, 2),
            ALTER COLUMN exchange_rate_at_creation TYPE NUMERIC(12,6)
                USING ROUND(exchange_rate_at_creation::numeric, 6)
    """)

    # ── responses ─────────────────────────────────────────────
    op.execute("""
        ALTER TABLE responses
            ALTER COLUMN price_usd TYPE NUMERIC(12,2)
                USING ROUND(price_usd::numeric, 2),
            ALTER COLUMN price_gel TYPE NUMERIC(12,2)
                USING ROUND(price_gel::numeric, 2),
            ALTER COLUMN exchange_rate_at_creation TYPE NUMERIC(12,6)
                USING ROUND(exchange_rate_at_creation::numeric, 6)
    """)

    # ── deals ──────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE deals
            ALTER COLUMN agreed_price TYPE NUMERIC(12,2)
                USING ROUND(agreed_price::numeric, 2),
            ALTER COLUMN exchange_rate_snapshot TYPE NUMERIC(12,6)
                USING ROUND(exchange_rate_snapshot::numeric, 6),
            ALTER COLUMN final_price_gel TYPE NUMERIC(12,2)
                USING ROUND(final_price_gel::numeric, 2),
            ALTER COLUMN final_price_usd TYPE NUMERIC(12,2)
                USING ROUND(final_price_usd::numeric, 2)
    """)

    # ── transport_offers ───────────────────────────────────────
    op.execute("""
        ALTER TABLE transport_offers
            ALTER COLUMN price TYPE NUMERIC(12,2)
                USING ROUND(price::numeric, 2),
            ALTER COLUMN price_usd TYPE NUMERIC(12,2)
                USING ROUND(price_usd::numeric, 2)
    """)

    # ── transport_requests ─────────────────────────────────────
    op.execute("""
        ALTER TABLE transport_requests
            ALTER COLUMN price TYPE NUMERIC(12,2)
                USING ROUND(price::numeric, 2)
    """)


def downgrade() -> None:
    # Откат: NUMERIC → FLOAT (потеря точности несущественна при откате)
    op.execute("ALTER TABLE loads ALTER COLUMN price_usd TYPE FLOAT USING price_usd::float")
    op.execute("ALTER TABLE loads ALTER COLUMN price_gel TYPE FLOAT USING price_gel::float")
    op.execute("ALTER TABLE loads ALTER COLUMN exchange_rate_at_creation TYPE FLOAT USING exchange_rate_at_creation::float")
    op.execute("ALTER TABLE responses ALTER COLUMN price_usd TYPE FLOAT USING price_usd::float")
    op.execute("ALTER TABLE responses ALTER COLUMN price_gel TYPE FLOAT USING price_gel::float")
    op.execute("ALTER TABLE responses ALTER COLUMN exchange_rate_at_creation TYPE FLOAT USING exchange_rate_at_creation::float")
    op.execute("ALTER TABLE deals ALTER COLUMN agreed_price TYPE FLOAT USING agreed_price::float")
    op.execute("ALTER TABLE deals ALTER COLUMN exchange_rate_snapshot TYPE FLOAT USING exchange_rate_snapshot::float")
    op.execute("ALTER TABLE deals ALTER COLUMN final_price_gel TYPE FLOAT USING final_price_gel::float")
    op.execute("ALTER TABLE deals ALTER COLUMN final_price_usd TYPE FLOAT USING final_price_usd::float")
    op.execute("ALTER TABLE transport_offers ALTER COLUMN price TYPE FLOAT USING price::float")
    op.execute("ALTER TABLE transport_offers ALTER COLUMN price_usd TYPE FLOAT USING price_usd::float")
    op.execute("ALTER TABLE transport_requests ALTER COLUMN price TYPE FLOAT USING price::float")
