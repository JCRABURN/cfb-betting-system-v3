# 2026 Week 7 evaluation

Corrected owner-approved contest five: **2 wins, 3 losses, 0 pushes (40%)**.

All 59 locked matchups have final scores; all 59 ATS and 59 totals selections are graded against the corrected immutable contest lines. Formal audit remains **INCOMPLETE — CLV CUSTODY**.

## Owner-approved five

| Selection | Final (away–home) | Result | Cover margin | Human confidence |
|---|---|---|---:|---:|
| Air Force +1.5 | UNLV 31–41 Air Force | WIN | +11.5 | 3/5 |
| Indiana +3.5 | Ohio State 19–15 Indiana | LOSS | -0.5 | 3/5 |
| Georgia State +12.5 | Georgia State 22–49 James Madison | LOSS | -14.5 | 3/5 |
| Nebraska +7.5 | Nebraska 14–17 Oregon | WIN | +4.5 | 2/5 |
| Colorado State–Texas State UNDER 69.5 | Colorado State 27–66 Texas State | LOSS | -23.5 | 2/5 |

## Frozen cohort comparison

| Cohort | W–L–P | Win rate, pushes excluded | Hypothetical units at -110 |
|---|---:|---:|---:|
| owner_approved_five | 2–3–0 | 40.0% | -1.18 |
| governed_v28_top5 | 3–2–0 | 60.0% | +0.73 |
| ats_full | 26–33–0 | 44.1% | -9.36 |
| ats_research_top5 | 3–2–0 | 60.0% | +0.73 |
| ats_research_top10 | 5–5–0 | 50.0% | -0.45 |
| ats_research_remaining54 | 23–31–0 | 42.6% | -10.09 |
| total_full | 33–26–0 | 55.9% | +4.00 |
| total_research_top5 | 2–3–0 | 40.0% | -1.18 |
| total_research_top10 | 4–6–0 | 40.0% | -2.36 |
| total_research_remaining54 | 31–23–0 | 57.4% | +5.18 |
| legacy_mixed_research_top5 | 2–3–0 | 40.0% | -1.18 |
| human_review_candidate_board | 7–5–0 | 58.3% | +1.36 |

## What the results support

Indiana was a half-point ATS loss: a four-point defeat against +3.5. Air Force won outright by 10; Nebraska covered in a three-point defeat. Georgia State missed its line by 14.5 points. The Under missed by 23.5 points: 93 actual points versus a 59.345 projection, a 33.655-point forecast error. The original erroneous Under 72.5 would also have lost; correcting it to 69.5 did not change that outcome.

Compare each research Top 5/Top 10 only with its own market. The owner five, governed five, legacy mixed five and human candidate board are distinct frozen selections. The legacy mixed score has no validated common probability scale. Human confidence 3 went 1–2; confidence 2 went 1–1. These small samples do not establish calibrated reliability.

ATS research Top 5 went 3–2 versus 23–31 for the remaining 54. Totals research Top 5 went 2–3 versus 31–23 for the remaining 54; its Top 10 went 4–6. The totals scores did not concentrate winners at the top this week. ATS rank-band results were also not monotonic. The human five omitted Massachusetts (loss) and Syracuse (win) from the ATS research five and added Georgia State (loss) and Under 69.5 (loss), finishing one win behind that ATS cohort. This is a descriptive comparison, not proof that contextual review helps or hurts generally.

## Forecast and ranking diagnostics


### ATS

MAE 11.951; RMSE 14.741; actual-minus-forecast mean +0.093 points.

| Pregame research rank | W–L–P |
|---|---:|
| 1-5 | 3–2–0 |
| 6-10 | 2–3–0 |
| 11-20 | 5–5–0 |
| 21-40 | 7–13–0 |
| 41-59 | 9–10–0 |

### TOTAL

MAE 12.940; RMSE 15.611; actual-minus-forecast mean +1.265 points.

| Pregame research rank | W–L–P |
|---|---:|
| 1-5 | 2–3–0 |
| 6-10 | 2–3–0 |
| 11-20 | 7–3–0 |
| 21-40 | 12–8–0 |
| 41-59 | 10–9–0 |

Full diagnostics JSON includes favorites/underdogs, home/away/neutral, spread buckets, road favorites, confidence, Top 5 versus remainder, raw versus adjusted results, and explicit missing CLV comparisons. Raw projections and separately frozen numeric adjustments were preserved. No new model run or retrospective rank was generated.

## Custody and limitations

- CLV and key-number crossing unavailable: no timestamp-qualified pre-kickoff close captured.
- Backdoor classifications not evaluated; final scores alone are insufficient.
- Scoreboard and game summaries share ESPN as provider; no full-card independent-provider reconciliation.
- Research scores are uncalibrated; Brier/log loss are descriptive only; one week cannot validate ranking.
- All units and ROI assume hypothetical one-unit risk at -110; no wager prices, stakes, or realized profits are asserted.
- Twelve overlapping cohorts are comparisons, not twelve independent samples; human review is selection, not a numeric adjustment.
- Governed ATS confidence is uniformly 1 with missing uncertainty; its Top 5 is not evidence of reliability discrimination.

Verified 89 original sealed outputs, 96 corrected sealed outputs and 14 source files; owner-approval hash, pregame timestamps, result-free inputs, distinct game IDs, complete coverage and confidence bounds. Source DB opened read-only: integrity OK, zero foreign-key violations, SHA-256 unchanged before/after.

**Decision: hold existing model and policy versions.** CLV custody is incomplete, so this evaluation does not satisfy the completed-audit gate for a policy proposal. One week's results do not establish profitability or justify a new ranking rule.

## Reproduce

Run `python -m scripts.build_week7_postgame_audit --verify` offline. The verifier recomputes every table and diagnostic and checks all output hashes. Initial capture is separate: `python -m scripts.capture_week7_postgame_evidence`; it refuses to replace an existing capture. Initial generation: `python -m scripts.build_week7_postgame_audit`.

ESPN game URLs and raw-summary SHA-256 values are in the results and per-pick ledgers; compressed exact payloads and request timestamps are in provider-evidence. Postgame provider-labeled closes remain separate observations and never replace contest lines.
