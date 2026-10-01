# WEEK 5 MODEL EXECUTION — READY FOR PICKS

**Local governed draft and shadow research only. No authoritative cloud publication or wager recommendation.**

Generated 2026-10-01T03:55:14.210152+00:00; execution code `1de0ff6e6e33013242d3b4bf5dc1d66e8f1d3d98`; contest `splashsports-cfb-2026-w05`.

## Readiness and source custody

The authoritative owner CSV reconciles to **56/56** Week 5 FBS matchups and 56 immutable spread-plus-total locks in the isolated execution database. Its normalized LF SHA-256 is `2f598560b4aed27a93615fc41a6577dedd041b52966c16bdc1cb393cc0e410e4`. The Windows checkout byte hash is `5c908c56af505308a80822221166ce19479086f00bdce174dbcad2aab013771e`. No original source database row was modified.

A Week 1 Pittsburgh–Miami (OH) kickoff moved by 30 minutes in CFBD; the original and corrected values are in the ingestion manifest. The Hawai‘i Week 5 CSV kickoff is one minute later than CFBD and remains explicitly visible in reconciliation. All 56 Week 5 predictions preceded their provider kickoffs. All current market observations remain separate from locked SplashSports lines.

Completed 2026 FBS-vs-FBS games ingested through Week 4: **215**. End-of-Week-4 EPA snapshots: **138** teams. Week 5 ATS forecasts: **56**; totals forecasts: **56**; model fallbacks: **0**; manual numeric adjustments: **0**.

DraftKings current spreads and totals matched **56/56**; outdoor kickoff forecasts **54/54**, with two dome games. ESPN listed only **3** team groups: missing rows are not evidence of health. Expected quarterbacks are unverified. FCS opponents appear in several teams’ prior schedules, and the aggregate CFBD EPA feed does not prove FBS-only isolation.

## Model trust

The main-policy ATS EPA-only model fits 4,830 historical rows from 2019–2025, using Week 4 snapshots for all Week 5 targets. It produces game-specific home margins but no game-specific uncertainty, so all governed Confidence values are 1 and the official-policy Top 5 follows deterministic lock-ID tie order. A separate out-of-sample residual-based uncertainty artifact yields a shadow ATS ranking, but its uncertainty ranges only about 18.282–18.304 points across this slate and does not establish five strong bets. No 2026 outcome was used to refit ATS coefficients; completed games affect only point-in-time Week 4 team features.

The component totals model is shadow-only. Its 2019–2025 rolling-origin evaluation produced 4687 projections, MAE 13.361, RMSE 16.737, and 1897-1784-38 against archived opening totals, ROI -1.62% at -110. Original quote timestamps are unverified. Its displayed normal probabilities are raw, not empirically calibrated. The unified ranking uses a conservative ATS transform and these raw totals probabilities; it is experimental and its five selections are not a calibrated cross-market betting card.

## Prior card audit

Week 1 local ATS card 18-25-0; Week 2 local ATS card 24-25-0. Combined recorded Weeks 1–2: 42-50-0; Top 5 3-7-0. Week 3's previously generated pre-kickoff provisional ATS card graded 27-29-0, provisional Top 5 1-4-0. Shadow totals across Weeks 2–3: 50-55-0. No Week 4 historical pick was fabricated. Full cuts are in `week5_prior_performance_audit.json`; complete CLV remains unavailable without timestamped closing custody.

## OFFICIAL ATS TOP 5 — governed selection order, local draft

Home spread and current DraftKings line are both stated as home-team spreads. Positive locked advantage means the locked selected-side price is better than current market. None is a wager recommendation.

| Rank | Game | Pick | Locked home | Home margin | Home ATS edge | Conf | DK home | Locked advantage | Game script | Primary risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | Western Kentucky @ New Mexico State | New Mexico State -2.5 | -2.5 | +15.2 | +12.7 | 1 | -2.5 | +0.0 | Independent forecasts imply Western Kentucky 18.8, New Mexico State 33.9; both implied scores are positive. | Main-policy ATS uncertainty is absent and all Confidence values are 1; FCS-game effects and QB status are unverified. |
| 4 | North Texas @ Tulsa | Tulsa -1.5 | -1.5 | +2.9 | +1.4 | 1 | +1.5 | -3.0 | Independent forecasts imply North Texas 24.6, Tulsa 27.5; both implied scores are positive. | DraftKings now gives the selected side 3.0 more points than the lock; QB/injury coverage is incomplete. |
| 3 | Liberty @ Delaware | Delaware +7.5 | +7.5 | -0.1 | +7.4 | 1 | +7.5 | +0.0 | Independent forecasts imply Liberty 24.0, Delaware 23.9; both implied scores are positive. | Main-policy ATS uncertainty is absent and all Confidence values are 1; FCS-game effects and QB status are unverified. |
| 2 | Pittsburgh @ Virginia Tech | Pittsburgh +3.5 | -3.5 | -1.0 | -4.5 | 1 | -3.0 | +0.5 | Independent forecasts imply Pittsburgh 25.7, Virginia Tech 24.7; both implied scores are positive. | Main-policy ATS uncertainty is absent and all Confidence values are 1; FCS-game effects and QB status are unverified. |
| 1 | Penn State @ Northwestern | Northwestern +2.5 | +2.5 | +1.0 | +3.5 | 1 | +2.5 | +0.0 | Independent forecasts imply Penn State 25.9, Northwestern 26.9; both implied scores are positive. | Main-policy ATS uncertainty is absent and all Confidence values are 1; FCS-game effects and QB status are unverified. |

## SHADOW ATS TOP 5 — research uncertainty order

