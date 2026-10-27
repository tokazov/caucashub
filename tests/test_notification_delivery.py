"""Outbox claim, retry and real adapter HTTP contracts; all delivery is isolated."""
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.models.notification import NotificationDelivery
from app.models.user import User
from app.services import notification_channels as channels
from app.services import notification_delivery as worker
from tests.test_notification_inbox import (
    notification_db, add_event, notice_rows, delivery_rows,
)


def install_channels(monkeypatch, email_outcomes=None):
    calls = []
    outcomes = list(email_outcomes or [])
    async def email(to, subject, html, *, idempotency_key=None):
        calls.append(("email", to, idempotency_key, subject, html))
        if outcomes:
            return outcomes.pop(0)
        return channels.DeliveryResult("sent", provider_id="isolated-email")
    async def telegram(chat_id, text, *, idempotency_key=None):
        calls.append(("telegram", str(chat_id), idempotency_key, text))
        return channels.DeliveryResult("sent", provider_id="isolated-telegram")
    monkeypatch.setattr(channels, "send_email", email)
    monkeypatch.setattr(channels, "send_telegram", telegram)
    return calls


@pytest.mark.asyncio
async def test_committed_delivery_targets_only_recipient_and_is_not_sent_again(notification_db, monkeypatch):
    ctx = notification_db
    calls = install_channels(monkeypatch)
    await add_event(ctx)
    stats = await worker.dispatch_once(sessions=ctx["sessions"])
    assert stats["sent"] == 2
    profile = ctx["profiles"]["shipper"]
    assert Counter((call[0], call[1]) for call in calls) == {
        ("email", profile["email"]): 1, ("telegram", profile["telegram_id"]): 1,
    }
    assert all(call[2] for call in calls), "Every provider command needs a stable delivery key"
    rows = await delivery_rows(ctx)
    assert {row.status for row in rows} == {"sent"}
    assert all(row.attempts == 1 for row in rows)
    assert all(row.provider_id for row in rows)
    assert len(await notice_rows(ctx)) == 1
    await worker.dispatch_once(sessions=ctx["sessions"])
    assert len(calls) == 2
    assert all(row.attempts == 1 for row in await delivery_rows(ctx))


@pytest.mark.asyncio
async def test_waiting_for_peer_is_inbox_only(notification_db, monkeypatch):
    ctx = notification_db
    calls = install_channels(monkeypatch)
    await add_event(ctx, key="deal:7:confirmed:1:waiting",
                    kind="delivery_waiting", actor="shipper")
    assert len(await notice_rows(ctx)) == 1
    assert await delivery_rows(ctx) == []
    await worker.dispatch_once(sessions=ctx["sessions"])
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["retry", "unknown"])
async def test_retry_reuses_delivery_key_but_unknown_outcome_is_not_resent(notification_db, monkeypatch, outcome):
    ctx = notification_db
    calls = install_channels(monkeypatch, [
        channels.DeliveryResult(outcome, error="isolated failure", retry_after=2 if outcome == "retry" else None),
        channels.DeliveryResult("sent", provider_id="email-after-retry"),
    ])
    await add_event(ctx)
    await worker.dispatch_once(sessions=ctx["sessions"])
    email_row = next(row for row in await delivery_rows(ctx) if row.channel == "email")
    assert email_row.attempts == 1
    if outcome == "retry":
        assert email_row.status == "pending"
        assert email_row.next_attempt_at is not None
        async with ctx["sessions"]() as db:
            row = await db.get(NotificationDelivery, email_row.id)
            row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        await worker.dispatch_once(sessions=ctx["sessions"])
        again = next(row for row in await delivery_rows(ctx) if row.channel == "email")
        assert again.status == "sent" and again.attempts == 2
        email_calls = [call for call in calls if call[0] == "email"]
        assert len(email_calls) == 2
        assert email_calls[0][2] == email_calls[1][2]
    else:
        assert email_row.status == "unknown"
        await worker.dispatch_once(sessions=ctx["sessions"])
        assert len([call for call in calls if call[0] == "email"]) == 1
        assert next(row for row in await delivery_rows(ctx) if row.channel == "email").attempts == 1
    assert len([call for call in calls if call[0] == "telegram"]) == 1
    assert len(await notice_rows(ctx)) == 1
    await worker.dispatch_once(sessions=ctx["sessions"])
    assert all(row.status in {"sent", "unknown"} for row in await delivery_rows(ctx))


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient_state", ["pending_chat", "deleted"])
async def test_unavailable_recipient_channels_are_skipped_without_provider_calls(notification_db, monkeypatch, recipient_state):
    ctx = notification_db
    calls = install_channels(monkeypatch)
    await add_event(ctx)
    async with ctx["sessions"]() as db:
        user = await db.get(User, ctx["profiles"]["shipper"]["id"])
        if recipient_state == "pending_chat":
            user.telegram_id = "pending:unverified"
        else:
            user.is_deleted = True
        await db.commit()
    await worker.dispatch_once(sessions=ctx["sessions"])
    rows = {row.channel: row for row in await delivery_rows(ctx)}
    assert rows["telegram"].status == "skipped"
    assert not any(call[0] == "telegram" for call in calls)
    if recipient_state == "deleted":
        assert calls == []
        assert rows["email"].status == "skipped"
    else:
        assert len(calls) == 1 and calls[0][0] == "email"
        assert rows["email"].status == "sent"


