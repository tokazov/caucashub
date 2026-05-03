"""
Интеграционные тесты: отклики на грузы.
Запуск: pytest tests/test_responses.py -v

Тест использует in-memory SQLite и тестовый клиент FastAPI.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os

# Устанавливаем тестовую конфигурацию ДО импорта app
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_caucashub.db")
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
from app.models.response import Response, ResponseStatus
from passlib.context import CryptContext
from sqlalchemy import select, delete

# Используем тот же алгоритм что и app/routers/auth.py
pwd = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Создаём таблицы, наполняем тестовыми данными, после — чистим."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Удаляем старые тестовые записи
        await db.execute(delete(Response))
        await db.execute(delete(Load))
        await db.execute(delete(User))
        await db.commit()

        # Создаём двух пользователей
        shipper = User(
            email="shipper@test.ge",
            hashed_password=pwd.hash("password123"),
            company_name="Test Shipper LLC",
            phone="+99599000001",
            role=UserRole.shipper,
            plan=UserPlan.pro,
            is_active=True,
        )
        carrier = User(
            email="carrier@test.ge",
            hashed_password=pwd.hash("password123"),
            company_name="Test Carrier",
            phone="+99599000002",
            role=UserRole.carrier,
            plan=UserPlan.pro,
            is_active=True,
        )
        db.add_all([shipper, carrier])
        await db.commit()
        await db.refresh(shipper)
        await db.refresh(carrier)

        # Груз от shipper
        load = Load(
            user_id=shipper.id,
            from_city="Тбилиси",
            to_city="Батуми",
            weight_kg=5000,
            truck_type=TruckType.tent,
            price_gel=800,
            load_date=__import__("datetime").datetime.utcnow(),
            scope=LoadScope.local,
            status=LoadStatus.active,
        )
        db.add(load)
        await db.commit()
        await db.refresh(load)

    yield

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _login(client: AsyncClient, email: str) -> str:
    """Логинимся и возвращаем токен."""
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["token"]


async def _get_load_id(db) -> int:
    result = await db.execute(select(Load).where(Load.from_city == "Тбилиси"))
    load = result.scalar_one()
    return load.id


# ── TEST 1: Создание отклика ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_carrier_can_respond_to_load():
    """Перевозчик успешно откликается на активный груз."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Логинимся как перевозчик
        token = await _login(client, "carrier@test.ge")

        # Получаем id груза
        async with AsyncSessionLocal() as db:
            load_id = await _get_load_id(db)

        # Откликаемся
        r = await client.post(
            f"/api/responses/load/{load_id}",
            json={"price": 750.0, "message": "Готов везти, свободен завтра"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("ok") is True
        assert "response_id" in data
        assert data.get("status") == "pending"


# ── TEST 2: Нельзя откликнуться на свой груз ─────────────────────────────────

@pytest.mark.asyncio
async def test_shipper_cannot_respond_to_own_load():
    """Грузовладелец не может откликнуться на свой собственный груз."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "shipper@test.ge")

        async with AsyncSessionLocal() as db:
            load_id = await _get_load_id(db)

        r = await client.post(
            f"/api/responses/load/{load_id}",
            json={"price": 900.0},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        assert "own load" in r.json().get("detail", "").lower()


# ── TEST 3: Без авторизации — 401 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_respond_without_auth_returns_401():
    """Отклик без токена → 401 Unauthorized."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with AsyncSessionLocal() as db:
            load_id = await _get_load_id(db)

        r = await client.post(
            f"/api/responses/load/{load_id}",
            json={"price": 700.0}
            # нет Authorization header
        )
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"


# ── TEST 4: Нельзя откликнуться дважды ───────────────────────────────────────

@pytest.mark.asyncio
async def test_carrier_cannot_respond_twice():
    """Один перевозчик не может подать два отклика на один груз."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "carrier@test.ge")

        async with AsyncSessionLocal() as db:
            load_id = await _get_load_id(db)

        # Первый отклик
        r1 = await client.post(
            f"/api/responses/load/{load_id}",
            json={"price": 750.0},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r1.status_code == 200

        # Второй отклик — должен отклониться
        r2 = await client.post(
            f"/api/responses/load/{load_id}",
            json={"price": 700.0},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r2.status_code == 400
        assert "already responded" in r2.json().get("detail", "").lower()


# ── TEST 5: Нельзя откликнуться на canceled груз ─────────────────────────────

@pytest.mark.asyncio
async def test_cannot_respond_to_canceled_load():
    """Нельзя откликнуться на груз со статусом canceled."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Сначала отменяем груз от имени shipper
        shipper_token = await _login(client, "shipper@test.ge")

        async with AsyncSessionLocal() as db:
            load_id = await _get_load_id(db)

        r_del = await client.delete(
            f"/api/loads/{load_id}",
            headers={"Authorization": f"Bearer {shipper_token}"}
        )
        assert r_del.status_code == 200

        # Теперь перевозчик пробует откликнуться
        carrier_token = await _login(client, "carrier@test.ge")
        r = await client.post(
            f"/api/responses/load/{load_id}",
            json={"price": 750.0},
            headers={"Authorization": f"Bearer {carrier_token}"}
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        assert "no longer available" in r.json().get("detail", "").lower()
