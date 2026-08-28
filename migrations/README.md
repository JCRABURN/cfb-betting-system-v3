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

## Confidence and ranking policies

Migration 7 creates `contest_ranking_policies` and
`contest_card_policy_assignments`. Policy definitions store separate
Confidence and ranking versions, monotonic model-uncertainty thresholds, the
unscored Confidence floor, exact Top 5 count, reliability metric, ordering
method, deterministic tie-breaker, effective time, author, and provenance.

A Confidence/ranking version pair is unique and immutable. Assignments are
append-only and must bind a policy that was already effective to the exact card
generation timestamp. The migration adds no policy definitions or assignments
and does not change existing card or pick rows. It also blocks new `official`
card rows until a later validated publication service can atomically enforce
all official-card gates; complete cards remain immutable `draft` snapshots with
an `official_ready` report.

## Reproducible card runs

Migration 8 creates immutable `contest_selection_policies`, their normalized
ordered `contest_selection_policy_books`, and one `card_run_manifests` row per
reproducible card. The manifest copies and cross-checks the model run's code,
model, feature-schema, configuration, and data-snapshot identifiers; all three
contest-policy versions; the card's locked-line hash and generation time; and
the count and SHA-256 fingerprint of adjustments visible at that instant.

Database triggers prevent policy or manifest replacement, mutation, and
deletion. A manifest cannot reference a partial book order or a policy/run that
does not match the card. New manual adjustments must follow their prediction
timestamp and cannot be backdated into an already frozen card history. The
migration adds no policy, manifest, adjustment, card, or pick rows.

## Daily refresh revision history

Migration 9 creates immutable `card_refresh_policies`, complete per-game
`card_revision_pick_changes`, and `card_refresh_revisions`. The operating
policy is explicitly UTC Tuesday through Saturday. Database checks derive the
stored operating date and weekday from the UTC refresh timestamp and require
the policy to have been effective before the prior card.

Each refresh must link consecutive card versions, cover the identical complete
set of locked-line IDs, preserve the prior selection and ranking policies, and
copy both cards' side, Confidence, rank, Top 5, prediction, and fallback values
exactly. Triggers reject incomplete histories, fabricated change flags, model
or adjustment mixing in `data_refresh`, model-run changes in
`contextual_adjustment`, and locked-line snapshot changes without an explicit
correction record and `data_correction` revision. All three tables are
append-only. The migration adds no policy, card, pick, revision, or history
rows.

## Manual contextual adjustment application

Migration 10 creates immutable `manual_adjustment_policies`, one
`card_adjustment_policy_assignments` row per generated card, ordered
`contest_pick_adjustment_items`, and one `contest_pick_adjustment_snapshots`
row per model-backed pick. The fixed policy applies signed adjustments
additively to home margin and Confidence, then clamps Confidence to 1–5.

Database triggers require the policy to be effective at card generation, each
item to reference an eligible as-of adjustment for the pick's exact model
prediction, and every snapshot to agree with the immutable raw prediction,
pick Confidence, item count, and numeric totals. Policies, assignments, items,
and snapshots cannot be replaced, updated, or deleted. The migration adds no
policy, assignment, item, snapshot, adjustment, card, or pick rows.

## Complete postgame audit ledger

Migration 11 creates immutable postgame-audit policies and their normalized
key-number, spread-bucket, and failure-taxonomy definitions. Card-level audit
runs contain complete per-pick details, normalized key-number crossings,
applicable failure records, and a completion seal with a canonical ledger
SHA-256 checksum.

Database triggers require each detail to match the card pick, effective locked
line as of card generation, completed game score, explicit pre-kickoff closing
line, selected-side ATS and CLV calculations, frozen adjustment snapshot,
Confidence, rank, Top 5, hook, key-number, favorite, location, and spread-
bucket classifications. A completion row is rejected until every card pick and
every required crossing and failure record is present. Confirmed backdoor
covers require stored scoring-sequence evidence; the default is explicitly
`not_evaluated`.

Policy definitions freeze on first use. Policies, runs, details, crossings,
failures, and completion seals cannot be replaced, updated, or deleted.
Corrections append a contiguous superseding run instead of altering history.
The migration adds no audit policies, runs, details, completion rows, game
results, market lines, cards, or picks.

## Weekly diagnostics and policy recommendations

Migration 12 creates immutable versioned diagnostic policies, append-only
weekly diagnostic runs, normalized segment aggregates, structured Lessons
Learned, numeric policy-change recommendations, and completion seals. The
`weekly_diagnostic_source_results` view exposes exactly eight required
dimensions from the completed per-pick audit ledger; raw-versus-adjusted
comparison uses only picks with a recorded raw-model result.

Database triggers require a completed postgame audit, an effective diagnostic
policy, contiguous supersession, exact recomputation of every segment, matching
lesson evidence, and recommendations that agree with the assigned immutable
Confidence/ranking policy. A candidate may only tighten an existing numeric
Confidence uncertainty threshold by the policy's predefined step, must name an
unused proposed version, and must require owner approval. The completion seal
requires all 26 segments, four Lessons Learned, and four recommendations before
recording the canonical SHA-256 ledger checksum.

Policies, runs, segments, lessons, recommendations, and completion seals cannot
be replaced, updated, or deleted. The migration adds no diagnostic policies or
runs, no recommendations, and no model, ranking, Confidence, card, line, audit,
workflow, or authoritative database rows.

## Official weekly controller

Migration 14 creates immutable weekly-controller policies and required-source
rules, controller runs, contest line-lock batches, per-card source decisions,
and official-card publication envelopes. It adds no policy, controller, line,
model, card, or publication rows and does not alter the immutable card table.

An official publication trigger rejects incomplete coverage, invalid
Confidence or ranking, missing manifests/policies, missing source evidence,
line-snapshot disagreement, and broken daily revision chains. Publication
rows, controller custody, line batches, and freshness decisions are append-only.
See `docs/WEEKLY_CONTROLLER.md` for the operating contract and recovery steps.

## Football identity foundation

Migration 19 creates an additive NCAA/NFL identity registry for franchises,
effective team names and alignments, exact sport-scoped aliases, versioned
venues, football events and append-only event revisions, provider event IDs,
and optional exact legacy-CFB links. It seeds only the immutable `NCAA` and
`NFL` sport rows. No current CFB table is rewritten, no legacy link is inferred,
and Product A does not read the new tables. See
`docs/FOOTBALL_IDENTITY_FOUNDATION.md` for the schema and recovery contract.

## Mixed Pick'em custody

Migration 20 adds the isolated Product B contest, source-import, manifest,
approval, earliest-kickoff deadline, and immutable line-lock custody tables. It
seeds only the `mixed_pickem` product and its NCAA/NFL allowlist, creates no
season, round, import, approval, or lock, and does not rewrite or reinterpret
Product A data. See `docs/MIXED_PICKEM_CUSTODY.md` for the staged operating and
recovery contract.

## Recovery

SQLite DDL is applied inside one transaction per migration. A failed migration
is rolled back and is not recorded in `schema_migrations`.

Before an explicitly authorized migration of an authoritative database, create
and verify a separate backup copy. If a committed migration later proves
incorrect, stop writers, preserve the failed database for audit, restore the
verified pre-migration copy, and deploy a new forward-fix migration. Do not
delete or edit migration-ledger rows manually.
