# Week 8 continuity — prospective board and verification

Objective: continue PR39's screenshot ingestion using unchanged v2.8 and existing ATS/totals research policies, preserve original custody, and generate every eligible upcoming selection. The complete board is [WEEK8_BOARD.md](../outputs/2026-week8-prospective-v2/WEEK8_BOARD.md).

## Readiness and source custody

The 56 unique screenshot matchups reconcile to all 56 captured Week 8 FBS-vs-FBS games with **zero spread/total discrepancies**. Six original PNGs were recovered from owner task `Review PR 38 Audit`, task ID `6ad7c843-3a48-83ea-9bb3-00a537ae40d7`, message `3699ad41-9c52-48ab-920e-0ad00ae7ad02`. They are preserved under `outputs/2026-week8-prospective/source-evidence/`. The independently read 57 image observations include one consistent Ole Miss–Texas overlap. Each prospective source row identifies its original image and image row, and the PR39 CSV row.

The screenshot receipt timestamp is recorded from that message. Original screenshot capture/posting time is unknown; no authoritative Tuesday freeze is asserted. All displayed upcoming times reconcile with the captured UTC schedule using Chicago CDT; the image itself does not print its timezone.

PR39 head is `3148e4fe7cd7ab9387048386903db68ad7c2de4b`; original CSV SHA-256 remains `174b0e645afe45f7c4d5f569b88f856a38c4b6707106b0298279c9bee58b72f6`. Its 56 rows, lines, statuses and final scores are unchanged. No market-line endpoint was called, and no line was replaced.

The October 21 preparation had 53 upcoming games but did not execute predictions. That preparation and capture remain preserved. On October 22, New Mexico State–Sam Houston had elapsed, so a new `v2` source/output version excludes it alongside the three Tuesday finals. The four exclusions are game IDs `401871055`, `401871069`, `401871092`, `401871070`. No prediction was backdated for them. There are **52 eligible games, 52 ATS selections and 52 totals selections**, with zero missing forecasts, totals or unexplained schedule omissions.

Models ran at **2026-10-22 21:37:32 UTC**, card generation at **21:37:49 UTC**, and the board was sealed at **21:40:38 UTC**, before the first eligible kickoff at **23:00 UTC**. Generated-at fields are authoritative; the inherited `week8-20261021:*` run-key suffix is a preparation identifier, not a generation timestamp. The finalizer's inherited console heading says `WEEK 7 MARKET COVERAGE`; all Week 8 identities, data, files, counts and timestamps are verified independently. That cosmetic log label is retained with the executed, hash-sealed source.

Readiness: **complete prospective model/research board**. It is not an owner-approved final contest five or sportsbook recommendation. Injury, quarterback and weather review remains pending, with no invented neutral values or numeric adjustments. Historical CLV remains INCOMPLETE; current Week 8 closing-line evidence has not been captured.

## Ranking and unchanged policy

The existing combined research ordering gives:

| Rank | Matchup | Research selection | Projection | Existing research Confidence |
|---:|---|---|---:|---:|
| 1 | Miami (OH) at Central Michigan | Over 40.5 | 51.45 | 4/5 |
| 2 | San Diego State at Colorado State | Under 64.5 | 54.70 | 4/5 |
| 3 | Utah State at Texas State | Under 60.5 | 51.08 | 4/5 |
| 4 | Colorado at Oklahoma State | Under 55.5 | 46.69 | 4/5 |
| 5 | Baylor at Kansas | Under 53.5 | 45.51 | 3/5 |

These scores are **uncalibrated research measures**, not validated probabilities. The all-totals list illustrates the existing score-scale mismatch; no market-balancing or new selection rule was introduced. Separate governed ATS Top 5, ATS research Top 5/Top 10, totals research Top 5/Top 10 and human-review shortlist are preserved. All 52 governed ATS selections retain Confidence 1 because the existing policy has null governed uncertainty. Totals Confidence distribution is 24 at 1, 10 at 2, 14 at 3 and 4 at 4; all values satisfy the required 1–5 range. No artificial Confidence 5 was assigned.

ATS remains `epa-only-linear-v1`, trained on 4,830 rows from 2019–2025. Totals remains `pit-epa-component-total-linear-v1`, trained on 5,003 prior-fold observations. Features are limited to Week 7 or earlier. All current-week targets have null outcomes in the derived ingestion payload. Existing selection, ranking, adjustment, calibration-transform and totals-reliability configurations are unchanged; no policy has been promoted.

