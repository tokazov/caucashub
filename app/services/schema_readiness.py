"""Read-only application schema checks shared by predeploy, startup and health.

These checks require every mapped column without rewriting historical data or
coercing existing PostgreSQL types. Empty database creation is an explicit
predeploy operation, never a startup fallback.
"""
from sqlalchemy import Enum as SAEnum, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError


class SchemaNotReady(RuntimeError):
    pass


def application_metadata():
    from app.database import Base
    # __init__ registers the main models. These two tables were historically
    # registered only by their routers; the CLI must check them as well.
    from app.models import ad, payment  # noqa: F401
    return Base.metadata


def verify_connection(connection):
    """LIMIT 0 checks names and access, never loads customer records."""
    tables = application_metadata().sorted_tables
    for table in tables:
        try:
            connection.execute(select(table).limit(0))
            if connection.dialect.name == 'postgresql':
                expected = {column.name: set(column.type.enums) for column in table.columns
                            if isinstance(column.type, SAEnum)}
                if expected:
                    rows = connection.execute(text(
                        "SELECT a.attname, e.enumlabel FROM pg_attribute a "
                        "JOIN pg_type t ON t.oid=a.atttypid AND t.typtype='e' "
                        "LEFT JOIN pg_enum e ON e.enumtypid=t.oid "
                        "WHERE a.attrelid=to_regclass(:table_name) AND a.attnum>0 AND NOT a.attisdropped"
                    ), {'table_name': table.name}).all()
                    actual = {}
                    for name, label in rows:
                        actual.setdefault(name, set()).update([label] if label is not None else [])
                    for name, required in expected.items():
                        # Historical VARCHAR storage remains compatible. Only
                        # existing native enums constrain accepted write values.
                        if name in actual and not required.issubset(actual[name]):
                            raise SchemaNotReady('Required database enum unavailable: ' + table.name + '.' + name)
        except SQLAlchemyError:
            # Do not expose connection strings or raw driver errors in health.
            raise SchemaNotReady('Required database schema unavailable: ' + table.name) from None
    return tuple(table.name for table in tables)


async def verify_application_schema(engine):
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(verify_connection)
    except SchemaNotReady:
        raise
    except SQLAlchemyError:
        raise SchemaNotReady('Application database unavailable') from None


def bootstrap_empty_database(connection):
    """Operator opt-in only. Refuse to modify a partially populated schema."""
    if inspect(connection).get_table_names():
        raise SchemaNotReady('Empty-database bootstrap refused: tables already exist')
    application_metadata().create_all(connection, checkfirst=True)
