# MASTER PROMPT v2.9 RECOMMENDATIONS — WEEK 5 POSTGAME

**Approve: none.** Master Prompt v2.8 remains active. This task makes no policy or model change. The authoritative v2.8 prompt text is not present in this repository, so its exact current numeric rules cannot be verified. No candidate is represented as an implementable v2.9 replacement without that baseline and out-of-sample evaluation.

| Candidate | Current v2.8 rule | Proposed v2.9 rule and numeric threshold | Week 5 and cumulative evidence | Expected benefit | Overfitting risk | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| Promote shadow totals | Unverified prompt text; current research status SHADOW_ONLY | No change; retain SHADOW_ONLY | Historical OOS 1,897-1,784-38, -1.62% ROI; Week 5 23-33-0 (-21.59% ROI at -110) | None established | High if one week overrides OOS | REJECT |
| Hard cutoff on ATS raw edge ≥7 | Unverified prompt text; current card does not rank by raw edge | No new threshold | 23 Week 5 games 10-13-0 (-17.00% ROI at -110); Week 1 local-draft large edges 10-18-0 (-31.82% ROI at -110); Weeks 2–3 edge cuts unavailable | None established | High from post hoc threshold | REJECT |
| FCS, blowout, QB, opponent strength, market, road-favorite or weather adjustment | Unverified prompt text; no verified v2.8 numeric rule | No numeric change proposed | Week 5 pregame exposure flags and outcomes cannot establish causal coefficient; no walk-forward comparison | Unknown | High | NEED_MORE_DATA |

A future proposal must first locate and freeze the exact v2.8 text, define a numeric candidate and acceptance metric before fitting, then run point-in-time walk-forward validation against the current baseline. The owner must approve any resulting new version.
