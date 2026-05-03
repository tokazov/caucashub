"""
Тесты ADR-007А: таблица cities, автокомплит, сидинг.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_cities.db")
os.environ.setdefault("SECRET_KEY", "test-cities-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

from app.main import app
from app.database import engine, Base


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Сидинг городов (в тестах lifespan не запускается автоматически)
    from app.database import AsyncSessionLocal
    from app.services.cities_seed import seed_cities
    async with AsyncSessionLocal() as db:
        await seed_cities(db)

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_cities_seeded_on_startup():
    """Таблица cities должна быть заполнена (сидинг через fixture)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/cities/?popular_only=true&limit=20")
        assert r.status_code == 200
        data = r.json()
        assert "cities" in data
        assert len(data["cities"]) >= 5, f"Expected >=5 popular cities, got {len(data['cities'])}"


@pytest.mark.asyncio
async def test_city_autocomplete_tbilisi():
    """Автокомплит по 'Тби' должен вернуть Тбилиси."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/cities/?q=Тби")
        assert r.status_code == 200
        cities = r.json()["cities"]
        names = [c["name_ru"] for c in cities]
        assert "Тбилиси" in names, f"Тбилиси not found in {names}"


@pytest.mark.asyncio
async def test_city_filter_by_country():
    """Фильтр по стране GE возвращает только грузинские города."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/cities/?country=GE&limit=50")
        assert r.status_code == 200
        cities = r.json()["cities"]
        assert len(cities) >= 10
        for c in cities:
            assert c["country_iso"] == "GE", f"Non-GE city found: {c}"


@pytest.mark.asyncio
async def test_city_has_coordinates():
    """Тбилиси должен иметь координаты."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/cities/?q=Тбилиси")
        cities = r.json()["cities"]
        tbilisi = next((c for c in cities if c["name_ru"] == "Тбилиси"), None)
        assert tbilisi is not None
        assert tbilisi["lat"] is not None
        assert tbilisi["lon"] is not None
        assert abs(tbilisi["lat"] - 41.69) < 0.1


@pytest.mark.asyncio
async def test_yandex_not_available_yet():
    """Яндекс пока недоступен (ключ ожидается) — API сигнализирует об этом."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/cities/")
        assert r.status_code == 200
        assert r.json().get("yandex_available") == False
