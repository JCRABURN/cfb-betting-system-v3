# Provider ingestion custody

Milestone 14 adds the offline-testable custody boundary used before provider
data may feed an official V3 workflow. It does not enable a provider, schedule,
production write path, or model change.

## Safety boundary

`ingestion.custody.ProviderIngestionService` accepts an already-captured JSON
payload or recorded fixture. It has no HTTP client and reads no credentials.
The caller supplies provider, endpoint, non-secret request parameters, UTC
request time, parser version, raw-payload reference, data type, and optional
expected payload checksum.

Credential-named request parameters are removed before custody. Endpoint query
strings are not retained. Every run stores a SHA-256 checksum, accepted and
rejected counts, final status, parser version, and replay reference.

The append-only migration-v13 records are:

- `provider_ingestion_runs`: one final custody record per provider payload and
  parser version;
- `provider_ingestion_rejections`: record-level quarantine with stable reason,
  raw-record checksum, and replayable JSON;
- `provider_ingestion_acceptances`: provider-neutral accepted-record identity,
  parser provenance, checksum, and observation time for every typed adapter;
- `provider_market_snapshots`: strictly validated, canonically mapped pregame
  spread observations;
- `provider_data_snapshots`: versioned point-in-time freshness evidence;
- `provider_team_aliases`: centrally governed provider-to-canonical aliases.

All six tables reject updates and deletes at the database boundary. Market
snapshots also require an accepted run and an exact canonical `games` mapping.

## Quarantine behavior

Unknown or ambiguous teams, malformed spreads, duplicates, invalid timestamps,
stale observations, unsupported markets, missing matchup identifiers, reversed
matchups, missing mappings, and conflicting mappings are quarantined. They do
not enter `provider_market_snapshots` or an optional downstream canonical
writer. A mix of accepted and rejected records is `partial`, never `completed`.

An exact replay is idempotent. The same bytes under a different parser version
create a distinct interpretation and preserve both histories. An expected
checksum mismatch is recorded without parsing. If a downstream writer raises,
the entire record transaction rolls back and a separate final `failed` run is
preserved.

## Freshness policy v1

| Data type | Maximum age |
| --- | ---: |
| Odds | 15 minutes |
| Injuries | 6 hours |
| Weather | 3 hours |
| Game status | 5 minutes |
| Contextual data | 24 hours |

`assess_required_freshness()` selects only runs requested at or before the
card's requested as-of timestamp. It returns `current`, `partial`, `stale`, or
`missing` for every required source. For a multi-record payload, expiration is
based on the earliest accepted observation so one fresh row cannot hide older
rows. `partial`, `stale`, and `missing` require an explicit permitted fallback
in the future weekly controller.

Freshness or model/research gaps must never omit a locked lined FBS contest
game. The production contest hierarchy remains responsible for producing one
side, Confidence 1–5, and a ranking with recorded fallback provenance.

## Offline replay

Replay fixtures only into a disposable database:

```text
python -m ingestion.replay \
  --database path/to/disposable.db \
  --fixture tests/fixtures/provider_ingestion/odds_valid.json \
  --requested-at 2026-08-25T15:00:00+00:00
```

The command performs no network access and refuses the repository's
authoritative `data/cfb.db`. A replay database needs canonical `teams` and
`games` rows for records to be accepted; unresolved fixture records are
quarantined by design.

## Migration recovery

Migration 13 only creates new, initially empty custody tables, indexes, and
triggers; it does not rewrite an existing table or row. The migration runner
applies and verifies those objects in one transaction, so a failed application
rolls back automatically.

Before applying the migration to any promoted database, retain a verified
pre-migration database snapshot. If recovery is required after a successful
application, stop writers, restore that complete pre-migration snapshot, verify
SQLite integrity and foreign keys, and run the code version whose migration
ledger ends at version 12. Do not delete migration-ledger rows or drop custody
objects manually in place. Reverting the code commit alone is sufficient only
when migration 13 has never been applied to the target database.

## Model and production state

The EPA-only model remains the production baseline. The rejected ridge,
dynamic-rating, and gradient-boosted research candidates are not imported,
tuned, promoted, or connected to ingestion or card generation. Model-promotion
criteria are unchanged. No scheduled production workflow is enabled.
