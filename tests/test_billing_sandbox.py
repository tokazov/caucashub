"""Isolated payment state, time boundaries, ownership and concurrent delivery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import uuid

import pytest
from httpx import ASGITransport, AsyncBaseTransport, AsyncClient

from app.billing_sandbox.core import BillingError, SandboxBilling
from app.billing_sandbox.api import create_app


SECRET = b"isolated-simulator-test-key-not-a-bank-credential"
REPOSITORY = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A sandbox operation attempted a network connection")
    original_connect = socket.socket.connect

    def local_only(sock, address):
        # Windows' asyncio socketpair may use a loopback connection internally.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost"):
            return original_connect(sock, address)
        if hasattr(socket, "AF_UNIX") and sock.family == socket.AF_UNIX:
            return original_connect(sock, address)
        return forbidden()

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", local_only)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def billing(tmp_path, clock):
    return SandboxBilling(tmp_path / "billing.sandbox.sqlite3", clock=clock,
                          signing_secret=SECRET)


def create(billing, product="pro", *, customer="alice", target=None, key=None):
    return billing.create_order(customer, product, key or uuid.uuid4().hex,
                                target_id=target)


def deliver(billing, order, outcome="paid", customer="alice"):
    raw, signature = billing.make_event(customer, order["id"], outcome)
    return billing.accept_event(raw, signature)


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sign(event):
    raw = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    return raw, hmac.new(SECRET, raw, hashlib.sha256).hexdigest()


def test_core_has_no_production_database_import():
    code = (
        "import sys; import app.billing_sandbox.core; "
        "assert 'app.database' not in sys.modules; "
        "assert 'app.models.user' not in sys.modules; "
        "assert 'app.models.load' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], cwd=REPOSITORY,
                   check=True, capture_output=True, timeout=15)


@pytest.mark.parametrize("name", ["production.sqlite3", "billing.db", ":memory:",
                                   "postgresql://forbidden.invalid/database"])
def test_storage_rejects_non_sandbox_locations(tmp_path, name):
    location = name if ":" in name else tmp_path / name
    with pytest.raises((ValueError, BillingError)):
        SandboxBilling(location, signing_secret=SECRET)
    if ":" not in name:
        assert not (tmp_path / name).exists()


def test_existing_real_user_tables_are_never_modified(tmp_path):
    path = tmp_path / "unrelated.sandbox.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE users (plan TEXT); INSERT INTO users VALUES ('free');"
                         "CREATE TABLE loads (is_boosted INTEGER); INSERT INTO loads VALUES (0);")
    before = path.read_bytes()
    with pytest.raises((ValueError, BillingError)):
        SandboxBilling(path, signing_secret=SECRET)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT plan FROM users").fetchone() == ("free",)
        assert db.execute("SELECT is_boosted FROM loads").fetchone() == (0,)


def test_order_uses_catalog_price_and_disabled_business_cannot_be_bought(billing):
    order = create(billing)
    assert (order["amount_tetri"], order["currency"], order["status"]) == (4900, "GEL", "pending")
    assert order["project"] == "caucashub"
    with pytest.raises(BillingError) as error:
        create(billing, "business")
    assert error.value.status_code == 409
    assert len(billing.list_orders("alice")) == 1


def test_create_idempotency_is_scoped_to_customer_and_rejects_changed_purchase(billing):
    first = create(billing, key="same-intent")
    retry = create(billing, key="same-intent")
    assert retry["id"] == first["id"]
    with pytest.raises(BillingError) as error:
        create(billing, "promote_24h", target="alice-load", key="same-intent")
    assert error.value.status_code == 409
    other = create(billing, customer="bob", key="same-intent")
    assert other["id"] != first["id"]
    assert len(billing.list_orders("alice")) == len(billing.list_orders("bob")) == 1


def test_concurrent_checkout_retries_create_one_pending_order(billing):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: create(billing, key="parallel-checkout"), range(12)))
    assert len({result["id"] for result in results}) == 1
    assert len(billing.list_orders("alice")) == 1


def test_another_customer_cannot_read_or_simulate_the_order(billing):
    order = create(billing)
    for action in [lambda: billing.get_order("bob", order["id"]),
                   lambda: billing.make_event("bob", order["id"], "paid")]:
        with pytest.raises(BillingError) as error:
            action()
        assert error.value.status_code == 404
    assert billing.list_grants("alice") == []


@pytest.mark.parametrize("target", ["bob-load", "missing-load", "expired-load", None])
def test_boost_requires_an_owned_eligible_target(billing, target):
    with pytest.raises(BillingError):
        create(billing, "promote_24h", target=target)
    assert billing.list_orders("alice") == []


def test_invalid_signature_cannot_turn_a_pending_order_into_a_grant(billing):
    order = create(billing)
    raw, signature = billing.make_event("alice", order["id"], "paid")
    with pytest.raises(BillingError) as error:
        billing.accept_event(raw, "0" * len(signature))
    assert error.value.status_code in (400, 401, 403)
    assert billing.get_order("alice", order["id"])["status"] == "pending"
    assert billing.list_grants("alice") == []


@pytest.mark.parametrize("field,value", [("amount_tetri", 1), ("currency", "USD"),
                                         ("provider_tx_id", "another-transaction"),
                                         ("project", "techrent")])
def test_even_signed_notifications_must_match_the_order_snapshot(billing, field, value):
    order = create(billing)
    raw, _ = billing.make_event("alice", order["id"], "paid")
    event = json.loads(raw)
    event[field] = value
    with pytest.raises(BillingError):
        billing.accept_event(*sign(event))
    assert billing.get_order("alice", order["id"])["status"] == "pending"
    assert billing.list_grants("alice") == []


def test_duplicate_and_concurrent_delivery_create_exactly_one_grant(billing, clock):
    order = create(billing)
    raw, signature = billing.make_event("alice", order["id"], "paid")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: billing.accept_event(raw, signature), range(12)))
    assert {result["status"] for result in results} == {"paid"}
    grants = billing.list_grants("alice")
    assert len(grants) == 1
    assert instant(grants[0]["starts_at"]) == clock()
    assert instant(grants[0]["ends_at"]) == clock() + timedelta(days=30)
    deliver(billing, order)  # A new event ID for the same paid order is also a no-op.
    assert billing.list_grants("alice") == grants


def test_reusing_event_id_for_a_different_transition_is_rejected(billing):
    order = create(billing)
    raw, signature = billing.make_event("alice", order["id"], "paid")
    billing.accept_event(raw, signature)
    changed = json.loads(raw)
    changed["outcome"] = "refunded"
    with pytest.raises(BillingError) as error:
        billing.accept_event(*sign(changed))
    assert error.value.status_code == 409
    assert billing.get_order("alice", order["id"])["status"] == "paid"
    assert billing.list_grants("alice")[0]["active"] is True


def test_failed_transaction_rolls_back_grant_and_allows_same_notification_retry(tmp_path, clock):
    path = tmp_path / "rollback.sandbox.sqlite3"
    billing = SandboxBilling(path, clock=clock, signing_secret=SECRET)
    order = create(billing)
    raw, signature = billing.make_event("alice", order["id"], "paid")
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TRIGGER reject_paid BEFORE UPDATE OF status ON sb_orders
            WHEN NEW.status = 'paid'
            BEGIN SELECT RAISE(ABORT, 'injected state write failure'); END;
        """)
    with pytest.raises(sqlite3.DatabaseError):
        billing.accept_event(raw, signature)
    assert billing.get_order("alice", order["id"])["status"] == "pending"
    assert billing.list_grants("alice") == []
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM sb_events").fetchone()[0] == 0
        db.execute("DROP TRIGGER reject_paid")
    assert billing.accept_event(raw, signature)["status"] == "paid"
    assert len(billing.list_grants("alice")) == 1


