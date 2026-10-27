"""Password recovery/change through isolated real HTTP routers; email is a sink."""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import event, select, update

from app.config import settings
from app.models.deal import Deal, DealStatus
from app.models.user import ResetCode, User
from app.routers import auth, tg_bot, users
from app.services import notification_channels
from app.services.notification_channels import DeliveryResult
from tests.test_publication_journeys import cargo, journey  # noqa: F401


pytestmark = pytest.mark.asyncio
ORIGINAL = "JourneyTest39!"
CHANGED = "RecoveredAccess84!"
OTHER = "AlternativeAccess85!"


@pytest_asyncio.fixture
async def access(journey, monkeypatch):
    app = journey["client"]._transport.app
    if not any(route.path == "/api/users/me" for route in app.routes):
        app.include_router(users.router, prefix="/api/users")
    if not any(route.path == "/api/tg/generate-link" for route in app.routes):
        app.include_router(tg_bot.router, prefix="/api/tg")
    mail = AsyncMock(return_value=DeliveryResult("sent", provider_id="synthetic-email"))
    monkeypatch.setattr(notification_channels, "send_email", mail)
    auth._login_attempts.clear()
    users._phone_change_codes.clear()
    yield {**journey, "mail": mail}
    users._phone_change_codes.clear()
    auth._login_attempts.clear()


async def get_user(context, role="shipper"):
    async with context["sessions"]() as db:
        return (await db.execute(select(User).where(User.email == f"{role}@example.test"))).scalar_one()


async def reset_rows(context):
    async with context["sessions"]() as db:
        return (await db.execute(select(ResetCode).order_by(ResetCode.id))).scalars().all()


async def request_code(context, email="shipper@example.test"):
    response = await context["client"].post("/api/auth/forgot-password", json={"email": email})
    assert response.status_code == 200, response.text
    args = context["mail"].await_args.args
    assert args[0] == email.strip().lower()
    match = re.search(r"(?<![0-9])[0-9]{6}(?![0-9])", args[2])
    assert match, "The synthetic email must contain the real six-digit code"
    return match.group()


async def login(context, password=ORIGINAL):
    return await context["client"].post("/api/auth/login",
        json={"email": " SHIPPER@example.test ", "password": password})


async def reset(context, code, password=CHANGED):
    return await context["client"].post("/api/auth/reset-password",
        json={"email": " SHIPPER@example.test ", "code": code, "new_password": password})


def bearer(token):
    return {"Authorization": "Bearer " + token}


async def protected_me(context, headers):
    return await context["client"].get("/api/users/me", headers=headers)


async def test_recovery_is_hashed_single_use_and_revokes_api_pdf_and_pending_tg_link(access):
    code = await request_code(access, " SHIPPER@example.test ")
    rows = await reset_rows(access)
    assert len(rows) == 1
    assert rows[0].code.startswith("h1.") and rows[0].code != code
    assert auth._reset_matches("shipper@example.test", code, rows[0].code)
    assert rows[0].attempts == 0 and rows[0].request_count == 1
    account = await get_user(access)
    async with access["sessions"]() as db:
        await db.execute(update(User).where(User.id == account.id).values(telegram_id="pending:synthetic-link"))
        await db.commit()
    listing = await access["client"].post("/api/loads/", headers=access["headers"]["shipper"], json=cargo())
    assert listing.status_code == 200, listing.text
    carrier = await get_user(access, "carrier")
    async with access["sessions"]() as db:
        deal = Deal(load_id=listing.json()["id"], shipper_id=account.id, carrier_id=carrier.id,
                    status=DealStatus.completed, act_number="ACCESS-TEST-ACT")
        db.add(deal)
        await db.commit()
        deal_id = deal.id
    users._phone_change_codes[account.id] = {"new_phone": "+995599999999", "code": "123456"}
    response = await reset(access, code)
    assert response.status_code == 200, response.text
    assert await reset_rows(access) == []
    assert account.id not in users._phone_change_codes
    changed = await get_user(access)
    assert changed.telegram_id is None and changed.password_version == 1
    assert auth._verify_password(CHANGED, changed.hashed_password)
    assert (await reset(access, code, OTHER)).status_code == 400
    assert (await login(access, ORIGINAL)).status_code == 401
    headers = access["headers"]["shipper"]
    assert (await protected_me(access, headers)).status_code == 401
    assert (await access["client"].post("/api/tg/generate-link", headers=headers)).status_code == 401
    stale = headers["Authorization"].removeprefix("Bearer ")
    for kwargs in [{"headers": headers}, {"params": {"token": stale}}]:
        denied = await access["client"].get(f"/api/deals/{deal_id}/act.pdf", **kwargs)
        assert denied.status_code == 401, denied.text
    fresh = await login(access, CHANGED)
    assert fresh.status_code == 200, fresh.text
    assert (await protected_me(access, bearer(fresh.json()["token"]))).status_code == 200
    assert access["mail"].await_count == 2
    assert all(call.args[0] == "shipper@example.test" for call in access["mail"].await_args_list)


