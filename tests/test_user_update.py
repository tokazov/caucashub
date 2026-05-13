"""
Tests for UpdateProfileRequest — inn validation (Task 12).

Pydantic validator: inn must be exactly 9 digits (Georgian tax ID).
None and empty string → accepted (no INN is valid).
"""
import pytest
import pytest_asyncio
import os
import hashlib

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_user_update.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-user-update")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import get_db, Base

TEST_DB = "sqlite+aiosqlite:///./test_user_update.db"
engine_test = create_async_engine(TEST_DB, connect_args={"check_same_thread": False})
AsyncSessionTest = sessionmaker(engine_test, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with AsyncSessionTest() as session:
        yield session

app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True, scope="module")
async def setup_db():
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(scope="module")
async def token(client):
    phone = int(hashlib.md5(b"inn_test_user").hexdigest()[:7], 16) % 9000000 + 1000000
    r = await client.post("/api/auth/register", json={
        "email": "inn_test_user@test.ge",
        "password": "TestPass99!",
        "company_name": "INN Test Co",
        "phone": f"+9955{phone}",
        "role": "shipper",
    })
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _patch(client, token, inn_value):
    return await client.put(
        "/api/users/me",
        json={"inn": inn_value},
        headers={"Authorization": f"Bearer {token}"},
    )


# ── Тесты ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inn_valid_9_digits(client, token):
    """ИНН из 9 цифр → 200."""
    r = await _patch(client, token, "123456789")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_inn_with_dashes_normalized(client, token):
    """ИНН с дефисами '123-45-6789' → 200, в профиле '123456789'."""
    r = await _patch(client, token, "123-45-6789")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    # Проверяем что сохранилось нормализованно
    me = await client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json().get("inn") == "123456789", f"Expected '123456789', got: {me.json().get('inn')}"


@pytest.mark.asyncio
async def test_inn_too_short_rejected(client, token):
    """ИНН '12345' (5 цифр) → 422."""
    r = await _patch(client, token, "12345")
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_inn_too_long_rejected(client, token):
    """ИНН '1234567890' (10 цифр) → 422."""
    r = await _patch(client, token, "1234567890")
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_inn_none_accepted(client, token):
    """inn: null → 200, ИНН обнуляется."""
    r = await _patch(client, token, None)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_inn_empty_string_treated_as_none(client, token):
    """inn: '' → 200, пустая строка = отсутствие ИНН."""
    r = await _patch(client, token, "")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
