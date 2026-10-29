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
from sqlalchemy import select, func, or_
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Literal, Annotated
from datetime import datetime, timezone

from app.services.listing_freshness import current_transport_conditions, date_is_current, transport_availability_metadata
from app.services.transport_capacity import (TRUCK_TYPES, canonical_truck_type,
    validate_transport_capacity, capacity_metadata)
from app.services.route_locations import RouteLocationInput, location_filter_clause
from app.services.public_ratings import public_ratings, public_rating_fields
from app.database import get_db
from app.models.transport_offer import TransportOffer
from app.models.user import User
from app.routers.auth import require_user
from app.services.city_identity import (
    city_registry, city_filter_clause, route_scope_clause,
    public_route_metadata, apply_publication_cities,
)

router = APIRouter(prefix="/api/transport", tags=["transport"])

# ── Pydantic schemas ──────────────────────────────────────────────────────────

VALID_TRUCK_TYPES = TRUCK_TYPES

class TransportOfferCreate(BaseModel):
    from_location: Optional[RouteLocationInput] = None
    to_location: Optional[RouteLocationInput] = None
    from_city:      str
    to_city:        str
    from_city_id: Optional[int] = Field(None, ge=1, strict=True)
    to_city_id: Optional[int] = Field(None, ge=1, strict=True)
    from_city_key: Optional[str] = Field(None, max_length=150)
    to_city_key: Optional[str] = Field(None, max_length=150)
    truck_type:     str
    capacity_kg:    float = Field(gt=0, le=100000, allow_inf_nan=False)
    available_from: datetime
    available_to:   Optional[datetime] = None
    price:          Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    price_usd:      Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
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

    @field_validator("capacity_kg", mode="before")
    @classmethod
    def validate_capacity(cls, v):
        if isinstance(v, bool):
            raise ValueError("Грузоподъёмность должна быть числом")
        return v

    @field_validator("truck_type")
    @classmethod
    def validate_truck_type(cls, value):
        value = canonical_truck_type(value)
        if value not in VALID_TRUCK_TYPES:
            raise ValueError("Выберите допустимый тип кузова")
        return value

    @model_validator(mode="after")
    def validate_body_capacity(self):
        validate_transport_capacity(self.truck_type, self.capacity_kg)
        return self

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if v is not None and v < 0:
            raise ValueError("Цена не может быть отрицательной")
        return v


class TransportOfferPatch(BaseModel):
    from_location: Optional[RouteLocationInput] = None
    to_location: Optional[RouteLocationInput] = None
    from_city:      Optional[str] = None
    to_city:        Optional[str] = None
    from_city_id: Optional[int] = Field(None, ge=1, strict=True)
    to_city_id: Optional[int] = Field(None, ge=1, strict=True)
    from_city_key: Optional[str] = Field(None, max_length=150)
    to_city_key: Optional[str] = Field(None, max_length=150)
    truck_type:     Optional[str] = None
    capacity_kg:    Optional[float] = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
    available_from: Optional[datetime] = None
    available_to:   Optional[datetime] = None
    price:          Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    price_usd:      Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    urgent:         Optional[bool] = None
    notes:          Optional[str] = None
    status:         Optional[str] = None   # перевозчик может снять: active→canceled
    confirm_availability: bool = False

    _validate_capacity = field_validator("capacity_kg", mode="before")(TransportOfferCreate.validate_capacity.__func__)
    _validate_truck_type = field_validator("truck_type")(TransportOfferCreate.validate_truck_type.__func__)

    @model_validator(mode="after")
    def validate_body_capacity(self):
        if self.truck_type is not None and self.capacity_kg is not None:
            validate_transport_capacity(self.truck_type, self.capacity_kg)
        return self


# ── Helpers ───────────────────────────────────────────────────────────────────

