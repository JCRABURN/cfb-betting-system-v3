# Week 10 forensic audit

All 57 eligible games are final and agree across ESPN summaries, ESPN scoreboard and CFBD. All 114 independent grades agree with the separately graded frozen PR50 baseline. No missing eligible game or unexplained score discrepancy remains.

All selections, lines, forecasts, confidence, ranks, timestamps, screenshots and owner-review versions remain unchanged. Master Prompt v2.8 is unchanged. No owner-approved five was identified; research and human-review cohorts are not submitted contest picks. All new analyses and numerical proposals are RESEARCH ONLY.

## Full card and sportsbook-line baseline

| Market | N | W-L-P | Hit rate | -110 units | MAE | RMSE | Bias actual-model | Line MAE | Line RMSE |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| ATS | 57 | 26-31-0 | 45.61% | -7.363636 | 14.122257 | 17.996157 | -7.682401 | 12.798246 | 16.671359 |
| TOTAL | 57 | 26-31-0 | 45.61% | -7.363636 | 15.155035 | 18.887521 | 5.034213 | 13.131579 | 16.123563 |

Returns risk one unit per selection: win +10/11, loss -1, push zero. The locked-line baseline is a point forecast comparator, not a wager with an invented winning side. Full ATS and totals grades are in week10_ats_audit.csv and week10_totals_audit.csv.

## Every frozen cohort

| Cohort | N | W-L-P | -110 units |
|---|---:|---|---:|
| ATS_RESEARCH_1-5 | 5 | 1-4-0 | -3.090909 |
| ATS_RESEARCH_11+ | 47 | 23-24-0 | -3.090909 |
| ATS_RESEARCH_6-10 | 5 | 2-3-0 | -1.181818 |
| GOVERNED_ATS_TOP5 | 5 | 2-3-0 | -1.181818 |
| HUMAN_20261105-afternoon-decision_1-5 | 5 | 0-5-0 | -5.000000 |
| HUMAN_20261105-afternoon-decision_6-10 | 5 | 2-3-0 | -1.181818 |
| INITIAL_FROZEN_TEN_CANDIDATES_NO_COMBINED_ORDER | 10 | 2-8-0 | -6.181818 |
| ORIGINAL_COMBINED_RESEARCH_TOP5 | 5 | 1-4-0 | -3.090909 |
| TOTAL_RESEARCH_1-5 | 5 | 1-4-0 | -3.090909 |
| TOTAL_RESEARCH_11+ | 47 | 24-23-0 | -1.181818 |
| TOTAL_RESEARCH_6-10 | 5 | 1-4-0 | -3.090909 |

Overlapping cohorts must not be added together. Research ranks 1–5, 6–10 and 11+ are nonoverlapping within each market. Original Top10 equals the first two segments. No historical ordering has been rewritten.

## Frozen PR50 prospective experiment

| Candidate | ATS Top5 W-L-P / units | Totals Top5 W-L-P / units | Combined Top5 W-L-P / units |
|---|---|---|---|
| FROZEN_V28 | 1-4-0 / -3.090909 | 1-4-0 / -3.090909 | 1-4-0 / -3.090909 |
| LOCKED_LINE | NO SELECTIONS — forecast-only baseline | NO SELECTIONS — forecast-only baseline | NO SELECTIONS — forecast-only baseline |
| FIXED_25_PERCENT_MODEL | 1-4-0 / -3.090909 | 1-4-0 / -3.090909 | 1-4-0 / -3.090909 |
| EDGE_LOGIT | 1-4-0 / -3.090909 | 4-1-0 / 2.636364 | 2-3-0 / -1.181818 |
| CONTROLLED_LOGIT | 1-4-0 / -3.090909 | 3-2-0 / 0.727273 | 1-4-0 / -3.090909 |
| CONDITIONAL_UNCERTAINTY_LOGIT | 1-4-0 / -3.090909 | 3-2-0 / 0.727273 | 1-4-0 / -3.090909 |
| MARKET_RESIDUAL_RIDGE | 1-4-0 / -3.090909 | 2-3-0 / -1.181818 | 2-3-0 / -1.181818 |

