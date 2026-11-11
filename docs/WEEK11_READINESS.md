# 2026 Week 11 readiness and custody

## Current state

**TRANSCRIPTION RECONCILED; ORIGINAL IMAGE CUSTODY INCOMPLETE; MODEL EXECUTION
PENDING.** Concurrent PR #52 commits `64ffcb0`, `64c8f70`, `2664e16` and
`8cccef1c5f14b4230091fb443af92f8a5665c358` delivered the owner's 67-game line
transcription and metadata. Their complete commit ancestry is preserved by a
normal branch merge, not a force push. This supersedes the earlier no-receipt
statements below and in the archived readiness/elapsed-game snapshots.

The production CSV, row-by-row transcript and schedule reconciliation agree on
all 67 spreads, totals, teams and kickoffs. Source CSV SHA256 is
`a27f367a38918e188cc2e8aa417b9a1970049ca02d0501789d00ccfdb0b12c22`.
The four original source blobs and recorded hashes are unchanged. Exact-path
`-text` attributes restore their original LF bytes on Windows; no expected
source hash or historical artifact was changed.

The metadata references eight owner screenshots observed no later than
November 10 at 16:27:38 America/Chicago. It explicitly says the original image
bytes are not all available in the delivering runtime. One last-asset hash is
reported, but no image bytes are independently verified in this task. Full
visual transcription/custody is therefore **not certified complete**. A quote
timestamp is unknown. Receipt of the missing images and an independent visual
check remain required before certifying the official source lock and model seal.

There are **three elapsed scheduled games and 64 remaining** at the separate
01:40:28 UTC gate. Actual provider status must be refreshed before execution.
There are still **zero Week 11 ATS/totals picks**, no Top 10, no combined five and
no owner-approved selections. `python -m scripts.verify_week11_transcription`
checks all four exact source hashes, all 67 row correspondences and this gate.
It reports incomplete image custody rather than inventing image hashes.

## Original pre-screenshot readiness snapshot (preserved)

READINESS PREPARED; CONTEST SOURCE PENDING. Owner approval remains PENDING.
No Week 11 owner SplashSports screenshots have been received. There are zero
locked contest games, zero ATS selections, zero totals selections and no Top 10
or combined Top 5. Market observations are separate evidence, never substitutes
for contest lines. Screenshot coverage and lined contest coverage remain unknown.

The independently reconciled schedule contains **67 FBS games: 67 FBS-versus-FBS,
zero FBS-versus-FCS/other**, all upcoming at the capture timestamp. All have
prior-week season EPA inputs and resolved provider IDs/orientation. No game is
silently excluded. These counts describe the schedule, not confirmed contest
eligibility. The collector deliberately requests all classifications and the
reconciler retains either-side-FBS games; an adversarial FCS case is tested.

The first games are Kent State at Bowling Green and Western Michigan at Akron
on November 10 at **18:00 America/Chicago**, then Ohio at Miami (OH) at 19:00.
Eligibility must be refreshed at actual generation. Any game already started
then must be recorded as elapsed, never assigned a backdated prospective pick.

**Later execution gate, November 10 at 19:40:28 America/Chicago:** the archived
scheduled kickoffs of those three games have elapsed. The separate
`kickoff-gate-20261111T014028Z.json` preserves this decision without rewriting the
earlier 67-upcoming readiness snapshot. Sixty-four games remain upcoming by the
archived schedule; refresh live schedule/status before actual execution. No
postgame information was retrieved for this gate and no selections were backfilled.

## Verified baseline and historical preservation

Base main: `95a21305c6676383bcfbd0405954975fbfe38ddf`.

| Delivery | Original head | Merge |
|---|---|---|
| PR #49 Week 10 | `a2a98cf460be6564d7df3dafe81ba7f467b807c9` | `3bb2814924ddf5057f2cce3b46245560fcd2927f` |
| PR #51 formal audit | `24c3eb44b6f0951bb32203dcb16c561e6568a9e6` | `95a21305c6676383bcfbd0405954975fbfe38ddf` |

Both original heads are ancestors of main. PR #51's source tree equals main's
tree `483a40165439c628e4805832ed93a6ff20b3db65`. Recorded proof commands:

```text
git merge-base --is-ancestor a2a98cf460be6564d7df3dafe81ba7f467b807c9 95a21305c6676383bcfbd0405954975fbfe38ddf
git merge-base --is-ancestor 24c3eb44b6f0951bb32203dcb16c561e6568a9e6 95a21305c6676383bcfbd0405954975fbfe38ddf
git diff --exit-code 24c3eb44b6f0951bb32203dcb16c561e6568a9e6 95a21305c6676383bcfbd0405954975fbfe38ddf
```

