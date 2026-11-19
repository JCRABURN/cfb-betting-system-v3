# Week 11 and season results

**Actual Week 11 submission:** five recovered external-origin records, excluded from v3 grading and weighted points by the owner-confirmed later correction. They are preserved separately, not attributed to independent owner selection.

**Actual cumulative v3 submissions, Weeks 1–10:** 20–30–0, **55/150 weighted points**, -11.82 hypothetical -110 units (-23.64% ROI), 50 picks. ATS 11–19; totals 9–11. The previous 55-pick/165-point v3 denominator is superseded.

**Week 11 recorded full card:** ATS **36–28**; totals **35–29**. Friday contextual five **2–3**, original combined research five **3–2**, governed ATS five **0–5**. The 61-game forward-sealed subset is reported separately below; three late-sealed Wednesday games retain their qualification.

**Root cause and v2.9 priority:** governed ATS uncertainty is null, all 64 confidence ratings collapse to 1, and Top 5 ordering falls through to locked-line IDs. Repair the disclosure of this fallback and prospectively test market-residual forecasting with out-of-sample calibrated ranking across both markets. Do not increase confidence or promote a replacement without validation.

| Frozen cohort | Picks | Wins | Losses | Pushes | Hit rate | Net units | ROI |
|---|---|---|---|---|---|---|---|
| ATS_RESEARCH_TOP5 | 5 | 2 | 3 | 0 | 0.4000 | -1.1818 | -0.2364 |
| ATS_RESEARCH_TOP10 | 10 | 4 | 6 | 0 | 0.4000 | -2.3636 | -0.2364 |
| TOTAL_RESEARCH_TOP5 | 5 | 3 | 2 | 0 | 0.6000 | 0.7273 | 0.1455 |
| TOTAL_RESEARCH_TOP10 | 10 | 4 | 6 | 0 | 0.4000 | -2.3636 | -0.2364 |
| GOVERNED_ATS_TOP5 | 5 | 0 | 5 | 0 | 0.0000 | -5.0000 | -1.0000 |
| ORIGINAL_COMBINED_RESEARCH_TOP5 | 5 | 3 | 2 | 0 | 0.6000 | 0.7273 | 0.1455 |
| HUMAN_20261112-v1 | 5 | 2 | 3 | 0 | 0.4000 | -1.1818 | -0.2364 |
| HUMAN_20261113-v2 | 5 | 2 | 3 | 0 | 0.4000 | -1.1818 | -0.2364 |

| Coverage | Market | N | W | L | P | Net units | Model MAE | Line MAE |
|---|---|---|---|---|---|---|---|---|
| WEEK11_RECORDED64 | ATS | 64 | 36 | 28 | 0 | 4.7273 | 14.3256 | 13.3438 |
| WEEK11_RECORDED64 | TOTAL | 64 | 35 | 29 | 0 | 2.8182 | 12.8269 | 12.5781 |
| WEEK11_FORWARD61 | ATS | 61 | 36 | 25 | 0 | 7.7273 | 14.1776 | 13.4836 |
| WEEK11_FORWARD61 | TOTAL | 61 | 33 | 28 | 0 | 2.0000 | 12.6265 | 12.3361 |
| WEEKS5_11_COMPARABLE400 | ATS | 400 | 204 | 196 | 0 | -10.5455 | 13.1035 | 12.2300 |
| WEEKS5_11_COMPARABLE400 | TOTAL | 400 | 202 | 198 | 0 | -14.3636 | 13.5004 | 12.7350 |
| WEEKS5_11_EXCLUDE_LATE_WEDNESDAY397 | ATS | 397 | 204 | 193 | 0 | -7.5455 | 13.0716 | 12.2431 |
| WEEKS5_11_EXCLUDE_LATE_WEDNESDAY397 | TOTAL | 397 | 200 | 197 | 0 | -15.1818 | 13.4747 | 12.6990 |

