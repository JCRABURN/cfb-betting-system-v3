# WEEK 5 2026 POSTGAME AUDIT

This grades the frozen local governed-draft ATS card and shadow-only totals card; it does not create wagers or alter pregame selections. All results are from the captured ESPN Week 5 scoreboard and 56 game summaries, independently reconciled to an NCAA-derived scoreboard feed. Each provider response was retrieved after completion and preserved with raw SHA-256 and UTC retrieval time.

## Frozen pregame state

Contest: `splashsports-cfb-2026-w05`. Pregame code SHA: `1de0ff6e6e33013242d3b4bf5dc1d66e8f1d3d98`. Card generated: `2026-10-01T03:55:14.210152+00:00`. ATS model: `epa-only-linear-v1`; ATS data hash: `661796a7f200728559456e18f100d71c837f6975a38945b07737cbd147dace76`. Totals model: `pit-epa-component-total-linear-v1`; totals data hash: `d47f87674b178a72a0274930bd65d649c3937fed24c1b2a4f0b0e4f7073fda9c`. Locked-line snapshot: `0e9705b44349587bb3d54ff7a22e6b0159a6fbd9a04fe1f7862759cc143543aa`. Source DB hash: `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`. The 56 ATS picks, 56 shadow totals, deterministic governed ATS Top 5, seven-game analytical ATS shortlist, five-game human decision shortlist, shadow totals watchlist and combined shadow Top 5 are read from the unchanged pregame files. The governed ATS Top 5 is lock-ID ordered, not strength ranked. All governed Week 5 Confidence values are 1.

## Result and grading gates

56/56 locked game IDs have unique completed final scores; duplicate IDs 0, missing scores 0, postponed/cancelled graded 0. ESPN scoreboard, ESPN game summary and NCAA-derived final scores agree for all 56. Overtime games: 3. Home/away orientation matches the locked card except ESPN's malformed `San Jos� State` text, reconciled explicitly by identical game ID, away name and provider home/away assignment; the locked name was not changed. For a home ATS pick, grading margin = actual home margin + locked home spread; for an away pick, it is the negative of that quantity. For Over, grading margin = actual total − locked total; Under uses its negative. Positive wins, zero pushes, negative loses. One unit is risked at -110 per selection; a win earns 10/11 units, loss costs 1, push earns 0, and ROI divides by all graded selections.

## Week 5 records

- All ATS: **34-22-0 (15.91% ROI at -110)**; units 8.909091.
- Shadow totals: **23-33-0 (-21.59% ROI at -110)**; units -12.090909; **SHADOW / NOT PRODUCTION ELIGIBLE**.
- Governed deterministic ATS Top 5: **3-2-0 (14.55% ROI at -110)**.
- Analytical ATS shortlist: **3-4-0 (-18.18% ROI at -110)**.
- Human decision shortlist: **2-3-0 (-23.64% ROI at -110)**.
- Shadow totals Top 5: **3-2-0 (14.55% ROI at -110)**.

## Human decision shortlist: result quality versus decision quality

| Review rank | Game | Frozen SplashSports selection | Final away-home | ATS result | Grading margin | Qualified CLV | Decision quality |
| ---: | --- | --- | --- | --- | ---: | --- | --- |
| 1 | Pittsburgh @ Virginia Tech | Pittsburgh +3.5 | 35-33 | WIN | 5.5 | UNAVAILABLE | INDETERMINATE_WITHOUT_VERIFIED_CONTEXT_AND_CLV |
| 2 | Alabama @ Mississippi State | Mississippi State +5.5 | 56-23 | LOSS | -27.5 | UNAVAILABLE | INDETERMINATE_WITHOUT_VERIFIED_CONTEXT_AND_CLV |
| 3 | Cincinnati @ Arizona | Cincinnati +7.5 | 7-34 | LOSS | -19.5 | UNAVAILABLE | INDETERMINATE_WITHOUT_VERIFIED_CONTEXT_AND_CLV |
| 4 | Penn State @ Northwestern | Northwestern +2.5 | 13-34 | WIN | 23.5 | UNAVAILABLE | INDETERMINATE_WITHOUT_VERIFIED_CONTEXT_AND_CLV |
| 5 | Liberty @ Delaware | Delaware +7.5 | 30-14 | LOSS | -8.5 | UNAVAILABLE | QB_EXPECTATION_WEAKENED;CAUSAL_EFFECT_UNVERIFIED |

