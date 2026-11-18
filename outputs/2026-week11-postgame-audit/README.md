# Integrated Week 11 forensic and season contest audit

Read [the executive report](v1/EXECUTIVE_REPORT.md) first. The complete
[season workbook](deliverables/season-performance.xlsx) contains 44 worksheets,
including the formula-driven actual submission ledger and weighted dashboard.
The [pregame-context comparison](context-v2/PREGAME_CONTEXT_COMPARISON.md)
links archived availability and matchup concerns to observed game process.
Elapsed-game refreshes are excluded from pregame evidence.
The [season report](v1/SEASON_CONTEST_REPORT.md) lists every actual v3 pick.

The owner confirmed the later PR #54 correction in this task: Weeks 1–10 are
the v3 submission population (50 picks, 150 possible points). The five Week 11
external-origin submissions are preserved separately, ungraded and excluded
from v3 comparisons. The original 128 Week 11 v3 predictions and every frozen
v3 recommendation cohort remain in the forensic audit.

## Acceptance evidence

| Requirement | Evidence and result |
|---|---|
| Reconcile complete contest archive | `v1/season_game_reconciliation.csv`: 621 distinct matchups, canonical teams, ESPN/CFBD IDs and agreeing final scores; zero unresolved identities or score conflicts. |
| Grade actual model submissions at PDF lines | `v1/actual_v3_submission_ledger.csv`: all 50 v3 picks, exact lines, scores, grading margins, W/L/P, weights, points, rational -110 units and provenance. Five external records have a separate ungraded ledger. |
| Weekly and cumulative actual performance | `actual_weekly_performance.csv`, `actual_market_performance.csv`, `actual_weight_performance.csv`: 20–30–0, 55/150, -130/11 units. Weekly progression includes every losing week and week-end drawdown. |
| Match all recovered recommendation cohorts | `season_recommendation_ledger.csv`, `season_recommendation_performance.csv`, `submission_recommendation_differences.csv`: 1,317 recommendation rows across 81 week/cohort groups. Cohorts and revisions are never summed as independent selections. |
| Resolve Week 11 divergence | Later owner attribution correction explains external model origin. No independent owner selection is inferred. No intervening v3 decision artifact was found in the inspected repository and frozen reviews; other model repositories were not inspected. |
| Week 5 correction | Actual weight-1 pick is Texas Tech -13.5; Delaware +7.5 remains the archived contextual recommendation. |
| Week 7 approval | All five submissions and exact lines match corrected owner approval. Weights are distinct from model confidence. |
| Week 4 recovery | 58 matchup finals and five submissions recovered; 3–2 and 8/15 independently confirmed. Full-card forecasts and original generation timestamps remain missing. |
| Historical locked inputs | 1,106 comparisons: 1,056 exact matches, 43 unavailable early totals, seven differing input rows. Six are original Week 7 totals; one is Week 2 Mississippi State–Minnesota spread orientation. Original and export values remain side by side. |
| Week 11 schedule displays | `week11_export_kickoff_differences.csv`: nine differences, including Ole Miss–Oklahoma Sunday. Earlier eligibility snapshots and late-seal status are unchanged. |
| Full Week 11 grading | `week11_ats_audit.csv` and `week11_totals_audit.csv`: 64 each; 36–28 ATS, 35–29 totals. Three Tuesday games have results only. Three Wednesday forecasts retain late-custody qualification; the 61 forward-sealed games are separately reported. |
| Every frozen recommendation layer | `cohort_membership.csv`, `cohort_results.csv`, `cohort_overlap.csv`: governed, ATS/totals research Top 5/10, combined five and both contextual revisions. |
| Confidence and ranking forensics | `CONFIDENCE_FORENSICS.md`, calibration and discrimination CSVs: production null uncertainty, ID-order fallback, research uncertainty, totals Gaussian probabilities, contextual confidence, zero-case buckets, intervals and sample qualifications. |
| Market baseline and segments | `forecast_vs_market.csv`, `segment_diagnostics.csv`, cumulative performance/ranking tables: MAE, RMSE, bias, tails, paired bootstraps, confidence, edge, spread, side, location, road favorites, totals direction and size. Neither market beats line-baseline aggregate accuracy. |
| CLV, hooks and backdoors | `clv_audit.json`, `clv_observations.csv`, `hook_backdoor_audit.csv`: no timestamp-qualified closing quotes; CLV is explicitly unavailable. Backdoor classifications require validated scoring sequences. |
| Game-level logic failures | `GAME_LEVEL_LOGIC_FAILURES.md`, process/passers/scoring/priority tables: every Top 5 game, major miss, large-edge loss and high-confidence totals loss. Observed process is separated from unsupported injury/weather/causal claims. |
| Frozen prospective research | Five methods × two markets × 61 games = 610 retained predictions; exact combined cohorts, within-market frozen-probability rankings, Brier/log loss/reliability, all results, and 28 forecasts from 14 drive-prototype games. No candidate promoted. |
| Drive anomalies | All 147 original anomalies retained; 116 derived corrections corroborated by scoring-play IDs, 31 still quarantined. Original prototype and pregame evidence unchanged. |
| v2.9 development | Expanding prior-week residual-ridge experiments, prior-fold probability calibration, failed folds and all candidate predictions retained. Nine additional feature families have explicit missing-evidence/validation requirements. Week 11 is development data for this new experiment. |
| Lessons and proposed policy | `LESSONS_LEARNED.md`, `PROPOSED_MASTER_PROMPT_V2_9.md`, `v29_research_protocol.json`: numeric proposals, rejection/promotion criteria, risks and required future validation. v2.8 remains active. |
| PDF provenance | PR #54 manifest pins extraction CSVs and ZIP/PDF hashes/page references. November 16 printing does not prove pregame forecasts. Original PDF/ZIP binaries were unavailable locally; no fresh visual re-extraction is claimed. |
| Source custody | `custody_verification.json`: 870 original PR #53 members, 2,729 historical input files, eight original screenshots and unchanged database verified. `audit_manifest.json` pins inputs, source code and all 56 generated member outputs. |

