"""
Тесты пагинации — Решение 4.
GET /api/responses/my — limit/offset
GET /api/deals/my — limit/offset
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import get_db, Base

TEST_DB = "sqlite+aiosqlite:///./test_pagination.db"
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


async def _register(client, suffix: str, role: str = "carrier") -> tuple[str, int]:
    r = await client.post("/api/auth/register", json={
        "email":        f"pag_test_{suffix}@test.ge",
        "password":     "TestPass99!",
        "company_name": f"PagTest{suffix}",
        "phone":        f"+9955{suffix.zfill(8)[:8]}",
        "role":         role,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    return d["token"], d["user_id"]


@pytest.mark.asyncio
async def test_responses_my_pagination_defaults(client):
    """GET /api/responses/my возвращает total, limit, offset."""
    token, _ = await _register(client, "r001")
    r = await client.get("/api/responses/my", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    d = r.json()
    assert "total"   in d
    assert "limit"   in d
    assert "offset"  in d
    assert d["limit"]  == 50
    assert d["offset"] == 0


@pytest.mark.asyncio
async def test_responses_my_pagination_params(client):
    """Кастомные limit/offset принимаются."""
    token, _ = await _register(client, "r002")
    r = await client.get("/api/responses/my?limit=10&offset=0",
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    d = r.json()
    assert d["limit"]  == 10
    assert d["offset"] == 0


@pytest.mark.asyncio
async def test_responses_my_limit_max(client):
    """limit > 200 отклоняется."""
    token, _ = await _register(client, "r003")
    r = await client.get("/api/responses/my?limit=999",
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_deals_my_pagination_defaults(client):
    """GET /api/deals/my возвращает total, limit, offset."""
    token, _ = await _register(client, "d001", role="shipper")
    r = await client.get("/api/deals/my", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    d = r.json()
    assert "total"  in d
    assert "limit"  in d
    assert "offset" in d
    assert d["limit"]  == 50
    assert d["offset"] == 0


@pytest.mark.asyncio
async def test_deals_my_pagination_params(client):
    """Кастомные limit/offset принимаются."""
    token, _ = await _register(client, "d002", role="shipper")
    r = await client.get("/api/deals/my?limit=5&offset=10",
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    d = r.json()
    assert d["limit"]  == 5
    assert d["offset"] == 10


@pytest.mark.asyncio
async def test_deals_my_limit_max(client):
    """limit > 200 отклоняется."""
    token, _ = await _register(client, "d003", role="shipper")
    r = await client.get("/api/deals/my?limit=500",
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_trucks_has_offset(client):
    """GET /api/trucks/ принимает offset."""
    r = await client.get("/api/trucks/?limit=10&offset=0")
    assert r.status_code == 200
