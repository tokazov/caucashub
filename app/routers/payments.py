"""
Платёжная логика CaucasHub.

Эндпоинты:
  POST /api/payments/create              — создать платёж (pending)
  GET  /api/payments/my                  — история своих платежей
  GET  /api/payments/status/{id}         — статус своего платежа
  GET  /api/payments/callback/tbc        — webhook от TBC Pay
  GET  /api/payments/callback/bog        — webhook от BOG
  POST /api/payments/admin/payments/{id}/activate — ручная активация
"""
import os
import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.models.payment import Payment
from app.models.load import Load
from app.models.user import User
from app.routers.auth import require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payments", tags=["payments"])

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "caucashub-admin-2026")
BASE_URL = os.getenv("BASE_URL", "https://caucashub.ge")
TBC_API_URL = os.getenv("TBC_API_URL", "https://api.tbcbank.ge/v1")
TBC_CLIENT_ID = os.getenv("TBC_CLIENT_ID")
TBC_CLIENT_SECRET = os.getenv("TBC_CLIENT_SECRET")
BOG_API_URL = os.getenv("BOG_API_URL", "https://api.bog.ge/payments/v1")
BOG_CLIENT_ID = os.getenv("BOG_CLIENT_ID")
BOG_CLIENT_SECRET = os.getenv("BOG_CLIENT_SECRET")

PRICES: dict[str, float] = {
    "plan_pro":      49.00,
    "plan_business": 149.00,
    "promote_24h":   5.00,
    "promote_72h":   12.00,
    "promote_168h":  25.00,
}


# ── Schemas ───────────────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    type: str
    payload: dict = {}
    provider: Optional[str] = "tbc"  # "tbc" | "bog"


# ── Helper: activate_payment ──────────────────────────────────────────────────

async def activate_payment(payment_id: int, db: AsyncSession) -> bool:
    """Активирует платёж: меняет план или поднимает груз."""
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment or payment.status != "pending":
        return False

    if payment.type in ("plan_pro", "plan_business"):
        plan = "pro" if payment.type == "plan_pro" else "business"
        await db.execute(
            update(User)
            .where(User.id == payment.user_id)
            .values(plan=plan)
        )
        logger.info(f"[PAYMENT] User {payment.user_id} upgraded to {plan}")

    elif payment.type.startswith("promote_"):
        load_id = payment.payload.get("load_id")
        if load_id:
            await db.execute(
                update(Load)
                .where(Load.id == load_id, Load.user_id == payment.user_id)
                .values(is_boosted=True)
            )
            logger.info(f"[PAYMENT] Load {load_id} promoted for user {payment.user_id}")

    payment.status = "paid"
    payment.paid_at = datetime.now(timezone.utc)
    await db.commit()

    # Email уведомление (non-blocking)
    try:
        await _send_payment_email(payment, db)
    except Exception as e:
        logger.warning(f"[PAYMENT] Email notify failed: {e}")

    return True


