# V3 production cutover and first-live-week runbook

The final blocker-remediation change installs the guarded execution adapter,
manual SplashSports import path, replayable provider bundle, weekly
configuration contract, database-cutover tooling, and cross-process writer
lock. It does not promote this repository, enable a schedule, call a live
provider, write the authoritative database, or authorize the first live week.

Current determination:

`PRODUCTION READY: NO`

## Why the answer is still no

All code and repository-preparation blockers from PR #17 are resolved. The
remaining blockers are genuine owner or live-week state:

1. **Category C — credentials/provider:** `CFBD_API_KEY` and `ODDS_API_KEY`
   are not securely configured, live connectivity is not authorized, and no
   current connectivity evidence exists.
2. **Category D — current-week input:** no live season/week configuration,
   manually supplied SplashSports card, expected count, checksummed lock
   manifest, or current replayable provider bundle exists yet.
3. **Category E — production transition:** the authoritative database has not
   been backed up, migrated, and populated with approved immutable policy
   registrations; the protected environment and production authorization
   flags remain disabled; the owner has not approved cutover.
4. Schedule activation remains a separate Category E decision and is not
   required for the first manually dispatched live week.

Tests passing and adapter availability do not clear external or owner-approval
blockers.

## Report-only preflight after remediation

The 2026-08-20 report-only `thursday_refresh` preflight produced 20 machine
findings, zero warnings, zero live API calls, zero execution attempts, and an
unchanged authoritative database checksum. The execution-adapter check now
passes. Its report SHA-256 is
`02ec20cdc23987f94a557574c5d20b31824f44736a15edb47fb4fde7faa0f496`.
Every remaining finding is classified below; several are duplicate fail-closed
symptoms of the same missing owner state.

| # | Remaining preflight finding | Category | Exact owner action | When |
| --- | --- | --- | --- | --- |
| 1 | Production runtime mode absent | E | Select production runtime in the protected operating environment. | Cutover |
| 2 | Repository production enablement absent | E | Enable V3 production only after migration and review. | Cutover |
| 3 | Per-operation execution enablement absent | E | Enable guarded operations after dry-run acceptance. | First live week |
| 4 | Owner cutover approval absent | E | Record explicit owner cutover approval. | Cutover |
| 5 | Kill switch missing/engaged | E | Explicitly disengage it only for the approved operation window. | Each live operation |
| 6 | Required boolean set incomplete | E | Configure the exact protected flags after the related approvals. | Cutover |
| 7 | Runtime repository variables absent | E | Configure both repository identities to the exact V3 value. | Cutover |
| 8 | `CFBD_API_KEY` and `ODDS_API_KEY` absent | C | Add both as `v3-production` environment secrets or OS secret-manager entries. | Connectivity setup |
| 9 | Provider connectivity not authorized | C | Authorize the controlled two-endpoint connectivity check. | Connectivity setup |
| 10 | Current connectivity evidence absent | C | Review a successful controlled check and record its UTC verification timestamp. | Before live ingestion |
| 11 | Season/week absent | D | Create the current secret-free weekly JSON from the example. | First live week |
| 12 | Contest identity/count absent | D | Enter the current SplashSports contest identifiers and expected lined-game count. | Tuesday input |
| 13 | Locked EPA identifiers absent | D | Retain the exact EPA-only identifiers already present in the weekly template. | First live week |
| 14 | Active policy versions absent | E | Complete governed policy registration, then reference those exact versions in weekly JSON. | Cutover |
| 15 | Migrations 1-14 not applied to authoritative DB | E | Approve and run the guarded migration with a new verified backup. | Cutover |
| 16 | No games for configured week | D | Capture/replay current provider evidence for the selected week. | First live week |
| 17 | Production policy tables unavailable | E | Cleared by the same governed authoritative migration and registration. | Cutover |
| 18 | SplashSports manifest absent | D | Supply CSV/XLSX or reviewed screenshot transcription and build its checksum-locked manifest. | Tuesday input |
| 19 | Line-lock readiness incomplete | D | Validate the complete manifest after migration and current-week game ingestion. | Tuesday input |
| 20 | Controller idempotency ledger unavailable | E | Cleared by the governed authoritative migration; never edit the ledger manually. | Cutover |

