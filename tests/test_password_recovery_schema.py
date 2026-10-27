"""Revision 024 readiness preserves legacy recovery rows and session versions."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from scripts import prepare_loading_period as release
from tests.test_deal_review_schema import review_database  # noqa: F401


pytestmark = pytest.mark.asyncio


async def legacy_recovery_store(engine, *, omit_code=False):
    async with engine.begin() as connection:
        created_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "TIMESTAMP"
        fields = ["id INTEGER PRIMARY KEY", "email TEXT", "expires_at TIMESTAMP",
                  f"created_at {created_type} DEFAULT CURRENT_TIMESTAMP"]
        if not omit_code:
            fields.append("code TEXT")
        await connection.execute(text("CREATE TABLE reset_codes (" + ",\n".join(fields) + ")"))
        if omit_code:
            await connection.execute(text("INSERT INTO reset_codes (id, email) VALUES (77, 'legacy@example.test')"))
        else:
            await connection.execute(text(
                "INSERT INTO reset_codes (id, email, code, expires_at) "
                "VALUES (77, 'legacy@example.test', '123456', :expires)"),
                {"expires": datetime.utcnow() + timedelta(minutes=10)})


async def test_024_repeats_preserving_old_code_attempts_and_password_versions(review_database):
    await legacy_recovery_store(review_database)
    await release.prepare_schema(review_database)
    async with review_database.begin() as connection:
        initial = (await connection.execute(text(
            "SELECT code, attempts, request_count FROM reset_codes WHERE id = 77"))).one()
        assert tuple(initial) == ("123456", 0, 0)
        assert (await connection.execute(text(
            "SELECT SUM(password_version) FROM users"))).scalar_one() == 0
        await connection.execute(text("UPDATE users SET password_version = 7 WHERE id = 1"))
        await connection.execute(text("UPDATE reset_codes SET attempts = 2, request_count = 3 WHERE id = 77"))
        before = (await connection.execute(text("SELECT * FROM reset_codes WHERE id = 77"))).mappings().one()
    await release.prepare_schema(review_database)
    await release.prepare_schema(review_database)
    async with review_database.connect() as connection:
        after = (await connection.execute(text("SELECT * FROM reset_codes WHERE id = 77"))).mappings().one()
        assert dict(after) == dict(before)
        assert (await connection.execute(text(
            "SELECT password_version FROM users WHERE id = 1"))).scalar_one() == 7
        assert (await connection.execute(text("SELECT COUNT(*) FROM users"))).scalar_one() == 2


@pytest.mark.parametrize("target", ["password_version", "attempts", "request_count"])
async def test_024_rejects_existing_incompatible_counter_without_rewriting_legacy_record(review_database, target):
    await legacy_recovery_store(review_database)
    async with review_database.begin() as connection:
        table = "users" if target == "password_version" else "reset_codes"
        await connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {target} TEXT DEFAULT 'incompatible' NOT NULL"))
    with pytest.raises(RuntimeError, match="Password recovery schema is incompatible"):
        await release.prepare_schema(review_database)
    async with review_database.connect() as connection:
        row = (await connection.execute(text(
            "SELECT id, email, code FROM reset_codes WHERE id = 77"))).one()
        assert tuple(row) == (77, "legacy@example.test", "123456")
        assert (await connection.execute(text("SELECT COUNT(*) FROM users"))).scalar_one() == 2


async def test_024_rejects_missing_legacy_columns_without_dropping_rows(review_database):
    await legacy_recovery_store(review_database, omit_code=True)
    with pytest.raises(RuntimeError, match="Password recovery schema is missing columns"):
        await release.prepare_schema(review_database)
    async with review_database.connect() as connection:
        row = (await connection.execute(text("SELECT id, email FROM reset_codes"))).one()
        assert tuple(row) == (77, "legacy@example.test")


async def test_024_creates_missing_store_and_requires_zero_not_null_counters(review_database):
    await release.prepare_schema(review_database)
    async with review_database.begin() as connection:
        await connection.execute(text(
            "INSERT INTO reset_codes (email, code, expires_at) "
            "VALUES ('new@example.test', 'h1.synthetic.digest', :expires)"),
            {"expires": datetime.utcnow() + timedelta(minutes=5)})
        row = (await connection.execute(text(
            "SELECT id, attempts, request_count FROM reset_codes"))).one()
        assert row.id and row.attempts == row.request_count == 0
    with pytest.raises(Exception):
        async with review_database.begin() as connection:
            await connection.execute(text(
                "INSERT INTO reset_codes (email, attempts, request_count) VALUES ('invalid@example.test', NULL, 0)"))
