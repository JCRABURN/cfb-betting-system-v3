# Controlled live-week shadow rehearsal

PR #21 adds a manually dispatched, cloud-hosted rehearsal path for one real
week. It uses an isolated managed-PostgreSQL stream and the existing EPA-only
contest engine. Production remains disabled, the production kill switch stays
engaged, schedules remain absent, and no wager-placement path exists.

The workflow is `.github/workflows/v3_shadow_rehearsal.yml`. Every run uses a
GitHub-hosted runner; the runner filesystem is disposable and is never the
authoritative state store. Durable state is keyed by:

`JCRABURN/cfb-betting-system-v3:shadow:<season>:week:<week>`

This is deliberately separate from the production stream.

## Required owner input and protected setup

The owner supplies the authoritative weekly SplashSports screenshot or
CSV/XLSX and resolves genuinely ambiguous rows. Engineering prepares the
reviewed, checksummed manifest and secret-free weekly configuration in the
workflow ref. No contest line may be inferred from a sportsbook feed.

The protected `v3-production` GitHub Environment must make these secrets
available without exposing their values:

- `CFB_V3_DATABASE_URL`
- `CFBD_API_KEY`
- `ODDS_API_KEY`

The environment must retain the production isolation values:

- `CFB_V3_PRODUCTION_ENABLED=false`
- `CFB_V3_OPERATION_EXECUTION_ENABLED=false`
- `CFB_V3_KILL_SWITCH=true`
- `CFB_V3_OWNER_CUTOVER_APPROVED=false`

The rehearsal has independent authorization values:

- `CFB_V3_SHADOW_REHEARSAL_ENABLED=true`
- `CFB_V3_SHADOW_OPERATION_EXECUTION_ENABLED=true`
- `CFB_V3_SHADOW_KILL_SWITCH=false`
- `CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED=true`

The remaining environment variables identify the reviewed weekly config,
manifest, manifest checksum, contest, expected lined-game count, and already
registered policy versions. The environment's deployment-branch policy must
permit the exact workflow ref being rehearsed. Secret values must never be
copied into source, chat, logs, artifacts, configuration, or database rows.

## Controlled sequence

Dispatch `V3 Controlled Live-Week Shadow Rehearsal` with the real season and
week and the confirmation `RUN_V3_SHADOW_REHEARSAL`. Run stages in this order:

1. `initialize` creates or idempotently replays the isolated shadow stream from
   a migrated disposable copy of `data/cfb.db` and registers the approved
   policies. It never mutates the repository database.
2. `connectivity_check` performs the minimal authorized provider checks and
   uploads redacted evidence.
3. `tuesday_lock` captures current provider data, validates the owner-reviewed
   SplashSports manifest, locks every contest line once, publishes card v1,
   and evaluates the current sportsbook board. DraftKings is the primary
   actionable sportsbook; exact DraftKings spreads and American prices feed
   the governed recommendation engine. Other books remain a separate market-
   comparison view.
4. `wednesday_refresh`, `thursday_refresh`, and `friday_refresh` capture newer
   provider observations, publish cards v2-v4 against the original lock, and
   preserve every BET/NO BET evaluation and supersession.
5. `saturday_final` publishes card v5, evaluates the last pre-kickoff current
   offers, and immutably designates each latest same-book offer as closing
   evidence. The observed offer is not rewritten; a separate closing-line row
   preserves its exact provider, timestamp, spread, price, and provenance.
6. `postgame_grading` ingests final status, grades every final contest pick,
   grades every preserved BET and NO BET evaluation, calculates same-book CLV,
   and records missing closing evidence explicitly.
7. `weekly_audit` makes no live provider call. It seals diagnostics and four
   Lessons Learned, emits the complete shadow acceptance report, and fails if
   any acceptance gate is unmet.

Each stage writes redacted result and preflight artifacts. Provider evidence is
checksummed and retained separately. A failed or quarantined provider record is
durable evidence; it is never silently converted into context or a fabricated
value.

Every pregame result contains a readable `DRAFTKINGS BETTING BOARD`, also shown
in the workflow summary. It has one row for every locked game. Available rows
show the selected team/side, exact DraftKings spread and American price, offer
timestamp, fair spread, edge, cover and break-even probabilities, expected
value, stake, policy, reason, freshness, and immutable provenance. If the
current capture does not contain a DraftKings spread, the row is
`DRAFTKINGS_UNAVAILABLE` with the capture attempt, timestamp, and reason. A
FanDuel, BetMGM, Caesars/William Hill, Bovada, consensus, or SplashSports line
is never relabeled or substituted as DraftKings. The board is advisory only;
the repository contains no wager-submission or sportsbook-account path.

## Acceptance gates

The final report succeeds only when it demonstrates all of the following:

- the immutable lock count equals the reviewed lined-game count;
- cards v1-v5 exist, preserving four revisions and one lock checksum;
- every card reproduces exactly;
- every locked game has one side and Confidence 1-5;
- every card has exactly five Top 5 picks when at least five games are lined;
- missing or stale input is represented by an explicit governed fallback;
- provider failures and rejected rows remain explicit;
- every real DraftKings offer is evaluated and reproducible;
- every locked game has an explicit current DraftKings evaluation or an
  explicit provider-side unavailable state;
- DraftKings BET, NO BET, stale, unavailable, and supersession counts are
  reported independently from the multi-book comparison board;
- materially newer DraftKings offers preserve immutable supersession history;
- every contest pick and every BET/NO BET evaluation is graded;
- every DraftKings evaluation has same-book DraftKings closing evidence,
  grading, and CLV, or the missing closing evidence is explicit;
- diagnostics are complete and exactly four Lessons Learned are recorded;
- every contextual adjustment has evidence, source, and provenance; and
- `wagers_placed` is zero.

An incomplete run remains a failed rehearsal. It must not be described as a
successful live week or used to authorize PR #22.

## Recovery

Engage `CFB_V3_SHADOW_KILL_SWITCH=true` and disable
`CFB_V3_SHADOW_OPERATION_EXECUTION_ENABLED` to stop further stages. Preserve
all artifacts and the immutable shadow stream. Correct source input through a
new reviewed manifest or explicit correction record; never update or delete a
locked line, offer, designation, card, evaluation, audit, diagnostic, or cloud
snapshot. Re-run only with the same idempotency key for a true replay or a new
governed revision identity where the policy requires it.

Recurring schedules and production activation remain outside PR #21 and
require separate explicit approval.

## Deferred PR #22 scheduling contract

PR #21 does not add a schedule. If the owner separately authorizes PR #22, its
cloud-hosted DraftKings refresh cadence must be configuration-driven, require
no owner computer or command, respect the configured Odds API quota, and add
governed pre-kickoff refreshes. It must automatically supersede materially
changed DraftKings recommendations and fail visibly when quota or freshness
prevents a current recommendation. An aggressive polling interval must never
be hard-coded independently of the owner's provider allowance.
