"""
Тесты Postgres-backed Idempotency (feat/idempotency-postgres).

Покрывают:
- test_idempotency_replay:         повторный POST с тем же ключом → 200 + Idempotency-Replayed + тот же id
- test_idempotency_payload_mismatch: тот же ключ, другое тело → 422
- test_idempotency_no_key:         запрос без заголовка → обычный 200, нет записи в таблице
- test_idempotency_expired:        expires_at в прошлом → повтор обрабатывается как новый
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_idempotency.db")
os.environ.setdefault("SECRET_KEY", "test-idempotency-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete as sql_delete, select

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User
from app.models.load import Load
from app.models.idempotency_key import IdempotencyKey
from app.routers.auth import create_token

transport = ASGITransport(app=app)

# ── Фикстуры ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Создаём схему + чистим таблицы перед каждым тестом."""
    from app.models.response import Response
    from app.models.deal import Deal
    from app.models.status_change import StatusChange

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await db.execute(sql_delete(IdempotencyKey))
        await db.execute(sql_delete(StatusChange))
        await db.execute(sql_delete(Deal))
        await db.execute(sql_delete(Response))
        await db.execute(sql_delete(Load))
        await db.execute(sql_delete(User))
        await db.commit()

    yield

    # Teardown — чистим БД
    async with AsyncSessionLocal() as db:
        await db.execute(sql_delete(IdempotencyKey))
        await db.execute(sql_delete(StatusChange))
        await db.execute(sql_delete(Deal))
        await db.execute(sql_delete(Response))
        await db.execute(sql_delete(Load))
        await db.execute(sql_delete(User))
        await db.commit()


async def _register_user(client, suffix, role="shipper"):
    r = await client.post("/api/auth/register", json={
        "email": f"idem_{suffix}@test.ge",
        "password": "Test1234!",
        "company_name": f"Idem Co {suffix}",
        "phone": f"+7999{suffix[:6].ljust(6,'0')}",
        "role": role,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    return data.get("access_token") or data.get("token")


def _load_body(from_city="Тбилиси", to_city="Батуми", weight=1000):
    return {
        "from_city": from_city,
        "to_city": to_city,
        "weight_kg": weight,
        "truck_type": "tent",
        "price_gel": 500,
        "is_urgent": False,
    }


# ── Тесты ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@patch("app.services.subscription_matcher.notify_subscribers", new_callable=AsyncMock)
async def test_idempotency_replay(_mock_notify):
    """
    Повторный POST /api/loads/ с тем же Idempotency-Key и тем же телом:
    - второй ответ: 200
    - заголовок Idempotency-Replayed: true
    - тот же id груза (не создаётся дубль)
    """
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_user(client, "replay1")
        headers = {"Authorization": f"Bearer {token}"}
        body = _load_body()
        idem_key = "test-replay-uuid-0001"

        # Первый запрос
        r1 = await client.post("/api/loads/", json=body,
                                headers={**headers, "Idempotency-Key": idem_key})
        assert r1.status_code == 200, r1.text
        load_id_1 = r1.json().get("id") or r1.json().get("load_id")
        assert load_id_1, f"Expected id in response, got: {r1.json()}"
        assert "Idempotency-Replayed" not in r1.headers

        # Второй запрос — тот же ключ, то же тело
        r2 = await client.post("/api/loads/", json=body,
                                headers={**headers, "Idempotency-Key": idem_key})
        assert r2.status_code == 200, r2.text
        load_id_2 = r2.json().get("id") or r2.json().get("load_id")
        assert load_id_2 == load_id_1, \
            f"Expected same id on replay, got {load_id_2} vs {load_id_1}"
        assert r2.headers.get("Idempotency-Replayed") == "true", \
            f"Expected Idempotency-Replayed header, got: {dict(r2.headers)}"

        # В БД должен быть только один груз
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Load))
            loads = res.scalars().all()
        assert len(loads) == 1, f"Expected 1 load in DB, got {len(loads)}"


@pytest.mark.asyncio
@patch("app.services.subscription_matcher.notify_subscribers", new_callable=AsyncMock)
async def test_idempotency_payload_mismatch(_mock_notify):
    """
    Тот же Idempotency-Key, но разное тело запроса → 422 payload_mismatch.
    """
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_user(client, "mismatch1")
        headers = {"Authorization": f"Bearer {token}"}
        idem_key = "test-mismatch-uuid-0002"

        body1 = _load_body(from_city="Тбилиси", weight=1000)
        body2 = _load_body(from_city="Кутаиси", weight=2000)  # отличается

        # Первый запрос
        r1 = await client.post("/api/loads/", json=body1,
                                headers={**headers, "Idempotency-Key": idem_key})
        assert r1.status_code == 200, r1.text

        # Второй запрос — тот же ключ, другое тело
        r2 = await client.post("/api/loads/", json=body2,
                                headers={**headers, "Idempotency-Key": idem_key})
        assert r2.status_code == 422, r2.text
        detail = r2.json().get("detail", {})
        assert detail.get("code") == "idempotency_payload_mismatch", \
            f"Expected payload_mismatch, got: {detail}"
        assert detail.get("key") == idem_key


@pytest.mark.asyncio
@patch("app.services.subscription_matcher.notify_subscribers", new_callable=AsyncMock)
async def test_idempotency_no_key(_mock_notify):
    """
    Запрос без заголовка Idempotency-Key:
    - проходит как обычно (200)
    - запись в idempotency_keys НЕ создаётся
    """
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_user(client, "nokey1")
        headers = {"Authorization": f"Bearer {token}"}
        body = _load_body()

        r = await client.post("/api/loads/", json=body, headers=headers)
        assert r.status_code == 200, r.text

        async with AsyncSessionLocal() as db:
            res = await db.execute(select(IdempotencyKey))
            keys = res.scalars().all()
        assert len(keys) == 0, \
            f"Expected no idempotency records without key, got {len(keys)}"


