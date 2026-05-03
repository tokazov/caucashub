"""
Тесты Трека 9: справочники, нормализация, счётчики.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_dict.db")
os.environ.setdefault("SECRET_KEY", "test-dict")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

from app.main import app
from app.database import engine, Base
from app.services.normalizers import normalize_email, normalize_phone, normalize_company_name, normalize_tax_id
from app.services.dictionaries import normalize_org_type, normalize_payment_type


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.database import AsyncSessionLocal
    from app.services.cities_seed import seed_cities
    async with AsyncSessionLocal() as db:
        await seed_cities(db)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── Справочники API ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_truck_types_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/dictionaries/truck-types")
    assert r.status_code == 200
    data = r.json()
    assert "truck_types" in data
    assert len(data["truck_types"]) >= 8
    # Каждый тип имеет id, label_ru, label_ge
    for t in data["truck_types"]:
        assert "id" in t
        assert "label_ru" in t
        assert "label_ge" in t


@pytest.mark.asyncio
async def test_payment_types_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/dictionaries/payment-types")
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()["payment_types"]]
    assert "cash" in ids
    assert "bank_3d" in ids
    assert "prepay_50" in ids


@pytest.mark.asyncio
async def test_org_types_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/dictionaries/org-types")
    assert r.status_code == 200
    ids = [o["id"] for o in r.json()["org_types"]]
    assert "llc" in ids
    assert "ie" in ids
    assert "private" in ids


@pytest.mark.asyncio
async def test_countries_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/dictionaries/countries")
    assert r.status_code == 200
    isos = [c["iso"] for c in r.json()["countries"]]
    assert "GE" in isos
    assert "RU" in isos
    assert "TR" in isos


@pytest.mark.asyncio
async def test_all_dictionaries_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/dictionaries/all")
    assert r.status_code == 200
    data = r.json()
    assert all(k in data for k in ("truck_types", "payment_types", "org_types", "countries"))


@pytest.mark.asyncio
async def test_stats_counters_endpoint():
    """Счётчики возвращают нули при пустой БД (не хардкод)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/stats/counters")
    assert r.status_code == 200
    data = r.json()
    assert "active_loads" in data
    assert "online_trucks" in data
    assert "companies" in data
    assert isinstance(data["active_loads"], int)


# ── Нормализаторы (unit) ──────────────────────────────────────────────────────

def test_normalize_email():
    assert normalize_email("  User@EXAMPLE.COM  ") == "user@example.com"
    assert normalize_email("test@test.ge") == "test@test.ge"


def test_normalize_phone_georgian():
    assert normalize_phone("+995 599 123 456") == "+995599123456"
    assert normalize_phone("995599123456") == "+995599123456"


def test_normalize_phone_russian():
    assert normalize_phone("89012345678") == "+79012345678"


def test_normalize_company_name():
    assert normalize_company_name("  ТОО  Рога  ") == "ТОО Рога"
    assert normalize_company_name("") is None


def test_normalize_tax_id_georgia():
    assert normalize_tax_id("123456789") == "123456789"
    assert normalize_tax_id("123-456-789") == "123456789"
    assert normalize_tax_id("12345") is None  # не 9 цифр


def test_normalize_org_type():
    assert normalize_org_type("ООО") == "llc"
    assert normalize_org_type("ИП") == "ie"
    assert normalize_org_type("შპს") == "llc"
    assert normalize_org_type("private") == "private"
    assert normalize_org_type("что-то неизвестное") == "private"  # fallback


def test_normalize_payment_type():
    assert normalize_payment_type("Нал") == "cash"
    assert normalize_payment_type("Безнал 3 дня") == "bank_3d"
    assert normalize_payment_type("50% предоплата") == "prepay_50"
    assert normalize_payment_type("cash") == "cash"