The controlled-logistic combined Top5 did not improve selection quality in this prospective week. It retained four losing ATS picks and replaced the ATS benchmark’s winning Middle Tennessee pick with a winning Miami–Notre Dame Under: zero unit gain. Its five picks differ entirely from the frozen combined five, but both also finished 1–4. Better retrospective Weeks6–9 results did not establish a stronger Week10 five.

The totals-only EDGE_LOGIT candidate went 4–1; it remains a reported secondary candidate, not a retrospectively selected winning policy. All seven candidates remain in the diagnostics. No candidate is retuned using Week10 outcomes.

All seven candidates retained, including failures. Late Nov6 reporting addendum follows Thursday kickoffs and is not claimed as original preregistration. Original protocol/798 predictions predate all kickoffs. Historical Weeks6–9 results remain retrospective research. Wilson intervals ignore within-week/team dependence; one week cannot support a reliable cluster interval.

| Primary comparison | Exact shared picks | Unit difference | Jaccard | Leave-one-game-out gain range |
|---|---:|---:|---:|---|
| CONTROLLED_LOGIT:COMBINED vs FROZEN_V28:ATS | 4 | 0.000000 | 0.666667 | [-0.9090909091, 0.9090909091] |
| CONTROLLED_LOGIT:COMBINED vs FROZEN_V28:COMBINED | 0 | 0.000000 | 0.000000 | [-1.0, 1.0] |
| FROZEN_V28:ATS vs FROZEN_V28:COMBINED | 0 | 0.000000 | 0.000000 | [-1.0, 1.0] |

One win in five has a Wilson 95% interval of roughly 3.6%–62.4%; the human 0–5 interval is 0%–43.4%. These intervals additionally assume independence that repeated teams/week effects can violate. One prospective week cannot yield a defensible week-cluster improvement interval. No significance, profitability or Confidence3–5 promotion is supported.

## Full-card experimental accuracy and probability diagnostics

| Market | Candidate | W-L-P | Units | MAE | RMSE | AUC | Brier | ECE | 80% coverage | 90% coverage |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ATS | FROZEN_V28 | 26-31-0 | -7.363636 | 14.122257 | 17.996157 | 0.465261 | 0.253995 | 0.061186 | 0.666667 | 0.894737 |
| ATS | LOCKED_LINE | 0-0-0 | 0.000000 | 12.798246 | 16.671359 | 0.500000 | 0.250000 | 0.043860 | 0.736842 | 0.877193 |
| ATS | FIXED_25_PERCENT_MODEL | 26-31-0 | -7.363636 | 13.004481 | 16.898433 | 0.465261 | 0.253995 | 0.061186 | 0.754386 | 0.877193 |
| ATS | EDGE_LOGIT | 26-31-0 | -7.363636 | 14.122257 | 17.996157 | 0.465261 | 0.253880 | 0.046725 | 0.666667 | 0.894737 |
| ATS | CONTROLLED_LOGIT | 26-31-0 | -7.363636 | 14.122257 | 17.996157 | 0.368486 | 0.271028 | 0.188669 | 0.666667 | 0.894737 |
| ATS | CONDITIONAL_UNCERTAINTY_LOGIT | 26-31-0 | -7.363636 | 14.122257 | 17.996157 | 0.358561 | 0.272743 | 0.204261 | 0.701754 | 0.859649 |
| ATS | MARKET_RESIDUAL_RIDGE | 19-38-0 | -20.727273 | 13.558696 | 17.380261 | 0.504155 | 0.269117 | 0.208871 | 0.719298 | 0.842105 |
| TOTAL | FROZEN_V28 | 26-31-0 | -7.363636 | 15.155035 | 18.887521 | 0.306452 | 0.297209 | 0.187649 | 0.754386 | 0.877193 |
| TOTAL | LOCKED_LINE | 0-0-0 | 0.000000 | 13.131579 | 16.123563 | 0.500000 | 0.250000 | 0.043860 | 0.824561 | 0.912281 |
| TOTAL | FIXED_25_PERCENT_MODEL | 26-31-0 | -7.363636 | 13.524894 | 16.678745 | 0.306452 | 0.297209 | 0.187649 | 0.807018 | 0.894737 |
| TOTAL | EDGE_LOGIT | 26-31-0 | -7.363636 | 15.155035 | 18.887521 | 0.693548 | 0.236097 | 0.105041 | 0.754386 | 0.877193 |
| TOTAL | CONTROLLED_LOGIT | 26-31-0 | -7.363636 | 15.155035 | 18.887521 | 0.694789 | 0.238882 | 0.071207 | 0.754386 | 0.877193 |
| TOTAL | CONDITIONAL_UNCERTAINTY_LOGIT | 26-31-0 | -7.363636 | 15.155035 | 18.887521 | 0.657568 | 0.240824 | 0.096382 | 0.701754 | 0.894737 |
| TOTAL | MARKET_RESIDUAL_RIDGE | 29-28-0 | -1.636364 | 13.065910 | 15.621326 | 0.451970 | 0.256235 | 0.088381 | 0.789474 | 0.929825 |

