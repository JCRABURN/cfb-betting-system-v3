# Week 7 2026 evaluation — implementation and verification

## Objective and result

Evaluate the corrected, owner-approved Week 7 card and all frozen research
tracks without changing pregame selections, model policy or locked lines.
All 59 ATS and 59 totals selections are graded. The approved five went 2–3;
ATS full card 26–33; totals full card 33–26. Governed ATS and ATS research
Top 5 each went 3–2; totals research Top 5 2–3 and Top 10 4–6.

Grading is complete. The formal audit is **INCOMPLETE_CLV_CUSTODY** because
there are no timestamp-qualified pre-kickoff closing quotes. No policy change
is proposed. This is a contest/research evaluation, not a realized wagering
P&L report. Hypothetical unit calculations explicitly assume one-unit risk at
-110; actual prices and stakes were not recorded.

## Files changed

- `scripts/capture_week7_postgame_evidence.py`: separate one-time capture of
  an ESPN scoreboard and 59 completed game summaries, with timestamps and hashes.
- `scripts/build_week7_postgame_audit.py`: offline reconciliation, grading,
  twelve overlapping cohort comparisons, diagnostics, correction impact,
  custody checks and read-only deterministic replay.
- `tests/test_week7_postgame_audit.py`: 14 test cases including parameterized
  adversarial cases. No existing test or expected value was modified.
- `outputs/2026-week7-postgame-audit/`: exact compressed evidence, capture
  manifest, six CSV ledgers, diagnostics, report and audit manifest.
- `.gitattributes`: preserve new audit text/binary bytes and the original
  owner-approval bytes across checkouts.
- This verification document.

## Schema and behavior

No schema, migration, dependency, model coefficient, policy, prediction,
rank, confidence, locked line, manual adjustment or production workflow
changes. `data/cfb.db` is opened only with `mode=ro` and `query_only=ON`.
Final scores are joined to pregame game and team IDs; missing/duplicate IDs,
orientation conflicts, unfinished games, score conflicts, changed kickoff
times and checksum mismatches fail visibly. The capture and initial report
commands refuse to overwrite an existing capture/audit; `--verify` is read-only.

The postgame provider fields labeled close are stored separately. They do not
qualify as closing lines or CLV, and never replace contest lines. Backdoor
classifications remain explicitly unevaluated. The six historical total
corrections are compared separately; the invalidated original values are
counterfactual evidence only.

## Tests and exact commands executed

Working directory for the audit commands:
`C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.worktrees\week7-postgame-audit`.
The existing repository virtual environment was used; no package was installed.

```powershell
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m scripts.capture_week7_postgame_evidence
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m scripts.build_week7_postgame_audit
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m scripts.build_week7_postgame_audit --verify
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m pytest -q tests/test_week7_postgame_audit.py tests/test_week7_corrected_owner_approval.py tests/test_week7_source_correction.py tests/test_week7_prospective_seal.py
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m pytest -q
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m scripts.verify_repo_safety
& 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe' -m scripts.verify_week7_corrected_git_custody
git diff --check
```

Results in this environment:

- Capture: 59 completed summaries accepted, zero rejected, complete scoreboard coverage.
- Final focused suite: **23 passed in 3.26 seconds**.
- Broad suite run: **672 passed, 1 failed, 39 warnings in 139.07 seconds**.
  This run preceded the final code-hash portability regression test; the final
  focused run above includes that additional test and the final code.
- Sole broad-suite failure:
  `tests/test_week5_postgame_audit.py::test_audit_is_complete_and_never_rewrites_frozen_week5_inputs`.
  A Week 5 review file is checked out with CRLF while its sealed hash describes
  LF bytes. This failure is already documented on PR #37. Week 5 artifacts and
  tests were not altered. The same targeted test was also executed in the
  untouched `week7-prospective` worktree to confirm the pre-existing failure.
- Offline audit replay, repository safety and corrected Git custody: **PASS**.
  Git custody checks all 111 indexed corrected source/output/seal hashes.

New tests cover incorrect final scores, incomplete games, absent scores,
wrong team identity, swapped home/away teams, missing/duplicate events,
tampered evidence and approval bytes, refusal to overwrite, missing closing
custody, pushes, spread sign conventions, source corrections and complete
deterministic output replay.

