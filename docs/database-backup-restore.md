# Full database archive and restore verification

`scripts/database_backup.py` replaces an API export for database recovery. It is
an operator tool, not a scheduled/offsite backup service. It never imports data
into a production database and has no `DROP DATABASE`, `--clean` or restore-to-
existing-database option.

## What is saved

The `backup` command uses PostgreSQL `pg_dump --format=custom`, without table or
schema filters. It includes every application table (users, loads, transport,
responses, deals, reviews, notifications and other tables), schema, indexes,
constraints, sequence values and PostgreSQL large objects. A read-only
repeatable-read transaction exports one snapshot, shared by metadata queries
and `pg_dump`. Concurrent table changes therefore do not mix different moments.

The archive includes database-private data, password hashes and private document
names. Treat it as confidential. It is not encrypted by pg_dump. Use a protected
encrypted disk and an encrypted independent/offsite copy; a copy on the same
computer is insufficient disaster recovery. This tool restricts a newly written
directory to its owner (and SYSTEM on Windows), refuses output inside the source
worktree and does not print connection URLs, PostgreSQL diagnostic bodies or rows.
It accepts only a fresh empty output folder or a folder already carrying its
backup-purpose marker; it will not reset permissions on an unrelated folder.

It does not include cluster roles/tablespaces, server configuration/secrets,
external upload/object storage files or WAL/PITR history. The original archive
retains database ownership/ACL information; a local restore drill deliberately
does not apply that ownership/ACL. Native database backups and PITR are separate
controls and must also have a verified retention schedule.

## Operator: create an archive

Install matching PostgreSQL client tools. For PostgreSQL 18 use PostgreSQL 18 or
a supported newer pg_dump. Official Windows binaries are linked by
<https://www.postgresql.org/download/windows/> to EnterpriseDB; no Windows service
or global PATH change is required. Python dependencies include the project's
`asyncpg` requirement.

Run in a real interactive terminal from the repository root:

```powershell
python -m scripts.database_backup backup --prompt-source --pg-bin "C:\path\to\pgsql\bin" --output-dir "C:\private-backups\CaucasHub"
```

Paste the PostgreSQL connection URL only into the hidden prompt, never into a
chat, command argument, Git file, screenshot or shell history. The prompt refuses
non-interactive input. Remote connections require TLS (`sslmode=require` or
certificate-verifying modes). The URL stays in process memory; child PostgreSQL
tools receive connection settings through their environment, not command-line
arguments. An operator-managed `PGPASSFILE` is also supported when the URL omits
the password.

For a secret manager/approved runtime, the alternative is an explicitly named
environment variable: `--database-env BACKUP_DATABASE_URL`. Do not put its value
in a shell command that will be logged. No secret is discovered from `.env` files
or an application configuration automatically.

Success prints only a manifest path. Keep the adjacent `.dump` and
`.manifest.json` together. The manifest contains a SHA-256 archive checksum,
schema definitions represented by hashes, table counts, aggregate row/record-ID
hashes, sequence configurations and large-object hashes. It never contains row
values. A successful dump is marked `restore_verified: false`: it must not be
described as a tested recovery until the restore report succeeds.

## Restore drill: fresh, marked, local PostgreSQL only

Use a separate disposable local PostgreSQL cluster that you created yourself,
with password authentication, loopback listening and a protected data directory.
Do not use an SSH tunnel, proxy, the live application database or a shared server.
The administrator connection must use the literal `127.0.0.1` or `::1` and the
`postgres` maintenance database. Hostnames (including `localhost`) are rejected.

In that **disposable cluster only**, the operator/CI setup must explicitly set:

```sql
COMMENT ON DATABASE postgres IS 'caucashub-disposable-restore-admin-v1';
```

Do not run that statement on production. The restore tool never sets this
administrator marker itself. It requires it before creating any target database.
The source production connection is never used as the restore administrator.

```powershell
python -m scripts.database_backup restore-test --prompt-admin --pg-bin "C:\path\to\pgsql\bin" --manifest "C:\private-backups\CaucasHub\caucashub_DATE.manifest.json"
```

Enter the local `postgres` maintenance URL in the hidden prompt. The tool checks
the archive checksum, validates the connected server/administrator marker,
creates a unique `caucashub_restore_test_...` database, marks it as disposable,
checks that it is still empty and restores in one transaction with
`--exit-on-error`. It never reuses an existing target, even an older marked one.
It compares structure, every table's row count/data hash/record-ID aggregate,
sequence configuration, foreign-key definitions/validation and large objects.
For each non-cycling sequence owned by a table column, it also checks that the
next ID is beyond the restored rows, preventing collisions. Only matching data
and structure with safe owned IDs produce `restore_verified: true` in a separate
dated report. Unowned/cycling sequence values are included in the archive but are
explicitly listed as not independently verified by that ID invariant.

Sequence counters are PostgreSQL non-MVCC state and can legitimately advance
during an archive. The tool compares static configuration and restored next-ID
safety rather than treating a safe advanced counter as corrupted data. It does
not claim byte-for-byte equality with a source counter read at an earlier moment.
No application writes are blocked to force this comparison to pass.

The tool leaves the disposable database intact for inspection. It never drops a
database or deletes older archives. Apply an explicit retention policy separately;
do not prune the only known-good archive before another restore has passed.

## Release checklist

Before a production schema change, record the timestamp and successful status of
a fresh native Railway volume backup. A scheduled future backup is insufficient.
Keep an independent protected archive and its successful restore report; do not
label an untested archive as recoverable. The native schedule and this operator
tool do not automatically create an independent offsite copy before every deploy.

Run the full regression suite against disposable data and test the intended
additive migration on an isolated restored copy. Confirm that existing customer,
listing, response, deal and review IDs and records are retained. Apply the release
only after these checks pass, then verify API health and the main user journeys.

If a release fails, roll back application code while retaining the current
customer database. Never automatically replace it with an older snapshot: that
would lose registrations, requests and other writes made after the snapshot.
An actual production recovery requires a separate reviewed cutover plan that
accounts for those newer writes. This utility intentionally has no such command.

## Regression proof

```text
python -m pytest tests/test_database_backup.py -q
```

Synchronous guards reject remote/unapproved targets, unsafe libpq overrides,
source-worktree output, non-interactive password prompts, path traversal and
checksum corruption. Additional guards reject an unmarked administrator and an
unmarked/nonempty target. The real integration case requires a synthetic local
PostgreSQL 18 CI service with the administrator marker, `TEST_POSTGRES_URL` and
`PG_BIN` (or `POSTGRES_BIN`; PATH also works). If the URL is configured, missing
clients are an error, not a skipped recovery test.

That case creates synthetic users/loads/transport/responses/deals/reviews/
notifications, a view, index, enum and large object; makes an archive; changes a
source row and advances a sequence after snapshot export to prove that the table
archive remains consistent and safe counter advancement is accepted;
restores into a fresh database; compares all fingerprints; exercises a real
foreign-key violation; rejects both an existing marked target and an unmarked
stale one; and proves metadata contains no fixture personal text.

This test does not prove a production archive exists, a cloud backup schedule is
enabled, credentials are available or a production recovery has been rehearsed.
Record those operational checks independently before a release.