def test_parallel_distinct_renewals_are_serialized_without_losing_a_period(billing, clock):
    orders = [create(billing), create(billing)]
    events = [billing.make_event("alice", order["id"], "paid") for order in orders]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda event: billing.accept_event(*event), events))
    grants = sorted(billing.list_grants("alice"), key=lambda grant: grant["starts_at"])
    assert len(grants) == 2
    assert instant(grants[0]["starts_at"]) == clock()
    assert grants[0]["ends_at"] == grants[1]["starts_at"]
    assert instant(grants[1]["ends_at"]) == clock() + timedelta(days=60)
    assert sum(grant["active"] for grant in grants) == 1


def test_early_renewal_and_exact_expiry_boundary(billing, clock):
    first = create(billing)
    deliver(billing, first)
    clock.advance(days=10)
    deliver(billing, create(billing))
    clock.advance(days=20)
    grants = sorted(billing.list_grants("alice"), key=lambda grant: grant["starts_at"])
    assert grants[0]["active"] is False
    assert grants[1]["active"] is True
    assert instant(grants[1]["ends_at"]) == clock() + timedelta(days=30)
    clock.advance(days=30)
    assert not any(grant["active"] for grant in billing.list_grants("alice"))


@pytest.mark.parametrize("product,hours,price", [("promote_24h", 24, 500),
                                               ("promote_72h", 72, 1200),
                                               ("promote_168h", 168, 2500)])
