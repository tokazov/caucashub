"""Railpack gate for loading periods and retry-safe load publication.

Apply revisions 020 and 021 directly using their idempotent additive DDL. The production
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
from sqlalchemy import inspect, String, Numeric, Float


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