Initial custody testing exposed checkout conversion of the original Week 7
approval. Its exact existing Git blob was restored in this new worktree and
verified against the pre-existing seal. Its content and Git blob are unchanged;
the added attribute prevents recurrence. Code hashes normalize only CRLF/LF
for portability; evidence and output hashes remain exact-byte SHA-256. Early
development outputs were preserved in temporary directories before regeneration;
the committed output comes from the final generator.

## Data-quality checks and acceptance evidence

- 59 distinct locked games, 59 matched finals, 59 ATS picks, 59 total picks;
  zero duplicates or ungraded rows; all corrected totals present.
- Team IDs, exact home/away orientation and kickoff timestamps match frozen
  pregame data and both ESPN endpoints. Every game is explicitly final.
- The original 89-file seal, corrected 96-output/14-source seal, corrected
  owner approval, source screenshots, lock hash and cross-manifest identity
  all pass. Pregame source contains no target results; cards and approvals
  precede the relevant kickoffs.
- Both research rank sets cover 1–59. Governed and owner Top 5 counts are five;
  Confidence is within 1–5. The original card manifest records zero fallbacks
  and zero skips. Every cohort's membership is exported for inspection.
- Read-only database integrity is `ok`; zero foreign-key violations;
  source SHA-256 is unchanged before/after:
  `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.
- Forecast MAE/RMSE, ranking bands, favorites/dogs, location, spread buckets,
  road favorites, confidence, raw/adjusted results and missing CLV comparisons
  are explicit. No numeric manual adjustment was recorded on these cards.
- Every saved output and raw payload is hashed; final replay reconstructs
  every CSV row, diagnostic and report without provider access.

## Known limitations and risks

CLV and key-number crossings are unverifiable. No backdoor classification is
claimed. Full-card scores are reconciled across two ESPN endpoints, not two
independent providers. Research scores are uncalibrated and the twelve cohorts
overlap; these observations cannot prove profitability, calibration, or a
stable ranking advantage. Governed ATS confidence is uniformly 1 and uncertainty
is absent, so its Top 5 must not be described as a reliability ranking.

The highest practical risk is confusing the corrected approval with the
superseded Under 72.5 approval, or confusing postgame close labels with qualified
CLV. Both distinctions are retained in machine-readable ledgers and the report.
The broader suite is not fully green on this Windows checkout because of the
pre-existing Week 5 checksum failure. The draft audit branch is stacked on
unmerged PR #37, which depends on #36 and #35; those are not approved or merged
by this evaluation. The requested PR target remains `main`; inherited changes
must receive their own review before this branch is eligible to merge.

## Independent checks of the five selected finals

The primary sources below were checked on October 20, 2026, in addition to the
recorded ESPN evidence. They corroborate the five scores; they are not used to
change any pregame feature or selection.

- [Air Force 41, UNLV 31 — Air Force Athletics](https://goairforcefalcons.com/news/2026/10/17/football-air-force-produces-430-rushing-yards-in-41-31-win-over-unlv).
- [Ohio State 19, Indiana 15 — Indiana Athletics](https://iuhoosiers.com/news/2026/10/17/football-win-streak-cracked-by-buckeyes-PETE).
- [James Madison 49, Georgia State 22 — Georgia State Athletics](https://georgiastatesports.com/news/2026/10/17/football-panthers-come-up-short-in-a-49-22-loss-to-james-madison.aspx).
- [Oregon 17, Nebraska 14 — Oregon Athletics](https://goducks.com/game-center/24382).
- [Texas State 66, Colorado State 27 — Texas State Athletics](https://txst.com/news/2026/10/15/football-game-recap-bobcats-dominate-colorado-state-66-27-in-pac-12-home-opener.aspx).

## Review, rollback and unrelated-file confirmation

The task diff is reviewed against pregame/monitoring head
`55c0a417c72492943253ad50cf139415ca3902be`. Only the files listed above belong to
this task. No original repository, main checkout work in progress, production
database, prior output, prior approval, model policy, secret or schedule changed.

Rollback is to close the draft PR or revert only this audit commit. Retain all
original/corrected pregame artifacts and owner approvals. No schema or data
migration rollback is required. Recomputing an audit after a source correction
must create a distinct version, preserving this evaluation.
