"""
Платёжная логика CaucasHub.

Эндпоинты:
  POST /api/payments/create              — создать платёж (pending)
  GET  /api/payments/status/{id}         — статус своего платежа
  GET  /api/payments/callback/tbc        — webhook от TBC Pay
  POST /api/admin/payments/{id}/activate — ручная активация (X-Admin-Secret)
"""
import os
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
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

router = APIRouter(prefix="/api/payments", tags=["payments"])

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "caucashub-admin-2026")
BASE_URL = os.getenv("BASE_URL", "https://caucashub.ge")

PRICES: dict[str, float] = {
    "plan_pro":      49.00,
    "plan_business": 149.00,
    "promote_24h":   5.00,
    "promote_72h":   12.00,
    "promote_168h":  25.00,
}

HOURS_MAP = {
    "promote_24h":  24,
    "promote_72h":  72,
    "promote_168h": 168,
}


# ── Schemas ───────────────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    type: str
    payload: dict = {}


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

    elif payment.type.startswith("promote_"):
        load_id = payment.payload.get("load_id")
        if load_id:
            await db.execute(
                update(Load)
                .where(Load.id == load_id, Load.user_id == payment.user_id)
                .values(is_boosted=True)
            )

    payment.status = "paid"
    payment.paid_at = datetime.now(timezone.utc)
    await db.commit()
    return True


# ── Helper: TBC Pay (опционально, если есть credentials) ─────────────────────

async def _create_tbc_payment(amount: float, payment_id: int, description: str) -> dict | None:
    """Создаёт платёж в TBC Pay. Возвращает {pay_url, tbc_id} или None."""
    client_id = os.getenv("TBC_CLIENT_ID")
    client_secret = os.getenv("TBC_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Получаем access token
            tok_resp = await client.post(
                "https://api.tbcbank.ge/v1/tpay/access-token",
                json={"client_id": client_id, "client_secret": client_secret},
            )
            if tok_resp.status_code != 200:
                return None
            token = tok_resp.json().get("access_token")

            # Создаём платёж
            pay_resp = await client.post(
                "https://api.tbcbank.ge/v1/tpay/payments",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "amount": {"currency": "GEL", "total": amount},
                    "returnurl": f"{BASE_URL}/payment/success?pid={payment_id}",
                    "callbackurl": f"{BASE_URL}/api/payments/callback/tbc",
                    "extra": str(payment_id),
                    "description": description,
                    "language": "RU",
                },
            )
            if pay_resp.status_code not in (200, 201):
                return None
            data = pay_resp.json()
            links = data.get("links", [])
            pay_url = links[0]["uri"] if links else None
            return {"pay_url": pay_url, "tbc_id": data.get("payId")}
    except Exception:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/create")
async def create_payment(
    data: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Создать платёжную запись. Возвращает payment_id и ссылку (если TBC настроен)."""
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

    payment = Payment(
        user_id=current_user.id,
        type=data.type,
        payload=data.payload,
        amount_gel=Decimal(str(amount)),
        status="pending",
        provider="manual",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    pay_url = None
    # Попытка создать TBC платёж если credentials есть
    description = f"CaucasHub: {data.type.replace('_', ' ')}"
    tbc = await _create_tbc_payment(amount, payment.id, description)
    if tbc:
        payment.provider = "tbc"
        payment.provider_tx_id = tbc.get("tbc_id")
        await db.commit()
        pay_url = tbc.get("pay_url")

    return {
        "payment_id": payment.id,
        "status": payment.status,
        "amount": float(payment.amount_gel),
        "currency": "GEL",
        "type": data.type,
        "pay_url": pay_url,
        "telegram": "@tokazov",
    }


@router.get("/status/{payment_id}")
async def payment_status(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Статус платежа (только свои)."""
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
    tbc_payment_id = params.get("PaymentId") or params.get("paymentId")
    status = params.get("status", "").upper()

    if tbc_payment_id and status == "OK":
        result = await db.execute(
            select(Payment).where(Payment.provider_tx_id == tbc_payment_id)
        )
        payment = result.scalar_one_or_none()
        if payment:
            await activate_payment(payment.id, db)

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
    payment = result.scalar_one_or_none()
    return {
        "ok": True,
        "payment_id": payment_id,
        "status": payment.status if payment else "paid",
    }
