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
from app.services.telegram_notify import (
    notify_new_response, notify_response_accepted, notify_deal_created,
    notify_response_rejected,
)
# plan_check.check_can_respond удалён (ADR-013 B) — лимиты вернутся с Pro-тарифом
import os
import httpx
import asyncio

router = APIRouter(prefix="/api/responses", tags=["responses"])

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
RESEND_API_KEY = "re_UesN9evJ_H9Me3arJbM74gL1d2quF2te1"

# ---------------------------------------------------------------------------
# Email i18n — Georgian first (internal Georgian freight market)
# ---------------------------------------------------------------------------
def _t(lang: str | None, ka: str, ru: str) -> str:
    """Return Georgian text for 'ka' lang, Russian otherwise."""
    return ka if (lang or "ka") == "ka" else ru

def _email_header() -> str:
    return '<div style="background:#1a1a2e;padding:20px;text-align:center"><h2 style="color:#f7b731;margin:0">CaucasHub.ge</h2></div>'

def _email_footer(lang: str | None) -> str:
    return f'<div style="background:#f0f2f5;padding:12px;text-align:center;font-size:12px;color:#999">{_t(lang,"CaucasHub.ge — საქართველოს სატვირთო ბირჟა","CaucasHub.ge — Биржа грузов Грузии")}</div>'

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
    load_res = await db.execute(select(Load).where(Load.id == load_id))
    load = load_res.scalar_one_or_none()
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

    await db.commit()
    await db.refresh(resp)

    # Получаем грузоотправителя
    owner_res = await db.execute(select(User).where(User.id == load.user_id))
    owner = owner_res.scalar_one_or_none()

    # TG-уведомление грузоотправителю
    if owner and owner.telegram_id and not owner.telegram_id.startswith("pending:"):
        try:
            price_val = float(data.price) if data.price else 0
            carrier_rating = round((current_user.rating or 50) / 10, 1)
            carrier_deals = getattr(current_user, 'completed_deals_count', 0) or 0
            asyncio.create_task(notify_new_response(
                owner.telegram_id,
                load.from_city, load.to_city, price_val, "₾",
                carrier_rating=carrier_rating,
                carrier_deals=carrier_deals,
                load_id=load_id,
                lang=owner.lang or "ru"
            ))
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(f"TG notify failed (non-critical): {_e}")

    # Email грузоотправителю
    if owner and owner.email:
        carrier_name = current_user.company_name or current_user.email
        route = f"{load.from_city} → {load.to_city}"
        lang = owner.lang or "ka"
        price_text = (
            f"<b>{_t(lang,'შეთავაზებული ფასი','Предложенная цена')}:</b> {data.price} ₾<br>"
            if data.price else ""
        )
        msg_text = (
            f"<b>{_t(lang,'შეტყობინება','Сообщение')}:</b> {data.message}<br>"
            if data.message else ""
        )
        subj = _t(lang, f"🚛 ახალი გამოხმაურება თქვენს ტვირთზე {route}", f"Новый отклик на груз {route}")
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          {_email_header()}
          <div style="padding:24px;background:#fff">
            <h3>🚛 {_t(lang,'ახალი გამოხმაურება თქვენს ტვირთზე!','Новый отклик на ваш груз!')}</h3>
            <p>{_t(lang,f'გადამზიდი <b>{carrier_name}</b> მზადაა თქვენი ტვირთი გადაიტანოს:',f'Перевозчик <b>{carrier_name}</b> готов везти ваш груз:')}</p>
            <div style="background:#f8f9fa;border-radius:8px;padding:16px;margin:16px 0">
              <b>{_t(lang,'მარშრუტი','Маршрут')}:</b> {route}<br>
              <b>{_t(lang,'გადამზიდი','Перевозчик')}:</b> {carrier_name}<br>
              {price_text}{msg_text}
            </div>
            <p>{_t(lang,
              'შედით <a href="https://caucashub.ge" style="color:#f7b731">პირად კაბინეტში</a> → "ჩემი შეკვეთები" განყოფილება, რათა მიიღოთ ან უარყოთ.',
              'Зайдите в <a href="https://caucashub.ge" style="color:#f7b731">личный кабинет</a> → вкладка "Мои заказы" чтобы принять или отклонить.'
            )}</p>
          </div>
          {_email_footer(lang)}
        </div>
        """
        try:
            await send_email(owner.email, subj, html)
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(f"Email send failed (non-critical): {_e}")

    resp_result = {
        "ok": True,
        "response_id": resp.id,
        "status": resp.status.value if hasattr(resp.status, "value") else str(resp.status),
    }
    try:
        await save_idempotency(request, db, scope=f"respond_to_load:{load_id}",
                               user_id=current_user.id, response_status=200,
                               response_body=resp_result)
    except Exception as _se:
        import logging
        logging.getLogger(__name__).warning(f"save_idempotency failed (non-critical): {_se}")
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
    current_user: User = Depends(require_user)
):
    """Грузоотправитель принимает отклик → создаётся сделка"""
    from app.services.idempotency import check_idempotency, save_idempotency, make_idempotent_response
    cached, replayed = await check_idempotency(request, db, scope=f"accept_response:{response_id}", user_id=current_user.id)
    if replayed:
        return make_idempotent_response(cached)
    from app.services.state_machine import validate_transition
    from app.services.audit_log import log_status_change
    from app.models.deal import Deal as DealModel

    resp_res = await db.execute(select(Response).where(Response.id == response_id))
    resp = resp_res.scalar_one_or_none()
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")

    load_res = await db.execute(select(Load).where(Load.id == resp.load_id))
    load = load_res.scalar_one_or_none()
    if not load or load.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your load")

    # Трек 8: Защита от race condition — проверяем что у груза нет уже принятой сделки
    # Если resp уже не pending — значит другой запрос нас опередил
    current_resp_status = resp.status.value if hasattr(resp.status, 'value') else str(resp.status)
    validate_transition("response", current_resp_status, "accepted")

    # Проверяем нет ли активной сделки по этому грузу (двойной accept)
    existing_deal = await db.execute(
        select(DealModel).where(
            DealModel.load_id == resp.load_id,
            DealModel.status.notin_(["canceled"])
        )
    )
    if existing_deal.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Deal already exists for this load")

    # Принимаем отклик, отклоняем остальные
    resp.status = ResponseStatus.accepted
    await log_status_change(db, "response", resp.id, current_resp_status, "accepted", current_user.id)

    all_resp = await db.execute(
        select(Response).where(Response.load_id == resp.load_id, Response.id != response_id,
                                Response.status == ResponseStatus.pending)
    )
    for other in all_resp.scalars().all():
        other.status = ResponseStatus.rejected
        await log_status_change(db, "response", other.id, "pending", "rejected", current_user.id,
                                 reason="auto-rejected: another response accepted")

    await db.commit()

    # ADR-006: Создаём сделку со снапшотом курса
    from app.models.deal import Deal
    from app.services.exchange_rate import get_usd_gel_rate, convert_gel_to_usd, convert_usd_to_gel

    deal_rate = await get_usd_gel_rate()

    # Согласованная цена: сначала из отклика, потом из груза
    agreed_gel = resp.price_gel or (load.price_gel if hasattr(load, 'price_gel') else None)
    agreed_usd = resp.price_usd or (load.price_usd if hasattr(load, 'price_usd') else None)

    if agreed_gel and not agreed_usd:
        agreed_usd = convert_gel_to_usd(agreed_gel, deal_rate)
    elif agreed_usd and not agreed_gel:
        agreed_gel = convert_usd_to_gel(agreed_usd, deal_rate)

    agreed = agreed_gel or 0
    deal = Deal(
        load_id=resp.load_id,
        shipper_id=current_user.id,
        carrier_id=resp.user_id,
        agreed_price=agreed,
        currency="GEL",
        exchange_rate_snapshot=deal_rate,
        final_price_gel=agreed_gel,
        final_price_usd=agreed_usd,
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
            float(resp.price_usd or load.price_gel or 0), "₾",
            lang=carrier.lang or "ru"
        ))

    # Email перевозчику
    if carrier and carrier.email:
        route = f"{load.from_city} → {load.to_city}"
        shipper_name = current_user.company_name or current_user.email
        lang = carrier.lang or "ka"
        deal_num = deal.act_number or f"CH-{deal.id:04d}"
        subj = _t(lang, f"✅ თქვენი გამოხმაურება მიღებულია — {route}", f"✅ Ваш отклик принят — {route}")
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          {_email_header()}
          <div style="padding:24px;background:#fff">
            <h3>✅ {_t(lang,'თქვენი გამოხმაურება მიღებულია!','Ваш отклик принят!')}</h3>
            <p>{_t(lang,f'გამგზავნმა <b>{shipper_name}</b> მიიღო თქვენი გამოხმაურება.',f'Грузоотправитель <b>{shipper_name}</b> принял ваш отклик.')}</p>
            <div style="background:#e8f5e9;border-radius:8px;padding:16px;margin:16px 0;border-left:4px solid #2ecc71">
              <b>{_t(lang,'მარშრუტი','Маршрут')}:</b> {route}<br>
              <b>{_t(lang,'გარიგების ნომერი','Номер сделки')}:</b> {deal_num}<br>
              <b>{_t(lang,'სტატუსი','Статус')}:</b> {_t(lang,'დადასტურებულია','Подтверждена')}
            </div>
            <div style="background:#f8f9fa;border-radius:8px;padding:16px;margin:16px 0">
              <b>{_t(lang,'გამგზავნის კონტაქტი','Контакт грузоотправителя')}:</b><br>
              {f"📞 {current_user.phone}<br>" if current_user.phone else ""}
              📧 {current_user.email}
            </div>
            <p>{_t(lang,
              'შედით <a href="https://caucashub.ge" style="color:#f7b731">პირად კაბინეტში</a> → "ჩემი გარიგებები" მიწოდების სამართავად.',
              'Зайдите в <a href="https://caucashub.ge" style="color:#f7b731">личный кабинет</a> → "Мои сделки" для управления доставкой.'
            )}</p>
          </div>
          {_email_footer(lang)}
        </div>
        """
        await send_email(carrier.email, subj, html)

    # 3.2: Email грузовладельцу — симметричное уведомление о создании сделки
    deal_num = deal.act_number or f"CH-{deal.id:04d}"

    # TG-уведомление грузоотправителю о создании сделки с контактами перевозчика
    if current_user.telegram_id and not current_user.telegram_id.startswith("pending:"):
        asyncio.create_task(notify_deal_created(
            current_user.telegram_id,
            deal_num,
            load.from_city, load.to_city,
            carrier_name=(carrier.company_name if carrier else None),
            carrier_phone=(carrier.phone if carrier else None),
            carrier_email=(carrier.email if carrier else None),
            lang=current_user.lang or "ru"
        ))
    if current_user.email:
        carrier_name = carrier.company_name if carrier else _t(current_user.lang or "ka", "გადამზიდი", "Перевозчик")
        lang_sh = current_user.lang or "ka"
        subj_sh = _t(lang_sh, f"✅ გარიგება {deal_num} შეიქმნა — {route}", f"✅ Сделка {deal_num} создана — {route}")
        html_shipper = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          {_email_header()}
          <div style="padding:24px;background:#fff">
            <h3>✅ {_t(lang_sh,'გარიგება შეიქმნა!','Сделка создана!')}</h3>
            <p>{_t(lang_sh,
              f'თქვენ მიიღეთ გადამზიდის <b>{carrier_name}</b> გამოხმაურება. გარიგება <b>{deal_num}</b> შეიქმნა.',
              f'Вы приняли отклик перевозчика <b>{carrier_name}</b>. Сделка <b>{deal_num}</b> создана.'
            )}</p>
            <div style="background:#e8f5e9;border-radius:8px;padding:16px;margin:16px 0;border-left:4px solid #2ecc71">
              <b>{_t(lang_sh,'მარშრუტი','Маршрут')}:</b> {route}<br>
              <b>{_t(lang_sh,'გარიგების ნომერი','Номер сделки')}:</b> {deal_num}<br>
              <b>{_t(lang_sh,'გადამზიდი','Перевозчик')}:</b> {carrier_name}
              {f"<br><b>{_t(lang_sh,'ტელეფონი','Телефон')}:</b> {carrier.phone}" if carrier and carrier.phone else ""}
            </div>
            <p>{_t(lang_sh,
              'შედით <a href="https://caucashub.ge" style="color:#f7b731">პირად კაბინეტში</a> → "ჩემი გარიგებები" მიწოდების სტატუსის თვალყურის დევნებისთვის.',
              'Зайдите в <a href="https://caucashub.ge" style="color:#f7b731">личный кабинет</a> → "Мои сделки" чтобы отслеживать статус доставки.'
            )}</p>
          </div>
          {_email_footer(lang_sh)}
        </div>"""
        await send_email(current_user.email, subj_sh, html_shipper)

    accept_result = {
        "ok": True,
        "deal_id": deal.id,
        "deal_number": deal_num,
        "status": deal.status.value if hasattr(deal.status, "value") else str(deal.status),
    }
    await save_idempotency(request, db, scope=f"accept_response:{response_id}",
                           user_id=current_user.id, response_status=200,
                           response_body=accept_result)
    return accept_result

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

    # Telegram уведомление перевозчику (Task 6 — ADR-013)
    carrier_res_tg = await db.execute(select(User).where(User.id == resp.user_id))
    carrier_tg = carrier_res_tg.scalar_one_or_none()
    if carrier_tg and carrier_tg.telegram_id:
        import asyncio
        asyncio.create_task(notify_response_rejected(
            chat_id=carrier_tg.telegram_id,
            from_city=load.from_city,
            to_city=load.to_city,
            price=resp.price_gel or resp.price_usd or 0,
            cur="GEL" if resp.price_gel else "USD",
            lang=getattr(carrier_tg, 'lang', 'ru') or 'ru',
        ))

    # Email перевозчику
    carrier_res = await db.execute(select(User).where(User.id == resp.user_id))
    carrier = carrier_res.scalar_one_or_none()
    if carrier and carrier.email:
        route = f"{load.from_city} → {load.to_city}"
        lang = getattr(carrier, 'lang', None) or "ka"
        subj = _t(lang, f"ℹ️ გამოხმაურება ტვირთზე {route}", f"ℹ️ Отклик на груз {route}")
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          {_email_header()}
          <div style="padding:24px;background:#fff">
            <h3>ℹ️ {_t(lang,'თქვენი გამოხმაურება არ შეირჩა','Ваш отклик не был выбран')}</h3>
            <p>{_t(lang,
              f'სამწუხაროდ, გამგზავნმა სხვა გადამზიდი აირჩია მარშრუტისთვის <b>{route}</b>.',
              f'К сожалению, грузоотправитель выбрал другого перевозчика для маршрута <b>{route}</b>.'
            )}</p>
            <p>{_t(lang,
              'ნუ დანაღვლდებით — ახალი ტვირთები ყოველდღე ჩნდება. <a href="https://caucashub.ge" style="color:#f7b731">იხილეთ აქტუალური ტვირთები →</a>',
              'Не расстраивайтесь — новые грузы появляются каждый день. <a href="https://caucashub.ge" style="color:#f7b731">Смотрите актуальные грузы →</a>'
            )}</p>
          </div>
          {_email_footer(lang)}
        </div>
        """
        await send_email(carrier.email, subj, html)

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
