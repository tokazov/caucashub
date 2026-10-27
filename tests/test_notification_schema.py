"""Additive notification-store readiness on isolated SQLite/PostgreSQL schemas.

The real Railpack gate applies revision 023. These tests target stored-event
preservation, deduplication and the queue constraints needed before app startup.
"""
import json

import pytest
from sqlalchemy import (CheckConstraint, MetaData, Table, UniqueConstraint,
                        inspect, text)
from sqlalchemy.exc import IntegrityError

from app.models.notification import NotificationDelivery
from scripts import prepare_loading_period as release
from tests.test_deal_review_schema import review_database  # noqa: F401


pytestmark = pytest.mark.asyncio
KEYS = [
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000003",
]
NEW_KEY = "00000000-0000-4000-8000-000000000009"


async def seed_store(engine):
    async with engine.begin() as connection:
        for identifier, recipient in [(1, 1), (2, 2)]:
            await connection.execute(text(
                "INSERT INTO notifications "
                "(id, recipient_id, actor_id, event_key, kind, data, read_at) "
                "VALUES (:id, :recipient, 1, 'deal:1:created', 'deal_created', :data, CURRENT_TIMESTAMP)"),
                {"id": identifier, "recipient": recipient,
                 "data": json.dumps({"source": "cargo", "deal_id": 1,
                                     "from_city": "Тбилиси", "to_city": "ბათუმი"})})
        for identifier, notification_id, channel, key in [
            (1, 1, "email", KEYS[0]), (2, 1, "telegram", KEYS[1]), (3, 2, "email", KEYS[2]),
        ]:
            await connection.execute(text(
                "INSERT INTO notification_deliveries "
                "(id, notification_id, channel, status, attempts, idempotency_key, last_error) "
                "VALUES (:id, :notification, :channel, 'failed', 3, :key, 'provider_unavailable')"),
                {"id": identifier, "notification": notification_id, "channel": channel, "key": key})


async def snapshot(engine):
    async with engine.connect() as connection:
        inbox = (await connection.execute(text(
            "SELECT id, recipient_id, actor_id, event_key, kind, data, created_at, read_at "
            "FROM notifications ORDER BY id"))).mappings().all()
        deliveries = (await connection.execute(text(
            "SELECT id, notification_id, channel, status, attempts, idempotency_key, "
            "next_attempt_at, last_attempt_at, locked_until, claim_token, provider_id, "
            "last_error, created_at FROM notification_deliveries ORDER BY id"))).mappings().all()
    return [dict(row) for row in inbox], [dict(row) for row in deliveries]


async def test_gate_repeats_without_changing_inbox_or_delivery_history(review_database):
    await release.prepare_schema(review_database)
    await seed_store(review_database)
    before = await snapshot(review_database)
    # Same event reaches two people; each person's event can have both channels.
    assert len(before[0]) == 2 and len(before[1]) == 3
    assert all(row["read_at"] and row["created_at"] for row in before[0])
    assert all(row["attempts"] == 3 and row["status"] == "failed" for row in before[1])
    await release.prepare_schema(review_database)
    await release.prepare_schema(review_database)
    assert await snapshot(review_database) == before
    async with review_database.connect() as connection:
        assert (await connection.execute(text("SELECT COUNT(*) FROM users"))).scalar_one() == 2
        assert (await connection.execute(text("SELECT COUNT(*) FROM deals"))).scalar_one() == 2


@pytest.mark.parametrize("violation", [
    "event_recipient", "notification_channel", "idempotency_key", "channel", "status", "attempts",
])
async def test_database_rejects_duplicate_events_deliveries_and_invalid_queue_values(review_database, violation):
    await release.prepare_schema(review_database)
    await seed_store(review_database)
    before = await snapshot(review_database)
    with pytest.raises(IntegrityError):
        async with review_database.begin() as connection:
            if violation == "event_recipient":
                await connection.execute(text(
                    "INSERT INTO notifications (id, recipient_id, event_key, kind, data) "
                    "VALUES (9, 1, 'deal:1:created', 'deal_created', '{}')"))
            else:
                values = {"notification": 2, "channel": "telegram", "status": "pending",
                          "attempts": 0, "key": NEW_KEY}
                if violation == "notification_channel":
                    values.update(notification=1, channel="email")
                elif violation == "idempotency_key":
                    values["key"] = KEYS[0]
                elif violation == "channel":
                    values["channel"] = "sms"
                elif violation == "status":
                    values["status"] = "queued"
                elif violation == "attempts":
                    values["attempts"] = -1
                await connection.execute(text(
                    "INSERT INTO notification_deliveries "
                    "(id, notification_id, channel, status, attempts, idempotency_key) "
                    "VALUES (9, :notification, :channel, :status, :attempts, :key)"), values)
    assert await snapshot(review_database) == before


