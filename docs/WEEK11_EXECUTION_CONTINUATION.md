# Week 11 execution continuation — November 11, 2026

## Screenshot recovery supersession — 15:29 UTC

The eight original attachments were recovered through the Codex task-history
reader from **Review PR 51**, thread `6af280dc-1860-83ea-9bd9-d990eb4ca6dd`,
user turn `0a429164-aaab-4f71-b794-2dee9941128b`. The recorded original chat
receipt is **2026-11-10T22:25:54.183000+00:00**; local recovery is separately
recorded as **2026-11-11T15:29:26.328595+00:00**. Neither is invented as the
unknown screenshot quote timestamp. All original images are now preserved with
byte hashes under `outputs/2026-week11-prospective/source-evidence/`.

Independent visual transcription of all67 rows reconciles all spreads, totals,
teams, weekdays and clocks with **zero discrepancies**. The previously reported
last available asset hash matches chronological screenshot01. The task-history
attachment list is reversed relative to chronological card order; original
metadata is preserved and the resolution is recorded separately.

This supersedes the missing-image blocker below, which describes the earlier
09:15 CST eligibility snapshot. The original 67-row source remains unchanged.
Execution uses a separately derived upcoming subset after a fresh live status
capture. No owner betting approval is inferred from source recovery.

## Integrated baseline and scope

GitHub reports PR #52 merged on November 11 at 03:22:53 UTC into main
`d3ba84db74b67a6e4dd8d61e49f28c0759d3a34e`. Its tree is
`fcedf3731c3b6848a5acea5eb9d4a371bd51f413`, identical to source head
`bf3fedb1fa2fe8831c2b8a1a7bab54ae68992722` and the previously tested merge
`273cb9274c8e3f63c4e55de6248ac35901eca3a8`. Both Week10 PRs #49 and #51 are
ancestors. This records an observed merge; this task did not merge it. The
GitHub review and discussion APIs returned empty lists on November11. A merge
does not establish an independent APPROVED review or owner betting approval.

Prior-tree CI: [run42941703445](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/42941703445)
passed all four Windows/Linux Python3.11/3.12 jobs, 1,065 tests each. These are
prior-tree results, not results for this new execution prerequisite. The new
PR records its own exact source/tested-merge identities and verification.

## New schedule evidence

`scripts/week11_eligibility.py` captured both official providers at
**2026-11-11T15:15:38.962609+00:00 (09:15:38 CST)** using code commit
`290863b9907aeda3970b5f6e0fca66e7b2b636a6`.

Evidence directory: `outputs/2026-week11-readiness/20261111T151538Z-eligibility/`.
Both raw HTTP200 responses, raw/stored hashes, request parameters, actual request
and receipt timestamps, and the exact replayable ledger are preserved. Each of
the four artifact hashes is pinned independently in the tests. No expected
historical hash changed. Raw responses can contain Week11 scores and are
**prohibited as model inputs**; only identity, kickoff and current status are
used here. No Week11 score was used to generate or revise a forecast.

| Check | Result |
|---|---:|
| Original source line pairs retained | 67 |
| Current provider matchups reconciled | 67 |
| FBS-versus-FBS / FBS-versus-FCS | 67 / 0 |
| Completed games excluded from future picks | 3 |
| Upcoming by both providers at capture | 64 |
| Kickoff, identity or status conflicts | 0 |
| Verified original images in this task | 0 of 8 |
| New locks, ATS predictions, totals predictions | 0 / 0 / 0 |

The completed exclusions are Western Michigan at Akron (`401866458`), Kent
State at Bowling Green (`401866459`), and Ohio at Miami OH (`401866460`). Both
providers now report completion. No prospective selections exist for them.
Every original row and line remains available; exclusion does not delete a row.

Wednesday November11's three upcoming games start at **18:30 CST**:

| Matchup | Original home spread | Original total |
|---|---:|---:|
| Buffalo at Ball State | Ball State +2.5 | 51.5 |
| Sacramento State at Central Michigan | Central Michigan -17.5 | 43.5 |
| Massachusetts at Toledo | Toledo -14.5 | 51.5 |

These are source lines, **not recommendations**. The eligibility ledger is a
timestamped observation. It cannot authorize execution later without refreshing
both provider statuses and checking the actual clock. A later advertised kickoff
cannot revive a game whose original kickoff has elapsed. Unknown statuses,
additional/missing FBS games including FCS opponents, contradictory identities,
or altered contest lines fail closed. Provider kickoff changes, TBD times and
nonzero pregame scores block an affected upcoming game.

## Remaining execution blockers

Eight original screenshots were described in the owner's separate source
delivery, but complete image bytes remain unavailable here. The existing CSV,
transcription and reconciliation agree on all67 pairs; that agreement cannot
substitute for independently checking the actual images. No new Week11 images
were found in this worktree or the available recent Codex attachment files.
The previous request for their local/attachment paths remains unresolved.

Preserve and inspect all eight originals, record actual receipt/verification
times, then reconcile them to the unchanged source CSV SHA256
`a27f367a38918e188cc2e8aa417b9a1970049ca02d0501789d00ccfdb0b12c22`.
Do not fabricate original quote times or replace any number with a market line.
Formal disposable-database locks, unchanged v2.8 execution, full cards, separate
Top10s, candidate-specific primary-source context and the forward research
shadow remain pending. No combined five or owner approval is declared.

## Tests, changes, and recovery

Changes are limited to one new eligibility module, its adversarial tests, four
new evidence files, and this document. No existing implementation, policy,
workflow, security setting, source database, schema or historical artifact is
modified. Tests exercise both provider coverage, FCS additions, identity and
classification, source-line alteration, late kickoffs, status contradictions,
contamination, exact replay, missing checksums, raw-byte tampering and output
tampering. Original screenshot custody remains explicitly incomplete.

Executed initial focused test command: `python -X utf8 -m pytest -q
tests/test_week11_eligibility.py`: 23 passed in6.01s before the nine final custody
tests were added. Final-tree results and full-suite results belong in the PR
after execution. Read-only replay:

```text
python -m scripts.week11_eligibility --verify outputs/2026-week11-readiness/20261111T151538Z-eligibility
python -m scripts.prepare_week11_readiness --verify
python -m scripts.verify_week11_transcription
python -m scripts.verify_week10_acceptance
python -m scripts.build_week10_formal_audit --verify
python scripts/verify_repo_safety.py
python -m pytest -q
```

Risks are missing image custody, elapsed games, stale status observations and
unvalidated confidence. v2.8 and all earlier research remain unchanged. Rollback
is to revert the new eligibility helper/tests/documentation while retaining
captured source evidence; no database migration or historical rewrite is needed.
Independent technical review remains required for this new PR. No merge is
performed by this task.
