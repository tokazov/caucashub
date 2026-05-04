"""
Тесты остаточных задач Трека 10:
- 2.4.2 Блокировка аккаунта
- 2.5.4 Idempotency Key
- 1.9.5 Backfill городов (скрипт, не интеграционный)
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_remainder.db")
os.environ.setdefault("SECRET_KEY", "test-remainder")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User, UserRole, UserPlan
from app.models.load import Load, LoadStatus, TruckType, LoadScope
from app.models.response import Response, ResponseStatus
from app.models.deal import Deal, DealStatus
from app.services import exchange_rate as er_module
from app.services.idempotency import clear_idempotency_cache
from passlib.context import CryptContext
from sqlalchemy import select, delete

pwd = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
RATE = 2.73
ADMIN_SECRET = "caucashub-admin-2026"


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.services.cities_seed import seed_cities
    from app.models.status_change import StatusChange
    async with AsyncSessionLocal() as db:
        await db.execute(delete(StatusChange))
        await db.execute(delete(Deal))
        await db.execute(delete(Response))
        await db.execute(delete(Load))
        await db.execute(delete(User))
        await db.commit()
        await seed_cities(db)
    er_module.invalidate_cache()
    clear_idempotency_cache()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _reg(client, email, phone, role="carrier"):
    r = await client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!",
        "company_name": f"Co {role}", "phone": phone, "role": role,
    })
    assert r.status_code == 200, r.text
    return r.json()["token"], r.json()["user_id"]


async def _load(client, token) -> int:
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=RATE):
        er_module.invalidate_cache()
        r = await client.post("/api/loads/", json={
            "from_city": "Тбилиси", "to_city": "Батуми",
            "weight_kg": 1000, "truck_type": "tent", "price_gel": 500.0,
        }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── 2.4.2: Блокировка аккаунта ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_block_user_pauses_active_loads():
    """Блокировка пользователя → активные грузы переходят в paused."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token, user_id = await _reg(client, "block1@test.ge", "+99591010001", "shipper")
            load_id = await _load(client, token)

            # Блокируем через admin endpoint
            r = await client.post(f"/api/users/admin/{user_id}/block",
                                  params={"secret": ADMIN_SECRET, "reason": "test"})
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["blocked"] is True
            assert data["loads_paused"] >= 1

    # Проверяем в БД — груз paused
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Load).where(Load.id == load_id))
        load = result.scalar_one()
        assert str(load.status) in ("paused", "LoadStatus.paused")


@pytest.mark.asyncio
async def test_blocked_user_cannot_login():
    """Заблокированный пользователь не может логиниться."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token, user_id = await _reg(client, "block2@test.ge", "+99591010002")
        await client.post(f"/api/users/admin/{user_id}/block",
                          params={"secret": ADMIN_SECRET})

        login_r = await client.post("/api/auth/login",
                                    json={"email": "block2@test.ge", "password": "TestPass123!"})
        # Заблокированный → учётные данные верны, но is_active=False
        # login возвращает 401 (no email) или токен — зависит от реализации
        # По нашей логике: require_user проверяет is_active после логина
        # Логин УСПЕШЕН (email есть), но API вернёт 403 при следующем запросе
        if login_r.status_code == 200:
            new_token = login_r.json()["token"]
            me_r = await client.get("/api/users/me",
                                    headers={"Authorization": f"Bearer {new_token}"})
            assert me_r.status_code == 403, "Blocked user should get 403 on API requests"


@pytest.mark.asyncio
async def test_unblock_restores_paused_loads():
    """Разблокировка восстанавливает paused грузы в active."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token, user_id = await _reg(client, "block3@test.ge", "+99591010003", "shipper")
            load_id = await _load(client, token)

            # Блокируем
            await client.post(f"/api/users/admin/{user_id}/block",
                              params={"secret": ADMIN_SECRET})

            # Разблокируем
            r = await client.post(f"/api/users/admin/{user_id}/unblock",
                                  params={"secret": ADMIN_SECRET})
            assert r.status_code == 200
            assert r.json()["loads_restored"] >= 1

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Load).where(Load.id == load_id))
        load = result.scalar_one()
        assert str(load.status) in ("active", "LoadStatus.active")


