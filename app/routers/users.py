import os
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User, UserPlan
from app.routers.loads import require_user         # возвращает int (user_id)
from app.routers.auth import require_user as require_user_obj  # возвращает User object
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class UpdateProfileRequest(BaseModel):
    company_name: Optional[str] = None
    phone:        Optional[str] = None
    inn:          Optional[str] = None
    org_type:     Optional[str] = None
    city:         Optional[str] = None
    lang:         Optional[str] = None
    telegram_id:  Optional[str] = None


class DeleteAccountRequest(BaseModel):
    confirmation: str  # должно быть "УДАЛИТЬ"


class SetPlanRequest(BaseModel):
    plan:   str
    secret: str


PLAN_LIMITS = {
    "free":     0,
    "standard": 50,
    "pro":      -1,   # безлимит
    "pro_plus": -1,   # безлимит
}


@router.get("/me")
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user_obj),  # проверяет is_deleted → 401
):
    user = current_user
    if not user:
        raise HTTPException(404, "User not found")
    plan_val = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
    return {
        "id":                    user.id,
        "email":                 user.email,
        "company_name":          user.company_name,
        "phone":                 user.phone,
        "role":                  user.role,
        "plan":                  plan_val,
        "responses_this_month":  user.responses_this_month or 0,
        "responses_limit":       PLAN_LIMITS.get(plan_val, 0),
        "rating":                round((user.rating or 50) / 10, 1),
        "trips_count":           user.trips_count or 0,
        "is_verified":           user.is_verified,
        "inn":                   user.inn,
        "org_type":              user.org_type,
        "city":                  user.city,
        "lang":                  user.lang,
        "telegram_id":           user.telegram_id,
    }


@router.put("/me")
async def update_me(
    data: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    if data.company_name is not None:
        user.company_name = data.company_name
    if data.phone is not None:
        user.phone = data.phone
    if data.inn is not None:
        user.inn = data.inn
    if data.org_type is not None:
        user.org_type = data.org_type
    if data.city is not None:
        user.city = data.city
    if data.lang is not None:
        user.lang = data.lang
    if data.telegram_id is not None:
        user.telegram_id = data.telegram_id

    await db.commit()
    await db.refresh(user)

    return {
        "ok": True,
        "id":           user.id,
        "company_name": user.company_name,
        "phone":        user.phone,
        "inn":          user.inn,
        "org_type":     user.org_type,
        "city":         user.city,
    }


@router.post("/me/plan")
async def set_my_plan(
    data: SetPlanRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(require_user),
):
    """Admin устанавливает план пользователя вручную после оплаты."""
    admin_secret = os.getenv("ADMIN_SECRET", "caucashub-admin-2026")
    if data.secret != admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        new_plan = UserPlan(data.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {data.plan}")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    user.plan = new_plan
    await db.commit()
    await db.refresh(user)

    plan_val = user.plan.value if hasattr(user.plan, "value") else str(user.plan)
    return {"ok": True, "plan": plan_val}


@router.delete("/me")
async def delete_account(
    data: DeleteAccountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user_obj),  # нужен User-объект, не int
):
    """
    ADR-010 GDPR: Soft delete аккаунта.
    Требует подтверждения словом 'УДАЛИТЬ'.
    Блокируется при наличии активных сделок.
    """
    from app.models.deal import Deal, DealStatus
    from app.models.load import Load, LoadStatus
    from app.models.response import Response, ResponseStatus
    from app.services.audit_log import log_status_change

    # 1. Проверка подтверждения (case-sensitive)
    if data.confirmation != "УДАЛИТЬ":
        raise HTTPException(
            status_code=400,
            detail="Для подтверждения введите слово УДАЛИТЬ (точно, с учётом регистра)"
        )

    user_id = current_user.id

    # 2. Проверяем активные сделки (confirmed, loading, in_transit, delivered, disputed)
    BLOCKING_STATUSES = [
        DealStatus.confirmed, DealStatus.loading,
        DealStatus.in_transit, DealStatus.delivered, DealStatus.disputed,
    ]
    active_deals_res = await db.execute(
        select(Deal).where(
            (Deal.shipper_id == user_id) | (Deal.carrier_id == user_id),
            Deal.status.in_(BLOCKING_STATUSES)
        )
    )
    active_deals = active_deals_res.scalars().all()
    if active_deals:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Нельзя удалить аккаунт с активными сделками. "
                           "Завершите или отмените все сделки и попробуйте снова.",
                "active_deal_ids": [d.id for d in active_deals],
            }
        )

    # 3. Сохраняем email для письма (до анонимизации)
    old_email = current_user.email
    now = datetime.now(timezone.utc)

    # === ОДНА ТРАНЗАКЦИЯ: анонимизация ===

    # 3a. Отменяем все активные грузы
    loads_res = await db.execute(
        select(Load).where(Load.user_id == user_id, Load.status == LoadStatus.active)
    )
    canceled_count = 0
    for load in loads_res.scalars().all():
        load.status = LoadStatus.canceled
        canceled_count += 1

    # 3b. Отзываем все pending-отклики
    resp_res = await db.execute(
        select(Response).where(
            Response.user_id == user_id,
            Response.status == ResponseStatus.pending,
        )
    )
    withdrawn_count = 0
    for resp in resp_res.scalars().all():
        resp.status = ResponseStatus.withdrawn
        withdrawn_count += 1

    # 3c. Анонимизируем пользователя
    # email: уникальный индекс + NOT NULL → используем placeholder вместо NULL
    # (полная анонимизация — у placeholder нет смысловой информации)
    current_user.email         = f"deleted_{user_id}@caucashub.deleted"
    current_user.phone         = None
    current_user.company_name  = f"Удалённый пользователь #{user_id}"
    current_user.full_name     = None
    current_user.telegram_id   = None
    current_user.hashed_password = "<deleted>"
    current_user.is_active     = False
    current_user.is_deleted    = True
    current_user.deleted_at    = now
    # inn — сохраняем для rs.ge (налоговое хранение 6 лет)

    # 3d. Audit log
    await log_status_change(
        db, "user", user_id,
        from_status="active",
        to_status="deleted",
        user_id=user_id,
        reason=f"account_deleted: {canceled_count} loads canceled, {withdrawn_count} responses withdrawn",
    )

    await db.commit()

    # 4. Email-уведомление (асинхронно, не блокирует ответ)
    if old_email:
        asyncio.create_task(_send_deletion_email(old_email, user_id, now))

    return {
        "deleted": True,
        "loads_canceled": canceled_count,
        "responses_withdrawn": withdrawn_count,
    }