| Rank | Game | Pick | Locked home | Home margin | Home ATS edge | Shadow uncertainty | Game script | Primary risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Cincinnati @ Arizona | Cincinnati +7.5 | -7.5 | +3.7 | -3.8 | 18.282 | Independent forecasts imply Cincinnati 25.6, Arizona 29.4; both implied scores are positive. | Main-policy ATS uncertainty is absent and all Confidence values are 1; FCS-game effects and QB status are unverified. |
| 2 | Ohio @ Kent State | Kent State +3.5 | +3.5 | +3.6 | +7.1 | 18.282 | Independent forecasts imply Ohio 24.8, Kent State 28.4; both implied scores are positive. | Main-policy ATS uncertainty is absent and all Confidence values are 1; FCS-game effects and QB status are unverified. |
| 3 | North Texas @ Tulsa | Tulsa -1.5 | -1.5 | +2.9 | +1.4 | 18.282 | Independent forecasts imply North Texas 24.6, Tulsa 27.5; both implied scores are positive. | DraftKings now gives the selected side 3.0 more points than the lock; QB/injury coverage is incomplete. |
| 4 | California @ UNLV | UNLV -2.5 | -2.5 | +5.5 | +3.0 | 18.282 | Independent forecasts imply California 19.7, UNLV 25.2; both implied scores are positive. | Main-policy ATS uncertainty is absent and all Confidence values are 1; FCS-game effects and QB status are unverified. |
| 5 | Georgia Southern @ Coastal Carolina | Coastal Carolina +2.5 | +2.5 | +5.9 | +8.4 | 18.282 | Independent forecasts imply Georgia Southern 22.5, Coastal Carolina 28.4; both implied scores are positive. | Main-policy ATS uncertainty is absent and all Confidence values are 1; FCS-game effects and QB status are unverified. |

## SHADOW TOTALS TOP 5

| Rank | Game | Pick | Locked total | Projected | Edge | Raw P | Conf | DK total | Locked advantage | Game script | Primary risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Auburn @ Tennessee | UNDER | 54.5 | 44.6 | -9.9 | 0.722 raw | 4 | 54.5 | +0.0 | Independent forecasts imply Auburn 16.7, Tennessee 28.0; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |
| 2 | Boston College @ SMU | UNDER | 55.5 | 46.4 | -9.1 | 0.707 raw | 4 | 55.5 | +0.0 | Independent forecasts imply Boston College 16.6, SMU 29.8; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |
| 3 | California @ UNLV | UNDER | 52.5 | 44.8 | -7.7 | 0.677 raw | 3 | 53.5 | -1.0 | Independent forecasts imply California 19.7, UNLV 25.2; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |
| 4 | Navy @ Air Force | OVER | 46.5 | 53.9 | +7.4 | 0.672 raw | 3 | 45.5 | -1.0 | Independent forecasts imply Navy 20.8, Air Force 33.1; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |
| 5 | Penn State @ Northwestern | OVER | 45.5 | 52.8 | +7.3 | 0.668 raw | 3 | 45.5 | +0.0 | Independent forecasts imply Penn State 25.9, Northwestern 26.9; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |

## COMBINED ATS/O-U TOP 5 — experimental shadow

| Rank | Game | Market | Pick | Locked line | Projection | Edge | Shadow score | Conf | DK line | Locked advantage | Game script | Primary risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Auburn @ Tennessee | TOTAL | under | 54.5 | 44.6 | -9.9 | 0.722 shadow | 4 | 54.5 | +0.0 | Independent forecasts imply Auburn 16.7, Tennessee 28.0; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |
| 2 | Boston College @ SMU | TOTAL | under | 55.5 | 46.4 | -9.1 | 0.707 shadow | 4 | 55.5 | +0.0 | Independent forecasts imply Boston College 16.6, SMU 29.8; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |
| 3 | California @ UNLV | TOTAL | under | 52.5 | 44.8 | -7.7 | 0.677 shadow | 3 | 53.5 | -1.0 | Independent forecasts imply California 19.7, UNLV 25.2; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |
| 4 | Navy @ Air Force | TOTAL | over | 46.5 | 53.9 | +7.4 | 0.672 shadow | 3 | 45.5 | -1.0 | Independent forecasts imply Navy 20.8, Air Force 33.1; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |
| 5 | Penn State @ Northwestern | TOTAL | over | 45.5 | 52.8 | +7.3 | 0.668 shadow | 3 | 45.5 | +0.0 | Independent forecasts imply Penn State 25.9, Northwestern 26.9; both implied scores are positive. | Component totals lost money out of sample and the ESPN injury feed covers only three teams. |

## What I would trust most

Trust the immutable source lines, CFBD schedule/results reconciliation, and the relative direction of the baseline EPA forecast more than its ranked Confidence or any betting probability. The main-policy ATS Top 5 is a deterministic tie order with no demonstrated reliability discrimination; the research uncertainty order barely discriminates and prior local cards and Top 5 have poor realized performance. Totals and unified outputs are useful experimental signals for review, but their negative out-of-sample ROI and unverified quote-time custody prevent treating them as recommended wagers.

## Reproduction, limits, and rollback

The complete 56-game ATS and totals cards, reconciliation, current market/weather/rest review, model manifest, freshness report, prior audit, and checksummed raw provider evidence are adjacent files. Replay uses the copied source database in `data/production_inputs/2026-week5-execution/` or a byte-identical `data/cfb.db`, the fixed provider evidence, and the scripts in this branch. The managed PostgreSQL production stream was not available, so the local locks are durable only in the isolated execution copy and this review branch. No model was promoted, production workflow enabled, card published to the dashboard, or wager placed.

Rollback consists of abandoning this branch and retaining the local evidence archive; the authoritative source database hash is unchanged. The Week 1 schedule correction exists only in the disposable execution copy. No unrelated tracked files were changed.
