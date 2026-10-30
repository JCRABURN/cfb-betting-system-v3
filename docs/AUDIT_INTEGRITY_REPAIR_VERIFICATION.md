# Audit integrity repair and dependency integration

Objective: close the Week 6 overwrite and Week 7 acceptance-gate defects, reproduce original Week 5 checksum bytes through Git checkout attributes, and correct approval/runbook identification without altering historical evidence or v2.8.

## Exact integration inputs

| PR | Head inspected and included | Dependency |
|---|---|---|
| #35 | `57c33b29aa399e4d94c749f6e2d25a6e80b48262` | main `abb4eb26bd1140e66972d2f1143cd587e80960b4` |
| #36 | `48d0250aff3fc286b7b8bd06e7e798a4134910a5` | #35 |
| #37 | `55c0a417c72492943253ad50cf139415ca3902be` | #36 |
| #38 | `da7381b801abee170a8b321cf77d833626230a11` | contains #35–37 ancestry |
| #39 | `3148e4fe7cd7ab9387048386903db68ad7c2de4b` | #38; original 56-row Week 8 ingest |
| #40 | `5f07ca3d9e52d1b467886856f1ec6f36562728a3` | additive evidence requiring #35–38 |

The integration branch merges #40 into #39's tree, thereby retaining every dependency commit. Repair implementation is `3d82f881d10803a84bb3c700e911f4e2968ffb95`; final delivery additionally records checkout/replay regression tests and this report. A fresh checkout of that repair commit was used for verification, with the additional regression tests present during the complete suite. No disposable corrected repository was used for the full suite. The final PR head records the exact tested code and tests; documentation-only additions do not change execution.

## Changes and behavior

- `.gitattributes`: all three Week 5 directories retain original blobs with `-text`, except 53 specifically identified LF Git blobs requiring `text eol=crlf` to reproduce their original sealed working bytes. Original expected hashes are unchanged. The Week 8 PR39 CSV is also byte-preserved.
- `scripts/build_week6_postgame_audit.py`: preflight all 13 output destinations before grading, including partial audits; separately guard direct `finish` calls. CSV, JSON and Markdown writes use exclusive creation to reject a destination created after preflight. Existing provider evidence remains an input. A concurrent failure may leave new partial outputs; these are retained and future runs fail closed, never replace them.
- `scripts/verify_week7_audit_integrity.py`: canonical read-only acceptance entry point, integrity-v2. Require the exact original 69-output/3-code inventory, original digest values, exact status/identity fields and actual file inventory. Then replay all 118 selections and require replay/status agreement. The original hash-sealed v1 script remains unchanged as historical replay evidence; its weaker CLI is not an acceptance gate.
- `tests/fixtures/audit_integrity/week7_expected_manifest.json`: exact original manifest copied as a fixed inventory; regression pins its canonical hash `5192ebeac49e6a999af1af48c78f084b3574882468466e9df4e62195df6031a1`.
- `tests/fixtures/audit_integrity/protected_git_blobs.json`: pins all 610 pre-repair tracked output, production-line, ingest and source-database Git blobs. Regression checks index identity and no unstaged historical-content change.
- `docs/WEEK7_PROSPECTIVE_RUNBOOK.md`: adds current state and strict acceptance command while retaining the original pre-source planning text verbatim under a superseded heading.
- `docs/evidence/week7-approval-identification-correction.json`: additive correction identifying `cfbe724fc9687dea24bd50409bcc4a4c2214aec4` as the approval-containing commit. Original `d3ffcc24316af7deee7f9f0aebce9b46cb3fac80` field is retained and identified as parent/pending-card context. Original approval SHA-256 remains `31dd412b3e6c16f3f871e4dc0276c3b2c84c2faae95715ac20eb39d648042568`.
- `tests/test_audit_integrity_repairs.py`: 38 new cases covering every partial destination, exclusive-write races, valid new writes, missing/extra/changed/empty hash inventories, simultaneous file/hash omission, contradictory statuses/types, protected blobs, exact custody, deterministic Week 6 replay, both autocrlf settings, and approval correction.
- `tests/test_week7_acceptance_research.py`: the Week 6 defect reproduction becomes an overwrite-rejection regression. This expectation changed because the defect is repaired; no integrity assertion is weakened. The v1 Week 7 historical-defect reproduction remains useful and is accompanied by strict-v2 rejection tests.
- This verification report.

