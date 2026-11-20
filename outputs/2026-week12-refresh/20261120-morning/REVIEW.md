# Friday November 20 refresh

All 66 historical rows and all 132 market rows are byte-identical to Thursday.
The initial 1,210-file seal verifies. Fresh CFBD/ESPN schedules, using the
earliest original/provider kickoff, identify 60 upcoming and six started games.
The started rows, including Rice–Temple, retain every original field. No
Thursday result is used as a new prediction feature. The three Tuesday
no-forecast games and two Wednesday late-custody forecasts remain qualified.

All seven prior-week statistical payloads are unchanged. This is an evidence
refresh, without a model rerun or numeric contextual adjustment. `revision.json`
records zero changes using the actual Friday decision timestamp and pinned
evidence. Current markets are stored separately from the frozen contest lines.

## Current provisional research five

| Chip | Selection | Projected total | Raw uncalibrated CDF |
|---:|---|---:|---:|
| 5 | South Alabama–Southern Miss Under 66.5 | 50.743 | 82.67% |
| 4 | Houston–West Virginia Under 70.5 | 57.975 | 77.28% |
| 3 | Oklahoma State–Arizona State Under 61.5 | 48.998 | 77.24% |
| 2 | Memphis–Navy Under 66.5 | 54.710 | 75.93% |
| 1 | South Florida–Florida Atlantic Under 64.5 | 52.909 | 75.56% |

These are weak/unvalidated legacy research selections. They are not an approved
calibrated combined contest five or sportsbook recommendations. ATS research
scores are a different heuristic scale; governed ATS confidence remains 1.
Chips are scoring allocations. No quota, invented probability, v2.9 promotion
or frozen v2.8 logic change was introduced.

## Material developments

- WVU QB Michael Hawkins Jr. changed from Questionable to Probable. Houston
  OL McKenzie Agnello changed from Probable to Available. These reduce earlier
  offensive availability concerns; they do not establish a final starter or
  a quantified effect on the Under. WVU's other defensive concerns remain.
- ASU OL Jarmaine Mitchell changed from Available to Out. Oklahoma State LB
  Ethan Wesloski changed from Probable to Available. OSU QB Drew Mestemaker
  remains Questionable. Opposing offensive/defensive effects cannot be combined
  into an invented point adjustment. Starter confirmation remains incomplete.
- The new [Memphis official preview](https://gotigersgo.com/news/2026/11/19/football-no-24-tigers-head-east-to-annapolis-for-saturday-game-at-navy)
  emphasizes strong Memphis offense and explosive plays, along with productive
  rushing from Navy QB Jackson Gutierrez. This is material counterevidence to
  confidence in the raw Under. Captured offensive totals differ across older
  team articles; none is substituted for the sealed statistical model input.
- USF–FAU now has 3–23% hourly precipitation probability, down from Thursday's
  35%, with 7–10 mph wind. The documented Kromenhoek/Van Buren distinction and
  pass-defense concerns persist. There is no strong weather rationale for
  promoting this Under. South Alabama–Southern Miss and Memphis–Navy have
  light 5 mph wind and no forecast precipitation; final personnel reports
  remain unavailable for those teams.

All personnel statements above come from the dated official conference raw
receipts and `conference-personnel.csv` in `20261120-review`. Available,
Probable and Exempt are retained as distinct provider statuses; none is
silently converted into a confirmed starting assignment or absence count.

## Broader ATS pool and coverage

The previous ATS research top ten was reviewed. UMass is started and untouched.
Michigan State CB Tyran Chappell changed from Available to Doubtful; the
Milivojevic Out/Fancher Questionable and OL concerns remain. Maryland,
Rutgers and Virginia Tech QB/OL concerns remain unresolved. Arkansas,
San José State, Colorado State, South Carolina and UAB still lack complete
final personnel clearance in this capture; absence of a report is not health.
South Carolina now has 39% precipitation probability and 9–12 mph wind;
San José State has 39% and 3 mph. Field conditions and gusts are unknown.
These observations do not provide calibrated reliability for the ATS ranks.

The capture covers 120 teams, 500 source records, 59 outdoor forecasts and
one indoor game. Compared with Thursday there are 340 context field changes,
48 new/changed personnel rows and separate market observations changed in
49 upcoming games. These are observation counts, not forecast changes.
Pittsburgh's official landing-page request was unavailable; its earlier
receipt, current conference report and other provider fields remain distinct.
Season coaching records are not confirmation of no coaching change. Travel
distance/rest remain explicit stadium-distance and kickoff-interval proxies,
not verified itineraries. Missing final QB/OL/defense reports remain missing.

## Verification and governance

The context and daily comparison have deterministic read-only replay commands
in CI. Added tests reject changed, missing and duplicated statistical payloads
before an evidence-only carry-forward, and verify exact Friday replay.
Previous card hashes are checked against Thursday's manifest. No original
PDF, frozen line, model output, historical audit artifact, protected DB or
external-model Week11 attribution was changed. Friday evidence is additive
to PR56's integration with approved main, with no schema or model promotion.
Saturday's 08:00 America/Chicago refresh remains active, then must pause.

Exact test commands, current-environment outcomes, source hashes and replay
checks are in `validation.json`. Rollback is limited to new operational
changes while retaining the dated receipts; no DB/schema rollback is needed.
Unrelated files and the original production repository remain untouched.
ChatGPT reviews and merges PR56; Codex does not self-merge.
