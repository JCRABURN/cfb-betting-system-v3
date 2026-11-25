# Week 13 execution and verification

1. **Objective:** Load the owner-provided 2026 Week 13 SplashSports PDF and run the existing models. Completed for every upcoming game; elapsed games retained explicitly.
2. **Files changed:** Six Week13 scripts for capture, source reconciliation, execution, card generation, component sealing and verification/reporting; two Week13 test modules; `.gitattributes` entries preserving Week13 evidence bytes; this document; source receipts under `data/ingest/2026-week13-splashsports`; provider receipts under `outputs/2026-week13-readiness`; generated cards and verification evidence under `outputs/2026-week13-prospective`. The ignored execution database is `data/production_inputs/week13-execution.db`. No model implementation changed.
3. **Schema:** No new migrations or schema definitions. Existing migrations 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21 were applied only to a disposable source-database copy. Pre/post table counts and integrity results are saved in the ingestion and database verification manifests.
4. **Behavior:** Exact PDF lines are preserved; 69 matchups reconcile with CFBD and ESPN. Two November 24 games had elapsed before the November 25 PDF capture; those games receive no retrospective prediction. The other 67 games each have an ATS forecast, mandatory side, Confidence 1, and a totals research forecast. The governed Top 5 contains exactly five picks. Model and policy versions are unchanged. No official publication, wager, cloud mutation or schedule activation occurred.
5. **Tests:** Added 17 source tests and 11 output tests. They cover malformed/missing/duplicated source rows, sign and total mismatches, team orientation, unknown teams, kickoff conflicts, stale/future eligibility, target score contamination, elapsed-game preservation, complete outputs, immutable lines, numerical replay, confidence/fallback changes, future features and late forecasts. Existing tests are unchanged.
6. **Exact commands executed:** From the Week13 worktree using the shared local venv:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest -q tests/test_week13_source.py tests/test_contest_lines.py tests/test_backtest_harness.py tests/test_baseline_epa.py tests/test_full_card_engine.py tests/test_confidence_ranking.py
& '..\..\.venv\Scripts\python.exe' scripts/verify_repo_safety.py
& '..\..\.venv\Scripts\python.exe' -m pytest -q tests/test_weekly_controller.py tests/test_totals_shadow_top_five.py tests/test_totals_research.py tests/test_migrations.py
& '..\..\.venv\Scripts\python.exe' -m pytest -q tests/test_week13_source.py tests/test_week13_results.py
& '..\..\.venv\Scripts\python.exe' -m scripts.prepare_week13_source
& '..\..\.venv\Scripts\python.exe' -m scripts.run_week13_execution --database data/production_inputs/week13-execution.db --capture outputs/2026-week13-readiness/initial
& '..\..\.venv\Scripts\python.exe' -m scripts.finalize_week13_card --database data/production_inputs/week13-execution.db --output outputs/2026-week13-prospective
& '..\..\.venv\Scripts\python.exe' -m scripts.verify_week13_results --write-report
```

7. **Current-environment results:** 97 passed in 23.98s; safety checks passed; 62 passed in 14.38s; 28 passed in 6.36s. There are 170 distinct passing tests across these overlapping groups. An earlier invocation named nonexistent totals test files and collected no tests; the corrected command above passed. Model execution returned 67 ATS predictions and 67 totals predictions; finalization verified 134 market selections. Component sealing reran the fitted models and confirmed every saved forecast.
8. **Data quality:** 69 original/canonical matchups; 67 upcoming, 2 elapsed; no additional provider games, unresolved teams, duplicates or kickoff disagreements. Zero model/feature fallbacks; 67 Confidence values in 1-5; exactly five governed Top5 entries. All feature packages end at 2026 Week12. ATS fit uses 4,830 rows from 2019-2025. All preserved source rows were compared as multisets against the disposable DB and none changed or disappeared. SQLite integrity OK, no foreign-key violations. Protected `data/cfb.db` SHA256 remains `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.
9. **Limitations:** ATS uncertainty remains null under the existing governed policy, so every ATS Confidence is 1 and the governed Top5 is a deterministic tie-break, not differentiated reliability. Totals and within-market research ranks are unvalidated shadow outputs. Injury/QB/weather/market/context adjustments were not performed; they remain explicitly pending. No late Tuesday predictions were fabricated. Local Python is 3.12.14; repository automation targets Python 3.11.
10. **Risks:** Research scores are not calibrated probabilities or evidence of profitability. The card is a local draft; no five selections were submitted to SplashSports. The run is frozen at the recorded timestamp and does not incorporate later information.
11. **Rollback:** Stop using this local Week13 draft. Retain the immutable evidence for audit. The authoritative database needs no restore because it was never written. If the delivery changes are merged later, revert the Week13 delivery commit; do not rewrite historical lines or outputs. A refresh must use a new database/output path and new records.
12. **Scope confirmation:** No original repository, model policy, historical output, production database, secret or unrelated working file was changed. The owner's pre-existing NFL work remains untouched. The execution is pinned to commit `396b10250016344d2f2b1f115a42ee8ed97efb91` on `codex/week13-prospective`. A separate main-based delivery branch carries only Week13 files and the two exact prior-Week12 feature receipt dependencies; unmerged Week12 implementation/context changes are excluded from the PR. Review is required before merge.

The readable board is `outputs/2026-week13-prospective/week13_model_report.md`. Raw forecast components, source locks, ingestion manifests and output checksums are retained beside it. No new dependency was installed.

## Main-based delivery verification

The 170 relevant tests were rerun together in the isolated `week13-delivery` worktree and passed in 47.19s:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest -q tests/test_week13_source.py tests/test_week13_results.py tests/test_contest_lines.py tests/test_backtest_harness.py tests/test_baseline_epa.py tests/test_full_card_engine.py tests/test_confidence_ranking.py tests/test_weekly_controller.py tests/test_totals_shadow_top_five.py tests/test_totals_research.py tests/test_migrations.py
& '..\..\.venv\Scripts\python.exe' scripts/verify_repo_safety.py
& '..\..\.venv\Scripts\python.exe' -m scripts.verify_week13_results
```

Safety and result verification passed. All 40 sealed output files matched their SHA256 receipts after transfer. `git diff --name-only origin/main 2111ac4 -- models business_entities ingestion operations config migrations` was empty: the execution base uses the same model, policy, ingestion and schema implementations as current main. The original execution SHA remains available on the separate provenance branch. The complete delivery diff was reviewed; only the stated Week13 scope, byte-preservation attributes, and two prior-feature receipt dependencies are included.