The dedicated durable `cfb-v3-production` runner and protected environment
must also be provisioned as part of the Category E transition before any
persisted workflow run. Schedule activation remains a separate later Category
E choice; no schedule is needed for manual first-week dispatch.

## PR #17 blocker reclassification

The 21 PR #17 report entries reduce to five underlying groups:

| Prior blocker group | Category | Current disposition |
| --- | --- | --- |
| Missing runtime flags and exact repository values | B/E | Typed config and workflow wiring are complete; enabling them is an explicit owner transition. |
| Missing credential presence and connectivity evidence | C | Secure names and controlled checks are implemented; owner configuration remains. |
| Missing season/week, contest identity, model and policy values | B/D | Secret-free weekly configuration and locked defaults are implemented; the live week remains owner input. |
| Missing migration ledger, policies, controller tables and idempotency state | B/E | Rehearsal and guarded authoritative cutover tooling are complete; authoritative mutation remains approval-gated. |
| Missing line manifest and lock readiness | A/D | CSV, XLSX, and reviewed screenshot-transcription importers are complete; the actual Tuesday card remains owner input. |
| Missing live execution/persistence adapter | A | Eliminated. The adapter orchestrates the existing governed services and remains disabled by default. |

No Category A or B engineering blocker remains.

## Runtime separation and fail-closed flags

Development remains the default. A production operation requires every flag
below to have its exact safe value. Missing, misspelled, or non-boolean values
block execution.

| Environment variable | Required meaning |
| --- | --- |
| `CFB_V3_RUNTIME_MODE` | Explicit production runtime selection |
| `CFB_V3_PRODUCTION_ENABLED` | Repository-level V3 production enablement |
| `CFB_V3_OPERATION_EXECUTION_ENABLED` | Separate permission to execute an operation |
| `CFB_V3_KILL_SWITCH` | Must be explicitly disengaged |
| `CFB_V3_OWNER_CUTOVER_APPROVED` | Explicit owner cutover authorization |
| `CFB_V3_REPOSITORY` | Exact V3 repository allow-list identity |
| `GITHUB_REPOSITORY` | GitHub-provided repository identity |
| `CFB_V3_DATABASE_PATH` | Exact V3 authoritative database path |

The preflight also reads the local `origin` identity without printing its URL
or embedded credentials. The repository root, runtime identifier, GitHub
identifier, origin, and database target must all identify
`JCRABURN/cfb-betting-system-v3`. The original repository is always rejected.

## Credentials and provider authorization

Only credential variable names and presence are reported:

- `CFBD_API_KEY`
- `ODDS_API_KEY`

Values are never retained in the typed settings object, report, logs,
artifacts, tests, or documentation.

Live connectivity additionally requires:

- `CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED`
- `CFB_V3_PROVIDER_CONNECTIVITY_VERIFIED_AT`

The timestamp must be UTC, cannot be in the future, and must be no more than 24
hours old. Recording it is allowed only after an owner-authorized external
connectivity check. The preflight itself makes zero live API calls.

Configure the two secret values in GitHub under **Settings → Environments →
v3-production → Environment secrets**. For an owner-controlled local run, use
the operating system or approved secret manager. Never place values in a
weekly JSON file, repository variable, command line, artifact, or log.

The controlled connectivity command is
`python -m scripts.check_provider_connectivity`. It requires the exact
`AUTHORIZE_V3_CONNECTIVITY` confirmation and performs only:

- CFBD `GET /calendar` with the `CFBD_API_KEY` bearer credential;
- The Odds API `GET /v4/sports` with `ODDS_API_KEY`.

