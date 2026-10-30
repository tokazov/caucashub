"""Guard tests plus an opt-in real PostgreSQL archive/restore drill.

Set TEST_POSTGRES_URL to a SCRAM-protected local postgres maintenance DB and
POSTGRES_BIN to local pg_dump/pg_restore binaries. Never use a production URL.
"""
import json
import os
from pathlib import Path
import uuid
from unittest.mock import AsyncMock

import pytest

from scripts.database_backup import (
    BackupError, Connection, MARKER_PREFIX, TEST_PREFIX, assert_target, backup,
    fingerprint_database, load_manifest, private_directory, quote_identifier,
    restore_test, validate_loopback_target, executable, prompt_connection,
    assert_restore_admin, ADMIN_MARKER, sequence_invariants,
)
from scripts import database_backup


def local_connection(**changes):
    values = dict(host="127.0.0.1", port=55438, database="postgres", user="test_admin", password="do-not-print")
    values.update(changes)
    return Connection(**values)


@pytest.mark.parametrize("host", ["railway.internal", "production.example", "localhost", "192.168.1.1", "0.0.0.0", "::ffff:192.168.1.1"])
def test_restore_rejects_non_literal_loopback(host):
    with pytest.raises(BackupError):
        validate_loopback_target(local_connection(host=host), TEST_PREFIX + "a" * 32)


@pytest.mark.parametrize("name", ["railway", "postgres", "caucashub", "caucashub_restore_test_old", "caucashub_restore_test_" + "a"*12 + ";drop database railway"])
def test_restore_rejects_production_or_unapproved_database_names(name):
    with pytest.raises(BackupError):
        validate_loopback_target(local_connection(), name)


def test_restore_rejects_administrator_connected_to_application_database():
    with pytest.raises(BackupError):
        validate_loopback_target(local_connection(database="railway"), TEST_PREFIX + "a"*32)


def test_connection_secret_is_not_in_repr_or_validation_errors():
    connection = Connection.from_environment("PRIVATE", {"PRIVATE": "postgresql://test_admin:secret-password@127.0.0.1/postgres?sslmode=disable"})
    assert "secret-password" not in repr(connection)
    assert connection.password == "secret-password"
    with pytest.raises(BackupError) as error:
        Connection.from_environment("PRIVATE", {"PRIVATE": "postgresql://x:secret-password@production/db?hostaddr=127.0.0.1"})
    assert "secret-password" not in str(error.value)


def test_dump_environment_cannot_be_redirected_by_inherited_libpq_options(monkeypatch):
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.10")
    monkeypatch.setenv("PGSERVICE", "production")
    monkeypatch.setenv("PGOPTIONS", "-c default_transaction_read_only=off")
    environment = local_connection().client_environment(readonly=True)
    assert "PGHOSTADDR" not in environment and "PGSERVICE" not in environment
    assert "default_transaction_read_only=on" in environment["PGOPTIONS"]


def test_output_inside_source_tree_is_rejected():
    with pytest.raises(BackupError):
        private_directory(Path(__file__).parents[1] / "outputs" / "database-backups")
    with pytest.raises(BackupError):
        private_directory(database_backup.ROOT.parent / "other" / ".." / database_backup.ROOT.name / "outputs")