@pytest.mark.asyncio
@patch("app.services.subscription_matcher.notify_subscribers", new_callable=AsyncMock)
async def test_idempotency_expired(_mock_notify):
    """
    Если запись в idempotency_keys истекла (expires_at в прошлом):
    повторный запрос с тем же ключом обрабатывается как новый (не replay).
    """
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_user(client, "expired1")
        headers = {"Authorization": f"Bearer {token}"}
        body = _load_body()
        idem_key = "test-expired-uuid-0003"

        # Первый запрос — создаём запись
        r1 = await client.post("/api/loads/", json=body,
                                headers={**headers, "Idempotency-Key": idem_key})
        assert r1.status_code == 200, r1.text
        load_id_1 = r1.json().get("id") or r1.json().get("load_id")

        # Вручную обнуляем expires_at (делаем протухшим)
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(IdempotencyKey))
            record = res.scalar_one_or_none()
            assert record is not None
            record.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            await db.commit()

        # Второй запрос — то же тело, тот же ключ, но запись истекла
        r2 = await client.post("/api/loads/", json=body,
                                headers={**headers, "Idempotency-Key": idem_key})
        assert r2.status_code == 200, r2.text
        load_id_2 = r2.json().get("id") or r2.json().get("load_id")

        # Это новый груз — id отличается
        assert load_id_2 != load_id_1, \
            "Expected new load after expiry, but got the same id"
        assert "Idempotency-Replayed" not in r2.headers


@pytest.mark.asyncio
@patch("app.services.subscription_matcher.notify_subscribers", new_callable=AsyncMock)
async def test_idempotency_payload_mismatch_first_not_overwritten(_mock_notify):
    """
    При payload_mismatch первый груз остался нетронутым в БД.
    """
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_user(client, "mismatch2")
        headers = {"Authorization": f"Bearer {token}"}
        idem_key = "test-mismatch-overwrite-0004"

        body1 = _load_body(from_city="Тбилиси", weight=1000)
        body2 = _load_body(from_city="Поти", weight=3000)

        r1 = await client.post("/api/loads/", json=body1,
                                headers={**headers, "Idempotency-Key": idem_key})
        assert r1.status_code == 200
        original_id = r1.json().get("id") or r1.json().get("load_id")

        r2 = await client.post("/api/loads/", json=body2,
                                headers={**headers, "Idempotency-Key": idem_key})
        assert r2.status_code == 422

        # Проверяем: в БД ровно 1 груз и это именно первый
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Load))
            loads = res.scalars().all()
        assert len(loads) == 1, f"Expected 1 load (first not overwritten), got {len(loads)}"
        assert loads[0].id == original_id


@pytest.mark.asyncio
@patch("app.services.subscription_matcher.notify_subscribers", new_callable=AsyncMock)
async def test_idempotency_cross_user_isolation(_mock_notify):
    """
    Один и тот же Idempotency-Key от разных пользователей — независимые операции.
    Каждый должен получить свой груз, не replay.
    """
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token_a = await _register_user(client, "crossA", role="shipper")
        token_b = await _register_user(client, "crossB", role="shipper")

        body_a = _load_body(from_city="Тбилиси", weight=1000)
        body_b = _load_body(from_city="Батуми", weight=2000)
        shared_key = "shared-key-cross-user-0005"

        r_a = await client.post("/api/loads/", json=body_a,
                                 headers={"Authorization": f"Bearer {token_a}",
                                          "Idempotency-Key": shared_key})
        assert r_a.status_code == 200, r_a.text
        id_a = r_a.json().get("id") or r_a.json().get("load_id")

        r_b = await client.post("/api/loads/", json=body_b,
                                 headers={"Authorization": f"Bearer {token_b}",
                                          "Idempotency-Key": shared_key})
        assert r_b.status_code == 200, r_b.text
        id_b = r_b.json().get("id") or r_b.json().get("load_id")

        # Разные пользователи → разные грузы
        assert id_a != id_b, "Cross-user with same key must create independent loads"
        assert "Idempotency-Replayed" not in r_b.headers

        # В БД два груза
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Load))
            loads = res.scalars().all()
        assert len(loads) == 2, f"Expected 2 loads (one per user), got {len(loads)}"


@pytest.mark.asyncio
@patch("app.services.subscription_matcher.notify_subscribers", new_callable=AsyncMock)
async def test_idempotency_not_saved_on_validation_error(_mock_notify):
    """
    Если запрос падает с ошибкой валидации (422 от бизнес-логики),
    idempotency-запись НЕ сохраняется.
    Следующий запрос с тем же ключом + валидным телом → создаётся нормально.
    """
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_user(client, "valerr1")
        headers = {"Authorization": f"Bearer {token}"}
        idem_key = "test-valerr-uuid-0006"

        # Невалидный груз: weight_kg = 0 → 422
        bad_body = _load_body(weight=0)
        r_bad = await client.post("/api/loads/", json=bad_body,
                                   headers={**headers, "Idempotency-Key": idem_key})
        assert r_bad.status_code == 422, r_bad.text

        # idempotency-запись не должна была создаться
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(IdempotencyKey))
            keys = res.scalars().all()
        assert len(keys) == 0, f"Expected no idem record after 422, got {len(keys)}"

        # Повторный запрос с тем же ключом + валидным телом → успех
        good_body = _load_body(weight=1000)
        r_good = await client.post("/api/loads/", json=good_body,
                                    headers={**headers, "Idempotency-Key": idem_key})
        assert r_good.status_code == 200, r_good.text
        assert "Idempotency-Replayed" not in r_good.headers
