# Historical end-to-end rehearsal

Milestone 16 provides a deterministic, offline dress rehearsal of the complete
V3 operating lifecycle. It uses the committed `data/cfb.db` only as a read-only
historical source and performs every write against an in-memory clone.

## Locked historical scope

The rehearsal uses the six-game Saturday contest slate from 2024 Week 15. All
six games have an archived opener, archived closer, prior-week point-in-time
EPA, a final score, and a kickoff after the simulated Saturday-morning refresh.

| Game | Matchup | Kickoff UTC | Archived opener | Archived closer |
| --- | --- | --- | ---: | ---: |
| 401673465 | Iowa State at Arizona State | 2024-12-07 17:00 | Arizona State -2.5 | Arizona State -1.5 |
| 401673467 | Ohio at Miami (OH) | 2024-12-07 17:00 | Miami (OH) -2.5 | Miami (OH) -2.5 |
| 401673469 | Georgia at Texas | 2024-12-07 21:00 | Texas -2.5 | Texas -3.0 |
| 401673470 | Marshall at Louisiana | 2024-12-08 00:30 | Louisiana -4.5 | Louisiana -5.0 |
| 401673463 | Clemson at SMU | 2024-12-08 01:00 | SMU -2.5 | SMU -3.0 |
| 401673464 | Penn State at Oregon | 2024-12-08 01:00 | Oregon -3.5 | Oregon -3.0 |

These archived market values are replay fixtures. They are imported as a
simulated SplashSports contest batch for controller testing; the repository
does not claim the historical rows were actual SplashSports captures.

## Temporal isolation

Before Tuesday prediction, the in-memory clone stores the six historical final
scores separately and clears those scores and completion flags from the cloned
`games` rows. The EPA-only controller therefore runs without target outcomes
present. Point-in-time features still use only statistics from before Week 15.

The historical scores are restored only after the Saturday publication is
sealed. Archived closing values are then copied into replay-only closing rows
with simulated capture timestamps 30 minutes before kickoff, after the final
card timestamp. This makes the audit timing explicit without rewriting the
archived source rows.

## Lifecycle

The fixed UTC schedule is:

1. Tuesday, 2024-12-03 15:00 — initialize the contest, refresh all five source
   custody types, lock six lines, run the EPA-only baseline, and publish v1.
2. Wednesday, 2024-12-04 15:00 — refresh data and publish v2.
3. Thursday, 2024-12-05 15:00 — refresh data and publish v3.
4. Friday, 2024-12-06 15:00 — refresh data and publish v4.
5. Saturday, 2024-12-07 14:00 — publish final v5 before every locked kickoff.
6. Monday, 2024-12-09 15:00 — reveal final scores and complete the postgame
   audit against replay-timed closing lines.
7. Monday, 2024-12-09 16:00 — generate all required diagnostics, Lessons
   Learned, and numeric policy recommendations.

Every day records current custody for odds, injuries, weather, game status, and
contextual data through the Milestone 14 replayable ingestion service. No live
transport or credential is used.

The Saturday revision includes one explicitly synthetic `+1.5` home-margin and
`+1` Confidence adjustment for Oregon. Its evidence and provenance state that
it exists only to exercise raw-versus-adjusted auditing and is not a historical
claim. It flips the raw side and the completed audit classifies the effect as
`side_flip_helped`. The card also records an explicit `no_bet`; no wager or bet
recommendation is created.

## Verified deterministic result

The acceptance test and command produce:

- five immutable official publications;
- six picks and exactly five ranked Top 5 entries per version;
- four revisions and 24 per-pick before/after records;
- exact reproduction of every version;
- unchanged original locked-line rows;
- six completed audits: 3 wins, 3 losses, and 0 pushes;
- CLV, hook, key-number, location, spread, rank, and adjustment classification
  for every final pick;
- one manual adjustment, classified `side_flip_helped`;
- 26 diagnostic segments and four Lessons Learned;
- four numeric Confidence-policy recommendations, all held for insufficient
  evidence and never activated;
- SQLite `integrity_check=ok` and zero foreign-key violations;
- zero live API calls and zero authoritative database row changes.

## Run the rehearsal

Use the commit being verified:

```text
python -m scripts.run_historical_rehearsal \
  --database data/cfb.db \
  --code-commit-sha COMMIT_SHA \
  --pretty
```

The command prints a canonical JSON report containing the historical fixture,
locked-line, official-publication, audit, diagnostic, source-database, and
overall rehearsal SHA-256 values. Running it repeatedly with the same database
and commit produces the same rehearsal hash.

## Failure and recovery behavior

Missing games, final scores, opening lines, closing lines, pregame EPA, or a
post-Saturday kickoff fail the rehearsal visibly. Any controller, audit,
diagnostic, reproduction, integrity, or foreign-key failure also fails the
command.

The source database is opened read-only and copied into memory before pending
migrations are applied. On failure, the clone is discarded. There is no source
database recovery step because the command has no source write path. If the
source SHA changes during a run, the acceptance report fails.

## Limitations

- This is an offline historical simulation, not provider connectivity proof.
- The six-game slate is fixed so the Saturday final refresh precedes every
  contest kickoff; the three Friday championship games are outside this
  simulated Saturday contest slate.
- The adjustment is deliberately synthetic and must not be interpreted as a
  factual historical injury or matchup assessment.
- The one-week sample is descriptive. It cannot promote a model or activate a
  policy change.
- Production credentials, workflow schedules, and cutover remain Milestone 17.
