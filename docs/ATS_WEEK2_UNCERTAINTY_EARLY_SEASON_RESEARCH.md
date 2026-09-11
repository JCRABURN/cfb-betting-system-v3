# Week 2 ATS uncertainty repair and early-season support research

## Scope and status

This amendment changes only the missing ATS reliability input and its official
publication gate. It does not change `epa-only-linear-v1`, locked Week 2 lines,
Confidence thresholds, ranking order, selection rules, totals logic, or any
production schedule. The Week 2 replay remains **provisional and not
publishable** because the separate early-season feature-support defect is not
activated or repaired here.

## Governed uncertainty

No governed production ATS uncertainty artifact existed. The shadow selected-
side calibration is a different product and is not used. The new
`epa-oos-predictive-uncertainty-v1` artifact is rebuilt from 3,714 exact,
unrounded 2020--2025 rolling-origin forecasts produced by the frozen baseline.
Each season is fit only on earlier seasons; each target feature is the latest
`cfbd_point_in_time` snapshot strictly before kickoff week; ATS eligibility
requires a genuine historical opener.

The residual ledger has SHA-256
`7cc76abf69fccb966235c74b38dda4824f974b566b00e75d766439e6ba376d91`,
OOS RMSE 18.279631175886248 points, residual bias (actual minus prediction)
0.724741171467257 points, feature mean 0.007709117029612803, and feature Sxx
262.25572267407097. For target feature `x`, predictive uncertainty is:

```text
18.279631175886248 * sqrt(
    1 + 1/3714 + (x - 0.007709117029612803)^2 / 262.25572267407097
)
```

This is the standard one-feature prediction-leverage form with a frozen OOS
residual scale. It does not use the locked line, raw ATS edge, Week 2 outcome,
or a selected-side probability. It is not claimed to be empirically calibrated
ATS probability.

Every prediction records exact feature `x`, uncertainty, policy and formula
versions, artifact checksum, and residual-ledger checksum. Artifact absence or
checksum drift stops the run. Migration 23 separately prevents a future
official publication with null/nonpositive uncertainty on a model-backed Top-5
pick.

## Order invariance

The exact 49-game card was run in five independent disposable database copies:
natural lock order, reverse lock order, deterministic shuffled order, reversed
game-ID assignment, and seven inserted rows of database-identity padding.
Margins, uncertainties, selected sides, Confidence, ranks, and Top-5 membership
were identical by semantic matchup. Locked-line IDs differed as intended. The
existing Confidence and ranking policy was not changed.

## Historical Weeks 2--4 comparison

The historical archive contains 834 completed target games in 2020--2025. Of
those, 799 have eligible PIT EPA features; all 21 eligible 2020 forecasts lack
an opening line, leaving 778 ATS-graded forecasts. There are 3,196 candidate
rows: control plus the three predefined fixed-prior weights. Prior-season EPA
was available for 1,581 of 1,598 team observations per fixed candidate; the 17
missing priors explicitly use current-only EPA. Offensive and defensive play
counts are not stored, so K=50/100/200 sample-size candidates are not evaluated
and no proxy is manufactured.

| Candidate | N | MAE | RMSE | Bias | ATS W-L-P | Win% | ROI | >30 | >40 | abs(z)>=3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Current production | 799 | 16.97 | 21.86 | -2.50 | 391-372-15 | 51.25% | -2.13% | 6.51% | 2.38% | 7.38% |
| 25% current / 75% prior | 799 | 15.27 | 19.32 | -2.50 | 384-379-15 | 50.33% | -3.85% | 0.25% | 0.00% | 0.25% |
| 50% current / 50% prior | 799 | 15.32 | 19.49 | -2.50 | 385-378-15 | 50.46% | -3.60% | 1.25% | 0.25% | 0.75% |
| 75% current / 25% prior | 799 | 15.87 | 20.36 | -2.50 | 379-384-15 | 49.67% | -5.08% | 3.13% | 0.88% | 3.00% |

The 25/75 candidate reduces RMSE in every included season relative to control.
Its aggregate ATS decrease is not statistically distinguishable on paired side
changes: 87 candidate-right versus 94 control-right, McNemar p=0.656. ATS ROI
is therefore not the promotion basis.

