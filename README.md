# CFB Betting System V3

This repository is the isolated development copy of the College Football
Spread Betting System. Repository-wide agent and data-integrity rules are in
`AGENTS.md`.

## Reproducible development baseline

Python 3.11 is the supported automation runtime. Runtime packages and their
transitive dependencies are pinned in `requirements.txt`; test-only packages
are pinned in `requirements-dev.txt`. No new top-level package was introduced
by this lock—the existing `requests` and `pytest` dependencies are now resolved
deterministically.

Create an isolated virtual environment, then install and verify with:

```text
python -m pip install --requirement requirements-dev.txt
python scripts/verify_repo_safety.py
python -m pytest -q
```

Dependency updates must be intentional, must keep every requirement exactly
pinned, and must pass both verification commands.

## Workflow safety

Pull requests run the complete offline test suite with read-only repository
permissions. The copied production workflows have no schedule trigger in V3,
are serialized with concurrency controls, and contain an allow-list guard that
keeps their data-writing jobs inert outside `JCRABURN/cfb-betting-system`.

Do not weaken or remove those controls without explicit repository-owner
approval and a dedicated pull request.

The additional V3 production gateway is manual-only, protected by independent
production/execution/owner flags and a kill switch, and read-only by default.
Its installed adapter can persist only after a passing preflight, exact CLI
confirmation, protected-environment approval, and cross-process writer lock.
Persisted workflow execution requires the dedicated durable
`cfb-v3-production` self-hosted runner; disposable hosted runners are not
allowed to write the authoritative SQLite database. Each operation verifies a
staging copy, creates a checksummed recovery backup, and atomically replaces
the database only after success. No schedule is enabled.

## Database migrations

Schema changes use ordered, checksummed migration modules and a
`schema_migrations` ledger. Verify the entire migration chain against a
disposable copy of `data/cfb.db` with:

```text
python -m scripts.verify_migrations
```

The authoritative database is never opened for writing by that command. See
`migrations/README.md` for migration and recovery requirements.

## Contest line custody

Market and contest lines are separate records with different rules:

- `betting_lines` accepts only `opening`, `current`, and `closing` market
  snapshots.
- `contests` identifies the source contest for one season and week.
- `contest_locked_lines` stores the original contest lock, including raw and
  normalized team names, source identifiers, UTC lock time, provenance, and
  source-payload checksum.
- `contest_line_corrections` stores append-only corrected snapshots with the
  reason, author, timestamp, source, and superseded correction link.

Use `contest_lines.py` to create contests, lock lines, record corrections, and
read the effective corrected value. An identical lock replay is idempotent. A
changed replay, direct update, delete, replacement, duplicate matchup, or
out-of-order correction fails at the database boundary. The original locked
row is never rewritten by a correction.

## Separate business records

New work must not overload the legacy `picks` table. The
`business_entities` package records model runs, raw model predictions, contest
cards, contest picks, sportsbook recommendations, card revisions, manual
adjustments, and pick audits in distinct append-only tables. The legacy table
remains unchanged for the existing compatibility pipeline and historical
reads; it is not the persistence API for new features.

Every new record has a stable key, UTC timestamp, provenance, typed fields,
and database-enforced immutability. A contest pick does not create a wager,
manual context does not rewrite a raw prediction, and a revised card or audit
is linked to the prior record instead of replacing it.

## Full-card contest engine

Use `business_entities.generate_full_card()` to produce one recorded home or
away side for every line locked in a contest. It reads the effective locked
line state as of the card timestamp and applies this versioned hierarchy:

1. A point-in-time model prediction from the card's completed model run.
2. The first actionable pre-generation `current` line from the policy's
   ordered real-book list.
3. The first actionable pre-generation `opening` line from that list.
4. The locked-line underdog, with a versioned home/away tiebreak for pick'em.

Every non-model decision records a fallback code and provenance. Consensus,
closing, future-captured, unresolved, mismatched, and post-kickoff data cannot
enter the hierarchy. Generation is atomic and fails rather than omitting a
locked game.

The engine also requires a `ConfidenceRankingPolicy`. Model-backed picks map
their explicit `uncertainty_points` through versioned thresholds to Confidence
1–5. Picks without that reliability input, including fallback selections,
receive the visible conservative floor of 1 rather than an invented estimate.
The Top 5 is ordered by Confidence descending, then lower model uncertainty,
then immutable locked-line ID for exact ties. Raw model edge is not a ranking
input.

Policy definitions and card assignments are stored in immutable
`contest_ranking_policies` and `contest_card_policy_assignments` records. A
confidence/ranking version pair cannot silently change meaning between cards.
`inspect_full_card()` and `validate_full_card()` replay both supplied policies
and enforce complete Confidence coverage, exact Top 5 count and ranks, snapshot
integrity, and provenance.

Manual context is applied through a separate immutable policy. Each sourced
injury, quarterback, coaching, travel, weather, motivation, or matchup entry
retains its signed home-margin and Confidence effects, evidence, source,
author, timestamp, and provenance. Card generation adds the eligible effects
visible at its point-in-time timestamp, clamps adjusted Confidence to 1–5, and
freezes per-pick raw values, totals, adjusted values, and ordered adjustment
IDs. The raw model prediction is never edited.

