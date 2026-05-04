"""
Двусторонняя биржа — TransportOffer CRUD (ADR-016, Этап 2).

Эндпоинты:
  POST   /api/transport/          — создать предложение транспорта (перевозчик)
  GET    /api/transport/          — список предложений (публичный, с фильтрами)
  GET    /api/transport/{id}      — детали предложения
  PATCH  /api/transport/{id}      — изменить своё предложение
  DELETE /api/transport/{id}      — снять предложение

Статус-машина TransportOffer:
  active → taken (при accept TransportRequest)
  active → canceled (владелец снял)
  taken  → completed (после rate)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Header, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models.transport_offer import TransportOffer
from app.models.user import User
from app.routers.auth import require_user

router = APIRouter(prefix="/api/transport", tags=["transport"])

# ── Pydantic schemas ──────────────────────────────────────────────────────────

VALID_TRUCK_TYPES = {"tent", "gazel", "ref", "open", "container", "autovoz", "lowboy"}

class TransportOfferCreate(BaseModel):
    from_city:      str
    to_city:        str
    truck_type:     str
    capacity_kg:    float
    available_from: datetime
    available_to:   Optional[datetime] = None
    price:          Optional[float] = None
    price_usd:      Optional[float] = None
    urgent:         bool = False
    notes:          Optional[str] = None

    @field_validator("from_city", "to_city")
    @classmethod
    def validate_city(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Город не может быть пустым")
        if len(v) > 100:
            raise ValueError("Название города слишком длинное")
        return v

    @field_validator("capacity_kg")
    @classmethod
    def validate_capacity(cls, v: float) -> float:
        if v <= 0 or v > 100000:
            raise ValueError("capacity_kg должен быть от 1 до 100000 кг")
        return v

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if v is not None and v < 0:
            raise ValueError("Цена не может быть отрицательной")
        return v


class TransportOfferPatch(BaseModel):
    from_city:      Optional[str] = None
    to_city:        Optional[str] = None
    truck_type:     Optional[str] = None
    capacity_kg:    Optional[float] = None
    available_from: Optional[datetime] = None
    available_to:   Optional[datetime] = None
    price:          Optional[float] = None
    price_usd:      Optional[float] = None
    urgent:         Optional[bool] = None
    notes:          Optional[str] = None
    status:         Optional[str] = None   # перевозчик может снять: active→canceled


# ── Helpers ───────────────────────────────────────────────────────────────────

def _offer_to_dict(offer: TransportOffer, user: User = None,
                   show_contacts: bool = False) -> dict:
    return {
        "id":             offer.id,
        "user_id":        offer.user_id,
        "from_city":      offer.from_city,
        "to_city":        offer.to_city,
        "truck_type":     offer.truck_type,
        "capacity_kg":    offer.capacity_kg,
        "available_from": offer.available_from.isoformat() if offer.available_from else None,
        "available_to":   offer.available_to.isoformat() if offer.available_to else None,
        "price":          offer.price,
        "price_usd":      offer.price_usd,
        "status":         offer.status,
        "urgent":         offer.urgent,
        "notes":          offer.notes,
        "views":          offer.views or 0,
        "is_demo":        offer.is_demo,
        "created_at":     offer.created_at.isoformat() if offer.created_at else None,
        # Контакты только через сделку (ADR-013 B)
        "owner_phone":    user.phone if (user and show_contacts) else None,
        "owner_email":    user.email if (user and show_contacts) else None,
        "company_name":   user.company_name if user else None,
        "rating":         round((user.rating or 50) / 10, 1) if user else 5.0,
        "trips_count":    user.trips_count or 0 if user else 0,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
async def list_transport_offers(
    from_city:   Optional[str] = Query(None),
    to_city:     Optional[str] = Query(None),
    truck_type:  Optional[str] = Query(None),
    min_cap_kg:  Optional[float] = Query(None),
    limit:       int = Query(50, le=200),
    offset:      int = Query(0, ge=0),
    db:          AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    """Публичный список транспортных предложений с фильтрами."""
    q = select(TransportOffer).where(TransportOffer.status == "active")
    if from_city:
        q = q.where(TransportOffer.from_city.ilike(f"%{from_city}%"))
    if to_city:
        q = q.where(TransportOffer.to_city.ilike(f"%{to_city}%"))
    if truck_type:
        q = q.where(TransportOffer.truck_type == truck_type)
    if min_cap_kg:
        q = q.where(TransportOffer.capacity_kg >= min_cap_kg)

    count_res = await db.execute(select(func.count()).select_from(
        q.subquery()
    ))
    total = count_res.scalar_one()

    q = q.order_by(TransportOffer.urgent.desc(), TransportOffer.created_at.desc())
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    offers = result.scalars().all()

    out = []
    for o in offers:
        u_res = await db.execute(select(User).where(User.id == o.user_id))
        u = u_res.scalar_one_or_none()
        out.append(_offer_to_dict(o, u))

    return {"offers": out, "total": total, "limit": limit, "offset": offset}


@router.post("/", status_code=201)
async def create_transport_offer(
    data:             TransportOfferCreate,
    background_tasks: BackgroundTasks,
    db:               AsyncSession = Depends(get_db),
    current_user:     User = Depends(require_user),
):
    """Перевозчик публикует транспортное предложение."""
    if data.available_to and data.available_to <= data.available_from:
        raise HTTPException(422, "available_to должно быть позже available_from")

    offer = TransportOffer(
        user_id        = current_user.id,
        from_city      = data.from_city,
        to_city        = data.to_city,
        truck_type     = data.truck_type,
        capacity_kg    = data.capacity_kg,
        available_from = data.available_from,
        available_to   = data.available_to,
        price          = data.price,
        price_usd      = data.price_usd,
        urgent         = data.urgent,
        notes          = data.notes,
        status         = "active",
    )
    db.add(offer)
    await db.commit()
    await db.refresh(offer)

    # Этап 3: матчинг с TransportSubscription в фоне
    from app.services.transport_matcher import notify_transport_subscribers
    background_tasks.add_task(notify_transport_subscribers, offer, db)

    return {"ok": True, "offer": _offer_to_dict(offer, current_user)}


@router.get("/my")
async def my_transport_offers(
    limit:  int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db:     AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Мои транспортные предложения."""
    count_res = await db.execute(
        select(func.count()).where(TransportOffer.user_id == current_user.id)
    )
    total = count_res.scalar_one()
    result = await db.execute(
        select(TransportOffer)
        .where(TransportOffer.user_id == current_user.id)
        .order_by(TransportOffer.created_at.desc())
        .limit(limit).offset(offset)
    )
    offers = result.scalars().all()
    return {
        "offers": [_offer_to_dict(o, current_user, show_contacts=True) for o in offers],
        "total": total,
    }


