"""expand status_changes.entity_type to VARCHAR(50)

Revision ID: 015
Revises: 014
Create Date: 2026-05-13

Context: PR #7 (account deletion hardening) writes entity_type='user_deletion_attempt'
(22 chars) but column was VARCHAR(20) — caused 500 on DELETE /api/users/me.
Fix was applied as emergency_migration in main.py (hotfix PR #12).
This migration formalizes it per ADR-011.

Idempotency note: if column is already VARCHAR(50) (applied via emergency_migrations),
Postgres ALTER COLUMN TYPE VARCHAR(50) is a no-op — safe to run.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '015'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op if already VARCHAR(50) — Postgres handles silently
    op.alter_column(
        'status_changes',
        'entity_type',
        type_=sa.String(length=50),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Safe only if no rows have entity_type longer than 20 chars.
    # Explicit guard to prevent silent data truncation.
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM status_changes "
            "WHERE LENGTH(entity_type) > 20"
        )
    )
    count = result.scalar()
    if count > 0:
        raise Exception(
            f"Cannot downgrade: {count} rows have entity_type longer than "
            "20 characters. Remove or truncate them first."
        )
    op.alter_column(
        'status_changes',
        'entity_type',
        type_=sa.String(length=20),
        existing_type=sa.String(length=50),
        existing_nullable=False,
    )