Fixed probability bins, confidence buckets, interval widths and prior-only exact-pick bootstrap stability are in research_audit.json. Original confidence labels are not calibrated probabilities. The frozen protocol and candidate parameters are retained in that file and the exact PR50 source archive.

## Five largest forecast failures

| Market | Game (away at home) | Final away-home | Projection | Actual target | Absolute error | Process evidence |
|---|---|---|---:|---:|---:|---|
| ATS | Tulsa at Tulane | 60-10 | -0.061300 | -50 | 49.938700 | 141 plays; 24 drives; 766 yards; 14 classified explosives; 0 non-offensive points |
| TOTAL | West Virginia at Texas Tech | 48-53 | 51.583589 | 101 | 49.416411 | 157 plays; 31 drives; 1220 yards; 30 classified explosives; 2 non-offensive points |
| TOTAL | Western Kentucky at Middle Tennessee | 42-51 | 48.866494 | 93 | 44.133506 | 142 plays; 26 drives; 1010 yards; 17 classified explosives; 6 non-offensive points |
| TOTAL | Boise State at Colorado State | 64-38 | 59.728245 | 102 | 42.271755 | 130 plays; 23 drives; 1182 yards; 25 classified explosives; 0 non-offensive points |
| TOTAL | Oklahoma State at Kansas State | 66-28 | 53.821172 | 94 | 40.178828 | 139 plays; 29 drives; 892 yards; 13 classified explosives; 7 non-offensive points |

ATS projection is home margin; totals projection is combined points. Large forecast failure is distinct from losing a contest pick: some poor margin forecasts still select the winning underdog. Full ordered misses, observed passers and team efficiency are retained without omitting such cases.

## Fundamental logic and review failures

1. The raw ATS model reduces each matchup to one cumulative EPA differential. The total model has only four cumulative offense/defense EPA levels. QB changes, OL availability, injuries, possessions and explosive-play rates do not directly enter these sealed forecasts. These are demonstrable feature omissions, not a quantified injury explanation.
2. Large model-line gaps are often model errors. Both full-card MAE and RMSE again lose to the locked-line baseline. Research totals Top5 went 1–4 despite its largest estimated advantages. Its model MAE was 26.170 versus the line’s 15.900. Comparing uncalibrated ATS and totals scores does not make a reliable combined ranking.
3. A tempo-only repair is insufficient. Boise State–Colorado State produced 102 points with only 130 provider offensive plays and 23 drives: 1,182 yards, 25 classified explosives and zero non-offensive points. West Virginia–Texas Tech combined both volume and explosive efficiency: 31 drives and 1,220 yards. These are different failure modes.
4. UTSA–FAU reached 89 points with 151 plays, 28 drives, 988 yards and 28 classified explosives, without non-offensive scoring. The human review correctly recognized risk in that Under but did not choose better replacements. Its entire five lost.
5. The controlled ranking did not rescue the strongest five. Its substitution exchanged a winner for a winner and kept four losers. Improved labels or ordering are not demonstrated selection improvement.

