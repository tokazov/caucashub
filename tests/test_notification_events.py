"""Notification events through real HTTP transactions on disposable SQLite/PostgreSQL.

No worker is started and no email/Telegram provider is invoked. Events are asserted
in the same database as the business changes, including rollback and race cases.
"""
import asyncio

import pytest
from sqlalchemy import event, func, select

from app.models.deal import Deal
from app.models.load import Load
from app.models.notification import Notification
from app.models.response import Response
from app.models.transport_offer import TransportOffer
from app.models.transport_request import TransportRequest
from app.models.user import User
from tests.test_publication_journeys import cargo, journey  # noqa: F401


pytestmark = pytest.mark.asyncio
SOURCES = pytest.mark.parametrize("source", ["cargo", "transport"])


async def role_ids(context):
    async with context["sessions"]() as db:
        rows = (await db.execute(select(User.id, User.email))).all()
    return {email.split("@")[0]: user_id for user_id, email in rows}


async def stored_events(context):
    async with context["sessions"]() as db:
        rows = (await db.execute(select(Notification).order_by(Notification.id))).scalars().all()
        return [{"key": row.event_key, "kind": row.kind, "recipient": row.recipient_id,
                 "actor": row.actor_id, "data": row.data} for row in rows]


async def make_request(context, source, *, shipper_headers=None, carrier_headers=None):
    client, roles = context["client"], context["headers"]
    shipper_headers = shipper_headers or roles["shipper"]
    carrier_headers = carrier_headers or roles["carrier"]
    if source == "cargo":
        created = await client.post("/api/loads/", headers=shipper_headers, json=cargo())
        assert created.status_code == 200, created.text
        item_id = created.json()["id"]
        requested = await client.post(f"/api/responses/load/{item_id}", headers=carrier_headers,
                                      json={"price": 500, "message": "PRIVATE RAW MESSAGE"})
        assert requested.status_code == 200, requested.text
        request_id = requested.json()["response_id"]
    else:
        created = await client.post("/api/transport/", headers=carrier_headers, json={
            "from_city": "Тбилиси", "to_city": "Батуми", "truck_type": "tent",
            "capacity_kg": 10000, "available_from": cargo()["load_date"], "price": 600})
        assert created.status_code == 201, created.text
        item_id = created.json()["offer"]["id"]
        requested = await client.post(f"/api/transport/{item_id}/request", headers=shipper_headers,
            json={"cargo_description": "PRIVATE CARGO", "weight_kg": 3000,
                  "price": 500, "message": "PRIVATE RAW MESSAGE"})
        assert requested.status_code == 201, requested.text
        request_id = requested.json()["request"]["id"]
    return item_id, request_id


async def accept(context, source, request_id, *, key=None):
    if source == "cargo":
        path, role = f"/api/responses/accept/{request_id}", "shipper"
    else:
        path, role = f"/api/transport-requests/{request_id}/accept", "carrier"
    headers = dict(context["headers"][role])
    if key:
        headers["Idempotency-Key"] = key
    return await context["client"].post(path, headers=headers)


async def count(context, model):
    async with context["sessions"]() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar_one()


