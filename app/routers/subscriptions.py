"""
Подписки на маршруты (ADR-014).

Эндпоинты:
  GET    /api/subscriptions/          — список подписок текущего пользователя
  POST   /api/subscriptions/          — создать подписку
  PATCH  /api/subscriptions/{id}      — изменить подписку (активировать/деактивировать/фильтры)
  DELETE /api/subscriptions/{id}      — удалить подписку

Лимит: 50 подписок на пользователя (safety-cap против абуза).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy import func as sa_func
from pydantic import BaseModel, field_validator
from typing import Optional
from app.database import get_db
from app.models.subscription import RouteSubscription
from app.routers.auth import require_user

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])

SUBSCRIPTION_LIMIT = 50  # safety-cap


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SubscriptionCreate(BaseModel):
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
        if len(v) > 100:
            raise ValueError("Название города слишком длинное")
        # Сохраняем оригинальный регистр (не делаем lower — это ломает translateCity на фронте)
        # Дубликат-чек делается case-insensitive через ilike в запросе
        return v

    @field_validator("max_weight_t")
    @classmethod
    def validate_weight(cls, v):
        if v is not None and (v < 0 or v > 100):
            raise ValueError("max_weight_t должен быть 0–100 тонн")
        return v


class SubscriptionPatch(BaseModel):
    is_active:    Optional[bool] = None
    notify_tg:    Optional[bool] = None
    notify_email: Optional[bool] = None
    truck_type:   Optional[str]  = None
    max_weight_t: Optional[int]  = None


class SubscriptionOut(BaseModel):
    id:             int
    from_city:      str
    to_city:        str
    notify_tg:      bool
    notify_email:   bool
    truck_type:     Optional[str]
    max_weight_t:   Optional[int]
    is_active:      bool
    created_at:     str

    model_config = {"from_attributes": True}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sub_to_out(s: RouteSubscription) -> dict:
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
async def list_subscriptions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Список всех подписок текущего пользователя."""
    result = await db.execute(
        select(RouteSubscription)
        .where(RouteSubscription.user_id == current_user.id)
        .order_by(RouteSubscription.created_at.desc())
    )
    subs = result.scalars().all()
    return {"subscriptions": [_sub_to_out(s) for s in subs], "total": len(subs)}


@router.post("/", status_code=201)
async def create_subscription(
    data: SubscriptionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Создать подписку на маршрут. Лимит: 50 активных подписок."""
    # Проверяем лимит по тарифному плану
    from app.services.plan_check import check_subscriptions_limit
    count_res = await db.execute(
        select(func.count()).where(RouteSubscription.user_id == current_user.id)
    )
    count = count_res.scalar_one()
    # Жёсткий safety-cap
    if count >= SUBSCRIPTION_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"Превышен лимит подписок ({SUBSCRIPTION_LIMIT}). Удалите ненужные."
        )
    # Лимит по тарифу
    ok, limit_err = check_subscriptions_limit(current_user, count)
    if not ok:
        raise HTTPException(status_code=403, detail=limit_err)

    # Проверяем дубликаты (from_city + to_city + is_active), case-insensitive
    dup_res = await db.execute(
        select(RouteSubscription).where(
            RouteSubscription.user_id == current_user.id,
            func.lower(RouteSubscription.from_city) == data.from_city.lower(),
            func.lower(RouteSubscription.to_city) == data.to_city.lower(),
            RouteSubscription.is_active == True,  # noqa: E712
        )
    )
    if dup_res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Подписка на этот маршрут уже существует")

    sub = RouteSubscription(
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
    return {"ok": True, "subscription": _sub_to_out(sub)}


@router.patch("/{sub_id}")
async def update_subscription(
    sub_id: int,
    data: SubscriptionPatch,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Изменить подписку (активировать/деактивировать/поменять фильтры)."""
    result = await db.execute(
        select(RouteSubscription).where(
            RouteSubscription.id == sub_id,
            RouteSubscription.user_id == current_user.id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Подписка не найдена")

    if data.is_active is not None:
        sub.is_active = data.is_active
    if data.notify_tg is not None:
        sub.notify_tg = data.notify_tg
    if data.notify_email is not None:
        sub.notify_email = data.notify_email
    if data.truck_type is not None:
        sub.truck_type = data.truck_type if data.truck_type != "" else None
    if data.max_weight_t is not None:
        sub.max_weight_t = data.max_weight_t

    await db.commit()
    await db.refresh(sub)
    return {"ok": True, "subscription": _sub_to_out(sub)}


@router.delete("/{sub_id}", status_code=200)
async def delete_subscription(
    sub_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    """Удалить подписку."""
    result = await db.execute(
        select(RouteSubscription).where(
            RouteSubscription.id == sub_id,
            RouteSubscription.user_id == current_user.id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Подписка не найдена")

    await db.delete(sub)
    await db.commit()
    return {"ok": True, "deleted_id": sub_id}
