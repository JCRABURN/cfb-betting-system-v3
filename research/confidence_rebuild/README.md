# Confidence and predictive accuracy rebuild — RESEARCH ONLY

The strongest five have **not demonstrated a reliable improvement**. The controlled
logistic ranking is a candidate for further observation, not promotion: combined
Top 5 improves from 9–11 (−2.82 units) to 12–8 (+2.91) in this retrospective
chronological replay, but the sample is four weeks, calibration fails the proposed
gates, and selection membership is unstable. No candidate earns Confidence 3–5.

This is a narrow research PR based on main `abb4eb26bd1140e66972d2f1143cd587e80960b4`.
It does not integrate the cumulative PR backlog. Audit inputs are exact Git blobs
from PR #48 commit `950df28202ee01c3cb1a11777170cdba628a0cfe`; Week 10 comes from
PR #49 commit `5823b6dd2d0321fd91ad1a8ce474b192fd21c9c1`.

## Boundaries and chronology

The input pack contains 279 historical games (56/58/59/52/54 for Weeks 5–9),
each with ATS and totals, plus 57 sealed Week 10 games with **no outcomes**.
Weeks 6–9 provide 223 evaluation games per market. Each fit uses only earlier
weeks; Week 5 seeds training. Feature scaling, regression, uncertainty estimation,
classification and empirical interval radii are fitted inside that boundary.
No evaluation-week feature distributions enter training. Each original prediction
timestamp precedes kickoff, and prior training kickoffs precede the test card.

Historical outcomes were already known when this program was designed. The protocol
was committed before this evaluation ran, but **this is not historical preregistration
or untouched prospective evidence**. All seven candidates are reported. No parameter,
threshold or candidate was selected after inspecting these results. Week 5 is included
in descriptive confidence diagnostics, never counted as an evaluation fold.

The separate prospective Week 10 shadow was generated at
`2026-11-06T00:15:50.408748+00:00`, before the earliest `00:30 UTC` kickoff, with
source commit `46fe7652baafc9c61f6c7234e6d1d6661fbe257f`. It covers all 57 games,
798 rows across seven candidates and two markets. Commit
`15b84e40e70a6c9876b9888659db32ee7b5fe641` preserved and pushed it before kickoff;
GitHub PR #50 was created at `00:18:54 UTC`. Later reporting/verification additions
are not its generating source. This shadow does not change a contest recommendation,
authorize a wager, or confer owner approval. Do not overwrite or refit it after kickoff.

## Findings and causes

1. **Governed ATS confidence is an explicit fallback.** Archived
   `business_entities/weekly_controller.py` supplies `uncertainty_points=None`;
   `confidence_for_uncertainty` returns 1 when uncertainty is absent. All 279
   historical ATS picks are 1/5 (142–137, 50.90%, −7.91 units). A separate shadow
   uncertainty and edge score do not supply validated governed uncertainty.
   Making the labels larger would not solve this missing calibration.
2. **Totals confidence ranks model disagreement, not demonstrated reliability.**
   The raw selected probability uses a normal-error calculation and forecast gap;
   its confidence mapping is unvalidated. Across Weeks 5–9, Confidence 1 is
   56–47 (54.37%), 2 is 41–33 (55.41%), 3 is 39–51 (43.33%), 4 is 5–6,
   and 5 is 0–1. Confidence 4/5 have too few cases for useful individual conclusions.
   In evaluation weeks the frozen totals score has AUC 0.4563, versus ATS 0.5667.
   These are discrimination measures, not calibrated win probabilities.
3. **The model moves away from a stronger forecast baseline.** Evaluation ATS
   MAE/RMSE are 12.259/15.094 versus locked-line 11.545/14.276; totals are
   13.089/16.560 versus 12.652/16.000. Model-minus-line MSE is +24.016 ATS
   and +18.209 totals. The identity `gap² − 2*gap*(actual−line)` shows that
   displacement is not compensated by enough alignment with market residuals.
   Totals bias, actual minus prediction, is +2.062 points versus +0.684 for the
   line. This identifies forecasting underperformance, not which omitted input caused it.
4. **The cumulative inputs cannot resolve all game-specific changes.** Exact
   archived prior-week success, PPA, rushing rate, explosiveness and plays/drives
   are available. Plays per drive measures drive length; it is **not pace,
   seconds per play or expected possessions**. There is no complete, timestamped
   game-level QB/backup, OL injury/start, defensive-availability or coaching dataset
   in these inputs. Missing personnel features remain `UNAVAILABLE_NOT_IMPUTED`.
   We cannot estimate their independent causal effects or invent numerical adjustments.
