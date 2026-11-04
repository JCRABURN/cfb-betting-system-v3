# Week 9 scoring-process supersession v2

This is the authoritative correction for non-offensive scoring process diagnostics. All 54 scores, 108 grades, frozen cohorts, forecasts, confidence, ranks and original v1 files are unchanged. The v1 audit remains the grading authority; its type-only non-offensive summaries are superseded by this separate version.

Provider playType labels the initiating sack, not the resulting defensive fumble-return touchdown. Type-only v1 classification omitted four touchdowns.

The correction requires matching play IDs, the defense as scoring team, clock, post-play scores and fumble-return descriptions in both captured sources. It does not infer a defensive touchdown solely from a final score or a Sack label. Original source fields and raw bytes remain intact.

| Game | Previous events → corrected | Previous points → corrected |
|---|---:|---:|
| Florida @ Georgia | 0 → 1 | 0 → 7 |
| Mississippi State @ Texas | 0 → 1 | 0 → 7 |
| UAB @ South Florida | 0 → 2 | 0 → 14 |

All four events are defensive fumble returns (28 points including bundled conversions); none changes special-teams touchdown counts. FAU–North Texas remains zero non-offensive events and Texas State–Boise remains one event/7 points. These are observed scoring classifications, not counterfactual adjusted finals.

| Corrected subgroup | N | W-L-P | MAE | Bias actual−forecast | -110 units |
|---|---:|---|---:|---:|---:|
| nonoffensive_score | 21 | 12-9-0 | 12.907946 | 2.006651 | 1.909091 |
| no_nonoffensive_score | 33 | 17-16-0 | 11.599107 | 1.200918 | -0.545455 |

Every other Week 9/cross-week result and research conclusion is unchanged. The correction was discovered by inspecting actual scoring descriptions after the initial 885-test CI passed; those earlier runs did not test this semantic correction. New tests and final-head CI are required. Replay with `python -m scripts.week9_scoring_process_v2 --verify`.
