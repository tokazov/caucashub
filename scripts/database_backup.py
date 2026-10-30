"""Full PostgreSQL archive and deliberately local-only restore drill.

Connection secrets are read from an explicitly named environment variable, never
command-line arguments.  This module does not restore to an existing database,
drop a database, or implement a production restore path.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlsplit
import uuid

import asyncpg


ROOT = Path(__file__).resolve().parents[1]
FORMAT_VERSION = 1
TEST_PREFIX = "caucashub_restore_test_"
TEST_NAME = re.compile(r"caucashub_restore_test_[a-z0-9_]{12,50}\Z")
MARKER_PREFIX = "caucashub-disposable-restore-v1:"
ADMIN_MARKER = "caucashub-disposable-restore-admin-v1"
DIRECTORY_MARKER = ".caucashub-backup-directory.json"
DIRECTORY_PURPOSE = {"format_version": 1, "purpose": "caucashub-private-database-backups"}
SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


class BackupError(RuntimeError):
    """A safe-to-display error without database values or tool stderr."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def safe_json(path: Path, value: Any) -> None:
    """Create a new private report without replacing previous evidence."""
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
    if os.name != "nt":
        path.chmod(0o600)


@dataclass(frozen=True)
class Connection:
    host: str
    port: int
    database: str
    user: str = field(repr=False)
    password: str | None = field(default=None, repr=False)
    sslmode: str = "prefer"
    passfile: str | None = field(default=None, repr=False)

    @classmethod
    def from_environment(cls, name: str, environ: Mapping[str, str] | None = None) -> "Connection":
        env = os.environ if environ is None else environ
        value = env.get(name, "")
        if not value:
            raise BackupError(f"Set {name} privately to a PostgreSQL URL; no URL is accepted on the command line.")
        return cls.from_secret(value, name)

    @classmethod
    def from_secret(cls, value: str, name: str = "Private connection input") -> "Connection":
        try:
            parts = urlsplit(value)
            if parts.scheme not in {"postgres", "postgresql"} or not parts.hostname or not parts.username:
                raise ValueError()
            query = parse_qs(parts.query, strict_parsing=True)
            if set(query) - {"sslmode", "connect_timeout", "application_name"}:
                raise ValueError()
            try:
                local = ipaddress.ip_address(parts.hostname).is_loopback
            except ValueError:
                local = False
            sslmode = query.get("sslmode", ["prefer" if local else "require"])[0]
            if sslmode not in SSL_MODES or len(query.get("sslmode", [sslmode])) != 1:
                raise ValueError()
            if not local and sslmode not in {"require", "verify-ca", "verify-full"}:
                raise ValueError()
            database = unquote(parts.path.removeprefix("/"))
            if not database or "\x00" in database or "/" in database:
                raise ValueError()
            return cls(parts.hostname, parts.port or 5432, database, unquote(parts.username),
                       unquote(parts.password) if parts.password is not None else None,
                       sslmode, os.environ.get("PGPASSFILE"))
        except (ValueError, TypeError):
            raise BackupError(f"{name} must contain one valid PostgreSQL connection URL.") from None

    def client_environment(self, *, database: str | None = None, readonly: bool = False) -> dict[str, str]:
        # Inherited libpq hostaddr/service/options must not override the target.
        env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        env.update(PGHOST=self.host, PGPORT=str(self.port), PGDATABASE=database or self.database,
                   PGUSER=self.user, PGSSLMODE=self.sslmode, PGCONNECT_TIMEOUT="15",
                   PGAPPNAME="caucashub_database_safety")
        if self.password is not None:
            env["PGPASSWORD"] = self.password
        if self.passfile:
            env["PGPASSFILE"] = self.passfile
        # A dump cannot accidentally write through its own libpq connection.
        if readonly:
            env["PGOPTIONS"] = "-c default_transaction_read_only=on -c lock_timeout=5000"
        return env

    async def connect(self, *, database: str | None = None) -> asyncpg.Connection:
        try:
            return await asyncpg.connect(host=self.host, port=self.port,
                database=database or self.database, user=self.user, password=self.password,
                passfile=self.passfile, ssl=self.sslmode, timeout=15, command_timeout=600,
                server_settings={"application_name": "caucashub_database_safety", "timezone": "UTC",
                                 "lock_timeout": "5000", "statement_timeout": "600000"})
        except Exception as exc:
            raise BackupError(f"Database connection failed ({type(exc).__name__}); connection details were withheld.") from None

    def source_fingerprint(self) -> str:
        return digest_json([self.host, self.port, self.database])


