# V3 cloud production cutover runbook

V3 production is designed to run entirely on GitHub-hosted infrastructure.
The owner does not need to run or maintain a personal computer, server, or
self-managed Actions runner.

Current determination:

`PRODUCTION READY: NO`

The cloud execution and persistence code is present, but the protected managed
database is not provisioned or initialized, current-week input is absent, live
provider access is not authorized, the kill switch is engaged, and the checked-
in schedule remains fail-closed behind those controls.

## Production boundary

GitHub Actions uses `ubuntu-latest` for every production and setup job.
PostgreSQL is the durable system of record across those ephemeral jobs. The
existing trigger-heavy SQLite domain schema remains the validated execution
format, but only inside a job's temporary directory:

1. The job opens a managed PostgreSQL transaction.
2. It obtains a transaction-scoped advisory lock for the V3 production stream.
3. It verifies and materializes the current checksummed state snapshot under
   `RUNNER_TEMP`.
4. The existing preflight and governed controller operate on that disposable
   snapshot without changing betting or model logic.
5. A successful operation appends an immutable state generation and one unique
   idempotency-key completion, then atomically advances the current head.
6. PostgreSQL commits only after all SQLite integrity, foreign-key, card, line,
   Confidence, Top 5, and audit checks pass.
7. Any failure rolls back the PostgreSQL transaction. The runner directory is
   discarded and is never a recovery source.

This boundary preserves the fourteen existing domain migrations and their
locked-line/card/audit triggers. It does not translate or weaken them. SQLite
remains supported for tests, historical simulation, fixtures, development,
and disposable rehearsals; durable production state does not depend on a
SQLite file surviving on any machine.

## Managed PostgreSQL schema

Ordered SQL files under `cloud_migrations/versions/` create:

- `cfb_v3_cloud_schema_migrations`: ordered name/checksum ledger;
- `cfb_v3_state_snapshots`: append-only checksummed SQLite generations;
- `cfb_v3_state_heads`: the atomically updated current generation per stream;
- `cfb_v3_operation_commits`: one immutable completion per operation key.

Snapshot and operation history reject update and delete. Foreign keys use
`ON DELETE RESTRICT`; stream/generation and stream/operation key pairs are
unique. The application also holds `pg_try_advisory_xact_lock` for the entire
read/execute/publish boundary. GitHub workflow concurrency is an additional
queueing control, not the durability or correctness mechanism.

`PostgreSQLSnapshotStore.apply_migrations()` applies each migration
inside a PostgreSQL transaction, under a separate advisory migration lock, and
rejects an unknown or changed ledger entry. Verify the checked-in inventory
offline with:

```text
python -m scripts.verify_cloud_migrations
```

The existing domain migration chain remains independently verifiable on a
disposable SQLite copy:

```text
python -m scripts.verify_migrations
```

## Why PostgreSQL

Managed PostgreSQL provides durable storage, transactional compare-and-swap
of the active head, uniqueness constraints, append-only history, and advisory
locking shared by independent GitHub-hosted jobs. Those guarantees cannot be
provided by a runner-local file. A provider may be selected by the owner, but
it must expose a standard TLS PostgreSQL connection URL and retain durable
backups/point-in-time recovery appropriate for production.

The runtime uses the exactly pinned `psycopg[binary]` driver. It is
LGPL-3.0-only, ships supported binary wheels for the Python 3.11 GitHub runner,
and avoids requiring compiler or system `libpq` setup in each ephemeral job.

## Protected GitHub configuration

Keep all sensitive values in the `v3-production` GitHub Environment. Required
environment secrets are:

- `CFB_V3_DATABASE_URL`
- `CFBD_API_KEY`
- `ODDS_API_KEY`

The database URL must include TLS settings required by the selected provider.
Never place it or either API key in repository variables, weekly JSON, command
arguments, logs, artifacts, pull requests, reports, source files, or rows in
the domain database. The persistence object redacts its representation and
converts connection failures to credential-free messages.

The existing fail-closed environment variables remain:

| Variable | Required live value |
| --- | --- |
| `CFB_V3_PRODUCTION_ENABLED` | `true` |
| `CFB_V3_OPERATION_EXECUTION_ENABLED` | `true` |
| `CFB_V3_KILL_SWITCH` | `false` |
| `CFB_V3_OWNER_CUTOVER_APPROVED` | `true` |
| `CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED` | `true` only after explicit approval |
| `CFB_V3_PROVIDER_CONNECTIVITY_VERIFIED_AT` | Current reviewed UTC evidence |

Keep the current safe values (`false`, `false`, `true`, `false`, `false`) until
the managed database, policies, provider custody, and a complete rehearsal are
reviewed. The exact V3 repository, EPA-only model identifiers, policy versions,
contest identity, expected count, and manifest checksum remain mandatory.

## One-time cloud initialization

