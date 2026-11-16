# 2026 season — recovered SplashSports contest entries (Weeks 1–11)

Owner supplied a ZIP of 11 PDF exports printed November 16, 2026, each labeled Entry 1 in the same contest. All 621 visible matchups and 55 selected entries were extracted from native text and button-outline geometry. Every week has exactly five selected entries with weights 1–5 (15 possible points). All selected lines and opposing spreads were validated against the displayed boxes. CSV bytes were independently verified against their Git blob identities from the extraction runtime.

- `2026-splashsports-all-contest-lines.csv`: 621 original displayed line pairs, displayed kickoff dates/times, team labels and records, PDF page, selected side/market/weight where applicable.
- `2026-splashsports-submitted-picks.csv`: 55 selected rows, sorted by week and descending contest weight.
- `manifest.json`: SHA-256 of the original ZIP and each PDF, row/page counts, output hashes, custody qualifications.
- Owner attestation: `data/ingest/2026-season-owner-model-origin-attestation.json`.

## Critical corrections to the audit

The Week 11 actual submitted card is **not** the PR #53 Friday contextual-review card. All five selection identities differ:

| Weight | Actual selected entry |
|---:|---|
| 5 | Wake Forest +1.5 at SMU |
| 4 | Penn State -8.5 vs Minnesota |
| 3 | Boise State -12.5 vs Oregon State |
| 2 | Texas Tech–Oklahoma State UNDER 73.5 |
| 1 | Duke–Miami (FL) OVER 53.5 |

Week 5's submitted fifth pick is Texas Tech -13.5, not Delaware +7.5 in the earlier context-review shortlist. Week 7's five match the corrected owner approval (including Under 69.5), but its contest scoring weights are 5/4/3/2/1, distinct from original model/context confidence. Week 4's five match the screenshot recovery: 3–2, 8/15 points, subject to independent provider reconciliation.

## Audit rules

Grade the 55 actual contest entries against the lines in these PDFs and independently reconciled final scores; keep separate frozen statistical, governed, research and AI-contextual cohorts. Where the displayed contest line differs from a frozen original model line, preserve both with explicit provenance. Match by season, week, canonical matchup/game ID, market and selection, not row order or mutable kickoff alone. Example: Week 11 Ole Miss–Oklahoma is displayed Sunday November 15; Utah–Arizona has a revised Saturday kickoff. Preserve the original timestamped source rather than replacing it.

No postgame export proves the original model generation timestamp, model version, calibrated probability, or pregame cryptographic seal. Blank selection fields mean no submitted pick on that game, not a model skip or a model prediction. Do not invent Week 4 full-card forecasts. The original PDFs contain no final scores; all grades except the existing screenshot-reported Week 4 results remain to be reconciled. Never count one submitted pick twice as independent evidence if a matching prior recommendation exists.

Original ZIP/PDF bytes were inspected and hashed in the delivering runtime; only extracted CSVs and metadata are committed here. The original binary archive remains the owner-supplied attachment, and must be retained separately with matching manifest hashes. No historical source, forecasts, policy or database modified.
