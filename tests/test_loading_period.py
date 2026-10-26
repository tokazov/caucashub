"""Calendar dates survive API round trips and loading periods control visibility."""
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine, inspect, select, text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError

from tests.test_listing_freshness import db  # isolated in-memory DB fixture
from app.database import get_db
from app.models.load import Load
from app.models.user import User
from app.routers.auth import require_user
from app.routers.loads import LoadCreate, LoadUpdate, router
from app.services.listing_freshness import loading_day, parse_loading_day
from app.routers.stats import get_counters, invalidate_counters_cache


def day(offset=0):
    return (loading_day(datetime.now(timezone.utc)) + timedelta(days=offset)).isoformat()


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    from app.services import exchange_rate, idempotency, subscription_matcher

    async def rate():
        return 2.7

    async def no_replay(*args, **kwargs):
        return None, False

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(exchange_rate, "get_usd_gel_rate", rate)
    monkeypatch.setattr(idempotency, "check_idempotency", no_replay)
    monkeypatch.setattr(idempotency, "save_idempotency", noop)
    monkeypatch.setattr(subscription_matcher, "notify_subscribers", noop)
    application = FastAPI()
    application.include_router(router, prefix="/api/loads")

    async def session():
        yield db

    async def user():
        return await db.get(User, 1)

    application.dependency_overrides[get_db] = session
    application.dependency_overrides[require_user] = user
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c:
        yield c


def payload(start=None, end=None):
    return dict(from_city="Tbilisi", to_city="Batumi", weight_kg=1000,
                truck_type="tent", price_gel=500,
                load_date=start or day(2), load_date_end=end)


@pytest.mark.parametrize("value", [
    "2026-10-27", "27.10.26", "27.10.2026",
    "2026-10-26T20:00:00Z", "2026-10-27T00:00:00+04:00",
])
def test_calendar_formats_are_same_georgian_day(value):
    assert parse_loading_day(value) == datetime(2026, 10, 26, 20, tzinfo=timezone.utc)


@pytest.mark.parametrize("schema", [LoadCreate, LoadUpdate])
@pytest.mark.parametrize("value", ["2026-02-30", "31.02.26", "", "invalid", 123])
def test_invalid_end_is_rejected(schema, value):
    with pytest.raises(ValidationError):
        schema(**payload(end=value))


@pytest.mark.asyncio
async def test_api_roundtrip_and_edit_persist_both_dates(client, db):
    r = await client.post("/api/loads/", json=payload(end=day(5)))
    assert r.status_code == 200, r.text
    result = r.json()
    ident = result["id"]
    db.expunge_all()  # subsequent requests must reload from the database
    mine = (await client.get("/api/loads/my/loads")).json()["loads"]
    assert mine[0]["load_date"] == day(2)
    assert mine[0]["load_date_end"] == day(5)
    assert mine[0]["date2"] is not None

    r = await client.put(f"/api/loads/{ident}", json={
        "load_date": day(3), "load_date_end": day(6), "cargo_desc": "Updated"
    })
    assert r.status_code == 200, r.text
    db.expunge_all()
    mine = (await client.get("/api/loads/my/loads")).json()["loads"][0]
    assert (mine["load_date"], mine["load_date_end"]) == (day(3), day(6))

    # Editing unrelated metadata preserves the period.
    r = await client.put(f"/api/loads/{ident}", json={"cargo_desc": "Only notes"})
    assert r.status_code == 200
    assert r.json()["load_date_end"] == day(6)

    # Explicit null removes the end; omission does not.
    r = await client.put(f"/api/loads/{ident}", json={"load_date_end": None})
    assert r.status_code == 200
    db.expunge_all()
    mine = (await client.get("/api/loads/my/loads")).json()["loads"][0]
    assert mine["load_date_end"] is None
    assert mine["date2"] is None
    assert mine["load_date"] == day(3)


@pytest.mark.asyncio
async def test_reversed_period_is_rejected_on_create_and_partial_update(client):
    r = await client.post("/api/loads/", json=payload(end=day(1)))
    assert r.status_code == 422
    good = await client.post("/api/loads/", json=payload(end=day(5)))
    ident = good.json()["id"]
    for patch in [{"load_date_end": day(1)}, {"load_date": day(6)}, {"load_date": None}]:
        r = await client.put(f"/api/loads/{ident}", json=patch)
        assert r.status_code == 422, r.text
    mine = (await client.get("/api/loads/my/loads")).json()["loads"][0]
    assert (mine["load_date"], mine["load_date_end"]) == (day(2), day(5))


@pytest.mark.asyncio
async def test_ongoing_period_visible_and_counts_toward_quota(client, db):
    good = await client.post("/api/loads/", json=payload(day(-1), day(1)))
    assert good.status_code == 200, good.text
    public = (await client.get("/api/loads/")).json()["loads"]
    assert [x["id"] for x in public] == [good.json()["id"]]
    invalidate_counters_cache()
    assert (await get_counters(db))["active_loads"] == 1
    # Removing the end would make the period expired; reject without modifying it.
    r = await client.put(f"/api/loads/{good.json()['id']}", json={"load_date_end": None})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_expired_period_hidden_and_renewal_cannot_bypass_tariff(client, db):
    old = Load(user_id=1, from_city="Tbilisi", to_city="Batumi",
               weight_kg=1000, truck_type="tent",
               load_date=parse_loading_day(day(-3)),
               load_date_end=parse_loading_day(day(-1)))
    db.add(old)
    await db.commit()
    ident = old.id
    assert not (await client.get("/api/loads/")).json()["loads"]
    for _ in range(5):
        r = await client.post("/api/loads/", json=payload(end=day(5)))
        assert r.status_code == 200, r.text
    r = await client.put(f"/api/loads/{ident}", json={"load_date": day(2), "load_date_end": None})
    assert r.status_code == 403
    assert r.json()["detail"]["current"] == 5
    mine = (await client.get("/api/loads/my/loads")).json()["loads"]
    assert len(mine) == 6  # expired history is preserved
    assert len((await client.get("/api/loads/")).json()["loads"]) == 5


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/020_load_date_end.py"
    spec = importlib.util.spec_from_file_location("loading_period_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_upgrade(engine, monkeypatch, temporary=False):
    module = migration()
    with engine.begin() as conn:
        conn.execute(text(("CREATE TEMPORARY TABLE " if temporary else "CREATE TABLE ")
                          + "loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
        conn.execute(text("INSERT INTO loads (id, load_date) VALUES (1, '2026-01-01')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        module.upgrade()
        module.upgrade()  # startup fallback and Alembic may execute in either order
        assert conn.execute(text("SELECT id, load_date_end FROM loads")).first() == (1, None)
        columns = {c["name"]: c for c in inspect(conn).get_columns("loads")}
        assert columns["load_date_end"]["nullable"]
    engine.dispose()


def test_sqlite_upgrade_is_idempotent_and_keeps_existing_rows(monkeypatch):
    check_upgrade(create_engine("sqlite:///:memory:"), monkeypatch)


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="requires isolated CI PostgreSQL")
def test_postgresql_upgrade_is_idempotent_and_keeps_existing_rows(monkeypatch):
    check_upgrade(create_engine(os.environ["TEST_POSTGRES_URL"]), monkeypatch, temporary=True)
