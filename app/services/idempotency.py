"""
Idempotency Key — Postgres-backed store (ADR-013 follow-up).

Поведение:
  - Заголовок: `Idempotency-Key` (IETF draft, без X- префикса).
  - TTL: 24 часа.
  - Хэш тела запроса: sha256(raw bytes) — отлавливает коллизию ключ+разное тело.
  - При повторе с тем же ключом и тем же телом: возвращает сохранённый ответ +
    заголовок `Idempotency-Replayed: true` (без обращения к бизнес-логике).
  - При повторе с тем же ключом и ДРУГИМ телом: 422 payload_mismatch.
  - Если заголовок отсутствует: запрос проходит без идемпотентности.
  - Только для мутирующих эндпоинтов (create_load, create_response, и т.д.).

Использование в роутере:
    result, replayed = await check_idempotency(request, db, scope, user_id)
    if replayed:
        return JSONResponse(
            content=result["body"],
            status_code=result["status"],
            headers={"Idempotency-Replayed": "true"}
        )
    # ... бизнес-логика ...
    await save_idempotency(request, db, scope, user_id, status_code, response_dict)

Фоновая очистка: запускается из main.py lifespan раз в час.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency_key import IdempotencyKey

# TTL для хранения ключей
_KEY_TTL = timedelta(hours=24)


def _get_key_header(request: Request) -> Optional[str]:
    """Читаем Idempotency-Key заголовок (без X- префикса, IETF draft)."""
    return request.headers.get("Idempotency-Key", "").strip() or None


async def _hash_body(request: Request) -> str:
    """sha256 от raw-байт тела запроса.
    
    Кешируем в request.state чтобы избежать проблем с повторным чтением
    (FastAPI/Starlette уже прочитали тело для парсинга JSON).
    """
    cached = getattr(request.state, "_idempotency_body_hash", None)
    if cached:
        return cached
    body = await request.body()
    h = hashlib.sha256(body).hexdigest()
    request.state._idempotency_body_hash = h
    return h


async def check_idempotency(
    request: Request,
    db: AsyncSession,
    scope: str,
    user_id: int,
) -> Tuple[Optional[dict], bool]:
    """
    Шаг 1 из 2: проверяем наличие записи для (scope, user_id, key).

    Returns:
        (None, False)           — ключа нет / заголовок отсутствует → продолжаем обычно
        ({"status": int, "body": dict}, True)  — нашли replay → вернуть сохранённый ответ
    Raises:
        HTTPException 422       — тот же ключ, но разное тело
    """
    raw_key = _get_key_header(request)
    if not raw_key:
        return None, False

    request_hash = await _hash_body(request)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.scope   == scope,
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key     == raw_key,
            IdempotencyKey.expires_at > now,
        )
    )
    record = result.scalar_one_or_none()

    if record is None:
        return None, False

    if record.request_hash != request_hash:
        raise HTTPException(
            status_code=422,
            detail={
                "code":    "idempotency_payload_mismatch",
                "message": "Same Idempotency-Key was used with a different request body.",
                "key":     raw_key,
            },
        )

    # Совпадение — возвращаем сохранённый ответ
    return {"status": record.response_status, "body": record.response_body}, True


async def save_idempotency(
    request: Request,
    db: AsyncSession,
    scope: str,
    user_id: int,
    response_status: int,
    response_body: Any,
) -> None:
    """
    Шаг 2 из 2: после успешного выполнения бизнес-логики сохраняем ответ.
    Если ключ отсутствует — ничего не делаем.
    """
    raw_key = _get_key_header(request)
    if not raw_key:
        return

    request_hash = await _hash_body(request)
    now = datetime.now(timezone.utc)

    # Сериализуем тело в plain dict (JSONifiable).
    # Decimal → float (после миграции ADR-006 prices хранятся как NUMERIC).
    from decimal import Decimal
    def _json_default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    try:
        response_body = json.loads(json.dumps(response_body, default=_json_default))
    except Exception:
        response_body = {"_raw": str(response_body)}

    record = IdempotencyKey(
        key=raw_key,
        user_id=user_id,
        scope=scope,
        request_hash=request_hash,
        response_status=response_status,
        response_body=response_body,
        created_at=now,
        expires_at=now + _KEY_TTL,
    )
    db.add(record)
    try:
        await db.commit()
    except Exception:
        # Гонка: два параллельных запроса с одним ключом — один выиграл, второй молча игнорирует
        await db.rollback()


def make_idempotent_response(cached: dict) -> JSONResponse:
    """Формирует JSONResponse из кешированной записи с заголовком Idempotency-Replayed."""
    return JSONResponse(
        content=cached["body"],
        status_code=cached["status"],
        headers={"Idempotency-Replayed": "true"},
    )


async def cleanup_expired_keys(db: AsyncSession) -> int:
    """
    Удаляет протухшие ключи. Вызывается из фоновой задачи раз в час.
    Возвращает кол-во удалённых строк.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        delete(IdempotencyKey).where(IdempotencyKey.expires_at < now)
    )
    await db.commit()
    return result.rowcount


# ── Совместимость со старым кодом (вызовы check_idempotency без db) ───────────
# Старый сигнатура: check_idempotency(request, scope, user_id) — только in-memory.
# Новый код использует Postgres. Все вызовы роутеров обновлены ниже.
# Эта заглушка не используется в продакшне — только для тестов которые ещё не обновлены.

def clear_idempotency_cache() -> None:
    """No-op: in-memory кеш удалён. Оставлен для совместимости с тестами."""
    pass