def test_each_boost_has_its_purchased_duration(billing, clock, product, hours, price):
    order = create(billing, product, target="alice-load")
    assert order["amount_tetri"] == price
    deliver(billing, order)
    grant = billing.list_grants("alice")[0]
    assert instant(grant["ends_at"]) - instant(grant["starts_at"]) == timedelta(hours=hours)
    clock.advance(hours=hours)
    assert billing.list_grants("alice")[0]["active"] is False


@pytest.mark.parametrize("outcome", ["failed", "cancelled", "expired"])
def test_unsuccessful_payment_never_issues_access(billing, outcome):
    order = create(billing)
    result = deliver(billing, order, outcome)
    assert result["status"] == outcome
    assert billing.list_grants("alice") == []
    with pytest.raises(BillingError):
        deliver(billing, order, "paid")
    assert billing.list_grants("alice") == []


def test_paid_target_that_expired_during_checkout_is_recorded_for_review_and_refund(billing, clock):
    order = create(billing, "promote_24h", target="alice-load")
    target = next(target for target in billing.list_targets("alice") if target["id"] == "alice-load")
    clock.value = instant(target["valid_until"]) + timedelta(seconds=1)
    result = deliver(billing, order)
    assert result["status"] == "paid"
    assert result["fulfillment_status"] == "needs_review"
    assert billing.list_grants("alice") == []
    assert deliver(billing, order, "refunded")["status"] == "refunded"


def test_refund_only_latest_renewal_prevents_holes_and_never_reactivates_it(billing):
    first, second = create(billing), create(billing)
    deliver(billing, first)
    deliver(billing, second)
    with pytest.raises(BillingError) as error:
        deliver(billing, first, "refunded")
    assert error.value.status_code == 409
    assert deliver(billing, second, "refunded")["status"] == "refunded"
    assert deliver(billing, first, "refunded")["status"] == "refunded"
    assert not any(grant["active"] for grant in billing.list_grants("alice"))
    with pytest.raises(BillingError):
        deliver(billing, second, "paid")
    assert not any(grant["active"] for grant in billing.list_grants("alice"))


def test_orders_and_idempotency_survive_a_process_restart(tmp_path, clock):
    path = tmp_path / "restart.sandbox.sqlite3"
    first = SandboxBilling(path, clock=clock, signing_secret=SECRET)
    order = create(first, key="persistent-intent")
    raw, signature = first.make_event("alice", order["id"], "paid")
    first.accept_event(raw, signature)
    restarted = SandboxBilling(path, clock=clock, signing_secret=SECRET)
    assert create(restarted, key="persistent-intent")["id"] == order["id"]
    restarted.accept_event(raw, signature)
    assert len(restarted.list_grants("alice")) == 1


def test_techrent_cannot_read_or_activate_caucashub_orders(tmp_path, clock):
    path = tmp_path / "projects.sandbox.sqlite3"
    caucashub = SandboxBilling(path, clock=clock, signing_secret=SECRET)
    order = create(caucashub)
    raw, signature = caucashub.make_event("alice", order["id"], "paid")
    techrent = SandboxBilling(path, project="techrent", clock=clock, signing_secret=SECRET)
    assert techrent.catalog() == []
    assert techrent.list_orders("alice") == []
    assert techrent.list_grants("alice") == []
    with pytest.raises(BillingError):
        techrent.get_order("alice", order["id"])
    with pytest.raises(BillingError):
        techrent.accept_event(raw, signature)
    assert caucashub.get_order("alice", order["id"])["status"] == "pending"


@pytest.mark.asyncio
async def test_disabled_factory_never_constructs_a_database(tmp_path, monkeypatch):
    from app.billing_sandbox import core
    def forbidden(*args, **kwargs):
        raise AssertionError("Disabled sandbox constructed its store")
    monkeypatch.setattr(core, "SandboxBilling", forbidden)
    path = tmp_path / "disabled.sandbox.sqlite3"
    app = create_app(db_path=path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8787") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/api/state")).status_code in (404, 503)
        assert (await client.post("/api/session", json={"customer_id": "alice"})).status_code in (404, 503)
    assert not path.exists()


