"""011 enum additions — перенос ALTER TYPE из emergency_migrations в Alembic

Revision ID: 011_enum_additions
Revises: 010_backfill_load_completed
Create Date: 2026-05-05

Добавляет все enum-значения которые были в _emergency_migrations.
Идемпотентна — использует IF NOT EXISTS через DO $$ блоки.

После этой миграции ALTER TYPE строки можно удалить из main.py _emergency_migrations,
оставив только CREATE TABLE IF NOT EXISTS (для холодного старта).
"""
from alembic import op


revision = '011_enum_additions'
down_revision = '010_backfill_load_completed'
branch_labels = None
depends_on = None


_ALTER_STMTS = [
    # userplan: pro_plus добавлен для Pro+тарифа
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_enum
            WHERE enumlabel='pro_plus'
              AND enumtypid=(SELECT oid FROM pg_type WHERE typname='userplan')
        ) THEN ALTER TYPE userplan ADD VALUE 'pro_plus';
        END IF;
    END $$""",

    # loadstatus: paused (владелец заблокирован)
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_enum
            WHERE enumlabel='paused'
              AND enumtypid=(SELECT oid FROM pg_type WHERE typname='loadstatus')
        ) THEN ALTER TYPE loadstatus ADD VALUE 'paused';
        END IF;
    END $$""",

    # loadstatus: completed (после rate_deal, случай B, 2026-05-05)
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_enum
            WHERE enumlabel='completed'
              AND enumtypid=(SELECT oid FROM pg_type WHERE typname='loadstatus')
        ) THEN ALTER TYPE loadstatus ADD VALUE 'completed';
        END IF;
    END $$""",

    # responsestatus: withdrawn (перевозчик отозвал отклик)
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_enum
            WHERE enumlabel='withdrawn'
              AND enumtypid=(SELECT oid FROM pg_type WHERE typname='responsestatus')
        ) THEN ALTER TYPE responsestatus ADD VALUE 'withdrawn';
        END IF;
    END $$""",
]


def upgrade():
    """Идемпотентно добавляет enum-значения через DO $$ IF NOT EXISTS блоки."""
    conn = op.get_bind()
    for stmt in _ALTER_STMTS:
        try:
            conn.execute(stmt if hasattr(stmt, 'execute') else __import__('sqlalchemy').text(stmt))
        except Exception as e:
            # SQLite не поддерживает ALTER TYPE — игнорируем в тестах
            if 'sqlite' not in str(type(conn.engine.dialect)).lower():
                raise
            print(f"[MIGRATE 011] skip (SQLite): {e}", flush=True)


def downgrade():
    # ALTER TYPE DROP VALUE не поддерживается в PostgreSQL < 14
    # Оставляем как no-op
    pass
