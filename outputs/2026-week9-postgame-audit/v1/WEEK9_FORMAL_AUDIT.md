# Week 9 formal postgame audit — v1

Formal score reconciliation and grading COMPLETE. Historical CLV INCOMPLETE. Owner approval PENDING. Merge recommendation HOLD until exact-tree CI and independent review are recorded. Master Prompt v2.8 and every sealed selection remain unchanged.

This additive audit supersedes the authority of the preliminary On3 grading at commit `190c8949edcf8da806908b567d4daa59b605f1cd`; it does not overwrite those five files. All 54 scores agree across fresh ESPN summaries, the ESPN scoreboard and CFBD finals. All 108 independently computed grades, locked lines, cover margins and preliminary six-decimal forecast errors reconcile without discrepancies.

Custody verifies 2729 pinned input files, including all 125 previously recorded protected artifacts. The source SQLite database has integrity `ok`, zero foreign-key violations, and SHA-256 `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`. Retrieval times, raw/compressed hashes, game IDs, orientation and final flags are retained in capture manifests and the 54-row final-score table.

ESPN and CFBD are separately retrieved providers, but may share upstream scoring data; agreement is corroboration rather than proof of independent statistical origins. The original optional `/games/advanced` request returned 404 and remains archived. A separate successful `/stats/game/advanced` capture supplies the diagnostic statistics ([provider endpoint documentation](https://github.com/CFBD/cfbd-python/blob/main/README.md)).

## Full-card and cross-week results

Hypothetical risk 1 per pick at -110: win +10/11, loss -1, push 0. No actual wager or profitability assertion.

Weeks 5-6 have pregame forecasts but retrospectively constructed research ordering; Weeks 7-9 have sealed pregame ranks. All new subgroup tests and candidate formulas were specified after outcomes and are exploratory, including temporally ordered replay. Repeated teams and overlapping cohorts are not independent trials.

| Week | Market | N | W-L-P | Hit rate | MAE | RMSE | Bias actual−forecast | -110 units | Locked-line MAE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | ATS | 56 | 34-22-0 | 60.71% | 14.033 | 19.121 | -0.589 | +8.909 | 13.107 |
| 5 | TOTAL | 56 | 23-33-0 | 41.07% | 14.225 | 17.284 | +2.448 | -12.091 | 12.839 |
| 6 | ATS | 58 | 28-30-0 | 48.28% | 13.011 | 16.073 | +1.617 | -4.545 | 11.552 |
| 6 | TOTAL | 58 | 33-25-0 | 56.90% | 12.430 | 16.278 | +1.034 | +5.000 | 12.431 |
| 7 | ATS | 59 | 26-33-0 | 44.07% | 11.951 | 14.741 | +0.093 | -9.364 | 10.907 |
| 7 | TOTAL | 59 | 33-26-0 | 55.93% | 12.940 | 15.611 | +1.265 | +4.000 | 12.839 |
| 8 | ATS | 52 | 26-26-0 | 50.00% | 10.875 | 13.374 | +1.201 | -2.364 | 10.654 |
| 8 | TOTAL | 52 | 23-29-0 | 44.23% | 15.010 | 18.955 | +4.681 | -8.091 | 14.135 |
| 9 | ATS | 54 | 28-26-0 | 51.85% | 13.120 | 15.927 | +1.840 | -0.545 | 13.093 |
| 9 | TOTAL | 54 | 29-25-0 | 53.70% | 12.108 | 15.348 | +1.514 | +1.364 | 11.259 |
| 5-9 | ATS | 279 | 142-137-0 | 50.90% | 12.615 | 15.984 | +0.817 | -7.909 | 11.858 |
| 5-9 | TOTAL | 279 | 141-138-0 | 50.54% | 13.317 | 16.708 | +2.139 | -9.818 | 12.690 |
| 7-9 | ATS | 165 | 80-85-0 | 48.48% | 11.995 | 14.734 | +1.014 | -12.273 | 11.542 |
| 7-9 | TOTAL | 165 | 85-80-0 | 51.52% | 13.320 | 16.657 | +2.423 | -2.727 | 12.730 |

## Does the totals rebound establish an improvement?

Week 9 totals rose from 23-29-0 to 29-25-0. MAE improved by 2.902 points and RMSE by 3.607, while directional underprediction fell from 4.681 to 1.514. These are actual descriptive improvements in forecast error, not merely a change in win count.

However, the 54-game hit-rate Wilson 95% interval is 40.6%–66.3%, spanning both 50% and the 52.38% break-even rate at -110. The locked-total baseline beats the model by 0.849 MAE points and 0.801 RMSE points. The week is compatible with ordinary outcome variance and does not demonstrate a new calibrated edge or structural model improvement. Week-to-week matchup composition changed; repeated teams invalidate treating every comparison as an independent experiment.

## Frozen selection cohorts

Ranks 1–5, 6–10 and 11+ are nonoverlapping within each market/week. Top 10 is the union of the first two segments and is never added again to a cumulative return. Human revisions, governed picks and research picks overlap; their returns must not be summed. Mixed ATS/totals cohort forecast-target metrics are deliberately not pooled.

| Cohort | N | W-L-P | -110 units |
| --- | --- | --- | --- |
| ATS_RESEARCH_1-5 | 5 | 3-2-0 | +0.727 |
| ATS_RESEARCH_11+ | 44 | 21-23-0 | -3.909 |
| ATS_RESEARCH_6-10 | 5 | 4-1-0 | +2.636 |
| GOVERNED_ATS_TOP5 | 5 | 3-2-0 | +0.727 |
| HUMAN_20261028-evening_1-5 | 5 | 3-2-0 | +0.727 |
| HUMAN_20261028-evening_6-10 | 5 | 3-2-0 | +0.727 |
| HUMAN_20261028-morning_1-5 | 5 | 3-2-0 | +0.727 |
| HUMAN_20261028-morning_6-10 | 5 | 3-2-0 | +0.727 |
| HUMAN_20261029-morning-decision_1-5 | 5 | 4-1-0 | +2.636 |
| HUMAN_20261029-morning-decision_6-10 | 5 | 2-3-0 | -1.182 |
| HUMAN_20261030-friday-morning_1-5 | 5 | 4-1-0 | +2.636 |
| HUMAN_20261030-friday-morning_6-10 | 5 | 2-3-0 | -1.182 |
| INITIAL_FROZEN_TEN_CANDIDATES_NO_COMBINED_ORDER | 10 | 6-4-0 | +1.455 |
| ORIGINAL_COMBINED_RESEARCH_TOP5 | 5 | 3-2-0 | +0.727 |
| TOTAL_RESEARCH_1-5 | 5 | 3-2-0 | +0.727 |
| TOTAL_RESEARCH_11+ | 44 | 25-19-0 | +3.727 |
| TOTAL_RESEARCH_6-10 | 5 | 1-4-0 | -3.091 |

### Latest saved human five — recommendations, not owner-approved picks

| Order | Matchup | Frozen selection / line | Frozen forecast | Human confidence | Final away–home | Result | Cover margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Northwestern @ Oregon | Northwestern 3.5 | -3.9257035349943417 | 2 | 26–34 | LOSS | -4.5 |
| 2 | Notre Dame @ Navy | Navy 30.5 | -10.981021675830757 | 2 | 35–13 | WIN | 8.5 |
| 3 | Southern Miss @ UL Monroe | under 56.5 | 47.77896800273346 | 2 | 35–21 | WIN | 0.5 |
| 4 | SMU @ Syracuse | under 58.5 | 49.830782526761865 | 1 | 27–30 | WIN | 1.5 |
| 5 | Troy @ James Madison | Troy 20.5 | 11.212407998613799 | 1 | 24–21 | WIN | 23.5 |

The October 28 morning and evening fives each went 3–2; the October 29 morning decision and October 30 retained version each went 4–1. These are four revisions of the same week, not 20 independent outcomes. Friday preserved already-started Thursday rows byte-for-byte through the existing owner-review verifier. The initial frozen ten is a candidate set with separate within-market ranks, not an invented combined ordering.

### FAU–North Texas removal

The recorded October 29 11:53:45 UTC decision replaced FAU–North Texas Under 77.5 (rank 5→6) with SMU–Syracuse Under 58.5 (rank 6→4), and moved Troy from 4→5. This preceded Thursday kickoff at 23:30 UTC. The unchanged original combined research board kept FAU Under at rank 1. The full pregame rationale, source capture timestamps and hashes are copied by reference and verbatim fields in `game_process_evidence.json`; postgame observations below are not presented as pregame knowledge.

FAU Under lost while SMU Under won: the single substitution improved the recorded five by one win and 21/11 = 1.909091 hypothetical units. It supports this particular decision descriptively, not a causal claim that human review has a repeatable edge. Original combined research 3–2 versus latest human 4–1 has the same one-win difference but involves several substitutions and overlaps.

## Ranking discrimination and confidence

| Weeks | Market | Rank segment | N | W-L-P | -110 units |
| --- | --- | --- | --- | --- | --- |
| 5 | ATS | 1-5 | 5 | 3-2-0 | +0.727 |
| 5 | ATS | 6-10 | 5 | 2-3-0 | -1.182 |
| 5 | ATS | 11+ | 46 | 29-17-0 | +9.364 |
| 5 | TOTAL | 1-5 | 5 | 3-2-0 | +0.727 |
| 5 | TOTAL | 6-10 | 5 | 2-3-0 | -1.182 |
| 5 | TOTAL | 11+ | 46 | 18-28-0 | -11.636 |
| 6 | ATS | 1-5 | 5 | 4-1-0 | +2.636 |
| 6 | ATS | 6-10 | 5 | 3-2-0 | +0.727 |
| 6 | ATS | 11+ | 48 | 21-27-0 | -7.909 |
| 6 | TOTAL | 1-5 | 5 | 1-4-0 | -3.091 |
| 6 | TOTAL | 6-10 | 5 | 3-2-0 | +0.727 |
| 6 | TOTAL | 11+ | 48 | 29-19-0 | +7.364 |
| 7 | ATS | 1-5 | 5 | 3-2-0 | +0.727 |
| 7 | ATS | 6-10 | 5 | 2-3-0 | -1.182 |
| 7 | ATS | 11+ | 49 | 21-28-0 | -8.909 |
| 7 | TOTAL | 1-5 | 5 | 2-3-0 | -1.182 |
| 7 | TOTAL | 6-10 | 5 | 2-3-0 | -1.182 |
| 7 | TOTAL | 11+ | 49 | 29-20-0 | +6.364 |
| 8 | ATS | 1-5 | 5 | 3-2-0 | +0.727 |
| 8 | ATS | 6-10 | 5 | 3-2-0 | +0.727 |
| 8 | ATS | 11+ | 42 | 20-22-0 | -3.818 |
| 8 | TOTAL | 1-5 | 5 | 3-2-0 | +0.727 |
| 8 | TOTAL | 6-10 | 5 | 0-5-0 | -5.000 |
| 8 | TOTAL | 11+ | 42 | 20-22-0 | -3.818 |
| 9 | ATS | 1-5 | 5 | 3-2-0 | +0.727 |
| 9 | ATS | 6-10 | 5 | 4-1-0 | +2.636 |
| 9 | ATS | 11+ | 44 | 21-23-0 | -3.909 |
| 9 | TOTAL | 1-5 | 5 | 3-2-0 | +0.727 |
| 9 | TOTAL | 6-10 | 5 | 1-4-0 | -3.091 |
| 9 | TOTAL | 11+ | 44 | 25-19-0 | +3.727 |
| 5-9 | ATS | 1-5 | 25 | 16-9-0 | +5.545 |
| 5-9 | ATS | 6-10 | 25 | 14-11-0 | +1.727 |
| 5-9 | ATS | 11+ | 229 | 112-117-0 | -15.182 |
| 5-9 | TOTAL | 1-5 | 25 | 12-13-0 | -2.091 |
| 5-9 | TOTAL | 6-10 | 25 | 8-17-0 | -9.727 |
| 5-9 | TOTAL | 11+ | 229 | 121-108-0 | +2.000 |
| 7-9 | ATS | 1-5 | 15 | 9-6-0 | +2.182 |
| 7-9 | ATS | 6-10 | 15 | 9-6-0 | +2.182 |
| 7-9 | ATS | 11+ | 135 | 62-73-0 | -16.636 |
| 7-9 | TOTAL | 1-5 | 15 | 8-7-0 | +0.273 |
| 7-9 | TOTAL | 6-10 | 15 | 3-12-0 | -9.273 |
| 7-9 | TOTAL | 11+ | 135 | 74-61-0 | +6.273 |

Higher AUC means more wins at higher score/edge; 0.5 means no discrimination. Permutation p-values are exploratory, unadjusted for multiple comparisons or repeated-team clustering. No score is promoted to a validated probability.

| Weeks | Market | Variable | N | Win correlation | AUC | Exploratory p |
| --- | --- | --- | --- | --- | --- | --- |
| 9 | ATS | selected_forecast_edge | 54 | 0.119721 | 0.563187 | 0.398 |
| 9 | ATS | research_score_not_calibrated | 54 | 0.119721 | 0.563187 | 0.398 |
| 9 | TOTAL | selected_forecast_edge | 54 | -0.13746 | 0.437241 | 0.331 |
| 9 | TOTAL | research_score_not_calibrated | 54 | -0.134296 | 0.437241 | 0.333 |
| 5-9 | ATS | selected_forecast_edge | 279 | 0.078441 | 0.549913 | 0.188 |
| 5-9 | ATS | research_score_not_calibrated | 279 | 0.078441 | 0.549913 | 0.188 |
| 5-9 | TOTAL | selected_forecast_edge | 279 | -0.102107 | 0.443108 | 0.076 |
| 5-9 | TOTAL | research_score_not_calibrated | 279 | -0.102005 | 0.442954 | 0.076 |
| 7-9 | ATS | selected_forecast_edge | 165 | 0.085909 | 0.552647 | 0.259 |
| 7-9 | ATS | research_score_not_calibrated | 165 | 0.085909 | 0.552647 | 0.259 |
| 7-9 | TOTAL | selected_forecast_edge | 165 | -0.091841 | 0.457206 | 0.226 |
| 7-9 | TOTAL | research_score_not_calibrated | 165 | -0.090277 | 0.457059 | 0.23 |

Frozen confidence buckets (all ATS confidence values are 1; there is no Week 9 ATS confidence ladder to validate):

| Weeks | Market | Confidence | N | W-L-P | Hit rate | MAE | -110 units |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 9 | ATS | 1 | 54 | 28-26-0 | 0.518519 | 13.120028 | -0.545455 |
| 9 | TOTAL | 1 | 25 | 15-10-0 | 0.6 | 11.09663 | 3.636364 |
| 9 | TOTAL | 2 | 12 | 7-5-0 | 0.583333 | 11.105826 | 1.363636 |
| 9 | TOTAL | 3 | 14 | 6-8-0 | 0.428571 | 13.642953 | -2.545455 |
| 9 | TOTAL | 4 | 2 | 1-1-0 | 0.5 | 11.467822 | -0.090909 |
| 9 | TOTAL | 5 | 1 | 0-1-0 | 0.0 | 29.214744 | -1.0 |
| 5-9 | ATS | 1 | 279 | 142-137-0 | 0.508961 | 12.615108 | -7.909091 |
| 5-9 | TOTAL | 1 | 103 | 56-47-0 | 0.543689 | 11.357968 | 3.909091 |
| 5-9 | TOTAL | 2 | 74 | 41-33-0 | 0.554054 | 11.687946 | 4.272727 |
| 5-9 | TOTAL | 3 | 90 | 39-51-0 | 0.433333 | 15.936466 | -15.545455 |
| 5-9 | TOTAL | 4 | 11 | 5-6-0 | 0.454545 | 19.73858 | -1.454545 |
| 5-9 | TOTAL | 5 | 1 | 0-1-0 | 0.0 | 29.214744 | -1.0 |

Brier score, log loss, mean uncalibrated score and actual hit rate by confidence and score bucket appear in `confidence_calibration.csv`. Confidence 1–5 is an ordinal archived label, not a percentage. Descriptive Brier/log loss of research scores does not confer probability calibration. Latest human confidence 2 went 2–1 (n=3), confidence 1 went 2–0 (n=2); neither supports a reliability ordering.

| Market | N | Within archived 1σ | Within archived 2σ | Empirical \|error\| p90 | p95 |
| --- | --- | --- | --- | --- | --- |
| ATS | 54 | 40 | 53 | 23.697818 | 33.026233 |
| TOTAL | 54 | 39 | 52 | 22.503751 | 29.214744 |

## Extreme misses, pace and defensive performance

All 54 matchups have captured team/player box scores, advanced offense/defense, drives and plays. The following measurements are postgame descriptions, not adjusted forecasts. Advanced offensive snap/drive counts include provider-specific rules and overtime; they measure volume, not clock-adjusted tempo. Explosives are pass gains ≥20 and rush gains ≥10 from explicitly classified plays. Return/ambiguous-fumble plays are excluded from that definition.

| Market | Matchup | Frozen forecast | Actual target | Signed error | Frozen pick | Result |
| --- | --- | --- | --- | --- | --- | --- |
| ATS | Boston College @ Duke | 8.223237380764393 | 45 | 36.776762619235607 | Duke -7.5 | WIN |
| ATS | Virginia @ Wake Forest | 10.825710981812527 | 44 | 33.174289018187473 | Virginia 12.5 | LOSS |
| ATS | Baylor @ UCF | 1.0262326260236856 | -32 | -33.0262326260236856 | Baylor 1.5 | WIN |
| ATS | Wisconsin @ Iowa | 0.7410066126164261 | 30 | 29.2589933873835739 | Wisconsin 3.5 | LOSS |
| ATS | Florida International @ Liberty | 12.052965893673505 | 39 | 26.947034106326495 | Florida International 13.5 | LOSS |
| ATS | Kent State @ Sacramento State | -2.6978184828563716 | 21 | 23.6978184828563716 | Sacramento State 9.5 | WIN |
| ATS | Kennesaw State @ Middle Tennessee | 7.424605196339355 | -16 | -23.424605196339355 | Middle Tennessee -2.5 | LOSS |
| ATS | Auburn @ Ole Miss | 6.639397666920903 | 30 | 23.360602333079097 | Auburn 13.5 | LOSS |
| ATS | Mississippi State @ Texas | 5.4574027354594135 | 28 | 22.5425972645405865 | Mississippi State 20.5 | LOSS |
| ATS | South Carolina @ Oklahoma | 5.456787992599956 | -17 | -22.456787992599956 | South Carolina 5.5 | WIN |
| TOTAL | Oklahoma State @ Iowa State | 51.09406799092176 | 100 | 48.90593200907824 | under 58.5 | LOSS |
| TOTAL | Texas State @ Boise State | 55.74394257626851 | 91 | 35.25605742373149 | under 62.5 | LOSS |
| TOTAL | Florida Atlantic @ North Texas | 59.78525616655543 | 89 | 29.21474383344457 | under 77.5 | LOSS |
| TOTAL | App State @ Georgia Southern | 49.15604031575242 | 22 | -27.15604031575242 | under 56.5 | WIN |
| TOTAL | Temple @ East Carolina | 50.37272599592973 | 26 | -24.37272599592973 | over 49.5 | LOSS |
| TOTAL | South Carolina @ Oklahoma | 44.496248677268724 | 67 | 22.503751322731276 | under 44.5 | LOSS |
| TOTAL | Jacksonville State @ New Mexico State | 46.272608608263454 | 24 | -22.272608608263454 | under 49.5 | WIN |
| TOTAL | Kennesaw State @ Middle Tennessee | 51.29287282330997 | 72 | 20.70712717669003 | over 50.5 | WIN |
| TOTAL | Washington @ Nebraska | 47.62437275770181 | 27 | -20.62437275770181 | under 49.5 | WIN |
| TOTAL | Miami @ North Carolina | 52.70151187016842 | 73 | 20.29848812983158 | over 52.5 | WIN |

Selected process evidence (complete tables cover all 54):

| Matchup | Total / frozen forecast | Offensive plays | Drives | Yards | Pass≥20 / rush≥10 | Non-offensive points* | OT |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Florida Atlantic @ North Texas | 89 / 59.785 | 172 | 26 | 1167 | 13 / 10 | 0 | False |
| Texas State @ Boise State | 91 / 55.744 | 152 | 27 | 913 | 9 / 3 | 7 | False |
| Troy @ James Madison | 45 / 48.825 | 154 | 31 | 757 | 4 / 11 | 7 | True |
| Northwestern @ Oregon | 60 / 50.072 | 136 | 23 | 897 | 9 / 10 | 0 | False |
| Colorado State @ Utah State | 45 / 52.439 | 121 | 18 | 727 | 6 / 12 | 0 | False |
| Wisconsin @ Iowa | 30 / 45.497 | 119 | 21 | 597 | 4 / 7 | 0 | False |
| Oklahoma State @ Iowa State | 100 / 51.094 | 149 | 26 | 1114 | 9 / 12 | 0 | False |
| App State @ Georgia Southern | 22 / 49.156 | 125 | 18 | 658 | 8 / 5 | 0 | False |
| Temple @ East Carolina | 26 / 50.373 | 124 | 19 | 601 | 0 / 10 | 0 | False |

*Non-offensive point deltas include any conversion bundled by ESPN with a return touchdown. They are not a counterfactual subtraction from the actual final.

FAU–UNT: 89 actual versus 59.785 frozen, an underforecast of 29.215 points. There were 172 offensive plays, 26 provider drives, 1,167 yards, 13 explosive passes and 10 explosive rushes. No non-offensive scoring event occurred. The failure therefore cannot be attributed to a special-teams touchdown or a defensive return; high volume and successful explosive offense are directly observed. The 17.715-point line gap was never evidence of 85.49% validated win probability.

Texas State–Boise State: 91 actual versus 55.744 frozen, a 35.256-point miss, with 152 plays, 27 drives and 913 yards. One non-offensive scoring event contributed 7 bundled points. Even 84 remaining arithmetic points exceed the frozen forecast by 28.256; that arithmetic does not model how the game would have unfolded without the return. The recurring Texas State total miss warrants testing explicit possessions and explosive-play features using pregame-only data, not adding a hindsight adjustment.

Troy–JMU went to overtime; final totals and ATS grades include overtime under ordinary contest grading. No medical or causal QB valuation is inferred from a box score. Observed passers, passing PPA, success rate, defensive PPA allowed and possession-time strings are preserved in the team/player tables. Pregame QB/OL/defense uncertainties remain the statements actually archived before kickoff; postgame participation cannot retroactively certify pregame availability.

| Postgame subgroup | N | W-L-P | MAE | Bias | -110 units |
| --- | --- | --- | --- | --- | --- |
| plays_150_plus | 8 | 4-4-0 | 15.439666 | 12.622398 | -0.363636 |
| plays_below150 | 46 | 25-21-0 | 11.528697 | -0.417592 | 1.727273 |
| drives_26_plus | 17 | 8-9-0 | 14.948574 | 8.985434 | -1.727273 |
| drives_below26 | 37 | 21-16-0 | 10.803017 | -1.918444 | 3.090909 |
| nonoffensive_score | 18 | 10-8-0 | 12.97004 | 4.430322 | 1.090909 |
| no_nonoffensive_score | 36 | 19-17-0 | 11.67713 | 0.056227 | 0.272727 |

These cutoffs (150 plays, 26 drives) were chosen for this postgame exploration. A valid future pace feature must predict volume before kickoff; conditioning on realized volume is explanatory only.

## Hooks, scoring sequences and CLV

All 54 ATS scoring sequences passed identity, clock, monotonic-score and final-score reconciliation. No selected ATS win meets the explicit backdoor-cover definition: selected-team scoring in the final five minutes or overtime changes non-cover to final cover while the team loses outright. Other late-score classifications are preserved in `scoring_sequence_review.json`. A hook is classified only at a half-point boundary with a validated sequence.

| Market | Matchup | Pick / line | Cover margin | Hook |
| --- | --- | --- | --- | --- |
| ATS | Kansas @ TCU | TCU -5.5 | 0.5 | WINNING_HOOK |
| ATS | Illinois @ Maryland | Maryland 2.5 | -0.5 | LOSING_HOOK |
| ATS | Bowling Green @ Western Michigan | Bowling Green 13.5 | 0.5 | WINNING_HOOK |
| TOTAL | Northern Illinois @ UNLV | under 54.5 | -0.5 | LOSING_HOOK |
| TOTAL | Southern Miss @ UL Monroe | under 56.5 | 0.5 | WINNING_HOOK |

CLV remains INCOMPLETE for all 108 selections: 312 archived pregame market observations, zero qualified closing quotes. Receipt timestamps establish retrieval before kickoff, not freshness or the final bookmaker closing price. No postgame odds label is substituted. Key-number crossing and CLV-positive/negative stratification remain unavailable; irrecoverable closes do not by themselves block unrelated integrity repairs.

## Quantified lessons and candidate changes — RESEARCH ONLY

1. **Forecast calibration before ranking promotion.** Across 279 games per market, ATS MAE 12.615 versus locked-line 11.858 and totals MAE 13.317 versus 12.690. Cumulative returns are negative after vig in both markets. Candidate A adds half of the strictly prior-week mean signed error; Candidate B blends the forecast 50/50 with the original locked-line implied target. Their temporally ordered replay is below. These fixed proposals were chosen retrospectively and require a new prospective holdout; no selection or forecast is replaced.

2. **Uncertainty and confidence.** Use the archived interval-coverage counts and per-bucket sample sizes, not raw point gap, to assess reliability. Research proposal: test a prior-only residual RMSE floor, and require at least 100 out-of-sample observations per proposed confidence bucket before a promotion decision. Compare coverage at 68%/95%, Brier/log loss and Top 5 returns. The sample-size rule is a proposed governance threshold, not adopted policy.

3. **Totals volume and efficiency.** Research a possession-count model multiplied by separately estimated points per possession, with lagged explosive-pass/rush rates and uncertain QB participation as explicit scenario inputs. Require at least 200 held-out game predictions and compare MAE/RMSE with both v2.8 and the original locked total. Numeric acceptance proposal: ≥0.5-point MAE improvement with no RMSE increase, plus no deterioration in interval coverage; reject if confidence intervals include material degradation. The 54 Week 9 process observations are exploratory support, not training/validation proof.

4. **Ranking.** Do not pool capped ATS research scores with a different totals score scale. Test separate prior-only calibration with walk-forward predictions; assess AUC, Brier/log loss, 1–5 versus 6–10 versus 11+ and same-game ATS/totals correlation. Propose at least 40 future Top 5 picks per market before evaluating ranking uplift, with a predeclared paired uncertainty interval. No ATS/totals diversification quota is introduced.

5. **Human review.** The latest five improved one result via the documented FAU→SMU substitution, but n=1 replacement and n=5 final selections are insufficient to infer skill. Continue preserving every review and compare only pre-kickoff decisions against the same frozen candidates. Never count multiple revisions of one game as independent bets.

Proposed acceptance criteria must be frozen before future outcomes, evaluated in rolling chronological folds, and reported whether accepted or rejected. Any adoption requires the completed qualifying governance audit, explicit owner approval and a new version identifier; this PR adopts none.

| Candidate | Market | Test week | Train N | Test N | Original MAE | Candidate MAE | Original RMSE | Candidate RMSE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HALF_PRIOR_BIAS | ATS | 6 | 56 | 58 | 13.011331 | 13.051964 | 16.073201 | 16.105506 |
| HALF_LOCKED_LINE_BLEND | ATS | 6 | 56 | 58 | 13.011331 | 11.87317 | 16.073201 | 14.927405 |
| HALF_PRIOR_BIAS | ATS | 7 | 114 | 59 | 11.951406 | 11.964965 | 14.741156 | 14.741887 |
| HALF_LOCKED_LINE_BLEND | ATS | 7 | 114 | 59 | 11.951406 | 11.204711 | 14.741156 | 13.879616 |
| HALF_PRIOR_BIAS | ATS | 8 | 173 | 52 | 10.874755 | 10.86002 | 13.374498 | 13.358663 |
| HALF_LOCKED_LINE_BLEND | ATS | 8 | 173 | 52 | 10.874755 | 10.547954 | 13.374498 | 12.998354 |
| HALF_PRIOR_BIAS | ATS | 9 | 225 | 54 | 13.120028 | 13.077652 | 15.927294 | 15.896788 |
| HALF_LOCKED_LINE_BLEND | ATS | 9 | 225 | 54 | 13.120028 | 12.895181 | 15.927294 | 15.602304 |
| HALF_PRIOR_BIAS | TOTAL | 6 | 56 | 58 | 12.43003 | 12.547187 | 16.278069 | 16.246333 |
| HALF_LOCKED_LINE_BLEND | TOTAL | 6 | 56 | 58 | 12.43003 | 12.356475 | 16.278069 | 15.930487 |
| HALF_PRIOR_BIAS | TOTAL | 7 | 114 | 59 | 12.939959 | 12.866725 | 15.610982 | 15.564826 |
| HALF_LOCKED_LINE_BLEND | TOTAL | 7 | 114 | 59 | 12.939959 | 12.787776 | 15.610982 | 15.578612 |
| HALF_PRIOR_BIAS | TOTAL | 8 | 173 | 52 | 15.010405 | 14.889621 | 18.954902 | 18.776455 |
| HALF_LOCKED_LINE_BLEND | TOTAL | 8 | 173 | 52 | 15.010405 | 14.495775 | 18.954902 | 18.188328 |
| HALF_PRIOR_BIAS | TOTAL | 9 | 225 | 54 | 12.1081 | 12.125208 | 15.348078 | 15.277671 |
| HALF_LOCKED_LINE_BLEND | TOTAL | 9 | 225 | 54 | 12.1081 | 11.612345 | 15.348078 | 14.762212 |

## Reproduction, limitations and governance

Run `python -m scripts.build_week9_formal_audit --verify` for exact offline byte replay, `python -m scripts.verify_replay_compat` for the repaired Week 7/8/9 dependency gates, and `python -m pytest -q` for the full suite. The writer refuses any existing output directory. The verifier requires exact output inventory, source-code identity and a separately pinned input inventory. It never rewrites evidence. Exact command execution, tested source/merge SHAs, native Windows results and GitHub matrix results are recorded separately in the delivery verification documents so this deterministic report does not invent test provenance.

The formal implementation descends from PR #47 (`0d9a4b56bd49e3fbef4326aa7a5bd6eec9d13e29`) and preserves the repaired dependency chain. PR #48 remains draft until independent review. COMMENTED is not APPROVED; the author cannot substitute for an independent reviewer. No reviewer has been designated.

Known limits: missing qualified historical closes; provider upstream dependence; small/confounded subgroups and repeated teams; no causal injury valuation or validated human-confidence probabilities; realized process data cannot be used for pregame ranking; Weeks 5–6 research order is retrospective; original mixed research ranking is not a production-valid score comparison. No raw artifact, schema, database, v2.8 policy, locked line, model output or owner approval changes.

Rollback: abandon/revert only this additive audit implementation and new audit/evidence files; retain the captured evidence and all prior versions for custody. No migration or database recovery is required. Unrelated main-worktree changes are excluded.