All five are graded at their frozen SplashSports numbers. The October 1 DraftKings observations are preserved separately. Post-review QB/injury changes and game-day weather causation are not established by the captured evidence, so a cover is not treated as proof of good logic and a miss is not treated as proof of bad logic. Each row's mechanical outcome is determined by actual home margin plus its locked home spread; specific causal claims remain unverified. One concrete QB-role mismatch emerged: the Oct 1 review listed Nick Minicucci as Delaware's probable QB, while ESPN's postgame boxscore identifies EJ Archield Jr. as Delaware's leading passer. That weakens the review's QB certainty premise but does not establish who started, an injury, or the cause of the ATS loss.

The best observed decision outcomes by locked ATS grading margin were Northwestern (+23.5 points) and Pittsburgh (+5.5 points); the worst were Mississippi State (-27.5 points) and Cincinnati (-19.5 points). This ranks results, not decision quality.

### Human layer versus pregame comparators

The raw-edge Top 5 comparator sorts only frozen pregame absolute edges; it is not an official or retrospectively altered card.

| Group | W-L-P and ROI | Mean ATS grading margin | Measured 14+ model misses | Qualified CLV |
| --- | --- | ---: | ---: | --- |
| full card | 34-22-0 (15.91% ROI at -110) | +0.61 | 24/56 | UNAVAILABLE |
| governed deterministic top five | 3-2-0 (14.55% ROI at -110) | +7.30 | 2/5 | UNAVAILABLE |
| analytical ats shortlist | 3-4-0 (-18.18% ROI at -110) | -3.64 | 4/7 | UNAVAILABLE |
| human decision shortlist | 2-3-0 (-23.64% ROI at -110) | -5.30 | 4/5 | UNAVAILABLE |
| raw edge top five comparator | 3-2-0 (14.55% ROI at -110) | +2.70 | 3/5 | UNAVAILABLE |

## CLV and close provenance

ESPN game summaries contain DraftKings `open` and `close` fields, but do not provide a quote-observed or closing timestamp. The audit records those provider-labeled numbers and an explicitly *indicative* locked-versus-provider difference, but all 112 qualified ATS/totals CLV values are **UNAVAILABLE**. The ESPN retrieval time is after the games and is not substituted for a pre-kickoff close timestamp. Thus ATS CLV-positive/negative records, decision-shortlist CLV, Top-5 CLV, shadow totals CLV and CLV/outcome correlation are unavailable, not zero.

## Hook, key number, and late-score evidence

Hook classifications require the actual ATS grading margin to equal ±0.5 on a half-point selection. Key-number classifications require a final margin of exactly 3 or 7 and a grading margin within one point of the boundary. The detailed game-by-game table records one-point boundaries separately. Late-score classification uses ESPN scoring-play sequence, clock and before/after cover state; it never infers a backdoor solely from the final. The late window is the final five minutes of regulation or overtime. BACKDOOR_COVER requires a selected-team score from an outright deficit into an ATS win while still losing outright. BACKDOOR_FAILURE requires a selected-team score from an outright deficit that improves the locked-line ATS margin, with a final ATS loss. LATE_FRONTDOOR_COVER requires a selected-team score into an ATS win without the backdoor-cover conditions. Other late scores are LATE_SCORE_NONDETERMINATIVE; absent or incomplete scoring sequences are NOT_EVALUATED_NO_PBP; no late score is NOT_APPLICABLE. UTEP–New Mexico's ESPN scoring-play list ends 7–60 while both final-score feeds say 7–61, so its late-score class is withheld as NOT_EVALUATED_NO_PBP with a partial-sequence flag. Observed late-score class counts: `{"BACKDOOR_FAILURE": 7, "LATE_FRONTDOOR_COVER": 4, "LATE_SCORE_NONDETERMINATIVE": 25, "NOT_APPLICABLE": 19, "NOT_EVALUATED_NO_PBP": 1}`.

### Scoring-sequence-backed backdoor failures

Scores are away-home. The late score is the score immediately after the identified scoring play.

| Game | Frozen pick | Before late play | Late score | Final score | Final ATS |
| --- | --- | --- | --- | --- | --- |
| Cincinnati @ Arizona | Cincinnati +7.5 | 0-34 | 7-34 | 7-34 | LOSS |
| Texas State @ San Diego State | Texas State -4.5 | 22-31 | 29-31 | 29-31 | LOSS |
| North Texas @ Tulsa | Tulsa -1.5 | 45-38 | 45-44 | 45-44 | LOSS |
| Eastern Michigan @ Massachusetts | Massachusetts -5.5 | 38-7 | 38-14 | 38-14 | LOSS |
| Georgia Southern @ Coastal Carolina | Coastal Carolina +2.5 | 31-17 | 31-24 | 31-24 | LOSS |
| Liberty @ Delaware | Delaware +7.5 | 30-6 | 30-14 | 30-14 | LOSS |
| UL Monroe @ South Alabama | UL Monroe +13.5 | 28-52 | 35-52 | 35-52 | LOSS |

