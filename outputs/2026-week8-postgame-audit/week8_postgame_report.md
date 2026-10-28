# Week 8 postgame audit

All 52 ATS and 52 totals picks graded from the original PR #42 seal. ESPN scoreboard and game summaries reconcile with separately captured CFBD final scores. No forecast was regenerated. CLV is INCOMPLETE; missing historical closes do not block unrelated integrity repairs.

No recorded owner-approved Week 8 five exists. The unfinished contextual review is not an approved card or a pregame substitution record.

| Frozen cohort | N | W-L-P | Hit rate | Hypothetical -110 units |
|---|---:|---|---:|---:|
| governed_v28_top5 | 5 | 2-3-0 | 40.0% | -1.182 |
| ats_full | 52 | 26-26-0 | 50.0% | -2.364 |
| ats_research_top5 | 5 | 3-2-0 | 60.0% | +0.727 |
| ats_research_top10 | 10 | 6-4-0 | 60.0% | +1.455 |
| ats_research_remaining47 | 47 | 23-24-0 | 48.9% | -3.091 |
| total_full | 52 | 23-29-0 | 44.2% | -8.091 |
| total_research_top5 | 5 | 3-2-0 | 60.0% | +0.727 |
| total_research_top10 | 10 | 3-7-0 | 30.0% | -4.273 |
| total_research_remaining47 | 47 | 20-27-0 | 42.6% | -8.818 |
| legacy_mixed_research_top5 | 5 | 3-2-0 | 60.0% | +0.727 |
| human_review_candidate_board | 10 | 6-4-0 | 60.0% | +1.455 |

## Original combined research Top 5

| Game | Pick | Final away-home | Forecast total | Result | Cover margin |
|---|---|---|---:|---|---:|
| Miami (OH) at Central Michigan | over 40.5 | 28-27 | 51.450 | WIN | +14.5 |
| San Diego State at Colorado State | under 64.5 | 49-56 | 54.705 | LOSS | -40.5 |
| Utah State at Texas State | under 60.5 | 17-20 | 51.076 | WIN | +23.5 |
| Colorado at Oklahoma State | under 55.5 | 24-57 | 46.691 | LOSS | -25.5 |
| Baylor at Kansas | under 53.5 | 24-25 | 45.510 | WIN | +4.5 |

## Largest totals errors

| Game | Forecast | Actual | Actual minus forecast |
|---|---:|---:|---:|
| San Diego State at Colorado State | 54.705 | 105 | +50.295 |
| Rice at Florida Atlantic | 52.505 | 100 | +47.495 |
| Colorado at Oklahoma State | 46.691 | 81 | +34.309 |
| Western Michigan at Toledo | 49.675 | 83 | +33.325 |
| North Texas at Navy | 57.138 | 88 | +30.862 |
| California at SMU | 48.801 | 79 | +30.199 |
| Indiana at Michigan | 47.460 | 19 | -28.460 |
| East Carolina at Memphis | 46.575 | 75 | +28.425 |
| Hawai'i at Northern Illinois | 49.130 | 77 | +27.870 |
| Boston College at Georgia Tech | 49.878 | 76 | +26.122 |

One postgame schedule discrepancy is retained separately: North Dakota State-New Mexico was listed at 02:00 UTC in the frozen schedule and 02:20 UTC by ESPN after the game. Generation and sealing preceded both. Team IDs and scores agree; original schedule bytes are unchanged.

All numeric model adjustments remain zero. Governed ATS confidence is uniformly 1, with null uncertainty and tied ranking inputs. Research confidence and scores are uncalibrated. Backdoor classification remains unavailable unless a complete validated scoring sequence exists; a final score alone is insufficient.

Replay offline with `python -m scripts.build_week8_postgame_audit --verify`. Exact file inventories, provider payload hashes, all protected source hashes, code identities and regenerated report/ledger bytes are checked. Re-running the writer against any existing output fails closed.
