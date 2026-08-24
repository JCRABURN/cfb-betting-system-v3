# Official weekly controller

Milestone 15 adds one authoritative orchestration boundary for Tuesday lock day
and Wednesday-through-Saturday revisions. It composes the existing immutable
line, model, adjustment, card, manifest, and revision services; it does not
replace them or create a second card engine.

## Official-card meaning

An official version is an immutable `official_card_publications` row pointing
to a complete immutable `contest_cards` snapshot. The card row remains marked
`draft` because migration 6 made every card field immutable and migration 7
correctly blocked direct `official` inserts before a validated publisher
existed. Migration 14 preserves those old contracts. The new publication
envelope is the sole authoritative official-status record.

Publication is the final insert in one SQLite transaction. Database triggers
independently require:

- one locked line and one home/away pick for every declared lined FBS game;
- no extra or duplicate pick;
- Confidence 1 through 5 for every pick;
- an exact ranked Top 5, or every game when fewer than five exist;
- immutable selection, Confidence, ranking, adjustment, refresh, and weekly
  controller policies;
- complete model/card manifest identifiers;
- matching line-snapshot hashes;
- all five source-freshness decisions;
- current provider custody or a versioned, explicitly permitted fallback;
- an unbroken prior-publication/card-revision chain for daily refreshes.

No reader should infer official status from `contest_cards.status`. Readers
must start from `official_card_publications` or the read-only inspection API.

## Tuesday lock flow

`run_tuesday_controller()` performs the following controlled sequence:

1. optionally invokes a configured data-refresh adapter;
2. evaluates point-in-time source freshness;
3. verifies the authorized source is SplashSports;
4. verifies the declared expected game count equals the imported line count;
5. resolves every raw team name through `CanonicalTeamResolver`;
6. rejects unknown, ambiguous, duplicate, reversed, missing, or multiply mapped
   FBS matchups;
7. creates the contest and immutable original line rows;
8. calculates the complete locked-line snapshot hash;
9. runs only the active EPA-only walk-forward baseline;
10. records any fully evidenced contextual adjustments separately from raw
    predictions;
11. generates a complete card through `generate_full_card()`;
12. validates fallback provenance, Confidence, ranking, policies, and the
    reproducibility manifest;
13. records the controller run, line batch, and source decisions;
14. inserts the official publication envelope last;
15. immediately reproduces the publication through the read-only inspector.

The line-batch payload reference is stored without URL query or fragment data.
Every line preserves the raw and canonical team names, source line identifier,
payload checksum, source, capture timestamp, and provenance.

Identical controller `run_key` replay returns the existing publication without
running the model again. Every run stores a canonical request SHA-256 and the
same key with different inputs fails as a conflict. A different run may not
relock an existing matchup, even when the submitted values are identical.

## EPA-only production model

The controller imports only `models.baseline_epa` and the existing sanctioned
point-in-time accessors in `models.backtest_harness`. It stores:

- model name `epa_only`;
- model version `epa-only-linear-v1`;
- feature schema `epa-differential-v1`;
- configuration `walk-forward-prior-seasons-v1`;
- code commit SHA;
- canonical data-snapshot SHA-256;
- training seasons and row count;
- explicit per-game missing-input skips.

Missing EPA or training inputs produce no fabricated forecast. The completed
operational model run records the skip, and the contest engine continues down
its versioned fallback hierarchy so every locked game still receives a side,
Confidence, and ranking. The ridge, dynamic-rating, and gradient-boosted
research candidates have no import or activation path in this controller.
Research promotion criteria are unchanged.

The baseline does not currently emit calibrated per-game uncertainty. Those
forecasts therefore receive the existing explicit unscored Confidence floor of
1. This limitation is visible in the card; the controller does not invent an
uncertainty estimate or rank by raw edge.

## Source freshness and fallbacks

Every weekly-controller policy must declare exactly one provider and one
permitted fallback code for each source in this fixed order:

1. odds;
2. injuries;
3. weather;
4. game status;
5. contextual data.

Current custody cannot be accompanied by a fallback. Partial, stale, or
missing custody cannot publish without a matching fallback code, reason,
evidence, and provenance. The decision is copied into immutable
`card_source_freshness` rows for that card version.

