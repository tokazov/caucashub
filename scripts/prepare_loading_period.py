"""Railpack pre-deploy gate for the additive loading-period migration.

Apply revision 020 alone using its existing idempotent DDL. The production
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


def migrate_connection(connection):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/020_load_date_end.py"
    spec = importlib.util.spec_from_file_location("loading_period_release_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


async def prepare_schema(engine):
    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            await connection.execute(text("SET LOCAL statement_timeout = '60s'"))
        await connection.run_sync(migrate_connection)
        # A no-op/failed migration must not allow the new application to start.
        await connection.execute(text("SELECT load_date, load_date_end FROM loads LIMIT 0"))


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
