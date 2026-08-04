# AGENTS.md — CFB Betting System V3

## 1. Authority and scope

This repository is the isolated development copy of the College Football
Spread Betting System.

The original repository must never be modified as part of work performed in
this repository.

These instructions apply to every coding agent, automation, subagent, and
repository task unless the repository owner explicitly provides a narrower
instruction that does not weaken the safeguards below.

When instructions conflict, use this priority:

1. Data integrity and anti-lookahead controls.
2. Immutable contest-line requirements.
3. Explicit owner instructions.
4. This AGENTS.md.
5. Existing implementation conventions.

No agent may silently weaken a higher-priority requirement.

## 2. Required development workflow

Never commit directly to main.

Every implementation change requires:

- a dedicated feature or fix branch;
- a narrowly scoped change set;
- relevant automated tests;
- a written verification summary;
- a pull request against main;
- review before merge.

Do not combine unrelated refactors, schema changes, model changes, and
presentation changes in one pull request.

A task is incomplete until:

- all relevant tests pass;
- the complete diff has been reviewed;
- changed behavior is documented;
- data migrations are reproducible;
- acceptance criteria are explicitly demonstrated.

Do not claim tests passed unless they were executed in the current environment.

## 3. Production isolation

This repository is not production until the owner explicitly promotes it.

Do not:

- modify the original cfb-betting-system repository;
- enable scheduled production workflows;
- publish a competing production dashboard;
- add or rotate secrets;
- make live wagers;
- automatically promote model changes;
- run live API calls unless the task explicitly authorizes them.

Prefer fixtures and recorded provider payloads during development.

Never write secrets, tokens, credentials, or private keys into:

- source files;
- prompts;
- logs;
- test fixtures;
- issues;
- pull requests;
- documentation;
- database rows.

Only reference environment-variable names.

## 4. Core product contract

The system must evaluate every lined FBS game.

For the contest card:

- every lined FBS game must receive a side;
- every pick must receive Confidence 1 through 5;
- every weekly card must include a ranked Top 5;
- no lined contest game may be silently omitted;
- missing model data must use an explicit fallback hierarchy;
- every fallback must be recorded.

Contest selection, quantitative prediction, and sportsbook recommendation are
different products and must remain separate.

The system must distinguish:

1. Model forecast:
   projected margin, probability, uncertainty, and model metadata.

2. Contest pick:
   mandatory side, Confidence 1–5, rank, and Top 5 status.

3. Sportsbook recommendation:
   bet or no-bet, expected value, offered price, and stake decision.

A mandatory contest pick must never be represented as a recommended wager
unless it independently satisfies the betting policy.

## 5. Immutable locked lines

SplashSports or other contest lines captured for a week are immutable.

Once locked:

- they must never be overwritten by later market movement;
- they must remain the official grading and contest-selection line;
- later market prices must be stored separately;
- every lock must record timestamp, source, contest, season, week, matchup,
  raw team names, normalized team names, and provenance;
- corrections require an explicit correction record preserving the original
  value and the reason for correction.

Never silently substitute:

- current lines for locked contest lines;
- closing lines for opening lines;
- consensus lines for a specified real-book line;
- one provider's line for another without recording it.

The system must clearly distinguish:

- locked contest line;
- model-entry line;
- current market line;
- closing line.

## 6. Anti-lookahead requirements

Never weaken existing lookahead protections.

All prediction features must be point-in-time safe.

To predict a game, the system may use only information that was available
before that game's kickoff and before the relevant card generation timestamp.

Never use:

- current-week statistics containing the target game's result;
- season-final statistics to predict earlier games in that season;
- closing lines as prediction inputs when evaluating an opening-line strategy;
- future injury, roster, coaching, weather, or market information;
- full-season aggregates that include later games.

Missing data must not be silently converted to zero, a league average, or a
fabricated value.

Any fallback or imputation must be:

- explicit;
- documented;
- tagged in output;
- testable;
- auditable.

Prediction code must not bypass the sanctioned point-in-time access layer.

## 7. Model-development rules

The current EPA-only model is a baseline, not proof of a profitable betting
edge.

Do not claim profitability unless demonstrated through predefined,
out-of-sample evaluation.

No feature may be retained because it sounds persuasive.

Every model or feature change must use:

- walk-forward validation;
- point-in-time data;
- predefined acceptance criteria;
- comparison against the current baseline;
- out-of-sample metrics;
- documented rejection as well as acceptance results.

Do not relax acceptance thresholds after seeing results.

Do not optimize only ATS win percentage.

Where applicable, evaluate:

- ATS percentage;
- ROI after vig;
- CLV;
- margin MAE and RMSE;
- Brier score;
- log loss;
- probability calibration;
- drawdown;
- confidence-rank monotonicity;
- Top 5 performance versus the remaining card.

Do not rank confidence by raw model edge unless out-of-sample evidence supports
that relationship.

Confidence 1–5 must eventually be based on calibrated relative reliability,
not narrative strength or arbitrary labels.

## 8. Quantitative and manual adjustments

Raw model output must remain separate from human or qualitative adjustments.

Any injury, quarterback, coaching, travel, weather, motivation, or matchup
adjustment must record:

- category;
- affected team or side;
- numeric margin adjustment;
- confidence adjustment;
- timestamp;
- evidence;
- source;
- author;
- superseded adjustment, if applicable.

Never rewrite the raw model projection to hide a manual adjustment.

Outputs must show:

- raw model projection;
- each adjustment;
- final adjusted projection.

Manual adjustments must be audited independently to determine whether they
helped or hurt.

## 9. Database and migrations

Do not make ad hoc production schema changes.

Every schema change requires a versioned migration.

Migrations must be:

- ordered;
- repeatable;
- idempotent where practical;
- tested against a copy of the current database;
- reversible or accompanied by a documented recovery procedure.

