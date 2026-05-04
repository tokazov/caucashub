"""
TransportRequest CRUD — отклики грузовладельцев на транспортные предложения (ADR-016).

Эндпоинты:
  POST   /api/transport/{offer_id}/request   — откликнуться (грузовладелец)
  GET    /api/transport-requests/my          — мои отклики (грузовладелец)
  GET    /api/transport/{offer_id}/requests  — отклики на моё предложение (перевозчик)
  DELETE /api/transport-requests/{id}        — отозвать отклик (грузовладелец)

Статус-машина TransportRequest:
  pending → accepted  (перевозчик принял → creates Deal)
  pending → rejected  (перевозчик отклонил)
  pending → canceled  (грузовладелец отозвал)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.transport_offer import TransportOffer
from app.models.transport_request import TransportRequest
from app.models.deal import Deal, DealStatus
from app.models.user import User
from app.routers.auth import require_user
from app.services.user_display import display_name, display_phone

router = APIRouter(tags=["transport-requests"])


class TransportRequestCreate(BaseModel):
    cargo_description: Optional[str] = None
    weight_kg:         Optional[float] = None
    price:             Optional[float] = None
    message:           Optional[str] = None


def _req_to_dict(r: TransportRequest, show_contacts: bool = False,
                 shipper: User = None) -> dict:
    return {
        "id":                  r.id,
        "transport_offer_id":  r.transport_offer_id,
        "user_id":             r.user_id,
        "cargo_description":   r.cargo_description,
        "weight_kg":           r.weight_kg,
        "price":               r.price,
        "message":             r.message,
        "status":              r.status,
        "created_at":          r.created_at.isoformat() if r.created_at else None,
        # Контакты — только если участник сделки (ADR-013 B)
        "shipper_name":  display_name(shipper) if shipper else None,
        "shipper_phone": display_phone(shipper) if (shipper and show_contacts) else None,
    }


# ── Создать отклик ────────────────────────────────────────────────────────────

@router.post("/api/transport/{offer_id}/request", status_code=201)
async def create_transport_request(
    offer_id: int,
    data: TransportRequestCreate,
    db:   AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Грузовладелец откликается на транспортное предложение."""
    offer_res = await db.execute(select(TransportOffer).where(TransportOffer.id == offer_id))
    offer = offer_res.scalar_one_or_none()
    if not offer:
        raise HTTPException(404, "Предложение не найдено")
    if offer.status != "active":
        raise HTTPException(400, f"Предложение недоступно (статус: {offer.status})")
    if offer.user_id == current_user.id:
        raise HTTPException(400, "Нельзя откликаться на собственное предложение")

    # Проверяем дубль
    dup = await db.execute(
        select(TransportRequest).where(
            TransportRequest.transport_offer_id == offer_id,
            TransportRequest.user_id == current_user.id,
            TransportRequest.status == "pending",
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(409, "Вы уже откликнулись на это предложение")

    req = TransportRequest(
        transport_offer_id = offer_id,
        user_id            = current_user.id,
        cargo_description  = data.cargo_description,
        weight_kg          = data.weight_kg,
        price              = data.price,
        message            = data.message,
        status             = "pending",
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return {"ok": True, "request": _req_to_dict(req)}


# ── Мои отклики ───────────────────────────────────────────────────────────────

@router.get("/api/transport-requests/my")
async def my_transport_requests(
    limit:  int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db:     AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Мои отклики на транспортные предложения (грузовладелец)."""
    count_res = await db.execute(
        select(func.count()).where(TransportRequest.user_id == current_user.id)
    )
    total = count_res.scalar_one()
    result = await db.execute(
        select(TransportRequest)
        .where(TransportRequest.user_id == current_user.id)
        .order_by(TransportRequest.created_at.desc())
        .limit(limit).offset(offset)
    )
    reqs = result.scalars().all()
    return {
        "requests": [_req_to_dict(r, show_contacts=False) for r in reqs],
        "total": total, "limit": limit, "offset": offset,
    }


# ── Отклики на моё предложение ────────────────────────────────────────────────

@router.get("/api/transport/{offer_id}/requests")
async def offer_requests(
    offer_id: int,
    db:       AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Список откликов на транспортное предложение (только для владельца предложения)."""
    offer_res = await db.execute(select(TransportOffer).where(TransportOffer.id == offer_id))
    offer = offer_res.scalar_one_or_none()
    if not offer:
        raise HTTPException(404, "Предложение не найдено")
    if offer.user_id != current_user.id:
        raise HTTPException(403, "Это не ваше предложение")

    result = await db.execute(
        select(TransportRequest)
        .where(TransportRequest.transport_offer_id == offer_id)
        .order_by(TransportRequest.created_at.desc())
    )
    reqs = result.scalars().all()
    out = []
    for r in reqs:
        shipper_res = await db.execute(select(User).where(User.id == r.user_id))
        shipper = shipper_res.scalar_one_or_none()
        # Контакты видны перевозчику если уже принял (сделка создана)
        show = (r.status == "accepted")
        out.append(_req_to_dict(r, show_contacts=show, shipper=shipper))
    return {"requests": out, "total": len(out)}


# ── Принять отклик ────────────────────────────────────────────────────────────

@router.post("/api/transport-requests/{req_id}/accept")
async def accept_transport_request(
    req_id: int,
    db:     AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Перевозчик принимает отклик → создаётся Deal (transport_offer_id заполнен)."""
    req_res = await db.execute(select(TransportRequest).where(TransportRequest.id == req_id))
    req = req_res.scalar_one_or_none()
    if not req:
        raise HTTPException(404, "Отклик не найден")

    offer_res = await db.execute(select(TransportOffer).where(TransportOffer.id == req.transport_offer_id))
    offer = offer_res.scalar_one_or_none()
    if not offer or offer.user_id != current_user.id:
        raise HTTPException(403, "Это не ваше предложение")
    if req.status != "pending":
        raise HTTPException(400, f"Отклик уже обработан: {req.status}")
    if offer.status != "active":
        raise HTTPException(400, f"Предложение недоступно: {offer.status}")

    # Меняем статусы
    req.status = "accepted"
    offer.status = "taken"

    # Создаём Deal
    from app.routers.deals import _act_number
    # Определяем agreed_price (из отклика или из предложения)
    agreed_price = req.price or offer.price

    deal = Deal(
        load_id              = None,                   # transport-путь
        transport_offer_id   = offer.id,
        transport_request_id = req.id,
        shipper_id           = req.user_id,            # грузовладелец → откликался
        carrier_id           = current_user.id,        # перевозчик → владелец offer
        response_id          = None,
        status               = DealStatus.confirmed,
        agreed_price         = agreed_price,
        currency             = "GEL",
    )
    db.add(deal)
    await db.flush()   # получаем deal.id
    deal.act_number = _act_number(deal.id)
    await db.commit()
    await db.refresh(deal)

    return {
        "ok":         True,
        "deal_id":    deal.id,
        "act_number": deal.act_number,
        "status":     deal.status.value,
    }


# ── Отклонить отклик ──────────────────────────────────────────────────────────

@router.post("/api/transport-requests/{req_id}/reject")
async def reject_transport_request(
    req_id: int,
    db:     AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Перевозчик отклоняет отклик."""
    req_res = await db.execute(select(TransportRequest).where(TransportRequest.id == req_id))
    req = req_res.scalar_one_or_none()
    if not req:
        raise HTTPException(404, "Отклик не найден")
    offer_res = await db.execute(select(TransportOffer).where(TransportOffer.id == req.transport_offer_id))
    offer = offer_res.scalar_one_or_none()
    if not offer or offer.user_id != current_user.id:
        raise HTTPException(403, "Это не ваше предложение")
    if req.status != "pending":
        raise HTTPException(400, f"Отклик уже обработан: {req.status}")

    req.status = "rejected"
    await db.commit()
    return {"ok": True, "request_id": req_id, "status": "rejected"}


# ── Отозвать отклик ───────────────────────────────────────────────────────────

@router.delete("/api/transport-requests/{req_id}")
async def cancel_transport_request(
    req_id: int,
    db:     AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Грузовладелец отзывает свой отклик."""
    req_res = await db.execute(select(TransportRequest).where(TransportRequest.id == req_id))
    req = req_res.scalar_one_or_none()
    if not req:
        raise HTTPException(404, "Отклик не найден")
    if req.user_id != current_user.id:
        raise HTTPException(403, "Это не ваш отклик")
    if req.status != "pending":
        raise HTTPException(400, f"Отклик уже обработан: {req.status}")

    req.status = "canceled"
    await db.commit()
    return {"ok": True, "request_id": req_id, "status": "canceled"}
