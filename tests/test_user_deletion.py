"""
Task 3.1 — тесты удаления аккаунта (ADR-010).

Блок 7: regression-тесты существующего поведения
Блоки 1-3: новые тесты (пароль, rate limit, audit log)
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_user_deletion.db")
os.environ.setdefault("SECRET_KEY", "test-deletion-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

import json
from datetime import datetime, timezone
import pytest
import json
from datetime import datetime, timezone
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete
from unittest.mock import patch, AsyncMock

from app.main import app
from app.database import get_db, Base
from app.models.user import User, UserRole, UserPlan
from app.models.load import Load, LoadStatus, TruckType
from app.models.response import Response, ResponseStatus
from app.models.deal import Deal, DealStatus
from app.models.status_change import StatusChange
from app.routers.auth import create_token
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

TEST_DB = "sqlite+aiosqlite:///./test_user_deletion.db"
engine_test = create_async_engine(TEST_DB, connect_args={"check_same_thread": False})
AsyncSessionTest = sessionmaker(engine_test, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with AsyncSessionTest() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db
transport = ASGITransport(app=app)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionTest() as db:
        await db.execute(delete(StatusChange))
        await db.execute(delete(Deal))
        await db.execute(delete(Response))
        await db.execute(delete(Load))
        await db.execute(delete(User))
        await db.commit()
    # Сбрасываем rate limit между тестами
    from app.services.rate_limit import _attempts
    _attempts.clear()
    yield


async def _make_user(email="test@caucashub.ge", password="TestPass99!", role="carrier", plan="free") -> tuple[int, str]:
    """Создаём пользователя и возвращаем (user_id, token)."""
    async with AsyncSessionTest() as db:
        user = User(
            email=email,
            phone=f"+99555{abs(hash(email)) % 9000000 + 1000000}",
            hashed_password=pwd_context.hash(password),
            company_name=f"Co {email[:5]}",
            role=UserRole.carrier,
            plan=UserPlan(plan),
            is_active=True,
            is_deleted=False,
            inn="123456789",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_token(user.id)
        return user.id, token


def auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── БЛОК 7: REGRESSION TESTS ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_blocks_when_active_deals():
    """Активные deals блокируют удаление → HTTP 400."""
    user_id, token = await _make_user("shipper@del.ge")
    async with AsyncSessionTest() as db:
        load = Load(user_id=user_id, from_city="Tbilisi", to_city="Moscow",
                    weight_kg=10, cargo_desc="test", status=LoadStatus.active,
                    price_gel=100, truck_type=TruckType.tent, load_date=datetime.now(timezone.utc))
        db.add(load)
        await db.flush()
        deal = Deal(shipper_id=user_id, carrier_id=user_id, load_id=load.id,
                    status=DealStatus.confirmed, agreed_price=100, currency="GEL")
        db.add(deal)
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                           content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "TestPass99!"}))
    assert r.status_code == 400
    assert "active_deal_ids" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_cancels_active_loads():
    """Активные грузы переходят в canceled при удалении."""
    user_id, token = await _make_user("loader@del.ge")
    async with AsyncSessionTest() as db:
        load = Load(user_id=user_id, from_city="Tbilisi", to_city="Moscow",
                    weight_kg=5, cargo_desc="stuff", status=LoadStatus.active,
                    price_gel=50, truck_type=TruckType.tent, load_date=datetime.now(timezone.utc))
        db.add(load)
        await db.commit()
        load_id = load.id

    with patch("app.routers.users._send_deletion_email", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                               content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "TestPass99!"}))
    assert r.status_code == 200
    assert r.json()["loads_canceled"] == 1

    async with AsyncSessionTest() as db:
        load = await db.get(Load, load_id)
        assert load.status == LoadStatus.canceled


@pytest.mark.asyncio
async def test_delete_withdraws_pending_responses():
    """Pending отклики переходят в withdrawn."""
    carrier_id, token = await _make_user("carrier@del.ge")
    shipper_id, _ = await _make_user("shipper2@del.ge")
    async with AsyncSessionTest() as db:
        load = Load(user_id=shipper_id, from_city="Tbilisi", to_city="Moscow",
                    weight_kg=10, cargo_desc="x", status=LoadStatus.active,
                    price_gel=100, truck_type=TruckType.tent, load_date=datetime.now(timezone.utc))
        db.add(load)
        await db.flush()
        resp = Response(user_id=carrier_id, load_id=load.id,
                        status=ResponseStatus.pending, price_gel=100)
        db.add(resp)
        await db.commit()
        resp_id = resp.id

    with patch("app.routers.users._send_deletion_email", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                               content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "TestPass99!"}))
    assert r.status_code == 200

    async with AsyncSessionTest() as db:
        resp = await db.get(Response, resp_id)
        assert resp.status == ResponseStatus.withdrawn


@pytest.mark.asyncio
async def test_delete_anonymizes_all_9_fields():
    """Проверяем каждое из 9 анонимизируемых полей."""
    user_id, token = await _make_user("anon@del.ge")
    async with AsyncSessionTest() as db:
        user = await db.get(User, user_id)
        user.telegram_id = "12345"
        user.full_name = "Real Name"
        await db.commit()

    with patch("app.routers.users._send_deletion_email", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                               content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "TestPass99!"}))
    assert r.status_code == 200

    async with AsyncSessionTest() as db:
        user = await db.get(User, user_id)
        assert "deleted" in user.email
        assert user.phone is None
        assert "Удалённый" in user.company_name
        assert user.full_name is None
        assert user.telegram_id is None
        assert user.hashed_password == "<deleted>"
        assert user.is_active is False
        assert user.is_deleted is True
        assert user.deleted_at is not None


@pytest.mark.asyncio
async def test_delete_preserves_inn():
    """ИНН сохраняется после удаления (налоговое хранение 6 лет)."""
    user_id, token = await _make_user("inn@del.ge")
    with patch("app.routers.users._send_deletion_email", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                               content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "TestPass99!"}))
    assert r.status_code == 200
    async with AsyncSessionTest() as db:
        user = await db.get(User, user_id)
        assert user.inn == "123456789"


@pytest.mark.asyncio
async def test_delete_writes_audit_log():
    """После успешного удаления есть запись в audit_log."""
    user_id, token = await _make_user("audit@del.ge")
    with patch("app.routers.users._send_deletion_email", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                               content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "TestPass99!"}))
    assert r.status_code == 200
    async with AsyncSessionTest() as db:
        res = await db.execute(
            select(StatusChange).where(StatusChange.entity_id == user_id)
        )
        entries = res.scalars().all()
        assert any(e.to_status == "deleted" for e in entries)


# ── БЛОК 1: ПАРОЛЬ ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_requires_password():
    """Запрос без current_password → 422 (Pydantic validation)."""
    _, token = await _make_user("nopwd@del.ge")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                           content=json.dumps({"confirmation": "УДАЛИТЬ"}))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_rejects_wrong_password():
    """Правильный confirmation + неверный пароль → 400, аккаунт не удалён."""
    user_id, token = await _make_user("wrongpwd@del.ge")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                           content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "WrongPass!"}))
    assert r.status_code == 400
    assert "пароль" in r.json()["detail"].lower()
    # Аккаунт не удалён
    async with AsyncSessionTest() as db:
        user = await db.get(User, user_id)
        assert user.is_deleted is False


@pytest.mark.asyncio
async def test_delete_accepts_correct_password():
    """Правильный confirmation + правильный пароль → 200."""
    _, token = await _make_user("correct@del.ge")
    with patch("app.routers.users._send_deletion_email", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                               content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "TestPass99!"}))
    assert r.status_code == 200
    assert r.json()["deleted"] is True


# ── БЛОК 2: RATE LIMIT ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_rate_limit_3_per_hour():
    """3 неудачные попытки → 4-я возвращает 429."""
    user_id, token = await _make_user("ratelimit@del.ge")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for _ in range(3):
            await c.request("DELETE", "/api/users/me", headers=auth(token),
                          content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "WrongPass!"}))
        r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                          content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "WrongPass!"}))
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_delete_rate_limit_per_user():
    """Rate limit отдельный для каждого user_id."""
    uid1, tok1 = await _make_user("rl_user1@del.ge")
    uid2, tok2 = await _make_user("rl_user2@del.ge")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Исчерпываем лимит для user1
        for _ in range(3):
            await c.request("DELETE", "/api/users/me", headers=auth(tok1),
                          content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "WrongPass!"}))
        # user1 — 429
        r1 = await c.request("DELETE", "/api/users/me", headers=auth(tok1),
                           content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "WrongPass!"}))
        # user2 — ещё не превысил
        r2 = await c.request("DELETE", "/api/users/me", headers=auth(tok2),
                           content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "WrongPass!"}))
    assert r1.status_code == 429
    assert r2.status_code != 429


# ── БЛОК 3: AUDIT LOG НЕУДАЧНЫХ ПОПЫТОК ─────────────────────────────────────

@pytest.mark.asyncio
async def test_failed_deletion_logged_wrong_password():
    """Неверный пароль → запись в audit_log с reason='wrong_password'."""
    user_id, token = await _make_user("auditpwd@del.ge")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.request("DELETE", "/api/users/me", headers=auth(token),
                      content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "WrongPass!"}))
    async with AsyncSessionTest() as db:
        res = await db.execute(
            select(StatusChange).where(
                StatusChange.entity_id == user_id,
                StatusChange.to_status == "wrong_password"
            )
        )
        assert res.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_failed_deletion_logged_wrong_confirmation():
    """Неверное слово подтверждения → запись в audit_log."""
    user_id, token = await _make_user("auditconf@del.ge")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.request("DELETE", "/api/users/me", headers=auth(token),
                      content=json.dumps({"confirmation": "удалить", "current_password": "TestPass99!"}))
    async with AsyncSessionTest() as db:
        res = await db.execute(
            select(StatusChange).where(
                StatusChange.entity_id == user_id,
                StatusChange.to_status == "wrong_confirmation"
            )
        )
        assert res.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_failed_deletion_logged_rate_limit():
    """После rate limit → запись в audit_log с reason='rate_limit'."""
    user_id, token = await _make_user("auditrl@del.ge")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for _ in range(3):
            await c.request("DELETE", "/api/users/me", headers=auth(token),
                          content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "WrongPass!"}))
        await c.request("DELETE", "/api/users/me", headers=auth(token),
                      content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "WrongPass!"}))
    async with AsyncSessionTest() as db:
        res = await db.execute(
            select(StatusChange).where(
                StatusChange.entity_id == user_id,
                StatusChange.to_status == "rate_limit"
            )
        )
        assert res.scalar_one_or_none() is not None


# ── БЛОК 4: PLAN RESET ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_resets_plan_to_free():
    """Пользователь с plan=pro → после удаления plan=free."""
    user_id, token = await _make_user("pro@del.ge", plan="pro")
    with patch("app.routers.users._send_deletion_email", new_callable=AsyncMock):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.request("DELETE", "/api/users/me", headers=auth(token),
                               content=json.dumps({"confirmation": "УДАЛИТЬ", "current_password": "TestPass99!"}))
    assert r.status_code == 200
    async with AsyncSessionTest() as db:
        user = await db.get(User, user_id)
        assert user.plan == UserPlan.free