def _offer_to_dict(offer: TransportOffer, user: User = None,
                   show_contacts: bool = False, review_summary=None, registry=None) -> dict:
    return {
        "id":             offer.id,
        **public_route_metadata(offer, registry),
        "user_id":        offer.user_id,
        "from_city":      offer.from_city,
        "to_city":        offer.to_city,
        "truck_type":     offer.truck_type,
        "capacity_kg":    offer.capacity_kg,
        "available_from": offer.available_from.isoformat() if offer.available_from else None,
        "available_to":   offer.available_to.isoformat() if offer.available_to else None,
        "dates_expired":  not date_is_current(offer.available_to or offer.available_from),
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
        **public_rating_fields(review_summary),
        **transport_availability_metadata(offer),
        **capacity_metadata(offer.truck_type, offer.capacity_kg),
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
    available_only: bool = False,
    db:          AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
    scope: Annotated[Optional[Literal["local", "intl"]], Query()] = None,
    from_city_id: Annotated[Optional[int], Query(ge=1)] = None,
    to_city_id: Annotated[Optional[int], Query(ge=1)] = None,
    from_city_key: Annotated[Optional[str], Query(max_length=150)] = None,
    to_city_key: Annotated[Optional[str], Query(max_length=150)] = None,
    from_location_key: Annotated[Optional[str], Query(max_length=150)] = None,
    to_location_key: Annotated[Optional[str], Query(max_length=150)] = None,
):
    """Каталог перевозчиков; прошедшие даты скрываются только по available_only."""
    registry = await city_registry(db)
    q = select(TransportOffer).where(
        TransportOffer.status == "active", TransportOffer.is_demo.is_(False)
    )
    if available_only:
        q = q.where(*current_transport_conditions())
    try:
        for prefix, text, identity, key, location_key in (
            ("from", from_city, from_city_id, from_city_key, from_location_key),
            ("to", to_city, to_city_id, to_city_key, to_location_key),
        ):
            if text or identity is not None or key or location_key:
                special = location_filter_clause(TransportOffer, prefix, text=text, key=location_key)
                if location_key:
                    if special is None:
                        raise ValueError("Неизвестный идентификатор точки")
                    q = q.where(special)
                else:
                    legacy = await city_filter_clause(db, registry,
                        getattr(TransportOffer, prefix + "_city"), getattr(TransportOffer, prefix + "_city_id"),
                        text=text, city_id=identity, city_key=key)
                    q = q.where(or_(legacy, special) if special is not None else legacy)
        if scope:
            q = q.where(await route_scope_clause(db, registry, TransportOffer, scope))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
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
    ratings = await public_ratings(db, [offer.user_id for offer in offers])

    out = []
    for o in offers:
        u_res = await db.execute(select(User).where(User.id == o.user_id))
        u = u_res.scalar_one_or_none()
        out.append(_offer_to_dict(o, u, review_summary=ratings.get(o.user_id), registry=registry))

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

    resolved = data.model_dump()
    try:
        registry = await apply_publication_cities(db, resolved)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    offer = TransportOffer(
        user_id        = current_user.id,
        from_city      = resolved["from_city"],
        to_city        = resolved["to_city"],
        from_city_id   = resolved["from_city_id"],
        to_city_id     = resolved["to_city_id"],
        from_location = resolved.get("from_location"),
        to_location = resolved.get("to_location"),
        truck_type     = data.truck_type,
        capacity_kg    = data.capacity_kg,
        available_from = data.available_from,
        available_to   = data.available_to,
        price          = data.price,
        price_usd      = data.price_usd,
        urgent         = data.urgent,
        notes          = data.notes,
        status         = "active",
        last_confirmed_at = datetime.now(timezone.utc),
    )
    db.add(offer)
    await db.commit()
    await db.refresh(offer)

    # Этап 3: матчинг с TransportSubscription в фоне
    from app.services.transport_matcher import notify_transport_subscribers
    background_tasks.add_task(notify_transport_subscribers, offer, db)

    ratings = await public_ratings(db, [current_user.id])
    return {"ok": True, "offer": _offer_to_dict(offer, current_user, review_summary=ratings.get(current_user.id), registry=registry)}


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
    ratings = await public_ratings(db, [current_user.id])
    return {
        "offers": [_offer_to_dict(o, current_user, show_contacts=True,
                    review_summary=ratings.get(current_user.id)) for o in offers],
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
    ratings = await public_ratings(db, [offer.user_id])
    return _offer_to_dict(offer, u, show_contacts=False,
                         review_summary=ratings.get(offer.user_id))   # контакты всегда скрыты


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

    # Validate the merged state before changing any ORM value. A one-field PATCH
    # cannot turn an existing valid van into a 100 t van. Cancelling legacy bad
    # rows remains possible and never requires silently changing their data.
    def utc(value):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    start = data.available_from if "available_from" in data.model_fields_set else offer.available_from
    end = data.available_to if "available_to" in data.model_fields_set else offer.available_to
    if start is None:
        raise HTTPException(422, "Укажите дату доступности")
    dates_changed = (utc(start) != utc(offer.available_from) or utc(end) != utc(offer.available_to))
    # Resending unchanged fields in an ordinary edit is not confirmation.
    reconfirm = data.confirm_availability or (dates_changed and date_is_current(end or start))
    if reconfirm or dates_changed or {"truck_type", "capacity_kg"} & data.model_fields_set:
        try:
            validate_transport_capacity(data.truck_type or offer.truck_type,
                data.capacity_kg if data.capacity_kg is not None else offer.capacity_kg)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    if end and utc(end) <= utc(start):
        raise HTTPException(422, "available_to должно быть позже available_from")
    if data.confirm_availability and not date_is_current(end or start):
        raise HTTPException(422, "Обновите даты доступности перед подтверждением")

    # Статус-машина: только active → canceled разрешён владельцу
    if data.status is not None:
        if data.status == "canceled" and offer.status == "active":
            offer.status = "canceled"
        else:
            raise HTTPException(400, f"Недопустимый переход статуса: {offer.status} → {data.status}")

    updates = data.model_dump(exclude_unset=True)
    try:
        registry = await apply_publication_cities(db, updates, existing=offer)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for field in ("from_city", "to_city", "from_city_id", "to_city_id", "from_location", "to_location",
                  "truck_type", "capacity_kg", "available_from", "available_to",
                  "price", "price_usd", "urgent", "notes"):
        if field in updates and (updates[field] is not None or field.endswith("_city_id") or field in ("available_to", "from_location", "to_location")):
            setattr(offer, field, updates[field])

    if reconfirm and offer.status == "active":
        offer.last_confirmed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(offer)
    ratings = await public_ratings(db, [current_user.id])
    return {"ok": True, "offer": _offer_to_dict(offer, current_user, review_summary=ratings.get(current_user.id), registry=registry)}


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
