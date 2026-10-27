"""Real HTTP ownership boundaries for listings, responses, deals and private contacts."""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func

from app.database import get_db
from app.models.deal import Deal
from app.models.load import Load, LoadStatus, TruckType
from app.models.notification import Notification, NotificationDelivery
from app.models.response import Response, ResponseStatus
from app.models.transport_offer import TransportOffer
from app.models.transport_request import TransportRequest
from app.models.truck import Truck
from app.models.user import User, UserPlan
from app.routers import loads, trucks, responses, transport, transport_requests, deals, users, notifications, tg_bot
from app.services import exchange_rate, subscription_matcher, transport_matcher
from app.services.listing_freshness import listing_day_start
from app.services.notifications import enqueue_event
from tests.test_notification_inbox import notification_db


@pytest_asyncio.fixture
async def access(notification_db, monkeypatch):
    context = dict(notification_db)
    sessions = context["sessions"]
    async def isolated_db():
        async with sessions() as db:
            yield db
    app = FastAPI()
    for router, prefix in (
        (loads.router, "/api/loads"), (trucks.router, "/api/trucks"),
        (responses.router, ""), (transport.router, ""), (transport_requests.router, ""),
        (deals.router, "/api/deals"), (users.router, "/api/users"),
        (notifications.router, ""), (tg_bot.router, "/api/tg"),
    ):
        app.include_router(router, prefix=prefix)
    app.dependency_overrides[get_db] = isolated_db
    monkeypatch.setattr(exchange_rate, "get_usd_gel_rate", AsyncMock(return_value=2.7))
    monkeypatch.setattr(subscription_matcher, "notify_subscribers", AsyncMock(return_value=0))
    monkeypatch.setattr(transport_matcher, "notify_transport_subscribers", AsyncMock(return_value=0))
    people = context["profiles"]
    day = listing_day_start() + timedelta(days=1)
    async with sessions() as db:
        load = Load(user_id=people["shipper"]["id"], from_city="Тбилиси", to_city="Батуми",
                    weight_kg=3000, truck_type=TruckType.tent, price_gel=500,
                    load_date=day, status=LoadStatus.active, cargo_desc="Own access test")
        foreign_load = Load(user_id=people["outsider"]["id"], from_city="Кутаиси", to_city="Поти",
                            weight_kg=1000, truck_type=TruckType.tent, price_gel=300,
                            load_date=day, status=LoadStatus.active, cargo_desc="Other access test")
        truck = Truck(user_id=people["carrier"]["id"], truck_type=TruckType.tent,
                      capacity_kg=10000, available_from="Тбилиси", is_available=True)
        offer = TransportOffer(user_id=people["carrier"]["id"], from_city="Тбилиси", to_city="Батуми",
                               truck_type="tent", capacity_kg=10000, available_from=day,
                               price=500, status="active", is_demo=False)
        foreign_offer = TransportOffer(user_id=people["outsider"]["id"], from_city="Кутаиси", to_city="Поти",
                                       truck_type="tent", capacity_kg=5000, available_from=day,
                                       price=300, status="active", is_demo=False)
        db.add_all([load, foreign_load, truck, offer, foreign_offer])
        await db.flush()
        response = Response(load_id=load.id, user_id=people["carrier"]["id"],
                            price_gel=500, status=ResponseStatus.pending)
        other_response = Response(load_id=load.id, user_id=people["outsider"]["id"],
                                  price_gel=450, status=ResponseStatus.pending)
        foreign_response = Response(load_id=foreign_load.id, user_id=people["carrier"]["id"],
                                    price_gel=300, status=ResponseStatus.pending)
        request = TransportRequest(transport_offer_id=offer.id, user_id=people["shipper"]["id"],
                                   cargo_description="Own request", weight_kg=3000, status="pending")
        foreign_request = TransportRequest(transport_offer_id=foreign_offer.id,
                                           user_id=people["shipper"]["id"],
                                           cargo_description="Other request", weight_kg=1000, status="pending")
        db.add_all([response, other_response, foreign_response, request, foreign_request])
        await db.flush()
        context["ids"] = {
            "load": load.id, "foreign_load": foreign_load.id, "truck": truck.id,
            "offer": offer.id, "foreign_offer": foreign_offer.id,
            "response": response.id, "other_response": other_response.id,
            "foreign_response": foreign_response.id,
            "request": request.id, "foreign_request": foreign_request.id,
        }
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        context["client"] = client
        yield context