5. **Edge does not become consistently useful after controls.** The controlled
   logit uses edge/sigma, log sigma, absolute line and selected direction. ATS
   edge coefficients change from −0.189 in the first fold to +0.155 in the last;
   totals coefficients remain negative (−0.080 to −0.185). Controlled OOS AUC is
   only 0.5209 ATS and 0.5129 totals, and Brier is 0.2583/0.2607 versus prior-only
   smoothed base-rate 0.2555/0.2558. Conditional uncertainty gives AUC
   0.5269/0.4931. Penalized coefficients are descriptive; they are not injury
   valuations, independent significance tests, or proof of a profitable edge.

## Candidate results and the strongest five

Full tables, reliability bins, uncertainty intervals, per-fold metrics, rank 1–5,
6–10 and 11–rest cohorts, coefficients and bootstrap frequencies are in
[TABLES.md](TABLES.md), [results.json](results/v1/results.json),
[supplement.json](results/v1/supplement.json) and the adjacent CSV files.

| Candidate | ATS full card W–L / units | Totals full card W–L / units | Combined five W–L / units |
| --- | --- | --- | --- |
| Frozen v2.8 research ordering | 108–115 / −16.82 | 118–105 / +2.27 | 9–11 / −2.82 |
| Fixed 25% model + 75% line | 108–115 / −16.82 | 118–105 / +2.27 | 9–11 / −2.82 |
| Edge logit | 108–115 / −16.82 | 118–105 / +2.27 | 8–12 / −4.73 |
| Controlled logit | 108–115 / −16.82 | 118–105 / +2.27 | 12–8 / +2.91 |
| Conditional uncertainty logit | 108–115 / −16.82 | 118–105 / +2.27 | 11–9 / +1.00 |
| Market-residual ridge | 104–119 / −24.45 | 111–112 / −11.09 | 11–9 / +1.00 |

All returns are hypothetical: risk 1 unit to win 10/11, no pushes in these
evaluation samples. The locked line is a forecasting baseline, not a wager; it
has no side, hit rate or betting ROI. Its 0.5 Brier comparator is evaluated on
the existing frozen selection labels. Original scores scored as probabilities
are expressly uncalibrated. Classifier candidates retain original sides, so
only their ordering and probability assessments can improve betting selection.

Fixed 25% shrinkage reduces ATS MAE to 11.516 and totals to 12.696. It does
**not change sides or ranks**, therefore cannot improve hit rate or Top 5 returns.
Its ATS MAE advantage over the line is only 0.029 points, with four-week block
95% difference interval [−0.106, +0.067]; it does not establish superior forecasting.
The residual ridge candidate reduces original-model error but remains worse than
the line in both markets and loses units across each full card. Its totals five
is 14–6 (+6.73), an exploratory small-cohort result, not evidence to deploy it.

The controlled candidate's combined gain is +5.73 units. The exact four-week
block resampling interval is [+1.91, +7.64], **not adjusted for trying multiple
candidates**. Only four distinct weeks generate that interval; repeated teams,
season effects and research selection make it optimistic as a generalization claim.
Its absolute 12/20 hit-rate Wilson95 interval is 38.66%–78.12%. Its combined
membership-bootstrap mean Jaccard falls from 0.663 in Week 7 to 0.346/0.420 in
Weeks 8/9. Week 6's 1.0 stability is degenerate: only one training-week cluster
exists. Membership stability ignores side changes for residual ridge; that result
is an upper bound on exact-pick stability, and cannot certify the promotion gate.

The frozen ATS **research** five is 13–7 (+4.82), totals research five 9–11
(−2.82), and governed ATS five 8–12 (−4.73). They are distinct cohorts. The
combined five's uncalibrated score comparison selects totals in all four folds.
Original combined ordering is checked against separate archived CSVs for Weeks
5–10. Week 5/6 per-market research ranks are explicitly derived orders of
pregame fields; they are not silently represented as archived rank columns.

## Candidate uncertainty and calibration methods

The implemented uncertainty ridge predicts absolute prior forecast error from
line size, model edge, drive-length proxy, offensive success and defensive
explosiveness. Convert predicted MAE to sigma using `sqrt(pi/2)` and clip to
5–60 points. This normal-shape conversion is an assumption, not an empirical
probability guarantee. Classifier training uses fixed-design leave-one-out
uncertainty predictions; scaling is fitted only within the prior training data.
The conditional candidate's 80/90% observed coverage is 82.96/95.52% ATS and
81.17/93.72% totals. Coverage alone does not establish usefulness; interval widths
are also reported. No exchangeability or conformal-coverage guarantee is claimed.

