"""PostgreSQL release contracts for additive 025/026 and typed route filters.

Runs only against explicit TEST_POSTGRES_URL. Every table is contained in a
unique disposable schema; no production schema, account or notification is used.
"""
import os
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import DateTime, JSON, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.database import Base, get_db
from app.models.load import Load, LoadStatus, LoadScope
from app.models.transport_offer import TransportOffer
from app.models.user import User, UserPlan
from app.services.route_locations import catalogue_identity
from scripts.prepare_loading_period import prepare_route_locations, prepare_transport_confirmation

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    not os.environ.get('TEST_POSTGRES_URL'), reason='requires isolated CI PostgreSQL')]


def cargo(number, **updates):
    return dict(id=number, user_id=990101, from_city='Тбилиси', to_city='Батуми',
                truck_type='tent', weight_kg=1000, price_gel=200,
                scope=LoadScope.local, status=LoadStatus.active,
                load_date=datetime.now(timezone.utc) + timedelta(days=3), **updates)


def offer(number, **updates):
    return dict(id=number, user_id=990101, from_city='Тбилиси', to_city='Батуми',
                truck_type='tent', capacity_kg=1000, status='active',
                available_from=datetime.now(timezone.utc) + timedelta(days=3), **updates)


@pytest_asyncio.fixture
async def pg_locations():
    url = os.environ['TEST_POSTGRES_URL']
    for prefix in ('postgres://', 'postgresql://'):
        if url.startswith(prefix):
            url = 'postgresql+asyncpg://' + url[len(prefix):]
            break
    schema = 'test_route_locations_' + uuid4().hex
    assert re.fullmatch(r'test_route_locations_[a-f0-9]{32}', schema)
    bootstrap = create_async_engine(url)
    engine = None
    old_override = app.dependency_overrides.get(get_db)
    try:
        async with bootstrap.begin() as connection:
            await connection.execute(text('CREATE SCHEMA "' + schema + '"'))
        engine = create_async_engine(url, connect_args={
            'server_settings': {'search_path': schema, 'statement_timeout': '30000', 'lock_timeout': '10000'}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            assert (await connection.execute(text('SELECT current_schema()'))).scalar_one() == schema
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            db.add(User(id=990101, email='pg-locations@example.test', hashed_password='unused',
                        company_name='Disposable PG location test', plan=UserPlan.pro_plus))
            await db.flush()
            db.add_all([Load(**cargo(1)), Load(**{**cargo(2), 'to_city': 'Владикавказ'}),
                        TransportOffer(**offer(1)),
                        TransportOffer(**{**offer(2), 'to_city': 'Владикавказ'})])
            await db.commit()
        # Reproduce the production-before-release schema inside this new schema.
        # Only nullable new columns in these disposable fixture tables are dropped.
        async with engine.begin() as connection:
            for table in ('loads', 'transport_offers'):
                for column in ('from_location', 'to_location'):
                    await connection.execute(text('ALTER TABLE ' + table + ' DROP COLUMN ' + column))
            await connection.execute(text('ALTER TABLE transport_offers DROP COLUMN last_confirmed_at'))
            for _ in range(2):
                await connection.run_sync(prepare_transport_confirmation)
                await connection.run_sync(prepare_route_locations)
        async def db_override():
            async with sessions() as db:
                yield db
        app.dependency_overrides[get_db] = db_override
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            yield client, sessions, engine
    finally:
        if old_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old_override
        if engine is not None:
            await engine.dispose()
        async with bootstrap.begin() as connection:
            # schema is a generated constant checked above, never a configured path/name.
            await connection.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
        await bootstrap.dispose()


async def test_postgres_025_026_are_nullable_repeatable_and_preserve_legacy_records(pg_locations):
    _, _, engine = pg_locations
    async with engine.connect() as connection:
        for table in ('loads', 'transport_offers'):
            columns = await connection.run_sync(lambda sync, name=table: {
                row['name']: row for row in inspect(sync).get_columns(name)})
            for name in ('from_location', 'to_location'):
                assert isinstance(columns[name]['type'], JSON)
                assert columns[name]['nullable'] is True and columns[name]['default'] is None
            rows = (await connection.execute(text(
                'SELECT id, from_location, to_location FROM ' + table + ' ORDER BY id'))).all()
            assert rows == [(1, None, None), (2, None, None)]
        columns = await connection.run_sync(lambda sync: {
            row['name']: row for row in inspect(sync).get_columns('transport_offers')})
        confirmed = columns['last_confirmed_at']
        assert isinstance(confirmed['type'], DateTime) and confirmed['type'].timezone
        assert confirmed['nullable'] is True and confirmed['default'] is None
        assert (await connection.execute(text(
            'SELECT id, last_confirmed_at FROM transport_offers ORDER BY id'))).all() == [(1, None), (2, None)]


async def test_postgres_public_gets_use_json_countries_and_checkpoint_keys_before_pagination(pg_locations):
    client, sessions, _ = pg_locations
    checkpoint = catalogue_identity('ge:dariali-checkpoint')
    assert checkpoint and checkpoint['country_iso'] == 'GE'
    russian_pin = {'kind': 'point', 'key': None, 'label': 'Russian warehouse pin',
                   'country_iso': 'RU', 'lat': 43.0241, 'lon': 44.6814,
                   'address': 'Synthetic country-filter regression',
                   'settlement_id': None, 'settlement_key': None, 'aliases': ['Russian warehouse pin']}
    async with sessions() as db:
        # id3 is a renamed Georgian checkpoint without a fabricated city ID.
        # id4 deliberately has legacy GE labels: authoritative JSON RU country
        # must override the old textual/city fallback in the real PostgreSQL SQL.
        for cls, make in ((Load, cargo), (TransportOffer, offer)):
            db.add(cls(**{**make(3), 'from_city': 'Renamed checkpoint gate',
                          'from_location': {**checkpoint, 'label': 'Renamed checkpoint gate'}}))
            db.add(cls(**{**make(4), 'from_location': russian_pin}))
        await db.commit()
    for endpoint, collection in (('loads', 'loads'), ('transport', 'offers')):
        async def get(**params):
            response = await client.get('/api/' + endpoint + '/', params=params)
            assert response.status_code == 200, response.text
            return response.json()
        local = await get(scope='local', limit=200)
        intl = await get(scope='intl', limit=200)
        assert {row['id'] for row in local[collection]} == {1, 3}
        assert {row['id'] for row in intl[collection]} == {2, 4}
        assert all(row['route_scope'] == 'local' for row in local[collection])
        assert all(row['route_scope'] == 'intl' for row in intl[collection])
        json_pin = next(row for row in intl[collection] if row['id'] == 4)
        assert json_pin['from_country_iso'] == 'RU'
        assert json_pin['from_location']['lat'] == russian_pin['lat']
        for params in ({'from_location_key': checkpoint['key']},
                       {'from_city': 'Дарьял'}, {'from_city': 'Dariali'}, {'from_city': 'დარიალი'}):
            found = await get(scope='local', limit=1, **params)
            assert found['total'] == 1
            assert [row['id'] for row in found[collection]] == [3]
            assert found[collection][0]['from_location']['key'] == checkpoint['key']
        inconsistent = await client.get('/api/' + endpoint + '/', params={
            'from_location_key': checkpoint['key'], 'from_city': 'Москва'})
        assert inconsistent.status_code == 422
