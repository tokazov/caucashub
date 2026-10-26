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
            await conn.execute(text("INSERT INTO loads VALUES (1, '2026-01-01')"))
        await release.prepare_schema(engine)
        await release.prepare_schema(engine)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT id, load_date_end FROM loads"))).first() == (1, None)
            assert (await conn.execute(text("SELECT COUNT(*) FROM idempotency_keys"))).scalar_one() == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_release_gate_rejects_store_without_unique_key():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE loads (id INTEGER PRIMARY KEY, load_date TIMESTAMP NOT NULL)"))
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
            await conn.execute(text("INSERT INTO loads VALUES (1, '2026-01-01')"))
        await release.prepare_schema(engine)
        await release.prepare_schema(engine)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT id, load_date_end FROM loads"))).first() == (1, None)
    finally:
        await engine.dispose()
