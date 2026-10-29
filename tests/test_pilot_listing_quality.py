"""Pilot quality checks use disposable SQLite, never production data."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base
from app.models.user import User
from app.models.deal import Deal, DealStatus
from app.models.deal_review import DealReview
from app.models.transport_offer import TransportOffer
from app.models.truck import Truck
from app.models.load import Load
from app.routers.transport import (TransportOfferCreate, TransportOfferPatch,
    create_transport_offer, update_transport_offer, list_transport_offers,
    get_transport_offer)
from app.routers.trucks import TruckCreate, get_trucks
from app.routers.users import UpdateProfileRequest, update_me, get_user
from app.routers.loads import get_loads
from app.carrier_profile import CarrierProfileFields
from app.services.public_ratings import public_ratings, public_rating_fields
from app.services.listing_freshness import transport_availability_metadata, listing_day_start
from app.routers.stats import get_counters, invalidate_counters_cache
from scripts.prepare_loading_period import prepare_transport_confirmation


def offer_data(**overrides):
    return dict(dict(from_city="Tbilisi", to_city="Batumi", truck_type="tent",
                capacity_kg=20000, available_from=datetime.now(timezone.utc) + timedelta(days=1),
                ), **overrides)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all([User(id=1, email="carrier@example.test", hashed_password="unused",
                             company_name="Carrier", rating=50, ratings_received_count=99,
                             truck_type="gazel", tonnage=3),
                         User(id=2, email="shipper@example.test", hashed_password="unused"),
                         User(id=3, email="outsider@example.test", hashed_password="unused")])
        await session.commit()
        yield session
    invalidate_counters_cache()
    await engine.dispose()


@pytest.mark.parametrize("value", [True, 0, -1, 100001, float("inf"), float("nan")])
@pytest.mark.parametrize("model", [TransportOfferCreate, TransportOfferPatch, TruckCreate])
def test_capacity_rejects_nonfinite_boolean_and_out_of_range(model, value):
    data = offer_data()
    if model is TruckCreate:
        data["available_from"] = "Tbilisi"
    data["capacity_kg"] = value
    with pytest.raises(ValidationError):
        model(**data)


@pytest.mark.parametrize("model", [TransportOfferCreate, TransportOfferPatch, TruckCreate])
def test_van_capacity_matches_catalogue_label_on_all_writes(model):
    data = offer_data()
    if model is TruckCreate:
        data["available_from"] = "Tbilisi"
    data.update(truck_type="gazel", capacity_kg=3500)
    assert model(**data).capacity_kg == 3500
    for capacity in (3500.01, 5000, 100000):
        with pytest.raises(ValidationError):
            model(**{**data, "capacity_kg": capacity})


def test_carrier_defaults_obey_same_body_capacity_rule():
    assert CarrierProfileFields(truck_type="gazel", tonnage=3.5).tonnage == 3.5
    with pytest.raises(ValidationError):
        CarrierProfileFields(truck_type="gazel", tonnage=100)


@pytest.mark.asyncio
async def test_partial_offer_edit_rejects_invalid_merged_body_without_side_effect(db):
    offer = TransportOffer(user_id=1, **offer_data())
    db.add(offer)
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await update_transport_offer(offer.id,
            TransportOfferPatch(truck_type="gazel", price=77), db, await db.get(User, 1))
    assert error.value.status_code == 422
    await db.refresh(offer)
    assert offer.truck_type == "tent" and offer.price is None
    van = TransportOffer(user_id=1, **{**offer_data(), "truck_type": "gazel", "capacity_kg": 3000})
    db.add(van)
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await update_transport_offer(van.id, TransportOfferPatch(capacity_kg=100000),
                                     db, await db.get(User, 1))
    assert error.value.status_code == 422
    await db.refresh(van)
    assert van.capacity_kg == 3000
    legacy = TransportOffer(user_id=1, **{**offer_data(), "truck_type": "gazel", "capacity_kg": 100000})
    db.add(legacy)
    await db.commit()
    result = await update_transport_offer(legacy.id, TransportOfferPatch(status="canceled"),
                                         db, await db.get(User, 1))
    assert result["offer"]["status"] == "canceled"
    assert result["offer"]["capacity_valid"] is False


@pytest.mark.asyncio
async def test_partial_profile_capacity_edit_checks_existing_body_before_other_fields(db):
    user = await db.get(User, 1)
    with pytest.raises(HTTPException) as error:
        await update_me(UpdateProfileRequest(tonnage=100, city="Must not persist"), db, user)
    assert error.value.status_code == 422
    await db.refresh(user)
    assert user.tonnage == 3 and user.city is None


@pytest.mark.asyncio
async def test_publish_and_explicit_confirmation_are_the_only_confirmation_sources(db):
    user = await db.get(User, 1)
    before = datetime.now(timezone.utc)
    result = await create_transport_offer(TransportOfferCreate(**offer_data()), BackgroundTasks(), db, user)
    assert result["offer"]["last_confirmed_at"]
    assert result["offer"]["availability_status"] == "confirmed"
    offer = await db.get(TransportOffer, result["offer"]["id"])
    first = offer.last_confirmed_at
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    assert first >= before
    await update_transport_offer(offer.id, TransportOfferPatch(price=700), db, user)
    await update_transport_offer(offer.id, TransportOfferPatch(
        price=800, available_from=offer.available_from, available_to=offer.available_to), db, user)
    await get_transport_offer(offer.id, db, None)  # local view count must not renew availability
    await db.refresh(offer)
    assert offer.last_confirmed_at.replace(tzinfo=timezone.utc) == first
    result = await update_transport_offer(offer.id, TransportOfferPatch(confirm_availability=True), db, user)
    assert datetime.fromisoformat(result["offer"]["last_confirmed_at"]) >= first


def test_staleness_is_mark_only_and_never_invents_legacy_confirmation():
    now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    offer = SimpleNamespace(available_from=now + timedelta(days=2), available_to=None,
                            last_confirmed_at=None, created_at=now, updated_at=now)
    assert transport_availability_metadata(offer, now) == {
        "last_confirmed_at": None, "availability_status": "unconfirmed", "confirmation_ttl_days": 7}
    offer.last_confirmed_at = now - timedelta(days=8)
    assert transport_availability_metadata(offer, now)["availability_status"] == "stale"
    offer.available_from = now - timedelta(days=1)
    assert transport_availability_metadata(offer, now)["availability_status"] == "expired"


@pytest.mark.asyncio
async def test_expired_confirmation_requires_new_dates_and_legacy_directory_is_not_deleted(db):
    old = TransportOffer(user_id=1, **{**offer_data(), "available_from": listing_day_start() - timedelta(days=1)})
    db.add(old)
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await update_transport_offer(old.id, TransportOfferPatch(confirm_availability=True), db,
                                     await db.get(User, 1))
    assert error.value.status_code == 422
    result = await list_transport_offers(from_city=None, to_city=None, truck_type=None,
        min_cap_kg=None, limit=50, offset=0, available_only=False, db=db, authorization=None)
    assert result["offers"][0]["id"] == old.id
    assert result["offers"][0]["last_confirmed_at"] is None
    assert result["offers"][0]["availability_status"] == "expired"


@pytest.mark.asyncio
async def test_public_ratings_ignore_legacy_five_stars_and_unconfirmed_or_unattributed_reviews(db):
    assert public_rating_fields((await public_ratings(db, [1])).get(1)) == {
        "rating": None, "review_count": 0, "rating_verified": False, "is_new_carrier": True}
    for index, status, confirmed, score, rater in (
        (1, DealStatus.rated, True, 4, 2), (2, DealStatus.completed, True, 2, 2),
        (3, DealStatus.confirmed, False, 5, 2), (4, DealStatus.completed, False, 5, 2),
        (5, DealStatus.completed, True, 5, 3)):
        db.add(Deal(id=index, shipper_id=2, carrier_id=1, status=status,
                    shipper_confirmed=confirmed, carrier_confirmed=confirmed))
        await db.flush()
        db.add(DealReview(deal_id=index, rater_id=rater, recipient_id=1, score=score))
    await db.commit()
    expected = {"rating": 3.0, "review_count": 2, "rating_verified": True, "is_new_carrier": False}
    assert public_rating_fields((await public_ratings(db, [1])).get(1)) == expected
    assert {key: (await get_user(1, db))[key] for key in expected} == expected
    db.add(TransportOffer(user_id=1, **offer_data()))
    db.add(Truck(user_id=1, truck_type="tent", capacity_kg=20000,
                 available_from="Tbilisi", is_available=True))
    db.add(Load(user_id=1, from_city="Tbilisi", to_city="Batumi", weight_kg=1000,
                truck_type="tent", load_date=listing_day_start()))
    await db.commit()
    offers = await list_transport_offers(from_city=None,to_city=None,truck_type=None,
        min_cap_kg=None,limit=50,offset=0,available_only=False,db=db,authorization=None)
    trucks = await get_trucks(None,None,50,0,db)
    loads = await get_loads(None,None,None,None,50,0,db)
    for row in (offers["offers"][0],trucks["trucks"][0],loads["loads"][0]):
        assert {key:row[key] for key in expected} == expected
    user = await db.get(User,1)
    assert user.rating == 50 and user.ratings_received_count == 99  # history untouched


@pytest.mark.asyncio
async def test_confirmation_schema_adds_nullable_column_without_backfill_and_is_repeatable():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE transport_offers (id INTEGER PRIMARY KEY, updated_at TIMESTAMP)"))
        await connection.execute(text("INSERT INTO transport_offers VALUES (1, '2026-10-29')"))
        await connection.run_sync(prepare_transport_confirmation)
        await connection.run_sync(prepare_transport_confirmation)
        assert (await connection.execute(text("SELECT last_confirmed_at FROM transport_offers WHERE id=1"))).scalar_one() is None
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("definition", ["TEXT", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"])
async def test_confirmation_schema_rejects_incompatible_or_fabricated_defaults(definition):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE transport_offers (id INTEGER PRIMARY KEY, last_confirmed_at " + definition + ")"))
            with pytest.raises(RuntimeError, match="last_confirmed_at"):
                await connection.run_sync(prepare_transport_confirmation)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stats_describe_registered_profiles_without_claiming_verified_companies(db):
    invalidate_counters_cache()
    result = await get_counters(db)
    assert result["registered_profiles"] == 3
    assert result["named_profiles"] == 1
    assert result["companies_metric"] == "named_user_profiles_not_verified_legal_entities"
    assert result["as_of"] == result["cached_at"]
