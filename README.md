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

Generation still creates a draft: passing `official_ready` means every contest
gate is satisfied, not that the card was automatically published. New
`official` rows are blocked until a validated publication service is added.
Contest ranking remains separate from sportsbook recommendations. The legacy
`models/card_generator.py` remains unchanged as a compatibility path and is not
used by this engine.

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

The command opens SQLite in read-only/query-only mode, reconstructs both stored
policies, re-runs point-in-time selection and ranking, verifies every pick and
manifest field, and emits canonical JSON. A mismatched identifier, missing
manifest, changed policy input, line-snapshot mismatch, or adjustment-history
mismatch fails visibly. Adjustments recorded after a card are excluded from its
as-of history, and a later insert cannot be backdated into a frozen history.
