"""Real HTTP guard regressions: absent admin configuration cannot grant access."""
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.routers import admin, ads, auth, cities, loads, payments, users
from app.services.admin_auth import admin_secret_matches


class ForbiddenDatabase:
    def __getattr__(self, name):
        raise AssertionError("Denied administrative request reached the database")


@pytest_asyncio.fixture
async def guarded_client():
    app = FastAPI()
    for module, prefix in [
        (admin, ""), (ads, ""), (auth, "/api/auth"), (cities, "/api/cities"),
        (loads, "/api/loads"), (payments, ""), (users, "/api/users"),
    ]:
        app.include_router(module.router, prefix=prefix)

    async def isolated_db():
        yield ForbiddenDatabase()

    async def signed_in_user():
        return SimpleNamespace(id=1)

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[auth.require_user] = signed_in_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


ENDPOINTS = [
    ("GET", "/api/admin/stats", None),
    ("GET", "/api/admin/users", None),
    ("PATCH", "/api/admin/users/999/plan", {"plan": "free"}),
    ("GET", "/api/ads/admin/list", None),
    ("DELETE", "/api/ads/admin/999", None),
    ("POST", "/api/cities/seed", None),
    ("DELETE", "/api/loads/admin/bulk-delete", [999]),
    ("POST", "/api/loads/admin/set-status?status=active", [999]),
    ("GET", "/api/payments/admin/payments/list", None),
    ("POST", "/api/payments/admin/payments/999/activate", None),
    ("GET", "/api/auth/admin/users", None),
    ("POST", "/api/auth/admin/reset-password?email=nobody%40example.test&new_password=IsolatedPassword123!", None),
    ("POST", "/api/users/admin/999/block", None),
    ("POST", "/api/users/admin/999/unblock", None),
    ("POST", "/api/users/admin/999/verify", None),
    ("POST", "/api/users/me/plan", {"plan": "free"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [None, "", "explicit-isolated-admin-secret"])
@pytest.mark.parametrize("method,path,body", ENDPOINTS)
async def test_invalid_admin_credentials_are_denied_before_any_database_access(
    guarded_client, monkeypatch, configured, method, path, body
):
    if configured is None:
        monkeypatch.delenv("ADMIN_SECRET", raising=False)
    else:
        monkeypatch.setenv("ADMIN_SECRET", configured)
    for supplied in ("", "caucashub-admin-" + "2026", "wrong-secret", "неверный"):
        payload = dict(body, secret=supplied) if isinstance(body, dict) else body
        response = await guarded_client.request(
            method, urlsplit(path).path,
            params=dict(parse_qsl(urlsplit(path).query), secret=supplied), json=payload,
            headers=[(b"x-admin-secret", supplied.encode("utf-8"))],
        )
        assert response.status_code == 403, (method, path, response.status_code)


def test_explicit_admin_secret_only_and_runtime_rotation(monkeypatch):
    monkeypatch.delenv("ADMIN_SECRET", raising=False)
    assert not admin_secret_matches("")
    assert not admin_secret_matches("arbitrary")
    monkeypatch.setenv("ADMIN_SECRET", "isolated-ключ-one")
    assert admin_secret_matches("isolated-ключ-one")
    assert not admin_secret_matches("isolated-ключ-two")
    monkeypatch.setenv("ADMIN_SECRET", "isolated-ключ-two")
    assert not admin_secret_matches("isolated-ключ-one")
    assert admin_secret_matches("isolated-ключ-two")
    assert not admin_secret_matches(None)