## Exact commits and integration

- Audit repair PR41: `78ed6eb5540f66ba3193f91366c802e27e3cb9c7`. Its actual integration tree passed 724 tests. Full dependency references and repair scope are in [AUDIT_INTEGRITY_REPAIR_VERIFICATION.md](AUDIT_INTEGRITY_REPAIR_VERIFICATION.md).
- Week 8 screenshot/capture commit: `abcbe47da98c00f3e0bb943317ba40d694ed5f4b`.
- Week 8 orchestration/source preparation: `7994259c5bb421ccc8c4626ada06f03d20bc2caa`.
- Executed model/card code: **`ecc2d2100eba99e24a1d94106b43a62912487eea`**.
- Sealing verifier commit: `e5d97f045eefbd1ece9ebe6df9f3c706d1c53f1f`.
- Final delivery commit records the sealed outputs, regression tests and this report; model-run identity continues to point to the executed commit above.

Main remains `abb4eb26bd1140e66972d2f1143cd587e80960b4`. PR38, PR39, PR40 and PR41 heads were rechecked on October 22 and remained unchanged/open/draft. Week 8 is a separate branch containing PR41's repaired integration ancestry. Recommend review/integration of the repaired dependency tree first, then this prospective evidence; do not accept unrepaired intermediate heads. No PR was merged.

## Changed files and behavior

- `.gitattributes`: preserve original/new Week 8 evidence bytes. `.gitignore`: exclude only the two local disposable execution DBs and their sidecars.
- `ingestion/custody.py`: one canonical SplashSports alias, `Connecticut → UConn`, needed for PR39's preserved spelling. It is tested at the resolver boundary; no downstream one-off mapping or source rewrite.
- `data/ingest/2026-week8-independent-screenshot-review.csv`: independently read image values and times, preserving overlap.
- `production-weeks/2026-week8-splashsports*.csv` and corresponding metadata: append-only initial preparation and v2 eligible subset, with original source hashes and elapsed exclusions.
- `scripts/capture_week8_core.py`, `prepare_week8_source.py`, `run_week8_execution.py`, `finalize_week8_card.py`, `seal_week8_components.py`, `seal_week8_board.py`: versioned weekly orchestration, explicit eligibility gates, unchanged shared model/policy calls, per-game component custody, independent numerical/ranking replay and append-only sealing.
- `outputs/2026-week8-prospective/`: six originals, custody, initial schedule/stats capture and reconciliation. `outputs/2026-week8-prospective-v2/`: refreshed capture, 11 replayable derived payloads, complete boards, manifests, component evidence, readable board and seal. The seal enumerates every one of its 34 output hashes, 11 source hashes and 104 canonical code/config hashes.
- `tests/test_week8_continuity.py`, `tests/test_week8_sealed_board.py`: 26 cases covering normal replay, screenshot/line/orientation conflicts, overlap, missing/duplicate games, alias scope, elapsed games, outcome contamination, future features, altered projections/confidence/rank, source preservation, late sealing and overwrite prevention.
- This verification report. The exact delivery inventory is available with `git diff --name-only 78ed6eb5540f66ba3193f91366c802e27e3cb9c7 HEAD`.

Schema changes: **none**. No new dependencies. Existing migrations 1–21 ran only on a disposable copy, with before/after row counts in `week8_ingestion_manifest.json`. The original `data/cfb.db` was not modified. Disposable ingestion accepted 941 records across 11 runs, rejected zero, and passed integrity/FK checks. Games increased 5,051→5,440 and team stats 14,721→15,273 in that copy only; 52 locked rows and each set of 52 predictions were created. Subsequent card entities exist only in the disposable copy and frozen exports.

## Commands, verification and failures

Working directory: `C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.worktrees/week8-continuity`.

