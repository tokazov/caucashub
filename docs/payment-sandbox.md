# Payment sandbox

This is an isolated simulator for reviewing CaucasHub's payment rules. It uses
fake customers, fake orders, simulated provider events and its own disposable
SQLite database. It does not charge cards, call TBC/BOG, activate production
plans, promote real loads, or send email/Telegram notifications.

The simulator is **not imported or mounted by app.main**. Creating its default
FastAPI app is disabled and does not import the sandbox database module. Do not
add this factory to the Railway start command or to the production router tree.

## Run locally

From the repository root, with project dependencies installed:

```console
python -m scripts.payment_sandbox --enable-sandbox
```

Open http://127.0.0.1:8878/. An explicit `--enable-sandbox` is required. The
listener is fixed to 127.0.0.1; there is no public-host flag. An optional `--port`
changes the port. The factory and launcher refuse Railway runtime markers.

Every run creates a new `session-*.sandbox.sqlite3` under
`artifacts/payment-sandbox/`. The file is retained for local inspection after
shutdown and can be discarded with the other test artifacts. It contains only
demo data. The launcher never reads `.env`, `DATABASE_URL`, production settings
or bank credentials. Test databases are excluded by the existing Git ignore.

`--project techrent` demonstrates an empty product namespace. It does not invent
TechRent prices, enable cross-project purchases or grant CaucasHub services.

## Review flow

1. Choose the Alice demo customer. This is an explicit fake-account session,
   not registration or real authentication.
2. Inspect the catalogue. Pro is 49 GEL/30 days; promotion options are
   5/12/25 GEL for 24/72/168 hours. Business is visible as disabled: its team
   capabilities are not implemented or offered for purchase.
3. Create an order. Price, currency, duration, customer and project are decided
   by the server. Promotion requires an eligible load owned by the demo buyer.
4. Simulate a paid, failed, cancelled or expired event. Only the paid outcome
   can issue a sandbox grant.
5. Repeat the paid simulation: the same order must not grant a second period.
6. Buy the same product again to inspect early renewal from the current end.
7. Switch to Bob: Alice's orders and grants must not become Bob's resources.
8. A full refund can be simulated for the latest grant on a resource. If a
   later grant exists, the simulator rejects the refund with a conflict rather
   than silently shortening another purchase. Partial refunds and disputes are
   deliberately outside this first version.

The expired demo load is not eligible for promotion. Times are UTC ISO strings;
access is evaluated from start/end times, not a permanent paid flag.

## HTTP contract

All routes below are local simulator routes, not production payment endpoints.

| Method | Route | Meaning |
|---|---|---|
| GET | `/health` | Simulator enabled/disabled state |
| POST | `/api/session` | Select `{ "customer_id": "alice" }` or `bob` |
| GET | `/api/state` | Current demo customer, catalogue, targets, orders, grants and time |
| POST | `/api/orders` | Create an order with product code and optional target ID |
| GET | `/api/orders/{id}` | Read the current demo customer's order |
| POST | `/api/orders/{id}/simulate` | Simulate an allowed outcome for that customer's order |

Order creation requires an `Idempotency-Key` header. Reusing a key for the same
request returns the same order; changing the request under that key is a
conflict. Order endpoints return an order object directly. Application errors
use `detail: {code, message}`; malformed request bodies use FastAPI validation
errors. Extra request fields are forbidden, including client-supplied price,
currency, project, owner, provider ID or entitlement duration.

The demo session is a random server-memory cookie, HttpOnly, SameSite=Strict,
scoped to `/api` and limited to one hour. Its name includes the project and a
random app-instance suffix, so parallel simulators on different localhost ports
do not overwrite each other's sessions, including two copies of CaucasHub.
Sessions are lost when the process restarts.
Requests require a loopback Host; mutating browser requests must be same-origin.
There is no CORS configuration and no external font, script or payment resource.
The simulator signs its own fake events in-process; this is **not** a TBC or BOG
signature implementation and is not a production webhook verification scheme.

## Boundaries before any real-money release

This sandbox is not a bank-certified test integration, checkout implementation,
accounting system or real subscription-access layer. Its grants remain in the
isolated sandbox tables and do not change ordinary User.plan or Load.is_boosted.

Before real payments: choose the company's bank and approved sites; implement
the selected provider's current protocol and signature/status verification;
build reconciliation, auditable fulfilment and refunds; define real customer
and company roles; migrate the production entitlement model; and verify the
full lifecycle against the bank's test environment. Obtain separate approval
before publishing code, changing live settings or making a control payment.