Schema changes: none. No new dependencies, database migration or source database mutation. Model, ranking, confidence, policy configuration, frozen selections, scores, lines, seals and expected source hashes are unchanged. No unrelated files changed by these repair commits. Root worktree NFL changes remain untouched.

## Commands and results from this environment

Working directory: `C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.worktrees/audit-integrity-repair`.

Interpreter: `C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.venv/Scripts/python.exe` (abbreviated `$py` below).

```powershell
$py = 'C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.venv/Scripts/python.exe'
& $py -m scripts.verify_week7_audit_integrity
& $py -m pytest -q tests/test_audit_integrity_repairs.py tests/test_week7_acceptance_research.py tests/test_week5_postgame_audit.py tests/test_week5_review.py
& $py -m pytest -q
git diff --check
git diff --stat
```

- Strict verifier: PASS. `COMPLETE_59_ATS_59_TOTALS`, `INCOMPLETE_CLV_CUSTODY`, 419/419 exact original custody hashes, 10/10 numerical research outputs replayed byte-for-byte.
- Focused suite before three additional checkout/replay regressions: **80 passed in 14.76 s**.
- Complete suite, including all added regressions: **724 passed, 39 warnings in 176.77 s**. Zero failed, skipped or unexplained cases. Warnings are existing `datetime.utcnow()` deprecations in historical backfill, dashboard, card and DB code/tests.
- Both `core.autocrlf=true` and `false` checkouts: every one of the 179 Week 5 expected hashes matches unchanged assertions.
- Week 6 deterministic replay: all 12 non-manifest outputs exactly match original bytes. Manifest equality also passes after changing only the temporary replay destination prefix back to the original path; every digest and other field is identical. Temporary output generation is the test destination, not a corrected repository copy.
- Protected historical Git blobs: 610/610 unchanged; original source DB SHA-256 `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842` preserved.
- Whitespace diff check: PASS. Full repair diff reviewed; no shared model/policy edits.

Initial command failures: a PowerShell `< NUL` redirection was rejected before execution; a text-mode checkout-index input supplied CRLF path separators and was rejected; NUL-delimited retry succeeded but checkout-index retained already-stat-clean LF files. Strict verification correctly rejected those 53 nonmatching hashes. A fresh normal Git worktree checkout using the committed attributes reproduced all expected bytes and passed. These were resolved setup failures, not suppressed tests or revised checksum expectations.

The archived PR40 `custody_checks.json` intentionally continues to describe its original LF checkout. The new verifier first validates all historical research input/output/code hashes, then requires all current custody bytes to match original hashes, confirms identical content identities across the old/new custody observations, and independently replays every numerical output. The old `research_week7_acceptance --verify` compares an environment-dependent custody report and is therefore not the repaired-tree acceptance command. Original PR40 evidence is not regenerated.

## Integration recommendation and limitations

The repaired combined tree meets code-integrity gates and is eligible for review. Integrate #35 → #36 → #37 → #38, then #39 and #40, together with the repair commits; or review the combined main-targeted integration PR. Do not merge unrepaired intermediate heads as an accepted final state. No GitHub PR was merged by this task. Re-run gates if any dependency head changes.

Historical CLV remains **INCOMPLETE**: no timestamp-qualified closing evidence was found or invented. Grading acceptance and safe code integration can proceed without declaring formal CLV completion. CLV absence does not block unrelated code merges; formal audit completion and any new ranking/selection-policy promotion remain gated. v2.8 is preserved.

Week 8 execution is delivered separately from these focused repair commits. Its original PR39 CSV is included unchanged in this integration tree. Three already-final games cannot be represented as prospective picks.

Risk: operators using the old sealed Week 7 CLI alone would still bypass the strengthened acceptance checks. The corrected runbook explicitly names the required strict entry point; the old implementation remains solely for historical code/hash reproducibility. Git attributes affect checkout representation, not historical content. Existing checkouts should be refreshed from the repaired commit rather than manually rewriting artifacts.

Rollback: revert only the repair commits on a new reviewed branch; retain all historical artifacts and the original hashes. Such rollback reintroduces known verifier/overwrite/EOL defects and must mark acceptance blocked. No database restore or policy rollback is needed because neither changed.
