"""
Тесты ADR-006: двойная валюта + снапшот курса NBG.

Проверяет:
1. Создание груза в GEL → автоматически заполняется price_usd
2. Создание груза в USD → автоматически заполняется price_gel
3. Создание отклика → price_usd конвертируется в price_gel
4. Создание сделки через accept_response → exchange_rate_snapshot зафиксирован
5. Курс кешируется (второй вызов не делает HTTP-запрос)
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_currency.db")
os.environ.setdefault("SECRET_KEY", "test-currency-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User, UserRole, UserPlan
from app.models.load import Load, LoadStatus, TruckType, LoadScope
from app.models.response import Response
from app.models.deal import Deal
from app.services import exchange_rate as er_module
from passlib.context import CryptContext
from sqlalchemy import select, delete
import datetime

pwd = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

# Фиксированный тестовый курс: 1 USD = 2.73 GEL
TEST_RATE = 2.73


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Deal))
        await db.execute(delete(Response))
        await db.execute(delete(Load))
        await db.execute(delete(User))
        await db.commit()

        shipper = User(
            email="shipper_c@test.ge",
            hashed_password=pwd.hash("pass123"),
            company_name="Shipper Co",
            phone="+99591111111",
            role=UserRole.shipper,
            plan=UserPlan.pro,
            is_active=True,
        )
        carrier = User(
            email="carrier_c@test.ge",
            hashed_password=pwd.hash("pass123"),
            company_name="Carrier Co",
            phone="+99592222222",
            role=UserRole.carrier,
            plan=UserPlan.pro,
            is_active=True,
        )
        db.add_all([shipper, carrier])
        await db.commit()

    er_module.invalidate_cache()

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "pass123"})
    assert r.status_code == 200
    return r.json()["token"]


# ── TEST 1: Груз в GEL → автозаполнение price_usd ────────────────────────────

@pytest.mark.asyncio
async def test_load_created_in_gel_fills_price_usd():
    """Груз создан в GEL — должен автоматически заполниться price_usd."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=TEST_RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await _login(client, "shipper_c@test.ge")
            r = await client.post("/api/loads/", json={
                "from_city": "Тбилиси", "to_city": "Батуми",
                "weight_kg": 1000, "truck_type": "tent",
                "price_gel": 819.0,   # GEL
                # price_usd не передаём
            }, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200

    # Проверяем в БД
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Load).where(Load.from_city == "Тбилиси"))
        load = result.scalar_one()
        assert float(load.price_gel) == 819.0
        assert load.price_usd is not None
        assert abs(float(load.price_usd) - 819.0 / TEST_RATE) < 0.05  # ±5 центов
        assert load.exchange_rate_at_creation == TEST_RATE


# ── TEST 2: Груз в USD → автозаполнение price_gel ────────────────────────────

@pytest.mark.asyncio
async def test_load_created_in_usd_fills_price_gel():
    """Груз создан в USD — должен автоматически заполниться price_gel."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=TEST_RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await _login(client, "shipper_c@test.ge")
            r = await client.post("/api/loads/", json={
                "from_city": "Кутаиси", "to_city": "Поти",
                "weight_kg": 2000, "truck_type": "ref",
                "price_usd": 300.0,   # USD
                # price_gel не передаём
            }, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Load).where(Load.from_city == "Кутаиси"))
        load = result.scalar_one()
        assert float(load.price_usd) == 300.0
        assert load.price_gel is not None
        assert abs(float(load.price_gel) - 300.0 * TEST_RATE) < 0.1
        assert load.exchange_rate_at_creation == TEST_RATE


# ── TEST 3: Отклик в GEL → price_usd заполнен ───────────────────────────────

@pytest.mark.asyncio
async def test_response_in_gel_fills_price_usd():
    """Перевозчик откликается с ценой в GEL — должен заполниться price_usd."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=TEST_RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token = await _login(client, "shipper_c@test.ge")
            carrier_token = await _login(client, "carrier_c@test.ge")

            # Создаём груз
            r = await client.post("/api/loads/", json={
                "from_city": "Гори", "to_city": "Рустави",
                "weight_kg": 500, "truck_type": "gazel",
                "price_gel": 400.0,
            }, headers={"Authorization": f"Bearer {shipper_token}"})
            assert r.status_code == 200
            load_id = r.json()["id"]

            # Откликаемся с ценой в GEL (price = GEL)
            r2 = await client.post(f"/api/responses/load/{load_id}", json={
                "price": 380.0,  # GEL
            }, headers={"Authorization": f"Bearer {carrier_token}"})
            assert r2.status_code == 200
            resp_id = r2.json()["response_id"]

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Response).where(Response.id == resp_id))
        resp = result.scalar_one()
        assert float(resp.price_gel) == 380.0
        assert resp.price_usd is not None
        assert abs(float(resp.price_usd) - 380.0 / TEST_RATE) < 0.05
        assert resp.exchange_rate_at_creation == TEST_RATE


# ── TEST 4: Создание сделки → exchange_rate_snapshot зафиксирован ────────────

@pytest.mark.asyncio
async def test_deal_has_exchange_rate_snapshot():
    """При принятии отклика создаётся сделка с зафиксированным курсом."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=TEST_RATE):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token = await _login(client, "shipper_c@test.ge")
            carrier_token = await _login(client, "carrier_c@test.ge")

            # Создаём груз
            r = await client.post("/api/loads/", json={
                "from_city": "Телави", "to_city": "Тбилиси",
                "weight_kg": 800, "truck_type": "bort",
                "price_gel": 500.0,
            }, headers={"Authorization": f"Bearer {shipper_token}"})
            assert r.status_code == 200
            load_id = r.json()["id"]

            # Отклик
            r2 = await client.post(f"/api/responses/load/{load_id}", json={
                "price": 480.0,
            }, headers={"Authorization": f"Bearer {carrier_token}"})
            assert r2.status_code == 200
            resp_id = r2.json()["response_id"]

            # Принимаем отклик
            r3 = await client.post(f"/api/responses/accept/{resp_id}",
                                   headers={"Authorization": f"Bearer {shipper_token}"})
            assert r3.status_code == 200

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Deal))
        deal = result.scalar_one()
        assert deal.exchange_rate_snapshot == TEST_RATE
        assert deal.final_price_gel is not None
        assert deal.final_price_usd is not None
        assert abs(float(deal.final_price_gel) - 480.0) < 0.1
        assert abs(float(deal.final_price_usd) - 480.0 / TEST_RATE) < 0.1


# ── TEST 5: Курс кешируется ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exchange_rate_caching():
    """NBG API вызывается только раз, второй раз — из кеша."""
    er_module.invalidate_cache()
    call_count = 0

    async def mock_fetch():
        nonlocal call_count
        call_count += 1
        return TEST_RATE

    with patch.object(er_module, '_fetch_rate_from_nbg', side_effect=mock_fetch):
        r1 = await er_module.get_usd_gel_rate()
        r2 = await er_module.get_usd_gel_rate()
        r3 = await er_module.get_usd_gel_rate()

    assert call_count == 1, f"Expected 1 API call, got {call_count}"
    assert r1 == r2 == r3 == TEST_RATE