`.github/workflows/v3_cloud_database_setup.yml` is the only production-stream
bootstrap gateway. It is manual, protected by `v3-production`, read-only to
the repository, and requires the exact `INITIALIZE_V3_CLOUD_STATE`
confirmation. It:

1. checks out a clean V3 commit on `ubuntu-latest`;
2. installs the pinned runtime lock;
3. runs repository safety checks;
4. copies and migrates `data/cfb.db` only in the runner's temporary directory;
5. registers the reviewed immutable production policies through the existing
   service layer;
6. applies/verifies the PostgreSQL migration ledger;
7. creates generation zero once and emits a redacted checksummed report.

An existing stream with identical state is an idempotent replay. An existing
different stream fails closed; it is never overwritten. The setup workflow
does not enable schedules, provider calls, production operations, or wagers.

Before dispatching setup, the owner must:

1. provision a managed PostgreSQL database with TLS and managed backups;
2. add `CFB_V3_DATABASE_URL` to `v3-production` environment secrets;
3. review and approve `config/production_policies.example.json`;
4. keep production execution disabled and the kill switch engaged;
5. temporarily record the explicit setup approval required by the workflow.

After setup, re-engage the safe flags until the first live-week rehearsal is
accepted.

## Weekly SplashSports input

SplashSports remains the sole authoritative contest-line source. It is never
replaced by an odds provider. The owner supplies screenshots or CSV/XLSX once
per week and resolves genuinely ambiguous rows. The current validated manifest
process remains unchanged:

- CSV/XLSX requires `Away Team`, `Home Team`, and home-team `Spread`;
- screenshot input uses a reviewed transcription plus retained image evidence;
- raw names and original input hashes are preserved;
- every name resolves through the canonical resolver;
- reversed, duplicate, unresolved, malformed, and count-mismatched rows fail;
- the manifest is immutable and checksum locked;
- a correction is new reviewed input and never an in-place line rewrite.

The secret-free weekly configuration locks the contest identity, expected
count, manifest path/hash, EPA-only identifiers, eight policy versions,
freshness policy, explicit fallbacks, adjustments, closing book, actor, and
provenance. No production operation proceeds without the exact reviewed
manifest and configuration.

The recurring owner responsibility is limited to supplying this weekly source
and resolving source ambiguity. Provider refreshes, cards, grading, audit, and
diagnostics are cloud execution stages.

## Production operation gateway

`.github/workflows/v3_production_operations.yml` runs on `ubuntu-latest` and
supports every governed stage:

| Operation | Result | Required prior state |
| --- | --- | --- |
| `tuesday_lock` | immutable lock and official v1 | complete reviewed manifest |
| `wednesday_refresh` | official v2 | complete lock and v1 |
| `thursday_refresh` | official v3 | complete lock and v2 |
| `friday_refresh` | official v4 | complete lock and v3 |
| `saturday_final` | official v5 | complete lock and v4 |
| `postgame_grading` | final grading and CLV ledger | final card, scores, closing custody |
| `weekly_audit` | diagnostics and Lessons Learned | completed postgame audit |

Every stage uses `v3:{season}:week:{week}:{operation}` as its idempotency key.
PostgreSQL permits only one completion per stream/key. The controller's
existing ledger remains a second domain-level idempotency control.

The job retains the exact repository allow list, protected environment,
owner/production/execution/kill-switch guards, EPA-only model constants,
read-only repository permissions, clean checkout, credential-free failure
artifact, and always-written job summary. No workflow contains `self-hosted`.
No job reads durable state from or writes durable state to the checkout.

For Tuesday through Saturday and postgame grading, the same guarded job invokes
the existing authorized provider-capture service before opening the cloud
writer transaction. Tuesday records opening market custody, Wednesday-Friday
record current custody, and Saturday evaluates the final current offers before
immutably designating those exact same-book observations as closing evidence.
Postgame capture obtains final game status without an odds call. The resulting
bundle is ingested through the existing parser/quarantine layer and uploaded as
a checksummed Actions artifact. A successful capture supplies the current
connectivity timestamp to preflight; no human has to refresh that timestamp.
Postgame grading settles the contest card and every preserved BET/NO BET
evaluation, including CLV. Weekly audit uses only the completed durable audits
and makes no provider call.

## Schedule state

The owner-authorized production schedule uses one GitHub-hosted dispatcher
heartbeat at minutes 7, 22, 37, and 52, Monday through Saturday UTC. The
heartbeat is not a provider polling interval. It checks the explicit
`production_schedule.entries` in the current owner-reviewed weekly
configuration and exits without credentials, API calls, or database access
when no entry is due.

The weekly schedule must:

- use `production-schedule-v1` and 15-minute dispatcher alignment;
- contain exactly one governed Tuesday lock, Wednesday-Friday refresh,
  Saturday final, postgame grading, and weekly audit in chronological order;