def block_event_inserts(context):
    def fail(connection, cursor, statement, parameters, execution_context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO NOTIFICATIONS"):
            raise RuntimeError("Synthetic notification persistence failure")
    event.listen(context["engine"].sync_engine, "before_cursor_execute", fail)
    return lambda: event.remove(context["engine"].sync_engine, "before_cursor_execute", fail)


@SOURCES
async def test_new_request_event_has_correct_owner_actor_and_private_payload(journey, source):
    ids = await role_ids(journey)
    item_id, request_id = await make_request(journey, source)
    rows = await stored_events(journey)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == ("new_response" if source == "cargo" else "new_transport_request")
    prefix = "response" if source == "cargo" else "transport_request"
    assert row["key"] == f"{prefix}:{request_id}:created"
    assert row["recipient"] == ids["shipper" if source == "cargo" else "carrier"]
    assert row["actor"] == ids["carrier" if source == "cargo" else "shipper"]
    data = row["data"]
    assert data["source"] == source
    assert data["from_city"] == "Тбилиси" and data["to_city"] == "Батуми"
    assert data["price"] == 500 and data["currency"] == "GEL"
    assert data["load_id" if source == "cargo" else "transport_offer_id"] == item_id
    assert data["response_id" if source == "cargo" else "transport_request_id"] == request_id
    # Structured contact fields and raw free text never enter stored event data.
    assert not ({"phone", "email", "message", "cargo_description", "notes",
                 "shipper_phone", "carrier_phone", "shipper_email", "carrier_email"} & data.keys())
    assert "PRIVATE" not in str(data)
    assert "@example.test" not in str(data) and "+995599" not in str(data)


@SOURCES
async def test_accept_creates_one_deal_two_recipient_events_and_takes_source(journey, source):
    item_id, request_id = await make_request(journey, source)
    ids = await role_ids(journey)
    first = await accept(journey, source, request_id, key="accept-once")
    assert first.status_code == 200, first.text
    deal_id = first.json()["deal_id"]
    repeated = await accept(journey, source, request_id, key="accept-once")
    assert repeated.status_code == (200 if source == "cargo" else 400), repeated.text
    if source == "cargo":
        assert repeated.headers["Idempotency-Replayed"] == "true"
        assert repeated.json() == first.json()
    events = [row for row in await stored_events(journey) if row["kind"] == "deal_created"]
    assert {(row["key"], row["recipient"]) for row in events} == {
        (f"deal:{deal_id}:created", ids["shipper"]), (f"deal:{deal_id}:created", ids["carrier"])}
    assert len(events) == 2
    assert all(row["data"]["deal_id"] == deal_id and row["data"]["source"] == source for row in events)
    assert all(row["data"]["price"] == 500 and row["data"]["currency"] == "GEL" for row in events)
    async with journey["sessions"]() as db:
        deal = await db.get(Deal, deal_id)
        listing = await db.get(Load if source == "cargo" else TransportOffer, item_id)
        assert listing.status == "taken"
        assert deal.act_number
        assert deal.response_id == request_id if source == "cargo" else deal.transport_request_id == request_id
    assert await count(journey, Deal) == 1


@SOURCES
async def test_new_request_event_write_failure_rolls_back_request(journey, source):
    client, roles = journey["client"], journey["headers"]
    if source == "cargo":
        response = await client.post("/api/loads/", headers=roles["shipper"], json=cargo())
        item_id = response.json()["id"]
        path, headers, body = f"/api/responses/load/{item_id}", roles["carrier"], {"price": 500}
    else:
        response = await client.post("/api/transport/", headers=roles["carrier"], json={
            "from_city": "Тбилиси", "to_city": "Батуми", "truck_type": "tent",
            "capacity_kg": 10000, "available_from": cargo()["load_date"]})
        item_id = response.json()["offer"]["id"]
        path, headers, body = f"/api/transport/{item_id}/request", roles["shipper"], {"weight_kg": 3000}
    remove = block_event_inserts(journey)
    try:
        failed = await client.post(path, headers=headers, json=body)
        assert failed.status_code == 500, failed.text
    finally:
        remove()
    assert await count(journey, Response if source == "cargo" else TransportRequest) == 0
    assert await count(journey, Notification) == 0


@SOURCES
async def test_accept_event_failure_rolls_back_deal_and_source_state(journey, source):
    item_id, request_id = await make_request(journey, source)
    before = await stored_events(journey)
    remove = block_event_inserts(journey)
    try:
        failed = await accept(journey, source, request_id, key="failing-accept")
        assert failed.status_code == 500, failed.text
    finally:
        remove()
    assert await stored_events(journey) == before
    assert await count(journey, Deal) == 0
    async with journey["sessions"]() as db:
        listing = await db.get(Load if source == "cargo" else TransportOffer, item_id)
        request = await db.get(Response if source == "cargo" else TransportRequest, request_id)
        assert listing.status == "active" and request.status == "pending"
    retried = await accept(journey, source, request_id, key="failing-accept")
    assert retried.status_code == 200, retried.text
    assert await count(journey, Deal) == 1


@SOURCES
@pytest.mark.parametrize("first_role", ["shipper", "carrier"])
async def test_delivery_event_recipients_and_replays_across_both_confirm_commands(journey, source, first_role):
    _, request_id = await make_request(journey, source)
    accepted = await accept(journey, source, request_id)
    deal_id = accepted.json()["deal_id"]
    ids = await role_ids(journey)
    peer = "carrier" if first_role == "shipper" else "shipper"
    client, headers = journey["client"], journey["headers"]
    first_path = f"/api/deals/{deal_id}/confirm"
    first = await client.post(first_path, headers=headers[first_role])
    assert first.status_code == 200 and first.json()["status"] == "delivered", first.text
    again = await client.post(first_path, headers=headers[first_role])
    assert again.status_code == 200, again.text
    waiting = [row for row in await stored_events(journey) if row["kind"].startswith("delivery_")]
    assert {(row["kind"], row["recipient"]) for row in waiting} == {
        ("delivery_waiting", ids[first_role]), ("delivery_confirmation_required", ids[peer])}
    assert len(waiting) == 2
    assert {row["key"] for row in waiting} == {f"deal:{deal_id}:confirmed:{ids[first_role]}"}
    # The compatibility status command uses the same locked confirmation helper.
    completed = await client.post(f"/api/deals/{deal_id}/status", headers=headers[peer],
        json={"status": f"delivered_{peer}"})
    assert completed.status_code == 200 and completed.json()["status"] == "completed", completed.text
    final_events = await stored_events(journey)
    completed_events = [row for row in final_events if row["kind"] == "deal_completed"]
    assert {(row["key"], row["recipient"]) for row in completed_events} == {
        (f"deal:{deal_id}:completed", ids["shipper"]), (f"deal:{deal_id}:completed", ids["carrier"])}
    assert len(completed_events) == 2
    for role in (first_role, peer):
        replay = await client.post(first_path, headers=headers[role])
        assert replay.status_code == 200 and replay.json()["status"] == "completed"
    assert await stored_events(journey) == final_events


@SOURCES
async def test_confirmation_event_failure_rolls_back_confirmation_and_counters(journey, source):
    _, request_id = await make_request(journey, source)
    accepted = await accept(journey, source, request_id)
    deal_id = accepted.json()["deal_id"]
    before = await stored_events(journey)
    remove = block_event_inserts(journey)
    try:
        failed = await journey["client"].post(f"/api/deals/{deal_id}/confirm",
                                               headers=journey["headers"]["carrier"])
        assert failed.status_code == 500, failed.text
    finally:
        remove()
    async with journey["sessions"]() as db:
        deal = await db.get(Deal, deal_id)
        assert deal.status == "confirmed"
        assert not deal.shipper_confirmed and not deal.carrier_confirmed
        assert deal.delivered_at is None and deal.completed_at is None
        users = (await db.execute(select(User))).scalars().all()
        assert all((user.completed_deals_count or 0) == 0 for user in users)
    assert await stored_events(journey) == before


@SOURCES
async def test_rejection_event_is_once_and_only_for_requester(journey, source):
    _, request_id = await make_request(journey, source)
    ids = await role_ids(journey)
    if source == "cargo":
        path, actor, recipient, prefix = f"/api/responses/reject/{request_id}", "shipper", "carrier", "response"
    else:
        path, actor, recipient, prefix = f"/api/transport-requests/{request_id}/reject", "carrier", "shipper", "transport_request"
    for _ in range(2):
        reply = await journey["client"].post(path, headers=journey["headers"][actor])
        assert reply.status_code == 200, reply.text
    rows = [row for row in await stored_events(journey) if row["kind"].endswith("_rejected")]
    assert len(rows) == 1
    assert rows[0]["key"] == f"{prefix}:{request_id}:rejected"
    assert rows[0]["recipient"] == ids[recipient] and rows[0]["actor"] == ids[actor]


@SOURCES
async def test_parallel_postgresql_accepts_create_one_deal_and_one_event_per_party(journey, source):
    if journey["engine"].dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locking")
    _, request_id = await make_request(journey, source)
    replies = await asyncio.wait_for(asyncio.gather(
        accept(journey, source, request_id), accept(journey, source, request_id)), timeout=20)
    assert sum(reply.status_code == 200 for reply in replies) == 1, [reply.text for reply in replies]
    assert all(reply.status_code in (200, 400, 409) for reply in replies)
    assert await count(journey, Deal) == 1
    rows = [row for row in await stored_events(journey) if row["kind"] == "deal_created"]
    assert len(rows) == 2 and len({row["recipient"] for row in rows}) == 2


async def test_direct_create_requires_matching_carrier_consent_and_preserves_legacy_identifier_omission(journey):
    item_id, request_id = await make_request(journey, "cargo")
    ids = await role_ids(journey)
    client, headers = journey["client"], journey["headers"]["shipper"]
    second = await client.post("/api/loads/", headers=headers, json=cargo())
    other_load_id = second.json()["id"]
    invalid = await client.post("/api/deals/", headers=headers, json={
        "load_id": other_load_id, "carrier_id": ids["carrier"], "response_id": request_id})
    assert invalid.status_code == 400, invalid.text
    assert await count(journey, Deal) == 0
    assert not [row for row in await stored_events(journey) if row["kind"] == "deal_created"]
    unbound = await client.post("/api/deals/", headers=headers, json={
        "load_id": other_load_id, "carrier_id": ids["carrier"], "agreed_price": 700, "currency": "GEL"})
    assert unbound.status_code == 400, unbound.text
    assert await count(journey, Deal) == 0
    assert not [row for row in await stored_events(journey) if row["kind"] == "deal_created"]
    consent = await client.post(f"/api/responses/load/{other_load_id}",
        headers=journey["headers"]["carrier"], json={"price": 700, "currency": "GEL"})
    assert consent.status_code == 200, consent.text
    valid = await client.post("/api/deals/", headers=headers, json={
        "load_id": other_load_id, "carrier_id": ids["carrier"], "agreed_price": 700, "currency": "GEL"})
    assert valid.status_code == 200, valid.text
    repeated = await client.post("/api/deals/", headers=headers, json={
        "load_id": other_load_id, "carrier_id": ids["carrier"]})
    assert repeated.status_code == 409, repeated.text
    rows = [row for row in await stored_events(journey) if row["kind"] == "deal_created"]
    assert len(rows) == 2 and {row["recipient"] for row in rows} == {ids["shipper"], ids["carrier"]}
    assert all(row["data"]["price"] == 700 for row in rows)


async def test_postgresql_direct_create_races_accept_under_same_source_lock(journey):
    if journey["engine"].dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locking")
    item_id, request_id = await make_request(journey, "cargo")
    ids = await role_ids(journey)
    replies = await asyncio.wait_for(asyncio.gather(
        accept(journey, "cargo", request_id),
        journey["client"].post("/api/deals/", headers=journey["headers"]["shipper"],
            json={"load_id": item_id, "carrier_id": ids["carrier"], "response_id": request_id})), timeout=20)
    assert sorted(reply.status_code for reply in replies) == [200, 409], [reply.text for reply in replies]
    assert await count(journey, Deal) == 1
    assert len([row for row in await stored_events(journey) if row["kind"] == "deal_created"]) == 2


@SOURCES
async def test_wrong_party_cannot_accept_or_create_acceptance_events(journey, source):
    _, request_id = await make_request(journey, source)
    before = await stored_events(journey)
    if source == "cargo":
        path, wrong_role = f"/api/responses/accept/{request_id}", "carrier"
    else:
        path, wrong_role = f"/api/transport-requests/{request_id}/accept", "shipper"
    denied = await journey["client"].post(path, headers=journey["headers"][wrong_role])
    assert denied.status_code == 403, denied.text
    assert await count(journey, Deal) == 0
    assert await stored_events(journey) == before


@SOURCES
async def test_parallel_postgresql_new_requests_create_one_request_and_one_event(journey, source):
    if journey["engine"].dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL source row locking")
    client, roles = journey["client"], journey["headers"]
    if source == "cargo":
        published = await client.post("/api/loads/", headers=roles["shipper"], json=cargo())
        assert published.status_code == 200, published.text
        path = f"/api/responses/load/{published.json()['id']}"
        headers, body = roles["carrier"], {"price": 500}
        expected_success, model = 200, Response
    else:
        published = await client.post("/api/transport/", headers=roles["carrier"], json={
            "from_city": "Тбилиси", "to_city": "Батуми", "truck_type": "tent",
            "capacity_kg": 10000, "available_from": cargo()["load_date"]})
        assert published.status_code == 201, published.text
        path = f"/api/transport/{published.json()['offer']['id']}/request"
        headers, body = roles["shipper"], {"weight_kg": 3000, "price": 500}
        expected_success, model = 201, TransportRequest
    replies = await asyncio.wait_for(asyncio.gather(
        client.post(path, headers=headers, json=body),
        client.post(path, headers=headers, json=body)), timeout=20)
    assert sum(reply.status_code == expected_success for reply in replies) == 1, [r.text for r in replies]
    assert all(reply.status_code in (expected_success, 400, 409) for reply in replies)
    assert await count(journey, model) == 1
    assert len(await stored_events(journey)) == 1
