"""
In-memory rate limiter для защиты чувствительных эндпоинтов.

ВАЖНО: не переживает рестарт Railway (приемлемо для низкочастотных операций
типа удаления аккаунта — не использовать для login или hot-path).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

_attempts: dict[str, list[datetime]] = defaultdict(list)


def check_rate_limit(key: str, limit: int, window: timedelta) -> bool:
    """
    Проверяет rate limit. Возвращает True если запрос разрешён, False если превышен.
    Потокобезопасность: asyncio однопоточный, GIL защищает dict операции.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - window
    # Очищаем устаревшие записи
    _attempts[key] = [t for t in _attempts[key] if t > cutoff]
    if len(_attempts[key]) >= limit:
        return False
    _attempts[key].append(now)
    return True


def reset_rate_limit(key: str) -> None:
    """Сброс лимита (для тестов)."""
    _attempts.pop(key, None)
