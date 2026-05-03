"""
Idempotency Key — защита от дублирования критичных действий (2.5.4).

Метод: in-memory кеш ключей с TTL 5 минут.
Критичные эндпоинты принимают заголовок X-Idempotency-Key.
Повторный запрос с тем же ключом → 409 Conflict с пояснением.

Ключ должен быть уникальным UUID от клиента (генерируется фронтом перед отправкой).
Если заголовок отсутствует — запрос проходит без проверки идемпотентности.

Использование:
    from app.services.idempotency import check_idempotency
    await check_idempotency(request, scope="respond_to_load")

Redis-замена в будущем: заменить _store на redis.set(key, ..., ex=300).
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Request, HTTPException

# TTL хранения ключей — 5 минут
_KEY_TTL = timedelta(minutes=5)

# {scope: {key: expires_at}}
_store: dict[str, dict[str, datetime]] = {}
_store_lock = asyncio.Lock()


async def check_idempotency(
    request: Request,
    scope: str,
    user_id: Optional[int] = None,
) -> None:
    """
    Проверяет X-Idempotency-Key заголовок.

    Если ключ уже использован в этом scope → 409.
    Если ключа нет — пропускает без проверки.

    Args:
        request: FastAPI Request
        scope: строка-пространство имён ("respond_to_load", "accept_response", etc.)
        user_id: добавляется к ключу для изоляции по пользователю
    """
    raw_key = request.headers.get("X-Idempotency-Key", "").strip()
    if not raw_key:
        return  # ключ не передан — пропускаем проверку

    # Составной ключ: scope + user_id + client_key
    compound = f"{scope}:{user_id or 'anon'}:{raw_key}"

    async with _store_lock:
        now = datetime.now(timezone.utc)
        # Чистим истёкшие ключи (lazy cleanup)
        if scope in _store:
            _store[scope] = {
                k: v for k, v in _store[scope].items() if v > now
            }

        bucket = _store.setdefault(scope, {})
        if compound in bucket:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "idempotency_conflict",
                    "message": "Duplicate request: this operation was already processed. "
                               "Use a new X-Idempotency-Key for a new request.",
                    "key": raw_key,
                }
            )

        bucket[compound] = now + _KEY_TTL


def clear_idempotency_cache() -> None:
    """Для тестов — очистить весь кеш."""
    _store.clear()