def test_enabled_sandbox_refuses_hosted_railway_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "isolated-test-marker")
    path = tmp_path / "refused.sandbox.sqlite3"
    with pytest.raises(ValueError, match="Railway"):
        create_app(enabled=True, db_path=path)
    assert not path.exists()


@pytest.mark.asyncio
async def test_http_owns_orders_prices_and_project_and_preserves_period_on_repeat(tmp_path, clock):
    app = create_app(enabled=True, db_path=tmp_path / "http.sandbox.sqlite3",
                     clock=clock, signing_secret=SECRET)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8787") as client:
        assert (await client.get("/api/state")).status_code == 401
        assert (await client.post("/api/payments/create", json={"type": "plan_pro"})).status_code == 404
        assert (await client.post("/api/session", json={"customer_id": "alice"})).status_code == 200
        for field, value in [("amount_tetri", 1), ("currency", "USD"),
                             ("customer_id", "bob"), ("project", "techrent")]:
            response = await client.post("/api/orders", json={"product_code": "pro", field: value},
                                         headers={"Idempotency-Key": "injected-" + field})
            assert response.status_code == 422
        response = await client.post("/api/orders", json={"product_code": "pro"},
                                     headers={"Idempotency-Key": "http-intent"})
        assert response.status_code in (200, 201)
        order = response.json()
        assert order["amount_tetri"] == 4900
        repeat = await client.post("/api/orders", json={"product_code": "pro"},
                                   headers={"Idempotency-Key": "http-intent"})
        assert repeat.json()["id"] == order["id"]
        endpoint = "/api/orders/" + order["id"]
        assert (await client.post(endpoint + "/simulate", json={"outcome": "paid"})).status_code == 200
        granted = (await client.get("/api/state")).json()["grants"]
        assert len(granted) == 1
        assert (await client.post(endpoint + "/simulate", json={"outcome": "paid"})).status_code == 200
        assert (await client.get("/api/state")).json()["grants"] == granted
        assert (await client.post("/api/session", json={"customer_id": "bob"})).status_code == 200
        assert (await client.get(endpoint)).status_code == 404
        assert (await client.post(endpoint + "/simulate", json={"outcome": "refunded"})).status_code == 404
        state = (await client.get("/api/state")).json()
        assert state["orders"] == state["grants"] == []


@pytest.mark.asyncio
async def test_loopback_application_rejects_foreign_host_and_cross_origin_write(tmp_path):
    app = create_app(enabled=True, db_path=tmp_path / "origin.sandbox.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8787") as client:
        assert (await client.get("/health", headers={"Host": "attacker.invalid"})).status_code == 400
        response = await client.post("/api/session", json={"customer_id": "alice"},
                                     headers={"Origin": "https://attacker.invalid"})
        assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("second_project", ["caucashub", "techrent"])
async def test_shared_browser_cookies_do_not_replace_sessions_of_other_local_apps(
    tmp_path, clock, second_project
):
    first = create_app(enabled=True, db_path=tmp_path / "first.sandbox.sqlite3",
                       project="caucashub", clock=clock, signing_secret=SECRET)
    second = create_app(enabled=True, db_path=tmp_path / "second.sandbox.sqlite3",
                        project=second_project, clock=clock, signing_secret=SECRET)

    class LocalApps(AsyncBaseTransport):
        def __init__(self):
            self.apps = {8878: ASGITransport(app=first), 8879: ASGITransport(app=second)}

        async def handle_async_request(self, request):
            return await self.apps[request.url.port].handle_async_request(request)

        async def aclose(self):
            for transport in self.apps.values():
                await transport.aclose()

    first_origin = "http://127.0.0.1:8878"
    second_origin = "http://127.0.0.1:8879"
    # One client intentionally acts like one browser: cookies for 127.0.0.1 are
    # shared across both ports. Independent clients would hide the collision.
    async with AsyncClient(transport=LocalApps()) as browser:
        first_login = await browser.post(first_origin + "/api/session", json={"customer_id": "alice"})
        assert first_login.status_code == 200
        second_login = await browser.post(second_origin + "/api/session", json={"customer_id": "bob"})
        assert second_login.status_code == 200

        first_state = await browser.get(first_origin + "/api/state")
        second_state = await browser.get(second_origin + "/api/state")
        assert first_state.status_code == second_state.status_code == 200
        assert first_state.json()["customer"]["id"] == "alice"
        assert second_state.json()["customer"]["id"] == "bob"
        assert first_state.json()["project"] == "caucashub"
        assert second_state.json()["project"] == second_project