Pregame review documents and observed QB statistics are retained. Missing verified OL snap counts, participation changes and causal counterfactuals prevent attributing an exact point loss to injury. No injury adjustment is invented.

Scoring classifications use validated scoring sequences. Defensive sack-fumble touchdowns require corroborating ESPN/CFBD IDs, clocks, scoring-team identity, score progression and descriptions. Troy’s zero-yard end-zone recovery is explicitly classified separately; no return distance is fabricated. Play volume is not clock-adjusted tempo; provider drive definitions and explosive-play filters are documented in game_process_evidence.json.

## Human review attribution

HUMAN_20261105-afternoon-decision_1-5: -1.909091 units versus the original combined five. Shared picks cancel. Added: Missouri 2.5 (LOSS); Boston College 6.5 (LOSS); UConn 6.5 (LOSS). Removed: West Virginia–Texas Tech under 65.5 (LOSS); Texas State–Oregon State under 72.5 (WIN); UTSA–Florida Atlantic under 73.5 (LOSS).

## Weeks5–10 comparison

| Week | Market | N | W-L-P | Units | Model MAE | Line MAE | Model RMSE | Line RMSE |
|---|---|---:|---|---:|---:|---:|---:|---:|
| 5 | ATS | 56 | 34-22-0 | 8.909091 | 14.033147 | 13.107143 | 19.120659 | 17.251294 |
| 5 | TOTAL | 56 | 23-33-0 | -12.090909 | 14.225392 | 12.839286 | 17.284336 | 15.621642 |
| 6 | ATS | 58 | 28-30-0 | -4.545455 | 13.011331 | 11.551724 | 16.073201 | 14.519013 |
| 6 | TOTAL | 58 | 33-25-0 | 5.000000 | 12.430030 | 12.431034 | 16.278069 | 15.860654 |
| 7 | ATS | 59 | 26-33-0 | -9.363636 | 11.951406 | 10.906780 | 14.741156 | 13.634919 |
| 7 | TOTAL | 59 | 33-26-0 | 4.000000 | 12.939959 | 12.838983 | 15.610982 | 15.855679 |
| 8 | ATS | 52 | 26-26-0 | -2.363636 | 10.874755 | 10.653846 | 13.374498 | 13.077432 |
| 8 | TOTAL | 52 | 23-29-0 | -8.090909 | 15.010405 | 14.134615 | 18.954902 | 17.671685 |
| 9 | ATS | 54 | 28-26-0 | -0.545455 | 13.120028 | 13.092593 | 15.927294 | 15.730073 |
| 9 | TOTAL | 54 | 29-25-0 | 1.363636 | 12.108100 | 11.259259 | 15.348078 | 14.547177 |
| 10 | ATS | 57 | 26-31-0 | -7.363636 | 14.122257 | 12.798246 | 17.996157 | 16.671359 |
| 10 | TOTAL | 57 | 26-31-0 | -7.363636 | 15.155035 | 13.131579 | 18.887521 | 16.123563 |
| 5-10 | ATS | 336 | 168-168-0 | -15.272727 | 12.870785 | 12.017857 | 16.342587 | 15.232132 |
| 5-10 | TOTAL | 336 | 167-169-0 | -17.181818 | 13.628681 | 12.764881 | 17.096928 | 15.958838 |
| 7-10 | ATS | 222 | 106-116-0 | -19.636364 | 12.540858 | 11.864865 | 15.636809 | 14.866599 |
| 7-10 | TOTAL | 222 | 111-111-0 | -10.090909 | 13.791320 | 12.833333 | 17.257454 | 16.068196 |

Weeks 5-6 have pregame forecasts but retrospectively constructed research ordering; Weeks 7-10 have sealed pregame ranks. All new subgroup tests and candidate formulas were specified after outcomes and are exploratory, including temporally ordered replay. Repeated teams and overlapping cohorts are not independent trials.

AUC and edge/rank discrimination, favorite/underdog, home/away, road favorites, spread/total size, Overs/Unders, confidence and nonoverlapping ranking segments are in the cross-week diagnostic tables. Six-week paired forecast-error uncertainty uses 2,000 seeded week-block resamples; repeated-team and one-season limitations remain.