async def _send_payment_email(payment: Payment, db: AsyncSession):
    """Отправляет email после успешной оплаты."""
    user_res = await db.execute(select(User).where(User.id == payment.user_id))
    user = user_res.scalar_one_or_none()
    if not user or not user.email:
        return

    type_names = {
        "plan_pro": "Pro план",
        "plan_business": "Business план",
        "promote_24h": "Продвижение груза на 24 часа",
        "promote_72h": "Продвижение груза на 3 дня",
        "promote_168h": "Продвижение груза на 7 дней",
    }
    type_name = type_names.get(payment.type, payment.type)

    try:
        from app.routers.responses import send_email
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
          <div style="background:#1a1a2e;padding:20px;text-align:center">
            <h2 style="color:#f7b731;margin:0">CaucasHub.ge</h2>
          </div>
          <div style="padding:24px;background:#fff">
            <h3>✅ Оплата прошла успешно!</h3>
            <p>Услуга <b>{type_name}</b> на сумму <b>₾{float(payment.amount_gel)}</b> активирована.</p>
            <p>Спасибо за использование CaucasHub!</p>
            <a href="{BASE_URL}" style="display:inline-block;background:#f7b731;color:#1a1a2e;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:700">Открыть CaucasHub →</a>
          </div>
        </div>
        """
        await send_email(user.email, f"✅ {type_name} активирован — CaucasHub", html)
    except Exception:
        pass


# ── TBC Pay ───────────────────────────────────────────────────────────────────

async def _create_tbc_payment(amount: float, payment_id: int, description: str) -> dict | None:
    """Создаёт платёж в TBC Pay. Возвращает {pay_url, tbc_id} или None."""
    if not TBC_CLIENT_ID or not TBC_CLIENT_SECRET:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # 1. Получаем access token
            tok_resp = await client.post(
                f"{TBC_API_URL}/tpay/access-token",
                data={"client_id": TBC_CLIENT_ID, "client_secret": TBC_CLIENT_SECRET},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if tok_resp.status_code != 200:
                logger.error(f"[TBC] Token error: {tok_resp.text[:200]}")
                return None
            token = tok_resp.json().get("access_token")

            # 2. Создаём платёж
            pay_resp = await client.post(
                f"{TBC_API_URL}/tpay/payments",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "amount": {"currency": "GEL", "total": amount},
                    "returnurl": f"{BASE_URL}/payment/success?pid={payment_id}",
                    "callbackurl": f"{BASE_URL}/api/payments/callback/tbc",
                    "extra": str(payment_id),
                    "description": description,
                    "language": "RU",
                    "preAuth": False,
                },
            )
            if pay_resp.status_code not in (200, 201):
                logger.error(f"[TBC] Payment error: {pay_resp.text[:200]}")
                return None

            data = pay_resp.json()
            links = data.get("links", [])
            pay_url = next((l["uri"] for l in links if l.get("rel") == "pay"), None)
            if not pay_url and links:
                pay_url = links[0].get("uri")
            return {"pay_url": pay_url, "tbc_id": data.get("payId")}

    except Exception as e:
        logger.error(f"[TBC] Exception: {e}")
        return None


# ── BOG Pay ───────────────────────────────────────────────────────────────────

async def _create_bog_payment(amount: float, payment_id: int, description: str) -> dict | None:
    """Создаёт платёж в Bank of Georgia. Возвращает {pay_url, bog_id} или None."""
    if not BOG_CLIENT_ID or not BOG_CLIENT_SECRET:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # 1. Получаем access token (Basic Auth)
            import base64
            creds = base64.b64encode(f"{BOG_CLIENT_ID}:{BOG_CLIENT_SECRET}".encode()).decode()
            tok_resp = await client.post(
                f"{BOG_API_URL}/auth/token",
                headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials"},
            )
            if tok_resp.status_code != 200:
                logger.error(f"[BOG] Token error: {tok_resp.text[:200]}")
                return None
            token = tok_resp.json().get("access_token")

            # 2. Создаём платёж
            pay_resp = await client.post(
                f"{BOG_API_URL}/payment",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "callback_url": f"{BASE_URL}/api/payments/callback/bog",
                    "external_order_id": str(payment_id),
                    "purchase_units": {
                        "currency": "GEL",
                        "total_amount": amount,
                        "basket": [{"quantity": 1, "unit_price": amount, "product_id": payment_id, "description": description}],
                    },
                    "redirect_urls": {
                        "success": f"{BASE_URL}/payment/success?pid={payment_id}",
                        "fail": f"{BASE_URL}/payment/error?pid={payment_id}",
                    },
                },
            )
            if pay_resp.status_code not in (200, 201):
                logger.error(f"[BOG] Payment error: {pay_resp.text[:200]}")
                return None

            data = pay_resp.json()
            return {"pay_url": data.get("redirect_url"), "bog_id": data.get("id")}

    except Exception as e:
        logger.error(f"[BOG] Exception: {e}")
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/create")
async def create_payment(
    data: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if data.type not in PRICES:
        raise HTTPException(400, detail=f"Unknown payment type. Valid: {list(PRICES)}")

    amount = PRICES[data.type]

    # Валидация payload для promote
    if data.type.startswith("promote_"):
        load_id = data.payload.get("load_id")
        if not load_id:
            raise HTTPException(400, detail="payload.load_id required for promote")
        load_res = await db.execute(
            select(Load).where(Load.id == load_id, Load.user_id == current_user.id)
        )
        if not load_res.scalar_one_or_none():
            raise HTTPException(404, detail="Load not found or not yours")

    provider_name = data.provider or "tbc"
    if provider_name not in ("tbc", "bog"):
        provider_name = "tbc"

    payment = Payment(
        user_id=current_user.id,
        type=data.type,
        payload=data.payload,
        amount_gel=Decimal(str(amount)),
        status="pending",
        provider=provider_name,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    pay_url = None
    description = f"CaucasHub: {data.type.replace('_', ' ')}"

    # Попытка создать платёж через выбранный провайдер
    try:
        if provider_name == "bog":
            bog = await _create_bog_payment(amount, payment.id, description)
            if bog:
                payment.provider_tx_id = str(bog.get("bog_id", ""))
                pay_url = bog.get("pay_url")
        else:
            tbc = await _create_tbc_payment(amount, payment.id, description)
            if tbc:
                payment.provider_tx_id = str(tbc.get("tbc_id", ""))
                pay_url = tbc.get("pay_url")

        if payment.provider_tx_id:
            await db.commit()
    except Exception as e:
        logger.error(f"[PAYMENT] Provider error: {e}")

    return {
        "payment_id": payment.id,
        "status": payment.status,
        "amount": float(payment.amount_gel),
        "currency": "GEL",
        "type": data.type,
        "pay_url": pay_url,
        "telegram": "@tokazov",
    }


@router.get("/my")
async def my_payments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    """История платежей текущего пользователя."""
    result = await db.execute(
        select(Payment)
        .where(Payment.user_id == current_user.id)
        .order_by(Payment.created_at.desc())
        .limit(limit).offset(offset)
    )
    payments = result.scalars().all()
    return {
        "payments": [
            {
                "id": p.id,
                "type": p.type,
                "status": p.status,
                "amount_gel": float(p.amount_gel),
                "provider": p.provider,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in payments
        ]
    }


@router.get("/status/{payment_id}")
async def payment_status(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    result = await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.user_id == current_user.id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, detail="Payment not found")
    return {
        "payment_id": payment.id,
        "type": payment.type,
        "status": payment.status,
        "amount_gel": float(payment.amount_gel),
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
    }


@router.get("/callback/tbc", response_class=PlainTextResponse)
async def tbc_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Webhook от TBC Pay. Активирует платёж при status=OK."""
    params = dict(request.query_params)
    # TBC передаёт PaymentId и status
    tbc_payment_id = params.get("PaymentId") or params.get("paymentId") or params.get("payId")
    status = params.get("status", "").upper()

    logger.info(f"[TBC CALLBACK] PaymentId={tbc_payment_id} status={status}")

    if tbc_payment_id and status == "OK":
        result = await db.execute(
            select(Payment).where(Payment.provider_tx_id == tbc_payment_id)
        )
        payment = result.scalar_one_or_none()
        if payment and payment.status == "pending":
            ok = await activate_payment(payment.id, db)
            logger.info(f"[TBC CALLBACK] activate_payment({payment.id}) = {ok}")

    return "OK"


