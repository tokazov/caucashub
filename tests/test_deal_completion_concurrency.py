"""Real PostgreSQL races through authenticated HTTP endpoints, no real delivery."""
import asyncio

import pytest
from sqlalchemy import func, select

from tests.test_publication_journeys import journey, cargo
from app.models.deal import Deal
from app.models.deal_review import DealReview
from app.models.user import User
from app.models.status_change import StatusChange
from app.routers import deals


async def confirmed_deal(context):
    client, headers = context["client"], context["headers"]
    created = await client.post("/api/loads/", headers=headers["shipper"], json=cargo())
    assert created.status_code == 200, created.text
    response = await client.post(f"/api/responses/load/{created.json()['id']}",
                                 headers=headers["carrier"], json={"price": 500})
    assert response.status_code == 200, response.text
    accepted = await client.post(f"/api/responses/accept/{response.json()['response_id']}",
                                 headers=headers["shipper"])
    assert accepted.status_code == 200, accepted.text
    return accepted.json()["deal_id"]


async def confirm(context, deal_id, role):
    return await context["client"].post(f"/api/deals/{deal_id}/confirm",
                                         headers=context["headers"][role])


async def rate(context, deal_id, role, score, comment):
    return await context["client"].post(f"/api/deals/{deal_id}/rate",
        headers=context["headers"][role], json={"score": score, "comment": comment})


def require_postgresql(context, monkeypatch):
    if context["engine"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock regression; SQLite has no FOR UPDATE")
    monkeypatch.setattr(deals, "_send_completed_emails", lambda *args: None)


async def assert_counts(context, completed, ratings):
    async with context["sessions"]() as session:
        users = (await session.execute(select(User).order_by(User.id))).scalars().all()
        assert [user.completed_deals_count for user in users] == [completed, completed]
        assert [user.trips_count for user in users] == [completed, completed]
        assert [user.ratings_received_count for user in users] == ratings


@pytest.mark.asyncio
async def test_parallel_confirmations_complete_once_without_losing_flags(journey, monkeypatch):
    require_postgresql(journey, monkeypatch)
    deal_id = await confirmed_deal(journey)
    replies = await asyncio.wait_for(asyncio.gather(
        confirm(journey, deal_id, "shipper"), confirm(journey, deal_id, "carrier")), timeout=20)
    assert [response.status_code for response in replies] == [200, 200]
    final = await confirm(journey, deal_id, "shipper")
    assert final.json()["status"] == "completed"
    assert final.json()["shipper_confirmed"] and final.json()["carrier_confirmed"]
    timestamp = final.json()["completed_at"]
    again = await confirm(journey, deal_id, "carrier")
    assert again.json()["completed_at"] == timestamp
    await assert_counts(journey, completed=1, ratings=[0, 0])
    async with journey["sessions"]() as session:
        count = (await session.execute(select(func.count()).select_from(StatusChange).where(
            StatusChange.entity_type == "deal", StatusChange.entity_id == deal_id,
            StatusChange.to_status == "completed"))).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_parallel_duplicate_rating_is_stored_and_counted_once(journey, monkeypatch):
    require_postgresql(journey, monkeypatch)
    deal_id = await confirmed_deal(journey)
    assert (await confirm(journey, deal_id, "shipper")).status_code == 200
    assert (await confirm(journey, deal_id, "carrier")).status_code == 200
    replies = await asyncio.wait_for(asyncio.gather(
        rate(journey, deal_id, "shipper", 1, "first"),
        rate(journey, deal_id, "shipper", 5, "second")), timeout=20)
    assert sorted(response.status_code for response in replies) == [200, 409]
    winner = next(response.json() for response in replies if response.status_code == 200)
    async with journey["sessions"]() as session:
        rows = (await session.execute(select(DealReview))).scalars().all()
        assert len(rows) == 1 and rows[0].score == winner["score"]
        recipient = await session.get(User, rows[0].recipient_id)
        assert recipient.ratings_received_count == 1 and recipient.rating == winner["score"] * 10
    await assert_counts(journey, completed=1, ratings=[0, 1])


@pytest.mark.asyncio
async def test_parallel_opposite_reviews_both_succeed(journey, monkeypatch):
    require_postgresql(journey, monkeypatch)
    deal_id = await confirmed_deal(journey)
    await confirm(journey, deal_id, "shipper")
    await confirm(journey, deal_id, "carrier")
    replies = await asyncio.wait_for(asyncio.gather(
        rate(journey, deal_id, "shipper", 4, "carrier review"),
        rate(journey, deal_id, "carrier", 2, "shipper review")), timeout=20)
    assert [response.status_code for response in replies] == [200, 200], [response.text for response in replies]
    await assert_counts(journey, completed=1, ratings=[1, 1])
    async with journey["sessions"]() as session:
        assert (await session.execute(select(func.count()).select_from(DealReview))).scalar_one() == 2
        row = await session.get(Deal, deal_id)
        assert row.status.value == "rated"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["completion", "rating"])
async def test_parallel_different_deals_refresh_shared_user_rows(journey, monkeypatch, phase):
    require_postgresql(journey, monkeypatch)
    ids = [await confirmed_deal(journey), await confirmed_deal(journey)]
    for deal_id in ids:
        await confirm(journey, deal_id, "shipper")
        if phase == "rating":
            await confirm(journey, deal_id, "carrier")

    original = deals._locked_users
    barrier = asyncio.Event()
    arrived = 0

    async def synchronized_user_lock(db, user_ids):
        nonlocal arrived
        # Both Deal selectin loaders must see the old User state before either
        # locks it. The locked query must then refresh that identity-map entry.
        arrived += 1
        if arrived == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=10)
        return await original(db, user_ids)

    monkeypatch.setattr(deals, "_locked_users", synchronized_user_lock)
    if phase == "completion":
        replies = await asyncio.wait_for(asyncio.gather(
            confirm(journey, ids[0], "carrier"), confirm(journey, ids[1], "carrier")), timeout=20)
        assert [response.status_code for response in replies] == [200, 200]
        await assert_counts(journey, completed=2, ratings=[0, 0])
    else:
        replies = await asyncio.wait_for(asyncio.gather(
            rate(journey, ids[0], "shipper", 1, "first deal"),
            rate(journey, ids[1], "shipper", 5, "second deal")), timeout=20)
        assert [response.status_code for response in replies] == [200, 200]
        await assert_counts(journey, completed=2, ratings=[0, 2])
        async with journey["sessions"]() as session:
            users = (await session.execute(select(User).order_by(User.id))).scalars().all()
            assert users[1].rating == 30
