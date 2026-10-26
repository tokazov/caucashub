"""The Railpack gate applies migration 020 and fails if the column is missing."""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts import prepare_loading_period as release


@pytest.mark.asyncio
async def test_release_gate_repeated_and_preserves_existing_records():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await conn.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("INSERT INTO loads VALUES (1, '2026-01-01')"))
            await conn.execute(text("INSERT INTO users VALUES (1)"))
        await release.prepare_schema(engine)
        await release.prepare_schema(engine)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT id, load_date_end FROM loads"))).first() == (1, None)
            assert (await conn.execute(text("SELECT COUNT(*) FROM idempotency_keys"))).scalar_one() == 0
            assert (await conn.execute(text("SELECT id, truck_type, tonnage FROM users"))).first() == (1, None, None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_release_gate_rejects_store_without_unique_key():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await conn.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("CREATE TABLE idempotency_keys (id INTEGER PRIMARY KEY)"))
        with pytest.raises(RuntimeError, match="unique key"):
            await release.prepare_schema(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_release_gate_rejects_missing_column(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await conn.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        monkeypatch.setattr(release, "migrate_connection", lambda conn: None)
        with pytest.raises(Exception, match="load_date_end"):
            await release.prepare_schema(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="requires isolated CI PostgreSQL")
async def test_release_gate_postgresql():
    url = os.environ["TEST_POSTGRES_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url)
    try:
        # A temporary table shadows any public table and cannot touch production data.
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TEMPORARY TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await conn.execute(text("CREATE TEMPORARY TABLE deals (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("CREATE TEMPORARY TABLE users (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("INSERT INTO loads VALUES (1, '2026-01-01')"))
            await conn.execute(text("INSERT INTO users VALUES (1)"))
        await release.prepare_schema(engine)
        await release.prepare_schema(engine)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT id, load_date_end FROM loads"))).first() == (1, None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("definition, field", [
    ("tonnage TEXT", "tonnage"),
    ("tonnage NUMERIC(1,0)", "tonnage"),
    ("tonnage NUMERIC(10,3)", "tonnage"),
    ("tonnage FLOAT NOT NULL DEFAULT 1", "tonnage"),
    ("truck_type VARCHAR(8)", "truck_type"),
    ("truck_type INTEGER", "truck_type"),
    ("truck_type VARCHAR(32) NOT NULL DEFAULT 'tent'", "truck_type"),
])
async def test_release_gate_rejects_incompatible_carrier_defaults(definition, field):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await conn.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))
            await conn.execute(text(f"CREATE TABLE users (id INTEGER PRIMARY KEY, {definition})"))
        with pytest.raises(RuntimeError, match=field):
            await release.prepare_schema(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_column", ["truck_type VARCHAR(32)", "tonnage FLOAT"])
async def test_release_gate_completes_partial_carrier_schema(existing_column):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await conn.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))
            await conn.execute(text(f"CREATE TABLE users (id INTEGER PRIMARY KEY, {existing_column})"))
            await conn.execute(text("INSERT INTO users (id) VALUES (1)"))
        await release.prepare_schema(engine)
        await release.prepare_schema(engine)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT id, truck_type, tonnage FROM users"))).first() == (1, None, None)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_release_gate_cannot_pass_with_noop_carrier_migration(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await conn.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, truck_type VARCHAR(32))"))
        monkeypatch.setattr(release, "prepare_carrier_defaults", lambda conn: None)
        with pytest.raises(Exception, match="tonnage"):
            await release.prepare_schema(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("definition", [
    "truck_type VARCHAR(9), tonnage FLOAT",
    "truck_type TEXT, tonnage NUMERIC",
])
async def test_release_gate_accepts_compatible_drift_without_rounding(definition):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await conn.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))
            await conn.execute(text(f"CREATE TABLE users (id INTEGER PRIMARY KEY, {definition})"))
            await conn.execute(text("INSERT INTO users (id) VALUES (1)"))
        await release.prepare_schema(engine)
        await release.prepare_schema(engine)
        async with engine.begin() as conn:
            await conn.execute(text(
                "UPDATE users SET truck_type = 'evacuator', tonnage = 24.1256789 WHERE id = 1"))
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT truck_type, tonnage FROM users WHERE id = 1"))).one()
            assert row.truck_type == "evacuator"
            assert float(row.tonnage) == pytest.approx(24.1256789, rel=0, abs=1e-12)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="requires isolated CI PostgreSQL")
@pytest.mark.parametrize("definition, compatible", [
    ("truck_type VARCHAR(8), tonnage DOUBLE PRECISION", False),
    ("truck_type VARCHAR(9), tonnage REAL", False),
    ("truck_type VARCHAR(9), tonnage NUMERIC(1,0)", False),
    ("truck_type VARCHAR(9), tonnage DOUBLE PRECISION", True),
    ("truck_type TEXT, tonnage NUMERIC", True),
])
async def test_release_gate_checks_postgresql_carrier_drift(definition, compatible):
    from uuid import uuid4

    url = os.environ["TEST_POSTGRES_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "test_carrier_schema_" + uuid4().hex
    bootstrap = create_async_engine(url)
    engine = None
    try:
        async with bootstrap.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
            await conn.execute(text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))
            await conn.execute(text(f"CREATE TABLE users (id INTEGER PRIMARY KEY, {definition})"))
            await conn.execute(text("INSERT INTO users (id) VALUES (1)"))
        if not compatible:
            with pytest.raises(RuntimeError, match="truck_type|tonnage"):
                await release.prepare_schema(engine)
        else:
            await release.prepare_schema(engine)
            await release.prepare_schema(engine)
            async with engine.begin() as conn:
                await conn.execute(text(
                    "UPDATE users SET truck_type = 'evacuator', tonnage = 24.1256789 WHERE id = 1"))
            async with engine.connect() as conn:
                row = (await conn.execute(text("SELECT truck_type, tonnage FROM users WHERE id = 1"))).one()
                assert row.truck_type == "evacuator"
                assert float(row.tonnage) == pytest.approx(24.1256789, rel=0, abs=1e-12)
    finally:
        if engine is not None:
            await engine.dispose()
        async with bootstrap.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await bootstrap.dispose()
