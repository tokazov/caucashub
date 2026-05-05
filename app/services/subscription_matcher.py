"""
Этап 2 подписок — матчинг и уведомления (ADR-014).

Логика:
1. После создания груза → find_matching_subscriptions(load)
2. Для каждого матча → send_subscription_notification(sub, load)
3. Дебаунс: один раз за 60 сек на пару (sub_id, load_id)
4. Каналы: Telegram (приоритет) → email (fallback)
"""
import logging
import time
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.subscription import RouteSubscription
from app.models.user import User
from app.models.load import Load

logger = logging.getLogger(__name__)

# Дебаунс: (sub_id, load_id) → timestamp последней отправки
_debounce_cache: dict[tuple[int, int], float] = {}
DEBOUNCE_SECONDS = 60


def _is_debounced(sub_id: int, load_id: int) -> bool:
    key = (sub_id, load_id)
    last = _debounce_cache.get(key, 0)
    return (time.monotonic() - last) < DEBOUNCE_SECONDS


def _mark_debounce(sub_id: int, load_id: int) -> None:
    _debounce_cache[(sub_id, load_id)] = time.monotonic()
    # Чистим старые записи раз в 1000 уведомлений
    if len(_debounce_cache) > 1000:
        cutoff = time.monotonic() - DEBOUNCE_SECONDS * 2
        expired = [k for k, v in _debounce_cache.items() if v < cutoff]
        for k in expired:
            del _debounce_cache[k]


def _normalize(city: str) -> str:
    return city.strip().lower()


def _cities_match(sub_city: str, load_city: str) -> bool:
    """Матч по городу — точное совпадение нормализованных строк."""
    return _normalize(sub_city) == _normalize(load_city)


def _truck_type_match(sub_type: Optional[str], load_type: Optional[str]) -> bool:
    """Если в подписке не задан тип — подходит любой. Иначе точное совпадение."""
    if not sub_type:
        return True
    if not load_type:
        return False
    return sub_type.lower() == load_type.lower()


def _weight_match(sub_max_t: Optional[int], load_kg: Optional[float]) -> bool:
    """Если в подписке нет лимита веса — подходит любой груз."""
    if not sub_max_t:
        return True
    if not load_kg:
        return True
    return (load_kg / 1000) <= sub_max_t


async def find_matching_subscriptions(
    load: Load,
    db: AsyncSession,
) -> list[RouteSubscription]:
    """
    Находит активные подписки которые матчат данный груз.
    Не возвращает подписку владельца груза (незачем самому себе слать).
    """
    result = await db.execute(
        select(RouteSubscription).where(
            RouteSubscription.is_active == True,  # noqa: E712
            RouteSubscription.user_id != load.user_id,
        )
    )
    subs = result.scalars().all()

    matched = []
    for sub in subs:
        if not _cities_match(sub.from_city, load.from_city or ""):
            continue
        if not _cities_match(sub.to_city, load.to_city or ""):
            continue
        if not _truck_type_match(sub.truck_type, load.truck_type):
            continue
        if not _weight_match(sub.max_weight_t, load.weight_kg):
            continue
        matched.append(sub)

    return matched


def _format_price(load: Load) -> str:
    if load.price_gel:
        return f"{load.price_gel:,.0f} ₾".replace(",", " ")
    if load.price_usd:
        return f"${load.price_usd:,.0f}".replace(",", " ")
    return "—"


def _format_weight(load: Load) -> str:
    if not load.weight_kg:
        return ""
    t = load.weight_kg / 1000
    return f"{t:.1f} т" if t < 10 else f"{int(t)} т"


async def _send_tg_notification(
    telegram_id: str,
    load: Load,
    site_url: str = "https://caucashub.ge",
) -> bool:
    """Отправляет TG-уведомление. Возвращает True если успешно."""
    import os
    import httpx

    bot_token = os.getenv("CAUCASHUB_TG_BOT_TOKEN", "")
    if not bot_token or telegram_id.startswith("pending:"):
        return False

    price_str  = _format_price(load)
    weight_str = _format_weight(load)
    truck_str  = load.truck_type or ""

    parts = ["🚛 *Новый груз по подписке*"]
    parts.append(f"*{load.from_city} → {load.to_city}*")
    details = []
    if truck_str:
        details.append(truck_str)
    if weight_str:
        details.append(weight_str)
    if price_str != "—":
        details.append(price_str)
    if details:
        parts.append(" · ".join(details))
    if load.cargo_desc:
        parts.append(f"_{load.cargo_desc[:80]}_")
    parts.append(f"[Открыть груз]({site_url})")

    text = "\n".join(parts)
    payload = {
        "chat_id": telegram_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload,
            )
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"[SUB] TG notify failed for {telegram_id}: {e}")
        return False


async def _send_email_notification(
    email: str,
    load: Load,
    site_url: str = "https://caucashub.ge",
) -> bool:
    """Email fallback уведомление."""
    try:
        from app.services.email_service import send_email
    except ImportError:
        return False

    price_str  = _format_price(load)
    weight_str = _format_weight(load)
    subject = f"🚛 Новый груз: {load.from_city} → {load.to_city}"
    html = f"""
    <div style="font-family:sans-serif;max-width:500px">
      <h3 style="color:#1a1a2e">🚛 Новый груз по вашей подписке</h3>
      <p style="font-size:18px;font-weight:bold">{load.from_city} → {load.to_city}</p>
      <table style="font-size:14px;color:#333">
        <tr><td>Кузов:</td><td>{load.truck_type or '—'}</td></tr>
        <tr><td>Вес:</td><td>{weight_str or '—'}</td></tr>
        <tr><td>Цена:</td><td>{price_str}</td></tr>
        {'<tr><td>Описание:</td><td>' + load.cargo_desc[:100] + '</td></tr>' if load.cargo_desc else ''}
      </table>
      <a href="{site_url}" style="display:inline-block;margin-top:16px;background:#f7b731;color:#1a1a2e;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:bold">Открыть биржу →</a>
    </div>
    """
    try:
        await send_email(email, subject, html)
        return True
    except Exception as e:
        logger.warning(f"[SUB] Email notify failed for {email}: {e}")
        return False


async def notify_subscribers(load: Load, db: AsyncSession) -> int:
    """
    Главная функция — вызывается из BackgroundTasks после создания груза.
    Возвращает кол-во отправленных уведомлений.
    """
    import traceback as _traceback
    try:
        matched = await find_matching_subscriptions(load, db)
        if not matched:
            return 0

        sent = 0
        for sub in matched:
            if _is_debounced(sub.id, load.id):
                logger.debug(f"[SUB] debounce skip sub={sub.id} load={load.id}")
                continue

            # Загружаем пользователя
            user_res = await db.execute(select(User).where(User.id == sub.user_id))
            user = user_res.scalar_one_or_none()
            if not user or user.is_deleted:
                continue

            ok = False

            # Telegram — приоритет
            if sub.notify_tg and user.telegram_id and not user.telegram_id.startswith("pending:"):
                ok = await _send_tg_notification(user.telegram_id, load)

            # Email — fallback
            if not ok and sub.notify_email and user.email:
                ok = await _send_email_notification(user.email, load)

            if ok:
                _mark_debounce(sub.id, load.id)
                sent += 1
                logger.info(f"[SUB] notified sub={sub.id} user={sub.user_id} load={load.id}")

        return sent
    except Exception as e:
        logger.error(
            "[BackgroundTask] notify_subscribers failed",
            extra={
                "task": "notify_subscribers",
                "load_id": getattr(load, "id", None),
                "error": str(e),
                "traceback": _traceback.format_exc(),
            }
        )
        return 0
