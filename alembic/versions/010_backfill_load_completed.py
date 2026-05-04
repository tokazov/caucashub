"""010 backfill: Load.status taken → completed для завершённых сделок

Revision ID: 010_backfill_load_completed
Revises: 009_adr016_transport_bilateral
Create Date: 2026-05-05

Контекст: до коммита be4d547 Load оставался в 'taken' после rate_deal.
Синхронизация (случай B): оба Load и TransportOffer → completed при rate_deal.
Этот backfill приводит исторические записи в соответствие.

Идемпотентен: повторный запуск обновит 0 записей.
"""
from alembic import op
from sqlalchemy import text
import logging

revision = '010_backfill_load_completed'
down_revision = '009_adr016_transport_bilateral'
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade():
    conn = op.get_bind()

    # Находим Load.status = 'taken' у которых есть Deal.status IN (completed, rated)
    result = conn.execute(text("""
        UPDATE loads
        SET status = 'completed'
        WHERE status = 'taken'
          AND id IN (
              SELECT DISTINCT load_id
              FROM deals
              WHERE load_id IS NOT NULL
                AND status IN ('completed', 'rated')
          )
    """))

    rowcount = result.rowcount if hasattr(result, 'rowcount') else -1
    print(f"[backfill] Load taken→completed: {rowcount} записей обновлено", flush=True)
    logger.info(f"backfill Load.taken→completed: {rowcount} rows updated")


def downgrade():
    # Откат: completed → taken для грузов с rated сделками
    conn = op.get_bind()
    result = conn.execute(text("""
        UPDATE loads
        SET status = 'taken'
        WHERE status = 'completed'
          AND id IN (
              SELECT DISTINCT load_id
              FROM deals
              WHERE load_id IS NOT NULL
                AND status IN ('completed', 'rated')
          )
    """))
    print(f"[backfill downgrade] Load completed→taken: {result.rowcount} записей", flush=True)