Milestone 15 rejects official selection policies with legacy market-book
fallbacks because `betting_lines` does not yet carry a direct acceptance ID
back to Milestone 14 custody. The official hierarchy therefore continues from
an unavailable model prediction directly to the locked-line underdog/pick'em
fallback. This conservative restriction prevents a stale legacy market row
from being silently treated as current. A future market fallback must first
add end-to-end acceptance lineage and adversarial tests in a separate change.

## Wednesday-through-Saturday refreshes

`run_daily_controller()` requires the latest valid official publication and a
strictly later Wednesday-through-Saturday UTC timestamp. It reuses the prior
selection, Confidence, ranking, and adjustment policies through
`refresh_full_card()`.

Each successful revision preserves both card snapshots and records every
locked line's prior and new side, Confidence, rank, Top 5 status, model
prediction, and fallback code. The reason, author, change type, source
freshness, data/model manifests, and adjustment history remain queryable.

- `data_refresh`, `bug_fix`, and `data_correction` run a new EPA-only model
  snapshot under the locked model/feature/configuration identifiers.
- `contextual_adjustment` reuses the exact prior model run and appends fully
  evidenced adjustments; raw predictions are not rewritten.
- a corrected line uses the existing append-only correction mechanism and an
  explicit `data_correction` revision. The original lock row never changes.
- branching from an older official publication is rejected.

Sportsbook recommendations remain a separate product and are never inferred
from mandatory contest picks. The controller accepts only explicit,
model-backed `SportsbookNoBetInput` advice and links each immutable no-bet row
to that official card version's contest pick. An actual bet recommendation
requires a directly custodied offered line and is not enabled in Milestone 15.
The database closes that version to additional recommendation rows as soon as
its official publication exists. This milestone does not place wagers.

## Dry run

Both controller entry points accept `dry_run=True`. Dry run clones the complete
SQLite connection into an isolated in-memory database, executes the same
migration triggers and publication gates there, returns the projected result,
and discards the clone. The authoritative connection must have no active
transaction and receives no rows.

## Read-only inspection

Use the publication key or identifier:

```text
python -m scripts.inspect_official_card \
  --database path/to/database.db \
  --publication-key splashsports-2026-week-1-official-v1
```

The command opens SQLite with `mode=ro` and `query_only=ON`. It recomputes the
complete-card report and canonical publication-manifest hash and reports
whether the version is the latest official version. It performs no API calls
and no database writes.

## Transaction and failure behavior

Line locking, model records, adjustments, card generation, policy assignments,
manifest creation, controller custody, and publication are one savepoint-backed
operation after optional provider refresh. Any failure after card generation
rolls all of those objects back, leaving no partially official card. The
optional provider refresh remains separately auditable in the Milestone 14
custody ledger.

A persisted failed attempt may record an immutable failed controller-run row
without a contest or card. Reuse of that failed `run_key` is rejected; retry
with a new operational identity after correcting the cause.

## Migration recovery

Migration 14 creates only empty tables, indexes, and triggers. It does not
change existing table definitions or rows.

If application fails, the migration transaction rolls back. If migration 14
has been applied and recovery is required, stop writers, restore the verified
complete pre-migration database snapshot, run SQLite integrity and foreign-key
checks, and deploy code whose migration ledger ends at version 13. Do not
delete migration-ledger rows or manually drop publication objects in place.

## Operational limitations

- The production adapter accepts only controlled provider bundles captured
  after explicit authorization and replays them through Milestone 14 custody.
  No live call occurs during ordinary tests or preflight.
- The production gateway supports exact-confirmation manual dispatch and
  owner-reviewed scheduled entries. Both require every cutover guard and run
  on GitHub-hosted `ubuntu-latest`. Idle dispatcher heartbeats make no provider
  or database call. Managed PostgreSQL holds the cross-run advisory lock and
  immutable durable snapshot history; the SQLite execution workspace is
  temporary and is discarded after the PostgreSQL transaction commits or
  rolls back. No owner computer or self-managed runner is required.
- Production credentials are not required, read, logged, or documented by
  value.
- Production cutover remains blocked by the explicit findings in
  `docs/PRODUCTION_CUTOVER.md`.
- The deterministic historical end-to-end dress rehearsal is documented in
  `docs/HISTORICAL_REHEARSAL.md`.
