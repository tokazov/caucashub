# ADR-019: Emergency Inline Migrations as Alembic Fallback

## Status

ACCEPTED — 2026-05-13

## Context

Railway Hobby tier does not reliably execute nixpacks `[phases.migrate]` before the application container starts. This means Alembic migrations may not run before the service receives traffic, causing startup failures when new code references new schema.

To mitigate, `app/main.py` contains an `emergency_migrations()` function executed in `lifespan` startup that performs idempotent inline DDL operations (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`, `ALTER TYPE ... ADD VALUE IF NOT EXISTS`, etc).

This contradicts ADR-011 which mandates all schema changes through Alembic. ADR-019 explicitly authorizes the emergency mechanism with the constraints below.

**History:**
- First added: 2026-04-24 (commit `9a7acd1`) with Telegram notification feature
- Removed: 2026-05-04 (Track 11, ADR-011 Variant A)
- Restored: 2026-05-04 (commit `a45a43b`) — reason: Railway Hobby confirmed unreliable for `phases.migrate`
- Not documented until this ADR: 2026-05-13

## Decision

`emergency_migrations()` is an authorized escape-hatch that runs at every application startup.

### Allowed operations

- `ADD COLUMN IF NOT EXISTS` — non-destructive, idempotent
- `CREATE TABLE IF NOT EXISTS` — non-destructive, idempotent
- `CREATE INDEX IF NOT EXISTS` — non-destructive, idempotent
- `ALTER TYPE ... ADD VALUE IF NOT EXISTS` — enum extensions, guarded
- `ALTER COLUMN TYPE` to **wider** only (e.g. `VARCHAR(20) → VARCHAR(50)`) — no truncation risk

### Forbidden operations

- `DROP COLUMN` / `DROP TABLE` — irreversible data loss
- `ALTER COLUMN TYPE` to **narrower** — risk of silent data truncation
- Any `DELETE` / `UPDATE` statements — data mutation, not DDL
- Non-idempotent operations — must always be safe to re-run on every restart

### Process

1. Every change added to `emergency_migrations` **MUST also be added** to a corresponding Alembic migration file (`alembic/versions/NNN_*.py`). The official Alembic history must remain complete and reflect the actual schema.

2. The reverse is not required: Alembic-only migrations are allowed when Railway `phases.migrate` is verified to work or when running against non-Railway environments (CI, local dev).

3. When adding to `emergency_migrations`, add a comment with the Alembic migration number that covers this change, e.g.:
   ```python
   # Also in: 015_expand_status_changes_entity_type.py
   "ALTER TABLE status_changes ALTER COLUMN entity_type TYPE VARCHAR(50)",
   ```

### When to remove

`emergency_migrations` should be removed when:
- Migration to Railway Pro (or another host with reliable pre-deploy hooks), **OR**
- Migration to a self-managed entrypoint script that runs `alembic upgrade head` before `uvicorn` starts

## Consequences

### Positive

- Service survives deployments on Railway Hobby without manual intervention
- New columns/tables available immediately on container start
- No "service down during migration" window on Railway

### Negative

- DDL changes happen at every startup (small overhead, ~50ms)
- Two sources of schema truth — must be kept in sync manually
- Risk of forgetting the Alembic counterpart for inline changes (mitigated by audit process)
- `ALTER COLUMN TYPE` in emergency_migrations is not guarded by `IF NOT EXISTS` — runs every startup (but is Postgres no-op when type already matches)

## Audit

See `docs/SCHEMA_DRIFT_AUDIT_2026-05-13.md` for the current state of sync between `emergency_migrations` and Alembic versions.

## Related

- **ADR-011** (Pre-deploy Alembic migrations) — this ADR formally amends ADR-011 to allow `emergency_migrations` as a fallback path on Railway Hobby
- **PR #12** — first `ALTER COLUMN` in emergency_migrations (entity_type VARCHAR(20)→(50)), formalized by Alembic 015 in PR #13