The report contains endpoint, credential-free parameters, timestamp, status,
payload checksum, and credential variable names—never values. A successful
timestamp becomes `CFB_V3_PROVIDER_CONNECTIVITY_VERIFIED_AT` only after owner
review.

`python -m scripts.capture_provider_bundle` is separately gated by
`CAPTURE_V3_PROVIDER_PAYLOADS`. It captures raw CFBD game/status evidence,
point-in-time EPA through `week - 1` when applicable, and real-book Odds API
spreads. It writes raw and normalized checksummed evidence under the ignored
`data/provider_evidence/` directory. The operation adapter replays this bundle
through Milestone 14 custody, quarantine, freshness, canonical writing, and
idempotency. Market rows are stored only as opening/current/closing rows and
can never modify `contest_locked_lines`.

Use `--capture-scope pregame` for games, EPA, and odds. A final pre-kickoff
capture may be labeled `--line-type closing`. After games finish, use
`--capture-scope postgame` to capture final CFBD game results without calling
the odds endpoint; postgame grading ingests that bundle before its final
preflight and audit. The earlier closing rows remain separate and immutable.

## Week and contest configuration

The operating week requires:

- `CFB_V3_SEASON`
- `CFB_V3_WEEK`
- `CFB_V3_CONTEST_KEY`
- `CFB_V3_CONTEST_NAME`
- `CFB_V3_SOURCE_CONTEST_ID`
- `CFB_V3_CONTEST_SOURCE`
- `CFB_V3_EXPECTED_LINED_GAME_COUNT`
- `CFB_V3_CONTEST_LINES_FILE`
- `CFB_V3_CONTEST_LINES_SHA256`

The source must be `SplashSports`. The line-manifest path must remain inside
the V3 checkout and its exact SHA-256 must be supplied. The manifest contract
is:

- `manifest_version` is `v3-contest-lines-v1`;
- `repository` identifies the V3 repository;
- source, season, week, contest key, source contest id, and expected count
  exactly match the runtime configuration;
- `lines` contains exactly the expected number of records;
- every record has unique `source_line_id`, `raw_home_team`, `raw_away_team`,
  finite `home_spread`, and an optional nonnegative finite `total`;
- reversed and duplicate matchups are forbidden;
- every raw name resolves through the canonical SplashSports resolver;
- every normalized matchup maps exactly once to the configured database week.

The preflight never locks these lines. It verifies readiness read-only. The
existing weekly controller remains the sole authorized future lock path.
When a contest already exists, its raw teams, spreads, totals, source-line
identifiers, source, and manifest hash must match exactly before an operation
can be treated as an idempotent replay.

### Manual SplashSports input

`python -m scripts.build_splashsports_manifest` accepts three controlled input
formats:

- `csv` with `Away Team`, `Home Team`, and home-team `Spread` columns;
- `xlsx` with the same required headers, parsed without macros or formulas;
- `screenshot_transcription`, which is the same strict CSV after a human has
  transcribed the screenshot. It additionally requires one or more PNG, JPEG,
  or WebP evidence files, a reviewer, and a UTC review timestamp.

Optional columns are `Game Date`, `Game Time`, `Total`, `SplashSports Game ID`,
and `Notes`. The importer hashes the original file, preserves raw names,
resolves only through the canonical resolver, maps every row to exactly one
FBS game, rejects reversed/duplicate/ambiguous matchups and malformed spreads,
and refuses an expected-count mismatch. It never infers a missing line or
guesses an unclear screenshot value.

All three formats produce the same `v3-contest-lines-v1` contract. The
downstream controller sees only that contract and the original input custody.
The importer refuses to overwrite an existing manifest. A correction must be
created as new reviewed input and handled through the append-only correction
process; an existing lock is never rewritten.

Example spreadsheet import:

```text
python -m scripts.build_splashsports_manifest \
  --input data/production_inputs/splashsports.csv \
  --input-format csv \
  --database data/cfb.db \
  --output config/production-weeks/lines.json \
  --season YEAR --week WEEK \
  --contest-key CONTEST_KEY --contest-name CONTEST_NAME \
  --source-contest-id SPLASHSPORTS_CONTEST_ID \
  --expected-lined-game-count COUNT \
  --captured-at UTC_TIMESTAMP --imported-by OWNER \
  --provenance OWNER_REVIEW_REFERENCE
```

The screenshot path uses `--input-format screenshot_transcription` plus
`--screenshot-evidence`, `--screenshot-reviewed-by`, and
`--screenshot-reviewed-at`.

### Weekly configuration

Copy `config/weekly_operation.example.json` to the ignored
`config/production-weeks/` directory and replace every placeholder. The file
contains no credentials. It locks season, week, contest identity, expected
count, manifest path/hash, EPA-only identifiers, eight policy versions,
freshness policy, explicit fallbacks, contextual adjustments, no-bet records,
closing book, display timezone, actor, and provenance. Conflicting environment
values fail closed. The adapter records the configuration checksum in every
result.

## Locked model and policies

These model identifiers are immutable cutover requirements:

- `CFB_V3_MODEL_NAME`
- `CFB_V3_MODEL_VERSION`
- `CFB_V3_FEATURE_SCHEMA_VERSION`
- `CFB_V3_CONFIGURATION_VERSION`

They must identify the EPA-only baseline, `epa-only-linear-v1`,
`epa-differential-v1`, and `walk-forward-prior-seasons-v1`. Research
candidates have no production configuration or workflow input.

All active policy versions must be explicit and already registered:

- `CFB_V3_CONTROLLER_POLICY_VERSION`
- `CFB_V3_SELECTION_POLICY_VERSION`
- `CFB_V3_CONFIDENCE_POLICY_VERSION`
- `CFB_V3_RANKING_POLICY_VERSION`
- `CFB_V3_ADJUSTMENT_POLICY_VERSION`
- `CFB_V3_REFRESH_POLICY_VERSION`
- `CFB_V3_AUDIT_POLICY_VERSION`
- `CFB_V3_DIAGNOSTICS_POLICY_VERSION`

The preflight checks immutable policy tables. The workflow cannot create,
promote, or modify a policy.

## Stale-data thresholds

The gateway verifies the sanctioned `provider_freshness_v1` configuration:

| Data type | Maximum age |
| --- | ---: |
| Odds | 900 seconds |
| Injuries | 21,600 seconds |
| Weather | 10,800 seconds |
| Game status | 300 seconds |
| Contextual data | 86,400 seconds |

Official publication still requires current custody or the exact permitted,
versioned fallback already enforced by the weekly controller.

## Operating-stage gateway

`.github/workflows/v3_production_operations.yml` is one manual gateway for all
writers. Its operation choices are:

| Choice | Intended controller stage | Prior-state requirement |
| --- | --- | --- |
| `tuesday_lock` | Initial line lock and official v1 | No prior lock, or exact completed v1 replay |
| `wednesday_refresh` | Daily refresh and official v2 | Complete immutable lock and v1 |
| `thursday_refresh` | Daily refresh and official v3 | Complete immutable lock and v2 |
| `friday_refresh` | Daily refresh and official v4 | Complete immutable lock and v3 |
| `saturday_final` | Final refresh and official v5 | Complete immutable lock and v4 |
| `postgame_grading` | Complete postgame grading | Final official publication and result inputs |
| `weekly_audit` | Diagnostics and completed weekly audit | Completed postgame audit |

Every stage receives the stable idempotency key
`v3:{season}:week:{week}:{operation}`. Existing completed keys are safe
replays. Existing incomplete or failed keys require recovery review and are
never silently reused.

