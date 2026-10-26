# Delivery completion, attributable reviews and final acts

## Contract

A participant confirms through POST /api/deals/{id}/confirm or the compatible
status commands delivered / delivered_shipper / delivered_carrier. Confirmations
are allowed from confirmed/loading/in_transit/delivered. The first confirmation
sets delivered; both confirmations set completed. Repeating completed/rated
confirmation is read-only. Canceled/disputed deals reject delivery confirmation.
Raw completed/rated status commands are rejected: use confirm/rate.

Each participant can store one review of the counterparty after completion.
POST /rate accepts score 1..5 and optional trimmed comment of at most 2000
characters. The first review keeps the established overall rated status; the
other participant can still leave their own review. Database uniqueness and
deal/user row locks prevent duplicate reviews and lost rating aggregates.

GET /my and mutation responses include viewer_has_rated, viewer_can_rate,
legacy_rating, my_review and counterparty_review. Reviews contain score,
comment and created_at. Mutation responses retain base deal fields; the
frontend must preserve enriched contacts/route and refresh GET /my.

Historical rated deals without review rows have legacy_rating=true and
viewer_can_rate=false. Their old rater, score and comment cannot be recovered,
so no review rows are fabricated and no second unattributable rating is allowed.

## Statistics

For newly completed transitions only, both parties' completed_deals_count and
legacy trips_count increase once. Ratings do not change these counters.
Each new stored review increments only its recipient's ratings_received_count;
that count, not trip count, weights the rating average.
Historical counts are retained as stored; this release does no repair/backfill.

The existing cargo/transport source lifecycle is retained: source records stay
taken until the first review changes them to completed.

## PDF

Final acts require completed/rated state and an active authorized participant.
Bearer headers and legacy query tokens share the normal account verifier,
including deletion, blocking and password-change invalidation. Acts use actual
Load data or TransportOffer plus TransportRequest data and RU/GE labels.
Responses are private/no-store. Old missing completion timestamps remain
unknown rather than being replaced with a fabricated completion date.

## Deployment

1. Run the full backend/SQLite/PostgreSQL/schema/PDF tests and combined browser
   journey against the exact proposed backend/frontend changes.
2. Deploy backend/schema first through the existing blocking Railpack command
   python -m scripts.prepare_loading_period.
3. The gate applies additive revision 022 directly, creates only a missing
   deal_reviews table, verifies columns/types/nullability, generated id primary
   key, unique key, score/distinct-participant checks, UTC-capable PostgreSQL
   timestamps and foreign keys, and SELECTs all required columns.
   No historical Alembic replay/stamp, review backfill or data rewrites occur.
4. Require the log 'Deal review schema ready; per-participant reviews enabled.'
   and a successful Railway deployment. /health alone does not prove readiness.
5. Publish the compatible frontend immediately after backend readiness and
   confirm desktop/mobile status, two independent reviews and RU/GE acts.

An older frontend has the existing delivered-state confirmation limitation;
the updated UI should follow backend deployment promptly. Backend fields and
legacy delivery commands remain available.

Rollback application/UI code while retaining the additive review table.
Do not downgrade 022 or drop reviews on production rollback.
