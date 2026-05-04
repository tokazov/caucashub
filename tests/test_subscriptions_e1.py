"""
Тесты Этап 1 — Подписки CRUD (ADR-014).
Покрывает: create, list, patch (activate/deactivate), delete, limit, duplicate.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import get_db, Base

TEST_DB = "sqlite+aiosqlite:///./test_subs_e1.db"
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


async def _register(client, suffix: str) -> str:
    r = await client.post("/api/auth/register", json={
        "email":        f"sub_test_{suffix}@test.ge",
        "password":     "TestPass99!",
        "company_name": f"SubTestCo{suffix}",
        "phone":        f"+99555{suffix.zfill(7)[:7]}",
        "role":         "carrier",
    })
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.mark.asyncio
async def test_create_subscription(client):
    token = await _register(client, "001")
    r = await client.post("/api/subscriptions/", json={
        "from_city": "Тбилиси",
        "to_city":   "Батуми",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["subscription"]["from_city"] == "тбилиси"  # нормализован в lowercase
    assert d["subscription"]["to_city"]   == "батуми"
    assert d["subscription"]["is_active"] is True
    assert d["subscription"]["notify_tg"] is True


@pytest.mark.asyncio
async def test_list_subscriptions(client):
    token = await _register(client, "002")
    await client.post("/api/subscriptions/", json={"from_city": "Гори", "to_city": "Рустави"},
                      headers={"Authorization": f"Bearer {token}"})
    await client.post("/api/subscriptions/", json={"from_city": "Поти", "to_city": "Кутаиси"},
                      headers={"Authorization": f"Bearer {token}"})
    r = await client.get("/api/subscriptions/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert len(d["subscriptions"]) == 2


@pytest.mark.asyncio
async def test_duplicate_subscription_rejected(client):
    token = await _register(client, "003")
    await client.post("/api/subscriptions/", json={"from_city": "Зугдиди", "to_city": "Тбилиси"},
                      headers={"Authorization": f"Bearer {token}"})
    r2 = await client.post("/api/subscriptions/", json={"from_city": "Зугдиди", "to_city": "Тбилиси"},
                           headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_patch_subscription(client):
    token = await _register(client, "004")
    r_create = await client.post("/api/subscriptions/", json={
        "from_city": "Гори", "to_city": "Батуми",
        "notify_tg": True, "notify_email": False,
    }, headers={"Authorization": f"Bearer {token}"})
    sub_id = r_create.json()["subscription"]["id"]

    r_patch = await client.patch(f"/api/subscriptions/{sub_id}", json={
        "is_active": False,
        "notify_email": True,
    }, headers={"Authorization": f"Bearer {token}"})
    assert r_patch.status_code == 200
    upd = r_patch.json()["subscription"]
    assert upd["is_active"]    is False
    assert upd["notify_email"] is True
    assert upd["notify_tg"]    is True  # не менялся


@pytest.mark.asyncio
async def test_delete_subscription(client):
    token = await _register(client, "005")
    r_create = await client.post("/api/subscriptions/", json={
        "from_city": "Ахалкалаки", "to_city": "Тбилиси",
    }, headers={"Authorization": f"Bearer {token}"})
    sub_id = r_create.json()["subscription"]["id"]

    r_del = await client.delete(f"/api/subscriptions/{sub_id}",
                                headers={"Authorization": f"Bearer {token}"})
    assert r_del.status_code == 200
    assert r_del.json()["ok"] is True

    # Проверяем что удалена
    r_list = await client.get("/api/subscriptions/", headers={"Authorization": f"Bearer {token}"})
    assert r_list.json()["total"] == 0


@pytest.mark.asyncio
async def test_cannot_delete_other_users_subscription(client):
    token1 = await _register(client, "006")
    token2 = await _register(client, "007")
    r_create = await client.post("/api/subscriptions/", json={
        "from_city": "Поти", "to_city": "Гори",
    }, headers={"Authorization": f"Bearer {token1}"})
    sub_id = r_create.json()["subscription"]["id"]

    r_del = await client.delete(f"/api/subscriptions/{sub_id}",
                                headers={"Authorization": f"Bearer {token2}"})
    assert r_del.status_code == 404  # чужая подписка — 404


@pytest.mark.asyncio
async def test_subscription_limit(client):
    """Safety-cap: не более 50 подписок на пользователя."""
    from app.routers.subscriptions import SUBSCRIPTION_LIMIT
    token = await _register(client, "008")

    # Создаём SUBSCRIPTION_LIMIT подписок
    for i in range(SUBSCRIPTION_LIMIT):
        r = await client.post("/api/subscriptions/", json={
            "from_city": f"city_{i}",
            "to_city":   f"dest_{i}",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201, f"Failed at {i}: {r.text}"

    # 51-я должна вернуть 400
    r_over = await client.post("/api/subscriptions/", json={
        "from_city": "overflow", "to_city": "limit",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r_over.status_code == 400
    assert "лимит" in r_over.json()["detail"].lower()


@pytest.mark.asyncio
async def test_unauthenticated_blocked(client):
    r = await client.get("/api/subscriptions/")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_city_normalization(client):
    """from_city / to_city нормализуются в lowercase."""
    token = await _register(client, "009")
    r = await client.post("/api/subscriptions/", json={
        "from_city": "  ТБИЛИСИ  ",
        "to_city":   "БАТУМИ",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201
    sub = r.json()["subscription"]
    assert sub["from_city"] == "тбилиси"
    assert sub["to_city"]   == "батуми"
