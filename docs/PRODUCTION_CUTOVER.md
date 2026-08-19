# V3 production cutover readiness

Milestone 17 adds a fail-closed production boundary and a machine-verifiable
cutover report. It does not promote this repository, enable a schedule, call a
live provider, write the authoritative database, or install an execution
adapter.

Current determination:

`PRODUCTION READY: NO`

## Why the answer is no

The current authoritative repository state has concrete blockers:

1. The governed migration ledger is not present in `data/cfb.db`; migrations
   1 through 14 are verified only on disposable copies.
2. The production controller, selection, Confidence, ranking, adjustment,
   refresh, audit, and diagnostic policy versions are not registered in the
   authoritative database.
3. Production environment flags, owner approval, credential presence, and
   recent provider-connectivity evidence have not been supplied and verified.
4. No authorized current-week SplashSports line manifest has been supplied.
5. No owner-authorized live ingestion/controller execution adapter or
   persistence step is installed.
6. The new workflow intentionally has read-only repository permissions and no
   schedule.

Tests passing does not clear these blockers.

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
- read-only workflow and job permissions;
- checkout credential persistence disabled;
- a redacted JSON preflight artifact;
- an always-written GitHub job summary;
- a visible failed guard job when authorization is missing or the kill switch
  is engaged, without checkout or credential access;
- no schedule and no automatic policy-change input.

Because no authorized execution adapter exists, the guarded entry point exits
nonzero before any mutation. The workflow is a cutover gate, not a disguised
production enablement.

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

Before any real operation, the owner must separately approve work that:

1. backs up and migrates the authoritative database under the documented
   migration procedure;
2. registers reviewed production policy versions;
3. installs and tests live provider adapters through Milestone 14 custody;
4. establishes a persistence mechanism with least-privilege write access;
5. supplies credentials and connectivity evidence outside source control;
6. protects and configures the `v3-production` GitHub environment;
7. supplies the authorized, checksummed contest-line manifest;
8. completes a dry run and reviews its official-card reproduction;
9. explicitly authorizes production cutover.

Enabling a schedule is a separate owner decision and a separate pull request.
