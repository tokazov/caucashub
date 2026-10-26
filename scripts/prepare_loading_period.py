"""Railpack gate for loading periods and retry-safe load publication.

Apply revisions 020, 021 and 022 directly using their idempotent additive DDL. The production
database has a history of startup fallback migrations, so this release must
not stamp or replay unrelated Alembic revisions without a schema audit.
"""
import asyncio
import importlib.util
from pathlib import Path
import sys

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy import inspect, String, Numeric, Float, Integer, DateTime


def migrate_connection(connection):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/020_load_date_end.py"
    spec = importlib.util.spec_from_file_location("loading_period_release_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


def prepare_carrier_defaults(connection):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/021_carrier_profile_defaults.py"
    spec = importlib.util.spec_from_file_location("carrier_defaults_release_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    from app.models.load import TruckType

    columns = {column["name"]: column for column in inspect(connection).get_columns("users")}
    truck = columns.get("truck_type")
    longest_code = max(len(member.value) for member in TruckType)
    if (truck is None or not truck["nullable"]
            or not isinstance(truck["type"], String)
            or (truck["type"].length is not None and truck["type"].length < longest_code)):
        raise RuntimeError("Carrier profile schema is missing or incompatible: truck_type")

    tonnage = columns.get("tonnage")
    capacity_type = tonnage["type"] if tonnage is not None else None
    if isinstance(capacity_type, Float):
        # SQLite REAL is binary64. PostgreSQL REAL/float4 is binary32 even when
        # reflection leaves precision unset; it would round valid API values.
        precision = capacity_type.precision
        compatible = connection.dialect.name == "sqlite" or (
            capacity_type.__visit_name__ != "REAL" and (precision is None or precision >= 53))
    else:
        # Constrained NUMERIC(p,s) may round fractional tonnes or overflow them.
        compatible = (isinstance(capacity_type, Numeric)
                      and capacity_type.precision is None and capacity_type.scale is None)
    if tonnage is None or not tonnage["nullable"] or not compatible:
        raise RuntimeError("Carrier profile schema is missing or incompatible: tonnage")


def prepare_idempotency(connection):
    # Create just the missing store; do not replay or stamp migration history.
    from app.models.idempotency_key import IdempotencyKey

    IdempotencyKey.__table__.create(connection, checkfirst=True)
    expected = {"scope", "user_id", "key"}
    unique_constraints = inspect(connection).get_unique_constraints("idempotency_keys")
    if not any(set(item["column_names"]) == expected for item in unique_constraints):
        raise RuntimeError("Idempotency store is missing its unique key")


def prepare_deal_reviews(connection):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/022_deal_reviews.py"
    spec = importlib.util.spec_from_file_location("deal_reviews_release_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()

    inspector = inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns("deal_reviews")}
    required = {"id", "deal_id", "rater_id", "recipient_id", "score", "comment", "created_at"}
    if not required.issubset(columns):
        raise RuntimeError("Deal review schema is missing columns")
    for name in ("id", "deal_id", "rater_id", "recipient_id", "score"):
        if not isinstance(columns[name]["type"], Integer) or columns[name]["nullable"]:
            raise RuntimeError("Deal review schema is incompatible: " + name)
    primary = inspector.get_pk_constraint("deal_reviews").get("constrained_columns") or []
    if primary != ["id"]:
        raise RuntimeError("Deal review schema is missing its id primary key")
    identifier = columns["id"]
    if connection.dialect.name == "postgresql":
        default = identifier.get("default") or ""
        if not identifier.get("identity") and not default.lower().startswith("nextval("):
            raise RuntimeError("Deal review schema is missing generated ids")
    elif connection.dialect.name == "sqlite" and str(identifier["type"]).upper() != "INTEGER":
        raise RuntimeError("Deal review schema requires SQLite INTEGER generated ids")
    comment = columns["comment"]
    if (not isinstance(comment["type"], String) or not comment["nullable"]
            or (comment["type"].length is not None and comment["type"].length < 2000)):
        raise RuntimeError("Deal review schema is incompatible: comment")
    created = columns["created_at"]
    if (not isinstance(created["type"], DateTime) or created["nullable"] or created["default"] is None
            or (connection.dialect.name == "postgresql" and not created["type"].timezone)):
        raise RuntimeError("Deal review schema is incompatible: created_at")
    unique = inspector.get_unique_constraints("deal_reviews")
    if not any(set(item["column_names"]) == {"deal_id", "rater_id"} for item in unique):
        raise RuntimeError("Deal review schema is missing its per-participant unique key")
    checks = {item["name"]: "".join(item["sqltext"].lower().split()).replace("(", "").replace(")", "")
              for item in inspector.get_check_constraints("deal_reviews")}
    if checks.get("ck_deal_reviews_score_range") != "score>=1andscore<=5":
        raise RuntimeError("Deal review schema is missing its score range check")
    if checks.get("ck_deal_reviews_distinct_people") != "rater_id<>recipient_id":
        raise RuntimeError("Deal review schema is missing its distinct participant check")
    expected_fks = {(("deal_id",), "deals", ("id",)), (("rater_id",), "users", ("id",)),
                    (("recipient_id",), "users", ("id",))}
    fks = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
           for item in inspector.get_foreign_keys("deal_reviews")}
    if not expected_fks.issubset(fks):
        raise RuntimeError("Deal review schema is missing participant/deal foreign keys")


async def prepare_schema(engine):
    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            await connection.execute(text("SET LOCAL statement_timeout = '60s'"))
        await connection.run_sync(migrate_connection)
        # A no-op/failed migration must not allow the new application to start.
        await connection.execute(text("SELECT load_date, load_date_end FROM loads LIMIT 0"))
        await connection.run_sync(prepare_carrier_defaults)
        await connection.execute(text("SELECT truck_type, tonnage FROM users LIMIT 0"))
        await connection.run_sync(prepare_deal_reviews)
        await connection.execute(text("SELECT id, deal_id, rater_id, recipient_id, score, comment, created_at FROM deal_reviews LIMIT 0"))
        await connection.run_sync(prepare_idempotency)
        await connection.execute(text(
            "SELECT key, user_id, scope, request_hash, response_status, "
            "response_body, created_at, expires_at FROM idempotency_keys LIMIT 0"
        ))


async def run():
    # Use the same URL/driver normalization as the application; never print it.
    from app.database import engine

    try:
        await prepare_schema(engine)
    finally:
        await engine.dispose()


def main():
    try:
        asyncio.run(run())
    except Exception as error:
        print(f"Loading-period pre-deploy failed ({type(error).__name__}); deployment stopped.", file=sys.stderr)
        return 1
    print("Loading-period schema ready; existing records preserved.")
    print("Idempotency schema ready; retry-safe publication enabled.")
    print("Carrier profile schema ready; optional defaults enabled.")
    print("Deal review schema ready; per-participant reviews enabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
