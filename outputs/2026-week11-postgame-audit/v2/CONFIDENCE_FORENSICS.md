# Confidence execution-path forensic audit

| Layer | Responsible execution path | Finding |
|---|---|---|
| Governed ATS | `scripts/run_week11_execution.py` calls `business_entities.weekly_controller.run_epa_only_model`; `business_entities.modeling.record_model_prediction` defaults uncertainty to None | EPA point forecast is recorded without governed uncertainty. The separate research estimate never fills this production field. |
| Confidence | `business_entities.ranking.confidence_for_uncertainty`, `UNSCORED_CONFIDENCE=1`; `scripts/finalize_week11_card.py` loads policy configuration | Missing uncertainty becomes 1. Existing thresholds 2,4,6,8 points are not calibrated cover-probability boundaries. Even ~18.3-point shadow uncertainty would remain Confidence1. |
| Governed Top5 | `business_entities.full_card._rank_selections` | Sorts confidence descending, uncertainty ascending, then locked_line_id ascending. All64 have confidence1/null, so first five IDs become the five. Stored rank5 denotes highest, not rank1. |
| Research ATS | `models.epa_uncertainty.EpaUncertaintyArtifact.uncertainty_points`; `config/epa-only-oos-uncertainty-v1.json`; frozen raw components | Residual RMSE18.2796311759 times sqrt(1+1/n+(x-xbar)^2/Sxx) gives nearly constant predictive SD. This is broad margin-error scale, not selection reliability. Research score min(.60,.50+.005*edge) is not calibrated. |
| Totals | `business_entities.totals_weekly_model.run_component_totals_shadow_model`; `business_entities.totals`; `scripts/finalize_week11_card.py` | Normal-CDF probability from projected-minus-line divided by residual SD; slope1; thresholds .55,.60,.70,.80. Large gaps create high confidence without empirical bucket validation. |
| Human context | archived `scripts/review_week11_context.py`, `scripts/review_week11_refresh.py` and Thursday/Friday review.json | 2,2,1,1,1 are cautious ordinal judgments reflecting contradictory matchup evidence and incomplete personnel context. No numeric injury/weather projection adjustments were recorded. |

The null value is a pipeline/policy limitation, not evidence that uncertainty is zero. Replacing it with the shadow scale alone would not create a meaningful ordering. A large homoskedastic residual scale can be statistically plausible while being almost useless for ranking which side covers.

