"""
Regression tests for require_user fix (PR #11).

All functions in tg_bot.py and users.py previously used
'user_id: int = Depends(require_user)' but require_user returns
a User object — causing 500 on every request.

These are sanity tests: verify endpoints return 200 (not 500).
No business logic validation.
"""
import pytest
import pytest_asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_require_user.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-require-user")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
import hashlib

from app.main import app
from app.database import get_db, Base

TEST_DB = "sqlite+aiosqlite:///./test_require_user.db"
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


async def _register(client, suffix: str, role: str = "carrier") -> str:
    phone_num = int(hashlib.md5(f"rru_{suffix}".encode()).hexdigest()[:7], 16) % 9000000 + 1000000
    r = await client.post("/api/auth/register", json={
        "email":        f"rru_{suffix}@test.ge",
        "password":     "TestPass99!",
        "company_name": f"RRUCo{suffix}",
        "phone":        f"+9955{phone_num}",
        "role":         role,
    })
    assert r.status_code == 200, f"Register failed: {r.text}"
    return r.json()["token"]


# ── tg_bot.py ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tg_generate_link_returns_200(client):
    """POST /api/tg/generate-link → 200 (not 500).
    Regression: was 500 due to require_user returning User object."""
    token = await _register(client, "tg_link")
    r = await client.post(
        "/api/tg/generate-link",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert "link" in r.json()
    assert "token" in r.json()


@pytest.mark.asyncio
async def test_tg_status_returns_200(client):
    """GET /api/tg/status → 200 (not 500).
    Regression: was 500 due to require_user returning User object."""
    token = await _register(client, "tg_status")
    r = await client.get(
        "/api/tg/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert "linked" in r.json()


@pytest.mark.asyncio
async def test_tg_unlink_returns_200(client):
    """DELETE /api/tg/unlink → 200 (not 500).
    Regression: was 500 due to require_user returning User object."""
    token = await _register(client, "tg_unlink")
    r = await client.delete(
        "/api/tg/unlink",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json().get("ok") is True


# ── users.py ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_users_update_me_returns_200(client):
    """PUT /api/users/me → 200 (not 500).
    Regression: was 500 due to require_user returning User object."""
    token = await _register(client, "update_me")
    r = await client.put(
        "/api/users/me",
        json={"company_name": "Updated Company Name"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_users_set_my_plan_requires_secret(client):
    """POST /api/users/me/plan → 403 with wrong secret (not 500).
    Regression: was 500 due to require_user returning User object.
    We verify it reaches auth logic (403), not crashes (500)."""
    token = await _register(client, "set_plan")
    r = await client.post(
        "/api/users/me/plan",
        json={"plan": "pro", "secret": "wrong-secret"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
