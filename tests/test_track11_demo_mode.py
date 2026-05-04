"""
Трек 11.1 — Тесты Demo-режима (ADR-012).

Сценарии:
1. Незалогиненный видит демо-груз в ленте (is_demo=True в ответе API).
2. POST /api/responses/load/{demo_id} → 400 "Demo loads cannot receive responses".
3. GET /api/stats/counters — демо-груз НЕ учитывается.
4. Инвалидация кеша: создать реальный груз → счётчик обновляется немедленно.
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_track11_demo.db")
os.environ.setdefault("SECRET_KEY", "test-demo-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("BREVO_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TG_BOT_TOKEN", "test:test")

import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.models.user import User, UserRole, UserPlan
from app.models.load import Load, LoadStatus
from app.routers.stats import invalidate_counters_cache
from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Создаём таблицы + seed данные перед каждым тестом. После — очищаем таблицы."""
    from sqlalchemy import delete as sql_delete
    from app.models.response import Response
    from app.models.deal import Deal
    from app.models.status_change import StatusChange

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Очищаем данные перед тестом (порядок по FK)
    async with AsyncSessionLocal() as db:
        await db.execute(sql_delete(StatusChange))
        await db.execute(sql_delete(Deal))
        await db.execute(sql_delete(Response))
        await db.execute(sql_delete(Load))
        await db.execute(sql_delete(User))
        await db.commit()

    # Seed данные
    import datetime
    async with AsyncSessionLocal() as db:
        real_user = User(
            email="carrier_demo@test.ge",
            hashed_password=pwd_context.hash("pass123"),
            company_name="Real Carrier",
            phone="+99512345678",
            role=UserRole.carrier,
            plan=UserPlan.standard,
            is_active=True,
        )
        demo_user = User(
            email="demo_owner@test.ge",
            hashed_password=pwd_context.hash("pass123"),
            company_name="Demo Company",
            phone="+99500000001",
            role=UserRole.shipper,
            is_demo=True,
        )
        db.add_all([real_user, demo_user])
        await db.commit()
        await db.refresh(real_user)
        await db.refresh(demo_user)

        real_load = Load(
            user_id=real_user.id,
            from_city="Тбилиси",
            to_city="Батуми",
            weight_kg=1000,
            truck_type="tent",
            load_date=datetime.datetime.now(datetime.timezone.utc),
            price_gel=500,
            status=LoadStatus.active,
            is_demo=False,
        )
        demo_load = Load(
            user_id=demo_user.id,
            from_city="Кутаиси",
            to_city="Рустави",
            weight_kg=500,
            truck_type="gazel",
            load_date=datetime.datetime.now(datetime.timezone.utc),
            price_gel=0,
            status=LoadStatus.active,
            is_demo=True,
        )
        db.add_all([real_load, demo_load])
        await db.commit()

    invalidate_counters_cache()
    yield


transport = ASGITransport(app=app)


@pytest.mark.asyncio
async def test_unauthenticated_sees_demo_flag():
    """Незалогиненный получает is_demo=True в ленте для демо-грузов."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/loads/")
    assert r.status_code == 200
    loads = r.json()["loads"]
    demo_loads = [l for l in loads if l.get("is_demo")]
    assert len(demo_loads) >= 1, "Должен быть хотя бы один демо-груз в ленте"


@pytest.mark.asyncio
async def test_respond_to_demo_load_blocked():
    """POST отклика на демо-груз → 400."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/loads/")
    demo = next((l for l in r.json()["loads"] if l.get("is_demo")), None)
    assert demo, "Демо-груз не найден в ленте"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_r = await client.post("/api/auth/login", json={"email": "carrier_demo@test.ge", "password": "pass123"})
    token = login_r.json()["token"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/responses/load/{demo['id']}",
            json={"message": "хочу везти", "price": 300},
            headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 400
    assert "Demo loads cannot receive responses" in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_counters_exclude_demo():
    """GET /api/stats/counters — демо-грузы не считаются."""
    invalidate_counters_cache()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/stats/counters")
    assert r.status_code == 200
    data = r.json()
    # В тестовой БД: 1 реальный груз + 1 демо-груз. Счётчик должен быть 1.
    assert data["active_loads"] == 1, f"Ожидали 1 реальный груз, получили {data['active_loads']}"


@pytest.mark.asyncio
async def test_cache_invalidated_on_load_create():
    """Создать реальный груз → счётчик /api/stats/counters обновляется сразу (не через 10 мин)."""
    invalidate_counters_cache()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/api/stats/counters")
    count_before = r1.json()["active_loads"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_r = await client.post("/api/auth/login", json={"email": "carrier_demo@test.ge", "password": "pass123"})
    token = login_r.json()["token"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cr = await client.post(
            "/api/loads/",
            json={
                "from_city": "Гори",
                "to_city": "Мцхета",
                "weight_kg": 200,
                "truck_type": "gazel",
                "price_gel": 150,
            },
            headers={"Authorization": f"Bearer {token}"}
        )
    assert cr.status_code == 200

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r2 = await client.get("/api/stats/counters")
    count_after = r2.json()["active_loads"]

    assert count_after == count_before + 1, (
        f"Кеш не инвалидирован: было {count_before}, ожидали {count_before+1}, получили {count_after}"
    )