async def test_gate_rejects_partial_notifications_without_dropping_existing_record(review_database):
    async with review_database.begin() as connection:
        await connection.execute(text(
            "CREATE TABLE notifications (id INTEGER NOT NULL PRIMARY KEY, legacy_marker TEXT)"))
        await connection.execute(text(
            "INSERT INTO notifications (id, legacy_marker) VALUES (77, 'preserve-existing-inbox')"))
    with pytest.raises(RuntimeError, match=r"Notification schema is incompatible: notifications.recipient_id"):
        await release.prepare_schema(review_database)
    async with review_database.connect() as connection:
        row = (await connection.execute(text(
            "SELECT id, legacy_marker FROM notifications"))).one()
        assert tuple(row) == (77, "preserve-existing-inbox")


def create_drifted_delivery_table(connection, drift):
    # Start with the real mapped table, changing exactly the target constraint.
    # SQLAlchemy emits multiline DDL, so SQLite reflection reads each CHECK
    # independently, matching the actual Alembic-created schema.
    metadata = MetaData()
    Table("notifications", metadata, autoload_with=connection)
    delivery = NotificationDelivery.__table__.to_metadata(metadata)
    target = {
        "attempts": "ck_notification_deliveries_attempts",
        "status": "ck_notification_deliveries_status",
        "channel_unique": "uq_notification_deliveries_channel",
    }[drift]
    matches = [constraint for constraint in delivery.constraints if constraint.name == target]
    assert len(matches) == 1
    delivery.constraints.remove(matches[0])
    if drift == "attempts":
        delivery.append_constraint(CheckConstraint("attempts >= -1", name=target))
    elif drift == "status":
        delivery.append_constraint(CheckConstraint("status IN ('pending', 'sent')", name=target))
    delivery.create(connection)
    inspector = inspect(connection)
    checks = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints("notification_deliveries")}
    assert set(checks) == {
        "ck_notification_deliveries_attempts", "ck_notification_deliveries_channel",
        "ck_notification_deliveries_status"}
    unique = {frozenset(item["column_names"])
              for item in inspector.get_unique_constraints("notification_deliveries")}
    assert frozenset({"idempotency_key"}) in unique
    assert (frozenset({"notification_id", "channel"}) in unique) == (drift != "channel_unique")
    if drift == "attempts":
        assert "-1" in checks[target]
    if drift == "status":
        assert "sending" not in checks[target]


@pytest.mark.parametrize("drift", ["attempts", "status", "channel_unique"])
async def test_gate_fails_closed_for_drifted_delivery_constraints_and_preserves_rows(review_database, drift):
    await release.prepare_schema(review_database)
    await seed_store(review_database)
    inbox_before, _ = await snapshot(review_database)
    async with review_database.begin() as connection:
        await connection.execute(text("DROP TABLE notification_deliveries"))
        await connection.run_sync(lambda sync: create_drifted_delivery_table(sync, drift))
        await connection.execute(text(
            "INSERT INTO notification_deliveries "
            "(id, notification_id, channel, status, attempts, idempotency_key) "
            "VALUES (55, 1, 'email', 'pending', 0, :key)"), {"key": NEW_KEY})
    before = await snapshot(review_database)
    assert before[0] == inbox_before and len(before[1]) == 1
    expected = "channel uniqueness" if drift == "channel_unique" else "delivery constraints"
    with pytest.raises(RuntimeError, match=expected):
        await release.prepare_schema(review_database)
    assert await snapshot(review_database) == before
