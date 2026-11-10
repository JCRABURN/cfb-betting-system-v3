# Week 11 preparation research — RESEARCH ONLY

These methods were specified after Week 10. Historical folds are chronological
retrospective exploration, not a claim of prospective validation. They do not
change v2.8, PR #50's sealed experiment, any historical forecast or any official
selection. No Week 11 predictions or outcomes are used here.

## Frozen comparison specification

Evaluate Weeks 6–10, fitting on Weeks 5 through evaluation-week-minus-one only.
Report every method and every week; do not select a winner using Week 11 results.
The original lines, forecasts, grades and research ranks come from the audited
Weeks 5–10 records. Weeks 5–6 research rankings were retrospective, another
limitation on interpreting these historical comparisons.

Point forecasts are the locked-line target plus 25%, 50% or 100% of the original
model deviation. ATS uses home margin; totals uses combined points. Positive
blends preserve original sides, so full-card results cannot improve merely by
shrinking the forecast. The line-only benchmark makes no wagers and has a
neutral 0.5 probability on the original selection for probability-score comparison.

Gaussian research probabilities use each candidate's prior-week residual mean
and sample standard deviation, separately by market. The point forecast remains
the stated blend. An additional frequency estimator uses prior standardized-edge
bins below 0.25, 0.25–0.5 and at least 0.5, Beta(1,1) smoothing and an explicit
same-market pooled fallback below 20 decided observations. None is a validated
confidence policy. Probabilities are clamped only at 0.000001 and 0.999999 for
numerical representation. This does not authorize Confidence 3–5.

Each method retains ATS, totals and combined research Top 5s, with at most one
selection per game. Ordering is probability descending, then market and game ID.
Cross-market probability comparability is an experimental hypothesis, not an
assumption allowed for the official card. Every cohort is compared with that
week's original ATS research Top 5; all memberships and failures are retained.

`results-v1.json` contains 50 market/fold evaluations and 60 Top 5 cohorts,
including training periods, sample sizes, residual parameters, W/L/P, -110 units,
MAE, RMSE, AUC, Brier score, ten fixed probability-bin reliability tables, ECE
and Wilson hit-rate intervals. Derived results use eight decimal places; original
evidence remains protected byte-for-byte by existing custody gates.

## Actual Week 10 historical-fold results (57 selections per market)

| Forecast | ATS MAE / RMSE | Totals MAE / RMSE | ATS Brier / AUC | Totals Brier / AUC |
|---|---:|---:|---:|---:|
| Locked line | 12.798 / 16.671 | 13.132 / 16.124 | .250 / .500 | .250 / .500 |
| 25% model | 13.004 / 16.898 | 13.525 / 16.679 | .267 / .373 | .263 / .315 |
| 50% model | 13.338 / 17.197 | 13.954 / 17.331 | .273 / .368 | .275 / .293 |
| Original point / Gaussian probability | 14.122 / 17.996 | 15.155 / 18.888 | .285 / .413 | .301 / .294 |
| Original point / prior frequency | 14.122 / 17.996 | 15.155 / 18.888 | .252 / .480 | .248 / .607 |

All positive blends retain 26–31 and -7.363636 units in both full markets. The
line-only baseline remains better than either shrinkage forecast on Week 10
point accuracy. Better point accuracy relative to the original model does not
establish better selection quality.

| Candidate | Weeks 6–10 ATS Top 5 | Totals Top 5 | Combined Top 5 | Week 10 combined |
|---|---:|---:|---:|---:|
| 25% model | 17–8, +7.455u | 6–19, -13.545u | 14–11, +1.727u | 0–5 |
| 50% model | 15–10, +3.636u | 6–19, -13.545u | 12–13, -2.091u | 1–4 |
| Original / Gaussian | 15–10, +3.636u | 8–17, -9.727u | 13–12, -0.182u | 1–4 |
| Prior frequency | 12–13, -2.091u | 13–12, -0.182u | 11–14, -4.000u | 1–4 |

Twenty-five overlapping picks per series, repeated teams, only five evaluation
weeks and post-Week-10 method specification preclude a promotion claim. Even the
best-looking ATS series failed 1–4 in Week 10; its combined series failed 0–5.
Do not tune bins, blending weights or ranking rules to rescue these results.

## Forward protocol and remaining work

After genuine Week 11 contest lines and the unchanged official forecasts exist,
seal a separate research shadow with these fixed methods, all probabilities,
training inputs, code/parameter hashes, selection memberships and receipt time.
Exclude any game already started at generation. Freeze before kickoff, then
evaluate all candidates after finals against the locked-line baseline and the
untouched original ATS research Top 5. Retain unsuccessful candidates, paired
selection differences and overlap; do not describe reordered shared winners as
new selection skill. Do not change the frozen PR #50 protocol.

Drive-based research is not implemented or validated in this delivery. Official
CFBD Week 8–10 drives and game efficiency have been captured for prospective
preparation. A complete historical, point-in-time-compatible drive feature set,
explicit garbage-time/possession definitions, handling of defensive and return
scores, and a separately sealed estimator are still required. Season advanced
EPA excludes garbage time; captured recent-game advanced data does not. Mixing
these filters silently would be invalid. Personnel and explosive-play effects
cannot be invented from a cumulative EPA average.

No new confidence assignments, model promotion or policy version is authorized.
The existing formal statistical, calibration, stability and independent-approval
gates remain in force; one favorable fold or unadjusted 95% interval is insufficient.

Replay: `python -m research.week11_validation.anchor_diagnostics --verify`.
Tests: `python -m pytest -q tests/test_week11_anchor_research.py`.