Source database SHA256:
`09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.
Read-only SQLite integrity is `ok`, with zero foreign-key violations. The existing
Week 10 audit custody verifier checks 3,266 pinned inputs/historical controls;
Week 10 source lines, 57 ATS and 57 totals, forecasts, owner-review revisions,
research shadow and audit evidence are unchanged.

Master Prompt **v2.8 remains governing**, under the owner's instruction and
preserved Week 10 governance. No standalone Master Prompt text is tracked;
`production_policies.example.json` contains implementation-version metadata and
proposed registration provenance, not independent permission to promote policy.
The readiness output records LF-normalized hashes of the unchanged implementation
and policy files; original historical byte checks remain unchanged.

## Source capture and coverage artifacts

All paths below are under `outputs/2026-week11-readiness/`:

* `20261110T193209Z/`: 13 timestamped responses and capture manifest. CFBD all
  2026 games, FBS/all-team registries, venues, season advanced through Week 10,
  separate Week 11 market observations, Week 8–10 advanced games/drives and ESPN.
* `20261110T193338Z-schedule/`: preserved failed ESPN date-range request, HTTP 400.
* `20261110T193425Z-schedule-v2/`: successful complete ESPN week request.
* `repository-baseline.json`: ancestry, exact tree and source database evidence.
* `prepared-v1/coverage.csv` and `schedule.json`: every scheduled matchup,
  kickoff, venue, provider IDs, feature status, prior opponent and rest interval.
* `prepared-v1/provider-mappings.json` and `resolver-aliases.json`: canonical
  mappings and aliases. Miami OH maps to Miami (OH) through the canonical resolver.
* `prepared-v1/market-observations-NOT-CONTEST-LINES.json`: 134 separate market
  observations across all 67 games, qualified-close false. Retrieval timestamp
  does not establish that a quote is a historical closing line. CLV is INCOMPLETE.
* `prepared-v1/readiness.json` and `manifest.json`: counts, blockers, historical
  custody results, exact derived-output hashes and capture/code references.

Each captured HTTP body is preserved as deterministic gzip, with both raw and
stored hashes, endpoint, nonsecret parameters, request/receipt times and capture
code identity. The 19 raw/baseline files are independently pinned by the test
fixture; seven derived files replay exactly. Original source bytes are not
normalized. Capture code hashing explicitly normalizes source CRLF to LF only.
The baseline and input-custody fixture retain their originally written CRLF
bytes. Two exact-path `whitespace=cr-at-eol` declarations recognize those line
endings without suppressing other whitespace errors or changing their hashes.

**Provider discrepancy resolved:** ESPN's initial `limit=1000` response returned
25 games. A date-range retry returned HTTP 400, "Failed to get events endpoint."
Both records remain intact. A separate `year=2026, week=11, seasontype=2,
groups=80, limit=300` response returned 67, exactly matching CFBD IDs, orientation
and kickoff timestamps. We observed these request/response differences; we do not
claim to have proven ESPN's internal reason for the inconsistent limit behavior.

Point-in-time inputs are captured before the first Week 11 kickoff. Season EPA
is explicitly bounded at endWeek 10; recent game/drives must reference completed
Weeks 8–10 games. Season EPA excludes garbage time and recent advanced games do
not; this distinction remains explicit for any later research feature design.

## Audit lessons applied to readiness

Week 10 ATS and totals each went **26–31, -7.363636 units** risking one at -110.
ATS MAE was 14.122 versus the locked-line baseline 12.798; totals MAE was 15.155
versus 13.132. Governed ATS Top 5 went 2–3; ATS research, totals research and
combined research went 1–4 each; the human five went 0–5. PR #50's prospective
controlled combined five also went 1–4, sharing four losers with the ATS benchmark
and exchanging one winner for another. It did not improve selection quality.

Weeks 5–10 cumulative ATS was 168–168 (-15.272727u), totals 167–169 (-17.181818u).
Totals Confidence 1–2 went 119–99; Confidence 3–5 went 48–70. The governed ATS
confidence remained 1. These scores do not establish calibrated probabilities.
Large model/line gaps require investigation, not automatically stronger confidence.
Cumulative EPA does not explicitly model pace, possession volume, explosive
plays or current QB/OL/defensive personnel. The Week 10 102-point Boise State–
Colorado State game on 23 drives also shows why pace alone is insufficient.

Separate research in `research/week11_validation/` reports all fixed 25%/50%
anchor and prior-only calibration candidates. It is retrospective exploration
specified after Week 10, not a new official model or prospective success claim.
No candidate changes the locked-line baseline's superior Week 10 point accuracy.
The drive-based estimator and prospective Week 11 shadow are explicitly pending.

## Execution and context gates still outstanding

1. Receive actual original owner screenshots; preserve bytes, actual receipt
   timestamp and hashes. Independently transcribe every spread/total, reconcile
   all 67 schedule rows with screenshot coverage, and explain every difference.
   Unknown contest inclusion is not evidence that a game is unlined or excluded.
2. Freeze qualified contest lines and refresh game status before prospective
   execution. Do not change an original line using the separately captured market.
3. Run the unchanged v2.8 ATS and existing totals implementation in a separate
   append-only Week 11 executor; produce every eligible lined game, governing
   confidence, ATS/totals Top 10 and clearly labeled combined research candidates.
   The readiness helper deliberately cannot execute picks even if handed a claimed
   screenshot manifest; it is not a substitute for verified ingestion.
4. Review all Top 10 candidates with primary-source QB/backup, OL, defense,
   coaching, weather/wind, recent efficiency, possessions, explosives, travel/rest
   and separate market evidence. These candidate-specific reviews are not yet
   completed because the contest candidates do not exist. No numeric adjustments
   or contextual recommendations have been invented.
5. Seal all forward research separately before each kickoff; retain every method
   and evaluate only after finals. No v2.9 promotion or new confidence policy.

## Verification and change scope

Initial focused readiness suite: **22 passed in 9.07 seconds**, native Windows
Python 3.12.14. Full-suite and exact-head cross-platform results belong in the
draft PR verification record after execution; this document does not predeclare
their success.

The first source head `7a8164d828cdb60437b5609de1f848523424eec1` passed the native
Windows suite: 1,046 passed, 39 pre-existing deprecation warnings, 556.45 seconds.
Initial CI passed both Python 3.12 jobs but failed the new research replay test
on both Python 3.11 jobs. The sole mismatch was ten signed-zero JSON values.
The separate research v2 implementation and original-byte custody gate repair
the integer-count calculation without altering original research evidence; see
the research README and machine-readable repair evidence. A pre-commit test
fixture also initially assigned WIN to an already-WIN result; correcting it to
flip the grade produced 44 passing focused tests in 9.10 seconds. Final-head
full-suite results must be checked separately from these prior-head results.

The source-transcription verifier initially encountered three test failures
because native Windows has no `tzdata` package. It now validates the observed
UTC-06:00 offset against both provider kickoffs for the bounded November 10–14
card, rejecting other dates. It does not depend on an implicit host timezone
database or introduce a new dependency. Its ten focused tests pass. A full-suite
attempt on local repair head `8b1aadb` was intentionally interrupted after the
concurrent source commits were discovered, so it is not claimed as exact-tree
verification. Final integrated-head results are recorded separately in the PR.

```text
python -m pytest -q tests/test_week11_readiness.py tests/test_week11_anchor_research.py
python -m pytest -q
python -m scripts.prepare_week11_readiness --verify
python -m research.week11_validation.anchor_diagnostics_v2 --verify
python -m scripts.verify_week11_transcription
python -m scripts.verify_week10_acceptance
python -m scripts.build_week10_formal_audit --verify
python scripts/verify_repo_safety.py
python -m scripts.verify_migrations
python -m scripts.verify_cloud_migrations
```

New tests cover capture-byte tampering, exact file coverage, missing/duplicate
games, provider orientation/kickoff/classification conflicts, future data,
FCS retention, missing EPA/market evidence, elapsed games, output overwrite,
rejection of unverified contest sources, chronological research splits and
evaluation-outcome independence of fitted probabilities.

Changes are limited to new Week 11 capture/reconciliation/research code, tests,
evidence and documentation, exact-byte attributes for those new artifacts, and
two read-only steps added to the existing CI workflow. The complete Linux/Windows
Python matrix and every existing safety/custody gate remain active. No operational
workflow, secret, permission, model, policy or historical file is changed.
Schema changes: **none**. Source database writes: **none**.

Risks/limitations: missing contest evidence, scheduled kickoff changes, provider
revision after capture, unvalidated confidence/ranking and incomplete drive-model
validation. Replay proves the archived snapshot, not future schedule freshness.
Rollback is to close or revert this focused branch while retaining captured
evidence; no database migration or historical-artifact replacement is needed.
