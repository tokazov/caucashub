"""Completion contracts through real routers on the shared disposable DB fixture.

No accounts, publications, notifications or PDF requests target production.
The imported fixture runs each test against SQLite and CI's isolated PostgreSQL.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import select, update

from app.models.deal import Deal, DealStatus
from app.models.user import User
from app.routers import deals
from tests.test_publication_journeys import cargo, journey  # noqa: F401


DESCRIPTION = "HTTP completion cargo: книги, მადლობა"
SOURCES = pytest.mark.parametrize("source", ["cargo", "transport"])
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def no_completion_email(monkeypatch):
    """Stop external notifications at the router notification boundary."""
    monkeypatch.setattr(deals, "_send_completed_emails", Mock(return_value=None))


async def accepted_deal(context, source):
    client, roles = context["client"], context["headers"]
    if source == "cargo":
        created = await client.post("/api/loads/", headers=roles["shipper"],
                                    json={**cargo(), "cargo_desc": DESCRIPTION})
        assert created.status_code == 200, created.text
        item_id = created.json()["id"]
        requested = await client.post(f"/api/responses/load/{item_id}",
                                      headers=roles["carrier"], json={"price": 500})
        assert requested.status_code in (200, 201), requested.text
        request_id = requested.json()["response_id"]
        accepted = await client.post(f"/api/responses/accept/{request_id}",
                                     headers=roles["shipper"])
    else:
        created = await client.post("/api/transport/", headers=roles["carrier"], json={
            "from_city": "Тбилиси", "to_city": "Батуми", "truck_type": "ref",
            "capacity_kg": 10000, "available_from": cargo()["load_date"],
            "price": 500, "notes": "Offer note is not the accepted cargo description",
        })
        assert created.status_code == 201, created.text
        item_id = created.json()["offer"]["id"]
        requested = await client.post(f"/api/transport/{item_id}/request",
            headers=roles["shipper"], json={"cargo_description": DESCRIPTION, "weight_kg": 3000})
        assert requested.status_code == 201, requested.text
        request_id = requested.json()["request"]["id"]
        accepted = await client.post(f"/api/transport-requests/{request_id}/accept",
                                     headers=roles["carrier"])
    assert accepted.status_code == 200, accepted.text
    return accepted.json()["deal_id"]


async def personal(context, role, deal_id):
    response = await context["client"].get("/api/deals/my", headers=context["headers"][role])
    assert response.status_code == 200, response.text
    return next(row for row in response.json()["deals"] if row["id"] == deal_id)


async def confirm(context, role, deal_id, expected=200):
    response = await context["client"].post(f"/api/deals/{deal_id}/confirm",
                                            headers=context["headers"][role])
    assert response.status_code == expected, response.text
    return response.json()


async def complete(context, source, first="carrier"):
    deal_id = await accepted_deal(context, source)
    first_result = await confirm(context, first, deal_id)
    assert first_result["status"] == "delivered"
    second = "shipper" if first == "carrier" else "carrier"
    final = await confirm(context, second, deal_id)
    assert final["status"] == "completed"
    assert final["shipper_confirmed"] is True and final["carrier_confirmed"] is True
    return deal_id, final


async def review(context, role, deal_id, score=4, comment=None, expected=200):
    response = await context["client"].post(f"/api/deals/{deal_id}/rate",
        headers=context["headers"][role], json={"score": score, "comment": comment})
    assert response.status_code == expected, response.text
    return response.json()


async def user_state(context):
    async with context["sessions"]() as db:
        rows = (await db.execute(select(User).where(
            User.email.in_(["shipper@example.test", "carrier@example.test"])))).scalars().all()
        return {row.email.split("@")[0]: {
            "rating": row.rating, "completed": row.completed_deals_count or 0,
            "trips": row.trips_count or 0, "received": row.ratings_received_count or 0,
        } for row in rows}


async def outsider(context):
    response = await context["client"].post("/api/auth/register", json={
        "email": "outsider@example.test", "password": "JourneyTest39!",
        "company_name": "Unrelated participant", "phone": "+995599000003",
        "role": "carrier", "inn": "404123456",
    })
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


@SOURCES
@pytest.mark.parametrize("first", ["shipper", "carrier"])
async def test_both_confirmation_orders_complete_once(journey, source, first):
    deal_id = await accepted_deal(journey, source)
    before = await user_state(journey)
    first_result = await confirm(journey, first, deal_id)
    other = "carrier" if first == "shipper" else "shipper"
    assert first_result["status"] == "delivered"
    assert first_result[first + "_confirmed"] is True
    assert first_result[other + "_confirmed"] is False
    assert first_result["delivered_at"] and first_result["completed_at"] is None
    assert await user_state(journey) == before

    repeated_first = await confirm(journey, first, deal_id)
    assert repeated_first["status"] == "delivered"
    assert repeated_first["delivered_at"] == first_result["delivered_at"]
    completed = await confirm(journey, other, deal_id)
    assert completed["status"] == "completed" and completed["completed_at"]
    assert completed["shipper_confirmed"] is True and completed["carrier_confirmed"] is True
    after = await user_state(journey)
    for role in ("shipper", "carrier"):
        assert after[role]["completed"] == before[role]["completed"] + 1
        assert after[role]["trips"] == before[role]["trips"] + 1
        assert after[role]["received"] == before[role]["received"]
        repeat = await confirm(journey, role, deal_id)
        assert repeat["status"] == "completed"
        assert repeat["completed_at"] == completed["completed_at"]
    assert await user_state(journey) == after


@SOURCES
@pytest.mark.parametrize("terminal", ["canceled", "disputed"])
async def test_confirmation_does_not_revive_canceled_or_disputed_deal(journey, source, terminal):
    deal_id = await accepted_deal(journey, source)
    async with journey["sessions"]() as db:
        await db.execute(update(Deal).where(Deal.id == deal_id).values(status=DealStatus(terminal)))
        await db.commit()
    before = await user_state(journey)
    for role in ("shipper", "carrier"):
        await confirm(journey, role, deal_id, expected=400)
    saved = await personal(journey, "shipper", deal_id)
    assert saved["status"] == terminal
    assert not saved["shipper_confirmed"] and not saved["carrier_confirmed"]
    assert saved["completed_at"] is None
    assert await user_state(journey) == before


@SOURCES
async def test_status_endpoint_cannot_bypass_confirmation_or_review(journey, source):
    deal_id = await accepted_deal(journey, source)
    for role in ("shipper", "carrier"):
        for status in ("completed", "rated"):
            result = await journey["client"].post(f"/api/deals/{deal_id}/status",
                headers=journey["headers"][role], json={"status": status})
            assert result.status_code == 400, result.text
    saved = await personal(journey, "shipper", deal_id)
    assert saved["status"] == "confirmed" and saved["completed_at"] is None
    assert not saved["shipper_confirmed"] and not saved["carrier_confirmed"]


@SOURCES
async def test_status_commands_enforce_roles_and_share_confirmation_state(journey, source):
    deal_id = await accepted_deal(journey, source)
    client, roles = journey["client"], journey["headers"]
    for status in ("loading", "in_transit"):
        denied = await client.post(f"/api/deals/{deal_id}/status",
                                   headers=roles["shipper"], json={"status": status})
        assert denied.status_code == 403, denied.text
        allowed = await client.post(f"/api/deals/{deal_id}/status",
                                    headers=roles["carrier"], json={"status": status})
        assert allowed.status_code == 200, allowed.text
    for role, status in (("shipper", "delivered_carrier"), ("carrier", "delivered_shipper")):
        denied = await client.post(f"/api/deals/{deal_id}/status",
                                   headers=roles[role], json={"status": status})
        assert denied.status_code == 403, denied.text
    delivered = await client.post(f"/api/deals/{deal_id}/status",
        headers=roles["carrier"], json={"status": "delivered_carrier"})
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "delivered"
    assert delivered.json()["carrier_confirmed"] is True
    final = await confirm(journey, "shipper", deal_id)
    assert final["status"] == "completed"
    assert (await personal(journey, "carrier", deal_id))["shipper_confirmed"] is True


@SOURCES
async def test_each_participant_has_one_persisted_review_and_independent_eligibility(journey, source):
    deal_id, completed = await complete(journey, source)
    for role in ("shipper", "carrier"):
        initial = await personal(journey, role, deal_id)
        assert initial["viewer_can_rate"] is True and initial["viewer_has_rated"] is False
        assert initial["my_review"] is None and initial["counterparty_review"] is None
    first_comment = "Аккуратно <b>без HTML</b> & მადლობა"
    first = await review(journey, "shipper", deal_id, score=4, comment=first_comment)
    assert first["status"] == "rated" and first["viewer_has_rated"] is True
    assert first["viewer_can_rate"] is False
    assert first["my_review"]["score"] == 4 and first["my_review"]["comment"] == first_comment
    for role in ("shipper", "carrier"):
        view = await personal(journey, role, deal_id)
        assert view["status"] == "rated" and view["legacy_rating"] is False
        if role == "shipper":
            assert view["viewer_has_rated"] is True and view["viewer_can_rate"] is False
            assert view["my_review"]["comment"] == first_comment
        else:
            assert view["viewer_has_rated"] is False and view["viewer_can_rate"] is True
            assert view["counterparty_review"]["score"] == 4
            assert view["counterparty_review"]["comment"] == first_comment
    before_duplicate = await user_state(journey)
    await review(journey, "shipper", deal_id, score=1, comment="overwrite attempt", expected=409)
    assert await user_state(journey) == before_duplicate

    second_comment = "Договорённость соблюдена, გმადლობთ"
    await review(journey, "carrier", deal_id, score=5, comment=second_comment)
    for role, own_score, own_text, other_score, other_text in [
        ("shipper", 4, first_comment, 5, second_comment),
        ("carrier", 5, second_comment, 4, first_comment),
    ]:
        view = await personal(journey, role, deal_id)
        assert view["viewer_has_rated"] is True and view["viewer_can_rate"] is False
        assert view["my_review"]["score"] == own_score and view["my_review"]["comment"] == own_text
        assert view["counterparty_review"]["score"] == other_score
        assert view["counterparty_review"]["comment"] == other_text
        assert view["my_review"]["created_at"] and view["counterparty_review"]["created_at"]
        repeat = await confirm(journey, role, deal_id)
        assert repeat["status"] == "rated" and repeat["completed_at"] == completed["completed_at"]
    await review(journey, "carrier", deal_id, expected=409)


@SOURCES
async def test_completion_and_rating_counters_are_separate_and_weighted_by_received_ratings(journey, source):
    async with journey["sessions"]() as db:
        await db.execute(update(User).where(User.email == "shipper@example.test").values(
            rating=20, ratings_received_count=2, completed_deals_count=10, trips_count=10))
        await db.execute(update(User).where(User.email == "carrier@example.test").values(
            rating=40, ratings_received_count=3, completed_deals_count=20, trips_count=20))
        await db.commit()
    deal_id, _ = await complete(journey, source)
    done = await user_state(journey)
    assert done["shipper"] == {"rating": 20, "received": 2, "completed": 11, "trips": 11}
    assert done["carrier"] == {"rating": 40, "received": 3, "completed": 21, "trips": 21}
    await review(journey, "shipper", deal_id, score=2, comment="Carrier review")
    first = await user_state(journey)
    assert first["shipper"] == done["shipper"]
    assert first["carrier"] == {"rating": 35, "received": 4, "completed": 21, "trips": 21}
    await review(journey, "carrier", deal_id, score=5, comment="Shipper review")
    rated = await user_state(journey)
    assert rated["shipper"] == {"rating": 30, "received": 3, "completed": 11, "trips": 11}
    assert rated["carrier"] == first["carrier"]
    for role in ("shipper", "carrier"):
        await confirm(journey, role, deal_id)
        await review(journey, role, deal_id, expected=409)
    assert await user_state(journey) == rated


@SOURCES
async def test_review_requires_both_delivery_confirmations(journey, source):
    deal_id = await accepted_deal(journey, source)
    await review(journey, "shipper", deal_id, expected=400)
    await confirm(journey, "carrier", deal_id)
    await review(journey, "carrier", deal_id, expected=400)
    saved = await personal(journey, "shipper", deal_id)
    assert saved["status"] == "delivered"
    assert saved["my_review"] is None and saved["counterparty_review"] is None


async def test_invalid_review_payloads_do_not_write_reviews_or_counters(journey):
    deal_id, _ = await complete(journey, "cargo")
    before = await user_state(journey)
    for payload in ({"score": 0}, {"score": 6}, {"score": True},
                    {"score": 4, "comment": "x" * 2001}):
        result = await journey["client"].post(f"/api/deals/{deal_id}/rate",
            headers=journey["headers"]["shipper"], json=payload)
        assert result.status_code == 422, result.text
    view = await personal(journey, "shipper", deal_id)
    assert view["viewer_can_rate"] is True and view["my_review"] is None
    assert await user_state(journey) == before


@SOURCES
async def test_legacy_rated_deal_has_no_invented_reviewer(journey, source):
    deal_id = await accepted_deal(journey, source)
    async with journey["sessions"]() as db:
        await db.execute(update(Deal).where(Deal.id == deal_id).values(
            status=DealStatus.rated, shipper_confirmed=True, carrier_confirmed=True,
            completed_at=datetime.now(timezone.utc)))
        await db.commit()
    before = await user_state(journey)
    for role in ("shipper", "carrier"):
        view = await personal(journey, role, deal_id)
        assert view["legacy_rating"] is True
        assert view["viewer_has_rated"] is False and view["viewer_can_rate"] is False
        assert view["my_review"] is None and view["counterparty_review"] is None
        await review(journey, role, deal_id, expected=409)
    assert await user_state(journey) == before


@SOURCES
async def test_actual_pdf_uses_accepted_source_and_normal_header_or_legacy_query_auth(journey, source, monkeypatch):
    captured = []
    real_generator = deals.generate_act_pdf

    def capture_and_generate(data):
        captured.append(dict(data))
        return real_generator(data)

    monkeypatch.setattr(deals, "generate_act_pdf", capture_and_generate)
    deal_id, _ = await complete(journey, source)
    client, roles = journey["client"], journey["headers"]
    for lang, role, auth_kind in [("ru", "shipper", "header"), ("ge", "carrier", "query")]:
        params = {"lang": lang}
        headers = roles[role] if auth_kind == "header" else {}
        if auth_kind == "query":
            params["token"] = roles[role]["Authorization"].removeprefix("Bearer ")
        result = await client.get(f"/api/deals/{deal_id}/act.pdf", params=params, headers=headers)
        assert result.status_code == 200, result.text
        assert result.headers["content-type"].startswith("application/pdf")
        assert result.headers["content-disposition"].startswith("attachment;")
        assert result.content.startswith(b"%PDF-") and len(result.content) > 1000
        data = captured[-1]
        assert data["lang"] == lang
        assert data["from_city"] == "Тбилиси" and data["to_city"] == "Батуми"
        assert data["cargo_desc"] == DESCRIPTION
        assert float(data["weight_kg"]) == 3000  # request weight, not offer capacity 10000
        expected_truck_labels = {
            "ru": {"cargo": "Тент", "transport": "Рефрижератор"},
            "ge": {"cargo": "ტენტი", "transport": "რეფრიჟერატორი"},
        }
        assert data["truck_type"] == expected_truck_labels[lang][source]
        assert float(data["agreed_price"]) == 500
        assert data["shipper_name"] == "Test shipper" and data["carrier_name"] == "Test carrier"
    await review(journey, "shipper", deal_id)
    after_review = await client.get(f"/api/deals/{deal_id}/act.pdf", headers=roles["carrier"])
    assert after_review.status_code == 200 and after_review.content.startswith(b"%PDF-")


@SOURCES
async def test_pdf_is_unavailable_before_both_confirmations(journey, source):
    deal_id = await accepted_deal(journey, source)
    for stage in ("confirmed", "delivered"):
        result = await journey["client"].get(f"/api/deals/{deal_id}/act.pdf",
                                             headers=journey["headers"]["shipper"])
        assert result.status_code == 400, (stage, result.text)
        if stage == "confirmed":
            await confirm(journey, "carrier", deal_id)


@SOURCES
async def test_unrelated_account_cannot_confirm_rate_or_download_an_act(journey, source):
    deal_id, _ = await complete(journey, source)
    headers = await outsider(journey)
    client = journey["client"]
    result = await client.post(f"/api/deals/{deal_id}/confirm", headers=headers)
    assert result.status_code == 403, result.text
    result = await client.post(f"/api/deals/{deal_id}/rate", headers=headers,
                               json={"score": 5, "comment": "Not my trade"})
    assert result.status_code == 403, result.text
    result = await client.get(f"/api/deals/{deal_id}/act.pdf", headers=headers)
    assert result.status_code == 403, result.text
    personal_result = await client.get("/api/deals/my", headers=headers)
    assert personal_result.status_code == 200
    assert deal_id not in {row["id"] for row in personal_result.json()["deals"]}


@pytest.mark.parametrize("revocation,expected", [("inactive", 403), ("deleted", 401), ("password", 401)])
async def test_act_respects_account_revocation_for_header_and_query_tokens(journey, revocation, expected):
    deal_id, _ = await complete(journey, "cargo")
    fields = {"is_active": False} if revocation == "inactive" else (
        {"is_deleted": True} if revocation == "deleted" else
        {"password_changed_at": datetime.now(timezone.utc) + timedelta(seconds=60)})
    async with journey["sessions"]() as db:
        await db.execute(update(User).where(User.email == "shipper@example.test").values(**fields))
        await db.commit()
    header = journey["headers"]["shipper"]
    token = header["Authorization"].removeprefix("Bearer ")
    for request in [{"headers": header}, {"params": {"token": token}}]:
        result = await journey["client"].get(f"/api/deals/{deal_id}/act.pdf", **request)
        assert result.status_code == expected, result.text


async def test_act_rejects_missing_or_invalid_credentials(journey):
    deal_id, _ = await complete(journey, "cargo")
    client = journey["client"]
    missing = await client.get(f"/api/deals/{deal_id}/act.pdf")
    assert missing.status_code in (401, 403), missing.text
    for request in [{"headers": {"Authorization": "Bearer invalid"}},
                    {"params": {"token": "invalid"}}]:
        result = await client.get(f"/api/deals/{deal_id}/act.pdf", **request)
        assert result.status_code == 401, result.text
