"""Persistent notification inbox contracts on disposable SQLite/PostgreSQL."""
import os
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.models.notification import Notification, NotificationDelivery
from app.models.user import User, UserRole
from app.routers import auth, notifications
from app.services.notifications import enqueue_event, render_message


EVENT_DATA = {
    "load_id": 42, "response_id": 24, "deal_id": 7,
    "deal_number": "CH-2026-0007",
    "from_city": "Тбилиси", "to_city": "Батуми",
    "price": 500, "currency": "GEL",
}


@pytest_asyncio.fixture(params=[
    "sqlite",
    pytest.param("postgresql", marks=pytest.mark.skipif(
        not os.environ.get("TEST_POSTGRES_URL"), reason="requires isolated CI PostgreSQL")),
])
async def notification_db(request, tmp_path, monkeypatch):
    schema = "test_notification_" + uuid4().hex
    bootstrap = None
    if request.param == "postgresql":
        url = os.environ["TEST_POSTGRES_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
        bootstrap = create_async_engine(url)
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'notifications.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def isolated_db():
        async with sessions() as db:
            yield db

    # Enqueue/inbox tests must not perform provider I/O, even if production code
    # catches an adapter exception. Worker tests patch the channel boundary.
    unexpected = []
    original_init = httpx.AsyncClient.__init__
    def blocked_provider(request):
        unexpected.append(request.url.host)
        raise AssertionError("Provider HTTP is forbidden in notification DB tests")
    sink = httpx.MockTransport(blocked_provider)
    def isolated_client(client, *args, **kwargs):
        if not isinstance(kwargs.get("transport"), ASGITransport):
            kwargs["transport"] = sink
        return original_init(client, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", isolated_client)

    app = FastAPI()
    app.include_router(notifications.router)
    app.dependency_overrides[get_db] = isolated_db
    profiles = {}
    async with sessions() as db:
        for index, role in enumerate(("shipper", "carrier", "outsider"), 1):
            user = User(
                email=f"{role}@example.test", hashed_password="not-used-by-token-auth",
                company_name=f"Isolated {role}", phone=f"+99559993000{index}",
                role=UserRole.carrier if role == "carrier" else UserRole.shipper,
                telegram_id=str(901000000 + index), lang="ge" if role == "carrier" else "ru",
                is_active=True, is_deleted=False,
            )
            db.add(user)
            await db.flush()
            profiles[role] = {
                "id": user.id, "email": user.email, "phone": user.phone,
                "telegram_id": user.telegram_id, "lang": user.lang,
            }
        await db.commit()
    headers = {role: {"Authorization": "Bearer " + auth.create_token(profile["id"])}
               for role, profile in profiles.items()}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            yield {"client": client, "sessions": sessions, "engine": engine,
                   "profiles": profiles, "headers": headers}
    finally:
        await engine.dispose()
        if bootstrap:
            async with bootstrap.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await bootstrap.dispose()
    assert unexpected == [], "Unexpected HTTP provider calls were swallowed by application code"


async def add_event(context, key="response:24:created", kind="new_response",
                    recipients=("shipper",), actor="carrier", data=None):
    async with context["sessions"]() as db:
        await enqueue_event(
            db, event_key=key, kind=kind,
            recipient_ids=[context["profiles"][role]["id"] for role in recipients],
            actor_id=context["profiles"][actor]["id"] if actor else None,
            data={**EVENT_DATA, **(data or {})},
        )
        await db.commit()
    return await notice_rows(context, key)


async def notice_rows(context, key=None):
    async with context["sessions"]() as db:
        query = select(Notification).order_by(Notification.id)
        if key is not None:
            query = query.where(Notification.event_key == key)
        return list((await db.execute(query)).scalars())


async def delivery_rows(context):
    async with context["sessions"]() as db:
        return list((await db.execute(
            select(NotificationDelivery).order_by(NotificationDelivery.id))).scalars())


@pytest.mark.asyncio
async def test_enqueue_deduplicates_recipients_and_replayed_event_without_committing(notification_db):
    ctx = notification_db
    ids = [ctx["profiles"][role]["id"] for role in ("shipper", "shipper", "carrier")]
    async with ctx["sessions"]() as db:
        for _ in range(2):
            await enqueue_event(db, event_key="deal:7:created", kind="deal_created",
                                recipient_ids=ids, actor_id=ids[0], data=EVENT_DATA)
        await db.commit()
    notices = await notice_rows(ctx)
    assert len(notices) == 2
    assert {row.recipient_id for row in notices} == set(ids)
    assert len(await delivery_rows(ctx)) == 4
    assert len({(row.notification_id, row.channel) for row in await delivery_rows(ctx)}) == 4


@pytest.mark.asyncio
async def test_enqueue_is_atomic_with_its_callers_transaction(notification_db):
    ctx = notification_db
    async with ctx["sessions"]() as db:
        await enqueue_event(db, event_key="response:24:rolled-back", kind="new_response",
                            recipient_ids=[ctx["profiles"]["shipper"]["id"]],
                            actor_id=ctx["profiles"]["carrier"]["id"], data=EVENT_DATA)
        await db.rollback()
    assert await notice_rows(ctx) == []
    assert await delivery_rows(ctx) == []


@pytest.mark.asyncio
async def test_inbox_returns_only_the_authenticated_recipient(notification_db):
    ctx = notification_db
    own = await add_event(ctx, "response:24:created", data={
        "phone": "+995599999999", "email": "private@example.test",
        "message": "private-response-body",
    })
    await add_event(ctx, "transport_request:25:created", kind="new_transport_request",
                    recipients=("carrier",), actor="shipper")
    response = await ctx["client"].get("/api/notifications",
        headers=ctx["headers"]["shipper"],
        params={"recipient_id": ctx["profiles"]["carrier"]["id"]})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == data["unread_count"] == 1
    assert [row["id"] for row in data["notifications"]] == [own[0].id]
    assert data["notifications"][0]["type"] == "new_response"
    assert data["notifications"][0]["data"]["load_id"] == 42
    assert "phone" not in own[0].data and "email" not in own[0].data and "message" not in own[0].data
    assert "+995599999999" not in response.text
    assert "private@example.test" not in response.text
    assert "private-response-body" not in response.text
    outsider = await ctx["client"].get("/api/notifications", headers=ctx["headers"]["outsider"])
    assert outsider.status_code == 200
    assert outsider.json()["notifications"] == []
    assert outsider.json()["unread_count"] == outsider.json()["total"] == 0


@pytest.mark.asyncio
async def test_inbox_requires_valid_active_user_authentication(notification_db):
    ctx = notification_db
    anonymous = await ctx["client"].get("/api/notifications")
    assert anonymous.status_code in (401, 403)
    invalid = await ctx["client"].get("/api/notifications",
        headers={"Authorization": "Bearer invalid-token"})
    assert invalid.status_code == 401
    async with ctx["sessions"]() as db:
        user = await db.get(User, ctx["profiles"]["shipper"]["id"])
        user.is_deleted = True
        await db.commit()
    deleted = await ctx["client"].get("/api/notifications", headers=ctx["headers"]["shipper"])
    assert deleted.status_code == 401


@pytest.mark.asyncio
async def test_mark_read_is_owned_idempotent_and_persistent(notification_db):
    ctx = notification_db
    notice = (await add_event(ctx))[0]
    url = f"/api/notifications/{notice.id}/read"
    foreign = await ctx["client"].post(url, headers=ctx["headers"]["carrier"])
    assert foreign.status_code == 404
    before = await ctx["client"].get("/api/notifications", headers=ctx["headers"]["shipper"])
    assert before.json()["unread_count"] == 1
    first = await ctx["client"].post(url, headers=ctx["headers"]["shipper"])
    assert first.status_code == 200, first.text
    read_at = (await notice_rows(ctx))[0].read_at
    assert read_at is not None
    second = await ctx["client"].post(url, headers=ctx["headers"]["shipper"])
    assert second.status_code == 200
    assert (await notice_rows(ctx))[0].read_at == read_at
    refreshed = await ctx["client"].get("/api/notifications", headers=ctx["headers"]["shipper"])
    assert refreshed.json()["unread_count"] == 0
    assert refreshed.json()["notifications"][0]["read_at"] is not None


@pytest.mark.asyncio
async def test_mark_all_read_preserves_other_recipients_and_pagination_totals(notification_db):
    ctx = notification_db
    for index in range(3):
        await add_event(ctx, f"response:{index}:created")
    other = (await add_event(ctx, "transport_request:30:created",
                            kind="new_transport_request", recipients=("carrier",)))[0]
    page = await ctx["client"].get("/api/notifications?limit=1&offset=1",
                                  headers=ctx["headers"]["shipper"])
    assert page.status_code == 200
    assert len(page.json()["notifications"]) == 1
    assert page.json()["total"] == page.json()["unread_count"] == 3
    response = await ctx["client"].post("/api/notifications/read-all",
                                       headers=ctx["headers"]["shipper"])
    assert response.status_code == 200, response.text
    own = await ctx["client"].get("/api/notifications", headers=ctx["headers"]["shipper"])
    peer = await ctx["client"].get("/api/notifications", headers=ctx["headers"]["carrier"])
    assert own.json()["unread_count"] == 0
    assert peer.json()["unread_count"] == 1
    assert peer.json()["notifications"][0]["id"] == other.id
    assert peer.json()["notifications"][0]["read_at"] is None


@pytest.mark.asyncio
async def test_inbox_rejects_invalid_pagination(notification_db):
    ctx = notification_db
    for query in ("limit=0", "limit=1000", "offset=-1"):
        response = await ctx["client"].get("/api/notifications?" + query,
                                           headers=ctx["headers"]["shipper"])
        assert response.status_code == 422, response.text


@pytest.mark.parametrize("language,georgian", [("ru", False), ("ge", True), ("ka", True)])
def test_provider_messages_use_neutral_metadata_and_safe_localized_html(language, georgian):
    from types import SimpleNamespace
    notification = SimpleNamespace(kind="new_response", data={
        **EVENT_DATA, "from_city": "<b>Тбилиси</b>", "phone": "+995599999999",
        "email": "private@example.test", "message": "private-response-body",
    })
    message = render_message(notification, language, actor_name="<img src=x onerror=bad>")
    assert "<img" not in message["html"] and "<b>Тбилиси" not in message["html"]
    assert "&lt;img" in message["html"] and "&lt;b&gt;" in message["html"]
    assert "+995599999999" not in str(message)
    assert "private@example.test" not in str(message)
    assert "private-response-body" not in str(message)
    if georgian:
        assert any("\u10a0" <= char <= "\u10ff" for char in message["subject"])
    else:
        assert "Новый отклик" in message["subject"]