async def snapshot(context):
    async with context["sessions"]() as db:
        load = await db.get(Load, context["ids"]["load"])
        offer = await db.get(TransportOffer, context["ids"]["offer"])
        response = await db.get(Response, context["ids"]["response"])
        request = await db.get(TransportRequest, context["ids"]["request"])
        return {
            "load": (load.cargo_desc, load.status.value),
            "offer": (offer.notes, offer.status),
            "response": response.status.value if hasattr(response.status, "value") else response.status,
            "request": request.status,
            "truck": await db.get(Truck, context["ids"]["truck"]) is not None,
            "deals": (await db.execute(select(func.count()).select_from(Deal))).scalar_one(),
            "notifications": (await db.execute(select(func.count()).select_from(Notification))).scalar_one(),
            "deliveries": (await db.execute(select(func.count()).select_from(NotificationDelivery))).scalar_one(),
        }


DENIED = [
    ("PUT", "/api/loads/{load}", {"cargo_desc": "forbidden"}, 403),
    ("DELETE", "/api/loads/{load}", None, 403),
    ("DELETE", "/api/trucks/{truck}", None, 404),
    ("PATCH", "/api/transport/{offer}", {"notes": "forbidden"}, 403),
    ("DELETE", "/api/transport/{offer}", None, 403),
    ("GET", "/api/responses/load/{load}", None, 403),
    ("POST", "/api/responses/accept/{response}", None, 403),
    ("POST", "/api/responses/reject/{response}", None, 403),
    ("DELETE", "/api/responses/cancel/{response}", None, 403),
    ("GET", "/api/transport/{offer}/requests", None, 403),
    ("POST", "/api/transport-requests/{request}/accept", None, 403),
    ("POST", "/api/transport-requests/{request}/reject", None, 403),
    ("DELETE", "/api/transport-requests/{request}", None, 403),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,payload,status", DENIED)
async def test_outsider_cannot_read_or_mutate_other_participants_objects(access, method, path, payload, status):
    before = await snapshot(access)
    response = await access["client"].request(method, path.format(**access["ids"]),
        json=payload, headers=access["headers"]["outsider"])
    assert response.status_code == status, response.text
    assert await snapshot(access) == before


@pytest.mark.asyncio
async def test_owners_keep_their_legitimate_listing_and_response_actions(access):
    client, ids, headers = access["client"], access["ids"], access["headers"]
    response = await client.put(f"/api/loads/{ids['load']}", json={"cargo_desc": "Updated own cargo"},
                                headers=headers["shipper"])
    assert response.status_code == 200, response.text
    patched = await client.patch(f"/api/transport/{ids['offer']}", json={"notes": "Updated own transport"},
                                 headers=headers["carrier"])
    assert patched.status_code == 200, patched.text
    inbox = await client.get(f"/api/responses/load/{ids['load']}", headers=headers["shipper"])
    assert inbox.status_code == 200
    assert {row["id"] for row in inbox.json()["responses"]} == {ids["response"], ids["other_response"]}
    assert all(row["carrier_phone"] is None and row["carrier_email"] is None for row in inbox.json()["responses"])
    incoming = await client.get(f"/api/transport/{ids['offer']}/requests", headers=headers["carrier"])
    assert incoming.status_code == 200
    assert incoming.json()["requests"][0]["shipper_phone"] is None
    withdrawn = await client.delete(f"/api/responses/cancel/{ids['response']}", headers=headers["carrier"])
    assert withdrawn.status_code == 200, withdrawn.text
    canceled = await client.delete(f"/api/transport-requests/{ids['request']}", headers=headers["shipper"])
    assert canceled.status_code == 200, canceled.text
    removed = await client.delete(f"/api/trucks/{ids['truck']}", headers=headers["carrier"])
    assert removed.status_code == 200, removed.text
    async with access["sessions"]() as db:
        foreign = await db.get(Load, ids["foreign_load"])
        other = await db.get(Response, ids["other_response"])
        assert foreign.cargo_desc == "Other access test"
        assert other.status == ResponseStatus.pending


@pytest.mark.asyncio
@pytest.mark.parametrize("viewer", [None, "outsider"])
async def test_public_catalogues_never_publish_private_phones_or_email_fallbacks(access, viewer):
    async with access["sessions"]() as db:
        user = await db.get(User, access["profiles"]["carrier"]["id"])
        user.company_name = None
        user.full_name = None
        outsider = await db.get(User, access["profiles"]["outsider"]["id"])
        outsider.plan = UserPlan.pro
        await db.commit()
    headers = access["headers"][viewer] if viewer else {}
    for url in ("/api/trucks/", "/api/loads/", f"/api/loads/{access['ids']['load']}",
                "/api/transport/", f"/api/transport/{access['ids']['offer']}",
                f"/api/users/{access['profiles']['carrier']['id']}"):
        response = await access["client"].get(url, headers=headers)
        assert response.status_code == 200, response.text
        for profile in access["profiles"].values():
            assert profile["phone"] not in response.text
            assert profile["email"] not in response.text
    row = (await access["client"].get("/api/trucks/", headers=headers)).json()["trucks"][0]
    assert row["phone"] is None
    assert row["company"]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,role,key,expected", [
    ("/api/loads/my/loads", "outsider", "loads", ("foreign_load",)),
    ("/api/responses/my", "outsider", "responses", ("other_response",)),
    ("/api/transport/my", "carrier", "offers", ("offer",)),
    ("/api/transport-requests/my", "shipper", "requests", ("request", "foreign_request")),
])
async def test_private_my_collections_ignore_foreign_user_id_parameters(access, endpoint, role, key, expected):
    response = await access["client"].get(endpoint,
        params={"user_id": access["profiles"]["carrier" if role != "carrier" else "outsider"]["id"]},
        headers=access["headers"][role])
    assert response.status_code == 200, response.text
    assert {row["id"] for row in response.json()[key]} == {access["ids"][name] for name in expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_pending", "withdrawn", "wrong_load", "wrong_carrier"])
async def test_direct_deal_cannot_invent_or_cross_bind_carrier_consent(access, case):
    ids, profiles = access["ids"], access["profiles"]
    payload = {"load_id": ids["load"], "carrier_id": profiles["carrier"]["id"]}
    if case in {"no_pending", "withdrawn"}:
        async with access["sessions"]() as db:
            response = await db.get(Response, ids["response"])
            if case == "no_pending":
                await db.delete(response)
            else:
                response.status = ResponseStatus.withdrawn
            await db.commit()
    else:
        payload["response_id"] = ids["foreign_response" if case == "wrong_load" else "other_response"]
    before = await snapshot(access) if case != "no_pending" else None
    result = await access["client"].post("/api/deals/", json=payload, headers=access["headers"]["shipper"])
    assert result.status_code == 400, result.text
    async with access["sessions"]() as db:
        assert (await db.execute(select(func.count()).select_from(Deal))).scalar_one() == 0
        assert (await db.execute(select(func.count()).select_from(Notification))).scalar_one() == 0
        assert (await db.get(Load, ids["load"])).status == LoadStatus.active
    if before is not None:
        assert await snapshot(access) == before


@pytest.mark.asyncio
async def test_legacy_direct_deal_resolves_real_pending_response_and_only_participants_get_contacts(access):
    ids, profiles, client, headers = access["ids"], access["profiles"], access["client"], access["headers"]
    result = await client.post("/api/deals/", json={"load_id": ids["load"], "carrier_id": profiles["carrier"]["id"]},
                               headers=headers["shipper"])
    assert result.status_code == 200, result.text
    deal_id = result.json()["id"]
    async with access["sessions"]() as db:
        deal = await db.get(Deal, deal_id)
        assert deal.response_id == ids["response"]
        assert (await db.get(Response, ids["response"])).status == ResponseStatus.accepted
        assert (await db.get(Load, ids["load"])).status == LoadStatus.taken
        created = list((await db.execute(select(Notification).where(
            Notification.event_key == f"deal:{deal_id}:created"))).scalars())
        assert {row.recipient_id for row in created} == {profiles["shipper"]["id"], profiles["carrier"]["id"]}
        owner_notice = next(row for row in created if row.recipient_id == profiles["shipper"]["id"])
        owner_notice_id = owner_notice.id
    for role, other in (("shipper", "carrier"), ("carrier", "shipper")):
        personal = await client.get("/api/deals/my", headers=headers[role])
        assert personal.status_code == 200
        deal = next(row for row in personal.json()["deals"] if row["id"] == deal_id)
        assert deal[other]["phone"] == profiles[other]["phone"]
        assert deal[other]["email"] == profiles[other]["email"]
    outsider = await client.get("/api/deals/my", headers=headers["outsider"])
    assert outsider.status_code == 200 and outsider.json()["deals"] == []
    exported = await client.get("/api/deals/export", headers=headers["outsider"],
                                params={"user_id": profiles["shipper"]["id"]})
    assert exported.status_code == 200, exported.text
    assert exported.json()["count"] == 0 and exported.json()["deals"] == []
    for method, url, data in (
        ("POST", f"/api/deals/{deal_id}/confirm", None),
        ("POST", f"/api/deals/{deal_id}/status", {"status": "loading"}),
        ("POST", f"/api/deals/{deal_id}/rate", {"score": 5}),
        ("GET", f"/api/deals/{deal_id}/act.pdf", None),
    ):
        blocked = await client.request(method, url, json=data, headers=headers["outsider"])
        assert blocked.status_code == 403, blocked.text
    read = await client.post(f"/api/notifications/{owner_notice_id}/read", headers=headers["outsider"])
    assert read.status_code == 404
    async with access["sessions"]() as db:
        assert (await db.get(Notification, owner_notice_id)).read_at is None
        assert (await db.get(Deal, deal_id)).status.value == "confirmed"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["direct", "cargo_accept", "transport_accept"])
