"""
Этап 3 — Матчинг TransportSubscription с новыми TransportOffer (ADR-016).

Симметрично subscription_matcher.py, но инвертировано:
- Грузовладелец подписывается на маршрут
- Уведомление приходит когда перевозчик публикует TransportOffer по этому маршруту
- Хук вызывается из POST /api/transport/ (BackgroundTasks)
"""
import logging
import time
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.transport_subscription import TransportSubscription
from app.models.transport_offer import TransportOffer
from app.models.user import User

logger = logging.getLogger(__name__)

# Дебаунс: (sub_id, offer_id) → timestamp
_debounce_cache: dict[tuple[int, int], float] = {}
DEBOUNCE_SECONDS = 60


def _is_debounced(sub_id: int, offer_id: int) -> bool:
    key = (sub_id, offer_id)
    return (time.monotonic() - _debounce_cache.get(key, 0)) < DEBOUNCE_SECONDS


def _mark_debounce(sub_id: int, offer_id: int) -> None:
    _debounce_cache[(sub_id, offer_id)] = time.monotonic()
    if len(_debounce_cache) > 1000:
        cutoff = time.monotonic() - DEBOUNCE_SECONDS * 2
        for k in [k for k, v in _debounce_cache.items() if v < cutoff]:
            del _debounce_cache[k]


def _normalize(city: str) -> str:
    return city.strip().lower()


def _cities_match(sub_city: str, offer_city: str) -> bool:
    return _normalize(sub_city) == _normalize(offer_city)


def _truck_match(sub_type: Optional[str], offer_type: Optional[str]) -> bool:
    if not sub_type:
        return True
    if not offer_type:
        return False
    return sub_type.lower() == offer_type.lower()


def _capacity_match(sub_max_t: Optional[int], offer_cap_kg: Optional[float]) -> bool:
    """Если у подписки есть min_capacity — предложение должно вмещать не меньше."""
    if not sub_max_t:
        return True
    if not offer_cap_kg:
        return True
    return (offer_cap_kg / 1000) >= sub_max_t


async def find_matching_transport_subscriptions(
    offer: TransportOffer,
    db: AsyncSession,
) -> list[TransportSubscription]:
    """Находит подписки грузовладельцев которые матчат новое транспортное предложение."""
    result = await db.execute(
        select(TransportSubscription).where(
            TransportSubscription.is_active == True,   # noqa: E712
            TransportSubscription.user_id != offer.user_id,  # не сам перевозчик
        )
    )
    subs = result.scalars().all()

    matched = []
    for sub in subs:
        if not _cities_match(sub.from_city, offer.from_city or ""):
            continue
        if not _cities_match(sub.to_city, offer.to_city or ""):
            continue
        if not _truck_match(sub.truck_type, offer.truck_type):
            continue
        if not _capacity_match(sub.max_weight_t, offer.capacity_kg):
            continue
        matched.append(sub)

    return matched


def _format_offer_price(offer: TransportOffer) -> str:
    if offer.price:
        return f"{offer.price:,.0f} ₾".replace(",", " ")
    if offer.price_usd:
        return f"${offer.price_usd:,.0f}".replace(",", " ")
    return "—"


def _format_capacity(offer: TransportOffer) -> str:
    if not offer.capacity_kg:
        return ""
    t = offer.capacity_kg / 1000
    return f"{t:.1f} т" if t < 10 else f"{int(t)} т"


async def _send_tg_notification(
    telegram_id: str,
    offer: TransportOffer,
    site_url: str = "https://caucashub.ge",
) -> bool:
    import os
    import httpx

    bot_token = os.getenv("CAUCASHUB_TG_BOT_TOKEN", "")
    if not bot_token or telegram_id.startswith("pending:"):
        return False

    price_str = _format_offer_price(offer)
    cap_str   = _format_capacity(offer)
    truck_str = offer.truck_type or ""

    parts = ["🚛 *Новое транспортное предложение*"]
    parts.append(f"*{offer.from_city} → {offer.to_city}*")
    details = []
    if truck_str:
        details.append(truck_str)
    if cap_str:
        details.append(cap_str)
    if price_str != "—":
        details.append(price_str)
    if details:
        parts.append(" · ".join(details))
    if offer.notes:
        parts.append(f"_{offer.notes[:80]}_")
    parts.append(f"[Смотреть предложение]({site_url})")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": telegram_id,
                    "text": "\n".join(parts),
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
            )
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"[TRANSPORT SUB] TG notify failed: {e}")
        return False


async def _send_email_notification(
    email: str,
    offer: TransportOffer,
    site_url: str = "https://caucashub.ge",
) -> bool:
    try:
        from app.services.email_service import send_email
    except ImportError:
        return False

    subject = f"🚛 Транспорт: {offer.from_city} → {offer.to_city}"
    price_str = _format_offer_price(offer)
    cap_str   = _format_capacity(offer)
    html = f"""
    <div style="font-family:sans-serif;max-width:500px">
      <h3 style="color:#1a1a2e">🚛 Новое транспортное предложение по вашей подписке</h3>
      <p style="font-size:18px;font-weight:bold">{offer.from_city} → {offer.to_city}</p>
      <table style="font-size:14px;color:#333">
        <tr><td>Кузов:</td><td>{offer.truck_type or '—'}</td></tr>
        <tr><td>Вместимость:</td><td>{cap_str or '—'}</td></tr>
        <tr><td>Цена:</td><td>{price_str}</td></tr>
        {'<tr><td>Примечание:</td><td>' + offer.notes[:100] + '</td></tr>' if offer.notes else ''}
      </table>
      <a href="{site_url}" style="display:inline-block;margin-top:16px;background:#f7b731;color:#1a1a2e;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:bold">Смотреть →</a>
    </div>
    """
    try:
        await send_email(email, subject, html)
        return True
    except Exception as e:
        logger.warning(f"[TRANSPORT SUB] Email notify failed: {e}")
        return False


async def notify_transport_subscribers(offer: TransportOffer, db: AsyncSession) -> int:
    """
    BackgroundTask — вызывается после POST /api/transport/.
    Находит матчащие подписки и отправляет уведомления.
    """
    import traceback as _traceback
    try:
        matched = await find_matching_transport_subscriptions(offer, db)
        if not matched:
            return 0

        sent = 0
        for sub in matched:
            if _is_debounced(sub.id, offer.id):
                continue

            user_res = await db.execute(select(User).where(User.id == sub.user_id))
            user = user_res.scalar_one_or_none()
            if not user or user.is_deleted:
                continue

            ok = False

            if sub.notify_tg and user.telegram_id and not user.telegram_id.startswith("pending:"):
                ok = await _send_tg_notification(user.telegram_id, offer)

            if not ok and sub.notify_email and user.email:
                ok = await _send_email_notification(user.email, offer)

            if ok:
                _mark_debounce(sub.id, offer.id)
                sent += 1
                logger.info(f"[TRANSPORT SUB] notified sub={sub.id} user={sub.user_id} offer={offer.id}")

        return sent
    except Exception as e:
        logger.error(
            "[BackgroundTask] notify_transport_subscribers failed",
            extra={
                "task": "notify_transport_subscribers",
                "offer_id": getattr(offer, "id", None),
                "error": str(e),
                "traceback": _traceback.format_exc(),
            }
        )
        return 0
