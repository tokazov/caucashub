# Loading dates and periods — release checklist

Prepared for PR #28. Production is not updated by the feature branch.

## Changes

- Add nullable `loads.load_date_end` (Alembic 020 plus ADR-019 startup fallback).
- Interpret loading dates as calendar days in Asia/Tbilisi and store UTC.
- Accept legacy dd.mm.yy/dd.mm.yyyy and ISO timestamps; reject invalid periods.
- Use the last day of the period for public visibility, counters and tariff slots.
- Preserve both dates when loading and editing, and support explicit removal of the end.
- Require server confirmation when editing; a rejected edit keeps the previous values.
- Apply date filters as interval overlaps together with the other filters.
- Refresh the API/main script cache keys in both static entry points.

## Verification

The loading-period GitHub Actions workflow runs isolated SQLite/API tests,
an idempotent PostgreSQL migration against a disposable service, JavaScript
syntax checks and browser-logic tests in UTC and Pacific/Kiritimati.
It uses test-only credentials and never connects to production databases.
Existing publication-timestamp and transport-render regressions are included.

## Hosting verified on 26 October 2026

- Railway project: caucashub, environment production, service api.
- Source: tokazov/caucashub, branch master, builder RAILPACK (not Nixpacks).
- Current start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT.
- Current pre-deploy command: empty. nixpacks.toml is not the active migration mechanism.
- Production PostgreSQL image: postgres-ssl:18; CI now also uses PostgreSQL 18.
- Current API health check returned HTTP 200 with database, loads, geocoder and dictionaries OK.
- Current rollback deployment: bd246f7c-b92e-4fb1-aded-6f8530349079 (commit 1d5de50).
- The API service has no mounted volume, so a local pg_dump in an API build container
  must not be treated as a confirmed durable backup.

For this release, stage `python -m scripts.prepare_loading_period` as the Railway
pre-deploy command (120-second timeout) and `/health` as the healthcheck path.
The gate applies revision 020 alone with bounded PostgreSQL lock/statement timeouts
and verifies the column before the deployment may proceed. It does not stamp or
replay the historical Alembic chain. Normalizing that chain needs a separate audit.

## Deployment order

1. Confirm the actual Railway service/branch and Cloudflare project/output path.
   The repository contains both root and frontend copies. Updating both does not
   itself prove which copy the live service publishes.
2. Confirm a recent restorable database backup and record current deployment IDs.
3. Apply Alembic 020 to the intended backend database, or confirm that the new
   backend's ADR-019 startup fallback added the nullable column successfully.
4. Confirm the backend accepts, returns and retains both selected days after
   a reload using a designated test account. Do not notify real users.
5. Release the matching static files after the backend is ready. The older API
   accepts but discards the end date, so simultaneous independent auto-deploys
   are not sufficient evidence of a correct rollout.
6. Check create, edit, clear end, interval search, quota, mobile form and console
   against the deployed versions before marking this package released.

## Rollback and data limits

Rollback the application/static deployments to their recorded versions and
leave the new nullable column in place. A schema downgrade is unnecessary for
an application rollback and would discard newly saved end dates.
This change does not delete or rewrite existing load records.
End dates that the old application never saved cannot be recovered
automatically; owners must re-enter those periods.

## Remaining verification

The connected hosting configuration, production migration, deployment order,
and a real mobile/browser smoke check must be verified at rollout. Unit/API
and CI checks do not replace these checks.
