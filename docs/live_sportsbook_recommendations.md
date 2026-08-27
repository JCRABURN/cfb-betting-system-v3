# Live sportsbook recommendations

The live sportsbook board is a separate decision product from the mandatory
SplashSports contest card. Contest picks continue to use the immutable locked
SplashSports line. Live recommendations use only exact, provider-custodied
`opening` or `current` two-sided sportsbook offers.

`production-sportsbook-v1` is defined before live evaluation with these fixed
numeric controls:

- 14.0-point normal-margin residual standard deviation;
- minimum 1.5-point spread edge;
- minimum 54.5% estimated cover probability;
- minimum 2.5% expected value per unit risked;
- maximum odds age of 900 seconds;
- material refresh after 300 seconds, a 0.5-point spread change, or a five-cent
  American-price change;
- stake sizing at 10 units per unit of expected value, rounded down to 0.25u;
- maximum suggested stake of 1.0u.

The probability calculation is policy-versioned and uses the EPA-only model's
fair margin with the fixed residual distribution. It does not use contest
Confidence, rejected research models, a closing line, or future observations.
Every eligible book observation produces an auditable `BET` or `NO BET`; stale
recommendations are superseded by an explicit expired `NO BET` record. Earlier
records are immutable and remain available for audit.

The cloud operation result includes the current board with book, team/side,
offered spread and price, capture time, model fair spread, edge, cover and
break-even probabilities, expected value, suggested stake, reason, policy
version, and provenance. The evaluator has no wager-placement integration and
production results always report `wagers_placed: 0`.

Provider capture and evaluation can be invoked repeatedly before kickoff; the
material-update and freshness rules control regeneration. The owner-authorized
GitHub schedule adds explicit `sportsbook_refresh` entries without publishing a
new contest-card version. Each scheduled capture is bounded by the weekly call
cap and a live quota-reserve probe. A refresh fails visibly rather than
publishing when any remaining locked game lacks a current DraftKings
recommendation. No refresh mutates locked SplashSports lines or places wagers.
