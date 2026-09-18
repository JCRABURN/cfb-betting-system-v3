# 2026 Week 3 execution and verification

## Objective and operating boundary

Execute the owner-supplied 57-game SplashSports slate using existing custody,
EPA, component-totals, and reliability services. Preserve the original database
and report every unavailable product explicitly. This branch inherits the
unmerged PR #26 totals foundation and local Week 2 extensions at `0515346`.
Those dependencies are not a production approval. Do not merge the inherited
tracked database snapshot or promote totals as part of this execution review.

PR #26 was inspected through GitHub on September 18, 2026. It remains an open
draft at `ad551c788bc85670cd6e3848730dea403277b1a6`; its owner review requested
governed ATS probability custody, subsequently added at that head. No approval
promoting totals or the early-season shrinkage research was found.

The base checkout has ATS services but not totals. This isolated execution
branch has `epa-only-linear-v1`, the governed OOS uncertainty artifact,
`pit-epa-component-total-linear-v1`, and the shadow unified-ranking service.
Original source schema is migration 22; existing migration 23 is applied only
to disposable/execution copies. There is no new schema migration in this change.

## Files and behavior changed

- `business_entities/weekly_controller.py`: explicitly omit games at or after
  kickoff before reading their features or writing an EPA prediction.
- `business_entities/totals_weekly_model.py`: the same cutoff and explicit skip
  provenance. Model coefficients, feature rules, thresholds, and policy
  versions are unchanged.
- `scripts/run_week3_execution.py`: offline replay of captured provider data,
  strict screenshot-order reconciliation, immutable locks, existing-model
  execution, Week 2 grading, and report generation in a new development copy.
- `tests/test_week3_execution.py`: 10 reconciliation, boundary, and result-
  custody tests. No existing test was changed or weakened.
- This document and `outputs/2026-week3-execution-20260918/`: execution evidence.

The runner adds two CFBD-confirmed 2026 FBS identities when missing, preserves
provider IDs and raw names, and resolves home/away from the official schedule.
The owner CSV itself is never edited. Capture time is a source claim distinct
from the actual September 18 ingestion lock; no timestamp is backdated.

Week 2 final scores bind to unique season/week/home/away/date matchups without
replacing its synthetic canonical IDs or original kickoff times. Hawai'i versus
New Mexico State has a one-minute source kickoff difference, retained in the
mapping ledger. Only its final-score columns are updated in the copy.

## Executed verification

Working directory for every command below is this isolated Week 3 worktree.
The exact executable is
`C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe`
(Python 3.12.14; repository automation specifies 3.11).

```powershell
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m pytest tests/test_week3_execution.py -q
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m pytest tests/test_contest_lines.py tests/test_weekly_controller.py tests/test_epa_uncertainty.py tests/test_totals_research.py tests/test_totals_shadow_top_five.py tests/test_complete_postgame_audits.py tests/test_provider_ingestion.py tests/test_confidence_ranking.py tests/test_full_card_engine.py tests/test_reproducibility.py tests/test_week3_execution.py -q
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m scripts.verify_migrations
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' scripts/verify_repo_safety.py
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m scripts.verify_cloud_migrations
git diff --check
```

Current-environment results: targeted suite **123 passed in 50.16 seconds**;
the 10 new tests also passed independently (0.83 seconds initially, 5.84 seconds
after report refinements). Migration verification passed through version 23,
existing row counts were preserved, integrity was `ok`, and foreign-key
violations were zero. Repository/workflow safety, cloud migration inventory,
and diff whitespace checks passed. The complete repository suite was not run.

The first disposable rehearsal exposed a transaction-boundary error before
the provider import; no authoritative database was affected. After correcting
that boundary, the second rehearsal completed: 57 locks, 56 ATS forecasts,
56 totals forecasts, and one explicit elapsed-kickoff skip. A final run is
recorded separately in the output manifest with its actual timestamp and SHA.

## Data-quality acceptance

- Exact inventory: Thursday 1, Friday 2, Saturday 54; all 57 source rows match
  official FBS pairings and kickoff timestamps. The other 18 provider schedule
  rows are FBS-versus-non-FBS and are explicitly excluded, not CSV omissions.
- No duplicate games, missing spreads/totals, non-opposing spread pairs, or
  unresolved canonical identities remain after the two provider-backed adds.
- Every locked source value is preserved; immutable lock IDs and source SHA,
  raw/canonical names, actual lock timestamp, and display timezone are saved.
- EPA capture stops at endWeek 2. Forecasts use the existing PIT accessor,
  remain before their own kickoff, and exclude Thursday's elapsed game.
- All 56 future games have model-backed sides and Confidence 1. The frozen
  reliability policy assigns its floor because uncertainties exceed 8 points;
  it does not establish useful calibrated differentiation here. No edge-based
  confidence override is applied.
- Weather and travel/rest observations are custodied without numeric manual
  adjustments. Missing injuries, coaching, motivation, and odds remain explicit.
- Pre/post row counts, existing-record preservation, source/backup hashes,
  SQLite integrity, and foreign-key checks are recorded in the execution report.

## Findings and limitations

Syracuse at Pittsburgh had already finished when the CSV became available.
The full-card and totals-card services correctly refuse to seal a newly
generated complete-week card. The unified service requires both valid cards;
there is no official ATS Top 5 or combined Top 5. A clearly provisional
remaining-game ATS ranking uses the unchanged existing ranking function.

Week 2 now has all 49 ATS results and 49 shadow totals results graded in the
execution copy. Both are **24 wins, 25 losses, 0 pushes**; the saved ATS Top 5
is **2 wins, 3 losses**. Missing closing-line custody prevents a completed ATS
diagnostic seal and CLV calculation. Backdoor and causal failures remain
unevaluated without scoring-sequence/context evidence. These one-week results
do not authorize a model or policy change.

Week 1 audit evidence was found in the separate `week1-postgame-audit` worktree:
43 picks, 18 wins, 25 losses; original capture times for archived closes are
missing, so its governed audit import remains blocked. That historical worktree
and its audit were only read, not rewritten or duplicated.

The current ESPN response has team names at group level while the existing
parser requires a nested team object. Raw response is retained; normalization
fails visibly. The Odds API connection failed before an HTTP response. Master
Prompt v2.8, original screenshots, and native SplashSports contest ID were not
supplied. Source contest ID uses the repository's weekly key. The original CSV
can be validated against schedule and internal arithmetic, but not independently
against screenshot pixels.

The managed authoritative stream cannot be imported because
`CFB_V3_DATABASE_URL` is unavailable. This task retains durable locks and
results in an isolated development SQLite snapshot; it does not represent them
as cloud-authoritative or published. No schedules, production flags, secrets,
model promotions, wagers, or competing dashboard were changed.

## Risks, rollback, and scope

Provisional forecasts may be mistaken for official selections unless their
status is retained. Raw totals probabilities are not empirically calibrated;
existing extrapolation/extreme-disagreement quarantine diagnostics apply.
Early-season opponent support remains an acknowledged model limitation.

Rollback consists of reverting this task's code/report commits and retaining
or archiving its isolated execution directory. The source database is untouched
and its byte-identical backup is kept next to the execution database. Never
delete historical locks or audit rows in place. If this snapshot is later
imported by a separately authorized controlled promotion, use the existing
complete-snapshot recovery procedure.

No unrelated files were changed by this task. The dirty NFL-development root
checkout, separate Week 1 audit checkout, original repository, and both source
`data/cfb.db` files were preserved.
