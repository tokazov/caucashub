"""Add idempotency_keys table (Postgres-backed idempotency with 24h TTL)

Revision ID: 013
Revises: 012
Create Date: 2026-05-10

Replaces in-memory _store in app/services/idempotency.py with a Postgres table.
Survives service restarts. TTL 24 hours (enforced by expires_at column).
Background cleanup job deletes expired rows hourly.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            id               SERIAL PRIMARY KEY,
            key              VARCHAR(255)  NOT NULL,
            -- user_id: INTEGER без FK на users.id — намеренно.
            -- Idempotency-записи живут максимум 24 часа (TTL).
            -- FK на users.id намеренно отсутствует: при soft-delete юзера
            -- (ADR-010) его токен инвалидирован через password_changed_at,
            -- новые запросы невозможны, существующие записи протухнут
            -- по TTL естественно. ON DELETE CASCADE создал бы ненужную
            -- связанность без практической пользы.
            user_id          INTEGER       NOT NULL,
            scope            VARCHAR(64)   NOT NULL,
            request_hash     VARCHAR(64)   NOT NULL,
            response_status  INTEGER       NOT NULL,
            response_body    JSONB         NOT NULL,
            created_at       TIMESTAMPTZ   DEFAULT NOW(),
            expires_at       TIMESTAMPTZ   NOT NULL,
            CONSTRAINT uq_idempotency_scope_user_key UNIQUE (scope, user_id, key)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_idempotency_expires
        ON idempotency_keys (expires_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
