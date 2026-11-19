# Week 12: frozen source and qualified draft forecasts

The original November 17 SplashSports PDF contains **66 matchups, 66 paired ATS
lines and 66 totals**. All 66 reconcile to canonical teams, CFBD game IDs and
ESPN schedules without duplicates, unknown teams, spread-sign errors or kickoff
differences. The original eight-page PDF is preserved at
`data/ingest/2026-week12-splashsports/original.pdf`.

The production model and v2.8 policies are unchanged from approved main
`79fa442a3c15d8f3f7435721b3d90db368ae55df`. No v2.9 research was promoted.
Execution commit is `69d14465fdaf437f8bdec85e155d97c818c020b4`.

**This is not a certified calibrated combined contest card.** Governed ATS
uncertainty is null, every governed ATS confidence is 1, and its Top Five is
resolved by locked-line ID. The ATS research heuristic and the totals normal
residual probability are not a validated common probability scale. All eligible
raw projections are retained; calibrated probability and common calibrated rank
remain empty rather than invented. Research confidence labels are not calibrated
reliability. Contest chips are scoring allocations.

## Source time, execution time and custody

- PDF display: **November 17, 2026, 2:22 PM CST**, or 20:22 UTC. PDF metadata
  20:22:34 UTC corroborates the displayed offset. This is the print time, not a
  model forecast timestamp. All eight rendered pages were visually checked.
- Actual recovery: November 18, 19:06:51 UTC. Hash:
  `60d6ced55737fe6749a34f092735b3a613d75824ebfd9138de1aa429d393edd2`.
- Actual model/card generation: November 18, 19:16:40/19:16:53 UTC. The three
  Tuesday games were already elapsed and receive no retrospective prediction.
- The later initial delivery seal is recorded at its actual time in
  `initial-seal.json`. **61 games were still upcoming; the two Wednesday games
  had started.** Their recorded generation times precede kickoff, but the new
  seal does not establish pregame custody for them. Preserve both forecasts with
  this limitation; do not revise them or count them as independently forward
  sealed predictions. The three Tuesday games remain wholly unforecasted.
- Supplemental UMass preview receipt is after Wednesday kickoff. Its historical
  publication date does not make this retrieval pregame evidence. It is excluded
  from forecast adjustments and recommendation changes.

## Files to review

| Artifact | Location |
|---|---|
| Every original matchup, source line, normalized identity and kickoff | `data/ingest/2026-week12-splashsports/frozen-v1/` |
| Complete 66-game coverage, forecasts and explicit seal custody | `outputs/2026-week12-delivery/v2/full-card-66.csv` |
| All 132 markets: 126 forecasts, six unavailable rows and seal custody | `outputs/2026-week12-delivery/v2/all-132-markets.csv` |
| Five distinct research games with chips 5,4,3,2,1 | `outputs/2026-week12-delivery/v1/provisional-research-five.csv` |
| Original governed, ATS research, totals research and legacy mixed cohorts | `outputs/2026-week12-prospective/` |
| Model versions, feature/configuration hashes, raw components and DB-copy counts | `outputs/2026-week12-prospective/week12_model_manifest.json`, `week12_raw_model_components.json`, `week12_ingestion_manifest.json` |
| All-game weather, personnel, rest, travel and coaching coverage | `outputs/2026-week12-context/review-v2/` |
| Exact initial artifact and unchanged model-policy hashes | `outputs/2026-week12-delivery/initial-seal.json` |
| Tests, limits and rollback | `outputs/2026-week12-delivery/VERIFICATION.md` |

`v1` is the immutable original generated delivery. Its PREGAME_FORECAST status
describes the recorded generation timestamp, not the later seal; apply the
explicit two-game custody qualification above in every subsequent audit.
`v2` adds a custody column to every row without changing any v1 forecast or line:
61 forward-sealed games, two late-custody games and three unforecasted games.

## Legacy research five — weak, unvalidated

There was no ATS/totals quota. Sorting the legacy scores yields five totals,
but that sorting cannot establish that they are stronger than the ATS pool.

| Chip | Research selection | Raw projected total | Under edge | Raw uncalibrated CDF | Legacy confidence |
|---:|---|---:|---:|---:|---:|
| 5 | South Alabama–Southern Miss Under 66.5 | 50.743 | 15.757 | 82.67% | 5 |
| 4 | Houston–West Virginia Under 70.5 | 57.975 | 12.525 | 77.28% | 4 |
| 3 | Oklahoma State–Arizona State Under 61.5 | 48.998 | 12.502 | 77.24% | 4 |
| 2 | Memphis–Navy Under 66.5 | 54.710 | 11.790 | 75.93% | 4 |
| 1 | South Florida–Florida Atlantic Under 64.5 | 52.909 | 11.591 | 75.56% | 4 |

These are raw model outputs, not empirical success rates, calibrated confidence,
recommended wagers, or an approved official combined Top Five. No numeric
context adjustment was fabricated. The diagnostic flags all five as weak and
requires prospective calibration evidence before promotion.

The unchanged governed ATS five are UMass -3.5, Buffalo -1.5, Temple -2.5,
UCF -2.5 and Toledo -15.5, all confidence 1. The first two are now immutable
started-game records; their line-ID ordering is not a quality ranking.

## Context and adversarial review

