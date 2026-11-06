# Week 7 acceptance research: verification and completion record

## Objective and scope

Independently assess PRs #35–#38, preserve all archived picks and lines, compute cross-week research diagnostics, and deliver an additive draft PR. Formal CLV remains INCOMPLETE. No deployment or policy promotion.

Validation baseline: `da7381b801abee170a8b321cf77d833626230a11` (PR #38), which includes the reviewed heads of #35, #36 and #37. Working branch: `codex/week7-acceptance-cross-week-diagnostics`. Verification checkout: `.worktrees/week7-acceptance`. The delivery branch/PR contains only this new additive evidence patch against main; it depends on #38 and must not be run on bare main without those prerequisites. Its PR description identifies the final delivery commit and the validated combined-tree commit.

## Files changed

All files are additions relative to #38:

- `scripts/research_week7_acceptance.py`: offline independent grading, exact/diagnosed custody, historical joins, numerical diagnostics, reproducible output manifest and read-only verification mode.
- `scripts/verify_week7_acceptance_copy.py`: disposable-copy test utility; resolves only exact recorded Week 5 EOL variants in that copy, without changing source files or expected hashes.
- `tests/test_week7_acceptance_research.py`: 12 acceptance tests. Covers all 118 Week 7 grades, the exact owner five, disjoint rank cohorts, duplicate/contamination rejection, push accounting, EOL-versus-content diagnosis, raw component arithmetic/cutoffs, manifest coverage/status, and disposable reproductions of inherited verifier/writer defects.
- `docs/WEEK7_AUDIT_ACCEPTANCE_AND_RESEARCH.md`: full findings, numerical interpretation, limitations, dependency recommendation, and RESEARCH ONLY proposals.
- `docs/WEEK7_ACCEPTANCE_VERIFICATION.md`: this verification record.
- `outputs/2026-week7-acceptance-research/.gitattributes`: preserves exact bytes of the new evidence directory.
- Generated evidence: `diagnostics.json`, `diagnostic_tables.md`, `selection_ledger.csv`, `weekly_metrics.csv`, `segments_week5_7.csv`, `earlier_week_segments.csv`, `rank_nonoverlap.csv`, `correlations.csv`, `time_split_replay.csv`, `custody_checks.json`, `week7_custody_details.json`, `research_manifest.json`.
- Recovered/review source evidence: `source-evidence/git-recovery.json`, `review_observations.json`, `week1_local_workbook_review.json`, `week2-pregame.json`, `week2-lock-manifest.json`, `week3-execution.json`, `week3-pregame-ats.json`, `week3-pregame-totals.json`.

## Schema and behavioral changes

Schema changes/migrations: none. Production behavior: none. The new command writes only its dedicated research output directory, or compares it read-only with `--verify`. It never imports a forecast/grading engine, mutates the source DB, changes original outputs, obtains live provider data, or places a wager. It uses existing Python/pytest, with no dependency additions.

Research text hashes explicitly use canonical LF; original custody checks continue to require the original exact bytes and report EOL differences separately. The new artifact manifest does not pretend that text normalization repairs historical custody. The disposable-copy test is a diagnosis, not an in-place repair.

## Exact verification commands and results

Executed in PowerShell from the verification checkout, using the existing environment:

```powershell
$py = 'C:\Users\jraburn\Documents\GitHub\cfb-betting-system-v3\.venv\Scripts\python.exe'
& $py -m scripts.build_week7_postgame_audit --verify
& $py -m scripts.research_week7_acceptance
& $py -m scripts.research_week7_acceptance --verify
& $py -m pytest -q tests/test_week7_acceptance_research.py
& $py -m pytest -q tests/test_week7_acceptance_research.py tests/test_week7_postgame_audit.py tests/test_week7_corrected_owner_approval.py tests/test_week7_source_correction.py tests/test_week7_prospective_seal.py
& $py -m pytest -q
& $py -m scripts.verify_week7_acceptance_copy
git diff --check
```

Results observed in this environment:

| Check | Result |
|---|---|
| Original Week 7 replay | PASS: COMPLETE_59_ATS_59_TOTALS, formal INCOMPLETE_CLV_CUSTODY |
| Independent research generation and byte-for-byte replay | PASS; deterministic seeded statistics and original checksum gates |
| New acceptance tests | 12 passed |
| Week 7 focused group | 35 passed |
| Full suite in unmodified LF verification checkout | **684 passed, 2 failed**, 39 warnings, 137.51 s |
| Full suite in disposable exact-byte Week 5 copy | **686 passed**, 39 warnings, 112.41 s; 53 EOL-only byte variants restored in the copy, zero original files modified |

The full unmodified-checkout failures are:

1. `tests/test_week5_postgame_audit.py::test_audit_is_complete_and_never_rewrites_frozen_week5_inputs`, at line 207.
2. `tests/test_week5_review.py::test_v4_hash_custody_and_locked_snapshot_unchanged`, at line 25.

Both first encounter `prior-evidence/week1-postgame-audit.csv`: expected `b9248fd7db2ba2cde5ba3674f61683522d9a6f885811441846368f82092dcf20`, LF checkout `0b7da8cd62a9b878e6da6398c0f786e023993a47fc4b4176fc86eb3d02f03759`. All 53 mismatches are enumerated in `custody_checks.json`, each resolving exactly to a newline variant. No failing test was edited, deleted, skipped or weakened. The 39 warnings are existing UTC datetime deprecations.

An initial diagnostic-development run failed because Week 6's mixed review CSV identifies selections by market/matchup rather than game ID. The new adapter was corrected to join those explicit fields and check the line and selection; no historical row was edited. The recorded successful results above supersede that development run. Final focused checks/replay were rerun after the final diagnostic changes; the full-suite results remain explicitly separated by environment.

Git ancestry commands each returned exit 0:

```text
git merge-base --is-ancestor 57c33b29aa399e4d94c749f6e2d25a6e80b48262 48d0250aff3fc286b7b8bd06e7e798a4134910a5
git merge-base --is-ancestor 48d0250aff3fc286b7b8bd06e7e798a4134910a5 55c0a417c72492943253ad50cf139415ca3902be
git merge-base --is-ancestor 55c0a417c72492943253ad50cf139415ca3902be da7381b801abee170a8b321cf77d833626230a11
```

## Data-quality checks

59 unique games per market; all 118 grades agree independently; five approval identities/lines/ranks/scores reconcile; final scores for those five corroborated by official athletics pages; 419 manifest entries examined across Weeks 5–7; Week 6/7 exact-byte custody passes; zero unresolved Week 5 content differences; all 59 Week 7 raw component forecasts reproduce; target features at or before Week 6; result-free pregame target schedule; source/capture/card/seal/approval timestamps before kickoff; all required 69 Week 7 output hashes and three code hashes present; zero qualified CLV; no raw/manual projection divergence; zero source DB hash change; original read-only integrity/FK replay passes.

Historical inclusion is explicit: Week 2 n=49 per market from a pregame Git commit; Week 3 n=56 per market from a pregame provisional archive with one preserved kickoff skip; Week 1 n=43 ATS audit context only; Week 4 missing, not reconstructed. The combined ledger contains 599 market observations, not 599 independent games. Ranking segments never overlap within market/week. Primary final-score observations are factual reviewer notes with links, not full immutable HTML archives or timestamp-qualified market evidence.

## Known limitations and risks

- Bare-main delivery depends on the unmerged #35–#38 stack; tests require those artifacts/modules. The PR is intentionally draft/dependency-blocked.
- Unmodified checkout full suite is not clean until the inherited Week 5 custody issue is corrected in its own reviewed change.
- Existing Week 6 writer and Week 7 verifier defects are reproduced, not repaired by changing historical code. The new independent acceptance gate protects this analysis.
- CLV is unavailable; 54 Week 7 finals lack an independent second-provider reconciliation beyond ESPN scoreboard/summary. Full original approval-message export and full independent 4,944-row training refit are outside this evidence set.
- Small selected cohorts, repeated teams and only three comparable ranking weeks limit inference. Earlier weeks have different eligibility/custody. No new result here is a prospective validation of a new rule.
- The most material risk is treating descriptive success, a retrospective candidate or the owner five as an independently validated betting recommendation. All outputs are labeled RESEARCH ONLY and preserve v2.8.

## Rollback and unrelated-file confirmation

Before merge, close the evidence PR or discard its delivery branch. After merge, revert only its additive commit through a reviewed PR. No migration, data restoration, schedule shutdown or policy rollback is needed. Do not delete or regenerate historical cards/audits during rollback.

Review the complete staged diff and name-status list before commit; it must contain only additions listed above. No unrelated tracked file changes are included. The pre-existing dirty NFL foundation checkout was not edited, committed, reset, or stashed. The original `cfb-betting-system` repository was never modified.
