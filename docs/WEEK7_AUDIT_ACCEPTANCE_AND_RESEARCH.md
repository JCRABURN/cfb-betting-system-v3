# Week 7 audit acceptance and cross-week diagnostics

Review date: 2026-10-21 UTC. Repository: `JCRABURN/cfb-betting-system-v3`.

**Recommendation: accept the Week 7 arithmetic and preserved selections as verified evidence; do not declare the formal audit complete or merge the dependency stack yet. CLV remains INCOMPLETE. No model, ranking, confidence, betting, or v2.8 policy change is authorized by this research.**

The new diagnostic script independently grades from pregame cards and recorded final scores; it does not call the production grading functions or rerun the forecast model. The existing Week 7 replay was also executed. Detailed machine-readable evidence, all per-selection observations, and all requested cuts are in [the research directory](../outputs/2026-week7-acceptance-research/). The [generated tables](../outputs/2026-week7-acceptance-research/diagnostic_tables.md) include earlier weeks and nonoverlapping rank segments. This report interprets those computations; it does not replace any historical output.

## 1. Dependency and acceptance findings

| PR | Reviewed head | Current base | Finding and required disposition |
|---|---|---|---|
| [#35](https://github.com/JCRABURN/cfb-betting-system-v3/pull/35) | `57c33b29aa399e4d94c749f6e2d25a6e80b48262` | `main` | Week 6 grading is usable; formal status explicitly FAIL for CLV/raw-component custody. Resolve the overwrite safeguard and Week 5 checkout custody defect before a clean merge. Preserve its incomplete audit designation. |
| [#36](https://github.com/JCRABURN/cfb-betting-system-v3/pull/36) | `48d0250aff3fc286b7b8bd06e7e798a4134910a5` | #35 branch | Research-only, no-go for v2.9. Expand its historical-coverage limitation: Week 2 pregame dual-market forecasts and Week 3 provisional forecasts are recoverable. Its replay balance is even-money, not -110 returns. Use the explicit -110 ledger here for comparisons. |
| [#37](https://github.com/JCRABURN/cfb-betting-system-v3/pull/37) | `55c0a417c72492943253ad50cf139415ca3902be` | #36 branch | Original and corrected seals pass. Clarify the stale runbook and approval commit reference; neither changes the five or their locks. |
| [#38](https://github.com/JCRABURN/cfb-betting-system-v3/pull/38) | `da7381b801abee170a8b321cf77d833626230a11` | `main` | 59/59 ATS and 59/59 totals independently agree; corrected five agree. Its verification command needs exact manifest coverage/status validation. Keep formal status INCOMPLETE. |

`main` was `abb4eb26bd1140e66972d2f1143cd587e80960b4`. Git ancestry checks confirmed #35 → #36 → #37 → #38. All four were open drafts, with no reviews or commit check-runs returned at inspection. This is not a statement that local testing never occurred. #38's diff against main includes the unmerged stack; its own audit commit adds 75 files/changes. Review those dependencies first. After each predecessor merges, retarget/reconcile the next branch and rerun the relevant checks. Do not assume squash-merging a predecessor makes the descendant diff clean.

The new evidence-only PR must also wait for #35–#38. Its validation was performed over the exact #38 head. Its patch contains new diagnostic artifacts, diagnostic/test utilities, and documentation only. It does not silently fix the inherited defects.

### Concrete defects and limitations

1. **P1, reproducibility gate: Week 5 byte custody depends on checkout EOL settings.** On this LF checkout, 25/91 pregame, 13/15 review, and 15/73 postgame entries differ from their exact recorded checksums: 53 distinct files. Every one matches after CRLF conversion in memory; zero unresolved content mismatches. `test_week5_postgame_audit.py:207` and `test_week5_review.py:25` fail. The earlier default-Windows failure at line 213 was the other manifestation of the same mixed EOL custody scheme. This is not evidence that Week 5 picks or scores changed. It does prevent an unconditional reproducibility pass. Add a separate, reviewed byte-preserving checkout/custody correction; retain original hashes and historical contents. Do not relax the original tests or replace their hashes with convenient current hashes.
2. **P2, #35 overwrite protection:** `scripts/build_week6_postgame_audit.py:42` opens output CSVs for writing and its JSON writer does likewise. A normal rerun can overwrite an existing audit. The new test demonstrates this only inside a disposable directory. Add a fail-closed existing-output gate/new-version destination in a separate fix. Existing evidence was not overwritten during this review.
3. **P2, #38 verification coverage/status:** `scripts/build_week7_postgame_audit.py:340` validates only hash entries actually present in the manifest. With both checksum maps emptied and the manifest falsely declaring COMPLETE/118 qualified CLV rows, `main(verify=True)` still succeeds because it independently computes the correct diagnostics but never compares those declarations. A monkeypatched, read-only test reproduces it. The new acceptance checker requires all 69 output entries, the three expected code entries, and matching status/zero qualified CLV. The current unaltered manifest passes. No present grading error or tampering was found; the defect matters for future verification.
4. **P2, #37 documentation/custody labeling:** `docs/WEEK7_PROSPECTIVE_RUNBOOK.md:7` still says the authoritative source is not present. The corrected approval's `approval_source_commit_sha=d3ffcc2…` points to the pending-card context committed at 19:32:10 UTC, before the recorded approval observation. The approval artifact first appears in `cfbe724fc9687dea24bd50409bcc4a4c2214aec4`, committed 19:46:07 UTC, still before kickoff. Use the latter as the approval-containing commit and retain the former as parent context. This report supplies that additive clarification. A raw signed owner-message export is not in the repository: custody consists of the contemporaneous approval record, its immutable hash, and the owner's characterization of these five as approved.
5. **Formal audit limitation:** no timestamp-qualified market close exists for these Week 7 rows. ESPN's postgame labeled-close fields have no qualifying quote timestamp. All qualified closing lines, CLV and close-based key-number crossings remain unavailable. Do not promote Week 6's indicative unqualified CLV proxies into evidence of true CLV. No historical close was fetched, reconstructed, substituted, or fabricated here.

## 2. Week 7 evidence and independent grading

All 59 unique lined games appear in both markets; there are no duplicate games, missing grades, silent omissions, or fallback picks. Grading uses corrected locked contest lines, not the later market fields. ESPN's archived scoreboard and 59 individual summaries agree on identity, kickoff, completion and final scores. These are two payloads from one provider, not independent providers. The five owner games were additionally checked against official athletics pages listed below. The other 54 finals have no second-provider reconciliation in #38; this remains an assurance limitation.

| Product | N | W–L | Hit rate | Hypothetical -110 units |
|---|---:|---:|---:|---:|
| Full ATS | 59 | 26–33 | 44.07% | -9.364 |
| Full totals | 59 | 33–26 | 55.93% | +4.000 |
| Owner-approved five | 5 | 2–3 | 40.00% | -1.182 |
| Governed v2.8 ATS five | 5 | 3–2 | 60.00% | +0.727 |
| ATS research five | 5 | 3–2 | 60.00% | +0.727 |
| Totals research five | 5 | 2–3 | 40.00% | -1.182 |

No pushes. One unit risked per selection: win earns 10/11, loss loses 1. No actual wager, offered price, stake, or realized betting profitability is claimed.

| Owner pick | Immutable line | Final (away–home) | Cover margin | Grade | Independent official source |
|---|---:|---|---:|---|---|
| Air Force | +1.5 | UNLV 31–Air Force 41 | +11.5 | W | [Air Force](https://goairforcefalcons.com/news/2026/10/17/football-air-force-produces-430-rushing-yards-in-41-31-win-over-unlv) |
| Indiana | +3.5 | Ohio State 19–Indiana 15 | -0.5 | L | [Indiana](https://iuhoosiers.com/news/2026/10/17/football-win-streak-cracked-by-buckeyes-PETE) |
| Georgia State | +12.5 | Georgia State 22–JMU 49 | -14.5 | L | [Georgia State](https://georgiastatesports.com/news/2026/10/17/football-panthers-come-up-short-in-a-49-22-loss-to-james-madison.aspx) |
| Nebraska | +7.5 | Nebraska 14–Oregon 17 | +4.5 | W | [Oregon](https://goducks.com/game-center/24382) |
| CSU–Texas State Under | **69.5** | CSU 27–Texas State 66 | -23.5 | L | [Texas State](https://txst.com/news/2026/10/15/football-game-recap-bobcats-dominate-colorado-state-66-27-in-pac-12-home-opener.aspx) |

The original Under 72.5 approval remains preserved and superseded. Six total-line source corrections and zero spread corrections were made before kickoff; they changed 27 totals ranks and one total direction (Nevada–North Dakota State). The corrected five were approved at 19:37:43 UTC on October 13. Under 69.5 is the official audited line, not a hindsight replacement.

### Custody and point-in-time review

The exact-byte checks pass for 89 original Week 7 files, 96 corrected output files, 14 corrected source files, both approval identities, the corrected approval-to-seal link, and the source database. Week 6's 41 frozen entries also pass. The full list of 419 Week 5–7 manifest entries and the EOL diagnoses is in `custody_checks.json`. `week7_custody_details.json` records the source timestamps and component reproduction checks.

| Identity | SHA-256 |
|---|---|
| Source database | `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842` |
| Corrected locked card | `d9c3c8b517875743b1c78c1ff3a5f190f83bcdb570eff8449752a6cf9fdbd568` |
| Corrected source CSV, raw | `0a3b81fd54de0f6497e547ae5b6e17f9aea47ec67bb3068cead4896244ac62b7` |
| Corrected source CSV, canonical | `2c7c87d1c55156140de1249306856a0809a0b1632483041186e5d78ddd9a328f` |
| Corrected approval | `31dd412b3e6c16f3f871e4dc0276c3b2c84c2faae95715ac20eb39d648042568` |
| Original approval | `335d7753d6482025aeda6e72948f182c22c93cb65d6226fc401c88c5da63bfe7` |
| Corrected seal | `9c6c32c3d38d3fcac5a7fa8858221f5e8bf61095439147d65785048fdb41d783` |

Core provider capture completed October 13 at 14:07:24 UTC; advanced stats requested `endWeek=6`. Initial context capture completed at 18:33:33 UTC. Corrected forecasts/card were generated at 19:20:46/19:21:01 UTC; seal at 19:25:34 UTC; approval observed at 19:37:43 UTC; earliest kickoff at 23:00 UTC. Model/research code is `8afaf9ecd495abd9357fa2dcce6710e394abf9ae`; source correction evidence is `f49e106b004ebc21b33bfa25e856e7996a75910a`.

All 59 target-game pregame records are result-free. All raw target team-stat packages are at or before Week 6. Independently applying the sealed ATS coefficient/intercept and totals component coefficients reproduces every stored projection. ATS training seasons are 2019–2025; totals training code filters to folds before `(2026,7)`. The diagnostic run did not refit the entire 4,944-row totals training matrix or independently certify the provider's historical availability ledger. **No postgame contamination was detected in the sealed inputs; this is narrower than proving that every upstream historical provider value was never revised.** The read-only DB integrity/FK checks in the existing replay pass and its hash is unchanged.

Numeric manual adjustments are zero. Raw and adjusted projections therefore grade identically. Human selection/confidence changes are a different intervention and are evaluated below. No backdoor classification is inferred solely from a final score.

## 3. Cross-week coverage and forecast performance

| Week | Evidence status | ATS W–L | ATS MAE / RMSE / bias | ATS units | Totals W–L | Totals MAE / RMSE / bias | Totals units |
|---|---|---:|---|---:|---:|---|---:|
| 1 | Recorded local draft audit; sealed original pregame forecast bytes not recovered | 18–25 | 20.968 / 25.790 / +13.434 | -8.636 | unavailable | unavailable | unavailable |
| 2 | Pregame Git archive recovered; local governed/limited shadow | 24–25 | 23.466 / 29.129 / +9.733 | -3.182 | 24–25 | 10.542 / 13.608 / -0.814 | -3.182 |
| 3 | Pregame provisional, one explicit kickoff skip | 27–29 | 14.760 / 18.186 / +4.915 | -4.455 | 26–30 | 14.726 / 17.717 / +5.737 | -6.364 |
| 4 | No replay-safe full card recovered | — | — | — | — | — | — |
| 5 | Frozen pregame; diagnosed byte-custody EOL defect | 34–22 | 14.033 / 19.121 / -0.589 | +8.909 | 23–33 | 14.225 / 17.284 / +2.448 | -12.091 |
| 6 | Frozen pregame, incomplete formal audit | 28–30 | 13.011 / 16.073 / +1.617 | -4.545 | 33–25 | 12.430 / 16.278 / +1.034 | +5.000 |
| 7 | Corrected sealed pregame, incomplete CLV | 26–33 | 11.951 / 14.741 / +0.093 | -9.364 | 33–26 | 12.940 / 15.611 / +1.265 | +4.000 |

Bias always means actual minus forecast, in home-margin points for ATS and total points for totals. The generated table includes each hit rate and sample size. No blank means zero.

Week 2's pregame artifact was recovered byte-for-byte from `c7b621a981cf72d9699a3899a1b5b92f548e6150` (September 10); its 49 line identities and forecasts reconcile to the later audited results. Two totals were quarantined from eligibility, but are retained in the all-forecast descriptive grading denominator; no promotion is implied. Week 3's archive/execution record comes from `9fd6743a3654c133a99a85c410576cf5c19bd4a4` (September 18). Its archived cards match the later preserved copies, and each of the 56 included forecasts precedes its kickoff. Syracuse–Pittsburgh remains skipped. Week 1 is shown as recorded context, excluded from genuinely recovered pregame inference. Earlier weeks are not pooled into the Week 5–7 score comparison because custody, model state, selection eligibility and ranking products differ.

A supplementary untracked Week 1 workbook, `outputs/week1-picks-2026-09-01/2026-week1-model-picks.xlsx`, was inspected read-only. All 43 selections, locked spreads and forecasts match the recorded audit (forecast tolerance 0.000001), using the existing canonical team resolver. It contains no total forecasts. Its local creation/write dates are September 1, but no pregame immutable hash or Git seal was recovered; mutable filesystem timestamps are not equivalent to verified pregame custody. Its SHA-256 and inspection record are preserved in `source-evidence/week1_local_workbook_review.json`; the workbook itself was not modified or added to Git.

Weeks 5–7: ATS **88–85, 50.87%, -5.000 units**, MAE 12.981, RMSE 16.705, bias +0.383 (n=173). Totals **89–84, 51.45%, -3.091 units**, MAE 13.185, RMSE 16.391, bias +1.570 (n=173). Both hit rates are below the 52.38% -110 break-even rate; neither supports a profitability claim. Their descriptive Wilson 95% intervals are 43.48–58.22% and 44.05–58.78%, before accounting for team/week dependence.

Maximum drawdown using only successive weekly settlements is 13.909 units ATS and 12.091 totals over these three weeks, starting at zero units. This is not an intragame or intraday wagering drawdown; no actual stake sequence is available.

## 4. Ranking, confidence and human selection

| Week / pooled | Market | Ranks 1–5 | Ranks 6–10 | Ranks 11+ |
|---|---|---|---|---|
| 5 | ATS | 3–2 | 2–3 | 29–17 |
| 6 | ATS | 4–1 | 3–2 | 21–27 |
| 7 | ATS | 3–2 | 2–3 | 21–28 |
| 5–7 | ATS | **10–5** | **7–8** | **71–72** |
| 5 | TOTAL | 3–2 | 2–3 | 18–28 |
| 6 | TOTAL | 1–4 | 3–2 | 29–19 |
| 7 | TOTAL | 2–3 | 2–3 | 29–20 |
| 5–7 | TOTAL | **6–9** | **7–8** | **76–67** |

These segments do not overlap. ATS Top 10 totals 17–13 (+2.455 units); totals Top 10 totals 13–17 (-5.182 units). Top 10 must not be treated as independent of Top 5. Week 7 alone was prospective tracking of the frozen research ordering; Weeks 5–6 comparison/order selection is retrospective. None of this validates a newly proposed policy out of sample.

ATS research Top 5: +4.091 units and a 17.30 percentage-point higher hit rate than the remaining 158 selections (78–80). Its 95% hit-rate interval is 41.71–84.82%; exact random-five testing conditional on each week's win count gives two-sided p=0.316. Totals research Top 5: -3.545 units, 12.53 points below the remaining 158 (83–75), p=0.517. Fifteen observations per market cannot establish ranking superiority or infer a reliable inverse strategy.

Governed ATS confidence is **1 for all 173** selections and governed uncertainty is absent. The governed five are therefore effectively selected by the deterministic lock-ID tiebreaker, not calibrated reliability: Week 5 3–2, Week 6 0–5, Week 7 3–2 (6–9 total). The research five use a different ordering. They must not be relabeled as the official v2.8 five.

Totals confidence is nonmonotonic: level 1 28–26 (n=54), level 2 30–22 (n=52), level 3 29–33 (n=62), level 4 2–3 (n=5), level 5 no observations. Favorable road-favorite avoidance is also only exploratory: road favorites went 5–10 (n=15); all favorites 29–35 versus underdogs 59–50. ATS home 52–47, away 35–38, neutral 1–0. Spread and edge bins are in the generated tables: the 7–9.9-point ATS edge group went 9–18 while 10+ went 15–10, which rejects a simple claim of monotonic reliability from these samples.

### Does edge or research score predict winning?

For Weeks 5–7, ATS edge and its affine research score have identical AUC **0.5302**, point-biserial r=0.0588, within-week permutation p=0.5114 (4,999 permutations). Totals edge AUC is **0.4525**, r=-0.0889, p=0.2850; totals score AUC **0.4524**, p=0.2842. These tests do not establish a useful association. Permutations preserve weekly win counts but not team dependence; all cuts and p-values are exploratory and unadjusted for multiple comparisons.

ATS score Brier/log loss are 0.24948/0.69211, only slightly better than the 0.25/0.69315 constant-50% reference. Totals are worse at 0.26273/0.72011. Totals scores forecast 101.48 wins but produce 89; the 0.60+ bucket is 31–36 (46.27%, n=67). This is stronger evidence of score overstatement than of a particular replacement threshold. Earlier totals AUC was 0.670 in Week 2 (n=49, exploratory p=0.035) and 0.503 in Week 3 (n=56, p=0.977): the apparent relationship did not persist. Week 2 and Week 3 raw scores expected 29.95 and 34.47 wins, versus 24 and 26 actual wins.

### Did human selection help?

| Week | Intervention | Human W–L | ATS score-order comparator | Difference in hypothetical units |
|---|---|---|---|---:|
| 5 | Pregame review shortlist | 2–3 | 3–2 | -1.909 |
| 6 | Pregame mixed-market review shortlist | 0–5 | 4–1 | -7.636 |
| 7 | Explicit owner-approved mixed five | 2–3 | 3–2 | -1.909 |

The review lists combined are 4–11 versus 10–5 for the ATS score-order comparators: -6 wins/-11.455 units across 15 selections. **Only Week 7 is the explicit owner-approval observation being evaluated here**; the earlier shortlists are not equivalent approval experiments, and mixed-market versus ATS-only comparisons are confounded by product composition. These results do not establish a causal human effect.

Week 7's exact substitutions relative to the ATS research five remove Massachusetts (L) and Syracuse (W), and add Georgia State (L) and CSU–Texas State Under (L). Three selections are shared. Net effect: -1 win/-1.909 units. Against totals-only Top 5 or the frozen legacy mixed five, the owner record is equal at 2–3. Human confidence 3 went 1–2 and confidence 2 went 1–1. Numeric projection adjustments were zero, so there is no separate quantitative-adjustment treatment to assess.

## 5. CSU–Texas State: forecasting error versus realized events

Frozen component forecasts: Texas State 33.4157, CSU 25.9293, total 59.3450, Under 69.5, raw research score 0.72813, residual sigma 16.7252. Actual: Texas State 66, CSU 27, total 93. Texas State contributes **+32.5843 points (96.82%)** of the +33.6550 total error; CSU contributes +1.0707. The total residual is 2.012 sigma. Under 69.5 loses by 23.5; the superseded 72.5 would also lose but is not used for grading.

The sealed October 13 corrected decision board, before approval, specifically documented Texas State's prior **102 plays/565 yards**, explosive-scoring risk, unresolved QB details and missing local weather capture. It stated that pace was not modeled and rated the Under BORDERLINE at human confidence 2. Those were foreseeable uncertainty factors. The four-feature EPA component model has no explicit pace, QB availability, explosive-play or defensive-change variable. The documented error is an inadequately supported high-confidence total/selection despite known model omissions; the exact numeric contribution of each omitted feature cannot be inferred from one result.

Archived ESPN summary `espn-game-401860923.json.gz` supplies the game evidence: Texas State had 716 yards, 503 rushing, 55 rushing attempts and 19 passing attempts (74 offensive plays, about 9.68 yards/play); CSU had 437 yards, 31 rushes and 41 attempts. Texas State's actual play count was below the cited 102-play prior game. Exceptional rushing efficiency was a major realized driver; this is not evidence that pace alone caused the miss. Texas State's one turnover and CSU's zero turnovers do not support a defensive-turnover-scoring explanation. The scoring sequence contains offensive rushing/passing TDs and a field goal, no defensive/return TD, no overtime, and no fourth-quarter points; the Under was exceeded early in the third quarter.

Individual runs, conversions and exact TD production were uncertain game events, not known pregame facts. Calling them categorically unforeseeable would overstate what the evidence establishes. Nor can the result validate a new injury/weather adjustment. The official [Texas State recap](https://txst.com/news/2026/10/15/football-game-recap-bobcats-dominate-colorado-state-66-27-in-pac-12-home-opener.aspx) corroborates the final; component attribution and event details above come from the separately hashed raw model and ESPN artifacts.

## 6. Error dependence and selection concentration

Across 173 matched Week 5–7 games, ATS-versus-total signed-error correlation is **0.0104**, absolute-error correlation **-0.0274**, and win-indicator correlation **0.1094**. There are 50 both-win, 46 both-loss, and 77 split outcomes. Near-zero linear error correlation does not prove independence or eliminate shared-team risk.

Among the 15 ATS research Top 5 games, signed/absolute error correlations are -0.1372/-0.2620. Among the 15 totals Top 5 games they are +0.3405/+0.3338; win-indicator correlation is +0.3889. These tiny selected samples are unstable. The ATS and totals research Top 5 contain zero overlapping games in these three weeks; their union contains 30 games. There is no estimate for a both-Top-5 cohort (n=0), not a zero correlation. Correlations and per-week pairs are in `correlations.csv`. No portfolio covariance or staking policy is inferred from three weeks.

## 7. Prioritized causes and numerical candidates — RESEARCH ONLY

Priority reflects evidence, not permission to modify an official product.

1. **Confidence/ranking discrimination is structurally absent in the governed ATS card:** 173/173 confidence 1, missing governed uncertainty, governed Top 5 6–9 versus research 10–5. Candidate: keep the official fallback intact while prospectively shadow-ranking by a market-specific calibrated success estimate. Compare existing governed rank, edge rank, and calibrated rank; retain the locked-ID tiebreaker. Do not select the production rule from these 15 Top 5 outcomes. Require at least 100 held-out Top 5 selections across at least 20 weeks, positive improvement over governed rank under week-block bootstrap, and no material deterioration in the remaining card.
2. **Totals probabilities overstate reliability and are incomparable to ATS scores:** 89 wins versus 101.48 expected; 0.60+ bucket 31/67. Candidate grid `p'=0.5 + w*(p_raw-0.5)`, `w ∈ {0,0.25,0.5,1}`; also fit market-specific regularized logistic calibration on prior weeks only. In the retrospective time-split replay, w=0.25 reduces totals Brier from 0.25555→0.24956 in Week 6 (58 tests; 56 earlier training observations) and 0.25177→0.24848 in Week 7 (59 tests; 114 earlier observations). Shrinkage does not alter rank; a cap alone cannot fix selection ordering. ATS shrinkage has mixed results. These hypotheses were examined after outcomes and are not fresh out-of-sample validation.
3. **EPA forecasts add less margin accuracy than the locked-line benchmark in the two later weeks:** ATS model MAE 13.011/11.951 versus locked-line forecast 11.552/10.907 in Weeks 6/7. Candidate forecast `w*model + (1-w)*locked_line_target`, w ∈ {0.5,0.75,1}; ATS target is negative locked home spread, totals target is the immutable locked total. At w=0.5 ATS MAE becomes 11.873/11.205; totals 12.356/12.788 versus baseline 12.430/12.940. The locked line is used only as an explicitly labeled research predictor/benchmark, never substituted into a historical lock or called a close. Pure positive-weight shrinkage preserves sides and generally preserves rank, so accuracy gains alone do not establish a betting edge. Reject simple ATS intercept correction on this evidence: correcting by the prior mean bias worsens MAE in both replay weeks.
4. **Totals omit pace and contextual uncertainty:** CSU–Texas State is a 33.655-point error, predominantly Texas State's component, with pregame pace concerns already documented. Candidate model: point-in-time possessions × expected points per possession, with separate offense/defense and rushing/explosive-play components; compare rolling 3/5-game pace with opponent-adjusted shrinkage toward season-to-date. Predeclare minimum 3 prior games; below that use an explicitly tagged prior-season/league hierarchical prior with its own uncertainty. No invented zero values. Fit regularization using earlier seasons only, and ablate pace, explosiveness, QB and opponent strength separately. Require at least 500 held-out totals and ≥50 high-total (60+) games before claiming an improvement for that subgroup. This single miss does not justify adding 33 points or banning high-total Unders.
5. **Human review has not demonstrated incremental value:** explicit approval n=5 costs one win versus frozen ATS rank; heterogeneous review history n=15 costs six. Candidate prospective protocol: retain an unmodified baseline and a separate reviewed five; every substitution requires a timestamped reason/category and proposed numeric impact, even when zero. Grade the paired added/removed selections and confidence changes. Require ≥50 prospective substitutions before an effect claim; report market composition and common picks. Do not retrospectively reselect the owner card.

Uncertainty candidate: freeze rolling prior-only residual intervals at 80/90/95% and compare them with the existing normal-residual intervals. On n=173, current totals ±1 sigma coverage is 67.05% and ±1.96 sigma 95.95%; ATS is 74.57%/96.53%. These do not support indiscriminate sigma inflation. Empirical absolute-error 90/95% radii are ATS 27.53/34.01 and totals 27.02/31.49 points, descriptive only. Test heteroskedastic intervals by prior pace/feature quality using at least 100 prior residuals per group, otherwise pool explicitly. A context-unknown sensitivity grid of sigma multipliers {1,1.15,1.30} may be evaluated, not deployed. Do not infer the correct multiplier from CSU–Texas State alone.

For every candidate, agree to a numerical acceptance plan **before** opening a new held-out fold: chronological train/calibrate/test, no current-week outcomes, intact frozen baseline, and predeclared missingness behavior. Suggested screening gates for owner review: ≥500 scored held-out forecasts per market over ≥10 weekly folds; Brier improvement ≥0.005 with log loss no worse; or MAE improvement ≥0.5 points with RMSE no worse; week-block bootstrap 95% improvement interval above zero; calibration error ≤0.03 in adequately populated bins; and stable results across seasons. Ranking claims need the larger Top 5 sample above. Confidence 1–5 should be derived from held-out calibrated reliability bins, with ≥100 decided observations per bin and merged/withheld bins when unsupported. The thresholds here are proposals, not already approved policy.

Report ATS%, hypothetical after-vig ROI, margin/total errors, Brier/log loss, calibration, rank monotonicity and drawdown by week; true CLV stays missing until prospective qualified quotes exist. Use nested earlier-fold selection for all grids, correct or explicitly limit multiple comparisons, and reserve an untouched final season plus newly sealed prospective weeks. All current time-split tables are retrospective research replays, even though each fitted mean uses only earlier weeks. No candidate has passed this acceptance plan.

## 8. Delivery and controls

The evidence-only patch adds the independent diagnostic script, a disposable-copy verification utility, 12 acceptance tests, generated diagnostic evidence, recovered pregame Git artifacts with their hashes/commit references, and these documents. Schema changes: none. New dependencies: none (standard library plus existing pytest). No production models, v2.8 configuration, original audit files, locked lines, weekly selections, or database files are modified. No workflows are enabled and no wagers are placed.

See [verification and completion record](WEEK7_ACCEPTANCE_VERIFICATION.md) for exact commands, failures, current-environment results, changed files, risks, and rollback. Merge remains **HOLD** pending the prerequisite reviews, checkout-custody/overwrite/verifier fixes, and clean relevant checks. Even after those fixes, the archived audit must continue to say INCOMPLETE for CLV; merge of evidence must never be presented as completed CLV or approval of a new model.
