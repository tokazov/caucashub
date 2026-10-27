"""Committed outbox processing with exclusive claims and conservative retries."""
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4
from sqlalchemy import select, update, and_
from app.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationDelivery
from app.models.user import User
from app.services import notification_channels as channels
from app.services.notifications import render_message
from app.services.user_display import display_name

logger = logging.getLogger("uvicorn.error.notifications")
MAX_ATTEMPTS = 4

async def _deliver(sessions, identifier, token):
    request = None
    async with sessions() as db:
        delivery = await db.get(NotificationDelivery, identifier)
        if delivery is None or delivery.status != "sending" or delivery.claim_token != token:
            return "skipped"
        notification = await db.get(Notification, delivery.notification_id)
        user = await db.get(User, notification.recipient_id) if notification else None
        actor = await db.get(User, notification.actor_id) if notification and notification.actor_id else None
        attempts = delivery.attempts
        if user is None or user.is_deleted or not user.is_active:
            result = channels.DeliveryResult("skipped", error="recipient_unavailable")
        else:
            message = render_message(notification, user.lang, display_name(actor) if actor else "")
            if delivery.channel == "telegram" and (not user.telegram_id or str(user.telegram_id).startswith("pending:")):
                result = channels.DeliveryResult("skipped", error="telegram_not_linked")
            else:
                request = {"channel": delivery.channel, "key": delivery.idempotency_key,
                           "email": user.email, "chat": str(user.telegram_id or ""), "message": message}
    # Release the DB connection before waiting on an external provider.
    if request is not None:
        try:
            if request["channel"] == "email":
                result = await channels.send_email(request["email"], request["message"]["subject"],
                    request["message"]["html"], idempotency_key=request["key"])
            else:
                result = await channels.send_telegram(request["chat"], request["message"]["text"],
                                                       idempotency_key=request["key"])
        except asyncio.CancelledError:
            raise
        except Exception:
            result = channels.DeliveryResult("unknown", error="provider_adapter_error")
    now = datetime.now(timezone.utc)
    outcome = result.status
    if outcome not in {"sent", "retry", "failed", "unknown", "skipped"}:
        result = channels.DeliveryResult("unknown", error="invalid_adapter_result")
        outcome = "unknown"
    state = "pending" if outcome == "retry" and attempts < MAX_ATTEMPTS else ("failed" if outcome == "retry" else outcome)
    values = {"status": state, "locked_until": None, "claim_token": None,
              "provider_id": result.provider_id, "last_error": result.error}
    if state == "pending":
        values["next_attempt_at"] = now + timedelta(seconds=min(1800, max(1, result.retry_after or 60)))
    async with sessions() as db:
        await db.execute(update(NotificationDelivery).where(
            NotificationDelivery.id == identifier, NotificationDelivery.status == "sending",
            NotificationDelivery.claim_token == token).values(**values))
        await db.commit()
    return "failed" if outcome == "retry" and state == "failed" else outcome

async def dispatch_once(*, sessions=None, limit=50):
    sessions = sessions or AsyncSessionLocal
    now = datetime.now(timezone.utc)
    claims = []
    async with sessions() as db:
        # A process may have died after provider acceptance. Do not resend blindly.
        await db.execute(update(NotificationDelivery).where(
            NotificationDelivery.status == "sending",
            NotificationDelivery.locked_until <= now).values(
                status="unknown", last_error="delivery_lease_expired", claim_token=None, locked_until=None))
        statement = select(NotificationDelivery.id).where(
            NotificationDelivery.status == "pending", NotificationDelivery.next_attempt_at <= now
        ).order_by(NotificationDelivery.id).limit(max(1, min(100, limit))).with_for_update(skip_locked=True)
        ids = list((await db.execute(statement)).scalars())
        for identifier in ids:
            token = str(uuid4())
            result = await db.execute(update(NotificationDelivery).where(
                NotificationDelivery.id == identifier, NotificationDelivery.status == "pending",
                NotificationDelivery.next_attempt_at <= now).values(
                    status="sending", attempts=NotificationDelivery.attempts + 1,
                    last_attempt_at=now, locked_until=now + timedelta(seconds=900), claim_token=token
                ).returning(NotificationDelivery.id))
            if result.scalar_one_or_none() is not None:
                claims.append((identifier, token))
        await db.commit()
    stats = {key: 0 for key in ("claimed", "sent", "failed", "unknown", "skipped", "retry")}
    stats["claimed"] = len(claims)
    # Keep delivery latency bounded while respecting per-provider flood responses.
    semaphore = asyncio.Semaphore(4)
    async def run(claim):
        async with semaphore:
            return await _deliver(sessions, *claim)
    outcomes = await asyncio.gather(*(run(claim) for claim in claims))
    for outcome in outcomes:
        stats[outcome] += 1
    return stats

async def worker_loop():
    try:
        health = await channels.configuration_health()
        logger.info("[NOTIFICATIONS] provider health email=%s telegram=%s", health["email"], health["telegram"])
    except Exception:
        logger.warning("[NOTIFICATIONS] provider health unavailable")
    while True:
        try:
            stats = await dispatch_once(limit=20)
            if stats["claimed"]:
                logger.info("[NOTIFICATIONS] delivery batch claimed=%d sent=%d failed=%d unknown=%d skipped=%d retry=%d",
                            *(stats[key] for key in ("claimed", "sent", "failed", "unknown", "skipped", "retry")))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[NOTIFICATIONS] delivery batch failed; queued events retained")
        await asyncio.sleep(10)