The initial capture covers 63 games and 126 teams: 533 source records, 62 outdoor
hourly forecasts and one indoor venue. Three unavailable official-team pages
were recovered separately. B1G, Big 12 and ACC reports contain six teams with
initial reports and 44 teams still pending. The 427 extracted QB/OL/defensive
rows are statuses, not 427 absences. Missing ESPN injuries are **missing**, not
evidence of health. Season passing leaders are not confirmed starters.

The following findings inform risk review only; raw and adjusted model outputs
remain identical, with zero numeric adjustments:

- **Houston–West Virginia:** the [official November 18 preview](https://wvusports.com/news/2026/11/18/football-wvu-concludes-home-slate-with-meeting-against-21st-ranked-houston-on-saturday)
  reports Michael Hawkins Jr. questionable with an ankle bone bruise, Scotty
  Fox Jr. as the contingency and an offensive-line absence. It also reports
  severe explosive-play vulnerability on WVU's defense. That defensive risk
  works against the Under; the injury is not assigned an invented point value.
  Initial NWS forecast is mild with light wind. Final QB and OL clearance is
  still missing.
- **Oklahoma State–Arizona State:** the [official November 17 preview](https://thesundevils.com/news/2026/11/17/football-ready-for-final-home-game-against-oklahoma-state)
  describes Jake Fette's third consecutive start and ASU's improving rushing
  defense, but also a highly productive Oklahoma State offense. Those are
  competing mechanisms, not proof of a 77% Under. Final personnel reports are
  pending; the initial weather is calm.
- **Memphis–Navy:** [Memphis' official preview](https://gotigersgo.com/news/2026/11/15/football-memphis-navy-to-air-on-espn2)
  describes strong offensive production and Navy's rushing and possession
  profile. Offensive explosiveness is a direct Under risk. Its listed offensive
  component averages do not add to the stated total; do not ingest those prose
  figures as corrected quantitative features. Navy's longer rest is recorded
  separately, without an unsupported causal adjustment.
- **South Alabama–Southern Miss:** the [November 16 Southern Miss coaching interview](https://southernmiss.com/news/2026/11/16/football-blake-anderson-weekly-news-conference-the-south-alabama-game)
  identifies pressure, errors and unnamed injuries, without a complete player
  clearance report. Offensive difficulty can lower scoring, while turnovers
  can create short fields. Initial forecast has light wind, so weather provides
  little support for an extreme Under probability.
- **South Florida–Florida Atlantic:** the [official FAU recap](https://fausports.com/news/2026/11/14/football-florida-atlantic-stalls-in-tulsa)
  documents passing and receiving production that is an Under risk. Initial
  NWS forecast has modest wind and rain chances, not a demonstrated severe
  weather suppression mechanism. A prior USF preview has an earlier statistical
  cutoff and is not silently treated as current through Week 11.
- **Wednesday:** the initial passing-leader extraction has been corrected in
  review-v2 (`passingYards`, preserving review-v1). Both Wednesday rows are now
  frozen. The later UMass injury article is quarantined from pregame decisions.
- **Other games:** all-game rows record available conference QB, OL and defense
  statuses, passing leaders, weather, prior-game IDs, rest intervals, venue
  distances and season coaching records. These are explicit coverage fields;
  they do not certify all starting quarterbacks or every coaching change. Oregon
  and Clemson initial reports require final confirmation. Official-page capture
  alone is not a completed personnel review.

Travel is straight-line stadium distance, not a verified itinerary. Rest is
kickoff-to-kickoff time. Gusts, field condition, complete OL/defensive snaps and
many final starting assignments are unavailable. Current market observations
are kept separate from contest lines. No outcome from Week 12 is used in these
forecasts. Week 11 game results are legitimate prior-week model inputs; the
external model's Week 11 submitted selections are never an input.

## Daily operation through Saturday November 21

Append dated captures and revisions. Never overwrite original.pdf, frozen-v1,
the initial board, delivery-v1, the seal or earlier refreshes. Verify the seal
first. Refresh official personnel, weather, coaching and separate markets only
for games that have not started. Use the earlier of source and provider kickoff
when deciding eligibility. Stop an update if live status is stale or conflicting.

If fresh prior-week features justify rerunning the unchanged model, first run
`python -m scripts.capture_week12_readiness --output NEW_CAPTURE`, then
`python -m scripts.run_week12_execution --database NEW_DISPOSABLE_DB --capture NEW_CAPTURE --output outputs/2026-week12-refresh/NEW_RUN`.
The capture must be no more than five minutes old. Finalize that new run with
`scripts.finalize_week12_card`, its new output directory and eligible-lines.csv.
Never replace the initial 66-row history with an upcoming-only subset. Carry all
started-game rows forward exactly, including rank and membership.

Validate a complete proposed 66-row revision with
`python -m scripts.week12_revision_ledger --previous PRIOR_CARD --current NEW_CARD --as-of UTC_TIMESTAMP --reason REASON --model-version VERSION --evidence CAPTURE_MANIFEST --output outputs/2026-week12-refresh/NEW_REVISION.json`.
Every changed selection, projection, probability/score, confidence, rank or chip
retains its previous value, new value, timestamp, reason and provenance. A
zero-change refresh records an empty changes list. No new calibration or policy
is authorized midweek. ChatGPT reviews the draft PR; no self-merge or routine
owner review is required. Pause scheduled refreshes after Saturday morning.