| Target week | Control MAE/RMSE | 25/75 MAE/RMSE | 50/50 MAE/RMSE | 75/25 MAE/RMSE |
|---|---:|---:|---:|---:|
| Week 2 | 19.24 / 25.23 | 15.04 / 19.03 | 15.57 / 20.03 | 16.97 / 22.20 |
| Week 3 | 17.70 / 22.21 | 17.02 / 21.29 | 16.80 / 21.08 | 16.99 / 21.39 |
| Week 4 | 14.51 / 18.37 | 13.93 / 17.67 | 13.83 / 17.50 | 14.01 / 17.74 |

Season-level control versus 25/75 RMSE is: 2020 33.51/23.73, 2021
23.41/18.74, 2022 21.00/18.43, 2023 18.37/17.04, 2024 22.64/21.15,
and 2025 21.68/20.50. The candidate therefore improves forecast stability
across every season represented, not merely in aggregate.

## Extreme and opponent-support diagnostics

For current production, forecast MAE/RMSE rises from 16.97/21.86 overall to
22.21/28.65 at abs(z)>=2 (N=144), 24.74/31.34 at abs(z)>=3 (N=59), and
30.84/40.59 at abs(z)>=4 (N=19). High-z ATS results are not evidence of margin
calibration and are too small to justify aggressive probabilities.

Prior-sample opponent support is materially associated with error. The control
rows classified FBS have N=629 and MAE/RMSE 15.84/19.81. Rows with at least one
FCS prior opponent have N=161 and MAE/RMSE 20.46/27.40; 22.98% have abs(z)>=3.
Unknown support has N=9 and is not decision-grade. This is evidence for a
support problem, not authorization for an FCS penalty.

On the current Week 2 card, control produces 8 absolute margins above 30, 6
above 40, and 11 abs(z)>=3 observations. Research-only 25/75 produces 0/0/0;
50/50 produces 1/0/1; 75/25 produces 4/1/3. No variant is activated.

Georgia Southern at Clemson illustrates the mechanism. Clemson's one-game net
EPA is -0.86585 after facing LSU; Georgia Southern's is +0.71094 after facing
FCS Charleston Southern. Their unadjusted difference is -1.57679 (z=-5.94),
which contributes -55.33 points; adding the 3.80660 intercept yields -51.52.
App State at East Carolina is the same failure mode: App State's +0.73103 net
EPA after FCS Maine versus ECU's -0.53359 after Alabama produces x=-1.26462
(z=-4.77), a -44.37 coefficient contribution, and -40.57 after intercept.
Both values are mathematically consistent with the code but not football-
comparable without an early-season support policy.

## Research recommendation

**FIXED PRIOR SHRINKAGE CANDIDATE**, specifically the pre-registered 25%
current / 75% prior candidate, has the strongest forecast-error and pathology
evidence. This is a research recommendation only. Owner approval, a new model
or feature-policy version, implementation tests, and a separate pull request
are required before activation.

## SQLite custody recommendation

`data/cfb.db` was first added in commit
`a6463de76bc3fa5277950de7431560eb66d6f62e`. Commit `7b40a08` first added the
governed Week 2 binary snapshot; `c7b621a` replayed the same row counts with
approved policy custody and final timestamps/checksums.

The Week 2 snapshot contains 49 Week 2 game rows, 138 provider acceptances and
138 `cfbd_point_in_time` Week 1 team rows (plus 396 legacy `cfbd` rows), 49
locks, 49 ATS predictions/picks, 49 total predictions/candidates/components, 49
ATS shadow calibration evaluations, one official card/publication/controller
run, one totals shadow card/run, five freshness rows, and the related policy,
assignment, completion, and manifest rows. It contains no unified Top-5 run.

Those inputs are reconstructible from the immutable Week 2 manifest, the
checksummed CFBD Week 1 replay bundle/raw payload, and the governed execution
script. The older architecture intentionally committed SQLite for persistence,
but the current cloud architecture makes managed PostgreSQL snapshot history
authoritative and materializes SQLite into an ephemeral runner. Git-tracking a
feature-branch runtime snapshot duplicates durable state, produces opaque
binary conflicts, and can diverge from the PostgreSQL stream. Recommendation:
**DO NOT MERGE TRACKED DB CHANGE**. This task does not delete or rewrite it.

## Rollback

Revert the uncertainty module/artifact integration and migration 23 before it
is applied. If migration 23 has been applied to a disposable or future runtime
snapshot, recovery is forward-only: add a reviewed migration removing the
trigger. Existing committed cards and database rows are never rewritten.