@pytest.mark.parametrize("unavailable", ["inactive", "deleted"])
async def test_new_deal_rejects_unavailable_counterparty_atomically(access, path, unavailable):
    ids, profiles = access["ids"], access["profiles"]
    counterparty = "shipper" if path == "transport_accept" else "carrier"
    async with access["sessions"]() as db:
        user = await db.get(User, profiles[counterparty]["id"])
        if unavailable == "deleted":
            user.is_deleted = True
        else:
            user.is_active = False
        await db.commit()
    before = await snapshot(access)
    if path == "direct":
        result = await access["client"].post("/api/deals/", headers=access["headers"]["shipper"],
            json={"load_id": ids["load"], "carrier_id": profiles["carrier"]["id"], "response_id": ids["response"]})
    elif path == "cargo_accept":
        result = await access["client"].post(f"/api/responses/accept/{ids['response']}", headers=access["headers"]["shipper"])
    else:
        result = await access["client"].post(f"/api/transport-requests/{ids['request']}/accept", headers=access["headers"]["carrier"])
    assert result.status_code == 400, result.text
    assert await snapshot(access) == before


@pytest.mark.asyncio
async def test_profile_cannot_assign_or_clear_a_telegram_chat_bypassing_verification(access):
    profile = access["profiles"]["shipper"]
    async with access["sessions"]() as db:
        original_name = (await db.get(User, profile["id"])).company_name
    for telegram_id in ("901009999", "pending:made-up", ""):
        result = await access["client"].put("/api/users/me",
            json={"telegram_id": telegram_id, "company_name": "must-not-save"},
            headers=access["headers"]["shipper"])
        assert result.status_code == 403, result.text
        async with access["sessions"]() as db:
            user = await db.get(User, profile["id"])
            assert user.telegram_id == profile["telegram_id"]
            assert user.company_name == original_name
    for value in (None, profile["telegram_id"]):
        no_op = await access["client"].put("/api/users/me", json={"telegram_id": value, "city": "Тбилиси"},
                                         headers=access["headers"]["shipper"])
        assert no_op.status_code == 200, no_op.text
    async with access["sessions"]() as db:
        assert (await db.get(User, profile["id"])).telegram_id == profile["telegram_id"]
        assert (await db.execute(select(func.count()).select_from(Notification))).scalar_one() == 0


