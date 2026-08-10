# Database migrations

The SQLite schema is managed by immutable, ordered modules in
`migrations/versions/`. `db.init_db()` applies every pending migration before
application code uses the database.

Each applied migration is recorded in `schema_migrations` with its version,
name, normalized source checksum, and UTC application time. The runner refuses
gapped history, renamed migrations, changed checksums, schema drift, integrity
failures, foreign-key violations, or changes to existing table row counts.

## Verify safely

Run this before merging any schema change:

```text
python -m scripts.verify_migrations
```

The command copies `data/cfb.db` into a temporary directory, records table row
counts, applies migrations to the copy, runs SQLite integrity and foreign-key
checks, verifies row counts, and confirms the source database hash did not
change. It never opens the authoritative database for writing.

## Add a migration

1. Add the next contiguous `vNNNN_description.py` module.
2. Define `VERSION`, `NAME`, `upgrade(conn)`, and `verify(conn)`.
3. Append the module to `MIGRATION_MODULES` without editing older modules.
4. Keep schema-only migrations row-count preserving.
5. Add normal-path, idempotence, failure, and disposable-copy tests.
6. Run migration verification and the complete test suite.

Never rewrite an applied migration. Fix a defect with a new forward migration.

## Immutable contest lines

Migration 5 adds `contests`, `contest_locked_lines`, and
`contest_line_corrections`. It does not import or reinterpret any legacy
`betting_lines` rows. The legacy table remains the market feed and is limited
to `opening`, `current`, and `closing`; a locked contest line cannot be stored
there.

Locked contest rows and their contest identity are immutable. Corrections are
full replacement snapshots linked in a contiguous append-only chain, while the
original lock remains unchanged. Database triggers reject updates, deletes,
replacement inserts, relocks, matchup collisions, invalid game mappings, and
out-of-order corrections even when a caller bypasses the Python service.

If captured contest data is wrong, use the correction service with a reason,
author, UTC timestamp, source, provenance reference, and payload checksum. Do
not edit the locked row or migration ledger.

## Separate business entities

Migration 6 creates explicit, empty tables for `model_runs`,
`model_predictions`, `contest_cards`, `contest_picks`,
`sportsbook_recommendations`, `card_revisions`, `manual_adjustments`, and
`pick_audits`. It does not transform, reinterpret, or delete legacy `picks`
rows. New writes use the typed functions in `business_entities`; the legacy
table remains a compatibility boundary until its existing readers and writers
are retired in later milestones.

The new tables are append-only. Database triggers reject updates, deletes,
and replacement inserts. Revision, adjustment, and audit histories use
contiguous supersession links, while cross-entity triggers prevent a card,
line, prediction, pick, recommendation, or closing line from being attached
to an unrelated contest or game.

## Recovery

SQLite DDL is applied inside one transaction per migration. A failed migration
is rolled back and is not recorded in `schema_migrations`.

Before an explicitly authorized migration of an authoritative database, create
and verify a separate backup copy. If a committed migration later proves
incorrect, stop writers, preserve the failed database for audit, restore the
verified pre-migration copy, and deploy a new forward-fix migration. Do not
delete or edit migration-ledger rows manually.
