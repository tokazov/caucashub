"""Unsupported live payments cannot create records, contact banks or grant access."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.routers import auth, payments


@pytest.fixture
def inert_app(monkeypatch):
    app = FastAPI()
    app.include_router(payments.router)

    async def forbidden_dependency():
        raise AssertionError("Unsupported payment reached a database/account dependency")
        yield  # Async generator, like get_db.

    async def forbidden_action(*args, **kwargs):
        raise AssertionError("Unsupported payment attempted activation or bank access")

    app.dependency_overrides[get_db] = forbidden_dependency
    app.dependency_overrides[auth.require_user] = forbidden_dependency
    for name in ("activate_payment", "_create_tbc_payment", "_create_bog_payment", "_send_payment_email"):
        monkeypatch.setattr(payments, name, forbidden_action)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["tbc", "bog"])
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_unsigned_legacy_callback_is_inert_before_any_database_dependency(
    inert_app, monkeypatch, provider, method, enabled
):
    monkeypatch.setattr(payments, "_PAYMENTS_ENABLED", enabled)
    async with AsyncClient(transport=ASGITransport(app=inert_app), base_url="http://test") as client:
        response = await client.request(
            method, "/api/payments/callback/" + provider,
            params={"PaymentId": "forged-transaction", "status": "OK"},
            json={"event": "payment.success", "external_order_id": "1", "status": "completed"},
        )
    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["tbc", "bog"])
async def test_flag_cannot_enable_an_unverified_real_gateway(inert_app, monkeypatch, provider):
    monkeypatch.setattr(payments, "_PAYMENTS_ENABLED", True)
    async with AsyncClient(transport=ASGITransport(app=inert_app), base_url="http://test") as client:
        response = await client.post("/api/payments/create", json={"type": "plan_pro", "provider": provider})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_disabled_create_keeps_existing_unavailable_response_without_data_access(inert_app, monkeypatch):
    monkeypatch.setattr(payments, "_PAYMENTS_ENABLED", False)
    async with AsyncClient(transport=ASGITransport(app=inert_app), base_url="http://test") as client:
        response = await client.post("/api/payments/create", json={"type": "plan_pro"})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert "payment_id" not in response.json()
