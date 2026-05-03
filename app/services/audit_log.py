"""
Запись переходов состояний в audit log (status_changes).
Используется всеми роутерами при изменении статуса.
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.status_change import StatusChange


async def log_status_change(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    from_status: Optional[str],
    to_status: str,
    user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> StatusChange:
    """Записывает смену статуса в таблицу status_changes."""
    entry = StatusChange(
        entity_type=entity_type,
        entity_id=entity_id,
        from_status=from_status,
        to_status=to_status,
        user_id=user_id,
        reason=reason,
    )
    db.add(entry)
    # flush без commit — вызывающий сделает commit сам
    await db.flush()
    return entry
