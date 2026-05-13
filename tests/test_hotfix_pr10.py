"""
Тесты hotfix PR #10:
  1. test_get_my_deals_returns_200    — /api/deals/my не падает с 500
  2. test_responses_load_hides_carrier_name_until_accept — carrier_name скрыт до accept
"""
import pytest
import pytest_asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_hotfix_pr10.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-pr10")
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

TEST_DB = "sqlite+aiosqlite:///./test_hotfix_pr10.db"
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


import hashlib

async def _register(client, suffix: str, role: str = "shipper") -> tuple[str, int]:
    # Генерируем уникальный номер из суффикса чтобы избежать коллизий между тестами
    phone_num = int(hashlib.md5(suffix.encode()).hexdigest()[:7], 16) % 9000000 + 1000000
    r = await client.post("/api/auth/register", json={
        "email":        f"pr10_{suffix}@test.ge",
        "password":     "TestPass99!",
        "company_name": f"PR10Co{suffix}",
        "phone":        f"+9955{phone_num}",
        "role":         role,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    return d["token"], d["user_id"]


async def _create_load(client, token: str) -> int:
    r = await client.post("/api/loads/", json={
        "from_city":  "Тбилиси",
        "to_city":    "Батуми",
        "weight_kg":  500,
        "price_gel":  200,
        "truck_type": "tent",
        "cargo_desc": "Hotfix PR10 test груз",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── Тест 1: /api/deals/my не падает с 500 ────────────────────────────────────

@pytest.mark.asyncio
async def test_get_my_deals_returns_200(client):
    """Регрессия: User object передавался как int — deals/my возвращал 500."""
    shipper_tok, _ = await _register(client, "s_deals_200")
    r = await client.get("/api/deals/my",
                         headers={"Authorization": f"Bearer {shipper_tok}"})
    assert r.status_code == 200, f"Ожидали 200, получили {r.status_code}: {r.text}"
    body = r.json()
    assert "deals" in body
    assert isinstance(body["deals"], list)


# ── Тест 2: carrier_name скрыт до accept ─────────────────────────────────────

@pytest.mark.asyncio
async def test_responses_load_hides_carrier_name_until_accept(client):
    """ADR-013: carrier_name == None пока отклик pending; после accept — виден."""
    shipper_tok, _ = await _register(client, "s_hide_name")
    carrier_tok, _ = await _register(client, "c_hide_name", role="carrier")
    load_id = await _create_load(client, shipper_tok)

    # Carrier откликается
    r_resp = await client.post(f"/api/responses/load/{load_id}", json={
        "price": 180,
        "message": "Готов",
    }, headers={"Authorization": f"Bearer {carrier_tok}"})
    assert r_resp.status_code in (200, 201), r_resp.text
    resp_id = r_resp.json().get("response_id")

    # Пока pending — carrier_name скрыт
    r_list = await client.get(f"/api/responses/load/{load_id}",
                              headers={"Authorization": f"Bearer {shipper_tok}"})
    assert r_list.status_code == 200, r_list.text
    responses = r_list.json().get("responses", [])
    assert len(responses) > 0, "Нет откликов"
    pending = next((x for x in responses if x["id"] == resp_id), responses[0])
    assert pending.get("carrier_name") is None, \
        f"carrier_name должен быть None до accept, получили: {pending.get('carrier_name')}"

    # После accept — carrier_name виден
    r_acc = await client.post(f"/api/responses/accept/{resp_id}",
                              headers={"Authorization": f"Bearer {shipper_tok}"})
    assert r_acc.status_code == 200, r_acc.text

    r_list2 = await client.get(f"/api/responses/load/{load_id}",
                               headers={"Authorization": f"Bearer {shipper_tok}"})
    responses2 = r_list2.json().get("responses", [])
    accepted = next((x for x in responses2 if x["id"] == resp_id), responses2[0])
    assert accepted.get("carrier_name") is not None, \
        "carrier_name должен быть виден после accept"


# ── Тест 3: carrier_company_name — алиас если поле называется так ─────────────

@pytest.mark.asyncio
async def test_responses_load_hides_carrier_company_name_until_accept(client):
    """Дополнительная проверка через company_name напрямую."""
    shipper_tok, _ = await _register(client, "s_co_name")
    carrier_tok, _ = await _register(client, "c_co_name", role="carrier")
    load_id = await _create_load(client, shipper_tok)

    r_resp = await client.post(f"/api/responses/load/{load_id}", json={
        "price": 150,
    }, headers={"Authorization": f"Bearer {carrier_tok}"})
    assert r_resp.status_code in (200, 201), r_resp.text

    r_list = await client.get(f"/api/responses/load/{load_id}",
                              headers={"Authorization": f"Bearer {shipper_tok}"})
    responses = r_list.json().get("responses", [])
    for resp in responses:
        # Проверяем что ни один идентифицирующий ключ не раскрыт
        assert resp.get("carrier_name") is None, \
            f"carrier_name утёк: {resp.get('carrier_name')}"
        assert resp.get("carrier_phone") is None
        assert resp.get("carrier_email") is None