Do not overload legacy columns with new meanings merely to avoid migration
work.

Predictions, contest cards, contest picks, sportsbook recommendations, manual
adjustments, and audits should be represented as separate entities.

Do not modify or regenerate data/cfb.db unless the task explicitly requires it.

Before any database mutation:

- create or use a disposable test copy;
- record pre-migration row counts;
- run integrity checks;
- verify post-migration row counts;
- confirm no unrelated records changed.

## 10. Reproducibility

Every official model run and card must be reproducible.

Store or reference:

- code commit SHA;
- model version;
- feature-schema version;
- configuration version;
- data snapshot identifier or hash;
- locked-line snapshot identifier or hash;
- generation timestamp;
- manual-adjustment history;
- contest and week identifiers.

Generated cards must not depend on undocumented local state.

Do not manually edit generated outputs to make them look correct.

Fix the source data, configuration, or generation code and regenerate.

## 11. Ingestion and provider data

Preserve raw provider responses or replayable fixtures where legally and
operationally practical.

For each ingestion run, record:

- provider;
- endpoint;
- request parameters excluding secrets;
- request time;
- parser version;
- response or payload checksum;
- rows accepted;
- rows rejected;
- rejection reasons;
- final status.

Normalize team names through one canonical resolver.

Do not add one-off team-name corrections in downstream model or reporting code.

Unexpected provider behavior must fail visibly or produce explicit quarantine
records; it must not silently pollute the primary dataset.

## 12. Data-quality gates

Before publishing an official card, verify:

- expected lined-game count;
- normalized matchup count;
- locked-line count;
- pick count;
- duplicate count;
- unresolved FBS-vs-FBS teams;
- stale-source status;
- missing feature status;
- missing model metadata;
- Top 5 count;
- Confidence coverage;
- fallback usage.

Official card generation must fail when:

- a locked contest game has no pick;
- locked lines are duplicated or altered;
- an FBS-vs-FBS matchup cannot be normalized;
- the Top 5 does not contain exactly five eligible games when five or more
  games exist;
- Confidence is outside 1–5;
- required provenance is missing.

Do not publish an incomplete card as though it were complete.

## 13. Testing requirements

Tests must target both normal behavior and failure modes.

Required test categories include:

- anti-lookahead adversarial tests;
- locked-line immutability;
- schema migrations;
- ingestion replay;
- team normalization;
- duplicate prevention;
- every-game contest coverage;
- fallback hierarchy;
- Confidence bounds;
- Top 5 ranking;
- reproducibility;
- grading and CLV;
- hook and key-number classification;
- workflow safety.

A test that only confirms the happy path is insufficient for a financial or
betting-critical control.

Never delete, weaken, skip, or rewrite an existing test solely to make a new
implementation pass.

Any changed test expectation must be justified in the pull request.

## 14. Weekly operating policy

Weekly lines are locked once, using the authorized contest source.

Tuesday through Saturday, new information may revise:

- selected side;
- Confidence;
- Top 5 status;
- sportsbook recommendation;
- manual adjustment.

New information must never revise the locked contest line.

Every revision must retain:

- prior value;
- new value;
- timestamp;
- reason;
- data and model versions.

Model logic and policy rules must not be changed midweek.

Midweek changes are limited to:

- refreshed data;
- documented contextual adjustments;
- bug fixes required to preserve correctness;
- explicit data corrections.

Any bug fix or data correction affecting an official card must preserve both
the pre-fix and post-fix outputs and clearly identify the official version.

## 15. Postgame audit

Every official pick must be graded.

The audit must record:

- final score;
- ATS win, loss, or push;
- locked contest line;
- closing line;
- CLV;
- hook outcome;
- key-number crossing;
- favorite or underdog;
- home, away, or neutral;
- spread bucket;
- confidence;
- rank;
- Top 5 status;
- raw versus manually adjusted result;
- applicable failure taxonomy.

Do not infer a backdoor cover solely from the final score when scoring-sequence
or play-by-play evidence is required.

Weekly diagnostics must include at least:

- favorites versus underdogs;
- home versus away;
- spread buckets;
- road favorites;
- Confidence levels;
- Top 5 versus remaining card;
- raw model versus manual adjustments;
- CLV-positive versus CLV-negative picks.

Model-policy changes may be proposed only after the full weekly audit.

No rule is changed merely because of one bad beat or isolated outcome.

## 16. Version control and governance

Model, confidence, audit, and contest policies must be versioned.

Every official output must identify the active policy versions.

Rule changes occur only after:

- a completed audit;
- documented evidence;
- numeric justification;
- owner approval;
- a new version identifier.

Do not rewrite prior versions.

Preserve historical configurations so old cards can be reproduced.

## 17. Coding standards

Prefer clear modules over large multi-purpose scripts.

Avoid sys.path manipulation when proper packaging is feasible.

Use explicit types for critical data structures.

Use UTC internally for timestamps and record display timezone separately.

Use structured logging for production paths.

Avoid unvalidated JSON blobs when stable relational columns or typed models are
more appropriate.

Do not introduce a new dependency without documenting:

- why it is needed;
- its license;
- operational impact;
- reproducibility impact.

Do not perform broad cleanup or style refactoring inside a functional change
unless separately approved.

## 18. Required completion report

Every Codex implementation response and pull request must include:

1. Objective.
2. Files changed.
3. Schema changes.
4. Behavioral changes.
5. Tests added or modified.
6. Exact test commands executed.
7. Test results from the current environment.
8. Data-quality checks performed.
9. Known limitations.
10. Risks.
11. Rollback procedure.
12. Confirmation that no unrelated files changed.

Do not use vague statements such as "should work" or "appears correct."

Demonstrate the result.