@router.get("/{offer_id}")
async def get_transport_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    """Детали транспортного предложения. Контакты — только через сделку (ADR-013 B)."""
    result = await db.execute(select(TransportOffer).where(TransportOffer.id == offer_id))
    offer = result.scalar_one_or_none()
    if not offer:
        raise HTTPException(404, "Предложение не найдено")
    offer.views = (offer.views or 0) + 1
    await db.commit()
    u_res = await db.execute(select(User).where(User.id == offer.user_id))
    u = u_res.scalar_one_or_none()
    return _offer_to_dict(offer, u, show_contacts=False)   # контакты всегда скрыты


@router.patch("/{offer_id}")
async def update_transport_offer(
    offer_id: int,
    data: TransportOfferPatch,
    db:   AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Изменить своё транспортное предложение."""
    result = await db.execute(select(TransportOffer).where(TransportOffer.id == offer_id))
    offer = result.scalar_one_or_none()
    if not offer:
        raise HTTPException(404, "Предложение не найдено")
    if offer.user_id != current_user.id:
        raise HTTPException(403, "Это не ваше предложение")
    if offer.status in ("taken", "completed"):
        raise HTTPException(400, f"Нельзя изменить предложение со статусом {offer.status}")

    # Статус-машина: только active → canceled разрешён владельцу
    if data.status is not None:
        if data.status == "canceled" and offer.status == "active":
            offer.status = "canceled"
        else:
            raise HTTPException(400, f"Недопустимый переход статуса: {offer.status} → {data.status}")

    for field in ("from_city", "to_city", "truck_type", "capacity_kg",
                  "available_from", "available_to", "price", "price_usd",
                  "urgent", "notes"):
        val = getattr(data, field)
        if val is not None:
            setattr(offer, field, val)

    await db.commit()
    await db.refresh(offer)
    return {"ok": True, "offer": _offer_to_dict(offer, current_user)}


@router.delete("/{offer_id}")
async def delete_transport_offer(
    offer_id: int,
    db:   AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Снять предложение (переход в canceled, не физическое удаление)."""
    result = await db.execute(select(TransportOffer).where(TransportOffer.id == offer_id))
    offer = result.scalar_one_or_none()
    if not offer:
        raise HTTPException(404, "Предложение не найдено")
    if offer.user_id != current_user.id:
        raise HTTPException(403, "Это не ваше предложение")
    if offer.status == "taken":
        raise HTTPException(400, "Нельзя снять предложение — по нему активная сделка")
    offer.status = "canceled"
    await db.commit()
    return {"ok": True, "offer_id": offer_id, "status": "canceled"}
