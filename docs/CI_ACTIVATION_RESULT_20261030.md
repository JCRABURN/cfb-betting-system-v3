# Authorized CI-only activation result — HOLD

The owner authorized the bounded procedure in `CI_ACTIVATION_PROPOSAL.md`.
Repository Actions was disabled at preflight. The existing CI workflow was
active; no duplicate workflow or trigger repair was needed. On October 30,
the six specified operational workflows were disabled and read back before
repository Actions was enabled. The unchanged PRs were closed and reopened,
remaining drafts. Independent GitHub execution now exists, but both runs failed.

| PR | Exact source head | GitHub-tested merge commit | Result |
|---|---|---|---|
| 44 | `922f1f8f8c66ef14674eb9aa20db144a45dada68` | `183398e54172058472184f1704f32c4cda8033a4` | 764 passed, 5 failed; 157.49 seconds |
| 45 | `6e1948dd9b675a3f1226350ce5b40a6556e09f7a` | `295456f93c6fdfcfcf2d65b9f61d73733ca319a2` | 803 passed, 6 failed; 165.43 seconds |

Both merge commits use base `abb4eb26bd1140e66972d2f1143cd587e80960b4`.
These are GitHub's temporary PR merge commits, not merges into main.
Checkout logs prove the actual tested identities; run metadata separately
identifies source heads. Runtime was Ubuntu 26.04 / CPython 3.11.17.

- PR 44: https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/41060138183
- PR 45: https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/41060143806

Both runs passed checkout, dependency installation, repository safety,
disposable SQLite migration verification and managed PostgreSQL migration
inventory. Both failed `python -m pytest -q` with exit code 1.

## Failures retained without weakening checks

Both PRs failed:

1. `tests/test_audit_integrity_repairs.py::test_strict_full_replay_and_exact_current_custody`
2. `tests/test_week7_acceptance_research.py::test_original_verifier_defect_is_reproduced_without_editing_any_evidence`
3. `tests/test_week7_postgame_audit.py::test_full_replay_and_protected_inputs`
4. `tests/test_week8_postgame_audit.py::test_full_104_grades_read_only_replay`
5. `tests/test_week8_postgame_audit.py::test_numerical_research_replays_and_prior_folds_exclude_test_week`

The first three report `diagnostics replay mismatch`; the fourth reports
`manifest checksum coverage or audit status contradiction`; the fifth reports
`numerical research replay mismatch`. PR 45 additionally failed
`tests/test_week9_context.py::test_all_54_contexts_replay_without_model_adjustment`
with `context replay mismatch`.

The exact field/byte causes have not been established. Runtime and platform
differ from the earlier successful Windows / Python 3.12.14 runs; that is an
investigation lead, not a proven explanation or grounds for waiving failures.
No test, expectation, runtime, tolerance, checksum or sealed artifact was changed.
No rerun was requested after failure. The instruction to stop on unexpected
behavior was applied to further CI actions and source pushes.

## Configuration and custody

Workflow IDs 327189312, 327189314, 339530568, 337926765, 341565576 and
327189316 are `disabled_manually`. CI 328094886 remains active. Repository
Actions is enabled. Token defaults remain `read`; automated pull-request
review approval remains false. SHA-pinning configuration is unchanged.
No secrets, variables, environments, production controls, repository rulesets
or branch protection were changed. No operational workflow run was observed.

125 protected files were rehashed against the prior inventory and all match.
The source database remains
`09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.
The existing Week 9 54 ATS / 54 totals seal and v2.8 remain unchanged.
Missing historical CLV remains INCOMPLETE and is not the cause of these CI
failures. Raw PDF and extracted-text evidence remains unchanged; PR 46's
separate reading copies do not suppress the original whitespace findings.

## Completion record and remaining gates

Objective: activate only existing CI, capture exact independent results, and
preserve all other controls. Files added are this report and
`outputs/2026-ci-merge-gates/20261030-authorized-activation/`: activation helper,
timestamped API receipts, compressed job logs, log custody and preservation
records. The full file inventory is recorded separately in that directory.
There are no schema, application, model, policy or test changes.

Executed commands for activation were the local Python executable plus
`outputs/2026-ci-merge-gates/20261030-authorized-activation/activate_ci.py`
with `preflight`, `disable`, `enable`, `trigger`, and `status` phases.
The CI workflow executed exactly:

```text
python -m pip install --requirement requirements-dev.txt
python scripts/verify_repo_safety.py
python -m scripts.verify_migrations
python -m scripts.verify_cloud_migrations
python -m pytest -q
```

No new local full-suite success is claimed. Earlier 769/809-pass results
remain valid only for their recorded Windows runs. Friday context checks are
separately recorded in the Week 9 worktree and do not cure these CI failures.
New source evidence is retained locally after the stop condition; pushing it
would trigger another CI run. PR descriptions receive the failure notice
without changing head commits or requesting new CI.

**HOLD PRs 44, 45 and 46.** Required next gates are a documented explanation
and integrity-preserving repair of all failures, successful independent CI
on the resulting exact integration trees, and an independent non-author
APPROVED review. No reviewer is designated; COMMENTED is not APPROVED.
PR 46 has no independent CI run and inherits failing dependencies.

Dependency order remains PR 41 (contains repaired 35–40), then 42, then
43 and 44 (siblings; either order after 42), then 45, then 46. No defective
dependency should merge on the strength of an old local test result.

Risk: cross-runtime deterministic replay remains unproven. Main has no
branch protection/rulesets, so these owner-required gates must still be
observed explicitly. Rollback is to disable repository Actions if required;
do not restore the six operational workflows without separate authorization.
For additive documentation, revert only its new commit, preserving original
evidence. No unrelated tracked files changed; no PR was approved or merged.
