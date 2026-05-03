"""
Действия над аккаунтом: блокировка, разблокировка (2.4.2).

Логика при блокировке is_active=False:
- Пользователь не может логиниться (проверка в require_user)
- Активные грузы → paused (скрыты из ленты, но не удалены)
- Активные отклики → withdrawn (перевозчик не может действовать)
- Активные сделки → остаются как есть (вторая сторона завершает их)

При разблокировке:
- is_active = True
- paused грузы → active
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.models.load import Load, LoadStatus
from app.models.response import Response, ResponseStatus
from app.services.audit_log import log_status_change


async def block_user(
    db: AsyncSession,
    user_id: int,
    admin_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    Блокирует пользователя.
    Возвращает словарь с количеством затронутых объектов.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")
    if not user.is_active:
        return {"already_blocked": True}

    # Паузим активные грузы
    loads_res = await db.execute(
        select(Load).where(Load.user_id == user_id, Load.status == LoadStatus.active)
    )
    paused_count = 0
    for load in loads_res.scalars().all():
        load.status = LoadStatus.paused
        await log_status_change(db, "load", load.id, "active", "paused", admin_user_id,
                                 reason=f"owner_blocked: {reason or 'admin action'}")
        paused_count += 1

    # Отзываем pending-отклики
    resp_res = await db.execute(
        select(Response).where(
            Response.user_id == user_id,
            Response.status == ResponseStatus.pending,
        )
    )
    withdrawn_count = 0
    for resp in resp_res.scalars().all():
        resp.status = ResponseStatus.withdrawn
        await log_status_change(db, "response", resp.id, "pending", "withdrawn", admin_user_id,
                                 reason=f"owner_blocked: {reason or 'admin action'}")
        withdrawn_count += 1

    # Блокируем пользователя
    user.is_active = False
    await log_status_change(db, "user", user_id, "active", "blocked", admin_user_id, reason=reason)
    await db.commit()

    return {
        "blocked": True,
        "user_id": user_id,
        "loads_paused": paused_count,
        "responses_withdrawn": withdrawn_count,
        "note": "Active deals are preserved — counterparty can still complete them",
    }


async def unblock_user(
    db: AsyncSession,
    user_id: int,
    admin_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    Разблокирует пользователя.
    Восстанавливает paused грузы в active.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")
    if user.is_active:
        return {"already_active": True}
    if getattr(user, 'is_deleted', False):
        raise ValueError("Cannot unblock deleted account")

    # Восстанавливаем paused → active
    loads_res = await db.execute(
        select(Load).where(Load.user_id == user_id, Load.status == LoadStatus.paused)
    )
    restored_count = 0
    for load in loads_res.scalars().all():
        load.status = LoadStatus.active
        await log_status_change(db, "load", load.id, "paused", "active", admin_user_id,
                                 reason=f"owner_unblocked: {reason or 'admin action'}")
        restored_count += 1

    user.is_active = True
    await log_status_change(db, "user", user_id, "blocked", "active", admin_user_id, reason=reason)
    await db.commit()

    return {
        "unblocked": True,
        "user_id": user_id,
        "loads_restored": restored_count,
    }