- contain one or more additional `sportsbook_refresh` entries after Tuesday
  lock and before Saturday final;
- keep entries at least 30 minutes apart;
- declare the monthly Odds API allowance, protected reserve, estimated cost,
  and maximum paid calls for that week; and
- fit every paid schedule entry inside both the weekly cap and declared
  allowance.

Each paid pregame capture first calls the provider's quota-free `/sports`
endpoint and requires provider response-header evidence that the paid odds call
will leave the configured reserve intact. The paid response is checked again.
Missing/malformed quota evidence, insufficient credits, stale DraftKings odds,
or an unavailable DraftKings recommendation for any remaining pre-kickoff
locked game fails the run visibly. Failed operations roll back and do not
replace the last validated dashboard.

`sportsbook_refresh` has a schedule-slot operation instance, obtains its own
managed PostgreSQL idempotency key, and can automatically append/supersede
materially refreshed BET/NO BET evaluations. It never creates a contest-card
version, changes a contest pick, modifies a SplashSports locked line, or places
a wager. The five existing card stages remain the only scheduled card-version
writers.

GitHub scheduled workflows execute from the default branch and can be delayed.
A slot executes only within its unique 15-minute window; a later heartbeat is
idle rather than silently spending quota twice. GitHub may disable schedules in
a public repository after 60 days without repository activity, so the owner
must treat the Actions schedule state as an operational readiness check.

## Provider custody and model contract

Provider access still requires explicit authorization and current evidence.
Raw payloads are checksummed, normalized through the existing custody layer,
and quarantined on validation failure. Market opening/current/closing rows are
separate from locked SplashSports lines and can never update them.

The active production model remains exactly:

- `epa_only`
- `epa-only-linear-v1`
- `epa-differential-v1`
- `walk-forward-prior-seasons-v1`

Ridge, dynamic-rating, and gradient-boosted research candidates remain
rejected. This boundary change does not tune, promote, substitute, or expose a
production activation path for any research model. It does not change the
locked promotion criteria.

Missing research or provider data may invoke only the existing explicit,
recorded contest fallback hierarchy. It never permits omission of a locked
lined FBS game. Every official card still requires one side per locked game,
Confidence 1–5 for every pick, and exactly five ranked Top 5 games when five or
more are eligible.

## Kill switch and recovery

Emergency order:

1. Set `CFB_V3_KILL_SWITCH=true`.
2. Set `CFB_V3_OPERATION_EXECUTION_ENABLED=false`.
3. Set `CFB_V3_PRODUCTION_ENABLED=false`.
4. Cancel any queued GitHub run.
5. Preserve redacted artifacts and managed-database logs.
6. Inspect the last immutable PostgreSQL snapshot and operation completion.
7. Restore only through the provider's managed recovery process to a separate
   database, then verify snapshot checksum, SQLite integrity, foreign keys,
   domain migration ledger, and cloud migration ledger.
8. Resume only after owner review with a new operational identity where the
   domain idempotency policy requires one.

Never update/delete a snapshot, operation completion, locked line, card,
adjustment, audit, diagnostic, or migration-ledger row to force recovery.
Never treat a runner temporary file or Actions artifact as authoritative state.

## Remaining owner setup and readiness answers

One-time owner setup remains:

- select/provision managed PostgreSQL with TLS, backups, and recovery;
- store its URL and provider API keys in the protected GitHub Environment;
- approve the reviewed policy configuration and run the guarded cloud setup;
- configure secret-free production variables and the weekly intake location;
- authorize/review provider connectivity and one complete dry rehearsal;
- explicitly approve production cutover and keep the kill switch state under
  owner control.

Recurring owner work remains:

- supply the authoritative weekly SplashSports screenshot or CSV/XLSX;
- confirm expected lined-game count and resolve genuinely ambiguous source
  data;
- review exceptional failed/quarantined runs or proposed policy changes.

Explicit answers:

1. Does production require the owner's PC to be running? **NO.**
2. Does production require a self-managed runner? **NO.**
3. Can Tuesday-Saturday operations run on GitHub-hosted infrastructure? **YES.**
4. Is production state durable between ephemeral workflow runs? **YES**, after
   the managed PostgreSQL stream is provisioned and bootstrapped.
5. Managed datastore: **PostgreSQL**, for transactional durable snapshots,
   uniqueness, immutable history, atomic head changes, and advisory locks.
6. Owner setup: the one-time protected configuration listed above.
7. Recurring owner work: weekly SplashSports input and genuine ambiguity review.
8. Are schedules checked in? **YES**, but no provider or database operation can
   run until every protected flag is live and the current weekly configuration
   contains a valid due entry.
9. Current `PRODUCTION READY`: **NO**, pending external setup, current-week
   input, live authorization, rehearsal, and explicit cutover approval.
