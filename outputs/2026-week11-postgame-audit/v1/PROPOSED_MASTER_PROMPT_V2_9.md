# Proposed Master Prompt v2.9 — inactive research proposal

v2.8 remains the active policy. This document does not activate, overwrite or silently amend it. Owner approval and a new version are required after independent validation.

1. Preserve mandatory contest coverage and all existing data/line custody safeguards. Clearly distinguish model forecast, contest selection and sportsbook recommendation.
2. Require a model forecast baseline comparison against the original locked line. Begin with a regularized residual forecast. Keep every unsuccessful experiment.
3. Rank ATS and totals on a common OOS calibrated probability/reliability scale, with at most one selection per game. Do not force a market mix. Report overlap and week dependence.
4. Treat .525/.55/.58/.62 as candidate research bucket boundaries only. Do not translate raw edge, a Gaussian CDF or narrative conviction directly to high confidence.
5. If calibrated probability is absent, use Confidence1 and label the Top5 UNVALIDATED_FALLBACK. Deterministic canonical matchup ordering is bookkeeping only; never present a database ID as quality.
6. Add contextual completeness and model-fold reliability only after historical availability and incremental OOS value are demonstrated. Keep manual adjustments separate and timestamped.
7. For every validation fold, train only prior weeks, freeze rules, retain all eligible games/predictions and grade exact locked lines. Calibrate on prior OOF predictions, not in-sample fits or current outcomes.
8. Week11 is development input for newly designed methods. Reserve future weeks or a separately defined untouched holdout. No retrospective winner is called validated.
9. Proposed promotion gates are specified in v29_research_protocol.json:20 prospective weeks, paired week-block forecast and Top5 improvement, calibrated probabilities, ranking discrimination and cross-week stability. High confidence requires500 bucket cases (800 for5),20 weeks/two seasons,ECE<=.03 and lower95 cover bound above52.381%. These gates are proposals, not an approved policy.
10. Drive features require explicit regulation possession definitions, documented zero-play/end-half exclusions, nonoffensive TD separation, observed conversion points, overtime handling, consistent garbage-time rules, missingness, opponent adjustment and PIT receipt checks. Unresolved records remain quarantined.

| Architecture | Evaluation status | Next evidence required |
|---|---|---|
| Market-anchored residual | IMPLEMENTED_RETROSPECTIVE_RESEARCH | Simple fixed-penalty ridge on frozen forecast-minus-line; future holdout required. |
| Opponent-adjusted efficiency | BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER | Build weekly opponent schedule-adjusted offensive/defensive ledger through sanctioned PIT accessor. |
| Offense-defense matchup interactions | BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER | Regularized interactions only after point-in-time base features and fold sample audit. |
| Recency weighting | BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER | Require game-level EPA timestamps and consistent garbage-time definition. |
| Home-field and travel | PARTIAL_HOME_MARGIN_BASELINE_ONLY | Need neutral-site, stadium coordinates and known schedule/rest history; no fabricated travel. |
| Pace and possessions | FROZEN14_GAME_PROTOTYPE_GRADED_SEPARATELY | Resolve drive score quarantine before feature inclusion; exclude overtime consistently. |
| Expected points per drive | BLOCKED_DRIVE_ADJUDICATION | Separate offensive points from return/defensive points; validate conversion attribution. |
| Explosive offense versus defense | BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER | Stable rush10/pass20 definitions; no game-total or season-final contamination. |
| Red-zone efficiency | BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER | Standardize trip and touchdown definitions; shrink small denominators. |
| QB and personnel | BLOCKED_HISTORICAL_PIT_EVIDENCE | Only timestamped availability and snap expectations; observed postgame usage is not pregame knowledge. |

The executable research program evaluates a simple market-residual ridge with prior-OOF frequency ranking using frozen forecasts. Feature families without comparable PIT evidence are explicitly blocked; no fabricated personnel history, retrospectively refreshed feature, or synthetic drive result is used.
