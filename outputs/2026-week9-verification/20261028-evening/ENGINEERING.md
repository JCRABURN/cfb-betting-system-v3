# Week 9 evening validation — October 28, 2026

## Objective and result

Refresh the ten owner-review candidates while preserving the sealed 54 ATS and 54 totals card, v2.8, screenshot lines, original forecasts, confidence, timestamps and mixed research Top 5. Owner approval remains PENDING. This is Wednesday evidence; Saturday availability has not yet occurred.

The separate evening recommendation is Northwestern +3.5 (human confidence 2), Navy +30.5 (2), Southern Miss–ULM Under 56.5 (2), Troy +20.5 (1), and FAU–North Texas Under 77.5 (1). Troy replaces San José State; Northwestern's human confidence falls from 3 to 2. The morning revision and every original model value remain intact. No numerical forecast adjustment or market-diversification quota was applied.

## Scope, files, and behavior

Only new files in these paths are included in this delivery:

- `outputs/2026-week9-context/20261028T2237Z/`: raw source responses, request/receipt timestamps and hashes, derived context and 108 separate market observations for 54 games.
- `outputs/2026-week9-context/20261028T224038Z-supplement/`: five additional official-source attempts, four HTTP 200 responses and an explicitly preserved Navy HTTP 404.
- `outputs/2026-week9-owner-review/20261028-evening/`: all ten candidates, reasons, prior ranks, human confidence changes, immutable raw forecasts, Oregon input sensitivity and custody hashes.
- `outputs/2026-week9-verification/20261028-evening-full-suite.txt` and `outputs/2026-week9-verification/20261028-evening/`: executed test output, exact integration results, GitHub status snapshot and this report.

No code, tests, dependencies, schema, source database, model, policy, historical result, original evidence or production workflow changes. No tests were added or modified for this additive evidence refresh. The full staged path inventory is saved alongside this report. No unrelated files are included.

## Exact integration and preservation

Tested delivery head: `e3a9a10ed63c0aa003d16e88208331d1ff81e170`, in the actual `codex/week9-prospective-execution` worktree. Its ancestors were checked explicitly:

- Main: `abb4eb26bd1140e66972d2f1143cd587e80960b4`.
- Repaired aggregate #41: `78ed6eb5540f66ba3193f91366c802e27e3cb9c7`.
- Sealed Week 8 #42: `7f42da36f9aef4666bb715d49babde7ee374defa`.
- Week 9 source #43: `43807ae374b9db143c1d9675d7a7cafe6e2f28ba`.
- Week 8 audit #44: `922f1f8f8c66ef14674eb9aa20db144a45dada68`.

Exact Git-byte comparisons passed for 66 Week 8 audit/research files and 44 Week 9 prospective files. Week 7 checks passed 419 custody assertions and 10 deterministic research replays. Week 8 seal and audit gates passed for 52 ATS plus 52 totals; Week 9 seal passed for 54 plus 54, with two elapsed Tuesday games excluded. Original Week 9 mixed research ordering remains separately frozen and uncalibrated.

Week 9 seal SHA256: `77aea6d0eefecc6dce014524610294da617d7dab2b6e903a59f8664f664e5460`.

