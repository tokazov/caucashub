"""Real HTTP journeys on disposable databases; no email or Telegram delivery."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models.idempotency_key import IdempotencyKey
from app.models.load import Load
from app.routers import auth, deals, loads, responses, transport, transport_requests
from app.services import exchange_rate, subscription_matcher, telegram_notify, transport_matcher
from app.services.listing_freshness import listing_day_start


@pytest_asyncio.fixture(params=[
    "sqlite",
    pytest.param("postgresql", marks=pytest.mark.skipif(
        not os.environ.get("TEST_POSTGRES_URL"), reason="requires isolated CI PostgreSQL")),
])
async def journey(request, tmp_path, monkeypatch):
    schema = "test_publication_" + uuid4().hex
    bootstrap = None
    if request.param == "postgresql":
        url = os.environ["TEST_POSTGRES_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
        bootstrap = create_async_engine(url)
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'journey.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def isolated_db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    for router, prefix in [
        (auth.router, "/api/auth"), (loads.router, "/api/loads"),
        (deals.router, "/api/deals"), (responses.router, ""),
        (transport.router, ""), (transport_requests.router, ""),
    ]:
        app.include_router(router, prefix=prefix)
    app.dependency_overrides[get_db] = isolated_db
    auth._login_attempts.clear()
    rate = AsyncMock(return_value=2.7)
    notifications = AsyncMock(return_value=0)
    monkeypatch.setattr(exchange_rate, "get_usd_gel_rate", rate)
    monkeypatch.setattr(subscription_matcher, "notify_subscribers", notifications)
    monkeypatch.setattr(transport_matcher, "notify_transport_subscribers", AsyncMock(return_value=0))
    monkeypatch.setattr(telegram_notify, "send_tg_message", AsyncMock(return_value=True))
    monkeypatch.setattr(telegram_notify, "notify_owner_new_user", AsyncMock())
    monkeypatch.setattr(responses, "send_email", AsyncMock())

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://testserver") as client:
        headers = {}
        for index, role in enumerate(["shipper", "carrier"], 1):
            credentials = {"email": f"{role}@example.test", "password": "JourneyTest39!"}
            response = await client.post("/api/auth/register", json={
                **credentials, "company_name": f"Test {role}",
                "phone": f"+99559900000{index}", "role": role, "inn": "404123456",
            })
            assert response.status_code == 200, response.text
            login = await client.post("/api/auth/login", json=credentials)
            assert login.status_code == 200, login.text
            headers[role] = {"Authorization": "Bearer " + login.json()["token"]}
        yield {"client": client, "headers": headers, "sessions": sessions,
               "engine": engine, "notifications": notifications, "rate": rate}

    await engine.dispose()
    if bootstrap:
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()


def cargo():
    tomorrow = listing_day_start() + timedelta(days=1)
    return {"from_city": "Тбилиси", "to_city": "Батуми", "weight_kg": 3000,
            "price_gel": 500, "truck_type": "tent", "scope": "local",
            "load_date": tomorrow.isoformat(),
            "load_date_end": (tomorrow + timedelta(days=2)).isoformat()}


async def load_count(context):
    async with context["sessions"]() as db:
        return (await db.execute(select(func.count()).select_from(Load))).scalar_one()


@pytest.mark.asyncio
async def test_retry_replays_saved_load_and_rejects_changed_payload(journey):
    client = journey["client"]
    headers = {**journey["headers"]["shipper"], "Idempotency-Key": "publication-retry"}
    body = cargo()
    first = await client.post("/api/loads/", headers=headers, json=body)
    assert first.status_code == 200, first.text
    replay = await client.post("/api/loads/", headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()
    assert await load_count(journey) == 1
    journey["notifications"].assert_awaited_once()
    changed = await client.post("/api/loads/", headers=headers, json={**body, "weight_kg": 4000})
    assert changed.status_code == 422
    assert changed.json()["detail"]["code"] == "idempotency_payload_mismatch"
    assert await load_count(journey) == 1


@pytest.mark.asyncio
async def test_old_client_without_key_still_publishes(journey):
    response = await journey["client"].post("/api/loads/", json=cargo(),
        headers=journey["headers"]["shipper"])
    assert response.status_code == 200, response.text
    assert await load_count(journey) == 1


@pytest.mark.asyncio
async def test_idempotency_cache_is_scoped_to_user(journey):
    ids = []
    for role in ("shipper", "carrier"):
        response = await journey["client"].post("/api/loads/", json=cargo(),
            headers={**journey["headers"][role], "Idempotency-Key": "same-key-two-users"})
        assert response.status_code == 200, response.text
        ids.append(response.json()["id"])
    assert len(set(ids)) == 2
    assert await load_count(journey) == 2


@pytest.mark.asyncio
async def test_overlong_idempotency_key_is_validation_error(journey):
    response = await journey["client"].post("/api/loads/", json=cargo(),
        headers={**journey["headers"]["shipper"], "Idempotency-Key": "x" * 256})
    assert response.status_code == 422
    assert await load_count(journey) == 0


@pytest.mark.asyncio
async def test_cache_failure_rolls_back_load_and_notification(journey):
    def fail_cache(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO IDEMPOTENCY_KEYS"):
            raise RuntimeError("Simulated cache write failure")
    event.listen(journey["engine"].sync_engine, "before_cursor_execute", fail_cache)
    try:
        response = await journey["client"].post("/api/loads/", json=cargo(),
            headers={**journey["headers"]["shipper"], "Idempotency-Key": "failed-cache"})
        assert response.status_code == 500
        assert await load_count(journey) == 0
        journey["notifications"].assert_not_awaited()
    finally:
        event.remove(journey["engine"].sync_engine, "before_cursor_execute", fail_cache)


@pytest.mark.asyncio
async def test_expired_key_can_be_reused(journey):
    client = journey["client"]
    headers = {**journey["headers"]["shipper"], "Idempotency-Key": "expired-cache"}
    first = await client.post("/api/loads/", headers=headers, json=cargo())
    assert first.status_code == 200, first.text
    async with journey["sessions"]() as db:
        await db.execute(update(IdempotencyKey).values(
            expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
        await db.commit()
    second = await client.post("/api/loads/", headers=headers, json=cargo())
    assert second.status_code == 200, second.text
    assert second.json()["id"] != first.json()["id"]
    assert await load_count(journey) == 2


@pytest.mark.asyncio
async def test_concurrent_postgresql_retries_create_one_load(journey):
    if journey["engine"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL transaction locking")
    async def slow_rate():
        await asyncio.sleep(0.1)
        return 2.7
    journey["rate"].side_effect = slow_rate
    headers = {**journey["headers"]["shipper"], "Idempotency-Key": "concurrent-retry"}
    body = cargo()
    responses_ = await asyncio.gather(*[
        journey["client"].post("/api/loads/", headers=headers, json=body) for _ in range(2)
    ])
    assert [r.status_code for r in responses_] == [200, 200], [r.text for r in responses_]
    assert len({r.json()["id"] for r in responses_}) == 1
    assert sum(r.headers.get("Idempotency-Replayed") == "true" for r in responses_) == 1
    assert await load_count(journey) == 1
    journey["notifications"].assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["cargo", "transport"])
async def test_two_roles_from_registration_to_completed_deal(journey, source):
    client, roles = journey["client"], journey["headers"]
    if source == "cargo":
        created = await client.post("/api/loads/", json=cargo(), headers=roles["shipper"])
        assert created.status_code == 200, created.text
        item_id = created.json()["id"]
        feed = await client.get("/api/loads/?from_city=Тбилиси&to_city=Батуми")
        assert item_id in {row["id"] for row in feed.json()["loads"]}
        detail = await client.get(f"/api/loads/{item_id}")
        assert detail.json()["owner_phone"] is None
        request = await client.post(f"/api/responses/load/{item_id}", json={"price": 500},
                                    headers=roles["carrier"])
        assert request.status_code in (200, 201), request.text
        request_id = request.json()["response_id"]
        duplicate = await client.post(f"/api/responses/load/{item_id}", json={"price": 500},
                                      headers=roles["carrier"])
        assert duplicate.status_code == 400
        accepted = await client.post(f"/api/responses/accept/{request_id}", headers=roles["shipper"])
    else:
        created = await client.post("/api/transport/", headers=roles["carrier"], json={
            "from_city": "Тбилиси", "to_city": "Батуми", "truck_type": "tent",
            "capacity_kg": 10000, "available_from": cargo()["load_date"], "price": 500,
        })
        assert created.status_code == 201, created.text
        item_id = created.json()["offer"]["id"]
        feed = await client.get("/api/transport/?from_city=Тбилиси")
        assert item_id in {row["id"] for row in feed.json()["offers"]}
        detail = await client.get(f"/api/transport/{item_id}")
        assert detail.json()["owner_phone"] is None
        request = await client.post(f"/api/transport/{item_id}/request", headers=roles["shipper"],
                                    json={"cargo_description": "Test cargo", "weight_kg": 3000})
        assert request.status_code == 201, request.text
        request_id = request.json()["request"]["id"]
        accepted = await client.post(f"/api/transport-requests/{request_id}/accept", headers=roles["carrier"])
    assert accepted.status_code == 200, accepted.text
    deal_id = accepted.json()["deal_id"]
    for role in ("shipper", "carrier"):
        personal = await client.get("/api/deals/my", headers=roles[role])
        deal = next(row for row in personal.json()["deals"] if row["id"] == deal_id)
        assert deal["deal_source"] == source
        assert deal["shipper"]["phone"] and deal["carrier"]["phone"]
        assert deal["load_from"] == "Тбилиси"
        assert deal["load_to"] == "Батуми"
        assert deal["load_kg"] == 3000
    for status, role in [("loading", "carrier"), ("in_transit", "carrier"),
                         ("delivered_carrier", "carrier"), ("delivered_shipper", "shipper")]:
        response = await client.post(f"/api/deals/{deal_id}/status", json={"status": status},
                                     headers=roles[role])
        assert response.status_code == 200, response.text
    personal = await client.get("/api/deals/my", headers=roles["shipper"])
    assert next(row for row in personal.json()["deals"] if row["id"] == deal_id)["status"] == "completed"
