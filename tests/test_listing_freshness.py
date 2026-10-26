"""Regression tests for expired listings, tariff slots and Georgian midnight."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base
from app.models.load import Load
from app.models.transport_offer import TransportOffer
from app.models.user import User
from app.routers.loads import LoadCreate, LoadUpdate, get_loads
from app.routers.transport import list_transport_offers
from app.routers.stats import get_counters, invalidate_counters_cache
from app.services.listing_freshness import (
    current_load_conditions, listing_day_start, date_is_current,
)
from app.services.plan_check import check_loads_limit


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(User(id=1, email='freshness@example.test', hashed_password='unused'))
        await session.commit()
        yield session
    invalidate_counters_cache()
    await engine.dispose()


def test_georgian_midnight():
    before = datetime(2026, 10, 26, 19, 59, tzinfo=timezone.utc)
    after = before + timedelta(minutes=1)
    assert listing_day_start(before) == datetime(2026, 10, 25, 20, tzinfo=timezone.utc)
    assert listing_day_start(after) == datetime(2026, 10, 26, 20, tzinfo=timezone.utc)
    assert date_is_current(listing_day_start(after), after)
    assert not date_is_current(listing_day_start(after) - timedelta(microseconds=1), after)


@pytest.mark.asyncio
async def test_feed_counter_and_tariff_use_same_current_loads(db):
    cutoff = listing_day_start()
    for i in range(5):
        db.add(Load(user_id=1, from_city='Tbilisi', to_city='Batumi',
                    weight_kg=1000, truck_type='tent',
                    load_date=cutoff - timedelta(days=i+1)))
    today = Load(user_id=1, from_city='Tbilisi', to_city='Batumi',
                 weight_kg=1000, truck_type='tent', load_date=cutoff)
    demo = Load(user_id=1, from_city='Tbilisi', to_city='Batumi',
                weight_kg=1000, truck_type='tent', load_date=cutoff, is_demo=True)
    db.add_all([today, demo])
    await db.commit()
    result = await get_loads(scope=None, from_city=None, to_city=None,
                            truck_type=None, limit=50, offset=0, db=db)
    assert [row['id'] for row in result['loads']] == [today.id]
    count = (await db.execute(select(func.count()).select_from(Load).where(
        Load.user_id == 1, *current_load_conditions()))).scalar_one()
    assert count == 1
    assert check_loads_limit(SimpleNamespace(plan='free'), count)[0]
    invalidate_counters_cache()
    assert (await get_counters(db))['active_loads'] == count
    # Owners keep their history; the filter does not delete or mutate records.
    assert (await db.execute(select(func.count()).select_from(Load))).scalar_one() == 7


@pytest.mark.asyncio
@pytest.mark.parametrize("available_only", [False, True])
async def test_transport_directory_preserves_carriers_with_expired_dates(db, available_only):
    cutoff = listing_day_start()
    def offer(start, end=None, demo=False, status="active"):
        return TransportOffer(user_id=1, from_city='Tbilisi', to_city='Batumi',
            truck_type='tent', capacity_kg=1000, available_from=start,
            available_to=end, is_demo=demo, status=status)
    expired = offer(cutoff-timedelta(days=2), cutoff-timedelta(seconds=1))
    interval = offer(cutoff-timedelta(days=2), cutoff+timedelta(days=1))
    today = offer(cutoff)
    old_single = offer(cutoff-timedelta(days=1))
    future = offer(cutoff+timedelta(days=2))
    demo = offer(cutoff, demo=True)
    canceled = offer(cutoff, status="canceled")
    taken = offer(cutoff, status="taken")
    db.add_all([expired, interval, today, old_single, future, demo, canceled, taken])
    await db.commit()
    # Omit the option to exercise the default used by the Machines tab.
    options = {"available_only": True} if available_only else {}
    result = await list_transport_offers(from_city=None, to_city=None, truck_type=None,
        min_cap_kg=None, limit=50, offset=0, db=db, authorization=None, **options)
    expected = {interval.id, today.id, future.id}
    if not available_only:
        expected |= {expired.id, old_single.id}
    assert result['total'] == len(expected)
    assert {o['id'] for o in result['offers']} == expected
    for row in result['offers']:
        assert row['dates_expired'] == (row['id'] in {expired.id, old_single.id})
        assert row['owner_phone'] is None
        assert row['owner_email'] is None
    # Visibility must never renew dates, delete history, or change user accounts.
    assert (await db.execute(select(func.count()).select_from(TransportOffer))).scalar_one() == 8
    assert (await db.execute(select(func.count()).select_from(User))).scalar_one() == 1
    await db.refresh(expired)
    assert not date_is_current(expired.available_to)


@pytest.mark.parametrize('schema', [LoadCreate, LoadUpdate])
@pytest.mark.parametrize('value', ['', '   ', 'x'*101])
def test_empty_or_overlong_city_rejected(schema, value):
    with pytest.raises(ValidationError):
        schema(from_city=value, to_city='Batumi', weight_kg=1000)

@pytest.mark.asyncio
async def test_can_publish_after_five_expired_loads(db, monkeypatch):
    from fastapi import BackgroundTasks, HTTPException
    from starlette.requests import Request
    from app.routers.loads import create_load
    from app.services import exchange_rate, idempotency

    async def rate():
        return 2.7
    async def check(*args, **kwargs):
        return None, False
    async def save(*args, **kwargs):
        return None
    monkeypatch.setattr(exchange_rate, 'get_usd_gel_rate', rate)
    monkeypatch.setattr(idempotency, 'check_idempotency', check)
    monkeypatch.setattr(idempotency, 'save_idempotency', save)
    cutoff = listing_day_start()
    for _ in range(5):
        db.add(Load(user_id=1, from_city='Tbilisi', to_city='Batumi',
            weight_kg=1000, truck_type='tent', load_date=cutoff-timedelta(days=1)))
    await db.commit()
    user = await db.get(User, 1)
    request = Request({'type': 'http', 'headers': []})
    data = LoadCreate(from_city='Tbilisi', to_city='Batumi', weight_kg=1000,
                      price_gel=500, load_date=datetime.now(timezone.utc))
    for _ in range(5):
        await create_load(data, request, BackgroundTasks(), db, user)
    with pytest.raises(HTTPException) as error:
        await create_load(data, request, BackgroundTasks(), db, user)
    assert error.value.status_code == 403
    assert error.value.detail['current'] == 5