async def _send_deletion_email(email: str, user_id: int, deleted_at: datetime):
    """Отправляет email-уведомление об удалении аккаунта (ADR-010)."""
    try:
        import httpx
        RESEND_KEY = os.getenv("RESEND_API_KEY") or os.getenv("BREVO_API_KEY", "")
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          <div style="background:#1a1a2e;padding:20px;text-align:center">
            <h2 style="color:#f7b731;margin:0">CaucasHub.ge</h2>
          </div>
          <div style="padding:24px;background:#fff">
            <h3>Ваш аккаунт удалён</h3>
            <p>Ваш аккаунт на CaucasHub.ge был удалён <b>{deleted_at.strftime('%d.%m.%Y в %H:%M UTC')}</b>.</p>
            <div style="background:#f8f9fa;border-radius:8px;padding:16px;margin:16px 0">
              <p style="margin:0;font-size:14px;color:#555">
                📋 Историческая информация о завершённых сделках сохраняется в обезличенном виде
                в соответствии с требованиями налогового законодательства Грузии (6 лет).
                Ваши личные данные (email, телефон, имя) удалены.
              </p>
            </div>
            <p>Если это было сделано по ошибке — свяжитесь с нами: <a href="mailto:support@caucashub.ge">support@caucashub.ge</a></p>
          </div>
          <div style="background:#f0f2f5;padding:12px;text-align:center;font-size:12px;color:#999">
            CaucasHub.ge — Биржа грузов Кавказа
          </div>
        </div>
        """
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_KEY}"},
                json={
                    "from": "CaucasHub <noreply@caucashub.ge>",
                    "to": [email],
                    "subject": "Ваш аккаунт CaucasHub удалён",
                    "html": html,
                },
                timeout=10,
            )
    except Exception:
        pass  # Email не критичен — данные уже анонимизированы


@router.get("/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"error": "Not found"}
    return {
        "id":           user.id,
        "company_name": user.company_name,
        "role":         user.role,
        "plan":         user.plan,
        "rating":       round((user.rating or 50) / 10, 1),
        "trips_count":  user.trips_count or 0,
        "is_verified":  user.is_verified,
        "inn":          user.inn,
        "org_type":     user.org_type,
        "city":         user.city,
    }