def test_unrelated_nonempty_directory_is_rejected_without_permission_changes(tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    original = unrelated / "keep.txt"
    original.write_text("unrelated user file", encoding="utf-8")
    with pytest.raises(BackupError, match="unrelated nonempty"):
        private_directory(unrelated)
    assert list(unrelated.iterdir()) == [original]
    assert original.read_text(encoding="utf-8") == "unrelated user file"


def test_marked_backup_directory_can_be_reused(tmp_path):
    directory = private_directory(tmp_path / "owned-backups")
    (directory / "synthetic.dump").write_bytes(b"TEST")
    assert private_directory(directory) == directory


def test_hidden_prompt_refuses_noninteractive_input(monkeypatch):
    monkeypatch.setattr(database_backup.sys.stdin, "isatty", lambda: False)
    with pytest.raises(BackupError, match="interactive terminal"):
        prompt_connection("Hidden: ")


def test_remote_source_requires_encrypted_connection():
    connection = Connection.from_secret("postgresql://user:secret@production.example/railway")
    assert connection.sslmode == "require"
    with pytest.raises(BackupError):
        Connection.from_secret("postgresql://user:secret@production.example/railway?sslmode=disable")


@pytest.mark.asyncio
async def test_unmarked_or_nonempty_target_is_rejected():
    connection = AsyncMock()
    target = TEST_PREFIX + "a"*32
    marker = MARKER_PREFIX + "fresh"
    connection.fetchrow.return_value = {"db": target, "address": "127.0.0.1", "marker": None}
    with pytest.raises(BackupError, match="marker"):
        await assert_target(connection, target, marker)
    connection.fetchrow.return_value["marker"] = marker
    connection.fetchval.return_value = 1
    with pytest.raises(BackupError, match="not empty"):
        await assert_target(connection, target, marker)


@pytest.mark.asyncio
async def test_unmarked_loopback_admin_is_rejected_before_any_create(monkeypatch, tmp_path):
    connection = AsyncMock()
    connection.fetchrow.return_value = {"db": "postgres", "address": "127.0.0.1", "marker": None}
    monkeypatch.setattr(Connection, "connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(database_backup, "load_manifest", lambda _: ({}, tmp_path / "synthetic.dump"))
    monkeypatch.setattr(database_backup, "executable", lambda *_: "pg_restore")
    runner = AsyncMock()
    monkeypatch.setattr(database_backup, "run_tool", runner)
    with pytest.raises(BackupError, match="pre-existing"):
        await restore_test(local_connection(), tmp_path / "manifest.json", None)
    connection.execute.assert_not_called()
    runner.assert_not_awaited()


def test_archive_checksum_and_path_traversal_are_rejected(tmp_path):
    archive = tmp_path / "sample.dump"
    archive.write_bytes(b"PGDMP" + b"synthetic"*10)
    manifest = tmp_path / "sample.manifest.json"
    data = {"format_version": 1, "format": "pg_dump_custom", "archive": "sample.dump",
            "consistent_snapshot": True, "source_transaction_read_only": True, "sha256": "wrong", "bytes": archive.stat().st_size}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BackupError, match="checksum"):
        load_manifest(manifest)
    data["archive"] = "../secret.dump"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BackupError, match="Invalid"):
        load_manifest(manifest)


@pytest.fixture
def real_pg():
    if not os.environ.get("TEST_POSTGRES_URL"):
        pytest.skip("Explicit disposable local PostgreSQL runtime not configured")
    connection = Connection.from_environment("TEST_POSTGRES_URL")
    validate_loopback_target(connection, TEST_PREFIX + "fixture" + uuid.uuid4().hex)
    configured = os.environ.get("PG_BIN") or os.environ.get("POSTGRES_BIN")
    pg_bin = Path(configured) if configured else None
    executable("pg_dump", pg_bin)  # Configured real-PG jobs fail instead of skipping missing clients.
    executable("pg_restore", pg_bin)
    return connection, pg_bin