@pytest.mark.asyncio
async def test_telegram_generate_and_unlink_only_change_the_authenticated_profile(access):
    own = access["profiles"]["outsider"]
    generated = await access["client"].post("/api/tg/generate-link", headers=access["headers"]["outsider"])
    assert generated.status_code == 200
    assert generated.json().get("token") and generated.json().get("link")
    async with access["sessions"]() as db:
        user = await db.get(User, own["id"])
        assert user.telegram_id == "pending:" + generated.json()["token"]
        for role in ("shipper", "carrier"):
            assert (await db.get(User, access["profiles"][role]["id"])).telegram_id == access["profiles"][role]["telegram_id"]
    unlinked = await access["client"].delete("/api/tg/unlink", headers=access["headers"]["outsider"])
    assert unlinked.status_code == 200
    async with access["sessions"]() as db:
        assert (await db.get(User, own["id"])).telegram_id is None
        assert (await db.get(User, access["profiles"]["shipper"]["id"])).telegram_id == access["profiles"]["shipper"]["telegram_id"]


@pytest.mark.asyncio
async def test_anonymous_private_requests_and_mutations_are_denied_without_changes(access):
    before = await snapshot(access)
    for method, pattern, payload, _ in DENIED:
        result = await access["client"].request(method, pattern.format(**access["ids"]), json=payload)
        assert result.status_code in (401, 403), (method, pattern, result.text)
    for path in ("/api/loads/my/loads", "/api/responses/my", "/api/transport/my",
                 "/api/transport-requests/my", "/api/deals/my", "/api/notifications"):
        result = await access["client"].get(path)
        assert result.status_code in (401, 403), (path, result.text)
    assert await snapshot(access) == before