## Numerical proposals — RESEARCH ONLY

- **Locked-line anchor**: Predeclare model weights 0, 0.25 and 0.50; fit no weights on the evaluation week. Evidence: Frozen PR50 25%-model candidate and exact market baseline are scored separately. Validation: Nested prior-week selection, then untouched future weeks; improve both MAE/RMSE and prospective Top5 return against ATS research baseline.
- **Possessions and points per drive**: Recent 3-game and season-to-date drive rates with predeclared 0.25/0.50 recent weights; possessions times opponent-adjusted points/drive. Evidence: Actual high-scoring misses include ordinary-volume but extreme-efficiency games, so a tempo-only correction is insufficient. Validation: Archive genuine pregame drive/play data, QB/OL status and missingness; never backfill from target-game plays.
- **Tail uncertainty and abstention research**: 80% and 90% prior-only conformal intervals, separate market residual scales; compare global versus predeclared line/tempo strata. Evidence: Week10 57-game error and archived-sigma coverage tables. Validation: At least 100 calibration residuals per stratum; missing-data tags and fallback; retain mandatory contest picks separately from betting abstention.
- **Confidence and ranking governance**: Keep PR50 gates: 100 prospective Top5 picks, 20 weeks, 2 seasons; ECE <=0.03, Jaccard >=0.60 and positive paired return lower95. Evidence: Controlled combined Top5 failed to improve Week10 over frozen ATS research. Validation: Confidence3:500 decisions/8weeks/p>=.55/LB>.52381; Confidence4:500/12/p>=.60/LB>.55; Confidence5:800/16/p>=.65/LB>.60. Owner approval/new version still required.

No new model, calibrated confidence, v2.9 policy, market substitution or owner approval is authorized by this audit. Keep all unsuccessful candidates for future comparison. The statistical minima are necessary, not sufficient.

## Custody, exclusions, CLV and engineering

3266 pinned inputs verify. Original historical custody verifies 2729 inputs and 125 protected artifacts; source database remains 09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842 with integrity ok and zero foreign-key violations.

All 62 original SplashSports matchups/spreads/totals reconcile. Five elapsed games were excluded before execution:
- Ohio at Akron: FINAL_AT_SCREENSHOT_RECEIPT_NOT_PROSPECTIVE; kickoff 2026-11-04T00:00:00+00:00.
- Buffalo at Miami OH: FINAL_AT_SCREENSHOT_RECEIPT_NOT_PROSPECTIVE; kickoff 2026-11-04T01:00:00+00:00.
- Ball State at Massachusetts: KICKOFF_ELAPSED_BEFORE_GENERATION; kickoff 2026-11-05T00:00:00+00:00.
- Toledo at Sacramento State: KICKOFF_ELAPSED_BEFORE_GENERATION; kickoff 2026-11-05T00:00:00+00:00.
- Central Michigan at Eastern Michigan: KICKOFF_ELAPSED_BEFORE_GENERATION; kickoff 2026-11-05T00:30:00+00:00.

The original 62-game screenshot source matches FBS-vs-FBS entries. It is not proof of complete contest coverage for FBS-vs-FCS games; no retrospective line or prediction is added for Merrimack-Wake Forest.

CLV INCOMPLETE: 114 archived market observations, zero qualified closes. Pregame receipt is not a qualified final pre-kickoff quote. Archived CFBD price objects lack quote timestamps; postgame market labels excluded. No close reconstructed.

Replay: `python -X utf8 -m scripts.build_week10_formal_audit --verify`. Generation refuses an existing output directory. Exact input/output hash coverage and status contradictions fail closed. Forecasts are read, never regenerated. The existing CI matrix covers Ubuntu/Windows and Python3.11/3.12. Exact source/tested-merge SHAs, actual test outcomes and workflow links belong to the delivery record; this generated report does not invent a future CI success.

No schema or database mutation. New audit modules, evidence, tests and documentation are additive; only scoped byte-preservation rules and existing CI triggers/gates are extended. Rollback abandons/reverts the audit implementation while retaining all source captures and frozen versions. No operational workflow activation or PR merge.
