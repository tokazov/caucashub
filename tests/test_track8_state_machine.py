"""
Тесты Трека 8: state machine, race condition, withdrawn, audit log.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_sm.db")
os.environ.setdefault("SECRET_KEY", "test-sm")
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
from app.models.deal import Deal
from app.models.status_change import StatusChange
from app.services.state_machine import validate_transition
from passlib.context import CryptContext
from sqlalchemy import select, delete
import datetime
from unittest.mock import patch, AsyncMock
from app.services import exchange_rate as er_module

pwd = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.database import AsyncSessionLocal
    from app.services.cities_seed import seed_cities
    async with AsyncSessionLocal() as db:
        await db.execute(delete(StatusChange))
        await db.execute(delete(Deal))
        await db.execute(delete(Response))
        await db.execute(delete(Load))
        await db.execute(delete(User))
        await db.commit()
        await seed_cities(db)

    er_module.invalidate_cache()
    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _register(client, email, phone, role="carrier"):
    r = await client.post("/api/auth/register", json={
        "email": email, "password": "pass123",
        "company_name": f"Test {role}", "phone": phone, "role": role,
    })
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _create_load(client, token) -> int:
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=2.73):
        er_module.invalidate_cache()
        r = await client.post("/api/loads/", json={
            "from_city": "Тбилиси", "to_city": "Батуми",
            "weight_kg": 1000, "truck_type": "tent", "price_gel": 500.0,
        }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── TEST 1: State machine — валидные переходы ─────────────────────────────────

def test_valid_transitions():
    """Проверка допустимых переходов через state_machine."""
    assert validate_transition("deal", "confirmed", "loading", raise_on_invalid=False)
    assert validate_transition("deal", "loading", "in_transit", raise_on_invalid=False)
    assert validate_transition("response", "pending", "accepted", raise_on_invalid=False)
    assert validate_transition("response", "pending", "withdrawn", raise_on_invalid=False)
    assert validate_transition("load", "active", "taken", raise_on_invalid=False)


def test_invalid_transitions_return_false():
    """Недопустимые переходы возвращают False при raise_on_invalid=False."""
    assert not validate_transition("deal", "completed", "active", raise_on_invalid=False)
    assert not validate_transition("deal", "canceled", "confirmed", raise_on_invalid=False)
    assert not validate_transition("response", "accepted", "pending", raise_on_invalid=False)
    assert not validate_transition("load", "canceled", "active", raise_on_invalid=False)


def test_invalid_transition_raises_http_400():
    """Недопустимый переход кидает HTTPException 400."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        validate_transition("deal", "completed", "active")
    assert exc_info.value.status_code == 400


# ── TEST 2: Withdrawn — перевозчик отзывает отклик ──────────────────────────

@pytest.mark.asyncio
async def test_carrier_can_withdraw_pending_response():
    """Перевозчик может отозвать свой pending-отклик."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=2.73):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token = await _register(client, "shipper8@test.ge", "+99591000001", "shipper")
            carrier_token = await _register(client, "carrier8@test.ge", "+99591000002", "carrier")
            load_id = await _create_load(client, shipper_token)

            # Откликаемся
            r = await client.post(f"/api/responses/load/{load_id}",
                                  json={"price": 450.0},
                                  headers={"Authorization": f"Bearer {carrier_token}"})
            assert r.status_code == 200
            resp_id = r.json()["response_id"]

            # Отзываем
            r2 = await client.delete(f"/api/responses/cancel/{resp_id}",
                                     headers={"Authorization": f"Bearer {carrier_token}"})
            assert r2.status_code == 200
            assert r2.json()["status"] == "withdrawn"

    # Проверяем в БД — статус withdrawn, запись не удалена
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Response).where(Response.id == resp_id))
        resp = result.scalar_one()
        assert str(resp.status) in ("withdrawn", "ResponseStatus.withdrawn")


@pytest.mark.asyncio
async def test_cannot_withdraw_accepted_response():
    """Нельзя отозвать принятый отклик."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=2.73):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token = await _register(client, "shipper8b@test.ge", "+99591000003", "shipper")
            carrier_token = await _register(client, "carrier8b@test.ge", "+99591000004", "carrier")
            load_id = await _create_load(client, shipper_token)

            r = await client.post(f"/api/responses/load/{load_id}",
                                  json={"price": 450.0},
                                  headers={"Authorization": f"Bearer {carrier_token}"})
            resp_id = r.json()["response_id"]

            # Принимаем отклик
            await client.post(f"/api/responses/accept/{resp_id}",
                               headers={"Authorization": f"Bearer {shipper_token}"})

            # Пробуем отозвать — должна быть ошибка
            r2 = await client.delete(f"/api/responses/cancel/{resp_id}",
                                     headers={"Authorization": f"Bearer {carrier_token}"})
            assert r2.status_code == 400


# ── TEST 3: Race condition — двойной accept ───────────────────────────────────

@pytest.mark.asyncio
async def test_double_accept_rejected():
    """
    Два параллельных accept на один отклик — второй должен получить 409.
    Имитируем последовательно (SQLite не поддерживает FOR UPDATE).
    """
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=2.73):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token = await _register(client, "shipper8c@test.ge", "+99591000005", "shipper")
            carrier_token = await _register(client, "carrier8c@test.ge", "+99591000006", "carrier")
            load_id = await _create_load(client, shipper_token)

            r = await client.post(f"/api/responses/load/{load_id}",
                                  json={"price": 400.0},
                                  headers={"Authorization": f"Bearer {carrier_token}"})
            resp_id = r.json()["response_id"]

            # Первый accept — должен пройти
            r1 = await client.post(f"/api/responses/accept/{resp_id}",
                                   headers={"Authorization": f"Bearer {shipper_token}"})
            assert r1.status_code == 200

            # Второй accept — должен получить 409 (deal уже создана) или 400 (статус не pending)
            r2 = await client.post(f"/api/responses/accept/{resp_id}",
                                   headers={"Authorization": f"Bearer {shipper_token}"})
            assert r2.status_code in (400, 409), f"Expected 400/409, got {r2.status_code}: {r2.text}"


# ── TEST 4: Audit log записывается ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_log_written_on_accept():
    """При принятии отклика в status_changes появляется запись."""
    with patch.object(er_module, '_fetch_rate_from_nbg', new_callable=AsyncMock, return_value=2.73):
        er_module.invalidate_cache()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            shipper_token = await _register(client, "shipper8d@test.ge", "+99591000007", "shipper")
            carrier_token = await _register(client, "carrier8d@test.ge", "+99591000008", "carrier")
            load_id = await _create_load(client, shipper_token)

            r = await client.post(f"/api/responses/load/{load_id}",
                                  json={"price": 450.0},
                                  headers={"Authorization": f"Bearer {carrier_token}"})
            resp_id = r.json()["response_id"]

            await client.post(f"/api/responses/accept/{resp_id}",
                               headers={"Authorization": f"Bearer {shipper_token}"})

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(StatusChange).where(
                StatusChange.entity_type == "response",
                StatusChange.entity_id == resp_id,
                StatusChange.to_status == "accepted",
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None, "Audit log entry missing"
        assert log.from_status == "pending"
        assert log.to_status == "accepted"