Units risk 1 to win 10/11 at hypothetical -110. Pushes return stake and are excluded from hit rate; ROI divides by all stakes. These are hypothetical returns, not actual wagers.

**The model still fails to beat the locked-line baseline on point accuracy in both markets**, for the recorded Week 11 board and the comparable Weeks 5–11 sample. A profitable single full-card week does not establish selection skill.

**No candidate demonstrates credible Top 5 improvement.** The best observed within-market frozen research five was ORIGINAL_POINT_GAUSSIAN totals, 4–1. All four frozen ATS research fives went 2–3, and all four frozen combined fives went 3–2. These are overlapping selections from one week. The 4–1 market-specific list is the predeclared probability ordering applied within totals; the exact separately archived combined lists remain unchanged.

Human review changed the original five from 3-2-0 to 2-3-0, a -1.9091-unit difference. The four removed extreme Unders went 3-1-0; the four added ATS picks went 2-2-0. The shared CSU–WSU Under lost. Excluding those four Unders worsened this week's selection quality.

**Single most important deficiency:** the system has no demonstrated ranking of reliable betting opportunities. Governed ATS ranking collapses to database ID order; research scores turn raw disagreement into an unvalidated confidence signal.

**Highest-priority corrective action:** evaluate a market-anchored residual forecast and common out-of-sample calibration/ranking pipeline prospectively, while keeping v2.8 unchanged. Label fallback Top 5 ordering as unvalidated. Do not raise confidence merely to fill high-confidence buckets.

## Eight decision questions

1. Week 11 taught us that full-board success can coexist with a failed strongest-five process. Governed five lost all five; human changes reduced wins.
2. This week improved cumulative hit rate, but does not establish sustained improvement. The seven-week comparable record remains below hypothetical -110 break-even in both markets.
3. The current model does not beat the locked-line forecast baseline on aggregate MAE/RMSE.
4. The governed Top 5 has no quality signal when uncertainty is absent. Research ranking lacks stable evidence of added value; see cumulative rank and AUC tables.
5. Human review hurt this week. Its small, overlapping historical sample cannot establish a durable benefit or a permanent exclusion policy.
6. Governed confidence is constant, so cannot discriminate. Research ATS uses the same ordinal label with a different uncertainty field. Totals probabilities are uncalibrated; human labels are tentative judgments.
7. Test simple regularized market-residual forecasting first. Add opponent adjustment and pace only after comparable point-in-time feature coverage and drive validation.
8. Confidence 4/5 requires independently validated probabilities, adequate bucket samples, calibration and stability across untouched weeks, and owner-approved policy versioning. A normal CDF or large raw edge is insufficient.

## Scope and limitations

- Week11 submissions originated outside v3 and are excluded per confirmed owner scope.
- Three late-sealed Wednesday games remain qualified.
- No timestamp-qualified closing quotes.
- Human confidence comparable latest-review ledger currently covers Weeks9-11; earlier ordinal/context systems are not pooled.
- Week4 full-card predictions and Week1 full totals forecasts remain missing; actual Weeks1-10 submissions are independently graded.
- Original PDF binaries are not in this checkout; PR54 extraction hashes and provenance are retained, not claimed as a fresh visual PDF verification.
- Postgame personnel/OL/defensive snap shares, measured weather, rivalry labels and causal attribution remain incomplete.
- Multiple overlapping methods, one prospective week and repeated teams limit inference.
- Drive anomalies unresolved in part; no promoted drive features.
- Nine proposed feature families lack a comparable sanctioned PIT feature ledger for validation.

67 original games reconcile across ESPN summary, ESPN scoreboard and CFBD. Three Tuesday games have results only. Three Wednesday predictions are graded with late-custody qualification; they are excluded from forward research. Provider agreement is corroboration, not proof of independent upstream data.

The comparable season table starts at Week 5. Earlier Week 1–3 records are included separately with their original qualifications, and missing weeks are not fabricated. All original screenshots, forecasts, contextual versions and raw provider bytes remain preserved.
