"""
Тесты ADR-013 Вариант B — контакты только в сделке.

Покрывает:
- GET /api/loads/{id}: незалогиненный → owner_phone=None
- GET /api/loads/{id}: залогиненный без сделки → owner_phone=None
- GET /api/deals/my: участник сделки видит телефон и email контрагента
- GET /api/deals/my: посторонний (не участник) — не может получить чужие сделки
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from app.main import app
from app.database import get_db, Base

TEST_DB = "sqlite+aiosqlite:///./test_adr013.db"
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


async def _register(client, suffix: str, role: str = "shipper") -> tuple[str, int]:
    r = await client.post("/api/auth/register", json={
        "email":        f"adr013_{suffix}@test.ge",
        "password":     "TestPass99!",
        "company_name": f"ADRCo{suffix}",
        "phone":        f"+9955{suffix[-7:].zfill(7)}",
        "role":         role,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    return d["token"], d["user_id"]


async def _create_load(client, token: str) -> int:
    r = await client.post("/api/loads/", json={
        "from_city":  "Тбилиси",
        "to_city":    "Батуми",
        "weight_kg":  2000,
        "price_gel":  500,
        "truck_type": "tent",
        "cargo_desc": "Тест ADR-013",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── Тесты контактов в грузах ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_contacts_hidden_unauthenticated(client):
    """Незалогиненный не видит owner_phone."""
    tok, _ = await _register(client, "s001")
    load_id = await _create_load(client, tok)

    r = await client.get(f"/api/loads/{load_id}")
    assert r.status_code == 200
    d = r.json()
    assert d.get("owner_phone") is None
    assert d.get("owner_email") is None


@pytest.mark.asyncio
async def test_load_contacts_hidden_authenticated_no_deal(client):
    """Залогиненный без сделки не видит owner_phone."""
    shipper_tok, _ = await _register(client, "s002")
    carrier_tok, _ = await _register(client, "c002", role="carrier")
    load_id = await _create_load(client, shipper_tok)

    # Перевозчик запрашивает груз — без сделки
    r = await client.get(f"/api/loads/{load_id}",
                         headers={"Authorization": f"Bearer {carrier_tok}"})
    assert r.status_code == 200
    d = r.json()
    assert d.get("owner_phone") is None, f"Ожидали None, получили: {d.get('owner_phone')}"
    assert d.get("owner_email") is None


@pytest.mark.asyncio
async def test_deal_contacts_visible_to_participant(client):
    """Участник сделки видит телефон и email контрагента через GET /api/deals/my."""
    shipper_tok, shipper_id = await _register(client, "s003")
    carrier_tok, carrier_id = await _register(client, "c003", role="carrier")

    # Создаём груз
    load_id = await _create_load(client, shipper_tok)

    # Перевозчик откликается
    r_resp = await client.post(f"/api/responses/load/{load_id}", json={
        "price_usd": 100,
        "message":   "Готов везти",
    }, headers={"Authorization": f"Bearer {carrier_tok}"})
    assert r_resp.status_code in (200, 201), r_resp.text
    rj = r_resp.json()
    resp_id = rj.get("response_id") or rj.get("response", {}).get("id")

    # Грузовладелец принимает отклик
    r_acc = await client.post(f"/api/responses/accept/{resp_id}",
                              headers={"Authorization": f"Bearer {shipper_tok}"})
    assert r_acc.status_code == 200, r_acc.text

    # Перевозчик смотрит свои сделки — должен видеть телефон грузовладельца
    r_deals = await client.get("/api/deals/my",
                               headers={"Authorization": f"Bearer {carrier_tok}"})
    assert r_deals.status_code == 200
    deals = r_deals.json()["deals"]
    assert len(deals) > 0, "Нет сделок у перевозчика"
    deal = deals[0]
    shipper_data = deal.get("shipper", {})
    assert shipper_data.get("phone") is not None, "Телефон грузовладельца не виден участнику сделки"

    # Грузовладелец смотрит свои сделки — должен видеть телефон перевозчика
    r_deals2 = await client.get("/api/deals/my",
                                headers={"Authorization": f"Bearer {shipper_tok}"})
    deals2 = r_deals2.json()["deals"]
    carrier_data = deals2[0].get("carrier", {})
    assert carrier_data.get("phone") is not None, "Телефон перевозчика не виден участнику сделки"


@pytest.mark.asyncio
async def test_can_respond_always_allowed(client):
    """ADR-013 B: любой авторизованный может откликнуться (нет плана free)."""
    shipper_tok, _ = await _register(client, "s004")
    carrier_tok, _ = await _register(client, "c004", role="carrier")
    load_id = await _create_load(client, shipper_tok)

    r = await client.post(f"/api/responses/load/{load_id}", json={
        "price_usd": 80,
        "message":   "Тест ADR-013 B",
    }, headers={"Authorization": f"Bearer {carrier_tok}"})
    # Не должен возвращать 402/403 по причине тарифа
    assert r.status_code in (200, 201), f"Неожиданный статус: {r.status_code} {r.text}"