## Large edges, calibration, and model misses

All 23 absolute raw ATS edges ≥7 points: **10-13-0 (-17.00% ROI at -110)**, versus **24-9-0 (38.84% ROI at -110)** below 7. Mean large edge 10.26 points; mean ATS grading margin -3.76. Prior FCS exposure is flagged in 22/23, prior 35+ point blowout in 21/23, and QB uncertainty in 22/23. These are pregame exposure flags, not proven causes. For context, the recorded Week 1 local draft was 10-18-0 (-31.82% ROI at -110) at edge ≥7 and 8-7-0 (1.82% ROI at -110) below 7; complete comparable edge cuts for Weeks 2–3 are unavailable in the frozen prior audit. Raw-edge/ATS-win Pearson r=-0.16067 (n=56); shadow-uncertainty/win r=-0.015511; October 1 locked market advantage/win r=-0.106967. All ATS Confidence values are 1, so confidence monotonicity cannot be assessed. Measured home-margin error variance is 371.89 points squared. No large-edge threshold is promoted from this one week.

### Largest measured model-margin misses (14+ points)

`MODEL_PROJECTION_FAILURE` here denotes a measured 14+ point home-margin error, not a proven causal failure. The FCS, opponent-strength, QB, weather, turnovers and game-script hypotheses remain unassigned without game-specific causal evidence.

| Game | ATS result | Actual minus projected home margin | Code |
| --- | --- | ---: | --- |
| Eastern Michigan @ Massachusetts | LOSS | -49.2 | MODEL_PROJECTION_FAILURE |
| Middle Tennessee @ Kansas | LOSS | +47.9 | MODEL_PROJECTION_FAILURE |
| Stanford @ Wake Forest | LOSS | +42.7 | MODEL_PROJECTION_FAILURE |
| Memphis @ Charlotte | LOSS | -41.4 | MODEL_PROJECTION_FAILURE |
| Virginia @ Florida State | LOSS | +39.5 | MODEL_PROJECTION_FAILURE |
| Alabama @ Mississippi State | LOSS | -34.8 | MODEL_PROJECTION_FAILURE |
| Baylor @ Arizona State | WIN | -33.8 | MODEL_PROJECTION_FAILURE |
| Oregon State @ Colorado State | LOSS | -31.6 | MODEL_PROJECTION_FAILURE |
| Florida @ Missouri | WIN | +30.4 | MODEL_PROJECTION_FAILURE |
| Bowling Green @ Miami (OH) | LOSS | -25.1 | MODEL_PROJECTION_FAILURE |
| Cincinnati @ Arizona | LOSS | +23.3 | MODEL_PROJECTION_FAILURE |
| UTEP @ New Mexico | WIN | +21.9 | MODEL_PROJECTION_FAILURE |

## Cumulative 2026 and totals gate

Recorded local-draft Weeks 1–2 ATS: 42-50-0 (-12.85% ROI at -110). Week 3 provisional ATS: 27-29-0 (-7.95% ROI at -110). Week 4 has no replay-safe stored picks and is excluded. With Week 5, all recorded/provisional ATS: 103-101-0 (-3.61% ROI at -110); Top 5: 7-13-0 (-33.18% ROI at -110). Recorded shadow totals Weeks 2, 3 and 5: 73-88-0 (-13.44% ROI at -110). The historical totals OOS ledger (2019–2025) remains separate: 1,897-1,784-38, -1.62% ROI, with archival opening-quote time custody unverified. Week 5 does not satisfy a predefined promotion gate; totals stay SHADOW_ONLY. Prior-week aggregate spread bins differ from the requested Week 5 bins and do not expose a complete raw-edge segmentation; incompatible bins are not silently pooled.

Combined comparable cuts: favorite 26-29-0 (-9.75% ROI at -110), underdog 77-72-0 (-1.34% ROI at -110), home 45-44-0 (-3.47% ROI at -110), away 58-57-0 (-3.72% ROI at -110), road favorite 4-7-0 (-30.58% ROI at -110), and remaining card 96-88-0 (-0.40% ROI at -110). See `week5_diagnostics.json` and `week5_cumulative_2026_diagnostics.json` for every computable segment, units, win rate and ROI.

## Audit limitations and recovery

No timestamp-qualified closing market feed, verified post-review QB/injury ledger or observed game-day weather ledger was available in the captured evidence. Those missing observations limit decision-process, CLV and causal attribution conclusions. The pregame card, policies, locked lines, source DB, and master prompt were not edited. Rollback: close the audit PR or revert its commit; the frozen Week 5 files and source DB remain intact.