@pytest.mark.asyncio
async def test_real_custom_archive_restores_full_rows_ids_sequences_foreign_keys_and_lobs(real_pg, tmp_path, monkeypatch):
    admin_info, pg_bin = real_pg
    suffix = uuid.uuid4().hex
    source_name = "caucashub_backup_fixture_" + suffix
    admin = await admin_info.connect()
    await assert_restore_admin(admin)  # CI/operator explicitly marks only its disposable local cluster.
    await admin.execute("CREATE DATABASE " + quote_identifier(source_name) + " TEMPLATE template0")
    await admin.close()
    source = Connection(admin_info.host, admin_info.port, source_name, admin_info.user,
                        admin_info.password, admin_info.sslmode, admin_info.passfile)
    conn = await source.connect()
    try:
        await conn.execute("""
            CREATE TYPE public.deal_state AS ENUM ('pending','completed');
            CREATE TABLE public.users(id bigserial PRIMARY KEY,email text NOT NULL UNIQUE,name text,legal_name_ka text);
            CREATE TABLE public.loads(id bigserial PRIMARY KEY,user_id bigint NOT NULL REFERENCES users(id),title text,location jsonb);
            CREATE TABLE public.transport(id bigserial PRIMARY KEY,user_id bigint REFERENCES users(id),capacity numeric);
            CREATE TABLE public.responses(id bigserial PRIMARY KEY,load_id bigint REFERENCES loads(id),user_id bigint REFERENCES users(id));
            CREATE TABLE public.deals(id bigserial PRIMARY KEY,load_id bigint REFERENCES loads(id),state deal_state);
            CREATE TABLE public.reviews(id bigserial PRIMARY KEY,deal_id bigint REFERENCES deals(id),comment text,public_comment boolean DEFAULT false);
            CREATE TABLE public.notifications(id bigserial PRIMARY KEY,user_id bigint REFERENCES users(id),payload jsonb);
            CREATE TABLE public.alembic_version(version_num varchar(32) PRIMARY KEY);
            CREATE INDEX loads_title_idx ON public.loads(title);
            CREATE VIEW public.completed_deals AS SELECT id,load_id FROM public.deals WHERE state='completed';
            INSERT INTO users(email,name,legal_name_ka) VALUES ('backup-fixture-only@example.test','TEST synthetic Cyrillic','ტესტი სახელი'),('second-backup@example.test','TEST Latin','მეორე ტესტი');
            INSERT INTO loads(user_id,title,location) VALUES(1,'TEST груз fixture', '{"lat":42.73548,"lon":44.63132,"label":"TEST синтетическая точка"}');
            INSERT INTO transport(user_id,capacity) VALUES(2,2500);
            INSERT INTO responses(load_id,user_id) VALUES(1,2);
            INSERT INTO deals(load_id,state) VALUES(1,'completed');
            INSERT INTO reviews(deal_id,comment) VALUES(1,'TEST private comment not to be logged');
            INSERT INTO notifications(user_id,payload) VALUES(1,'{"kind":"TEST"}');
            INSERT INTO alembic_version VALUES('028_document_names');
            SELECT lo_from_bytea(0,convert_to('TEST synthetic large object','UTF8'));
        """)
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            before = await fingerprint_database(conn)
        original_tool = database_backup.run_tool
        concurrent_update = False
        async def change_after_snapshot(tool, arguments, env, timeout=1800):
            nonlocal concurrent_update
            if "--format=custom" in arguments:
                other = await source.connect()
                try:
                    await other.execute("UPDATE loads SET title='TEST concurrent update after exported snapshot'")
                    # A real concurrent insert advances a non-MVCC sequence. The
                    # exported snapshot excludes its row; safe advanced counters
                    # must not be falsely reported as a corrupt archive.
                    await other.execute("INSERT INTO notifications(user_id,payload) VALUES(1,'{\"kind\":\"TEST concurrent\"}')")
                    concurrent_update = True
                finally:
                    await other.close()
            return await original_tool(tool, arguments, env, timeout)
        monkeypatch.setattr(database_backup, "run_tool", change_after_snapshot)
        manifest_path = await backup(source, tmp_path / "private-backups", pg_bin)
        assert concurrent_update is True
        await conn.execute("UPDATE loads SET title='TEST груз fixture'")
        await conn.execute("DELETE FROM notifications WHERE id>1")
        metadata, archive = load_manifest(manifest_path)
        assert archive.read_bytes()[:5] == b"PGDMP"
        assert metadata["database"] == before
        rendered = manifest_path.read_text(encoding="utf-8")
        for secret in ("backup-fixture-only@example.test", "TEST private comment", "TEST synthetic large object", "TEST synthetic Cyrillic"):
            assert secret not in rendered
        assert len(metadata["database"]["tables"]) == 8
        assert metadata["database"]["large_objects"]["count"] == 1
        assert metadata["database"]["foreign_keys"] == 7
        target = TEST_PREFIX + suffix
        report_path = await restore_test(admin_info, manifest_path, pg_bin, target)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["restore_verified"] is True
        assert report["table_counts_data_and_ids_match"] is True
        assert report["sequence_configuration_match"] is True and report["large_objects_match"] is True
        assert report["owned_sequence_next_values_safe"] is True
        assert report["validated_foreign_keys"] == 7
        restored = await admin_info.connect(database=target)
        try:
            assert await restored.fetchval("SELECT count(*) FROM users") == 2
            # Reject a broken relationship in the restored schema, not just count FK names.
            with pytest.raises(Exception) as error:
                await restored.execute("INSERT INTO responses(load_id,user_id) VALUES(99999,1)")
            assert type(error.value).__name__ == "ForeignKeyViolationError"
            await restored.execute("SELECT setval('users_id_seq',1,false)")
            invariant = await sequence_invariants(restored, metadata["database"]["sequences"])
            assert any(item["name"] == "users_id_seq" and item["safe_next_owned_id"] is False for item in invariant)
        finally:
            await restored.close()
        # Existing even marked targets must never be overwritten or cleaned.
        with pytest.raises(BackupError, match="already exists"):
            await restore_test(admin_info, manifest_path, pg_bin, target)
        stale = TEST_PREFIX + "stale_" + uuid.uuid4().hex
        admin = await admin_info.connect()
        try:
            await admin.execute("CREATE DATABASE " + quote_identifier(stale) + " TEMPLATE template0")
        finally:
            await admin.close()
        with pytest.raises(BackupError, match="already exists"):
            await restore_test(admin_info, manifest_path, pg_bin, stale)
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            assert await fingerprint_database(conn) == before
        # Keep evidence outside the source worktree, with only safe aggregate fields.
        output = os.environ.get("DATABASE_SAFETY_TEST_REPORT")
        if output:
            Path(output).write_text(json.dumps({"ok": True, "manifest": str(manifest_path),
                "restore_report": str(report_path), "archive_bytes": archive.stat().st_size,
                "tables": report["tables"], "rows": report["rows"], "foreign_keys": report["foreign_keys"],
                "synthetic_data_only": True}, indent=2), encoding="utf-8")
    finally:
        await conn.close()
