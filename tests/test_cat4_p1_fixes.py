"""
Тесты P1-фиксов Категории 4.

Тест 1 (Фикс 1): weight_kg=0 и price=0 → 422
Тест 2 (Фикс 2): date_end < date_start → 422
Тест 3 (Фикс 3): смена телефона — двухшаговый процесс (request → confirm)
Тест 4 (Фикс 4): слабый/короткий пароль → 422 при регистрации
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_cat4_p1.db")
os.environ.setdefault("SECRET_KEY", "test-cat4-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

import pytest
import pytest_asyncio
import datetime
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete as sql_delete

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User, UserRole, UserPlan
from app.models.load import Load, LoadStatus
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
transport = ASGITransport(app=app)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Создаём таблицы + seed пользователя перед каждым тестом."""
    from app.models.response import Response
    from app.models.deal import Deal
    from app.models.status_change import StatusChange

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await db.execute(sql_delete(StatusChange))
        await db.execute(sql_delete(Deal))
        await db.execute(sql_delete(Response))
        await db.execute(sql_delete(Load))
        await db.execute(sql_delete(User))
        await db.commit()

    # Seed: один перевозчик
    async with AsyncSessionLocal() as db:
        user = User(
            email="shipper_cat4@test.ge",
            hashed_password=pwd_context.hash("StrongPass99!"),
            company_name="Test Co",
            phone="+995500000001",
            role=UserRole.shipper,
            plan=UserPlan.standard,
            is_active=True,
        )
        db.add(user)
        await db.commit()

    yield


async def _get_token() -> str:
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/login", json={"email": "shipper_cat4@test.ge", "password": "StrongPass99!"})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["token"]


# ── Тест 1: weight=0 и price=0 → 422 ──────────────────────────────────────
@pytest.mark.asyncio
async def test_weight_zero_returns_422():
    """POST /api/loads/ с weight_kg=0 → 422."""
    token = await _get_token()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/loads/",
            json={"from_city": "Тбилиси", "to_city": "Батуми",
                  "weight_kg": 0, "truck_type": "tent", "price_gel": 500},
            headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 422, f"Ожидали 422, получили {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_price_zero_returns_422():
    """POST /api/loads/ с price_gel=0 и price_usd=0 → 422."""
    token = await _get_token()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/loads/",
            json={"from_city": "Тбилиси", "to_city": "Батуми",
                  "weight_kg": 1000, "truck_type": "tent", "price_gel": 0},
            headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 422, f"Ожидали 422, получили {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_weight_over_limit_returns_422():
    """POST /api/loads/ с weight_kg=99999 → 422."""
    token = await _get_token()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/loads/",
            json={"from_city": "Тбилиси", "to_city": "Батуми",
                  "weight_kg": 99999, "truck_type": "tent", "price_gel": 500},
            headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 422, f"Ожидали 422, получили {r.status_code}: {r.text}"


# ── Тест 2: date_end < date_start → 422 ──────────────────────────────────────
@pytest.mark.asyncio
async def test_date_end_before_start_returns_422():
    """date_end раньше date_start → 422."""
    token = await _get_token()
    tomorrow = (datetime.date.today() + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    yesterday = datetime.date.today().strftime("%d.%m.%y")  # дата раньше tomorrow

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/loads/",
            json={
                "from_city": "Тбилиси", "to_city": "Батуми",
                "weight_kg": 500, "truck_type": "tent", "price_gel": 400,
                "load_date": tomorrow + "T00:00:00",
                "load_date_end": yesterday,  # раньше load_date
            },
            headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 422, f"Ожидали 422, получили {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_date_end_valid_passes():
    """date_end >= date_start → 200."""
    token = await _get_token()
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    next_week = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d.%m.%y")

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/loads/",
            json={
                "from_city": "Тбилиси", "to_city": "Батуми",
                "weight_kg": 500, "truck_type": "tent", "price_gel": 400,
                "load_date": tomorrow + "T00:00:00",
                "load_date_end": next_week,
            },
            headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 200, f"Ожидали 200, получили {r.status_code}: {r.text}"


# ── Тест 3: Смена телефона — двухшаговый процесс ─────────────────────────────
@pytest.mark.asyncio
async def test_phone_change_requires_confirmation():
    """Прямое изменение телефона через PUT /api/users/me НЕ принимает phone."""
    token = await _get_token()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.put(
            "/api/users/me",
            json={"company_name": "Updated Co"},  # только company_name, без phone
            headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 200, f"company_name update failed: {r.text}"
    # Убеждаемся что phone не изменился через PUT
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        me = await c.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["phone"] == "+995500000001", "Телефон не должен меняться через PUT"


@pytest.mark.asyncio
async def test_phone_change_request_returns_message():
    """POST /api/users/me/request-phone-change возвращает message (не ошибку)."""
    token = await _get_token()
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/users/me/request-phone-change",
            json={"new_phone": "+995599000002"},
            headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 200, f"Ожидали 200, получили {r.status_code}: {r.text}"
    assert "message" in r.json()


@pytest.mark.asyncio
async def test_phone_change_wrong_code_returns_400():
    """Неверный код при подтверждении → 400."""
    token = await _get_token()
    # Шаг 1 — запрос
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post(
            "/api/users/me/request-phone-change",
            json={"new_phone": "+995599000003"},
            headers={"Authorization": f"Bearer {token}"}
        )
    # Шаг 2 — неверный код
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/users/me/confirm-phone-change",
            json={"code": "000000"},
            headers={"Authorization": f"Bearer {token}"}
        )
    assert r.status_code == 400, f"Ожидали 400 при неверном коде, получили {r.status_code}"


# ── Тест 4: Слабый/короткий пароль → 422 ─────────────────────────────────────
@pytest.mark.asyncio
async def test_short_password_rejected_on_register():
    """Пароль < 8 символов при регистрации → 422."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/register", json={
            "email": "weakpass@test.ge",
            "password": "abc",
            "company_name": "Test",
            "phone": "+995500000099",
            "role": "carrier"
        })
    assert r.status_code == 422, f"Ожидали 422, получили {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_weak_password_rejected_on_register():
    """Пароль из blacklist при регистрации → 422."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/register", json={
            "email": "weakpass2@test.ge",
            "password": "password",
            "company_name": "Test",
            "phone": "+995500000098",
            "role": "carrier"
        })
    assert r.status_code == 422, f"Ожидали 422, получили {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_strong_password_accepted_on_register():
    """Сильный пароль при регистрации → 200."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/register", json={
            "email": "strongpass@test.ge",
            "password": "MyStr0ngP@ss99",
            "company_name": "Strong Co",
            "phone": "+995500000097",
            "role": "carrier"
        })
    assert r.status_code == 200, f"Ожидали 200, получили {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_exact_8_chars_accepted():
    """Пароль ровно 8 символов (не в blacklist) → 200."""
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/auth/register", json={
            "email": "eightchar@test.ge",
            "password": "Abc12345",
            "company_name": "Eight Co",
            "phone": "+995500000096",
            "role": "shipper"
        })
    assert r.status_code == 200, f"Ожидали 200, получили {r.status_code}: {r.text}"
