# Mixed Pick'em source custody and contest-line locking

## Boundary

This document governs Phase 2 of Product B, the mixed NCAA + NFL ATS Pick'em
contest. The phase starts with an administrator CSV or XLSX source and ends
with immutable contest lines. It does not generate forecasts, picks,
Confidence, rankings, Top 5 selections, sportsbook recommendations, standings,
or wagers. Product A's SplashSports controller and line custody remain separate
and unchanged.

The administrator's weekly sheet is authoritative for the exact game set,
contest spread, and row count. The system does not reconstruct organizer intent
from rankings, sport weeks, weekdays, or provider schedules. Card size is
variable; approximately 15 games is an operating expectation, not a schema
constant.

## Product and round identity

Migration 20 seeds the `mixed_pickem` contest product and its NCAA/NFL
allowlist. Operators create immutable Product B season and round records. The
current season policy can record 20 planned rounds, but the schema permits
other positive policy-defined counts. A contest round number is independent of
NCAA and NFL week numbers; canonical events retain their own sport season,
season type, and sport week.

Product B uses only `mixed_*` contest tables. It never uses Product A's
`contests`, `contest_locked_lines`, cards, picks, or scheduler state as a
prerequisite.

## Versioned source contract

Parser version `mixed-pickem-slate-v1` permanently supports UTF-8 CSV and XLSX.
The required canonical columns are away team, home team, spread, and spread
side. Optional columns are sport, kickoff, source event ID, and notes. Header
aliases are an explicit allowlist in the parser; values are never treated as
headers and an unrecognized layout requires a new parser version.

XLSX worksheet selection is explicit. The importer does not select a sheet by
position or guess among candidates. Macro content, external links, external
relationships, and untrusted formula cells are rejected. The importer reads
Open XML values without executing workbook content and retains the SHA-256 of
the original bytes. CSV and XLSX fixtures in this repository are entirely
fictional; real weekly pool sheets must not be committed.

Every nonblank data row enters immutable raw-row custody, including a physical
row number, source order, canonical raw-row JSON, raw team/spread/sport/kickoff/
event-ID/notes fields, row checksum, parse state, and exact errors. Invalid rows
are represented, never silently skipped.

## Exact spread representation

The v1 contract accepts whole- and half-point numeric spreads from -100 through
+100 and the explicit pick'em tokens `PK`, `PICK`, and `EVEN`. A required spread
side is `HOME`, `AWAY`, or an exact raw team name. The displayed value is stored
as signed integer millipoints and normalized to canonical home-team
millipoints. Raw text and orientation remain immutable.

NaN, infinity, unsupported increments, out-of-range values, missing
orientation, and contradictory/unknown sides fail review. Binary floating
point is not used for custody equality.

## Resolution and manifest review

Resolution is point-in-time and deterministic:

1. An explicit event ID from an explicitly named provider.
2. An exact sport-scoped canonical away/home pair within the configured UTC
   window.
3. Exact reviewed provider aliases within the same window.

There is no fuzzy matching, nickname guessing, cross-sport inference, or event
creation. The canonical `football_events` record supplies final sport,
orientation, kickoff, and neutral-site state. A sheet sport is only a check. A
sheet kickoff must carry an explicit timezone and equal the canonical kickoff.
Reversed teams, zero/multiple matches, cross-sport conflicts, stale kickoff,
and duplicate raw/matchup/event/source-ID representations fail closed.

`mixed_slate_manifests` and their immutable row records expose every raw and
canonical result, exact counts, ordered hashes, evidence, warnings, and errors.
`inspect_manifest` returns deterministic JSON suitable for human review. A
manifest is ready only when every represented row is accepted and the expected
row count equals the source row count. There is no partial approval.

## Lifecycle and approval

Append-only state events record the governed sequence:

`RECEIVED -> PARSED -> RESOLVED -> MANIFEST_READY -> OWNER_APPROVED -> LOCKED`

`NEEDS_REVIEW`, `AMBIGUOUS`, and `REJECTED` retain failure evidence and allow a
corrected new import while the round is not approved or locked. Parsing never
approves, and resolution never locks.

An immutable owner approval binds one manifest ID to its exact source SHA-256,
manifest SHA-256, accepted row count, event/kickoff evidence hash, reviewer,
timestamp, and provenance. Any count or checksum mismatch blocks approval. A
new source or changed manifest requires new approval evidence.

## Deadline and kickoff corrections

For a complete manifest, the entry deadline is the minimum canonical UTC
kickoff across every row. The immutable derivation stores the ordered
event/kickoff set hash, minimum kickoff, policy version, calculation time, and
row-level evidence. It is not derived from Thursday, contest round, sport week,
or prose.

Before lock, a later append-only event revision changes the current event set.
Approval and locking recompute the set as of their timestamp and reject a stale
derivation, including a verified earlier kickoff. Append-only event-revision
evidence is the only condition that lets a staged `MANIFEST_READY` or
`OWNER_APPROVED` round accept a replacement import. The operator must produce a
new reviewed manifest, deadline derivation, and owner approval; all prior
evidence remains immutable. After lock, neither deadline nor line custody is
silently mutated; operational alert/correction handling is intentionally
deferred to a later phase.

## Atomic immutable lock

Locking is a separate explicit operation after approval. One SQLite savepoint
creates the lock batch, every manifest line, a completion record, and the
round's `LOCKED` state. It verifies source count equals manifest count equals
approval count equals locked-line count, along with current deadline evidence,
manifest checksum, uniqueness, product/sport scope, and the ordered line-set
hash. Any failed row rolls back the whole batch.

Each `mixed_contest_lines` row binds the Product B round, canonical event and
sport, import/manifest row, raw and canonical teams, raw spread, exact home
spread millipoints, source/row/manifest/line checksums, lock time, and
provenance. Update and delete triggers make imports, manifests, approvals,
deadlines, batches, and lines append-only.

The same NCAA event may coexist with a Product A SplashSports line, a Product B
mixed line, and a sportsbook market record at different prices. Product B
uniqueness is round plus canonical event; no record overwrites or substitutes
another business identity.

## Offline build command

`python -m scripts.build_mixed_pickem_manifest` operates only on an explicitly
selected existing database with migration 20 already applied. It requires the
source, media type, existing Product B round ID, resolution window, explicit
timestamps, actor/provenance, and an unused review-output path. XLSX also
requires `--worksheet`. An expected source-row count and source-event provider
can be supplied. The command only imports, resolves, derives the deadline, and
writes review JSON; it has no approval or lock option.

Owner approval and locking deliberately remain library operations for this
phase so an application cannot conflate file upload with authority. No
production workflow invokes these paths.

## Failure and recovery

Malformed or ambiguous sources remain in immutable custody with their reasons.
Correct the governed identity/source/configuration, create a new import, inspect
all rows, and approve only the new exact manifest. Do not edit a generated
manifest, approval, deadline, batch, or locked line.

Migration recovery is restoration from a verified pre-migration disposable
copy followed by a new forward migration; migration 20 and ledger rows must not
be edited after merge. Before lock, transaction failure leaves no partial
batch. After lock, preserve the batch and audit evidence. Formal organizer
post-lock corrections, screenshot/manual-transcription authority, live
providers, operational scheduling, models, picks, and downstream grading are
all deferred.