Generation still creates a draft: passing `official_ready` means every contest
gate is satisfied, not that the card was automatically published. New
`official` rows are blocked until a validated publication service is added.
Contest ranking remains separate from sportsbook recommendations. The legacy
`models/card_generator.py` remains unchanged as a compatibility path and is not
used by this engine.

## Complete postgame audits

Use `business_entities.audit_contest_card()` to grade an entire recorded card
in one transaction. The caller must identify one explicit, pre-kickoff
`closing` market line for every locked contest line. The service derives ATS
win/loss/push, selected-side CLV, hook and key-number outcomes, favorite or
underdog, location, spread bucket, Confidence, rank, Top 5, and raw-versus-
adjusted model results from immutable card inputs and completed game scores.

Each audit uses an immutable versioned policy and seals the full per-pick
ledger with a SHA-256 checksum. Corrections append a new card audit run and new
pick-audit sequences; they never overwrite a prior result. A run cannot be
marked complete unless every card pick has a detail record, all applicable key
crossings are recorded, and every result has a controlled failure-taxonomy
entry. `inspect_postgame_audit_run()` and `validate_postgame_audit_run()`
recompute coverage, result counts, and the ledger checksum.

Backdoor outcomes default to `not_evaluated`. A confirmed classification is
accepted only with explicit scoring-sequence evidence; the service never
infers a backdoor cover from the final score alone. Audit persistence does not
write the legacy `picks` table or alter locked contest lines, cards, model
predictions, adjustment snapshots, or market-line history.

## Weekly diagnostics and policy versioning

Use `business_entities.generate_weekly_diagnostics()` only after a complete,
validated card audit. One immutable diagnostic run records all 26 normalized
cuts required for favorites/underdogs, home/away/neutral, spread buckets, road
favorites, Confidence 1–5, Top 5 versus the remaining card, raw model versus
final adjusted selections, and positive/neutral/negative CLV. ATS rate is wins
divided by decisions; pushes remain visible in the sample but not the rate.

Each run also stores four explicitly descriptive Lessons Learned and four
numeric Confidence-threshold recommendations. The versioned diagnostic policy
sets the minimum sample, minimum underperformance delta, and permitted numeric
tightening step. Insufficient or unsupported evidence produces a hold. A
qualified result produces only `candidate_pending_owner_approval`, names a new
proposed Confidence-policy version, and never registers or assigns that version.
No active model, ranking, Confidence, card, line, audit, or adjustment record is
changed. Corrections append a new superseding diagnostic run, and the complete
evidence ledger is sealed with a SHA-256 checksum.

## Model research framework

`models.research_framework` evaluates new models without changing the active
EPA-only baseline. It builds sealed observations through the existing
point-in-time accessor, predicts market residual against a genuine opening
line, and keeps final scores and closing lines outside the model-input type.
Weekly rolling-origin folds train and calibrate only on earlier weeks; every
model is evaluated on the identical out-of-sample games.

The framework includes the EPA-only residual baseline plus pure-Python ridge,
dynamic team-rating, and gradient-boosted-stump candidates. A chronological
holdout inside each training fold supplies isotonic cover-probability
calibration and uncertainty. Reports include margin MAE/RMSE, Brier score, log
loss, calibration error, ATS, ROI after −110 vig, CLV, maximum drawdown, and
Confidence-rank monotonicity. The versioned v1 policy freezes every threshold
before results are observed. Clearing every gate creates only an owner-pending
candidate under a new model version; the framework has no activation path.

Run the complete predefined suite against a database snapshot with:

```text
python -m models.run_research \
  --database data/cfb.db \
  --code-commit-sha COMMIT_SHA
```

The command opens SQLite read-only/query-only, includes the database SHA-256,
code commit, feature-schema/configuration versions, fold membership, skips,
predictions, metrics, decisions, and canonical ledger hash in JSON on stdout.
It performs no API calls and writes no files or database rows.

## Provider ingestion custody

`ingestion.custody` is the fixture-driven boundary for provider data. Each run
records provider, endpoint without query credentials, sanitized request
parameters, UTC request time, parser version, exact payload checksum, replay
reference, accepted/rejected counts, and final status. Invalid records are
quarantined with stable reason codes. Every typed adapter records an immutable
provider-neutral acceptance, and only strictly validated, canonically mapped
spread records enter immutable `provider_market_snapshots`.

Freshness policy `provider_freshness_v1` defines explicit windows for odds,
injuries, weather, game status, and contextual data. Its as-of inspection API
returns current, partial, stale, or missing without reading a future run. A
partial/stale/missing source must be handled by an explicit controller fallback
and can never justify omitting a locked lined game.

Use the offline-only fixture replay command with a disposable database:

```text
python -m ingestion.replay \
  --database path/to/disposable.db \
  --fixture tests/fixtures/provider_ingestion/odds_valid.json \
  --requested-at 2026-08-25T15:00:00+00:00
```

