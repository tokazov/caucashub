# Carrier profile defaults release

The profile stores optional `truck_type` and `tonnage` defaults on the user.
Tonnage is in tonnes (maximum 100); vehicle/offer capacities remain in kg.
Saving a profile does not create, publish or modify a Truck or TransportOffer.
Existing user rows start with both values null; no backfill is performed.

## Backend/schema first

1. Review the backend/schema PR and its SQLite/PostgreSQL HTTP and migration CI.
2. Confirm Railway still uses the verified Railpack pre-deploy command
   `python -m scripts.prepare_loading_period`. The legacy `nixpacks.toml`
   path is not the active release gate.
3. Deploy backend/schema before merging the frontend PR. Every SQLAlchemy
   `SELECT(User)` references the new mapped columns, so `/health` alone is
   insufficient to prove schema readiness.
4. The pre-deploy gate applies revision 021 directly and idempotently,
   checks both column types/nullability and executes
   `SELECT truck_type, tonnage FROM users LIMIT 0`.
   It does not stamp or replay the historical Alembic chain.
5. Verify the successful pre-deploy log includes
   `Carrier profile schema ready; optional defaults enabled.`
   and the deployment completes successfully.
6. Verify the API with a disposable test account/environment: register with
   `truck_type=ref, tonnage=3.5`; PUT another valid pair; GET using a new
   login; omit fields to preserve them; send null to clear them.
   Do not use real customer accounts for test mutations.

No startup fallback is added: this release relies on the verified blocking
pre-deploy gate. Official migration history includes additive revision 021.

## Frontend second

After backend/schema is verified, retarget the stacked frontend PR to master
and confirm its diff contains only frontend files/tests. Run its complete CI,
merge, and verify the Cloudflare publication. Both HTML/JS copies are updated.
Verify registration, saving, reload and a new login in the browser. Validation
must keep settings open and highlight the type/capacity field; null defaults
must clear old local cache values.

## Rollback

Roll back application/frontend code while retaining the two nullable columns.
Old code ignores them. Never downgrade revision 021 or remove columns in a
production rollback: that would discard saved defaults. The migration's
downgrade is for disposable development/test databases only.
