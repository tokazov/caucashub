"""Трек 8: audit log + withdrawn status + unique deal per load.

Revision ID: 003_track8
Revises: 002_adr007
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa

revision = '003_track8'
down_revision = '002_adr007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Audit log таблица ────────────────────────────────────────────────────
    op.create_table(
        'status_changes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('entity_type', sa.String(20), nullable=False, index=True),
        sa.Column('entity_id', sa.Integer(), nullable=False, index=True),
        sa.Column('from_status', sa.String(30), nullable=True),
        sa.Column('to_status', sa.String(30), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('reason', sa.Text(), nullable=True),
    )

    # ── Response: добавить withdrawn ─────────────────────────────────────────
    # Enum уже хранит строки — новое значение 'withdrawn' просто добавляется
    # (SQLite не требует ALTER TYPE, PostgreSQL нужна миграция enum)
    # Для PostgreSQL: DO $$ BEGIN ALTER TYPE responsestatus ADD VALUE IF NOT EXISTS 'withdrawn'; END $$;
    # SQLite: не нужно (строки)


def downgrade() -> None:
    op.drop_table('status_changes')
