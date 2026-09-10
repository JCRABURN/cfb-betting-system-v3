# Totals shadow forecasting, audit, and unified Top-5 governance

## Scope and activation

Migration 21 adds an isolated, append-only totals domain and a generic
cross-market Top-5 candidate ledger. Both paths are `shadow` only.

Migration 22 extends that foundation without changing migration 21 or any ATS
table. It adds separately fitted home/away score custody, a manual shadow
weekly runner, complete totals grading and CLV custody, OOS same-game
correlation evidence, a correlation-aware mixed ranking, the #5/#6 cutoff
gap, and a combined mixed-card audit. All migration-22 rows are immutable.

The production ATS contract is unchanged:

- `contest_picks` remains ATS-only (`home|away|pass`);
- every locked lined FBS game still receives exactly one ATS side and
  Confidence 1–5 through the existing full-card engine;
- the EPA-only ATS model, official Top 5, weekly controller, publication,
  revision, sportsbook, grading, diagnostics, dashboard, Product A, and
  Product B paths do not import or query the new services;
- no schedule or production activation flag is added.

Shadow consumers must call the new typed services explicitly. The public
dashboard is intentionally unchanged so an experimental O/U candidate cannot
be mistaken for an official ATS pick or recommended wager.

## Custody model

`contest_locked_lines.total` remains the only contest-total authority. A totals
shadow card resolves each line with `get_effective_locked_line_as_of()` at the
card generation instant. Callers cannot supply or override a total.

For every locked line visible at that instant, the card records exactly one of:

- a `total_card_candidates` row with the exact effective total, correction ID,
  projected total, uncertainty, O/U direction, raw normal-residual probability,
  legacy shadow Confidence, policy version, PIT timestamps, and provenance; or
- a `total_card_skips` row naming `missing_locked_total`,
  `missing_game_identity`, or `missing_total_prediction`.

A completion seal is rejected unless candidates plus skips cover every visible
locked line exactly once. Missing totals are never fabricated. Later
corrections are invisible to earlier cards; later cards use the corrected
total while preserving the original lock and correction history.

The model and policy tables are separately versioned and immutable:

- `total_model_runs` allows only `research` or `shadow` lifecycle stages;
- `total_model_predictions` stores a raw projected game total and uncertainty,
  plus feature-as-of coordinates and a feature snapshot hash;
- `total_reliability_policies` owns the legacy raw-probability transform,
  shadow Confidence thresholds, and the exact-forecast tie direction
  independently of ATS. It is not an empirical calibration policy.

Predictions and cards are rejected when a feature snapshot reaches the target
week, a timestamp looks forward, or generation occurs at/after kickoff.

## Totals baseline methodology

The model is `pit_epa_total_linear` version `pit-epa-total-linear-v1`. It is not
the `epa_only` margin model and does not reuse the ATS target.

Target:

```text
actual_home_points + actual_away_points
```

Features, all obtained through the sanctioned point-in-time stats accessor:

```text
home offense EPA/play
home defense EPA/play
away offense EPA/play
away defense EPA/play
```

The baseline is a ridge-stabilized linear regression with an intercept. Each
weekly rolling-origin fold trains only on observations from strictly earlier
season/week folds. Week-one prior-season fallback behavior is inherited from
the sanctioned access layer. No pace, injury, weather, roster, or other
unavailable historical feature is invented.

Uncertainty is the training-fold residual RMSE. A normal residual distribution
produces a raw O/U probability for the historical opening total. The legacy
`symmetric_logit_scale_v1` field names are retained for schema compatibility;
v1 uses an identity slope of 1.0 and is not empirically calibrated. Reports
must label this as `RAW MODEL PROBABILITY` and report empirical calibrated
probability as `NOT AVAILABLE`. An exact
forecast/line tie deterministically selects `under` under policy v1.

Historical totals select a non-null opening total under
`historical-totals-book-priority-v1`, ordered Bovada, DraftKings, then ESPN Bet.
There is no alphabetical fallback. Historical `fetched_at` values are retained
as `archive_ingested_at`; they do not prove market observation or original
quote time. Every current archive row is therefore labeled
`UNVERIFIED_ARCHIVAL_OPENING`, with `market_observed_at` and
`original_quote_at` unavailable rather than fabricated.

## Historical out-of-sample result

Command re-executed after the custody correction on 2026-09-09:

```text
python -m scripts.run_totals_research --seasons 2019 2020 2021 2022 2023 2024 2025 --minimum-training-examples 100
```

The command opens the database read-only and verifies its SHA-256 before and
after the run.

| Measure | Result |
|---|---:|
| Dataset observations | 4,830 |
| Explicit dataset skips | 121 missing pregame stats |
| OOS folds | 100 |
| Skipped early folds | 3 |
| OOS forecasts | 4,687 |
| Total MAE | 13.3592 points |
| Total RMSE | 16.7339 points |
| O/U decisions | 3,719 |
| Wins–losses–pushes | 1,897–1,784–38 |
| Win rate, excluding pushes | 51.5349% |
| ROI at −110 | −1.5987% |
| Brier score | 0.260473 |
| Log loss | 0.718477 |
| Expected calibration error | 0.088100 |