Ridge penalty 20, logistic penalty 10, 30 Newton iterations, fixed 25% shrinkage,
probability clipping 0.01–0.99 and all probability bins were declared before this
evaluation. There is no hyperparameter search on Weeks 6–9. No new dependency is
introduced. The small deterministic estimators are research implementations and
require independent numerical review before any production consideration.

Next research data collection should record pregame QB expected/actual starter
evidence, backup snap history, returning OL starts and confirmed absences,
defensive personnel availability, situation-neutral seconds/play, drives/game,
explosive rush/pass rates and coaching transitions with effective timestamps.
Use an explicit missingness state and abstain from assigning personnel-based
numerical effects until timestamp-safe training data exist. Compare feature
ablations chronologically against the same baselines; do not backfill current
knowledge into past predictions. This proposal adds no made-up adjustment.

## Proposed gates before Confidence 3, 4 or 5

These are **RESEARCH ONLY acceptance proposals**, not a replacement for v2.8.
Bucket cases must be untouched prospective evaluations with frozen probabilities.

| Label | Calibrated predicted p floor | Minimum decided cases / weeks | Required 95% Wilson lower bound | Wins needed at minimum n |
| --- | --- | --- | --- | --- |
| 3 | 0.55 | 500 / 8 | >52.38095% | at least 284/500 |
| 4 | 0.60 | 500 / 12 | >55% | at least 297/500 |
| 5 | 0.65 | 800 / 16 | >60% | at least 508/800 |

Additionally require at least 100 prospective combined Top 5 selections over
20 weeks and two seasons; positive absolute Top 5 return; paired improvement
lower95 >0; AUC lower95 >0.5; ECE ≤0.03; Brier better than prior-only base rate;
median exact-selection stability Jaccard ≥0.6; forecast MAE and RMSE no worse
than the locked line. Use cluster-aware validation and multiplicity control
for a declared primary candidate; a naive Wilson bound alone is insufficient.
All gates, completed formal governance, independent review, owner approval and
a new policy version are required. No current candidate qualifies.

Probability calibration and discrimination are separate objectives; Brier/log
loss also reflect overall prediction quality. See the primary
[calibration documentation](https://scikit-learn.org/stable/modules/calibration.html)
and [chronological split documentation](https://scikit-learn.org/1.7/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).
These references explain evaluation principles; this implementation uses only
the Python standard library and does not claim sklearn estimator equivalence.

## Reproduction, custody and limitations

Run from the repository root with its pinned development environment:

```text
python -m research.confidence_rebuild.verify
python -m research.confidence_rebuild.cohorts
python -m research.confidence_rebuild.run --output research/confidence_rebuild/results/v1 --verify
python -m research.confidence_rebuild.supplement --verify
python -m research.confidence_rebuild.tables --verify
python -m pytest tests/test_confidence_research.py -q
python scripts/verify_repo_safety.py
python -m scripts.verify_migrations
python -m scripts.verify_cloud_migrations
python -m pytest -q
```

Input seal SHA256 is `ee8ee179bdfc20f1445ed082da64bb25e618ea3aca0dc631cec820e945302bf6`;
holdout SHA256 is `592b564798c434846ce169728aa3d0a4fd1b112d5397e587d40703ce2e58c23c`;
results SHA256 is `b75ea996a75d3ac502418f69455f482bc11cf160d2d1605e688cd1797eb57624`.
Source gzip payloads preserve exact Git blob bytes and separately record their
uncompressed SHA256. No historical checkout bytes or expected hashes are changed.
Derived research metrics use 10 decimal places for deterministic comparison;
this convention never relaxes original-source or holdout byte-integrity checks.

No live sports provider calls, database writes, model imports, migrations,
operational workflow changes, or new runtime dependencies occur. CLV remains
INCOMPLETE; a locked contest line is not a qualified market close. The data
cannot establish injury causality, a true possessions model, independent
multi-season performance, or prospective profit. These limitations are findings.

Changes are confined to this research namespace, its tests and additive research
`.gitattributes` rules. Existing application files, historical artifacts,
Week 10 seal, source database and v2.8 are preserved. Rollback is to close this
unmerged PR; after any separately authorized merge, revert the research commits
without touching source evidence. No schema rollback is necessary.

See [VERIFICATION.md](VERIFICATION.md) for exact tested commits, environments,
commands, CI failures and independent-review status. HOLD until applicable CI
and review gates pass; research completion does not approve betting selections.