@router.get("/callback/bog", response_class=PlainTextResponse)
async def bog_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Webhook от BOG. Активирует платёж при event=payment.success."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    event = body.get("event", "")
    order_id = str(body.get("external_order_id", ""))
    bog_status = body.get("status", "").lower()

    logger.info(f"[BOG CALLBACK] event={event} order_id={order_id} status={bog_status}")

    is_success = event == "payment.success" or bog_status in ("completed", "confirmed")

    if is_success and order_id:
        try:
            payment_id = int(order_id)
            result = await db.execute(select(Payment).where(Payment.id == payment_id))
            payment = result.scalar_one_or_none()
            if payment and payment.status == "pending":
                ok = await activate_payment(payment.id, db)
                logger.info(f"[BOG CALLBACK] activate_payment({payment_id}) = {ok}")
        except Exception as e:
            logger.error(f"[BOG CALLBACK] Error: {e}")

    return "OK"


@router.post("/admin/payments/{payment_id}/activate")
async def admin_activate(
    payment_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Ручная активация платежа (X-Admin-Secret header)."""
    secret = request.headers.get("X-Admin-Secret", "")
    if secret != ADMIN_SECRET:
        raise HTTPException(403, detail="Forbidden")

    ok = await activate_payment(payment_id, db)
    if not ok:
        raise HTTPException(400, detail="Payment not found or already processed")

    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    p = result.scalar_one_or_none()
    return {"ok": True, "payment_id": payment_id, "status": p.status if p else "paid"}