```powershell
$py = 'C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.venv/Scripts/python.exe'
& $py -m scripts.capture_week8_core --output-directory outputs/2026-week8-prospective-v2/core-initial
& $py -m scripts.prepare_week8_source --version v2
& $py -m scripts.run_week8_execution --source-lines production-weeks/2026-week8-splashsports-v2.csv --source-metadata production-weeks/2026-week8-splashsports-v2-lock-metadata.json --capture-dir outputs/2026-week8-prospective-v2/core-initial --database data/week8-prospective-v2-retry1-disposable.db --output outputs/2026-week8-prospective-v2
& $py -m scripts.finalize_week8_card --database data/week8-prospective-v2-retry1-disposable.db --output outputs/2026-week8-prospective-v2 --source-lines production-weeks/2026-week8-splashsports-v2.csv
& $py -m scripts.seal_week8_board
& $py -m scripts.seal_week8_board --verify
& $py -m pytest -q tests/test_week8_continuity.py tests/test_provider_ingestion.py
& $py -m pytest -q -p no:cacheprovider tests/test_week8_continuity.py tests/test_week8_sealed_board.py
& $py -m pytest -q -p no:cacheprovider
git diff --check
```

Generation/capture commands are historical reproduction references and must not be rerun to replace existing paths. Use the read-only verification command for the frozen board; later refreshes require new output/source versions and current kickoff checks.

Targeted results: 34 passed in 7.68 s for source/provider tests; 26 passed in 1.92 s for sealed-board/source tests. The initial targeted run produced a pytest cache-directory permission warning; `-p no:cacheprovider` disables only cache writes, not tests, and was used for the final checks.

Full suite on the actual combined integration worktree: **750 passed, 39 warnings in 171.41 seconds**, zero failed or skipped cases. The 39 warnings are the existing `datetime.utcnow()` deprecations described in the audit repair report. All source/output/code hashes and the independent board replay pass. No historical picks, lines, scores, manifests or expected hashes were changed; the existing audit integrity tests enforce those properties on this combined tree, including 419 exact custody checks and 610 protected historical Git blobs. Shared `models`, `business_entities`, `config`, `migrations`, `operations` and `contest_lines` have zero changes relative to PR41. Final changes after the full suite are documentation, ignore rules and CRLF diff-display attributes only. The complete functional diff and generated board were reviewed.

The unstaged whitespace check passed, but staging the frozen generated CSV/JSON files exposed CRLF terminators as trailing-whitespace warnings under `-text`. The output directories now explicitly declare `whitespace=cr-at-eol`, matching the historical Week 7 convention. No artifact bytes or hashes were changed. The complete Week 8 diff check and read-only seal verification were rerun after that attribute correction.

Resolved development failures: initial identity reconciliation correctly stopped for Sacramento State missing from the old DB's team list; using the captured FBS identity inventory resolved it. Connecticut then required the canonical resolver alias described above. The first execution failed before derived ingestion/model execution because its provider-evidence directory did not exist. The failed disposable DB is preserved, SHA-256 `1b4bb83a9992920cc322fc6e4d8ca94c168e5d18d26141486a6191b4bc2f00af`. The runner now creates an empty isolated directory and refuses to replace partial evidence. Retry used a new disposable DB and succeeded; no failed model selection was rewritten.

| Protected identity | SHA-256 |
|---|---|
| Original source DB | `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842` |
| Successful disposable execution DB | `53c8a01c594461c6c12e17861a5199c939ff1e8390b38746217c87d24df4be40` |
| Week 8 v2 source CSV | `c2c7d17f72fbbfb82960478dab3763cb1f929e5e20f8a44aad8208de8e7fc5d4` |
| Locked-card identity | `fb061eafe18584cd54661b7b3740e8d7914645af3808fea6508622f136c153b5` |
| Week 8 seal | `355e72a9a07ef3fc48891519655ab52ccd5c4283add5cd5a39f29788cf1beba2` |

Both disposable databases and the source DB independently return `integrity_check=ok` with zero FK violations. Disposable DBs remain local and are not committed.

## Limitations, risks and rollback

The sample does not validate winning probabilities or profitability. All-Confidence-1 ATS and the combined score-scale defect remain visible under unchanged policies. Missing contextual review and missing qualified historical closes are explicit limitations; CLV remains INCOMPLETE. No live wager, production deployment, dashboard publication, scheduled workflow or final owner selection was made. The provider request is timestamped and parameterized through Week 7; this does not independently certify the provider's entire historical revision history.

Rollback uses a new reviewed revert of Week 8-only commits, retaining the frozen evidence for audit and leaving PR41's integrity repair intact. Do not delete or rewrite historical artifacts to roll back publication status. No source DB restoration, schema rollback or model-policy rollback is needed. No unrelated files changed; existing NFL work in the root worktree remains untouched.