Reproducibility identifiers:

- authoritative database SHA-256:
  `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`;
- corrected dataset SHA-256:
  `72126e2bb6133b934e9afa6ab82a70f74cb8d3b7e797f6eee73bc8352e8c488a`;
- corrected OOS ledger SHA-256:
  `7aef0a7184c78d277fcd7a171f2be96a435daaf570d96155d6e04de487f1874b`.

The total-specific resolver correction added 11 decisions, removed none, and
changed the selected real-book row on one retained decision. The prior
spread-driven result was 3,708 decisions, 1,890–1,780–38, and −1.6672% ROI.
The corrected result remains negative and does not change the governance
conclusion.

The observed win rate does not clear the −110 break-even rate, ROI is
negative, and the probability diagnostics are not production-grade.

**TOTALS PRODUCTION ELIGIBLE: NO.**

The baseline remains `research_shadow_only`. No totals Confidence thresholds
or model version are promoted by this PR.

## Unified shadow Top 5

`unified_top_five_candidates` is a generic reference ledger. Each row contains
exactly one source identity:

- `ATS` → existing `contest_pick_id` plus an immutable
  `ats_shadow_calibrated_evaluation_id`; or
- `TOTAL` → `total_card_candidate_id`.

The unified service accepts ATS calibrated-evaluation IDs only. It reads the
probability and reliability-policy version from the sealed evaluation rows;
callers cannot assert either value. SQLite rejects an ATS candidate unless its
evaluation belongs to the run's exact card and calibration run, names the
exact contest pick and game, and supplies the exact stored probability and
policy version. `candidate_score` is constrained to that probability. Raw ATS
point edge and raw total point edge are not fields in the unified input or
ranking table, so cross-market raw-edge comparison is structurally
unavailable.

### Conservative ATS shadow reliability policy

The repository does not contain validation evidence sufficient to claim an
empirically calibrated ATS cover-probability model. Migration 21 therefore
records that limitation as `not_empirically_validated` and permits only the
shadow method `conservative_linear_margin_v1`.

For a contest pick with its exact ATS model prediction, the method calculates:

```text
home ATS advantage = predicted home margin + effective locked home spread
selected-side advantage = max(0, signed home ATS advantage)
shadow probability = min(policy cap,
                         0.50 + selected-side advantage * policy rate)
```

The initial governed fixture policy uses a rate of 0.005 probability per
margin point and a maximum of 0.60. Schema constraints permit no rate above
0.01 and no cap above 0.60. A pick without a model prediction receives exactly
0.50 rather than a fabricated advantage. This is a conservative, auditable
ranking transform, not a claim of empirical ATS calibration, profitability,
or wagering value.

Each immutable evaluation binds the contest card and pick, exact model run and
prediction when present, locked-line identity and point-in-time effective
timestamp, selected side, ATS model/version, calibration method and reliability
version, derived probability, generation timestamp, provenance, deterministic
evaluation key, and input hash. A completion seal proves one evaluation for
every pick before unified ranking can begin.

Ordering is deterministic:

```text
calibrated probability descending,
market type ascending (ATS before TOTAL),
source row ID ascending
```

The migration-21 default shadow policy sets `allow_multiple_per_game = false`. Ranking walks
the ordered pool and selects the first five distinct games. A policy may later
allow both markets from one game, but doing so requires a new immutable version
and supporting evidence. Completion is rejected unless every ATS pick and
every totals candidate has one unambiguous generic reference and the selected
count is exactly five whenever five eligible distinct games exist.

## Component-score shadow model

`pit-epa-component-total-linear-v1` fits home points and away points as two
separate ridge targets in every strict rolling-origin fold, then sums them.
It uses the same four point-in-time opponent-adjusted EPA level features as
the combined-target baseline. The manual weekly shadow runner fits only folds
before the target contest fold. SQLite rejects a component sum that does not
equal its parent total prediction. Missing target EPA remains an explicit
`missing_total_prediction` card skip. No production schedule imports this runner.

Historical component-score OOS results on the same 4,687 forecast games:

| Measure | Result |
|---|---:|
| Home score MAE | 10.2625 |
| Away score MAE | 9.7403 |
| Summed total MAE | 13.3611 |
| Summed total RMSE | 16.7368 |

The component version does not improve the v1 combined-target result and is
therefore also shadow-only.

## Comparative evaluation and rollout gate

On the corrected 3,719 lined OOS games, the model total is worse than simply
using the recorded market total as the point forecast:

| Forecast | N | MAE | RMSE |
|---|---:|---:|---:|
| EPA totals model | 3,719 | 13.1920 | 16.5321 |
| Recorded market total | 3,719 | 12.6080 | 15.8809 |

Season O/U ROI was +0.72% (2021), -4.61% (2022), +1.37% (2023), -1.31%
(2024), and -4.14% (2025). The 20+ point disagreement bucket was 3-10 with
-55.94% ROI, despite an average 91.17% raw normal-model probability. That region
is materially miscalibrated, not a promoted Confidence tier.

