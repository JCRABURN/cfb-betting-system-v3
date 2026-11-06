# CI and independent merge gate reconciliation

Objective: diagnose missing independent CI on #44/#45, verify their exact
dependency trees, preserve sealed evidence, and provide separately readable
PDF extracts. Owner approval of the Week 9 selections remains PENDING.

## Proven root cause and scope of evidence

Authenticated GitHub REST at 2026-10-29T21:38:50Z returned HTTP 200 and
`enabled: false` from the repository Actions-permissions endpoint. This is the
specific current execution blocker. Workflow 328094886 (`ci.yml`, Pull Request
Tests) is active and already exists on main. The repository-wide runs endpoint
returned total_count 0. Recorded PR-open events for #44 and #45 occurred on
October 28 at 13:44:10Z and 13:48:04Z. Both target main and are mergeable.

The workflow has no path filter, no draft-PR exclusion and no skip directive;
its existing pull_request event includes opened/synchronize/reopened. Default
token permissions are read-only and automated approval is disabled. No duplicate
workflow, workflow_dispatch trigger or broader token permission is necessary.
These API snapshots establish the current block, but do not establish who
disabled Actions or when. Repository event history is not a settings audit log.

Main is not protected (authenticated protection endpoint: HTTP 404, Branch not
protected), and the repository ruleset list is empty. No required GitHub status
checks were removed or weakened. The owner's CI and independent-review gates
still apply. Only JCRABURN is listed as a collaborator; that same account authored
both PRs. #44 has one COMMENTED review and #45 has two; neither has APPROVED
independent review. No review request is fabricated and no owner approval is cast.

The connector does not expose some administrative endpoints and its protection
request returned integration-scoped 403. The ordinary existing Git Credential
Manager authentication succeeded for the authorized read-only REST inspection.
No credential values were printed, saved, added or rotated.

The minimal activation procedure is in CI_ACTIVATION_PROPOSAL.md. It requires
explicit permission because the owner prohibited unapproved security-setting
changes. Six non-CI workflows must first be disabled so enabling repository
Actions does not activate production scheduling. Until approval, repository and
workflow settings remain untouched and no GitHub CI success or run URL exists.

## Exact-head verification in the current environment

| PR | Tested commit | Complete suite | Read-only checks |
|---|---|---|---|
| #44 | 922f1f8f8c66ef14674eb9aa20db144a45dada68 | 769 passed, 39 warnings, 195.39s | Eight passed |
| #45 | 6e1948dd9b675a3f1226350ce5b40a6556e09f7a | 809 passed, 39 warnings, 210.81s | Eleven passed |

Both new runs record HEAD before and after, empty tracked diffs, command, cwd,
start/end UTC, exit 0 and log SHA256. They are local Windows runs, not GitHub
Linux CI. They do not replace or relabel the earlier 203.82/240.94/193.64-second
runs. The #44 run started 21:42:14Z and completed 21:45:31Z; #45 started
21:42:03Z and completed 21:45:37Z. Results for this later repair branch must be
recorded separately and not attributed to either existing PR head.

Commands used the repository .venv/Scripts/python.exe:

```text
python -m pytest -q
python scripts/verify_repo_safety.py
python -m scripts.verify_migrations
python -m scripts.verify_cloud_migrations
python -m scripts.verify_week7_audit_integrity
python -m scripts.seal_week8_board --verify
python -m scripts.build_week8_postgame_audit --verify
python -m scripts.week8_scoring_sequence_review --verify
python -m scripts.week8_numerical_research --verify
```

The following additional commands passed on #45:

```text
python -m scripts.seal_week9_board --verify
python -m scripts.review_week9_context --capture outputs/2026-week9-context/20261029T1147Z-thursday-gate --verify
python -m scripts.verify_week9_owner_review outputs/2026-week9-owner-review/20261029-morning-decision/owner_review_shortlist.json
```

The eight #44 checks cover repository safety, disposable-copy SQLite migration,
managed migration inventory, repaired Week 7 custody, Week 8 seal, all 104 grades,
scoring sequences and numerical research replay. #45 adds the Week 9 seal and
separate context/owner-review replay. All 125 files across the Week 8 audit and
research, Week 9 prospective card, and all saved owner reviews matched #45 Git
blobs byte-for-byte. This is broader than the earlier 118-file inventory; it
includes later saved review versions. Source DB SHA256 is still
09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842.
The Week 9 seal remains
77aea6d0eefecc6dce014524610294da617d7dab2b6e903a59f8664f664e5460.
No post-kickoff full-card regeneration or historical line replacement occurred.

