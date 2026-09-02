# Totals shadow forecasting and unified Top-5 foundation

## Scope and activation

Migration 21 adds an isolated, append-only totals domain and a generic
cross-market Top-5 candidate ledger. Both paths are `shadow` only.

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
  projected total, uncertainty, O/U direction, totals-only calibrated
  probability, Confidence, policy version, PIT timestamps, and provenance; or
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
- `total_reliability_policies` owns totals probability calibration, Confidence
  thresholds, and the exact-forecast tie direction independently of ATS.

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
produces the O/U probability for the historical opening total. The totals-only
`symmetric_logit_scale_v1` calibration channel is independent of ATS; v1 uses
the pre-registered identity slope of 1.0 and reports its observed calibration
error rather than claiming it is calibrated enough for production. An exact
forecast/line tie deterministically selects `under` under policy v1.

## Historical out-of-sample result

Command executed on 2026-08-31:

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
| O/U decisions | 3,708 |
| Wins–losses–pushes | 1,890–1,780–38 |
| Win rate, excluding pushes | 51.4986% |
| ROI at −110 | −1.6672% |
| Brier score | 0.260713 |
| Log loss | 0.718995 |
| Expected calibration error | 0.088374 |

Reproducibility identifiers:

- authoritative database SHA-256:
  `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`;
- dataset SHA-256:
  `eae48d76526f4e47670a2aee37a8e6ac6f55d5b92bc5dc74d72d775b01aa0cfa`;
- OOS ledger SHA-256:
  `2a9d589abd144562470a71f4cc53f01b912b20868f3883e8b617e44c8e402879`.

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

The default shadow policy sets `allow_multiple_per_game = false`. Ranking walks
the ordered pool and selects the first five distinct games. A policy may later
allow both markets from one game, but doing so requires a new immutable version
and supporting evidence. Completion is rejected unless every ATS pick and
every totals candidate has one unambiguous generic reference and the selected
count is exactly five whenever five eligible distinct games exist.

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
migration 20 and migration 21 schemas and compares the complete typed result,
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
- Totals postgame audit, totals sportsbook recommendations, and official mixed
  contest publication are intentionally out of scope.
- The conservative ATS probability transform has not been empirically
  calibrated or validated for wagering; it exists only for auditable shadow
  cross-market ordering.
- This PR does not replace or modify the current official ATS Confidence,
  ranking, or Top-5 policy.

## Rollback and recovery

No existing table is altered and no authoritative row is migrated. Before any
authorized database deployment, keep the verified pre-migration copy. If the
schema must be rolled back before new shadow rows exist, restore that copy. If
shadow rows have been written, preserve the failed database for audit, disable
shadow callers, restore the copy, and ship a new forward migration. Never edit
migration-ledger rows or immutable shadow records in place.