The proposed future sample gate is 2,243 OOS decisions, derived from a
one-sided 5% significance / 80% power normal approximation for a predeclared
55% alternative against the 52.381% -110 break-even null. Sample size alone is
not sufficient: a future candidate must also beat the market-total forecast,
show stable holdout seasons, positive after-vig ROI, and acceptable Brier/log
loss/calibration under an owner-approved versioned policy.

## Correlation-aware shadow ranking

The additive migration-22 ranking starts from each governed source row's
calibrated selected-side probability, never raw ATS or total point edge. When
the opposite market for the same game was ranked earlier, it derives a
concentration penalty from historical joint OOS outcomes:

```text
phi = correlation(ATS win indicator, totals win indicator)
weight = max(lower endpoint of the Fisher 95% interval, 0)
penalty = weight * sqrt(p1(1-p1) * p2(1-p2))
adjusted score = calibrated probability - penalty
```

No tuned correlation threshold is used. Same-game opportunities remain in the
pool and can both be selected; any selected pair receives an immutable flag.
Cells with no evidence or intervals that include zero receive no numeric
penalty and are explicitly labeled. Candidate rows reference their exact
earlier same-game candidate and evidence cell; SQLite recomputes and enforces
the penalty, source probability, and source reliability-policy custody.

The exact ATS prior-season walk-forward ledger joined to the corrected totals
OOS ledger on 3,712 games produced:

| Relation | N | Phi | 95% interval | Penalty weight |
|---|---:|---:|---:|---:|
| Favorite + Over | 547 | 0.1549 | 0.0720 to 0.2357 | 0.0720 |
| Favorite + Under | 282 | 0.0343 | -0.0829 to 0.1505 | 0 |
| Underdog + Over | 1,684 | -0.0863 | -0.1335 to -0.0387 | 0 |
| Underdog + Under | 1,060 | 0.0465 | -0.0137 to 0.1064 | 0 |
| Pick'em + Over | 24 | 0.2509 | -0.1697 to 0.5941 | 0 |
| Pick'em + Under | 9 | -0.1581 | -0.7441 to 0.5654 | 0 |

The completion seal stores rank-5 score, rank-6 score, and their exact gap.
The mixed audit records ATS and totals source-audit identities separately,
then reports combined W/L/P, ROI, CLV, and expected versus actual win rate so
combined performance cannot conceal either submodel.

## Totals postgame audit

Every totals candidate is graded against its exact locked total. The audit
resolves a closing total from a real `betting_lines` closing row at or before
kickoff; absence is `missing_closing_total`, never a fabricated close. It
stores final component scores, actual total, W/L/P, -110 unit result, totals
CLV, signed projection error, edge, Confidence, and explicit context/failure
statuses. Weather, QB/injury, overtime, garbage time, and late-score effects
default to `not_evaluated`; any evaluated status requires evidence.

## Verification and parity

The adversarial suite covers over and under selection, exact-line ties, missing
totals, future corrections, corrected-total PIT behavior, future features,
post-kickoff generation, immutable runs/predictions/selections/policies,
caller ATS probability and policy-version injection, cross-pick and cross-card
calibration substitution, schema-level probability and policy spoofing,
separate ATS and totals reliability versions, mixed-market ordering, one entry
per game, duplicate/ambiguous identity rejection, replay determinism, complete
candidate-or-skip coverage, and database-trigger enforcement.

The migration parity test runs the same Product A Tuesday controller fixture on
the migration-20 schema and the schema after migrations 21 and 22, then compares the complete typed result,
all pre-existing table rows, ATS side/Confidence/rank/Top-5 fields,
publication, and sportsbook output exactly. Existing revision, grading,
diagnostic, dashboard, and sportsbook suites are also run unchanged before and
after the additive code. Migration verification copies `data/cfb.db`, preserves
every existing row count, runs integrity and foreign-key checks, and confirms
the source hash is unchanged.

## Limitations and risks

- The baseline has no pace, play-count, weather, injury, or roster history.
- The normal residual probability model and identity calibration slope are not
  sufficiently calibrated for production.
- Historical O/U grading uses the genuine recorded opening total when present;
  games without one are forecast-scored but not O/U graded.
- Totals sportsbook recommendations and official mixed contest publication
  remain intentionally out of scope.
- The conservative ATS probability transform has not been empirically
  calibrated or validated for wagering; it exists only for auditable shadow
  cross-market ordering.
- This PR does not replace or modify the current official ATS Confidence,
  ranking, or Top-5 policy.
- Conference, pace, wind, QB, offensive-line, and defensive-personnel subgroup
  analysis remains unavailable because the authoritative historical snapshot
  has no governed rows for those inputs. No adjustment is fabricated.
- Current 2026 locked contest rows do not yet contain verified totals. The
  shadow card records explicit skips until an authorized source supplies them.

## Rollback and recovery

No existing table is altered and no authoritative row is migrated. Before any
authorized database deployment, keep the verified pre-migration copy. If the
schema must be rolled back before new shadow rows exist, restore that copy. If
shadow rows have been written, preserve the failed database for audit, disable
shadow callers, restore the copy, and ship a new forward migration. Never edit
migration-ledger rows or immutable shadow records in place.
