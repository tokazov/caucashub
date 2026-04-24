from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models.user import User
from app.models.load import Load
from app.models.response import Response, ResponseStatus
from app.routers.auth import require_user
from app.services.telegram_notify import notify_new_response, notify_response_accepted
import httpx
import asyncio

router = APIRouter(prefix="/api/responses", tags=["responses"])

import os

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
RESEND_API_KEY = "re_UesN9evJ_H9Me3arJbM74gL1d2quF2te1"

async def send_email(to: str, subject: str, html: str):
    """Отправка email через Brevo (основной) или Resend (fallback)"""
    if BREVO_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
                    json={
                        "sender": {"name": "CaucasHub", "email": "noreply@caucashub.ge"},
                        "to": [{"email": to}],
                        "subject": subject,
                        "htmlContent": html,
                    },
                    timeout=10
                )
            return
        except Exception:
            pass
    # Fallback: Resend
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={
                    "from": "CaucasHub <noreply@caucashub.ge>",
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
                timeout=10
            )
    except Exception:
        pass  # email не критичен

class RespondRequest(BaseModel):
    message: Optional[str] = None
    price: Optional[float] = None

class AcceptRequest(BaseModel):
    response_id: int

@router.post("/load/{load_id}")
async def respond_to_load(
    load_id: int,
    data: RespondRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Перевозчик откликается на груз"""
    # Проверяем груз
    load_res = await db.execute(select(Load).where(Load.id == load_id))
    load = load_res.scalar_one_or_none()
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")
    if load.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot respond to your own load")

    # Проверяем дубликат
    existing = await db.execute(
        select(Response).where(Response.load_id == load_id, Response.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Already responded")

    # Создаём отклик
    resp = Response(
        load_id=load_id,
        user_id=current_user.id,
        message=data.message,
        price_usd=data.price,
        status=ResponseStatus.pending
    )
    db.add(resp)
    await db.commit()
    await db.refresh(resp)

    # Получаем грузоотправителя
    owner_res = await db.execute(select(User).where(User.id == load.user_id))
    owner = owner_res.scalar_one_or_none()

    # TG-уведомление грузоотправителю
    if owner and owner.telegram_id and not owner.telegram_id.startswith("pending:"):
        carrier_name = current_user.company_name or current_user.email.split("@")[0]
        price_val = float(data.price) if data.price else 0
        asyncio.create_task(notify_new_response(
            owner.telegram_id, carrier_name,
            load.from_city, load.to_city, price_val, "₾"
        ))

    # Email грузоотправителю
    if owner and owner.email:
        carrier_name = current_user.company_name or current_user.email
        route = f"{load.from_city} → {load.to_city}"
        price_text = f"<b>Предложенная цена:</b> {data.price} ₾<br>" if data.price else ""
        msg_text = f"<b>Сообщение:</b> {data.message}<br>" if data.message else ""
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          <div style="background:#1a1a2e;padding:20px;text-align:center">
            <h2 style="color:#f7b731;margin:0">CaucasHub.ge</h2>
          </div>
          <div style="padding:24px;background:#fff">
            <h3>🚛 Новый отклик на ваш груз!</h3>
            <p>Перевозчик <b>{carrier_name}</b> готов везти ваш груз:</p>
            <div style="background:#f8f9fa;border-radius:8px;padding:16px;margin:16px 0">
              <b>Маршрут:</b> {route}<br>
              <b>Перевозчик:</b> {carrier_name}<br>
              {price_text}{msg_text}
            </div>
            <p>Зайдите в <a href="https://caucashub.ge" style="color:#f7b731">личный кабинет</a> 
            → вкладка "Мои заказы" чтобы принять или отклонить.</p>
          </div>
          <div style="background:#f0f2f5;padding:12px;text-align:center;font-size:12px;color:#999">
            CaucasHub.ge — Биржа грузов Кавказа
          </div>
        </div>
        """
        await send_email(owner.email, f"Новый отклик на груз {route}", html)

    return {
        "ok": True,
        "response_id": resp.id,
        "status": resp.status
    }

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
        result.append({
            "id": r.id,
            "carrier_id": r.user_id,
            "carrier_name": carrier.company_name if carrier else "—",
            "carrier_phone": carrier.phone if carrier else None,
            "carrier_email": carrier.email if carrier else None,
            "message": r.message,
            "price": r.price_usd,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"responses": result, "total": len(result)}

@router.get("/my")
async def my_responses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Перевозчик видит свои отклики"""
    resp_res = await db.execute(
        select(Response).where(Response.user_id == current_user.id)
    )
    responses = resp_res.scalars().all()

    result = []
    for r in responses:
        load_res = await db.execute(select(Load).where(Load.id == r.load_id))
        load = load_res.scalar_one_or_none()
        result.append({
            "id": r.id,
            "load_id": r.load_id,
            "from": load.from_city if load else "—",
            "to": load.to_city if load else "—",
            "price": r.price_usd,
            "message": r.message,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {"responses": result, "total": len(result)}

@router.post("/accept/{response_id}")
async def accept_response(
    response_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Грузоотправитель принимает отклик → создаётся сделка"""
    resp_res = await db.execute(select(Response).where(Response.id == response_id))
    resp = resp_res.scalar_one_or_none()
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")

    load_res = await db.execute(select(Load).where(Load.id == resp.load_id))
    load = load_res.scalar_one_or_none()
    if not load or load.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your load")

    # Принимаем отклик, отклоняем остальные
    resp.status = ResponseStatus.accepted
    all_resp = await db.execute(
        select(Response).where(Response.load_id == resp.load_id, Response.id != response_id)
    )
    for other in all_resp.scalars().all():
        other.status = ResponseStatus.rejected

    await db.commit()

    # Создаём сделку
    from app.models.deal import Deal
    # Берём цену: сначала из отклика (перевозчик предложил), потом из груза
    agreed = float(resp.price_usd) if resp.price_usd else None
    if not agreed:
        agreed = float(load.price_gel or load.price_usd or 0)
    currency = "GEL"
    deal = Deal(
        load_id=resp.load_id,
        shipper_id=current_user.id,
        carrier_id=resp.user_id,
        agreed_price=agreed,
        currency=currency,
    )
    db.add(deal)
    await db.commit()
    await db.refresh(deal)

    # TG-уведомление перевозчику
    carrier_res = await db.execute(select(User).where(User.id == resp.user_id))
    carrier = carrier_res.scalar_one_or_none()
    if carrier and carrier.telegram_id and not carrier.telegram_id.startswith("pending:"):
        shipper_name = current_user.company_name or current_user.email.split("@")[0]
        asyncio.create_task(notify_response_accepted(
            carrier.telegram_id, shipper_name,
            load.from_city, load.to_city,
            float(resp.price_usd or load.price_gel or 0), "₾"
        ))

    # Email перевозчику
    if carrier and carrier.email:
        route = f"{load.from_city} → {load.to_city}"
        shipper_name = current_user.company_name or current_user.email
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          <div style="background:#1a1a2e;padding:20px;text-align:center">
            <h2 style="color:#f7b731;margin:0">CaucasHub.ge</h2>
          </div>
          <div style="padding:24px;background:#fff">
            <h3>✅ Ваш отклик принят!</h3>
            <p>Грузоотправитель <b>{shipper_name}</b> принял ваш отклик.</p>
            <div style="background:#e8f5e9;border-radius:8px;padding:16px;margin:16px 0;border-left:4px solid #2ecc71">
              <b>Маршрут:</b> {route}<br>
              <b>Номер сделки:</b> {deal.act_number or f"CH-{deal.id:04d}"}<br>
              <b>Статус:</b> Подтверждена
            </div>
            <div style="background:#f8f9fa;border-radius:8px;padding:16px;margin:16px 0">
              <b>Контакт грузоотправителя:</b><br>
              {f"📞 {current_user.phone}<br>" if current_user.phone else ""}
              📧 {current_user.email}
            </div>
            <p>Зайдите в <a href="https://caucashub.ge" style="color:#f7b731">личный кабинет</a> 
            → "Мои сделки" для управления доставкой.</p>
          </div>
        </div>
        """
        await send_email(carrier.email, f"✅ Ваш отклик принят — {route}", html)

    return {
        "ok": True,
        "deal_id": deal.id,
        "deal_number": deal.act_number or f"CH-{deal.id:04d}",
        "status": deal.status,
    }

@router.post("/reject/{response_id}")
async def reject_response(
    response_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Грузоотправитель отклоняет отклик"""
    resp_res = await db.execute(select(Response).where(Response.id == response_id))
    resp = resp_res.scalar_one_or_none()
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")

    load_res = await db.execute(select(Load).where(Load.id == resp.load_id))
    load = load_res.scalar_one_or_none()
    if not load or load.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your load")

    resp.status = ResponseStatus.rejected
    await db.commit()

    # Email перевозчику
    carrier_res = await db.execute(select(User).where(User.id == resp.user_id))
    carrier = carrier_res.scalar_one_or_none()
    if carrier and carrier.email:
        route = f"{load.from_city} → {load.to_city}"
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px">
          <div style="background:#1a1a2e;padding:20px;text-align:center">
            <h2 style="color:#f7b731;margin:0">CaucasHub.ge</h2>
          </div>
          <div style="padding:24px">
            <h3>ℹ️ Ваш отклик не был выбран</h3>
            <p>К сожалению, грузоотправитель выбрал другого перевозчика для маршрута <b>{route}</b>.</p>
            <p>Не расстраивайтесь — новые грузы появляются каждый день. 
            <a href="https://caucashub.ge" style="color:#f7b731">Смотрите актуальные грузы →</a></p>
          </div>
        </div>
        """
        await send_email(carrier.email, f"ℹ️ Отклик на груз {route}", html)

    return {"ok": True}

@router.delete("/cancel/{response_id}")
async def cancel_response(
    response_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user)
):
    """Перевозчик отзывает свой отклик (только pending)"""
    resp_res = await db.execute(select(Response).where(Response.id == response_id))
    resp = resp_res.scalar_one_or_none()
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")
    if resp.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your response")
    if resp.status != ResponseStatus.pending:
        raise HTTPException(status_code=400, detail="Cannot cancel accepted response")
    await db.delete(resp)
    await db.commit()
    return {"ok": True}