The command refuses `data/cfb.db` and makes no live API call. Full custody,
quarantine, freshness, replay, and recovery details are in
`docs/INGESTION_CUSTODY.md`.

## Official weekly controller

`business_entities.weekly_controller` is the authoritative Tuesday-through-
Saturday contest path. Tuesday imports one declared complete SplashSports line
batch, resolves every team centrally, locks every matchup once, runs only the
EPA-only baseline, applies separately recorded adjustments, generates a side
and Confidence for every locked game, ranks the exact Top 5, and inserts an
immutable official-publication envelope only after all gates pass.

Daily refreshes start from the latest official publication, retain every prior
version and pick change, and cannot change policy versions midweek. All five
provider source types must be current or have an explicit versioned fallback.
Dry run executes the same path in an isolated in-memory clone.

Inspect an official version without writes:

```text
python -m scripts.inspect_official_card \
  --database path/to/database.db \
  --publication-key PUBLICATION_KEY
```

See `docs/WEEKLY_CONTROLLER.md` for the publication contract, fallback rules,
daily revision behavior, recovery procedure, and current operational limits.

## Historical lifecycle rehearsal

Milestone 16 replays the six-game 2024 Week 15 Saturday contest slate through
Tuesday lock, Wednesday-Friday refreshes, Saturday final publication, postgame
grading, CLV/hook/key-number classification, weekly diagnostics, Lessons
Learned, and numeric policy recommendations. The source database is opened
read-only and all writes occur in an in-memory clone.

```text
python -m scripts.run_historical_rehearsal \
  --database data/cfb.db \
  --code-commit-sha COMMIT_SHA \
  --pretty
```

See `docs/HISTORICAL_REHEARSAL.md` for the locked fixture, timestamps, expected
results, temporal isolation, failure behavior, and limitations.

## Production cutover preflight

The cutover layer includes a read-only preflight for configuration, repository identity,
migrations, SQLite integrity, foreign keys, credentials by variable name,
provider authorization, season/week, contest lines, active policies, the
EPA-only model lock, stale-data thresholds, workflow safety, write-path safety,
line-lock readiness, and idempotency.

```text
python -m scripts.production_preflight \
  --operation tuesday_lock \
  --database data/cfb.db \
  --pretty
```

The current truthful result is `PRODUCTION READY: NO`. See
`docs/PRODUCTION_CUTOVER.md` for all blockers, environment-variable names,
manual CSV/XLSX/screenshot input, provider evidence capture, database rehearsal,
workflow stages, kill-switch procedure, and recovery instructions. Code and
repository-preparation blockers are resolved; owner credentials, current-week
input, authoritative migration, and explicit cutover approval remain.

## Reproduce a prior card

Every new full-card snapshot has an immutable `card_run_manifests` record. It
freezes the code commit, model and feature-schema versions, model configuration,
selection/Confidence/ranking policy versions, data and locked-line snapshot
hashes, generation timestamp, and the hash and count of the manual-adjustment
history visible at generation. The full ordered real-book fallback policy is
stored separately in immutable `contest_selection_policies` and
`contest_selection_policy_books` rows.

Replay a card by its two immutable run keys:

```text
python -m scripts.reproduce_card \
  --database data/cfb.db \
  --card-key CARD_KEY \
  --model-run-key MODEL_RUN_KEY
```

The command opens SQLite in read-only/query-only mode, reconstructs all stored
policies, re-runs point-in-time selection and ranking, verifies every pick and
manifest field, and emits canonical JSON. Its output shows the adjustment
policy and each pick's raw projection, ordered adjustment items, totals, and
final adjusted projection. A mismatched identifier, missing manifest, changed
policy input, line-snapshot mismatch, or adjustment-history mismatch fails
visibly. Adjustments recorded after a card are excluded from its as-of history,
and a later insert cannot be backdated into a frozen history.

## Daily card refreshes

Use `business_entities.refresh_full_card()` to create the next immutable card
snapshot during the UTC Tuesday-through-Saturday operating window. The service
reuses the prior card's stored selection, Confidence, and ranking policies,
requires a strictly later pre-kickoff timestamp, and records the reason,
author, source category, and provenance for the revision.

Every locked contest game receives a `card_revision_pick_changes` row with its
prior and new side, Confidence, Top 5 status, rank, prediction, and fallback
values plus explicit change flags. A refresh is atomic: incomplete coverage,
a policy change, an undocumented line replacement, or mixed change sources
rolls back the new card and its history.

`data_refresh` may use a newer data snapshot but must retain the model name and
version, feature schema, configuration, code commit, manual-adjustment history,
and locked-line snapshot. `contextual_adjustment` must retain the exact model
run and expose new append-only adjustment history. A corrected contest line
requires both an explicit line-correction record and a `data_correction`
revision; the original locked row is never changed. A contextual refresh
applies the new ledger to the unchanged raw prediction, so side, Confidence,
rank, and Top 5 may change while the locked line and model row remain immutable.