## Reproduction and dependencies

All grading and research replay is offline against archived responses:

```text
python -m scripts.build_week11_formal_audit --verify
python -m scripts.verify_week11_workbook
python -m scripts.week11_context_postgame --verify
python -m pytest -q tests/test_week11_forensic_audit.py tests/test_season_contest_audit.py
```

The builder refuses to overwrite an existing version. To generate a new audit,
use `--output outputs/2026-week11-postgame-audit/v2` and preserve v1. No original
prediction code is executed to recreate forecasts. Provider capture scripts
are separate, explicitly invoked network operations; replay never calls them.

Workbook authoring uses the installed Codex bundled `@oai/artifact-tool` runtime
(its existing bundled license/distribution), with no new repository or CI
dependency. It is an authoring-time dependency only; the read-only OOXML verifier
uses Python's standard library. Resolve the bundled package through
`.local-week11-workbook/node_modules` before running:

```text
python -m scripts.prepare_week11_workbook --folder outputs/2026-week11-postgame-audit/v1 --target .local-week11-workbook/input.json
node scripts/build_week11_workbook.mjs .local-week11-workbook/input.json outputs/2026-week11-postgame-audit/deliverables/season-performance.xlsx .local-week11-workbook/previews
```

The workbook's calculated grade columns and headline totals are checked against
the independent Python ledger. Authoring also changes one score, recalculates
the linked dashboard, verifies the changed win count, restores the score and
recalculates again. Every sheet is rendered for visual review. This does not
claim a native Microsoft Excel open test or byte-identical workbook packaging.

## Boundaries and rollback

There are no schema migrations, production database writes, production model
changes, active policy changes, scheduled workflows, wagers or original-repo
modifications. Only the PR-test workflow gains offline verification steps.

The large temporary PR #53 source archive is not duplicated in this PR because
its 870 exact members already exist on merged main. Its original capture
inventory and archive hash are preserved; every member is verified directly.

This is an additive audit. Roll back by reverting its feature commit(s), after
preserving any desired audit deliverables. No database rollback or historical
forecast restoration is necessary. Independent review and an explicit merge
decision remain required; Codex must not self-merge.
