# Week 10 contextual owner review — November 5, 2026

Objective: provide a separate prospective contest shortlist while preserving PR49's
sealed 57 ATS and 57 totals selections. Owner approval is **PENDING**. PR48 and PR49
remain **HOLD**. This is a human-review research recommendation, not a calibrated
sportsbook bet/stake recommendation or a change to Master Prompt v2.8.

The immutable input delivery is `bf3e359ba25c3013e6ecb5574c26306eaceddba9`;
model/card source remains `8afc2a3817fa811fdfe159c20b4b62cc6e8839e0`.
The separate decision is recorded at **2026-11-05 19:17:41.591559 UTC** (13:17 CST).
Thursday kickoffs are UTSA–FAU **November 6 00:30 UTC / Thursday 18:30 CST** and
JMU–Southern Miss **01:00 UTC / 19:00 CST**. Neither had started at review time.
Saturday selections are prospective candidates requiring later context review;
this document does not promise an unscheduled future refresh.

## Actual recommended five and ten-candidate comparison

All projections, contest lines, original confidence labels and uncertainty scales
below come directly from the sealed files. Positive ATS forecast means the selected
home team wins by that amount; Colorado State is projected to lose by 8.16.
The full JSON retains unrounded values. Human confidence is an ordinal judgment,
not a percentage; 2 means modest support with material uncertainty and 1 means weak.

| Human rank | Selection at locked line | Frozen forecast | Absolute model gap | Frozen uncertainty scale | Original market rank / confidence | Human confidence | Decision |
|---:|---|---:|---:|---:|---|---:|---|
| 1 | Missouri +2.5 vs Texas | Missouri by 7.397224 | 9.897224 | 18.282404 | ATS 3 / 1 | 2 | Include |
| 2 | Boston College +6.5 vs Florida State | BC by 4.301903 | 10.801903 | 18.282093 | ATS 2 / 1 | 2 | Include |
| 3 | UConn +6.5 vs North Carolina | UConn by 6.293335 | 12.793335 | 18.282231 | ATS 1 / 1 | 2 | Include |
| 4 | JMU–Southern Miss Under 58.5 | 47.415601 | 11.084399 | 16.733547 | Total 5 / 4 | 2 | Include |
| 5 | Air Force–Army Over 45.5 | 57.694351 | 12.194351 | 16.733547 | Total 4 / 4 | 1 | Include |
| 6 | West Virginia–Texas Tech Under 65.5 | 51.583589 | 13.916411 | 16.733547 | Total 3 / 4 | 1 | Alternative |
| 7 | Middle Tennessee +1.5 vs WKU | MTSU by 6.674065 | 8.174065 | 18.282283 | ATS 5 / 1 | 1 | Alternative |
| 8 | Colorado State +17.5 vs Boise State | Boise by 8.160542 | 9.339458 | 18.286330 | ATS 4 / 1 | 1 | Alternative |
| 9 | UTSA–FAU Under 73.5 | 56.622043 | 16.877957 | 16.733547 | Total 1 / 5 | 1 | Exclude from five |
| 10 | Texas State–Oregon State Under 72.5 | 56.221883 | 16.278117 | 16.733547 | Total 2 / 5 | 1 | Exclude from five |

The original combined research order remains **UTSA/FAU Under, TXST/OSU Under,
WVU/TT Under, AFA/Army Over, JMU/USM Under**. Three ATS candidates replace the first
three Unders only in this separate human-review artifact. There is no market quota.
ATS research scores (~.541–.564) and totals scores (~.746–.843) are different,
uncalibrated constructions; their magnitudes do not establish a superior totals win
probability. Every ATS gap is smaller than its approximately 18.28-point research
uncertainty scale. The totals scales are approximately 16.73 points. Neither scale
is presented as a validated prediction interval.

## Why these five