Tuesday through Saturday card stages must also run on their corresponding UTC
weekday and before every listed kickoff. Postgame grading requires final scores
and pre-kickoff closing-line custody for every locked game; weekly audit
requires a completed audit of the final official card.

The workflow has:

- manual dispatch only;
- one shared repository/week concurrency lock across every operation;
- `cancel-in-progress: false` for writer serialization;
- exact V3 repository allow-listing;
- an explicit confirmation phrase;
- a protected `v3-production` environment boundary;
- an owner-provisioned, persistent `cfb-v3-production` self-hosted runner;
- read-only workflow and job permissions;
- checkout credential persistence disabled;
- a redacted JSON preflight artifact;
- an always-written GitHub job summary;
- a visible failed guard job when authorization is missing or the kill switch
  is engaged, without checkout or credential access;
- no schedule and no automatic policy-change input.

The installed adapter remains inert unless every guard and preflight check
passes and the CLI receives the exact persist confirmation. It loads only
already-registered policies, replays provider evidence through custody,
serializes writers with both the workflow concurrency group and a database
lock file, and calls the existing Tuesday/daily controller, postgame audit, or
weekly diagnostics service. Official publication remains one atomic controller
transaction. No code path places a wager or activates a recommendation.

The guarded job deliberately cannot run on `ubuntu-latest`: a disposable
runner would discard the mutated SQLite database after the job. Before owner
authorization, provision a dedicated self-hosted runner with the
`cfb-v3-production` label, a durable work directory, OS-level access limited to
the V3 operator, and a documented host backup/restore process. The checkout
uses `clean: false` so the durable authoritative database is not reset between
operations. Do not share this runner with untrusted repositories or jobs.

Read-only mode is the default. Dry-run mode requires
`DRY_RUN_V3_OPERATION`, copies the configured database to a disposable
directory, executes the full persisted path there, verifies integrity and
foreign keys, and proves the source checksum is unchanged. Persist mode
requires `EXECUTE_V3_OPERATION`. An existing lock file is never broken
automatically; it requires kill-switch recovery review.
Persist mode executes against a same-filesystem staging copy, verifies SQLite
integrity and foreign keys, writes a checksummed pre-operation backup beneath
`data/backups/`, and atomically replaces `data/cfb.db` only after success. Any
failure before replacement leaves the authoritative database unchanged.

## Kill switch

Set `CFB_V3_KILL_SWITCH` to engaged at the repository or protected-environment
level to stop every stage. The same guard covers ingestion, Tuesday lock,
daily publication, database writers, postgame grading, and weekly audit.

Emergency order:

1. Engage `CFB_V3_KILL_SWITCH`.
2. Disable `CFB_V3_OPERATION_EXECUTION_ENABLED`.
3. Disable `CFB_V3_PRODUCTION_ENABLED`.
4. Cancel any run that has not reached its atomic controller transaction.
5. Preserve the failed-run artifact and logs.
6. Inspect the latest official publication read-only.
7. Verify database SHA-256, `integrity_check`, and `foreign_key_check`.
8. Follow the operation-specific recovery procedure below.

No schedule currently exists, so there is no cron trigger to disable.

## Preflight command

The machine-verifiable command is:

```text
python -m scripts.production_preflight \
  --operation tuesday_lock \
  --database data/cfb.db \
  --pretty
```

It exits nonzero whenever any blocker exists. Add `--report-only` only when a
human or CI step needs to capture the truthful report without treating
`PRODUCTION READY: NO` as a command failure.

The report includes every check, blocker, warning, credential variable name,
database hash before and after, live API call count, execution-attempt flag,
and its own canonical SHA-256. It never applies pending migrations.

The adapter's read-only weekly-config path is:

```text
python -m scripts.run_production_operation \
  --operation tuesday_lock \
  --database data/cfb.db \
  --weekly-config config/production-weeks/week.json \
  --mode read-only
```