## Dependency order

PR #41 (78ed6eb5540f66ba3193f91366c802e27e3cb9c7) contains the #35–#40 chain
and its repairs. Do not merge those unrepaired ancestors independently. Then
#42 (7f42da36f9aef4666bb715d49babde7ee374defa) supplies the sealed Week 8 board.
After #42 there are two branches: #43 (43807ae374b9db143c1d9675d7a7cafe6e2f28ba)
supplies Week 9 screenshot ingestion; #44 supplies the Week 8 audit.
#43 is not an ancestor of #44, and #44 is not an ancestor of #43.
#45 contains both. Merge order, only after all gates pass, is repaired #41,
then #42, then #43 and #44 in either order, then #45, then this additive repair.
Recheck merge-tree identities and CI if an earlier merge changes a PR base.

## Whitespace findings without evidence rewriting

The entire main-to-#45 diff has 6,421 native Git whitespace findings:
4,589 in FAU, 1,397 in JMU and 433 in UNT plain PDF extracts, one in a historical
Week 7 monitoring note, and one in scripts/build_week8_postgame_audit.py.
The latter script is itself pinned by the Week 8 audit manifest. Trimming it
would fail the original audit code checksum; no expected checksum was changed.

Three new reading copies remove only ASCII trailing spaces/tabs, normalize LF
and keep one final newline. Original PDFs and text extracts remain byte-for-byte
intact. The separate manifest pins both original PDF and extract SHA256 values,
records each derivative hash and identifies the copies as non-source views.
The read-only verifier requires exact output inventory and deterministic bytes;
the writer refuses an existing directory, including partial output.

Executed:

```text
python -m scripts.pdf_evidence_review --create
python -m scripts.pdf_evidence_review
python -m pytest tests/test_pdf_evidence_review.py -q
git diff --check origin/main HEAD
```

The nine focused tests passed in 1.25s before commit. They reject altered PDFs,
altered extracts, forged/missing/extra reading copies or manifests, and attempted
overwrite. No old test was changed. Native full-diff check remains exit 2 with
the documented immutable findings; it is not reported as passing. The new
investigation directory gets the same byte-preserving -text/cr-at-eol attributes
as existing custody directories. Trailing spaces/tabs remain checked; no path
exclusion, CI-validator change or broad whitespace suppression was added.
Unrelated failures remain visible. The compressed original checker output is
retained with the evidence. Clean views resolve readability; they do not erase
the historical formatting findings or substitute for original custody evidence.

## Recommendation, changes and rollback

**HOLD #44. HOLD #45.** Exact-head local tests and sealed-data replay pass, but
repository Actions remains disabled, no independent GitHub CI has run, and
no independent approving reviewer is available. The original raw whitespace
findings remain explicitly documented for review. No PR has been merged or
approved. Missing historical CLV remains INCOMPLETE and is not the cause of the
CI hold or a reason to reject unrelated audit arithmetic.

Latest Thursday five remains Northwestern +3.5 (2), Navy +30.5 (2), Southern
Miss–ULM Under 56.5 (2), SMU–Syracuse Under 58.5 (1), Troy +20.5 (1).
FAU–North Texas Under 77.5 remains alternative six. Human values are uncalibrated;
all frozen values, earlier versions, v2.8 and original mixed research five remain
unchanged. The interrupted afternoon capture stays separately preserved in the
week9-execution worktree and has not been promoted into a new owner review.

Files added: this report, activation proposal, nine-test verification module,
separate reading-copy script and four generated reading-copy files, plus API,
ancestry, hash and local-run evidence under outputs/2026-ci-merge-gates. The only
existing file changed is .gitattributes, for the new evidence directory. No schema,
dependency, model, weekly policy or existing application-code changes. No migration
mutation of data/cfb.db; the migration checks use disposable copies.
No unrelated files or original repository changes. The root NFL work is untouched.
Rollback is to leave this additive branch unmerged; remove or revert only its
additions if later necessary while retaining the evidence in Git history.
No database recovery is needed. Configuration rollback, if later authorized,
is specified separately in the activation proposal.
