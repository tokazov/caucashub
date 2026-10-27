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
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
import logging

from app.database import get_db
from app.models.transport_offer import TransportOffer
from app.models.transport_request import TransportRequest
from app.models.deal import Deal, DealStatus
from app.models.user import User
from app.routers.auth import require_user
from app.services.user_display import display_name, display_phone
from app.services.notifications import enqueue_event

logger = logging.getLogger(__name__)

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
    background_tasks: BackgroundTasks,
    db:   AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Грузовладелец откликается на транспортное предложение."""
    offer_res = await db.execute(select(TransportOffer).where(TransportOffer.id == offer_id)
                                 .with_for_update().execution_options(populate_existing=True))
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
    await db.flush()
    await enqueue_event(
        db, event_key=f"transport_request:{req.id}:created", kind="new_transport_request",
        recipient_ids=[offer.user_id], actor_id=current_user.id,
        data={"source": "transport", "transport_offer_id": offer.id,
              "transport_request_id": req.id, "from_city": offer.from_city,
              "to_city": offer.to_city,
              "price": float(req.price) if req.price is not None else None, "currency": "GEL"},
    )
    await db.commit()
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Accept the request, take its source and enqueue both participants atomically."""
    req = (await db.execute(select(TransportRequest).where(TransportRequest.id == req_id))).scalar_one_or_none()
    if req is None:
        raise HTTPException(404, "Отклик не найден")
    offer = (await db.execute(select(TransportOffer).where(TransportOffer.id == req.transport_offer_id)
                              .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if offer is None or offer.user_id != current_user.id:
        raise HTTPException(403, "Это не ваше предложение")
    req = (await db.execute(select(TransportRequest).where(TransportRequest.id == req_id)
                            .with_for_update().execution_options(populate_existing=True))).scalar_one()
    if req.status != "pending":
        raise HTTPException(400, f"Отклик уже обработан: {req.status}")
    if offer.status != "active":
        raise HTTPException(400, f"Предложение недоступно: {offer.status}")
    existing = (await db.execute(select(Deal.id).where(
        Deal.transport_offer_id == offer.id, Deal.status != DealStatus.canceled))).first()
    if existing:
        raise HTTPException(409, "Сделка для этого предложения уже существует")
    req.status = "accepted"
    offer.status = "taken"
    from app.routers.deals import _act_number, _enqueue_deal_created
    deal = Deal(load_id=None, transport_offer_id=offer.id, transport_request_id=req.id,
                shipper_id=req.user_id, carrier_id=current_user.id, response_id=None,
                status=DealStatus.confirmed, agreed_price=req.price or offer.price, currency="GEL")
    db.add(deal)
    await db.flush()
    deal.act_number = _act_number(deal.id)
    await _enqueue_deal_created(db, deal, current_user.id)
    await db.commit()
    return {"ok": True, "deal_id": deal.id, "act_number": deal.act_number, "status": deal.status.value}


# ── Отклонить отклик ──────────────────────────────────────────────────────────

@router.post("/api/transport-requests/{req_id}/reject")
async def reject_transport_request(
    req_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    req = (await db.execute(select(TransportRequest).where(TransportRequest.id == req_id))).scalar_one_or_none()
    if req is None:
        raise HTTPException(404, "Отклик не найден")
    offer = (await db.execute(select(TransportOffer).where(TransportOffer.id == req.transport_offer_id)
                              .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if offer is None or offer.user_id != current_user.id:
        raise HTTPException(403, "Это не ваше предложение")
    req = (await db.execute(select(TransportRequest).where(TransportRequest.id == req_id)
                            .with_for_update().execution_options(populate_existing=True))).scalar_one()
    if req.status == "rejected":
        return {"ok": True, "request_id": req_id, "status": "rejected"}
    if req.status != "pending":
        raise HTTPException(400, f"Отклик уже обработан: {req.status}")
    req.status = "rejected"
    await enqueue_event(
        db, event_key=f"transport_request:{req.id}:rejected", kind="transport_request_rejected",
        recipient_ids=[req.user_id], actor_id=current_user.id,
        data={"source": "transport", "transport_offer_id": offer.id, "transport_request_id": req.id,
              "from_city": offer.from_city, "to_city": offer.to_city,
              "price": float(req.price) if req.price is not None else None, "currency": "GEL"},
    )
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
    await db.execute(select(TransportOffer).where(TransportOffer.id == req.transport_offer_id)
                     .with_for_update().execution_options(populate_existing=True))
    req = (await db.execute(select(TransportRequest).where(TransportRequest.id == req_id)
                            .with_for_update().execution_options(populate_existing=True))).scalar_one()
    if req.status != "pending":
        raise HTTPException(400, f"Отклик уже обработан: {req.status}")

    req.status = "canceled"
    await db.commit()
    return {"ok": True, "request_id": req_id, "status": "canceled"}