Change to `--mode dry-run --confirmation DRY_RUN_V3_OPERATION` only after the
read-only report passes. Persist execution is reserved for the protected
workflow or an owner-approved operating host.

## Database cutover preparation

`python -m scripts.prepare_production_database` is the only production-cutover
wrapper. Rehearsal mode copies the source, records hashes, row counts,
pre-migration integrity and foreign keys, and the migration inventory, applies migrations 1–14
through `migrations.runner`, registers the proposed definitions from
`config/production_policies.example.json` through the existing immutable
policy services, and verifies the result. Those definitions still require
owner approval before authoritative use. The source must remain byte-for-byte
unchanged.

Authoritative mode remains Category E. It requires all of the following:

- the exact `data/cfb.db` target;
- a new explicit backup path whose checksum matches the source;
- `CFB_V3_OWNER_DATABASE_MIGRATION_APPROVED=true`;
- `CFB_V3_KILL_SWITCH=true`;
- `CFB_V3_OPERATION_EXECUTION_ENABLED=false`;
- `CFB_V3_PRODUCTION_ENABLED=false`;
- the exact `MIGRATE_V3_AUTHORITATIVE_DATABASE` confirmation.

The script never edits `schema_migrations` directly. A failure leaves the
verified backup for the documented restore procedure and does not fabricate
ledger or policy rows.

## Recovery

### Tuesday lock

An identical completed run key is idempotent. A conflicting or partial
contest must never be relocked or repaired in place. Engage the kill switch,
preserve the failed database and logs, inspect line custody, and restore a
verified pre-run database snapshot if the atomic controller guarantee was
somehow bypassed. Retry only with an approved operational identity.

### Wednesday through Saturday

Never branch from an older publication. Confirm the latest official version,
source freshness, line-snapshot hash, and policy assignments. A failed key is
not reused. Correct source data or the documented defect, preserve both
versions when a correction is required, and create the next append-only
revision.

### Postgame grading

Do not rewrite a completed audit. Correct scores or closing-line custody using
the governed source path, retain the prior audit, and create a superseding
audit run with complete evidence.

### Weekly audit

Diagnostics require a completed audit and cannot activate recommendations.
Correct the source audit first, then create a new diagnostic run. Owner
approval and a separately versioned policy remain mandatory for any later
rule change.

### Migration or integrity failure

Do not apply ad hoc schema SQL. Stop all writers, retain row counts and hashes,
verify a disposable copy, and follow `migrations/README.md`. Restore the last
verified complete snapshot rather than editing migration-ledger rows.

## Remaining authorization sequence

The remaining owner actions are:

1. **Category E — required before the first live week:** approve the reviewed
   policy configuration, create a verified backup, and authorize the guarded
   authoritative migration/policy registration.
2. **Category C — required before the first live week:** configure
   `CFBD_API_KEY` and `ODDS_API_KEY` as `v3-production` environment secrets,
   authorize the controlled connectivity check, and review its redacted
   evidence timestamp.
3. **Category E — required before the first live week:** protect the
   `v3-production` environment, restrict approvers, provision the dedicated
   durable `cfb-v3-production` runner, configure the documented non-secret
   variables, and keep the kill switch engaged until the dry-run report is
   accepted.
4. **Category D — required each live Tuesday:** provide the authoritative
   SplashSports screenshots or CSV/XLSX, confirm expected lined-game count,
   review any visible import rejection, and approve the resulting checksum.
5. **Category D — required for each operating stage:** approve current
   provider evidence or explicit documented freshness fallbacks, plus any
   sourced manual contextual adjustments. Supply a real closing-book choice
   before postgame grading.
6. **Category E — required before the first persisted operation:** review a
   complete disposable dry run, disengage the kill switch, enable production
   and operation flags, and explicitly approve cutover.

Schedule activation is **Category E, later only**. No schedule exists, and
enabling one requires a separate owner decision and pull request.
