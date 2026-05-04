"""
TransportSubscription CRUD — подписки грузовладельцев на транспорт (ADR-016).

Аналог /api/subscriptions/ но для транспортных предложений.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, field_validator
from typing import Optional

from app.database import get_db
from app.models.transport_subscription import TransportSubscription, TRANSPORT_SUBSCRIPTION_LIMIT
from app.routers.auth import require_user

router = APIRouter(prefix="/api/transport-subscriptions", tags=["transport-subscriptions"])


class TransportSubCreate(BaseModel):
    from_city:    str
    to_city:      str
    notify_tg:    bool = True
    notify_email: bool = False
    truck_type:   Optional[str] = None
    max_weight_t: Optional[int] = None

    @field_validator("from_city", "to_city")
    @classmethod
    def normalize_city(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Город не может быть пустым")
        return v.lower()


class TransportSubPatch(BaseModel):
    is_active:    Optional[bool] = None
    notify_tg:    Optional[bool] = None
    notify_email: Optional[bool] = None
    truck_type:   Optional[str]  = None
    max_weight_t: Optional[int]  = None


def _sub_to_dict(s: TransportSubscription) -> dict:
    return {
        "id":           s.id,
        "from_city":    s.from_city,
        "to_city":      s.to_city,
        "notify_tg":    s.notify_tg,
        "notify_email": s.notify_email,
        "truck_type":   s.truck_type,
        "max_weight_t": s.max_weight_t,
        "is_active":    s.is_active,
        "created_at":   s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/")
async def list_transport_subscriptions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    result = await db.execute(
        select(TransportSubscription)
        .where(TransportSubscription.user_id == current_user.id)
        .order_by(TransportSubscription.created_at.desc())
    )
    subs = result.scalars().all()
    return {"subscriptions": [_sub_to_dict(s) for s in subs], "total": len(subs)}


@router.post("/", status_code=201)
async def create_transport_subscription(
    data: TransportSubCreate,
    db:   AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    count_res = await db.execute(
        select(func.count()).where(TransportSubscription.user_id == current_user.id)
    )
    if count_res.scalar_one() >= TRANSPORT_SUBSCRIPTION_LIMIT:
        raise HTTPException(400, f"Превышен лимит подписок ({TRANSPORT_SUBSCRIPTION_LIMIT})")

    dup = await db.execute(
        select(TransportSubscription).where(
            TransportSubscription.user_id == current_user.id,
            TransportSubscription.from_city == data.from_city,
            TransportSubscription.to_city == data.to_city,
            TransportSubscription.is_active == True,   # noqa: E712
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(409, "Подписка на этот маршрут уже существует")

    sub = TransportSubscription(
        user_id      = current_user.id,
        from_city    = data.from_city,
        to_city      = data.to_city,
        notify_tg    = data.notify_tg,
        notify_email = data.notify_email,
        truck_type   = data.truck_type,
        max_weight_t = data.max_weight_t,
        is_active    = True,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return {"ok": True, "subscription": _sub_to_dict(sub)}


@router.patch("/{sub_id}")
async def update_transport_subscription(
    sub_id: int,
    data:   TransportSubPatch,
    db:     AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    result = await db.execute(
        select(TransportSubscription).where(
            TransportSubscription.id == sub_id,
            TransportSubscription.user_id == current_user.id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Подписка не найдена")

    if data.is_active is not None:
        sub.is_active = data.is_active
    if data.notify_tg is not None:
        sub.notify_tg = data.notify_tg
    if data.notify_email is not None:
        sub.notify_email = data.notify_email
    if data.truck_type is not None:
        sub.truck_type = data.truck_type or None
    if data.max_weight_t is not None:
        sub.max_weight_t = data.max_weight_t

    await db.commit()
    await db.refresh(sub)
    return {"ok": True, "subscription": _sub_to_dict(sub)}


@router.delete("/{sub_id}")
async def delete_transport_subscription(
    sub_id: int,
    db:     AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    result = await db.execute(
        select(TransportSubscription).where(
            TransportSubscription.id == sub_id,
            TransportSubscription.user_id == current_user.id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Подписка не найдена")
    await db.delete(sub)
    await db.commit()
    return {"ok": True, "deleted_id": sub_id}
