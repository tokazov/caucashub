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


async def log_failed_deletion_attempt(
    db: AsyncSession,
    user_id: int,
    reason: str,
) -> StatusChange:
    """
    Логирует неудачную попытку удаления аккаунта.
    reason: 'wrong_confirmation' | 'wrong_password' | 'active_deals' | 'rate_limit'
    Использует ту же таблицу status_changes что и log_status_change.
    """
    entry = StatusChange(
        entity_type="user_deletion_attempt",
        entity_id=user_id,
        from_status=None,
        to_status=reason,
        user_id=user_id,
        reason=f"failed_delete: {reason}",
    )
    db.add(entry)
    await db.flush()
    return entry