def validate_loopback_target(connection: Connection, target: str) -> None:
    try:
        address = ipaddress.ip_address(connection.host)
    except ValueError:
        raise BackupError("Restore drills require a literal loopback IP, not a hostname, service or remote host.") from None
    if not address.is_loopback or not (1 <= connection.port <= 65535):
        raise BackupError("Restore drills are permitted only on a loopback PostgreSQL server.")
    if not TEST_NAME.fullmatch(target):
        raise BackupError("Restore target must use the disposable caucashub_restore_test_ prefix and a unique suffix.")
    if connection.database != "postgres":
        raise BackupError("Restore administrator must connect to the local postgres maintenance database.")


def private_directory(path: Path) -> Path:
    path = Path(os.path.abspath(path.expanduser()))
    if path == ROOT or ROOT in path.parents:
        raise BackupError("Backup output must be outside the source worktree; archives must never enter Git.")
    if any(part == ".git" for part in path.parts):
        raise BackupError("Backup output cannot be inside Git metadata.")
    # Refuse symlinks/junction-like redirects before writing sensitive archives.
    for parent in [path, *path.parents]:
        if parent.exists() and (parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction())):
            raise BackupError("Backup output cannot traverse a link or junction.")
    if path.exists():
        if not path.is_dir():
            raise BackupError("Backup output is not a directory.")
        entries = list(path.iterdir())
        if entries:
            marker = path / DIRECTORY_MARKER
            try:
                marked = not marker.is_symlink() and marker.is_file() and marker.stat().st_size < 1024 and json.loads(marker.read_text(encoding="utf-8")) == DIRECTORY_PURPOSE
            except (OSError, ValueError):
                marked = False
            if not marked:
                raise BackupError("Refusing to change permissions on an unrelated nonempty directory; choose a fresh backup directory.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        principal = os.environ.get("USERDOMAIN", "")
        principal = (principal + "\\" if principal else "") + getpass.getuser()
        # Reset explicit grants as well: a pre-existing broad ACL is not safe.
        reset = subprocess.run(["icacls", str(path), "/reset"], capture_output=True, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW)
        result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
            principal + ":(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], capture_output=True, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if reset.returncode or result.returncode:
            raise BackupError("Could not protect the backup directory ACL; no dump was started.")
    else:
        path.chmod(0o700)
    if not (path / DIRECTORY_MARKER).exists():
        safe_json(path / DIRECTORY_MARKER, DIRECTORY_PURPOSE)
    return path


def executable(name: str, pg_bin: Path | None) -> str:
    if pg_bin:
        path = pg_bin / (name + (".exe" if os.name == "nt" else ""))
        if path.is_file():
            return str(path)
    else:
        found = shutil.which(name)
        if found:
            return found
    raise BackupError(f"{name} was not found; supply --pg-bin pointing to PostgreSQL client binaries.")


async def run_tool(tool: str, arguments: list[str], env: dict[str, str], timeout: int = 1800) -> dict[str, Any]:
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        child = await asyncio.create_subprocess_exec(tool, *arguments, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **kwargs)
        try:
            stdout, stderr = await asyncio.wait_for(child.communicate(), timeout)
        except asyncio.TimeoutError:
            child.kill()
            await child.communicate()
            raise BackupError("PostgreSQL tool timed out; the operation was not marked successful.") from None
        if child.returncode:
            raise BackupError(f"{Path(tool).stem} failed (exit {child.returncode}); diagnostic text withheld to protect database values.")
        return {"stdout": stdout, "stderr_present": bool(stderr.strip())}
    except OSError:
        raise BackupError("PostgreSQL tool could not be started.") from None


async def structural_metadata(conn: asyncpg.Connection) -> dict[str, Any]:
    # Hash definitions/defaults instead of publishing possible literals in them.
    relations = await conn.fetch("""
        SELECT n.nspname AS schema, c.relname AS name, c.relkind AS kind,
               CASE WHEN c.relkind IN ('v','m') THEN md5(pg_get_viewdef(c.oid,true)) ELSE NULL END AS definition_hash
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
          AND n.nspname NOT LIKE 'pg_temp_%' AND c.relkind IN ('r','p','v','m','S','f')
        ORDER BY n.nspname,c.relname
    """)
    columns = await conn.fetch("""
        SELECT table_schema AS schema,table_name AS name,column_name,ordinal_position,data_type,
               udt_schema,udt_name,is_nullable,md5(column_default) AS default_hash, is_identity, is_generated
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog','information_schema')
        ORDER BY table_schema,table_name,ordinal_position
    """)
    constraints = await conn.fetch("""
        SELECT n.nspname AS schema,c.relname AS table_name,k.conname AS name,k.contype AS type,
               k.convalidated AS validated,md5(pg_get_constraintdef(k.oid,true)) AS definition_hash
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
        ORDER BY n.nspname,c.relname,k.conname
    """)
    indexes = await conn.fetch("""
        SELECT schemaname AS schema,tablename AS table_name,indexname AS name,md5(indexdef) AS definition_hash
        FROM pg_indexes WHERE schemaname NOT IN ('pg_catalog','information_schema')
        ORDER BY schemaname,tablename,indexname
    """)
    return {"relations": [dict(r) for r in relations], "columns": [dict(r) for r in columns],
            "constraints": [dict(r) for r in constraints], "indexes": [dict(r) for r in indexes]}


async def fingerprint_database(conn: asyncpg.Connection) -> dict[str, Any]:
    """Only counts and aggregate hashes leave PostgreSQL, never field values."""
    structure = await structural_metadata(conn)
    tables = []
    for relation in structure["relations"]:
        if relation["kind"] not in {"r", "m"}:
            continue  # Partition parents would double-count their child records.
        schema, name = relation["schema"], relation["name"]
        qualified = quote_identifier(schema) + "." + quote_identifier(name)
        keys = await conn.fetch("""
            SELECT a.attname FROM pg_index i CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,ord)
            JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
            WHERE i.indrelid=$1::regclass AND i.indisprimary ORDER BY k.ord
        """, qualified)
        pk = [r["attname"] for r in keys]
        pk_expression = "jsonb_build_array(" + ",".join("t." + quote_identifier(k) for k in pk) + ")" if pk else None
        query = f"SELECT md5(to_jsonb(t)::text) AS row_hash FROM ONLY {qualified} t ORDER BY row_hash"
        rows_hash, keys_hash, count = hashlib.sha256(), hashlib.sha256(), 0
        async for row in conn.cursor(query, prefetch=500):
            rows_hash.update(row["row_hash"].encode("ascii") + b"\n")
            count += 1
        if pk_expression:
            key_query = f"SELECT md5({pk_expression}::text) AS key_hash FROM ONLY {qualified} t ORDER BY key_hash"
            async for row in conn.cursor(key_query, prefetch=500):
                keys_hash.update(row["key_hash"].encode("ascii") + b"\n")
        tables.append({"schema": schema, "name": name, "rows": count, "primary_key_columns": pk,
                       "data_sha256": rows_hash.hexdigest(),
                       "record_ids_sha256": keys_hash.hexdigest() if pk else None})
    sequences = [dict(row) for row in await conn.fetch("""
        SELECT n.nspname AS schema,c.relname AS name,s.seqstart AS start,s.seqincrement AS increment,
               s.seqmax AS maximum,s.seqmin AS minimum,s.seqcache AS cache,s.seqcycle AS cycle,
               tn.nspname AS owner_schema,t.relname AS owner_table,a.attname AS owner_column
        FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=c.oid
          AND d.refclassid='pg_class'::regclass AND d.refobjsubid>0 AND d.deptype IN ('a','i')
        LEFT JOIN pg_class t ON t.oid=d.refobjid LEFT JOIN pg_namespace tn ON tn.oid=t.relnamespace
        LEFT JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
        WHERE n.nspname NOT IN ('pg_catalog','information_schema') ORDER BY n.nspname,c.relname
    """)]
    large_objects = await conn.fetchval("SELECT count(*) FROM pg_largeobject_metadata")
    lob_hash = hashlib.sha256()
    async for row in conn.cursor("SELECT md5(loid::text) AS object_hash,pageno,md5(data) AS page_hash FROM pg_largeobject ORDER BY loid,pageno", prefetch=500):
        lob_hash.update((row["object_hash"] + ":" + str(row["pageno"]) + ":" + row["page_hash"] + "\n").encode("ascii"))
    return {"structure": structure, "structure_sha256": digest_json(structure),
            "tables": tables, "sequences": sequences,
            "large_objects": {"count": large_objects, "pages_sha256": lob_hash.hexdigest()},
            "foreign_keys": sum(c["type"] == "f" for c in structure["constraints"]),
            "validated_foreign_keys": sum(c["type"] == "f" and c["validated"] for c in structure["constraints"])}


async def sequence_invariants(conn: asyncpg.Connection, sequences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Non-MVCC counters may advance during a dump; verify safe next owned IDs.

    Dynamic counters are deliberately not compared with the earlier snapshot.
    Unowned/cycling sequence values remain in the archive but are not claimed as
    independently verified by a row-ID invariant.
    """
    checks = []
    for sequence in sequences:
        check = {"schema": sequence["schema"], "name": sequence["name"], "safe_next_owned_id": None}
        if sequence["owner_table"] and sequence["owner_column"] and not sequence["cycle"]:
            seq = quote_identifier(sequence["schema"]) + "." + quote_identifier(sequence["name"])
            table = quote_identifier(sequence["owner_schema"]) + "." + quote_identifier(sequence["owner_table"])
            column = quote_identifier(sequence["owner_column"])
            increment = int(sequence["increment"])
            aggregate, operator = ("max", ">") if increment > 0 else ("min", "<")
            query = f"""SELECT COALESCE(
                (SELECT last_value::numeric + CASE WHEN is_called THEN $1::bigint::numeric ELSE 0 END FROM {seq})
                {operator} (SELECT {aggregate}({column})::numeric FROM {table}), true)"""
            check["safe_next_owned_id"] = await conn.fetchval(query, increment)
        checks.append(check)
    return checks


async def backup(connection: Connection, output: Path, pg_bin: Path | None) -> Path:
    directory = private_directory(output)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    partial = directory / ("caucashub_" + stamp + ".dump.partial")
    archive = directory / ("caucashub_" + stamp + ".dump")
    manifest = directory / (archive.stem + ".manifest.json")
    tool = executable("pg_dump", pg_bin)
    conn = await connection.connect()
    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            snapshot = await conn.fetchval("SELECT pg_export_snapshot()")
            version = await conn.fetchval("SHOW server_version")
            metadata = await fingerprint_database(conn)
            result = await run_tool(tool, ["--format=custom", "--no-password", "--lock-wait-timeout=5000",
                "--snapshot=" + snapshot, "--file=" + str(partial)], connection.client_environment(readonly=True))
            if not partial.is_file() or partial.stat().st_size < 64:
                raise BackupError("PostgreSQL did not produce a complete custom archive.")
            with partial.open("rb") as handle:
                if handle.read(5) != b"PGDMP":
                    raise BackupError("Unexpected archive format.")
            partial.rename(archive)
            if os.name != "nt":
                archive.chmod(0o600)
            with archive.open("rb") as handle:
                checksum = hashlib.file_digest(handle, "sha256").hexdigest()
            payload = {"format_version": FORMAT_VERSION, "created_at": utc_now(), "format": "pg_dump_custom",
                "archive": archive.name, "bytes": archive.stat().st_size, "sha256": checksum,
                "server_version": version, "source_identifier_sha256": connection.source_fingerprint(),
                "consistent_snapshot": True, "source_transaction_read_only": True,
                "sequence_verification": "Archive contains counters; compare configuration and next-ID safety after restore, not non-MVCC snapshot counters.",
                "tool_warnings_present": result["stderr_present"], "database": metadata,
                "scope": "Complete single database: all non-system schemas, table data, sequences and large objects.",
                "excludes": ["Cluster roles and tablespaces", "External uploads/files", "Server secrets/configuration", "WAL/PITR history"],
                "restore_verified": False}
            safe_json(manifest, payload)
            return manifest
    finally:
        await conn.close()
        if partial.is_file():
            partial.unlink()  # Only this run's incomplete archive, never older backups.


def load_manifest(path: Path) -> tuple[dict[str, Any], Path]:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        name = metadata["archive"]
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".dump"):
            raise ValueError()
        archive = path.parent / name
        if archive.is_symlink() or metadata["format_version"] != FORMAT_VERSION or metadata["format"] != "pg_dump_custom":
            raise ValueError()
        if not metadata.get("consistent_snapshot") or not metadata.get("source_transaction_read_only"):
            raise ValueError()
        with archive.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != metadata["sha256"] or archive.stat().st_size != metadata["bytes"]:
            raise BackupError("Archive checksum/size mismatch; restore refused.")
        return metadata, archive
    except BackupError:
        raise
    except (OSError, KeyError, TypeError, ValueError):
        raise BackupError("Invalid or incomplete backup manifest; restore refused.") from None


async def assert_target(conn: asyncpg.Connection, target: str, marker: str) -> None:
    row = await conn.fetchrow("""
        SELECT current_database() AS db,host(inet_server_addr()) AS address,
               shobj_description(oid,'pg_database') AS marker
        FROM pg_database WHERE datname=current_database()
    """)
    try:
        address = ipaddress.ip_address(row["address"])
    except (ValueError, TypeError):
        raise BackupError("Restore target is not a verified loopback database.") from None
    if row["db"] != target or not address.is_loopback or row["marker"] != marker:
        raise BackupError("Restore target identity/ownership marker mismatch; restore refused.")
    count = await conn.fetchval("""
        SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
          AND n.nspname NOT LIKE 'pg_temp_%' AND c.relkind IN ('r','p','v','m','S','f')
    """)
    if count:
        raise BackupError("Restore target is not empty; restore refused.")


async def assert_restore_admin(conn: asyncpg.Connection) -> None:
    row = await conn.fetchrow("""
        SELECT current_database() AS db,host(inet_server_addr()) AS address,
               shobj_description(oid,'pg_database') AS marker
        FROM pg_database WHERE datname=current_database()
    """)
    try:
        address = ipaddress.ip_address(row["address"])
    except (ValueError, TypeError):
        raise BackupError("The restore administrator is not connected to a verified loopback server.") from None
    if not address.is_loopback or row["db"] != "postgres" or row["marker"] != ADMIN_MARKER:
        raise BackupError("Restore administrator DB lacks the pre-existing disposable-cluster marker; restore refused.")


async def restore_test(connection: Connection, manifest_path: Path, pg_bin: Path | None,
                       target: str | None = None) -> Path:
    target = target or TEST_PREFIX + uuid.uuid4().hex
    validate_loopback_target(connection, target)
    metadata, archive = load_manifest(manifest_path)
    tool = executable("pg_restore", pg_bin)
    admin = await connection.connect()
    marker = MARKER_PREFIX + uuid.uuid4().hex
    try:
        # Unlike the newly-created target's marker, this must already exist.
        # The backup/restore tool never attests an administrator database itself.
        await assert_restore_admin(admin)
        if await admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=$1)", target):
            raise BackupError("Restore target already exists; stale or unmarked targets are never reused.")
        # The only database mutation path in this tool creates a fresh local test DB.
        await admin.execute("CREATE DATABASE " + quote_identifier(target) + " TEMPLATE template0")
        await admin.execute("COMMENT ON DATABASE " + quote_identifier(target) + " IS '" + marker + "'")
    finally:
        await admin.close()
    conn = await connection.connect(database=target)
    try:
        await assert_target(conn, target, marker)
        await run_tool(tool, ["--no-password", "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl",
            "--dbname=" + target, str(archive)], connection.client_environment(database=target))
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            actual = await fingerprint_database(conn)
            sequence_checks = await sequence_invariants(conn, actual["sequences"])
        expected = metadata["database"]
        safe_sequences = all(item["safe_next_owned_id"] is not False for item in sequence_checks)
        matches = actual == expected and safe_sequences
        report = {"format_version": FORMAT_VERSION, "verified_at": utc_now(), "restore_verified": matches,
            "archive_sha256": metadata["sha256"], "manifest": manifest_path.name,
            "target": target, "target_loopback": True, "target_created_fresh": True,
            "structure_match": actual["structure_sha256"] == expected["structure_sha256"],
            "table_counts_data_and_ids_match": actual["tables"] == expected["tables"],
            "sequence_configuration_match": actual["sequences"] == expected["sequences"],
            "owned_sequence_next_values_safe": safe_sequences,
            "sequence_invariants": sequence_checks,
            "unowned_or_cycling_sequence_states_independently_verified": False if any(item["safe_next_owned_id"] is None for item in sequence_checks) else None,
            "large_objects_match": actual["large_objects"] == expected["large_objects"],
            "foreign_keys": actual["foreign_keys"], "validated_foreign_keys": actual["validated_foreign_keys"],
            "tables": len(actual["tables"]), "rows": sum(t["rows"] for t in actual["tables"]),
            "ownership_and_acl": "Not applied in local test; preserved in original archive.",
            "cleanup": "No database was dropped. Test database remains local and marked disposable."}
        report_path = manifest_path.with_name(manifest_path.stem + ".restore-" + uuid.uuid4().hex[:8] + ".json")
        safe_json(report_path, report)
        if not matches:
            raise BackupError("Restored database does not match the snapshot fingerprints; see the private restore report.")
        return report_path
    finally:
        await conn.close()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    dump = commands.add_parser("backup", help="Read-only full PostgreSQL custom archive; no API export.")
    dump.add_argument("--database-env", default="BACKUP_DATABASE_URL", help="Name of an environment variable, never its secret value.")
    dump.add_argument("--prompt-source", action="store_true", help="Human terminal only: read the source URL without echo or storing it.")
    dump.add_argument("--output-dir", type=Path, required=True, help="Private directory outside the source worktree.")
    dump.add_argument("--pg-bin", type=Path)
    restore = commands.add_parser("restore-test", help="Create and verify a NEW loopback-only disposable database.")
    restore.add_argument("--admin-env", default="RESTORE_TEST_ADMIN_URL")
    restore.add_argument("--prompt-admin", action="store_true", help="Human terminal only: read the LOCAL administrator URL without echo.")
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--pg-bin", type=Path)
    restore.add_argument("--target-db", help="Optional unique disposable target; an existing DB is always rejected.")
    return value


async def main_async(args: argparse.Namespace) -> None:
    if args.command == "backup":
        connection = prompt_connection("Source PostgreSQL URL (hidden): ") if args.prompt_source else Connection.from_environment(args.database_env)
        result = await backup(connection, args.output_dir, args.pg_bin)
    else:
        connection = prompt_connection("LOCAL postgres maintenance URL (hidden): ") if args.prompt_admin else Connection.from_environment(args.admin_env)
        result = await restore_test(connection, args.manifest, args.pg_bin, args.target_db)
    # Only filenames/status are printed, never connection strings or records.
    print(json.dumps({"ok": True, "command": args.command, "report": str(result)}, ensure_ascii=True))


def prompt_connection(message: str) -> Connection:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise BackupError("Hidden connection entry requires an interactive terminal; refusing an echoing fallback.")
    value = getpass.getpass(message, stream=sys.stderr)
    return Connection.from_secret(value)


def main() -> int:
    try:
        asyncio.run(main_async(parser().parse_args()))
        return 0
    except BackupError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"Operation failed ({type(exc).__name__}); details withheld to protect database values."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