**Missouri:** home underdog with a frozen winning margin and solid defensive
efficiency. The initial SEC report lists Texas LT Trevor Goosby and RB Hollywood
Smothers out, with Colin Simmons, Ryan Wingo and Cam Coleman questionable. Missouri
RT Josh Atkins is also out. Texas's stronger defensive efficiency and the loss of
a +2.5 ticket on a three-point defeat cap confidence. No injury points are added;
some absences may already influence the cumulative inputs.

**Boston College:** favorable frozen home margin, passing defense and rushing QB
production, versus FSU's documented receiver/secondary absences. **Starting center
Michael Crounse is out** in the initial ACC report; the earlier depth chart is not
clearance. Rick Stockstill replacing Mike Norvell adds uncertainty, not an automatic
FSU downgrade. +6.5 does not cover a seven-point loss.

**UConn:** strongest ATS research gap and home offensive efficiency support.
However, UNC QB Billy Edwards Jr. just completed 28/34 for 341 yards and four TD
against Miami. UConn allowed Air Force two second-half drives over ten minutes.
Complete current OL/defensive medical clearance was not obtained; this is not a
high-confidence injury-based selection.

**JMU–Southern Miss Under:** JMU's official 18.9 points allowed per game and Southern
Miss's documented passing/protection inconsistency support a modest lean. The Sun
Belt game-day report lists Pettaway out and Southern Miss OL Luke Rogers and Greg
Nunnery available. Returning linemen could improve offense; availability does not
establish snap counts. Cromwell's 135 rushing yards last week, JMU's strong return
game, and Southern Miss's improving run offense remain Over risks. JMU scored on its
first three offensive possessions against Troy before a five-turnover game; its
21-point finish is not evidence of a collapsed offense. JMU's 39.1 season PPG also
includes 87 against FCS Wagner. Mild/calm Hattiesburg weather supplies little Under
support. No second injury adjustment is invented.

**Air Force–Army Over:** Army allowed Memphis TD on seven of eleven possessions and
554 yards; Air Force QB Kemper Hodges ran for 200 yards/four TD. The strongest
counterargument is possession scarcity: rushing shares of 84.6%/79.9%, about
9.38/9.12 eligible offensive drives per game and Air Force's long clock-consuming
drives. Those counts exclude garbage time and are not a forecast of possessions.
This is the least confident inclusion, with rivalry game flow and rain uncertainty.

## Large-gap totals and excluded ATS candidates

**Do not select UTSA–FAU Under 73.5 solely for the 16.88-point gap.** FAU's official
notes show Veltkamp at 28.43 completions/game, 71.8% completion and 23 passing TD;
Messer has 74 receptions. FAU leads combined return TD and its last three game totals
are 80, 100 and 89. Last week's unchanged FAU–UNT total forecast was 59.785256 versus
89 actual (+29.214744 actual-minus-forecast). This one miss is a relevant failure
example, not a fitted correction. Today's retrieved box score has 167 combined
pass/rush attempts and 1160 yards. The formal audit's 172/1167 record is preserved;
the difference remains unresolved and is not used to rewrite that audit. These
figures are box-score volume measures, not measured seconds between snaps. UTSA has
twelve days' rest versus FAU seven. Boca's captured forecast (77–79F, 6–7 mph wind)
does not supply a strong Under weather case. Veltkamp/Devillier and McCown/Tennison
are the listed QB depth orders, not final medical clearance for either offense.

**Texas State–Oregon State Under 72.5:** Oregon State reports 517.4 yards and 40.1
PPG, and Atkinson passed for 300+ yards in all eight games. TXST's previous game
included 67-, 44- and 72-yard passing TD, a 35-yard QB rushing TD and a pick-six;
non-offensive scoring explains only part of 91 total points. The frozen Week9 total
was 55.743943 (+35.256057 error). Frozen offensive PPA/success are .268/.493 for
TXST and .267/.488 for OSU. Both have defensive absences. Morning Corvallis rain and
14–21 mph wind, plus OSU's improved recent defense, are counterevidence favoring
Under; they do not justify fabricated numeric adjustments or erase offensive risk.

