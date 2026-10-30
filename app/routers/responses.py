from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models.user import User
from app.models.load import Load, LoadStatus
from app.models.response import Response, ResponseStatus
from app.routers.auth import require_user
from app.services.notifications import enqueue_event
# plan_check.check_can_respond удалён (ADR-013 B) — лимиты вернутся с Pro-тарифом

router = APIRouter(prefix="/api/responses", tags=["responses"])

async def send_email(to: str, subject: str, html: str):
    """Compatibility boundary for callers outside the transactional event flow."""
    from app.services.notification_channels import send_email as provider_send_email
    result = await provider_send_email(to, subject, html)
    return result.status == "sent"


class RespondRequest(BaseModel):
    message: Optional[str] = None
    price: Optional[float] = None        # цена в GEL (основная)
    price_usd: Optional[float] = None   # цена в USD (если перевозчик хочет в USD)

class AcceptRequest(BaseModel):
    response_id: int

@router.post("/load/{load_id}")
async def respond_to_load(
    load_id: int,
    data: RespondRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Перевозчик откликается на груз"""
    return await _respond_to_load_impl(load_id, data, request, db, current_user)

async def _respond_to_load_impl(load_id, data, request, db, current_user):
    """Внутренняя реализация — для перехвата traceback"""
    # 2.5.4: idempotency check — защита от двойного отклика (Postgres-backed)
    from app.services.idempotency import check_idempotency, save_idempotency, make_idempotent_response
    cached, replayed = await check_idempotency(request, db, scope=f"respond_to_load:{load_id}", user_id=current_user.id)
    if replayed:
        return make_idempotent_response(cached)

    # Проверяем лимит откликов по тарифному плану
    from app.services.plan_check import check_responses_limit
    ok, limit_err = check_responses_limit(current_user)
    if not ok:
        raise HTTPException(status_code=403, detail=limit_err)

    # Проверяем груз
    load_res = await db.execute(select(Load).where(Load.id == load_id)
                                .with_for_update().execution_options(populate_existing=True))
    load = load_res.scalar_one_or_none()
    # A concurrent retry may have committed its cache while we waited for the load.
    cached, replayed = await check_idempotency(request, db, scope=f"respond_to_load:{load_id}",
                                               user_id=current_user.id)
    if replayed:
        return make_idempotent_response(cached)
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")
    # ADR-012: демо-грузы не принимают реальные отклики
    if getattr(load, 'is_demo', False):
        raise HTTPException(status_code=400, detail="Demo loads cannot receive responses")
    if load.status != LoadStatus.active:
        raise HTTPException(status_code=400, detail="Load is no longer available")
    if load.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot respond to your own load")

    # Проверяем дубликат
    existing = await db.execute(
        select(Response).where(Response.load_id == load_id, Response.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Already responded")

    # ADR-006: получаем курс NBG, заполняем обе валюты
    from app.services.exchange_rate import get_usd_gel_rate, convert_gel_to_usd, convert_usd_to_gel
    rate = await get_usd_gel_rate()

    price_gel = data.price  # price — это GEL по умолчанию
    price_usd = data.price_usd

    if price_gel and not price_usd:
        price_usd = convert_gel_to_usd(price_gel, rate)
    elif price_usd and not price_gel:
        price_gel = convert_usd_to_gel(price_usd, rate)

    # Категория 4 Part A: XSS-санитизация сообщения отклика
    from app.services.normalizers import sanitize_text
    safe_message = sanitize_text(data.message, max_length=500) if data.message else None

    # Создаём отклик
    resp = Response(
        load_id=load_id,
        user_id=current_user.id,
        message=safe_message,
        price_gel=price_gel,
        price_usd=price_usd,
        exchange_rate_at_creation=rate,
        status=ResponseStatus.pending
    )
    db.add(resp)

    # Увеличиваем счётчик откликов (для всех планов с лимитом)
    from datetime import datetime, timezone
    from app.services.plan_check import get_limits
    if get_limits(current_user)["responses"] > 0:
        current_user.responses_this_month = (current_user.responses_this_month or 0) + 1
        if current_user.responses_month_reset is None:
            current_user.responses_month_reset = datetime.utcnow()  # naive UTC — matches DB TIMESTAMP WITHOUT TIME ZONE

    await db.flush()
    await enqueue_event(
        db, event_key=f"response:{resp.id}:created", kind="new_response",
        recipient_ids=[load.user_id], actor_id=current_user.id,
        data={"source": "cargo", "load_id": load.id, "response_id": resp.id,
              "from_city": load.from_city, "to_city": load.to_city,
              "price": float(price_gel) if price_gel is not None else None, "currency": "GEL"},
    )
    resp_result = {"ok": True, "response_id": resp.id,
                   "status": resp.status.value if hasattr(resp.status, "value") else str(resp.status)}
    # The cache, response and event share the same commit. Without a key the
    # cache helper is a no-op, so the explicit commit is still required.
    await save_idempotency(request, db, scope=f"respond_to_load:{load_id}",
                           user_id=current_user.id, response_status=200,
                           response_body=resp_result, strict=True)
    await db.commit()
    return resp_result


@router.get("/load/{load_id}")
async def get_load_responses(
    load_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Грузоотправитель видит отклики на свой груз"""
    load_res = await db.execute(select(Load).where(Load.id == load_id))
    load = load_res.scalar_one_or_none()
    if not load or load.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your load")

    resp_res = await db.execute(
        select(Response).where(Response.load_id == load_id)
    )
    responses = resp_res.scalars().all()

    result = []
    for r in responses:
        carrier_res = await db.execute(select(User).where(User.id == r.user_id))
        carrier = carrier_res.scalar_one_or_none()
        # ADR-013: контакты перевозчика только после принятия отклика
        resp_accepted = (r.status.value if hasattr(r.status, 'value') else str(r.status)) == "accepted"
        result.append({
            "id": r.id,
            "carrier_id": r.user_id,
            # ADR-013: имя перевозчика скрыто до принятия отклика
            "carrier_name": carrier.company_name if (carrier and resp_accepted) else None,
            "carrier_phone": carrier.phone if (carrier and resp_accepted) else None,
            "carrier_email": carrier.email if (carrier and resp_accepted) else None,
            "message": r.message,
            "price": float(r.price_gel) if r.price_gel else (float(r.price_usd) if r.price_usd else None),
            "currency": "GEL" if r.price_gel else ("USD" if r.price_usd else None),
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"responses": result, "total": len(result)}

@router.get("/my")
async def my_responses(
    limit:  int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Перевозчик видит свои отклики (с пагинацией)."""
    # Общее кол-во
    count_res = await db.execute(
        select(func.count()).where(Response.user_id == current_user.id)
    )
    total = count_res.scalar_one()

    resp_res = await db.execute(
        select(Response)
        .where(Response.user_id == current_user.id)
        .order_by(Response.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    responses = resp_res.scalars().all()

    result = []
    for r in responses:
        load_res = await db.execute(select(Load).where(Load.id == r.load_id))
        load = load_res.scalar_one_or_none()
        result.append({
            "id": r.id,
            "load_id": r.load_id,
            "shipper_id": load.user_id if load else None,
            "from": load.from_city if load else "—",
            "to": load.to_city if load else "—",
            "price": float(r.price_gel) if r.price_gel else (float(r.price_usd) if r.price_usd else None),
            "currency": "GEL" if r.price_gel else ("USD" if r.price_usd else None),
            "message": r.message,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"responses": result, "total": total, "limit": limit, "offset": offset}

@router.post("/accept/{response_id}")
async def accept_response(
    response_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Accept one response and record its deal and notifications atomically."""
    from app.services.idempotency import check_idempotency, save_idempotency, make_idempotent_response
    from app.services.state_machine import validate_transition
    from app.services.audit_log import log_status_change
    from app.models.deal import Deal, DealStatus
    from app.routers.deals import _act_number, _enqueue_deal_created
    from app.services.exchange_rate import get_usd_gel_rate, convert_gel_to_usd, convert_usd_to_gel

    scope = f"accept_response:{response_id}"
    cached, replayed = await check_idempotency(request, db, scope=scope, user_id=current_user.id)
    if replayed:
        return make_idempotent_response(cached)
    resp = (await db.execute(select(Response).where(Response.id == response_id))).scalar_one_or_none()
    if resp is None:
        raise HTTPException(404, "Response not found")
    # Every accept/create path locks the source before its response.
    load = (await db.execute(select(Load).where(Load.id == resp.load_id)
                             .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if load is None or load.user_id != current_user.id:
        raise HTTPException(403, "Not your load")
    cached, replayed = await check_idempotency(request, db, scope=scope, user_id=current_user.id)
    if replayed:
        return make_idempotent_response(cached)
    resp = (await db.execute(select(Response).where(Response.id == response_id)
                             .with_for_update().execution_options(populate_existing=True))).scalar_one()
    existing = (await db.execute(select(Deal.id).where(
        Deal.load_id == load.id, Deal.status != DealStatus.canceled))).first()
    if existing:
        raise HTTPException(409, "Deal already exists for this load")
    if load.status != LoadStatus.active:
        raise HTTPException(400, "Load is no longer available")
    previous = resp.status.value if hasattr(resp.status, "value") else str(resp.status)
    validate_transition("response", previous, "accepted")

    carrier = await db.get(User, resp.user_id)
    if carrier is None or carrier.is_deleted or not carrier.is_active:
        raise HTTPException(400, "Перевозчик недоступен")

    deal_rate = await get_usd_gel_rate()
    agreed_gel = resp.price_gel or load.price_gel
    agreed_usd = resp.price_usd or load.price_usd
    if agreed_gel and not agreed_usd:
        agreed_usd = convert_gel_to_usd(agreed_gel, deal_rate)
    elif agreed_usd and not agreed_gel:
        agreed_gel = convert_usd_to_gel(agreed_usd, deal_rate)
    resp.status = ResponseStatus.accepted
    load.status = LoadStatus.taken
    await log_status_change(db, "response", resp.id, previous, "accepted", current_user.id)
    others = (await db.execute(select(Response).where(
        Response.load_id == load.id, Response.id != response_id,
        Response.status == ResponseStatus.pending).order_by(Response.id)
        .with_for_update().execution_options(populate_existing=True))).scalars().all()
    for other in others:
        other.status = ResponseStatus.rejected
        await log_status_change(db, "response", other.id, "pending", "rejected", current_user.id,
                                reason="auto-rejected: another response accepted")
        await _enqueue_response_rejected(db, other, load, current_user.id)

    deal = Deal(load_id=load.id, response_id=resp.id, shipper_id=current_user.id,
                carrier_id=resp.user_id, status=DealStatus.confirmed,
                agreed_price=agreed_gel or 0, currency="GEL",
                exchange_rate_snapshot=deal_rate, final_price_gel=agreed_gel,
                final_price_usd=agreed_usd)
    db.add(deal)
    await db.flush()
    deal.act_number = _act_number(deal.id)
    await _enqueue_deal_created(db, deal, current_user.id)
    result = {"ok": True, "deal_id": deal.id, "deal_number": deal.act_number,
              "status": deal.status.value}
    await save_idempotency(request, db, scope=scope, user_id=current_user.id,
                           response_status=200, response_body=result, strict=True)
    await db.commit()
    return result


async def _enqueue_response_rejected(db, response, load, actor_id):
    price = response.price_gel if response.price_gel is not None else response.price_usd
    await enqueue_event(
        db, event_key=f"response:{response.id}:rejected", kind="response_rejected",
        recipient_ids=[response.user_id], actor_id=actor_id,
        data={"source": "cargo", "load_id": load.id, "response_id": response.id,
              "from_city": load.from_city, "to_city": load.to_city,
              "price": float(price) if price is not None else None,
              "currency": "GEL" if response.price_gel is not None else "USD"},
    )


@router.post("/reject/{response_id}")
async def reject_response(
    response_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    resp = (await db.execute(select(Response).where(Response.id == response_id))).scalar_one_or_none()
    if resp is None:
        raise HTTPException(404, "Response not found")
    load = (await db.execute(select(Load).where(Load.id == resp.load_id)
                             .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if load is None or load.user_id != current_user.id:
        raise HTTPException(403, "Not your load")
    resp = (await db.execute(select(Response).where(Response.id == response_id)
                             .with_for_update().execution_options(populate_existing=True))).scalar_one()
    if resp.status == ResponseStatus.rejected:
        return {"ok": True}
    if resp.status != ResponseStatus.pending:
        raise HTTPException(400, "Response is already processed")
    resp.status = ResponseStatus.rejected
    await _enqueue_response_rejected(db, resp, load, current_user.id)
    await db.commit()
    return {"ok": True}


@router.delete("/cancel/{response_id}")
async def cancel_response(
    response_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """
    Перевозчик отзывает свой отклик (только pending → withdrawn).
    Трек 8: ADR-008 withdrawn. Запись не удаляется — меняется статус.
    """
    from app.services.state_machine import validate_transition
    from app.services.audit_log import log_status_change

    resp_res = await db.execute(select(Response).where(Response.id == response_id))
    resp = resp_res.scalar_one_or_none()
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")
    if resp.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your response")

    await db.execute(select(Load).where(Load.id == resp.load_id)
                     .with_for_update().execution_options(populate_existing=True))
    resp = (await db.execute(select(Response).where(Response.id == response_id)
                             .with_for_update().execution_options(populate_existing=True))).scalar_one()
    current_status = resp.status.value if hasattr(resp.status, 'value') else str(resp.status)
    validate_transition("response", current_status, "withdrawn")

    resp.status = ResponseStatus.withdrawn
    await log_status_change(db, "response", resp.id, current_status, "withdrawn", current_user.id)
    await db.commit()
    return {"ok": True, "status": "withdrawn"}


@router.post("/debug/test-load/{load_id}")
async def debug_test_respond(
    load_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Debug endpoint — диагностика ошибки отклика"""
    import traceback
    try:
        from app.services.exchange_rate import get_usd_gel_rate
        rate = await get_usd_gel_rate()
        load_res = await db.execute(select(Load).where(Load.id == load_id))
        load = load_res.scalar_one_or_none()
        return {
            "rate": rate,
            "load": str(load),
            "load_status": str(load.status) if load else None,
            "user_plan": current_user.plan,
            "responses_this_month": current_user.responses_this_month,
        }
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()[-1000:]}
