# Lessons learned and v2.9 recommendations

| Market | N | W | L | Model MAE | Line MAE | ROI |
|---|---|---|---|---|---|---|
| ATS | 400 | 204 | 196 | 13.1035 | 12.2300 | -0.0264 |
| TOTAL | 400 | 202 | 198 | 13.5004 | 12.7350 | -0.0359 |

| Problem and evidence | Root cause / affected implementation | Proposed solution and expected benefit | Overfitting risk / required validation |
|---|---|---|---|
| Governed five0–5; all64 confidence1/null | Governed forecast record omits uncertainty; confidence and Top5 fall through to IDs | Explicit unvalidated fallback status; develop calibrated ranking to identify the five with relative reliability | Do not simply rescale sigma; require OOS ranking/calibration and untouched-week Top5 comparison |
| Both markets trail line-baseline MAE over400 comparable games each | EPA-only margin and component totals do not establish added predictive information over market | Market-residual regularized baseline, then opponent interactions and consistent pace/PPD | Fixed penalty10 is research specification, not optimized or promoted. Compare every unsuccessful fold and candidate |
| Human2–3 versus original3–2; removed picks3–1 | Context cautions did not reliably identify which extreme gaps were bad | Version contextual changes with quantified completeness and eventual independent effect audit | One week cannot justify rejecting human review or banning a segment |
| Totals high confidence from Gaussian transform | Uncalibrated distribution and scale conflated with cover probability | OOF calibration shared across markets; empirical candidate buckets .525/.55/.58/.62 | Research thresholds only. Require bucket sample, calibration, Wilson lower bounds and stability |
| Prior drive anomalies147; {'RESOLVED_BY_CROSS_PROVIDER_SCORING_PLAY_IDS': 116, 'UNRESOLVED_REMAINS_QUARANTINED': 31} | Provider endpoint score deltas can contradict scoring-play sequence | Reproducible correction ledger for corroborated rows; exclude unresolved team-games | Late corrections cannot be inserted into old prospective runs; validate possession, TD conversion, nonoffensive and overtime rules |
| Qualified CLV coverage0/128 | Archived market quotes have no actual quote timestamps | Capture book-specific timed prices before future kickoff | Do not turn retrieval or postgame odds into closing evidence |

Confirmed defects are the absence of a quality-bearing fallback ranking and misleading comparability of confidence scales. Model replacements, probability boundaries, contextual completeness penalties and feature additions are experiments. No production code, thresholds, v2.8 prompt or locked lines change in this PR.

## Validation and rejection

All five original frozen candidates, all14 drive forecasts and the new residual candidate remain reported. Positive linear shrinkage toward the locked line preserves pick direction. Better MAE is not proof of better ATS results. The new candidate was specified after Week11 outcomes and is retrospective development, including its Week11 fold.

All four frozen combined-five methods returned3–2; none establishes superiority. The new residual ranking also has failed weeks, retained in v29_chronological_folds.csv and v29_candidate_top5.csv. No candidate passes the untouched-holdout promotion requirement.