**WVU–Texas Tech Under** is first alternative: Tech's run defense supports it, but
Castellanos's new dual-threat offense has only one game in the inputs and WVU allows
32.3 PPG. **MTSU +1.5** has a smaller gap, weak defensive reliability and incomplete
personnel clarity. **CSU +17.5** faces a severe run-defense mismatch (261.1 rushing
yards allowed/game versus Riley's 131.1 rushing yards/game), OL/RB questions and
secondary absences. Boise's questionable QB does not imply its backup is ineffective:
Cutforth threw three late TD against Texas State.

## Custody, limitations and verification

Timestamped raw gzip responses, SHA-256 manifests, official SEC/ACC/Sun Belt/Pac-12
availability, team articles/PDF reading copies, ten NWS hourly forecasts, separate
CFBD market observations and ten ESPN previews are retained. The original sealed
lines and forecasts never consume these later observations. Compressed PDFs retain
the exact original bytes; redundant decompressed PDFs need not be committed.
Before first publication, trailing line whitespace was removed only from derived
reading copies. Original extraction bytes and the pre-packaging review/inventory
are retained as gzip archives with a normalization custody record. Provider bytes,
all decision rows and their timestamps are unchanged. No whitespace check is disabled.

The Sun Belt response was received **19:03:45 UTC**, after its **15:33:29 UTC**
publication. An earlier conversational warning incorrectly compared publication to
the morning capture and is corrected here explicitly. New uncommitted directory
labels were aligned with actual first-request timestamps; raw bytes and original
manifest timestamps were never rewritten. Directory-label corrections are retained.

`docs/week10-human-context-20261105.json` is the authored judgment input. The builder
copies numerical fields from the sealed board and writes only a new review version.
The read-only verifier checks exact ten-candidate coverage, all frozen values,
source/reading-copy hashes, exact checksum coverage, actual capture chronology,
weather/Sun Belt publication times, confidence bounds, pending approval and zero
numeric adjustments. Descriptive metrics for twenty teams replay directly from
sealed data through Week9. Any future revision must copy already-started rows
exactly, including human rank and membership; no recommendation may be backdated.

New files: two capture adapters, the separate review builder/verifier, one adversarial
test module, this document, the human judgment JSON and additive context/review
evidence. `.gitattributes` adds only byte-preservation rules for these new evidence
directories. No schema, database, application model, policy, sealed output, historical
hash expectation, CI/security setting or operational workflow is changed. Existing
untracked verification receipts belong to prior work and are not relabeled as tests
of this new change. CLV remains **INCOMPLETE**.

Commands for current-environment verification (exact results and tested commit are
reported in the PR completion record, never inferred from an earlier run):

```text
python -X utf8 -m scripts.build_week10_owner_review --brief docs/week10-human-context-20261105.json --output outputs/2026-week10-owner-review/20261105-afternoon-decision
python -X utf8 -m scripts.verify_week10_owner_review outputs/2026-week10-owner-review/20261105-afternoon-decision/owner-review.json
python -X utf8 -m pytest -q tests/test_week10_owner_review.py tests/test_week10_continuity.py tests/test_week10_sealed_board.py
python -X utf8 -m pytest -q
python -X utf8 -m scripts.verify_week10_acceptance
python -X utf8 scripts/verify_repo_safety.py
```

PR49 still targets the PR47 branch. Existing CI only triggers on PRs into main;
there is no GitHub check at this Week10 head. Do not retarget or rebase ahead of
PR48's genuine non-author approval and verified main integration. Native tests do
not substitute for that pending Linux/Windows GitHub integration matrix.

Rollback: revert the additive review implementation if needed while retaining the
captured evidence and all sealed versions. No database restoration is needed.
No unrelated tracked changes are included. No owner contest approval is asserted.
