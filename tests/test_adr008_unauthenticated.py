"""
Тест ADR-008: незалогиненный пользователь → кнопка «Откликнуться» недоступна.
Проверяем бэкенд-поведение (не UI): незалогиненный получает 401, не фейковый успех.

Запуск: pytest tests/test_adr008_unauthenticated.py -v
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_adr008.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User, UserRole, UserPlan
from app.models.load import Load, LoadStatus, TruckType, LoadScope
from passlib.context import CryptContext
from sqlalchemy import delete
import datetime

pwd = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Load))
        await db.execute(delete(User))
        await db.commit()

        user = User(
            email="owner@test.ge",
            hashed_password=pwd.hash("pass123"),
            company_name="Owner LLC",
            phone="+99599111111",
            role=UserRole.shipper,
            plan=UserPlan.pro,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        load = Load(
            user_id=user.id,
            from_city="Тбилиси",
            to_city="Кутаиси",
            weight_kg=3000,
            truck_type=TruckType.bort,
            price_gel=500,
            load_date=datetime.datetime.utcnow(),
            scope=LoadScope.local,
            status=LoadStatus.active,
        )
        db.add(load)
        await db.commit()

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _get_load_id() -> int:
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Load).where(Load.from_city == "Тбилиси"))
        return result.scalar_one().id


# ── TEST 1: Незалогиненный → 401 (не "Заявка отправлена") ────────────────────

@pytest.mark.asyncio
async def test_unauthenticated_respond_returns_401_not_fake_success():
    """
    ADR-008: POST /api/responses/load/{id} без токена → 401.
    НЕ должен возвращать {"ok": true} (фейковый успех удалён).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        load_id = await _get_load_id()

        r = await client.post(
            f"/api/responses/load/{load_id}",
            json={"price": 400.0}
            # нет Authorization header
        )
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"
        # Убеждаемся что это не фейковый успех
        body = r.json()
        assert body.get("ok") is not True, "Fake success response should not be returned"


# ── TEST 2: Неверный токен → 401 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_token_returns_401():
    """Неверный/просроченный токен → 401, не 500 и не фейковый успех."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        load_id = await _get_load_id()

        r = await client.post(
            f"/api/responses/load/{load_id}",
            json={"price": 400.0},
            headers={"Authorization": "Bearer this.is.invalid.jwt.token"}
        )
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"


# ── TEST 3: После логина — успешный отклик ───────────────────────────────────

@pytest.mark.asyncio
async def test_after_login_can_respond():
    """
    ADR-008: Пользователь логинится, получает токен → может откликнуться.
    Симулирует сценарий: «Войдите → вернулись на карточку → кнопка появилась → кликнули».
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Регистрируем нового пользователя (перевозчик)
        reg = await client.post("/api/auth/register", json={
            "email": "newcarrier@test.ge",
            "password": "pass456",
            "company_name": "New Carrier",
            "phone": "+99599222222",
            "role": "carrier",
        })
        assert reg.status_code == 200, f"Register failed: {reg.text}"
        token = reg.json()["token"]

        # Теперь откликаемся с токеном
        load_id = await _get_load_id()
        r = await client.post(
            f"/api/responses/load/{load_id}",
            json={"price": 450.0},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        assert r.json().get("ok") is True


# ── TEST 4: Публичный список грузов доступен без логина ──────────────────────

@pytest.mark.asyncio
async def test_public_loads_accessible_without_auth():
    """Лента грузов доступна всем (GET /api/loads/) — только отклики требуют логина."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/loads/")
        assert r.status_code == 200
        data = r.json()
        assert "loads" in data
        assert len(data["loads"]) >= 1
