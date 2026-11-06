# Week 6 2026 formal post-week audit

## Executive verdict

**C — Ranking/calibration is materially broken for the Top-5 objective.** The governed ATS Top 5 went 0-5-0 (N=5; 0.0% W ex-push), while the full ATS card went 28-30-0 (N=58; 48.3% W ex-push). The governed five were simply the first five locked games, with no strength ordering and Confidence 1 on every ATS game. The separate mixed shadow Top 5 went 1-4-0 (N=5; 20.0% W ex-push); all five were totals because 25 totals scores exceeded the best ATS score. These observations do not establish that the EPA margin model is structurally broken; they directly indict the current selection and cross-market score custody. No timestamp-qualified closing lines were available, so true CLV and a process-quality verdict remain unresolved.

**Operational recommendation: PATCH the Top-5 governance and develop/test v2.9 offline before any owner-approved cutover. Keep v2.8 frozen until a separately reviewed policy change passes prior-week walk-forward evaluation.** The Week 6 card was a local governed draft, and the totals/mixed board was shadow, not a sportsbook recommendation.

## Frozen evidence and scope

- Model-run commit: `27e230225c6f46ecce9c840dc770efb276e4daf8`; later PR #34 review packaging merged as `abb4eb26bd1140e66972d2f1143cd587e80960b4`. The latter is not a model rerun.
- ATS model `epa-only-linear-v1`; totals model `pit-epa-component-total-linear-v1`; frozen generation `2026-10-06T22:02:22.889083+00:00` UTC.
- Locked-line domain SHA-256 `f2723f75d94c2c3e4edaadf618cbb71866f3cf2d8b59c62fe48ab84bad6c2c75`; source database SHA-256 `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.
- 41/41 sealed pregame files verified; 58 ATS candidates, 0 skips; 58 totals candidates, 0 skips; 116 combined selections.
- Governed ATS Top 5, in stored order: Southern Miss +10.5; Jacksonville State -2.5; New Mexico State +6.5; Sam Houston +13.5; Missouri State +2.5.
- Current v2.8 master prompt is cited in prior audit but its full authoritative numeric rule text is not checked into this repository; proposed exact policy deltas require that baseline.

## Full-card performance

ATS **28-30-0 (N=58; 48.3% W ex-push)**, totals **33-25-0 (N=58; 56.9% W ex-push)**, combined **61-55-0 (N=116; 52.6% W ex-push)**. These are hypothetical selections against immutable contest lines, not verified sportsbook bets or real ROI. The CSVs `week6_ats_audit.csv` and `week6_totals_audit.csv` contain every graded selection, including all losses, score, line, projection, confidence, ranking, hook, and evidence pointers.

### ATS favorite/dog

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| FAVORITE | 9-15-0 | 37.5% | 24 | 21.2–57.3% |
| UNDERDOG | 19-15-0 | 55.9% | 34 | 39.5–71.1% |

### ATS home/away

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| AWAY | 14-17-0 | 45.2% | 31 | 29.2–62.2% |
| HOME | 14-13-0 | 51.9% | 27 | 34.0–69.3% |

### ATS road/home × favorite/dog

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| HOME_FAVORITE | 6-10-0 | 37.5% | 16 | 18.5–61.4% |
| HOME_UNDERDOG | 8-3-0 | 72.7% | 11 | 43.4–90.2% |
| ROAD_FAVORITE | 3-5-0 | 37.5% | 8 | 13.7–69.4% |
| ROAD_UNDERDOG | 11-12-0 | 47.8% | 23 | 29.2–67.0% |

### ATS locked spread buckets

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| 0-3 | 6-8-0 | 42.9% | 14 | 21.4–67.4% |
| 14.5+ | 5-4-0 | 55.6% | 9 | 26.7–81.1% |
| 3.5-7 | 5-9-0 | 35.7% | 14 | 16.3–61.2% |
| 7.5-14 | 12-9-0 | 57.1% | 21 | 36.5–75.5% |

### ATS confidence

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| 1 | 28-30-0 | 48.3% | 58 | 35.9–60.8% |

### ATS score quintile (1 lowest)

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| 1 | 4-8-0 | 33.3% | 12 | 13.8–60.9% |
| 2 | 5-7-0 | 41.7% | 12 | 19.3–68.0% |
| 3 | 6-5-0 | 54.5% | 11 | 28.0–78.7% |
| 4 | 6-6-0 | 50.0% | 12 | 25.4–74.6% |
| 5 | 7-4-0 | 63.6% | 11 | 35.4–84.8% |

### Totals direction

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| OVER | 9-8-0 | 52.9% | 17 | 31.0–73.8% |
| UNDER | 24-17-0 | 58.5% | 41 | 43.4–72.2% |

### Totals confidence

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| 1 | 10-10-0 | 50.0% | 20 | 29.9–70.1% |
| 2 | 12-3-0 | 80.0% | 15 | 54.8–93.0% |
| 3 | 11-10-0 | 52.4% | 21 | 32.4–71.7% |
| 4 | 0-2-0 | 0.0% | 2 | 0.0–65.8% |

### Totals score quintile (1 lowest)

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| 1 | 6-6-0 | 50.0% | 12 | 25.4–74.6% |
| 2 | 7-5-0 | 58.3% | 12 | 31.9–80.7% |
| 3 | 9-2-0 | 81.8% | 11 | 52.3–94.9% |
| 4 | 7-5-0 | 58.3% | 12 | 31.9–80.7% |
| 5 | 4-7-0 | 36.4% | 11 | 15.2–64.6% |

### Totals locked-total buckets

| Segment | Record | Win % | N | 95% Wilson interval |
|---|---:|---:|---:|---:|
| 45-49.5 | 8-9-0 | 47.1% | 17 | 26.2–69.0% |
| 50-54.5 | 13-7-0 | 65.0% | 20 | 43.3–81.9% |
| 55-59.5 | 8-5-0 | 61.5% | 13 | 35.5–82.3% |
| 60+ | 1-1-0 | 50.0% | 2 | 9.4–90.5% |
| <45 | 3-3-0 | 50.0% | 6 | 18.8–81.2% |

## Governed ATS Top 5: exact ranking and failures

The frozen `ranking_basis` for all five is `DETERMINISTIC_POLICY_TOP5_NOT_STRENGTH_RANKED`. They are the first five locked-line rows. The stored rank labels run 5→1 and do not measure probability or edge. Their combined shadow-pool ranks are shown below; none was a top-five strength candidate. The sealed card stores aggregate EPA-only projected margin and edge but not a per-team EPA component attribution. The per-pick question-by-question analysis is in `week6_top5_failure_analysis.md`; missing raw component attribution is an audit limitation. No timestamp-qualified close exists, so the indicative ESPN DraftKings quote is shown only as an unqualified proxy. All five carry unverified QB/injury context and sample-quality warnings; no manual adjustment was made.

| Order | Pick / locked line | Final (away–home) | ATS margin | Stated P | Raw projected home margin | ATS edge pts | Pool rank | Indicative close / CLV* | Primary failure |
|---:|---|---:|---:|---:|---:|---:|---:|---|---|
| 1 | Southern Miss +10.5 (Southern Miss @ Troy) | 34–55 | -10.5 | 52.2% | +6.2 | +4.3 | 78/116 | -9.5 / +1 | D — ranking/selection failure |
| 2 | Jacksonville State -2.5 (Jacksonville State @ Kennesaw State) | 27–26 | -1.5 | 51.0% | -4.5 | +2.0 | 99/116 | +3 / +0.5 | G — football variance / narrow margin |
| 3 | New Mexico State +6.5 (New Mexico State @ Florida International) | 3–22 | -12.5 | 50.2% | +6.1 | +0.4 | 114/116 | -7 / -0.5 | D — ranking/selection failure |
| 4 | Sam Houston +13.5 (Sam Houston @ Liberty) | 3–35 | -18.5 | 52.1% | +9.3 | +4.2 | 79/116 | -13.5 / +0 | D — ranking/selection failure |
| 5 | Missouri State +2.5 (Missouri State @ Western Kentucky) | 13–34 | -18.5 | 53.9% | -5.3 | +7.8 | 57/116 | +1.5 / +4 | D — ranking/selection failure |

*ESPN postgame quote is provider-labeled ‘close’ without quote timestamp. CLV is unqualified; market direction/process claims are withheld.

The primary D labels identify the actual mechanism that elevated these losses into the official five: card-row order despite low confidence and low shadow rank. They do not claim the projected football margin was otherwise correct. Jacksonville State lost ATS by 1.5 points as a roughly 51% side; a single such result is a plausible narrow-loss variance case (G). The other four missed the locked spread by 10.5–18.5 points and their ranking failure is demonstrable; isolated scores cannot identify a specific missing feature or coefficient. For every pick the positive pregame signals were the frozen selected margin edge and any captured lock advantage; the negative signals were the sample/QB/injury warnings and low 50–54% stated probabilities. The handicaps were wrong in realized margin on four games, but probability aggressiveness cannot be inferred from five binary outcomes. A disciplined bettor would not treat these Confidence-1, unverified-context, row-order picks as five strongest wagers. The scoring-play classification in the ATS CSV is evidence-based; it is not inferred from final score alone.

## Shadow mixed Top 5 and combined board

The mixed Top 5 went 1-4-0 (N=5; 20.0% W ex-push), and the separate human review five went 0-5-0 (N=5; 0.0% W ex-push). These three five-pick lists are distinct products. The top ten combined scores are all totals; the first ATS candidate was displaced to pool rank 26. Mean stated score: ATS 0.526, totals 0.584. Totals use an uncalibrated normal shadow score, while ATS uses a conservative shadow mapping; they were not validated on a common scale.

| Pool rank | Market | Selection / line | Stated score | Result |
|---:|---|---|---:|---|
| 1 | TOTAL | under 53.5 — UCF @ Oklahoma State | 72.0% | LOSS |
| 2 | TOTAL | over 47.5 — Tulane @ Army | 71.5% | LOSS |
| 3 | TOTAL | under 59.5 — UCLA @ Oregon | 67.4% | WIN |
| 4 | TOTAL | under 61.5 — Arizona @ West Virginia | 67.2% | LOSS |
| 5 | TOTAL | over 46.5 — Central Michigan @ Ohio | 66.2% | LOSS |
| 6 | TOTAL | under 53.5 — Virginia Tech @ California | 64.4% | WIN |
| 7 | TOTAL | under 52.5 — Sam Houston @ Liberty | 64.0% | WIN |
| 8 | TOTAL | under 56.5 — Maryland @ Ohio State | 63.7% | LOSS |
| 9 | TOTAL | under 55.5 — San Diego State @ Oregon State | 63.5% | LOSS |
| 10 | TOTAL | under 56.5 — Missouri State @ Western Kentucky | 63.4% | WIN |

## Probability calibration

Treat each number as a stated shadow score, not as a proven fair-bet probability. A push would be excluded from binary calibration; Week 6 had none.

### ATS

| Predicted bucket | N | Expected W | Actual W | Expected % | Actual % | Actual − expected |
|---|---:|---:|---:|---:|---:|---:|
| 50-52% | 31 | 15.82 | 13 | 51.0% | 41.9% | -9.1 pp |
| 52-54% | 15 | 7.93 | 7 | 52.9% | 46.7% | -6.2 pp |
| 54-56% | 5 | 2.73 | 3 | 54.6% | 60.0% | +5.3 pp |
| 56-58% | 6 | 3.43 | 4 | 57.2% | 66.7% | +9.5 pp |
| 58-60% | 1 | 0.59 | 1 | 59.0% | 100.0% | +41.0 pp |
| 60+% | 0 | 0.00 | 0 | — | — | — |

### Totals

| Predicted bucket | N | Expected W | Actual W | Expected % | Actual % | Actual − expected |
|---|---:|---:|---:|---:|---:|---:|
| 50-52% | 3 | 1.52 | 2 | 50.8% | 66.7% | +15.9 pp |
| 52-54% | 12 | 6.37 | 6 | 53.1% | 50.0% | -3.1 pp |
| 54-56% | 11 | 6.05 | 7 | 55.0% | 63.6% | +8.7 pp |
| 56-58% | 5 | 2.86 | 4 | 57.2% | 80.0% | +22.8 pp |
| 58-60% | 4 | 2.37 | 3 | 59.2% | 75.0% | +15.8 pp |
| 60+% | 23 | 14.69 | 11 | 63.9% | 47.8% | -16.1 pp |

The totals 60%+ bucket was 11–12 (N=23) versus 14.69 expected wins. Week 5's analogous uncalibrated 60%+ totals bucket went 9-15-0 (N=24; 37.5% W ex-push) versus 15.45 expected wins. Together, the two high-score buckets delivered 20/47 wins against 30.14 expected. If the stated probabilities were honest and games independent, the Poisson-binomial chance of that few wins or fewer is 0.20%; this conditional calculation does not account for correlated risk or validate the shadow scores. The high-score tail shows severe calibration failure if interpreted as a win probability; broad model structure remains unproven and no numeric shrink factor is justified yet. The Week 6 ATS probabilities were concentrated at 50–54%, so 28 wins versus approximately 30.5 expected is not severe ATS calibration drift.

## Ranking power

These are **shadow score ranks** within each market and the combined board; the governed ATS Top 5 is separately row-order based. Mean qualified CLV is unavailable in every rank band.

### ATS shadow score order

| Score rank | Record | N | Mean stated P | Qualified mean CLV |
|---|---:|---:|---:|---:|
| Top 5 | 4-1-0 (80.0%) | 5 | 57.9% | unavailable |
| 6-10 | 3-2-0 (60.0%) | 5 | 55.5% | unavailable |
| 11-20 | 4-6-0 (40.0%) | 10 | 53.5% | unavailable |
| 21-40 | 10-10-0 (50.0%) | 20 | 51.9% | unavailable |
| 41-58 | 7-11-0 (38.9%) | 18 | 50.5% | unavailable |

### Totals shadow score order

| Score rank | Record | N | Mean stated P | Qualified mean CLV |
|---|---:|---:|---:|---:|
| Top 5 | 1-4-0 (20.0%) | 5 | 68.9% | unavailable |
| 6-10 | 3-2-0 (60.0%) | 5 | 63.8% | unavailable |
| 11-20 | 4-6-0 (40.0%) | 10 | 62.4% | unavailable |
| 21-40 | 16-4-0 (80.0%) | 20 | 57.3% | unavailable |
| 41-58 | 9-9-0 (50.0%) | 18 | 52.9% | unavailable |

### Combined score order

| Score rank | Record | N | Mean stated P | Qualified mean CLV |
|---|---:|---:|---:|---:|
| Top 5 | 1-4-0 (20.0%) | 5 | 68.9% | unavailable |
| 6-10 | 3-2-0 (60.0%) | 5 | 63.8% | unavailable |
| 11-20 | 4-6-0 (40.0%) | 10 | 62.4% | unavailable |
| 21-40 | 16-4-0 (80.0%) | 20 | 58.1% | unavailable |
| 41-116 | 37-39-0 (48.7%) | 76 | 52.5% | unavailable |

The strongest-scored totals five lost four of five, while ranks 21–40 outperformed them. This is an observed ranking inversion, not yet a stable rule. The official ATS five were never strength-ranked; their 0–5 result should not be attributed to a failed ATS probability ranking algorithm.

## Closing-line value and market process

**Qualified CLV: 0/116.** The ESPN DraftKings postgame payload exposes a `close` field but no quote timestamp. Retrieval on the audit date cannot establish when those odds were available or whether they were a true final pre-kickoff quote. `week6_clv_audit.csv` preserves every provider-labeled field and provenance, while `week6_diagnostics.json` gives descriptive, unqualified proxy summaries. The **unqualified proxy** mean/median/positive-share was ATS -0.20/+0.0/34.5% and totals +0.52/+0.0/46.6%. The detailed proxy by confidence, Top 5 and win/loss sign appears in diagnostics; it is not accepted as true CLV. Accordingly mean/median true CLV, CLV+ rate, Top-5 CLV, confidence cuts, CLV+/CLV− outcome splits, and GOOD PROCESS/BAD RESULT versus BAD PROCESS are **not adjudicated**. The earlier captured `current_market_line` is a pregame comparison, not a close, and is not substituted for one.

## Historical out-of-sample comparison

Prior ATS cards available here: Week 1 local draft, Week 2 local draft, Week 3 provisional, and Week 5 frozen audit. Week 4 has no replay-safe frozen card. Their combined ATS record was 103-101-0 (N=204; 50.5% W ex-push); Week 6 ATS was 28-30-0 (N=58; 48.3% W ex-push). The prior governed Top 5 was 7-13-0 (N=20; 35.0% W ex-push), now 7–18 including Week 6. Week 5 totals were 23-33-0 (N=56; 41.1% W ex-push), compared with 33-25-0 (N=58; 56.9% W ex-push) in Week 6. Weeks 1–3 lack complete stored comparable ATS/totals probability cards, so their calibration, totals, and cross-market rankings cannot be reconstructed honestly. The historical intervals and segment cuts in `week6_diagnostics.json` are descriptive and small-sample; do not turn a Week 6 split into a permanent rule.

## Counterfactual Top 5 — IN-SAMPLE DIAGNOSTIC ONLY

Every alternative uses only frozen pregame fields and is graded afterward; none was optimized by final score. None is a proposed production rule without prior-week replay and owner approval.

| Pregame rule | Week 6 record | Five selections (result) |
|---|---:|---|
| frozen mixed shadow | 1-4-0 (N=5; 20.0% W ex-push) | under 53.5 LOSS; over 47.5 LOSS; under 59.5 WIN; under 61.5 LOSS; over 46.5 LOSS |
| ats shadow score only | 4-1-0 (N=5; 80.0% W ex-push) | Ball State 36.5 WIN; Massachusetts 2.5 WIN; Maryland 34.5 WIN; Hawai'i 20.5 WIN; Vanderbilt 10.5 LOSS |
| totals shadow score only | 1-4-0 (N=5; 20.0% W ex-push) | under 53.5 LOSS; over 47.5 LOSS; under 59.5 WIN; under 61.5 LOSS; over 46.5 LOSS |
| illustrative total score cap 60pct | 1-4-0 (N=5; 20.0% W ex-push) | under 53.5 LOSS; over 47.5 LOSS; under 59.5 WIN; under 61.5 LOSS; over 46.5 LOSS |
| illustrative total excess probability half shrink | 2-3-0 (N=5; 40.0% W ex-push) | under 53.5 LOSS; over 47.5 LOSS; Ball State 36.5 WIN; under 59.5 WIN; under 61.5 LOSS |
| illustrative two ats three totals constraint | 3-2-0 (N=5; 60.0% W ex-push) | under 53.5 LOSS; over 47.5 LOSS; under 59.5 WIN; Ball State 36.5 WIN; Massachusetts 2.5 WIN |

A 60% cap alone leaves the same five because all top totals tie at the cap and retain frozen tie order. The ATS-only 4–1 result is a one-week diagnostic, not evidence for forcing ATS market balance. A true calibrated cross-market alternative cannot be replayed with existing historical probability custody.

## Five biggest problems, in order

1. **CRITICAL — TOP-5 RANKING.** Official ATS Top 5 was deterministic card order, 0–5 this week, and 7–13 across prior recorded weeks. Cause is known policy behavior, not football variance. Requires a separately approved ranking-policy test, not an in-week edit.
2. **HIGH — PROBABILITY CALIBRATION / TOTALS MODEL.** Week 6 totals ≥60% scored 11–12 against 14.69 expected; Week 5 analogous high bucket was 9–15; jointly 20/47 against 30.14 expected. High totals scores need walk-forward reliability study before use as probabilities. Do not assert coefficient failure from two weeks.
3. **HIGH — ATS/TOTALS COMBINATION.** 25 totals outranked the best ATS score; mixed Top 5 was 5/5 totals and 1–4. Structural score-scale mismatch is documented in the frozen manifest. Requires market-specific calibration before comparing scores.
4. **MODERATE — CLV DATA QUALITY.** 0/116 timestamp-qualified closes means market-process quality cannot be evaluated; this blocks formal PASS. Requires historical quote custody, not a model coefficient change.
5. **MODERATE — FEATURE/CONTEXT QUALITY.** All governed ATS Top-5 rows had unverified QB/injury context and sample warnings. The evidence does not identify which missing context caused any specific loss. Improve verified pregame data custody and test its OOS value; do not invent adjustments.

Line locking showed no defect: every grade uses the unchanged SplashSports snapshot. Home/road and spread-bucket splits are noisy at these sample sizes. Pure variance plausibly explains Jacksonville State's narrow loss but not the demonstrable Top-5 row-order governance and cross-market scale faults.

## Lessons Learned

- Keep the frozen governed ATS five, mixed shadow five, and human review five separate in every performance claim.
- Do not promote a shadow probability score to wagering confidence before OOS calibration and cross-market comparison.
- Persist timestamped book, market, quote, and capture metadata at close if CLV is an acceptance criterion.
- Preserve point-in-time data warnings; a missing QB fact cannot be inferred from an outcome.
- Use prior-week replay and predefined thresholds before any v2.9 cutover; no Week 6 result alone licenses a new rule.

## Potential v2.9 research plan — no implementation

| Priority | Current rule | Proposed research rule | Numeric delta | Evidence / expected benefit | Overfit risk | Required backtest |
|---|---|---|---|---|---|---|
| MUST FIX | Governed ATS Top 5 uses first five lock rows | Design a predeclared strength-rank policy with preserved fallback and compare to current policy | No justified numeric threshold yet | 0–5 Week 6 and 7–13 prior; may align Top 5 with calibrated reliability | HIGH | Replay all available sealed weeks; compare Top 5 versus remaining card and margin error |
| MUST FIX | Mixed shadow compares ATS conservative and totals normal scores directly | Fit market-specific OOS calibration before a unified rank; retain shadow status until validated | No justified shrink factor yet | 25 totals above top ATS and 1–4 mixed five; makes scores comparable | HIGH | Walk-forward Brier, log loss, calibration, ROI after vig, rank monotonicity |
| MUST FIX | Closing quote has no timestamp custody | Capture auditable last pre-kickoff real-book quote per market | Timestamp strictly before kickoff; no price threshold change | Enables qualified CLV and process review | LOW | Provider replay, timestamp cutoff and provenance tests |
| SHOULD TEST | Totals use uncalibrated normal probability | Test calibrated totals reliability or shrinkage learned on prior weeks | 60% cap and 50% excess shrink are diagnostics only, not recommended numeric changes | High-score totals underperformed in Weeks 5 and 6 | HIGH | Multi-season walk-forward calibration, held-out weeks, baseline comparison |
| SHOULD TEST | QB/injury context incomplete, no manual adjustment | Test verified point-in-time availability and incremental predictive value | No numeric adjustment justified | Warnings on official five; causal effect unknown | HIGH | Ablation with timestamped features and predeclared acceptance criteria |
| DO NOT CHANGE | Immutable locked lines, ATS/totals grading, v2.8 model coefficients | Preserve | 0 | No identified defect; data custody reconciles 58/58 | LOW | Existing immutability/grading checks |

Do not change spreads/totals, backfill outcome-aware projections, impose arbitrary 3–2 market balance, retune road-favorite rules, claim a profitable edge from hypothetical -110 accounting, or issue v2.9 before the baseline policy and OOS evidence are available.

## WHAT ACTUALLY CAUSED WEEK 6?

The governed ATS Top 5 was selected by locked-card order, not by estimated strength, and all five lost. The full ATS card was 28–30, so the worst outcome was concentrated in the unranked five. The mixed shadow board put totals in all five slots because its uncalibrated totals scores were systematically higher than the ATS scores; that five went 1–4. Totals overall were 33–25, but their 60%+ score bucket was 11–12, matching a Week 5 warning that high totals scores overstate reliability. Incomplete QB/injury context may matter but cannot be assigned causal credit from these records. The locked lines and grades reconciled; they did not cause the loss. Football variance explains at least the narrow Jacksonville State loss, but it does not explain deterministic Top-5 selection or unvalidated cross-market scoring. Without timestamped closes, we cannot say whether the market validated the picks before kickoff.

**WEEK 6 AUDIT STATUS: FAIL**

Every 58+58 selection is graded, Top-5 selection order reconstructed, calibration/ranking/history evaluated, and no production model changed. The required true CLV test cannot be completed with the available untimestamped `close` payload, and per-game raw EPA component attribution was not frozen, so the explicit PASS gate is not met.
