"""Carrier defaults survive new sessions without changing public vehicles."""
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models.user import User
from app.models.truck import Truck
from app.models.transport_offer import TransportOffer
from app.routers import auth, users
from app.services import telegram_notify


@pytest.mark.parametrize("model", [auth.RegisterRequest, users.UpdateProfileRequest])
@pytest.mark.parametrize("fields", [
    {"truck_type": "unknown"}, {"tonnage": 0}, {"tonnage": -1},
    {"tonnage": 101}, {"tonnage": float("nan")},
    {"tonnage": float("inf")}, {"tonnage": True},
])
def test_profile_and_registration_reject_invalid_defaults(model, fields):
    with pytest.raises(ValidationError):
        model(**{"email": "schema@example.test", "password": "StrongPass39!",
                 "company_name": "Schema", "phone": "+995599000001", **fields})


@pytest_asyncio.fixture(params=[
    "sqlite", pytest.param("postgresql", marks=pytest.mark.skipif(
        not os.environ.get("TEST_POSTGRES_URL"), reason="requires isolated CI PostgreSQL")),
])
async def profile(request, tmp_path, monkeypatch):
    bootstrap = None
    schema = "test_carrier_profile_" + uuid4().hex
    if request.param == "postgresql":
        url = os.environ["TEST_POSTGRES_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
        bootstrap = create_async_engine(url)
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def isolated_db():
        async with sessions() as session:
            yield session

    application = FastAPI()
    application.include_router(auth.router, prefix="/api/auth")
    application.include_router(users.router, prefix="/api/users")
    application.dependency_overrides[get_db] = isolated_db
    auth._login_attempts.clear()
    monkeypatch.setattr(telegram_notify, "notify_owner_new_user", AsyncMock())
    try:
        async with AsyncClient(transport=ASGITransport(app=application),
                               base_url="http://profile.test") as client:
            accounts = {}
            for index, name in enumerate(("carrier", "other"), 1):
                credentials = {"email": name + "@example.test", "password": "CarrierProfile39!"}
                response = await client.post("/api/auth/register", json={
                    **credentials, "company_name": name, "phone": f"+99559900000{index}",
                    "role": "carrier", "truck_type": "ref", "tonnage": 3.5,
                })
                assert response.status_code == 200, response.text
                accounts[name] = {"headers": {"Authorization": "Bearer " + response.json()["token"]},
                                  "id": response.json()["user_id"], "credentials": credentials,
                                  "registered": response.json()}
            yield {"client": client, "sessions": sessions, "accounts": accounts}
    finally:
        await engine.dispose()
        if bootstrap:
            async with bootstrap.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await bootstrap.dispose()


@pytest.mark.asyncio
async def test_registration_and_new_login_restore_fractional_tonnes(profile):
    account = profile["accounts"]["carrier"]
    assert account["registered"]["truck_type"] == "ref"
    assert account["registered"]["tonnage"] == 3.5
    login = await profile["client"].post("/api/auth/login", json=account["credentials"])
    assert login.status_code == 200
    response = await profile["client"].get("/api/users/me",
        headers={"Authorization": "Bearer " + login.json()["token"]})
    assert response.json()["truck_type"] == "ref"
    assert response.json()["tonnage"] == 3.5
    async with profile["sessions"]() as session:
        saved = await session.get(User, account["id"])
        assert (saved.truck_type, saved.tonnage) == ("ref", 3.5)


@pytest.mark.asyncio
async def test_update_omission_and_explicit_clear_are_distinct(profile):
    client, account = profile["client"], profile["accounts"]["carrier"]
    result = await client.put("/api/users/me", headers=account["headers"],
                              json={"truck_type": "megatent", "tonnage": 24.125})
    assert result.status_code == 200, result.text
    assert (result.json()["truck_type"], result.json()["tonnage"]) == ("megatent", 24.125)
    result = await client.put("/api/users/me", headers=account["headers"], json={"city": "Tbilisi"})
    assert (result.json()["truck_type"], result.json()["tonnage"]) == ("megatent", 24.125)
    result = await client.put("/api/users/me", headers=account["headers"],
                              json={"truck_type": None, "tonnage": None})
    assert result.status_code == 200
    response = await client.get("/api/users/me", headers=account["headers"])
    assert response.json()["truck_type"] is None
    assert response.json()["tonnage"] is None
    async with profile["sessions"]() as session:
        saved = await session.get(User, account["id"])
        assert saved.truck_type is None and saved.tonnage is None


@pytest.mark.asyncio
async def test_invalid_update_cannot_partially_change_profile(profile):
    client, account = profile["client"], profile["accounts"]["carrier"]
    response = await client.put("/api/users/me", headers=account["headers"],
                                json={"city": "Should not save", "tonnage": -5})
    assert response.status_code == 422
    response = await client.get("/api/users/me", headers=account["headers"])
    assert response.json()["city"] is None
    assert response.json()["tonnage"] == 3.5


@pytest.mark.asyncio
async def test_defaults_do_not_mutate_another_account_or_public_vehicles(profile):
    client, account = profile["client"], profile["accounts"]["carrier"]
    async with profile["sessions"]() as session:
        truck = Truck(user_id=account["id"], truck_type="tent", capacity_kg=20000,
                      available_from="Tbilisi", is_available=True)
        offer = TransportOffer(user_id=account["id"], truck_type="tent", capacity_kg=20000,
                               from_city="Tbilisi", to_city="Batumi",
                               available_from=datetime.now(timezone.utc), status="active")
        session.add_all([truck, offer])
        await session.commit()
    response = await client.put("/api/users/me", headers=account["headers"],
                                json={"truck_type": "gazel", "tonnage": 1.5})
    assert response.status_code == 200, response.text
    async with profile["sessions"]() as session:
        trucks = (await session.execute(select(Truck))).scalars().all()
        offers = (await session.execute(select(TransportOffer))).scalars().all()
        assert [(row.truck_type.value, row.capacity_kg, row.is_available) for row in trucks] == [
            ("tent", 20000, True)]
        assert [(row.truck_type, row.capacity_kg, row.status) for row in offers] == [
            ("tent", 20000, "active")]
        other = await session.get(User, profile["accounts"]["other"]["id"])
        assert (other.truck_type, other.tonnage) == ("ref", 3.5)


@pytest.mark.asyncio
async def test_profile_requires_login(profile):
    response = await profile["client"].put("/api/users/me",
                                           json={"truck_type": "tent", "tonnage": 20})
    assert response.status_code in (401, 403)
