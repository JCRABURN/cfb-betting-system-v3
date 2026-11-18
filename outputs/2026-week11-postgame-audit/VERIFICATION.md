# Integrated audit verification and completion record

1. **Objective:** complete the Week 11 forensic audit and recovered season contest audit together, respecting the later owner attribution correction. The v3 actual population is Weeks 1-10; Week 11 external submissions stay separate and ungraded.
2. **Files changed:** additive `scripts/week11_*`, season reconciliation/capture/report modules, the formal audit and workbook builders/verifier; four new test files; raw postgame captures; 57 immutable audit members, context supplement, workbook and verification receipts. `.gitattributes` preserves new evidence bytes. `.github/workflows/ci.yml` adds offline audit, context and workbook verification. See the PR file inventory for every path.
3. **Schema changes:** none. No data migrations or production database writes. Existing migration verifiers ran against disposable copies.
4. **Behavior:** adds offline grading/research reports and source reconciliation. Corrects the reporting population and actual-vs-recommendation attribution. No model, active policy, original line, historical prediction, or original recommendation is changed.
5. **Tests added:** adversarial source/line/weight/selection corruption, provider identity/orientation/finality/score conflicts, timestamp custody, canonical unknown teams, exact grading/pushes, null uncertainty, frozen research membership, probability boundaries, training/calibration leakage, immutable output boundaries, late context exclusion, and workbook cache/row/formula corruption. No existing test was modified or weakened.
6. **Exact commands:** listed below and in `verification-v1/results.json`. The local executable was `../../.venv/Scripts/python.exe`; no live API is used by replay or validation.
7. **Executed results:** complete local suite 1,196 passed with 39 pre-existing deprecation warnings. Then all 55 audit/context tests passed; after adding workbook corruption tests, all five context/workbook tests passed. These runs overlap; they are not summed as independent tests. All 14 local safety, migration and exact replay commands passed. Final PR CI is reported on the PR for its exact head and tested merge commit; local results alone are not a claim of remote CI success.
8. **Data-quality checks:** all 621 matchups reconciled; 50 actual v3 grades and five excluded records; no score conflicts, duplicate contest games or unresolved teams; exact weekly weight allocation; Week 4/5/7 corrections; seven preserved historical line differences and nine preserved kickoff display differences. All 128 Week 11 predictions graded. 870 PR53 members, 2,729 historical inputs and eight screenshots verified. Source database SHA-256 remains `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`; integrity ok, zero foreign-key violations.
9. **Known limitations:** original PDF/ZIP binaries unavailable locally; November 16 exports do not prove original forecast timestamps. Week 4 full-card forecasts and Week 1 full totals forecasts remain missing. Three Wednesday forecasts have late custody. No timestamp-qualified closing lines. Personnel snap shares, measured weather, rivalry/ranking classifications and causal adjustments are not fully recoverable. Thirty-one drive anomalies remain quarantined. Nine proposed feature families lack sufficient comparable point-in-time evidence; no claim that these architectures were empirically validated. The workbook was recalculated/rendered with the bundled authoring engine and inspected as OOXML, not opened in native Excel.
10. **Risks:** small selected samples, overlapping methods/revisions, repeated teams, descriptive intervals, multiple testing and post-outcome research specification preclude claims of profitability or a validated replacement. Provider agreement is corroboration, not proof of independent upstream sources. Changes to source evidence fail exact replay rather than silently updating this audit.
11. **Rollback:** revert the additive feature commit(s) after retaining desired reports. No database recovery or original-forecast regeneration is needed. v2.8 remains active and no production model is promoted.
12. **Scope confirmation:** the full staged file inventory and source diff were reviewed; generated outputs were independently replayed and workbook formulas checked. No unrelated files, original-repository files, source database, locked lines or frozen recommendation artifacts changed. Temporary archives, previews, the failed unpublished context-v1 build and workbook inspection dump are excluded from the PR. Codex will not merge it.

## Local commands and results

Every command below completed with exit code 0:

```text
python -m pytest -q
python scripts/verify_repo_safety.py
python -m scripts.verify_migrations
python -m scripts.verify_cloud_migrations
python -m scripts.verify_replay_compat --output .local-week11-audit-preview/verification/compatibility.json
python -m scripts.build_week9_formal_audit --verify
python -m scripts.week9_scoring_process_v2 --verify
python -m scripts.verify_week10_acceptance
python -m scripts.build_week10_formal_audit --verify
python -m scripts.prepare_week11_readiness --verify
python -m research.week11_validation.anchor_diagnostics_v2 --verify
python -m scripts.verify_week11_transcription
python -m scripts.verify_week11_acceptance
python -m scripts.build_week11_formal_audit --verify
python -m pytest -q tests/test_week11_forensic_audit.py tests/test_season_contest_audit.py tests/test_week11_context_postgame.py
python -m pytest -q tests/test_week11_context_postgame.py tests/test_week11_workbook.py
python -m scripts.week11_context_postgame --verify
python -m scripts.verify_week11_workbook
git diff --cached --check
```

The workbook authoring command, after preparing its source interchange, was:

```text
node --max-old-space-size=8192 scripts/build_week11_workbook.mjs .local-week11-workbook/input.json outputs/2026-week11-postgame-audit/deliverables/season-performance.xlsx .local-week11-workbook/final-previews
```

Workbook results: 44 worksheets; 50 independently matched calculated grades;
all 621 exact provider IDs; zero formula-error cells; changed-score recalculation
probe passed and inputs restored. Every sheet preview was visually inspected.
The export and authoring source hashes are in `deliverables/workbook-verification.json`.

## Review decision

The audit is suitable for independent review after successful exact-head PR CI.
It does not establish that v3 beats the market, that its Top 5 ranking adds value,
or that any proposed replacement is ready for production. ChatGPT/owner review
and merge authorization remain separate from technical verification.
