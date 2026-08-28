# Football identity foundation

Migration 19 adds the dormant, sport-aware identity layer approved in
`MIXED_NCAA_NFL_PHASE_0.md`. It is additive infrastructure for future football
products. It does not change the existing SplashSports CFB product, and no
current Product A reader or writer uses these tables.

## Identity hierarchy

The foundation separates durable identity from time-specific presentation:

```text
football_sports
  -> football_franchises
    -> football_teams
      -> football_team_seasons
      -> football_team_aliases

football_venues
  -> football_venue_versions

football_events
  -> football_event_revisions
  -> football_provider_event_ids
  -> legacy_cfb_game_links (compatibility only)
```

`football_sports` is seeded with only `NCAA` and `NFL`. A franchise is the
persistent program or club. A team is an effective named identity attached to
that franchise, allowing a future NFL backfill to preserve relocation or rename
history without changing old events. Team-season rows record alignment from an
explicit effective UTC timestamp, so conference, division, and classification
are historical facts rather than current lookups.

Aliases are exact, provider-specific, sport-scoped mappings. Their stored key is
only `lower(trim(raw_alias))`; there is no fuzzy matching. Reusing an alias in a
later season requires an explicit append-only supersession chain. The same text
may exist in NCAA and NFL because sport is part of the identity, but one
provider/sport alias cannot ambiguously resolve within a season.

## Venues and events

`football_venues` represents a persistent physical venue. Append-only venue
versions preserve stadium names, IANA time zones, roof/surface facts, and exact
integer microdegree coordinates from their effective UTC timestamps. The
schema supports neutral, temporary, bowl, and international venues without any
geocoder dependency.

`football_events` represents a real sporting event, never a contest row or a
sportsbook market. Its sport, season/type/week, teams, kickoff, venue, neutral
designation, and lifecycle state are explicit. Triggers require distinct teams,
same-sport active team identities, and a registered sport.

The accepted initial event row is immutable. Corrections append a complete
snapshot to `football_event_revisions`, with a contiguous revision number,
single supersession chain, later recorded timestamp, reason, author, and
provenance. Selecting the latest revision recorded on or before an `as_of`
timestamp reconstructs what the system believed then. Updates and deletes are
blocked.

Provider event IDs are unique within `(provider, sport, provider_event_id)` and
must reference an event of the same sport. A provider ID cannot be remapped to
another event.

## Legacy CFB compatibility

`legacy_cfb_game_links` is an optional, immutable compatibility map. Product A
continues to treat legacy `teams`, `games`, contest lines, cards, picks,
recommendations, controllers, schedules, and dashboard records as authoritative.
Nothing automatically creates generalized identities or links.

A link is accepted only when all of these are exact and deterministic:

- the generalized event is NCAA;
- season, season type, week, neutral designation, and kickoff match;
- effective `legacy_cfb` aliases map the legacy home and away strings to the
  event's corresponding canonical teams;
- the link uses `legacy_cfb_exact_v1` and carries UTC/provenance metadata.

No fuzzy name matching, approximate kickoff matching, guessed venue mapping, or
automatic backfill exists. A later governed backfill must create explicit
identities and aliases before it can propose links.

## Immutability and recovery

All new identity records reject updates and deletes. Historical change is
represented by effective rows or explicit revision/supersession records. The
migration rewrites no existing table and seeds no team, franchise, venue,
event, provider ID, or legacy link.

Migration rehearsal uses a disposable copy of `data/cfb.db`. If recovery is
required, preserve the failed database for audit, restore the verified
pre-migration copy, and ship a new forward migration. Never edit migration 19,
its ledger entry, or accepted identity rows.

Managed PostgreSQL needs no new relational DDL for this step. Its existing
append-only snapshot store persists the migrated SQLite state and records the
SQLite migration inventory and checksum. There is no separate database and no
self-hosted execution requirement.

## Intentionally unimplemented

This foundation does not implement mixed spreadsheet custody, contest products
or lines, NFL data acquisition or forecasting, the NCAA forecast-service
boundary, cross-sport Confidence/Top 5, standings/payouts, sportsbook changes,
dashboard/scheduler changes, or production activation. It makes no network or
provider calls and adds no wager-placement path.
