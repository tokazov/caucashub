"""
Тесты ADR-016 Этап 2 — Transport CRUD + статус-машины + IDOR.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from unittest.mock import patch
from app.main import app
from app.database import get_db, Base

TEST_DB = "sqlite+aiosqlite:///./test_transport_e2.db"
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


# Отключаем rate limit для тестов (все запросы с одного IP 127.0.0.1)
@pytest.fixture(autouse=True)
def no_rate_limit():
    with patch("app.routers.auth._check_brute_force_generic"):
        with patch("app.routers.auth._check_brute_force"):
            yield


@pytest_asyncio.fixture(scope="module")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _reg(client, suffix, role="carrier"):
    r = await client.post("/api/auth/register", json={
        "email": f"tr_e2_{suffix}@test.ge", "password": "TestPass99!",
        "company_name": f"TrE2_{suffix}", "phone": f"+9955{suffix[-7:].zfill(7)}",
        "role": role,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    return d["token"], d["user_id"]


_OFFER_DATA = {
    "from_city": "Тбилиси", "to_city": "Батуми",
    "truck_type": "tent", "capacity_kg": 10000,
    "available_from": "2026-06-01T08:00:00",
    "available_to":   "2026-06-05T18:00:00",
    "price": 800, "urgent": False,
}


# ── TransportOffer CRUD ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_transport_offer(client):
    tok, uid = await _reg(client, "c001")
    r = await client.post("/api/transport/", json=_OFFER_DATA,
                          headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["offer"]["from_city"] == "Тбилиси"
    assert d["offer"]["status"] == "active"


@pytest.mark.asyncio
async def test_list_transport_offers_public(client):
    r = await client.get("/api/transport/")
    assert r.status_code == 200
    d = r.json()
    assert "offers" in d
    assert "total" in d


@pytest.mark.asyncio
async def test_get_transport_offer_no_contacts(client):
    """Контакты скрыты в публичном эндпоинте (ADR-013 B)."""
    tok, _ = await _reg(client, "c002")
    r_create = await client.post("/api/transport/", json=_OFFER_DATA,
                                 headers={"Authorization": f"Bearer {tok}"})
    offer_id = r_create.json()["offer"]["id"]

    r = await client.get(f"/api/transport/{offer_id}")
    assert r.status_code == 200
    assert r.json().get("owner_phone") is None


@pytest.mark.asyncio
async def test_patch_transport_offer(client):
    tok, _ = await _reg(client, "c003")
    r_c = await client.post("/api/transport/", json=_OFFER_DATA,
                            headers={"Authorization": f"Bearer {tok}"})
    oid = r_c.json()["offer"]["id"]

    r = await client.patch(f"/api/transport/{oid}", json={"price": 900, "urgent": True},
                           headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["offer"]["price"] == 900
    assert r.json()["offer"]["urgent"] is True


@pytest.mark.asyncio
async def test_delete_transport_offer_sets_canceled(client):
    tok, _ = await _reg(client, "c004")
    r_c = await client.post("/api/transport/", json=_OFFER_DATA,
                            headers={"Authorization": f"Bearer {tok}"})
    oid = r_c.json()["offer"]["id"]

    r = await client.delete(f"/api/transport/{oid}",
                            headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"


@pytest.mark.asyncio
async def test_idor_patch_others_offer(client):
    tok1, _ = await _reg(client, "c005")
    tok2, _ = await _reg(client, "c006")
    r_c = await client.post("/api/transport/", json=_OFFER_DATA,
                            headers={"Authorization": f"Bearer {tok1}"})
    oid = r_c.json()["offer"]["id"]

    r = await client.patch(f"/api/transport/{oid}", json={"price": 1},
                           headers={"Authorization": f"Bearer {tok2}"})
    assert r.status_code == 403


# ── TransportRequest ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_transport_request(client):
    carrier_tok, _ = await _reg(client, "c010")
    shipper_tok, _ = await _reg(client, "s010", role="shipper")

    r_offer = await client.post("/api/transport/", json=_OFFER_DATA,
                                headers={"Authorization": f"Bearer {carrier_tok}"})
    oid = r_offer.json()["offer"]["id"]

    r = await client.post(f"/api/transport/{oid}/request", json={
        "cargo_description": "Строительные материалы",
        "weight_kg": 5000, "message": "Нужна машина на 1 июня",
    }, headers={"Authorization": f"Bearer {shipper_tok}"})
    assert r.status_code == 201, r.text
    assert r.json()["request"]["status"] == "pending"


@pytest.mark.asyncio
async def test_duplicate_request_rejected(client):
    carrier_tok, _ = await _reg(client, "c011")
    shipper_tok, _ = await _reg(client, "s011", role="shipper")

    r_offer = await client.post("/api/transport/", json=_OFFER_DATA,
                                headers={"Authorization": f"Bearer {carrier_tok}"})
    oid = r_offer.json()["offer"]["id"]

    await client.post(f"/api/transport/{oid}/request", json={"message": "1"},
                      headers={"Authorization": f"Bearer {shipper_tok}"})
    r2 = await client.post(f"/api/transport/{oid}/request", json={"message": "2"},
                           headers={"Authorization": f"Bearer {shipper_tok}"})
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_owner_cannot_request_own_offer(client):
    tok, _ = await _reg(client, "c012")
    r_offer = await client.post("/api/transport/", json=_OFFER_DATA,
                                headers={"Authorization": f"Bearer {tok}"})
    oid = r_offer.json()["offer"]["id"]

    r = await client.post(f"/api/transport/{oid}/request", json={},
                          headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_accept_transport_request_creates_deal(client):
    """Accept → Deal создана с transport_offer_id."""
    carrier_tok, carrier_id = await _reg(client, "c020")
    shipper_tok, shipper_id = await _reg(client, "s020", role="shipper")

    r_offer = await client.post("/api/transport/", json=_OFFER_DATA,
                                headers={"Authorization": f"Bearer {carrier_tok}"})
    oid = r_offer.json()["offer"]["id"]

    r_req = await client.post(f"/api/transport/{oid}/request", json={"message": "Хочу"},
                              headers={"Authorization": f"Bearer {shipper_tok}"})
    req_id = r_req.json()["request"]["id"]

    r_acc = await client.post(f"/api/transport-requests/{req_id}/accept",
                              headers={"Authorization": f"Bearer {carrier_tok}"})
    assert r_acc.status_code == 200, r_acc.text
    d = r_acc.json()
    assert d["ok"] is True
    assert "deal_id" in d
    assert d["act_number"].startswith("CH-")

    # Проверяем что offer стал taken
    r_offer2 = await client.get(f"/api/transport/{oid}")
    assert r_offer2.json()["status"] == "taken"


@pytest.mark.asyncio
async def test_reject_transport_request(client):
    carrier_tok, _ = await _reg(client, "c021")
    shipper_tok, _ = await _reg(client, "s021", role="shipper")

    r_offer = await client.post("/api/transport/", json=_OFFER_DATA,
                                headers={"Authorization": f"Bearer {carrier_tok}"})
    oid = r_offer.json()["offer"]["id"]

    r_req = await client.post(f"/api/transport/{oid}/request", json={},
                              headers={"Authorization": f"Bearer {shipper_tok}"})
    req_id = r_req.json()["request"]["id"]

    r = await client.post(f"/api/transport-requests/{req_id}/reject",
                          headers={"Authorization": f"Bearer {carrier_tok}"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_cancel_transport_request(client):
    carrier_tok, _ = await _reg(client, "c022")
    shipper_tok, _ = await _reg(client, "s022", role="shipper")

    r_offer = await client.post("/api/transport/", json=_OFFER_DATA,
                                headers={"Authorization": f"Bearer {carrier_tok}"})
    oid = r_offer.json()["offer"]["id"]

    r_req = await client.post(f"/api/transport/{oid}/request", json={},
                              headers={"Authorization": f"Bearer {shipper_tok}"})
    req_id = r_req.json()["request"]["id"]

    r = await client.delete(f"/api/transport-requests/{req_id}",
                            headers={"Authorization": f"Bearer {shipper_tok}"})
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"


@pytest.mark.asyncio
async def test_idor_accept_others_request(client):
    """Нельзя принять отклик на чужое предложение."""
    c1, _ = await _reg(client, "c030")
    c2, _ = await _reg(client, "c031")
    s1, _ = await _reg(client, "s030", role="shipper")

    r_offer = await client.post("/api/transport/", json=_OFFER_DATA,
                                headers={"Authorization": f"Bearer {c1}"})
    oid = r_offer.json()["offer"]["id"]

    r_req = await client.post(f"/api/transport/{oid}/request", json={},
                              headers={"Authorization": f"Bearer {s1}"})
    req_id = r_req.json()["request"]["id"]

    # c2 пытается принять отклик на предложение c1
    r = await client.post(f"/api/transport-requests/{req_id}/accept",
                          headers={"Authorization": f"Bearer {c2}"})
    assert r.status_code == 403


# ── TransportSubscription ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_transport_subscription_crud(client):
    tok, _ = await _reg(client, "s040", role="shipper")

    r = await client.post("/api/transport-subscriptions/", json={
        "from_city": "Тбилиси", "to_city": "Батуми",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 201
    sub_id = r.json()["subscription"]["id"]

    r_list = await client.get("/api/transport-subscriptions/",
                              headers={"Authorization": f"Bearer {tok}"})
    assert r_list.json()["total"] == 1

    r_del = await client.delete(f"/api/transport-subscriptions/{sub_id}",
                                headers={"Authorization": f"Bearer {tok}"})
    assert r_del.status_code == 200