async def test_change_revokes_same_second_token_but_new_login_works_and_bound_tg_survives(access, monkeypatch):
    now = datetime.now(timezone.utc).replace(microsecond=500000)
    monkeypatch.setattr(auth, "_utcnow", lambda: now)
    account = await get_user(access)
    async with access["sessions"]() as db:
        await db.execute(update(User).where(User.id == account.id).values(telegram_id="123456789"))
        await db.commit()
    code = await request_code(access)
    old_login = await login(access)
    old_token = old_login.json()["token"]
    wrong = await access["client"].post("/api/auth/change-password", headers=bearer(old_token),
        json={"old_password": "WrongExistingPassword!", "new_password": CHANGED})
    assert wrong.status_code == 400
    assert (await protected_me(access, bearer(old_token))).status_code == 200
    changed = await access["client"].post("/api/auth/change-password", headers=bearer(old_token),
        json={"old_password": ORIGINAL, "new_password": CHANGED})
    assert changed.status_code == 200, changed.text
    assert (await protected_me(access, bearer(old_token))).status_code == 401
    assert (await reset(access, code, OTHER)).status_code == 400
    fresh = await login(access, CHANGED)
    assert fresh.status_code == 200, fresh.text
    new_token = fresh.json()["token"]
    decode = lambda value: jwt.decode(value, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert decode(old_token)["iat"] == decode(new_token)["iat"]
    assert decode(new_token)["ver"] == 1
    assert (await protected_me(access, bearer(new_token))).status_code == 200
    assert (await get_user(access)).telegram_id == "123456789"


async def test_legacy_token_stays_valid_until_password_change_even_after_old_same_second_change(access):
    account = await get_user(access)
    old_change = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with access["sessions"]() as db:
        await db.execute(update(User).where(User.id == account.id).values(
            password_changed_at=old_change, password_version=0))
        await db.commit()
    legacy = jwt.encode({"sub": str(account.id), "iat": int(old_change.timestamp()),
                         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                        settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    assert (await protected_me(access, bearer(legacy))).status_code == 200
    changed = await access["client"].post("/api/auth/change-password", headers=bearer(legacy),
        json={"old_password": ORIGINAL, "new_password": CHANGED})
    assert changed.status_code == 200, changed.text
    assert (await protected_me(access, bearer(legacy))).status_code == 401


async def test_five_bad_codes_exhaust_persistent_budget_across_limiter_resets(access):
    code = await request_code(access)
    wrong = "000000" if code != "000000" else "999999"
    for _ in range(5):
        auth._login_attempts.clear()  # Simulate requests routed to different workers.
        response = await reset(access, wrong)
        assert response.status_code == 400, response.text
    auth._login_attempts.clear()
    assert (await reset(access, code)).status_code == 400
    rows = await reset_rows(access)
    assert len(rows) == 1 and rows[0].attempts == 5
    assert auth._verify_password(ORIGINAL, (await get_user(access)).hashed_password)
    assert (await protected_me(access, access["headers"]["shipper"])).status_code == 200


async def test_resends_have_cooldown_window_budget_and_do_not_extend_expiry(access, monkeypatch):
    now = [datetime.now(timezone.utc)]
    sequence = iter([111111, 222222, 333333, 444444])
    monkeypatch.setattr(auth, "_utcnow", lambda: now[0])
    monkeypatch.setattr(auth.secrets, "randbelow", lambda upper: next(sequence))
    first_code = await request_code(access)
    assert (await reset(access, "000000")).status_code == 400
    first = (await reset_rows(access))[0]
    original_expiry = first.expires_at
    for step in range(1, 4):
        auth._login_attempts.clear()
        # First immediate duplicate must not send another email.
        response = await access["client"].post("/api/auth/forgot-password",
                                               json={"email": "shipper@example.test"})
        assert response.status_code == 200
        if step == 1:
            assert access["mail"].await_count == 1
        now[0] += timedelta(seconds=61)
        auth._login_attempts.clear()
        response = await access["client"].post("/api/auth/forgot-password",
                                               json={"email": "shipper@example.test"})
        assert response.status_code == 200
    row = (await reset_rows(access))[0]
    assert access["mail"].await_count == 3 and row.request_count == 3 and row.attempts == 1
    assert row.expires_at == original_expiry
    assert (await reset(access, first_code)).status_code == 400
    now[0] += timedelta(minutes=16)
    auth._login_attempts.clear()
    await request_code(access)
    row = (await reset_rows(access))[0]
    assert access["mail"].await_count == 4 and row.request_count == 1 and row.attempts == 0


@pytest.mark.parametrize("state", ["unknown", "blocked", "deleted"])
async def test_forgot_noneligible_accounts_have_same_public_response_and_no_email(access, state):
    known = await access["client"].post("/api/auth/forgot-password", json={"email": "absent@example.test"})
    if state != "unknown":
        account = await get_user(access)
        async with access["sessions"]() as db:
            values = {"is_active": False} if state == "blocked" else {"is_deleted": True}
            await db.execute(update(User).where(User.id == account.id).values(**values))
            await db.commit()
    email = "absent@example.test" if state == "unknown" else "shipper@example.test"
    response = await access["client"].post("/api/auth/forgot-password", json={"email": email})
    assert response.status_code == 200 and response.json() == known.json()
    assert await reset_rows(access) == []
    access["mail"].assert_not_awaited()


async def test_expired_and_weak_password_do_not_change_account(access):
    code = await request_code(access)
    weak = await reset(access, code, "12345678")
    assert weak.status_code == 422
    assert (await protected_me(access, access["headers"]["shipper"])).status_code == 200
    async with access["sessions"]() as db:
        await db.execute(update(ResetCode).values(expires_at=datetime.utcnow() - timedelta(seconds=1)))
        await db.commit()
    assert (await reset(access, code)).status_code == 400
    account = await get_user(access)
    assert account.password_version == 0 and auth._verify_password(ORIGINAL, account.hashed_password)


@pytest.mark.parametrize("iat", [None, True, "123", float("nan")])
async def test_missing_or_invalid_jwt_issue_time_is_rejected(access, iat):
    account = await get_user(access)
    payload = {"sub": str(account.id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    if iat is not None:
        payload["iat"] = iat
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    assert (await protected_me(access, bearer(token))).status_code == 401


async def test_admin_password_reset_fails_closed_and_revokes_sessions(access, monkeypatch):
    account = await get_user(access)
    monkeypatch.delenv("ADMIN_SECRET", raising=False)
    denied = await access["client"].post("/api/auth/admin/reset-password",
        params={"email": account.email, "new_password": CHANGED, "secret": "unconfigured"})
    assert denied.status_code == 403
    monkeypatch.setenv("ADMIN_SECRET", "synthetic-isolated-admin-secret")
    response = await access["client"].post("/api/auth/admin/reset-password", params={
        "email": account.email, "new_password": CHANGED, "secret": "synthetic-isolated-admin-secret"})
    assert response.status_code == 200, response.text
    assert (await protected_me(access, access["headers"]["shipper"])).status_code == 401
    assert (await login(access, CHANGED)).status_code == 200


async def test_parallel_postgresql_recovery_consumes_code_once(access):
    if access["engine"].dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    code = await request_code(access)
    responses = await asyncio.wait_for(asyncio.gather(
        reset(access, code, CHANGED), reset(access, code, OTHER)), timeout=20)
    assert sorted(response.status_code for response in responses) == [200, 400], [r.text for r in responses]
    winning = CHANGED if responses[0].status_code == 200 else OTHER
    losing = OTHER if winning == CHANGED else CHANGED
    account = await get_user(access)
    assert account.password_version == 1 and auth._verify_password(winning, account.hashed_password)
    assert not auth._verify_password(losing, account.hashed_password)
    assert await reset_rows(access) == [] and access["mail"].await_count == 2


async def test_parallel_postgresql_changes_revalidate_token_after_user_lock(access):
    if access["engine"].dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    async def change(password):
        return await access["client"].post("/api/auth/change-password", headers=access["headers"]["shipper"],
            json={"old_password": ORIGINAL, "new_password": password})
    responses = await asyncio.wait_for(asyncio.gather(change(CHANGED), change(OTHER)), timeout=20)
    assert sorted(response.status_code for response in responses) == [200, 401], [r.text for r in responses]
    assert (await get_user(access)).password_version == 1 and access["mail"].await_count == 1


@pytest.mark.parametrize("delivery_status", ["failed", "unknown", "retry", "skipped"])
async def test_delivery_failure_keeps_public_response_generic_without_secret_logs(access, caplog, delivery_status):
    access["mail"].return_value = DeliveryResult(delivery_status, error="synthetic_delivery_error")
    known = await access["client"].post("/api/auth/forgot-password", json={"email": "shipper@example.test"})
    unknown = await access["client"].post("/api/auth/forgot-password", json={"email": "unknown@example.test"})
    assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json()
    access["mail"].assert_awaited_once()
    rows = await reset_rows(access)
    assert len(rows) == 1 and rows[0].code.startswith("h1.")
    delivered_code = re.search(r"(?<![0-9])[0-9]{6}(?![0-9])", access["mail"].await_args.args[2]).group()
    assert delivered_code not in caplog.text and "shipper@example.test" not in caplog.text


async def test_password_write_failure_preserves_old_credentials_code_and_session(access):
    code = await request_code(access)
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE USERS"):
            raise RuntimeError("Synthetic password write failure")
    event.listen(access["engine"].sync_engine, "before_cursor_execute", fail)
    try:
        response = await reset(access, code)
        assert response.status_code == 500, response.text
    finally:
        event.remove(access["engine"].sync_engine, "before_cursor_execute", fail)
    account = await get_user(access)
    assert account.password_version == 0 and auth._verify_password(ORIGINAL, account.hashed_password)
    assert len(await reset_rows(access)) == 1
    assert (await protected_me(access, access["headers"]["shipper"])).status_code == 200
    access["mail"].assert_awaited_once()
    assert (await reset(access, code)).status_code == 200


@pytest.mark.parametrize("new_password", ["x" * 73, "პ" * 25])
async def test_new_password_cannot_silently_truncate_at_bcrypt_byte_limit(access, new_password):
    code = await request_code(access)
    response = await reset(access, code, new_password)
    assert response.status_code == 422
    assert (await get_user(access)).password_version == 0
    assert len(await reset_rows(access)) == 1


async def test_legacy_long_sha256_password_login_does_not_truncate_or_upgrade_to_bcrypt(access):
    original = "Legacy-პაროლი-" * 8
    assert len(original.encode("utf-8")) > 72
    encoded = auth.pwd_context.hash(original, scheme="sha256_crypt")
    account = await get_user(access)
    async with access["sessions"]() as db:
        await db.execute(update(User).where(User.id == account.id).values(hashed_password=encoded))
        await db.commit()
    logged_in = await login(access, original)
    assert logged_in.status_code == 200, logged_in.text
    assert (await protected_me(access, bearer(logged_in.json()["token"]))).status_code == 200
    unchanged = await get_user(access)
    assert unchanged.hashed_password == encoded and unchanged.password_version == 0
    assert (await login(access, original[:20])).status_code == 401
    access["mail"].assert_not_awaited()