Original source database SHA256: `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.

Read-only refitting of the disposable execution database reproduced every numerical/model component exactly, without tolerance. Only the new component-capture runtime timestamp differs: original `2026-10-28T03:07:48.001022+00:00`, replay `2026-10-28T22:42:31.631890+00:00`. Neither original timestamps nor model outputs were overwritten. Disposable database hash remained unchanged; integrity and foreign-key checks passed.

## Commands executed in this environment

Python executable: `C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.venv/Scripts/python.exe`. Working directory: `C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.worktrees/week9-execution`.

```text
python -m scripts.capture_week9_context --output outputs/2026-week9-context/20261028T2237Z
python -m scripts.review_week9_context --capture outputs/2026-week9-context/20261028T2237Z
python -m pytest -q
python -m scripts.verify_week7_audit_integrity
python -m scripts.seal_week8_board --verify
python -m scripts.build_week8_postgame_audit --verify
python -m scripts.week8_scoring_sequence_review --verify
python -m scripts.week8_numerical_research --verify
python -m scripts.seal_week9_board --verify
python -m scripts.review_week9_context --capture outputs/2026-week9-context/20261028T2237Z --verify
python -m scripts.verify_week9_owner_review outputs/2026-week9-owner-review/20261028-evening/owner_review_shortlist.json
```

Full suite: **809 passed, 39 existing deprecation warnings, 203.82 seconds, exit 0**. All eight read-only gates passed. No unexplained test failures. Exact outputs for seven gates are in `integration-gates.json`; the owner-review gate separately returned 10 candidates, 5 recommendations, approval PENDING and frozen values unchanged.

## Evidence quality and material changes

The new capture contains 168 successful nonweather records and 54 weather records. All ten shortlist games were pregame at the saved review timestamp, `2026-10-28T22:44:03.241438+00:00`. Thursday Troy/JMU and FAU/UNT begin October 29 at 23:30 UTC. Later reviews must retain already-started candidate rows exactly; the original board includes games starting October 28 at 23:00 UTC.

Oregon's frozen Week 8 offense EPA includes three full games without Dante Moore. Its decline from Week 4 translates algebraically to 6.973 points already deducted from Oregon's margin, holding other inputs fixed; defensive improvement offsets 2.092 points. The net Oregon-input sensitivity is 4.881 points. This is not a causal QB valuation: Week 4 includes Moore's exit, and opponents, other personnel, sampling and provider revisions confound attribution. No further injury-point adjustment was invented. The post-Week-8 coordinator change is not represented in those inputs, and its direction is unknown.

SJSU's official prior-game recap documents three QBs used, 204 yards, 1/14 third downs and eleven punts. Its starter/backup and OL health remain unresolved. The secondary report of a QB injury is not elevated to official confirmation. Troy's October 28 official preview states JMU leading rusher George Pettaway will miss the game; Troy QB Crowder's own recurring injury and JMU's strong home offense keep human confidence at 1. FAU/UNT remains 1 because strong offenses and return scoring challenge the Under despite the large frozen gap.

Market observations were received at `2026-10-28T22:37:44.343863+00:00`, before all included kickoffs, with raw-response identity retained. Provider quote timestamps and guaranteed freshness are unavailable; ATS/total offered juice is not supplied. These are timestamp-qualified observations, not qualified closing lines or validated CLV. Locked lines are unchanged. Historical CLV stays **INCOMPLETE**.

One supplemental Navy archive request returned 404; it is preserved as unavailable. A 2025 availability page was excluded as stale rather than treated as 2026 evidence. Final QB/backup, offensive-line and defensive availability is not complete for every candidate. Weather is a forecast and no point adjustments were inferred from rain probability. These are ordinal, uncalibrated human judgments, not validated winning probabilities or wager instructions.

## CI, review and merge recommendation

GitHub snapshot at 22:45:32 UTC: #44 and #45 each had zero check runs, zero commit statuses and zero PR-triggered workflow runs. Each had one owner-authored **COMMENTED** review, not APPROVED. Missing checks are not a passing CI result; local tests do not substitute for independent review.

Keep both PRs draft pending independent review and resolution of the missing CI verification. Preserve the repaired #41 ancestry, then #42 and #43; integrate #44 before the dependent #45. Do not merge defective earlier ancestors individually. There is no local integrity failure in the tested aggregate tree, and irrecoverable historical CLV alone is not a reason to block unrelated integrity/evidence code. No merge or owner selection approval is declared.

## Risks and rollback

Personnel uncertainty, small samples, uncalibrated ranking scales and large forecast misses remain selection risks. Wednesday evidence cannot certify Saturday health. The existing morning automation continues through October 31, preserves each revision separately and stops after its final refresh.

Rollback: leave the evidence commit unmerged, or supersede the human review with a new timestamped version retaining this record. Do not delete custody history or rewrite the sealed card. No database migration or source-data restoration is needed. The original repository, unrelated NFL work and production workflows remain untouched.