@pytest.mark.asyncio
async def test_concurrent_postgresql_workers_claim_each_delivery_once(notification_db, monkeypatch):
    ctx = notification_db
    if ctx["engine"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-claim concurrency")
    calls = []
    async def send_email(to, subject, html, *, idempotency_key=None):
        calls.append(("email", to, idempotency_key))
        await asyncio.sleep(0.05)
        return channels.DeliveryResult("sent", provider_id="pg-email")
    async def send_telegram(chat_id, text, *, idempotency_key=None):
        calls.append(("telegram", str(chat_id), idempotency_key))
        await asyncio.sleep(0.05)
        return channels.DeliveryResult("sent", provider_id="pg-telegram")
    monkeypatch.setattr(channels, "send_email", send_email)
    monkeypatch.setattr(channels, "send_telegram", send_telegram)
    await add_event(ctx)
    await asyncio.gather(*[
        worker.dispatch_once(sessions=ctx["sessions"], limit=1) for _ in range(2)
    ])
    await worker.dispatch_once(sessions=ctx["sessions"])
    assert len(calls) == 2
    assert Counter(call[0] for call in calls) == {"email": 1, "telegram": 1}
    assert all(row.status == "sent" and row.attempts == 1 for row in await delivery_rows(ctx))


@pytest.mark.asyncio
async def test_expired_inflight_claim_is_unknown_instead_of_sending_twice(notification_db, monkeypatch):
    ctx = notification_db
    calls = install_channels(monkeypatch)
    await add_event(ctx)
    async with ctx["sessions"]() as db:
        rows = list((await db.execute(select(NotificationDelivery))).scalars())
        for row in rows:
            row.status = "sending"
            row.claim_token = str(uuid4())
            row.attempts = 1
            row.last_attempt_at = datetime.now(timezone.utc) - timedelta(minutes=10)
            row.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
    await worker.dispatch_once(sessions=ctx["sessions"])
    assert calls == []
    rows = await delivery_rows(ctx)
    assert all(row.status == "unknown" and row.attempts == 1 for row in rows)


@pytest.fixture
def provider_http(monkeypatch):
    # No configured secret is used by these tests, and every HTTPX client is a sink.
    for name, value in {
        "BREVO_API_KEY": "xkeysib-isolated-test", "RESEND_API_KEY": "re_isolated_test",
        "CAUCASHUB_TG_BOT_TOKEN": "123456:isolated-test-token",
        "TG_BOT_TOKEN": "", "TELEGRAM_BOT_TOKEN": "",
    }.items():
        monkeypatch.setenv(name, value)
    recorded = []
    state = {"handler": None}
    def capture(request):
        recorded.append(request)
        assert state["handler"] is not None
        return state["handler"](request)
    sink = httpx.MockTransport(capture)
    original_init = httpx.AsyncClient.__init__
    def isolated_client(client, *args, **kwargs):
        kwargs["transport"] = sink
        return original_init(client, *args, **kwargs)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", isolated_client)
    return recorded, state


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected,count", [
    ("success", "sent", 1), ("rejected", "sent", 2), ("duplicate", "sent", 1),
    ("limited", "retry", 1), ("transient", "unknown", 1),
    ("timeout", "unknown", 1), ("unconfigured", "skipped", 0),
    ("resend_only", "sent", 1),
])
async def test_email_adapter_checks_real_http_outcomes_without_unsafe_fallback(provider_http, monkeypatch, case, expected, count):
    requests, state = provider_http
    if case == "unconfigured":
        monkeypatch.setenv("BREVO_API_KEY", "")
        monkeypatch.setenv("RESEND_API_KEY", "")
    if case == "resend_only":
        monkeypatch.setenv("BREVO_API_KEY", "")
    def handler(request):
        if request.url.host == "api.resend.com":
            return httpx.Response(200, json={"id": "isolated-resend"})
        assert request.url.host == "api.brevo.com"
        if case == "timeout":
            raise httpx.ReadTimeout("isolated ambiguous outcome", request=request)
        if case == "rejected":
            return httpx.Response(401, json={"code": "unauthorized"})
        if case == "duplicate":
            return httpx.Response(400, json={"code": "duplicate_parameter"})
        if case == "limited":
            return httpx.Response(429, headers={"Retry-After": "9"}, json={"message": "busy"})
        if case == "transient":
            return httpx.Response(503, json={"message": "unavailable"})
        return httpx.Response(201, json={"messageId": "isolated-brevo"})
    state["handler"] = handler
    result = await channels.send_email(
        "shipper@example.test", "Isolated notification", "<p>Тбилиси → Батуми</p>",
        idempotency_key="11111111-1111-4111-8111-111111111142")
    assert result.status == expected
    assert len(requests) == count
    if expected == "sent" and case != "duplicate":
        assert result.provider_id
        assert any(marker in str(result.provider_id) for marker in ("isolated-brevo", "isolated-resend"))
    if case == "duplicate":
        assert result.error == "brevo_idempotent_replay"
        assert all(request.url.host == "api.brevo.com" for request in requests)
    if expected == "retry":
        assert result.retry_after is not None
        assert 0 < result.retry_after <= 1800
    if case == "limited":
        assert result.retry_after >= 9
    for request in requests:
        payload = json.loads(request.content)
        target = payload["to"]
        emails = [item["email"] for item in target] if request.url.host == "api.brevo.com" else target
        assert emails == ["shipper@example.test"]
        # Check stable provider dedup metadata without retaining auth headers.
        present = (request.headers.get("Idempotency-Key") == "11111111-1111-4111-8111-111111111142"
                   or payload.get("headers", {}).get("idempotencyKey") == "11111111-1111-4111-8111-111111111142")
        assert present
    if case in {"timeout", "limited", "transient"}:
        assert all(request.url.host == "api.brevo.com" for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected,count", [
    ("success", "sent", 1), ("api_error", "failed", 1),
    ("limited", "retry", 1), ("timeout", "unknown", 1),
    ("pending", "skipped", 0), ("unconfigured", "skipped", 0),
])
async def test_telegram_adapter_checks_body_and_connection_before_marking_sent(provider_http, monkeypatch, case, expected, count):
    requests, state = provider_http
    if case == "unconfigured":
        monkeypatch.setenv("CAUCASHUB_TG_BOT_TOKEN", "")
    def handler(request):
        assert request.url.host == "api.telegram.org"
        if case == "timeout":
            raise httpx.ReadTimeout("isolated ambiguous outcome", request=request)
        if case == "api_error":
            return httpx.Response(200, json={"ok": False, "error_code": 400, "description": "Bad Request"})
        if case == "limited":
            return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 7}})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 91}})
    state["handler"] = handler
    result = await channels.send_telegram(
        "pending:unverified" if case == "pending" else "901000001",
        "Изолированное уведомление", idempotency_key="22222222-2222-4222-8222-222222222243")
    assert result.status == expected
    assert len(requests) == count
    if case == "success":
        assert str(result.provider_id) == "91"
    if case == "limited":
        assert 7 <= result.retry_after <= 1800
    for request in requests:
        body = json.loads(request.content)
        assert str(body["chat_id"]) == "901000001"
        assert body["text"] == "Изолированное уведомление"


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["email", "telegram"])
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
async def test_pre_connection_failure_can_retry_without_cross_provider_fallback(provider_http, channel, error_type):
    requests, state = provider_http
    def unavailable(request):
        raise error_type("Isolated connection was not established", request=request)
    state["handler"] = unavailable
    if channel == "email":
        result = await channels.send_email("shipper@example.test", "Test", "<p>Test</p>",
            idempotency_key="33333333-3333-4333-8333-333333333344")
    else:
        result = await channels.send_telegram("901000001", "Test",
            idempotency_key="33333333-3333-4333-8333-333333333344")
    assert result.status == "retry" and result.retry_after == 60
    assert len(requests) == 1
    assert requests[0].url.host == ("api.brevo.com" if channel == "email" else "api.telegram.org")