| Scope | Layer | Confidence | N | W | L | Hit rate | Units | Mean edge | MAE points | Estimated uncertainty | Wilson95 | Weeks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WEEK11_RECORDED64 | GOVERNED_ATS | 1 | 64 | 36 | 28 | 0.5625 | 4.7273 | 3.9590 | 14.3256 | Unavailable | [0.440862, 0.67706] | 1 |
| WEEK11_RECORDED64 | GOVERNED_ATS | 2 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_RECORDED64 | GOVERNED_ATS | 3 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_RECORDED64 | GOVERNED_ATS | 4 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_RECORDED64 | GOVERNED_ATS | 5 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_RECORDED64 | RESEARCH_ATS | 1 | 64 | 36 | 28 | 0.5625 | 4.7273 | 3.9590 | 14.3256 | 18.2834 | [0.440862, 0.67706] | 1 |
| WEEK11_RECORDED64 | RESEARCH_ATS | 2 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_RECORDED64 | RESEARCH_ATS | 3 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_RECORDED64 | RESEARCH_ATS | 4 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_RECORDED64 | RESEARCH_ATS | 5 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_RECORDED64 | TOTALS | 1 | 23 | 13 | 10 | 0.5652 | 1.8182 | 0.8829 | 13.0096 | 16.7536 | [0.368114, 0.743654] | 1 |
| WEEK11_RECORDED64 | TOTALS | 2 | 21 | 10 | 11 | 0.4762 | -1.9091 | 2.9333 | 12.4616 | 16.7536 | [0.28344, 0.676305] | 1 |
| WEEK11_RECORDED64 | TOTALS | 3 | 14 | 8 | 6 | 0.5714 | 1.2727 | 6.4404 | 13.5109 | 16.7536 | [0.325906, 0.786192] | 1 |
| WEEK11_RECORDED64 | TOTALS | 4 | 2 | 1 | 1 | 0.5000 | -0.0909 | 10.8844 | 15.8844 | 16.7536 | [0.094531, 0.905469] | 1 |
| WEEK11_RECORDED64 | TOTALS | 5 | 4 | 3 | 1 | 0.7500 | 1.7273 | 18.4343 | 9.7712 | 16.7536 | [0.300642, 0.954413] | 1 |
| WEEKS5_11_COMPARABLE400 | GOVERNED_ATS | 1 | 400 | 204 | 196 | 0.5100 | -10.5455 | 4.5191 | 13.1035 | Unavailable | [0.461149, 0.558661] | 7 |
| WEEKS5_11_COMPARABLE400 | GOVERNED_ATS | 2 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS5_11_COMPARABLE400 | GOVERNED_ATS | 3 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS5_11_COMPARABLE400 | GOVERNED_ATS | 4 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS5_11_COMPARABLE400 | GOVERNED_ATS | 5 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS5_11_COMPARABLE400 | RESEARCH_ATS | 1 | 400 | 204 | 196 | 0.5100 | -10.5455 | 4.5191 | 13.1035 | 18.2839 | [0.461149, 0.558661] | 7 |
| WEEKS5_11_COMPARABLE400 | RESEARCH_ATS | 2 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS5_11_COMPARABLE400 | RESEARCH_ATS | 3 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS5_11_COMPARABLE400 | RESEARCH_ATS | 4 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS5_11_COMPARABLE400 | RESEARCH_ATS | 5 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS5_11_COMPARABLE400 | TOTALS | 1 | 146 | 81 | 65 | 0.5548 | 8.6364 | 1.0767 | 11.8668 | 16.7322 | [0.473802, 0.632977] | 7 |
| WEEKS5_11_COMPARABLE400 | TOTALS | 2 | 116 | 61 | 55 | 0.5259 | 0.4545 | 3.0626 | 11.7739 | 16.7320 | [0.43563, 0.614436] | 7 |
| WEEKS5_11_COMPARABLE400 | TOTALS | 3 | 114 | 50 | 64 | 0.4386 | -18.5455 | 6.0709 | 16.0790 | 16.7294 | [0.350984, 0.530213] | 7 |
| WEEKS5_11_COMPARABLE400 | TOTALS | 4 | 17 | 6 | 11 | 0.3529 | -5.5455 | 10.3891 | 21.2566 | 16.7294 | [0.173097, 0.586996] | 7 |
| WEEKS5_11_COMPARABLE400 | TOTALS | 5 | 7 | 4 | 3 | 0.5714 | 0.6364 | 17.8011 | 15.3508 | 16.7470 | [0.250458, 0.84178] | 3 |
| WEEK11_LATEST_REVIEW | HUMAN_CONTEXTUAL | 1 | 3 | 1 | 2 | 0.3333 | -1.0909 | 9.5581 | 16.9442 | 18.2842 | [0.061492, 0.79234] | 1 |
| WEEK11_LATEST_REVIEW | HUMAN_CONTEXTUAL | 2 | 2 | 1 | 1 | 0.5000 | -0.0909 | 10.6547 | 15.6547 | 17.5178 | [0.094531, 0.905469] | 1 |
| WEEK11_LATEST_REVIEW | HUMAN_CONTEXTUAL | 3 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_LATEST_REVIEW | HUMAN_CONTEXTUAL | 4 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEK11_LATEST_REVIEW | HUMAN_CONTEXTUAL | 5 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS9_11_LATEST_REVIEW_PER_WEEK | HUMAN_CONTEXTUAL | 1 | 6 | 3 | 3 | 0.5000 | -0.2727 | 9.8043 | 14.1514 | 17.7696 | [0.187616, 0.812384] | 3 |
| WEEKS9_11_LATEST_REVIEW_PER_WEEK | HUMAN_CONTEXTUAL | 2 | 9 | 3 | 6 | 0.3333 | -3.2727 | 11.2835 | 16.4502 | 17.7707 | [0.120584, 0.645798] | 3 |
| WEEKS9_11_LATEST_REVIEW_PER_WEEK | HUMAN_CONTEXTUAL | 3 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS9_11_LATEST_REVIEW_PER_WEEK | HUMAN_CONTEXTUAL | 4 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |
| WEEKS9_11_LATEST_REVIEW_PER_WEEK | HUMAN_CONTEXTUAL | 5 | 0 | 0 | 0 | Unavailable | 0.0000 | Unavailable | Unavailable | Unavailable | [None, None] | 0 |

| Scope | Market | N | Edge ranking AUC |
|---|---|---|---|
| WEEK11_RECORDED64 | ATS | 64 | 0.3323 |
| WEEK11_RECORDED64 | TOTAL | 64 | 0.4946 |
| WEEKS5_11_COMPARABLE400 | ATS | 400 | 0.5065 |
| WEEKS5_11_COMPARABLE400 | TOTAL | 400 | 0.4319 |

AUC below .5 means higher scores tended to identify losers within this sample. It is descriptive, not an invitation to reverse picks retrospectively. Exact edge buckets and all confidence levels, including zero-case buckets, appear in the CSVs. No claim of monotonic improvement is warranted from these samples. Human revisions are not counted as independent observations; cumulative human calibration uses the latest archived review per covered week.
