"""Railpack gate for loading periods and retry-safe load publication.

Apply the selected release migrations directly using idempotent additive DDL,
including the private-review, owner-confirmed names and act archive in 027-029.
All steps and the final application check share one transaction. The production
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



def prepare_notifications(connection):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/023_notifications.py"
    spec = importlib.util.spec_from_file_location("notifications_release_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    from sqlalchemy import JSON
    inspector = inspect(connection)
    expected = {
        "notifications": {
            "id": (Integer, False), "recipient_id": (Integer, False), "actor_id": (Integer, True),
            "event_key": (String, False), "kind": (String, False), "data": (JSON, False),
            "created_at": (DateTime, False), "read_at": (DateTime, True)},
        "notification_deliveries": {
            "id": (Integer, False), "notification_id": (Integer, False), "channel": (String, False),
            "status": (String, False), "attempts": (Integer, False), "idempotency_key": (String, False),
            "next_attempt_at": (DateTime, False), "last_attempt_at": (DateTime, True),
            "locked_until": (DateTime, True), "claim_token": (String, True),
            "provider_id": (String, True), "last_error": (String, True), "created_at": (DateTime, False)},
    }
    lengths = {"event_key": 160, "kind": 48, "channel": 16, "status": 16,
               "idempotency_key": 36, "claim_token": 36, "provider_id": 250, "last_error": 96}
    for table, fields in expected.items():
        columns = {item["name"]: item for item in inspector.get_columns(table)}
        for name, (kind, nullable) in fields.items():
            item = columns.get(name)
            if item is None or not isinstance(item["type"], kind) or item["nullable"] != nullable:
                raise RuntimeError("Notification schema is incompatible: " + table + "." + name)
            if kind is String and item["type"].length is not None and item["type"].length < lengths[name]:
                raise RuntimeError("Notification schema has a short column: " + name)
            if kind is DateTime and connection.dialect.name == "postgresql" and not item["type"].timezone:
                raise RuntimeError("Notification timestamp requires timezone: " + name)
        if inspector.get_pk_constraint(table).get("constrained_columns") != ["id"]:
            raise RuntimeError("Notification schema is missing its primary key")
        identity = columns["id"]
        if connection.dialect.name == "postgresql":
            if not identity.get("identity") and not (identity.get("default") or "").lower().startswith("nextval("):
                raise RuntimeError("Notification schema is missing generated ids")
        elif connection.dialect.name == "sqlite" and str(identity["type"]).upper() != "INTEGER":
            raise RuntimeError("Notification schema requires SQLite INTEGER generated ids")
        for name in ("created_at", "next_attempt_at"):
            if name in columns and columns[name].get("default") is None:
                raise RuntimeError("Notification schema is missing a timestamp default")
    unique = lambda table: [set(item["column_names"]) for item in inspector.get_unique_constraints(table)]
    if {"event_key", "recipient_id"} not in unique("notifications"):
        raise RuntimeError("Notification schema is missing event/recipient uniqueness")
    if ({"notification_id", "channel"} not in unique("notification_deliveries")
            or {"idempotency_key"} not in unique("notification_deliveries")):
        raise RuntimeError("Notification schema is missing channel uniqueness")
    required = {"notifications": {(("recipient_id",), "users", ("id",)), (("actor_id",), "users", ("id",))},
                "notification_deliveries": {(("notification_id",), "notifications", ("id",))}}
    for table, references in required.items():
        actual = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
                  for item in inspector.get_foreign_keys(table)}
        if not references.issubset(actual):
            raise RuntimeError("Notification schema is missing foreign keys")
    import re
    def normalized_check(value):
        value = re.sub(r"::(?:character varying|text)(?:\[\])?", "", value.lower())
        return "".join(value.split()).replace("(", "").replace(")", "")
    checks = {item["name"]: normalized_check(item["sqltext"])
              for item in inspector.get_check_constraints("notification_deliveries")}
    required_checks = {
        "ck_notification_deliveries_channel": "channelin'email','telegram'",
        "ck_notification_deliveries_status": "statusin'pending','sending','sent','failed','unknown','skipped'",
        "ck_notification_deliveries_attempts": "attempts>=0"}
    for name, value in required_checks.items():
        alternative = value.replace("in", "=anyarray[", 1) + "]" if "in" in value else value
        if checks.get(name) not in (value, alternative):
            raise RuntimeError("Notification schema is missing delivery constraints")


def prepare_password_recovery(connection):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/024_password_recovery_limits.py"
    spec = importlib.util.spec_from_file_location("password_recovery_release_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    inspector = inspect(connection)
    columns = {item["name"]: item for item in inspector.get_columns("reset_codes")}
    user_columns = {item["name"]: item for item in inspector.get_columns("users")}
    version = user_columns.get("password_version")
    if (version is None or not isinstance(version["type"], Integer) or version["nullable"]
            or version.get("default") is None):
        raise RuntimeError("Password recovery schema is incompatible: users.password_version")
    connection.execute(text("SELECT password_version FROM users LIMIT 0"))
    expected = {"id", "email", "code", "expires_at", "created_at", "attempts", "request_count"}
    if not expected.issubset(columns):
        raise RuntimeError("Password recovery schema is missing columns")
    for name in ("attempts", "request_count"):
        column = columns[name]
        if not isinstance(column["type"], Integer) or column["nullable"] or column.get("default") is None:
            raise RuntimeError("Password recovery schema is incompatible: " + name)
    connection.execute(text(
        "SELECT id, email, code, expires_at, created_at, attempts, request_count FROM reset_codes LIMIT 0"))



async def prepare_schema(engine, *, verify_application=False, bootstrap_empty=False):
    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            await connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            await connection.execute(text("SET LOCAL statement_timeout = '60s'"))
        if bootstrap_empty:
            from app.services.schema_readiness import bootstrap_empty_database
            await connection.run_sync(bootstrap_empty_database)
        await connection.run_sync(migrate_connection)
        # A no-op/failed migration must not allow the new application to start.
        await connection.execute(text("SELECT load_date, load_date_end FROM loads LIMIT 0"))
        await connection.run_sync(prepare_carrier_defaults)
        await connection.run_sync(prepare_document_names)
        await connection.execute(text("SELECT truck_type, tonnage, legal_name_ka, legal_name_ka_confirmed_at FROM users LIMIT 0"))
        await connection.run_sync(prepare_deal_reviews)
        await connection.run_sync(prepare_public_review_visibility)
        await connection.execute(text("SELECT id, deal_id, rater_id, recipient_id, score, comment, created_at, public_comment FROM deal_reviews LIMIT 0"))
        await connection.run_sync(prepare_deal_act_archives)
        await connection.execute(text('SELECT deal_id,schema_version,issued_at,payload,payload_sha256,'
                                      'ru_pdf,ge_pdf,ru_sha256,ge_sha256 FROM deal_act_archives LIMIT 0'))
        await connection.run_sync(prepare_notifications)
        await connection.run_sync(prepare_password_recovery)
        await connection.run_sync(prepare_idempotency)
        await connection.run_sync(prepare_transport_confirmation)
        await connection.run_sync(prepare_route_locations)
        await connection.execute(text(
            "SELECT key, user_id, scope, request_hash, response_status, "
            "response_body, created_at, expires_at FROM idempotency_keys LIMIT 0"
        ))
        if verify_application:
            from app.services.schema_readiness import verify_connection
            await connection.run_sync(verify_connection)


def prepare_deal_act_archives(connection):
    """Create only an absent archive; never repair or rewrite an existing one."""
    from sqlalchemy import JSON, LargeBinary
    import re
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/029_deal_act_archives.py'
    spec = importlib.util.spec_from_file_location('deal_act_archives_release_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    inspector = inspect(connection)
    columns = {item['name']: item for item in inspector.get_columns('deal_act_archives')}
    expected = {
        'deal_id': Integer, 'schema_version': Integer, 'issued_at': DateTime,
        'payload': JSON, 'payload_sha256': String, 'ru_pdf': LargeBinary,
        'ge_pdf': LargeBinary, 'ru_sha256': String, 'ge_sha256': String,
    }
    for name, kind in expected.items():
        column = columns.get(name)
        if column is None or column['nullable'] or not isinstance(column['type'], kind):
            raise RuntimeError('Act archive schema is incompatible: ' + name)
        if kind is String and column['type'].length != 64:
            raise RuntimeError('Act archive schema requires SHA-256 width: ' + name)
        if (kind is DateTime and connection.dialect.name == 'postgresql'
                and not column['type'].timezone):
            raise RuntimeError('Act archive schema requires timezone: ' + name)
        if name not in ('schema_version', 'issued_at') and column.get('default') is not None:
            raise RuntimeError('Act archive schema has an unsafe default: ' + name)
    version_default = re.sub(r"[\s'\"()]", '', str(columns['schema_version'].get('default') or ''))
    version_default = version_default.removesuffix('::integer')
    issue_default = re.sub(r'[\s()]', '', str(columns['issued_at'].get('default') or '')).lower()
    if version_default != '1' or issue_default not in ('now', 'current_timestamp'):
        raise RuntimeError('Act archive schema is missing version/issue defaults')
    if inspector.get_pk_constraint('deal_act_archives').get('constrained_columns') != ['deal_id']:
        raise RuntimeError('Act archive schema is missing per-deal uniqueness')
    references = inspector.get_foreign_keys('deal_act_archives')
    if len(references) != 1 or not any(item['constrained_columns'] == ['deal_id'] and item['referred_table'] == 'deals'
               and item['referred_columns'] == ['id']
                   and item.get('referred_schema') in (None, inspector.default_schema_name)
               and str(item.get('options', {}).get('ondelete', 'NO ACTION')).upper() in ('NO ACTION', 'RESTRICT')
               and str(item.get('options', {}).get('onupdate', 'NO ACTION')).upper() in ('NO ACTION', 'RESTRICT')
               for item in references):
        raise RuntimeError('Act archive schema is missing a non-destructive deal foreign key')
    def normalize(value):
        normalized = re.sub(r'[\s()]', '', value.lower())
        # PostgreSQL resolves length(varchar) as length(varchar::text). Only
        # these already-validated varchar(64) columns have this binary cast.
        for name in ('ru_sha256', 'ge_sha256', 'payload_sha256'):
            normalized = normalized.replace('length' + name + '::text', 'length' + name)
        return normalized
    checks = {item['name']: normalize(item['sqltext'])
              for item in inspector.get_check_constraints('deal_act_archives')}
    required = {
        'ck_deal_act_archive_version': 'schema_version=1',
        'ck_deal_act_archive_ru_pdf': 'lengthru_pdf>0',
        'ck_deal_act_archive_ge_pdf': 'lengthge_pdf>0',
        'ck_deal_act_archive_ru_sha': 'lengthru_sha256=64',
        'ck_deal_act_archive_ge_sha': 'lengthge_sha256=64',
        'ck_deal_act_archive_payload_sha': 'lengthpayload_sha256=64',
    }
    if any(checks.get(name) != value for name, value in required.items()):
        raise RuntimeError('Act archive schema is missing archive validation constraints')
    connection.execute(text('SELECT deal_id,schema_version,issued_at,payload,payload_sha256,'
                            'ru_pdf,ge_pdf,ru_sha256,ge_sha256 FROM deal_act_archives LIMIT 0'))


def prepare_document_names(connection):
    """Require additive nullable owner fields; never derive historic names."""
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/028_document_names.py'
    spec = importlib.util.spec_from_file_location('document_names_release_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    columns = {item['name']: item for item in inspect(connection).get_columns('users')}
    name, confirmed = columns.get('legal_name_ka'), columns.get('legal_name_ka_confirmed_at')
    if (name is None or not isinstance(name['type'], String) or name['type'].length != 255
            or not name['nullable'] or name.get('default') is not None):
        raise RuntimeError('Document names schema is incompatible: legal_name_ka')
    if (confirmed is None or not isinstance(confirmed['type'], DateTime) or not confirmed['nullable']
            or confirmed.get('default') is not None
            or (connection.dialect.name == 'postgresql' and not confirmed['type'].timezone)):
        raise RuntimeError('Document names schema is incompatible: legal_name_ka_confirmed_at')
    connection.execute(text('SELECT legal_name_ka, legal_name_ka_confirmed_at FROM users LIMIT 0'))


def prepare_public_review_visibility(connection):
    """Add consent=false for old texts; fail closed on schema/default drift."""
    from sqlalchemy import Boolean
    import re
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/027_review_comment_visibility.py'
    spec = importlib.util.spec_from_file_location('review_visibility_release_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    column = next((item for item in inspect(connection).get_columns('deal_reviews')
                   if item['name'] == 'public_comment'), None)
    default = re.sub(r"[\s'\"()]", '', str(column.get('default') or '')).lower() if column else ''
    default = default.removesuffix('::boolean')
    if (column is None or not isinstance(column['type'], Boolean) or column['nullable']
            or default not in ('false', '0')):
        raise RuntimeError('Review visibility schema is incompatible: public_comment')
    connection.execute(text('SELECT public_comment FROM deal_reviews LIMIT 0'))


def prepare_transport_confirmation(connection):
    """Apply only additive availability state; never backfill confirmations."""
    path = Path(__file__).resolve().parents[1] / "alembic/versions/025_transport_confirmation.py"
    spec = importlib.util.spec_from_file_location("transport_confirmation_release_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    inspector = inspect(connection)
    if not inspector.has_table("transport_offers"):
        return  # Existing fresh-install bootstrap creates the catalogue table.
    column = next((item for item in inspector.get_columns("transport_offers")
                   if item["name"] == "last_confirmed_at"), None)
    if (column is None or not column["nullable"] or not isinstance(column["type"], DateTime)
            or column.get("default") is not None
            or (connection.dialect.name == "postgresql" and not column["type"].timezone)):
        raise RuntimeError("Transport confirmation schema is incompatible: last_confirmed_at")
    connection.execute(text("SELECT last_confirmed_at FROM transport_offers LIMIT 0"))


def prepare_route_locations(connection):
    """Add nullable JSON endpoints, never infer legacy coordinates/countries."""
    from sqlalchemy import JSON
    path = Path(__file__).resolve().parents[1] / "alembic/versions/026_route_locations.py"
    spec = importlib.util.spec_from_file_location("route_locations_release_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    inspector = inspect(connection)
    for table in ("loads", "transport_offers"):
        if not inspector.has_table(table):
            continue
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        for name in ("from_location", "to_location"):
            column = columns.get(name)
            if column is None or not isinstance(column["type"], JSON) or not column["nullable"] or column.get("default") is not None:
                raise RuntimeError("Route location schema is incompatible: " + table + "." + name)
        connection.execute(text("SELECT from_location, to_location FROM " + table + " LIMIT 0"))


async def run(*, bootstrap_empty=False):
    # Use the same URL/driver normalization as the application; never print it.
    from app.database import engine

    try:
        await prepare_schema(engine, verify_application=True, bootstrap_empty=bootstrap_empty)
    finally:
        await engine.dispose()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Guarded additive schema preparation')
    parser.add_argument('--bootstrap-empty', action='store_true',
                        help='Create application tables only in a completely empty database')
    args = parser.parse_args()
    try:
        asyncio.run(run(bootstrap_empty=args.bootstrap_empty))
    except Exception as error:
        print(f"Loading-period pre-deploy failed ({type(error).__name__}); deployment stopped.", file=sys.stderr)
        return 1
    print("Loading-period schema ready; existing records preserved.")
    print("Idempotency schema ready; retry-safe publication enabled.")
    print("Carrier profile schema ready; optional defaults enabled.")
    print("Deal review schema ready; per-participant reviews enabled.")
    print("Notification schema ready; persistent inbox and delivery queue enabled.")
    print("Password recovery schema ready; persistent verification budgets enabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
