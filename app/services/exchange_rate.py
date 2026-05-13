"""
Модуль получения курса NBG (Национальный банк Грузии).

API: https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json
Кеш: in-memory, 1 час.

Использование:
    from app.services.exchange_rate import get_usd_gel_rate, convert_gel_to_usd, convert_usd_to_gel
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

NBG_API_URL = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json"
CACHE_TTL_HOURS = 1
FALLBACK_RATE = 2.70  # резервный курс если NBG недоступен

# ── In-memory кеш ─────────────────────────────────────────────────────────────
_cache: dict = {
    "rate": None,          # float: GEL за 1 USD
    "expires_at": None,    # datetime UTC
}
_cache_lock = asyncio.Lock()


async def get_usd_gel_rate() -> float:
    """
    Возвращает курс: сколько GEL за 1 USD по данным NBG.
    Кешируется на 1 час. При недоступности API — возвращает FALLBACK_RATE.
    """
    async with _cache_lock:
        now = datetime.now(timezone.utc)
        if _cache["rate"] and _cache["expires_at"] and now < _cache["expires_at"]:
            return _cache["rate"]

        rate = await _fetch_rate_from_nbg()
        _cache["rate"] = rate
        _cache["expires_at"] = now + timedelta(hours=CACHE_TTL_HOURS)
        return rate


async def _fetch_rate_from_nbg() -> float:
    """Запрашивает свежий курс из NBG API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(NBG_API_URL)
            r.raise_for_status()
            data = r.json()

        # Структура ответа: [{date, currencies: [{code, rate, quantity, ...}]}]
        if not data or not isinstance(data, list):
            raise ValueError("Unexpected NBG response format")

        currencies = data[0].get("currencies", [])
        for cur in currencies:
            if cur.get("code") == "USD":
                rate = float(cur["rate"]) / float(cur.get("quantity", 1))
                logger.info(f"[NBG] USD rate: {rate} GEL (fetched at {datetime.now(timezone.utc).isoformat()})")
                return rate

        raise ValueError("USD not found in NBG response")

    except Exception as exc:
        logger.warning(f"[NBG] Failed to fetch rate: {exc}. Using fallback chain.")
        # Fallback 1: in-memory cache
        if _cache.get("rate"):
            logger.info("[NBG] Using cached rate as fallback")
            return _cache["rate"]
        # Fallback 2: константа
        logger.warning(f"[NBG] No cache available, using FALLBACK_RATE={FALLBACK_RATE}")
        return FALLBACK_RATE


def convert_gel_to_usd(amount_gel, rate) -> "Decimal":
    """Конвертирует лари в USD. rate = GEL за 1 USD. Возвращает Decimal."""
    from decimal import Decimal, ROUND_HALF_UP
    d_amount = Decimal(str(amount_gel)) if not isinstance(amount_gel, Decimal) else amount_gel
    d_rate = Decimal(str(rate)) if not isinstance(rate, Decimal) else rate
    if d_rate <= 0:
        return Decimal("0.00")
    return (d_amount / d_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def convert_usd_to_gel(amount_usd, rate) -> "Decimal":
    """Конвертирует USD в лари. rate = GEL за 1 USD. Возвращает Decimal."""
    from decimal import Decimal, ROUND_HALF_UP
    d_amount = Decimal(str(amount_usd)) if not isinstance(amount_usd, Decimal) else amount_usd
    d_rate = Decimal(str(rate)) if not isinstance(rate, Decimal) else rate
    return (d_amount * d_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def invalidate_cache() -> None:
    """Сбросить кеш (для тестов)."""
    _cache["rate"] = None
    _cache["expires_at"] = None