@pytest.mark.asyncio
async def test_block_preserves_active_deals():
    """Блокировка не трогает активные сделки — вторая сторона завершает их."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token, shipper_id = await _reg(client, "block4sh@test.ge", "+99591010004", "shipper")
            carrier_token, _ = await _reg(client, "block4ca@test.ge", "+99591010005", "carrier")
            load_id = await _load(client, shipper_token)

            # Создаём сделку
            resp = await client.post(f"/api/responses/load/{load_id}", json={"price": 400.0},
                                     headers={"Authorization": f"Bearer {carrier_token}"})
            resp_id = resp.json()["response_id"]
            await client.post(f"/api/responses/accept/{resp_id}",
                               headers={"Authorization": f"Bearer {shipper_token}"})

            # Блокируем shipper
            r = await client.post(f"/api/users/admin/{shipper_id}/block",
                                  params={"secret": ADMIN_SECRET})
            assert r.status_code == 200

    # Сделка должна остаться в статусе confirmed
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Deal))
        deal = result.scalar_one()
        assert str(deal.status) in ("confirmed", "DealStatus.confirmed"), \
            f"Deal should remain confirmed, got {deal.status}"


# ── 2.5.4: Idempotency Key ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idempotency_key_prevents_duplicate_respond():
    """Повторный отклик с тем же X-Idempotency-Key → 409."""
    clear_idempotency_cache()
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token, _ = await _reg(client, "idem1sh@test.ge", "+99591011001", "shipper")
            carrier_token, _ = await _reg(client, "idem1ca@test.ge", "+99591011002", "carrier")
            load_id = await _load(client, shipper_token)

            headers = {
                "Authorization": f"Bearer {carrier_token}",
                "X-Idempotency-Key": "test-key-abc123"
            }

            # Первый запрос — должен пройти
            r1 = await client.post(f"/api/responses/load/{load_id}",
                                   json={"price": 400.0}, headers=headers)
            assert r1.status_code == 200, r1.text

            # Второй с тем же ключом — 409
            r2 = await client.post(f"/api/responses/load/{load_id}",
                                   json={"price": 400.0}, headers=headers)
            assert r2.status_code == 409, f"Expected 409, got {r2.status_code}: {r2.text}"
            assert r2.json()["detail"]["code"] == "idempotency_conflict"


@pytest.mark.asyncio
async def test_idempotency_key_different_key_allowed():
    """Разные X-Idempotency-Key — каждый запрос обрабатывается нормально."""
    clear_idempotency_cache()
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token, _ = await _reg(client, "idem2sh@test.ge", "+99591011003", "shipper")
            carrier_token, _ = await _reg(client, "idem2ca@test.ge", "+99591011004", "carrier")
            load_id = await _load(client, shipper_token)

            # Первый запрос с ключом-1 — OK
            r1 = await client.post(f"/api/responses/load/{load_id}",
                                   json={"price": 400.0},
                                   headers={"Authorization": f"Bearer {carrier_token}",
                                            "X-Idempotency-Key": "key-1"})
            assert r1.status_code == 200

            # Попытка дублировать с ключом-2 → 400 Already responded (дублируем отклик, не ключ)
            r2 = await client.post(f"/api/responses/load/{load_id}",
                                   json={"price": 390.0},
                                   headers={"Authorization": f"Bearer {carrier_token}",
                                            "X-Idempotency-Key": "key-2"})
            # Должно быть 400 (already responded), не 409 (idempotency)
            assert r2.status_code == 400
            assert "already" in r2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_no_idempotency_key_works_normally():
    """Без X-Idempotency-Key — запрос проходит без проверки идемпотентности."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token, _ = await _reg(client, "idem3sh@test.ge", "+99591011005", "shipper")
            carrier_token, _ = await _reg(client, "idem3ca@test.ge", "+99591011006", "carrier")
            load_id = await _load(client, shipper_token)

            r = await client.post(f"/api/responses/load/{load_id}",
                                  json={"price": 400.0},
                                  headers={"Authorization": f"Bearer {carrier_token}"})
            assert r.status_code == 200


# ── 1.9.5: Backfill городов — unit test ──────────────────────────────────────

@pytest.mark.asyncio
async def test_backfill_cities_matches_known_city():
    """Backfill находит 'Тбилиси' по первым 4 буквам."""
    from scripts.backfill_cities import _normalize_for_match
    assert _normalize_for_match("Тбилиси") == "тбил"
    assert _normalize_for_match("  ТБИЛИСИ  ") == "тбил"
    assert _normalize_for_match("тбил") == "тбил"
