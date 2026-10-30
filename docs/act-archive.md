# Issued act archive

An act is archived on its first successful authenticated PDF download. The
archive contains its issue timestamp, the source document fields, both language
versions of the generated PDF, and integrity hashes. Later downloads return the
stored bytes rather than rebuilding the document from editable profiles.

## Capture and access

- Only a current authenticated participant of a completed/rated deal with both
  delivery confirmations can issue the first act. Both Georgian legal names
  must be confirmed before capture.
- The first issue captures names, tax identifiers, displayed contact details,
  shipment details, route, dates, agreed amount/currency and document number.
  Unused email fields are excluded. Both language files are saved together.
- Two concurrent requests must produce one archive bundle for the deal. A failed
  PDF generation or database commit must not leave a partially issued archive.
  The archive is committed before the HTTP response is sent. If the browser
  cancels the transfer, a retry retrieves the same already prepared file.
- Once issued, later profile edits, confirmation revocation or counterparty soft
  deletion do not rewrite the archived file. A deleted account still cannot
  authenticate. The surviving participant retains private access to the act.
- Public profiles and ordinary deal JSON never expose the private snapshot or
  PDF bytes. An integrity failure blocks download; the application must not
  silently regenerate or replace an issued document.

## Accounting export

For a deal with an issued act, CSV uses its archived accounting fields so that
its names, tax identifiers, route, shipment details and amount match the act.
Unissued rows keep their existing confirmation requirements and current values.
For transport deals, cargo description and cargo weight come from the accepted
transport request, not the vehicle's notes or carrying capacity. Missing cargo
weight remains unknown rather than being replaced with vehicle capacity.
Export alone does not issue acts or manufacture historical document snapshots.
JSON remains an account overview with current display names and archive status,
not a route for retrieving private legal-name snapshots.
An invalid private snapshot blocks CSV rather than guessing its contents or
period. Because snapshot integrity is checked before its frozen period is read,
one corrupt snapshot can also block an export for another period. Recover the
original from a verified backup; do not recreate it from current profile data.

## Existing records and corrections

The additive migration creates an empty archive table. It never backfills
previous deals from today's profiles and does not claim to recover a PDF that
was downloaded before this archive existed. Such a deal is captured at its
first download after the feature is enabled; its actual archive timestamp is
retained independently of the older deal completion date.
Existing completion/calendar-date semantics are preserved. Archive timestamps
are stored as UTC instants and shown in the cabinet in Asia/Tbilisi time.

There is no edit/overwrite endpoint for issued acts. A future correction flow
must issue an explicitly numbered revision and preserve the earlier document;
it is outside this change. This archive is application-level preservation, not
a digital signature, a trusted timestamp or a tax-authority submission.

## Storage and deployment

The archive stays in the existing private PostgreSQL database. Full database
backups include its JSON and binary PDF columns; no new object store, account or
access credential is required. Backup/restore tests exercise zero and high-bit
bytes in both language files and verify their hashes after real pg_restore.

Preparation, schema verification and rollback tests run against disposable local
databases. Startup/health checks stay read-only. Publication requires the owner's
approval and a successful exact-source CI run. Historical document data remains
private to the transaction participants; retention/purge policy and any legal
requirements require a separate explicit decision before automated deletion is
introduced.
