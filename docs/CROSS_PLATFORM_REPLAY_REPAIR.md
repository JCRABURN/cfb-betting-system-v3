# Cross-platform replay repair and merge gates

The six failing tests are repaired without changing historical source files,
artifacts, expected hashes, contest lines, forecasts, results, approvals or v2.8.
PRs #44, #45 and #46 now pass their complete Linux and Windows CI matrices.
**HOLD all PRs for independent approval.** No independent reviewer has been
designated; the existing author COMMENTED reviews do not satisfy that requirement.

## Demonstrated root causes

The authoritative failures are runs [41060138183](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/41060138183)
and [41060143806](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/41060143806).
The subsequent diagnostic matrix and unchanged-head #46 reproduction retain
the failures separately, rather than overwriting their records.

| Failed test | Actual cause and affected values |
|---|---|
| `test_strict_full_replay_and_exact_current_custody` | Week 7: eight float leaves differ under Python 3.11 summation. |
| `test_original_verifier_defect_is_reproduced_without_editing_any_evidence` | Same Week 7 discrepancy prevented reaching the intended original-verifier defect assertion. |
| `test_full_replay_and_protected_inputs` | Same eight Week 7 float leaves; largest difference 3.552713678800501e-15. |
| `test_full_104_grades_read_only_replay` | Two Week 8 metric leaves and 346 cross-week metric leaves differ; their two manifest output hashes consequently differ. **No actual checksum coverage or audit status contradiction** was found: the shared error message obscured the arithmetic mismatch. |
| `test_numerical_research_replays_and_prior_folds_exclude_test_week` | Fourteen numerical-research float leaves differ under Python 3.11 summation. |
| `test_all_54_contexts_replay_without_model_adjustment` | 216 leaves: 54 games x two teams x timezone offset/status. Archived null/unavailable becomes a float/verified when a timezone database exists. |

The machine-readable [field comparison](../outputs/2026-cross-platform-replay/findings/root-causes-and-field-differences.json)
contains all 588 differing leaves: exact JSON paths, values, types, numeric hex,
ULPs, first differing file byte, hashes, impact category and causal mechanism.
It maps all six test failures to their artifacts. Largest native metric
difference across the diagnostics is 2.842170943040401e-14. No game grade,
cohort, forecast, confidence label, locked line or ranked selection changes.

Python 3.12 changed float `sum` to compensated accumulation, documented in
[Python's built-in functions](https://docs.python.org/3.12/library/functions.html#sum)
and the [CPython implementation](https://raw.githubusercontent.com/python/cpython/v3.12.0/Python/bltinmodule.c).
Replacing only the affected module's summation with explicit compensated
arithmetic eliminates the Week 7, Week 8 and numerical-research discrepancies
on Ubuntu 3.11. Native Ubuntu 3.12 reproduces every non-context output exactly.
Windows 3.11 independently exhibits the same arithmetic discrepancies.
The new verifier then reproduces every archived output byte on all four runtimes.
These interventions establish the cause, rather than attributing it to an
operating system without a control.

The original local Windows environment has neither TZPATH entries nor the
`tzdata` package. The historical context function catches ZoneInfoNotFoundError
and emits null with `UNAVAILABLE_LOCAL_TZDATA;SOURCE_ZONE_NAMES_RETAINED`.
Ubuntu resolves the retained source zone names through system TZPATH. Fresh
Windows CI also reproduces the mismatch: installation logs show `psycopg==3.3.4`
pulling `tzdata==2026.6`. Therefore timezone availability, not Windows versus
Linux itself, is the second undeclared runtime input. Recorded zone names and
kickoff timestamps are unchanged. No later timezone information is retroactively
inserted into an archived context record.

Iteration, CSV handling, serialization and other floating-point functions were
also checked: all native graded/cohort CSVs and text reports are byte-identical;
the logged `math.log(.7).hex()` probe agrees; sorted JSON and explicit LF CSV
serialization are retained. Restoring only summation and original timezone
availability yields exact bytes, including all metrics. No separate ordering,
CSV parser, JSON formatting or math-library defect remains in these artifacts.
Requirements files have different LF/CRLF byte hashes across checkouts, but
their Git blobs and dependency declarations were not modified.

## Repair boundary

`scripts/replay_compat_v1.py` verifies LF-qualified source hashes for six
historical scripts, then reuses their function code in isolated namespaces with
explicit CPython 3.12 finite-number summation. It does not alter original modules,
process builtins, import state or historical code. An explicit equivalent Week 8
serializer avoids a function-local import bypassing the isolated computation.
The hash checks here are additional checks; original byte-custody checks remain.

`scripts/replay_week9_compat.py` is a read-only verifier. Its pinned profile lists
the original capture-manifest and derived-board SHA256 for each of six archived
captures, together with the documented unavailable timezone provider. Unknown
captures, changed code/profile, changed bytes and generation requests fail
closed. The profile controls provenance only; it never substitutes expected
forecast or diagnostic values. Future context generation still uses the original
generator and is outside this historical verifier's scope.

`scripts/verify_replay_compat.py` verifies all Week 7/8 grading, research custody,
CSV/JSON/report bytes, Week 9 seal and each available archived context. Its report
contains computed and archived hashes. PR #44 predates Week 9, so its gate has
17 exact outputs; #45/#46 have 23, including all six contexts. This scope
difference is explicit, not a skipped failing test.

Five existing test files change only imports/call routing to this versioned
runtime; assertions and expectations remain. New tests reject altered code,
forecast, line, confidence, rank, result, missing checksum entries, contradictory
statuses, changed context bytes (even valid JSON whitespace), unsupported
timezone availability and unknown captures. Both material numeric changes and
a 1e-12 metric mutation are rejected. No tolerance or rounding is permitted.

The existing `ci.yml` retains its trigger, read-only token and all prior gates.
It adds a four-environment matrix, exact replay gate and archived diagnostic
artifacts. The timeout rises from 15 to 25 minutes for the additional replay.
There is no duplicate workflow, skip, disabled test or removed check.

## Successful CI on actual PR integration trees

All jobs ran the same unchanged requirements files. Ubuntu runners used 26.04;
the complete platform/package inventory is archived per job. Windows setup-python
provides 3.11.9 and 3.12.10; the initially attempted Windows 3.11.17/3.12.14
matrix entries failed setup and are **not** counted as successful runs. Their
always-run diagnostic used the runner's default 3.12.10; its actual version is
recorded. The repaired workflow guards diagnostics on successful Python setup.

| PR/run | Source head | Tested GitHub merge SHA | Tests per environment |
|---|---|---|---:|
| [#44 / 41102004369](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/41102004369) | `c3513d47d43ba3753496e0bca50a109b7836358a` | `8c755db43fb91ce52c4584eb0f31d4e3340dd2f7` | 791 |
| [#45 / 41102071702](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/41102071702) | `a664aa6347307d4d5c7ef14634a37df7fc8c8a31` | `f08d644659b83a024d8c3d4edcef738562550441` | 841 |
| [#46 / 41102087073](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/41102087073) | `c63b2f7beadfd01ec2ece3a1af0052d8f5915cd3` | `643cf009e851a554311d9833970f2df6adb04205` | 850 |
| [#47 implementation / 41101927943](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/41101927943) | `9f310e1a3a1fd0412ca71f695ba5abd3ca71b6f3` | `3b944cea830a76bd000e278518e47734ab6ac331` | 850 |

Each row has four successful suites: Ubuntu 3.11.17/3.12.14 and Windows
3.11.9/3.12.10. All safety, migration and exact replay steps passed. Python 3.12
reports 39 existing deprecation warnings; Python 3.11 reports none. Raw logs,
job steps and summaries are under `outputs/2026-cross-platform-replay/ci/`.
The [agreement table](../outputs/2026-cross-platform-replay/findings/cross-platform-agreement.json)
compares every computed output hash between all four jobs, including grades,
cohorts, metrics, rankings and context. Every comparison is exact.

The #47 implementation run predates two additional pregame captures already
present in #45; its gate correctly covered four contexts. The later merge of
#46 into #47 is `d2a2883f6acb33aea829e85ad4117baac1e85e87`, with a Git tree
identical to #46 and all six captures. A local full suite and gates are recorded
separately for that merge. Subsequent evidence delivery commits must never be
described as that local tested commit. The final #47 GitHub event is recorded
in the PR delivery status and must be green before considering merge.

## Preservation, scope and governance

The [protection inventory](../outputs/2026-cross-platform-replay/findings/protected-artifacts-and-ancestry.json)
rechecks all 125 protected files on #45/#46/#47. #44 has 70 applicable files;
the other 55 do not exist in its original tree. No historical data path is
modified or deleted relative to the original heads. The additive Thursday/Friday
captures already on #45 remain distinct. Source database SHA256 remains
`09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.
Week 9 seal remains
`77aea6d0eefecc6dce014524610294da617d7dab2b6e903a59f8664f664e5460`.
All original script blobs, approvals, lines, forecasts, scores and expected
hashes remain. No schema, dependency, model or weekly-policy change occurred.

The separately derived PDF reading copies still pass their checksum and
deterministic replay checks. Historical raw whitespace findings remain visible;
no sealed PDF or text bytes were trimmed and no validator was suppressed.
The new evidence directory uses byte-preserving attributes, like the existing
custody directories. New repair changes must pass their own diff whitespace check.

Only Pull Request Tests is active. The six authorized operational workflows
remain `disabled_manually`; default token permissions remain read and automated
review approval remains disabled. No security, secret or production setting was
changed during this repair. PR #46 received an authorized reopened event at its
unchanged original head (run 41071724168, 812 passed/six failed), followed by
the successful repaired integration event above; no empty trigger commit was used.

The logical dependency order is #41 (which contains #35-#40), #42, then #43
and #44, then #45, #46 and #47. This is not approval to merge older standalone
heads: the successful CI cited here covers the cumulative repaired #44/#45
trees, not separate #41/#42/#43 heads. Prefer reviewing and integrating the
tested cumulative #44 tree (which already contains #41/#42), then #45 (which
also contains #43), then #46 and #47. If separate earlier PR merges are desired,
first apply the applicable compatibility repair and obtain their own passing
CI and independent approval. The common
compatibility changes were cherry-picked into #44 so its actual tree passes;
#45 merged that exact #44 head, #46 merged #45, and #47 merged #46. Do not
merge the unrepaired ancestors independently. Recheck generated merge SHA and
CI after any earlier merge changes a later PR's base.

**#44 HOLD; #45 HOLD; #46 HOLD; #47 HOLD.** Technical replay and CI gates pass
on the cited trees; independent approval is still missing. Historical CLV remains
INCOMPLETE and is not a blocker for this repair. Contest owner approval remains
PENDING and is not being inferred from CI. The Week 9 automation was paused on
November 2 without collecting postgame data or changing selections.

Risks/limits: the compatibility contract supports the pinned historical code and
finite numeric inputs, not arbitrary future models; future captures require
explicit new provenance rather than silent enrollment. CI runner images and
unlocked transitive package availability can change, but the recorded environment
and fail-closed byte checks expose that change. No new predictive validity,
calibration, profitability or CLV claim follows from deterministic replay.

Rollback: leave the repair unmerged, or revert its compatibility entry points,
test routing and CI extension through a reviewed PR. Retain all archived failure
and success evidence in Git history. There is no database migration or artifact
rewrite to reverse. Do not restore operational workflows as part of rollback.
The unrelated root-worktree NFL changes and original repository were untouched.

## Changed files and exact verification commands

Implementation files are `.github/workflows/ci.yml`,
`scripts/diagnose_cross_platform_replay.py`, `scripts/replay_compat_v1.py`,
`scripts/replay_week9_compat.py`, `scripts/verify_replay_compat.py`,
`tests/fixtures/replay_compat/week9_context_profiles.json`,
`tests/test_replay_compat_v1.py`, `tests/test_replay_week9_compat.py`, and the
five import-routing changes in `tests/test_audit_integrity_repairs.py`,
`tests/test_week7_acceptance_research.py`, `tests/test_week7_postgame_audit.py`,
`tests/test_week8_postgame_audit.py`, `tests/test_week9_context.py`.
The delivery adds this document, one new-directory `.gitattributes` rule and
evidence under `outputs/2026-cross-platform-replay/`. There are no unrelated
implementation changes. The per-tree name-status lists are in the protection
inventory; inherited pregame evidence is distinguished from this repair.

Commands executed on the actual integrated repair worktree with its repository
`.venv/Scripts/python.exe -X utf8` (Python 3.12.14):

```text
python -m pytest -q
python scripts/verify_repo_safety.py
python -m scripts.verify_migrations
python -m scripts.verify_cloud_migrations
python -m scripts.verify_replay_compat --output outputs/2026-cross-platform-replay/local-windows312-final-integration/compatibility.json
python -m scripts.seal_week8_board --verify
python -m scripts.week8_scoring_sequence_review --verify
python -m scripts.pdf_evidence_review
python -m scripts.verify_week9_owner_review outputs/2026-week9-owner-review/20261030-friday-morning/owner_review_shortlist.json
git diff --check origin/main HEAD
```

Local pytest on merge `d2a2883f6acb33aea829e85ad4117baac1e85e87` passed
**850 tests, 39 existing warnings in 457.95 seconds** (wrapper elapsed
459.532 seconds). These timings measure different intervals of the same run;
neither replaces any earlier run. The receipt records HEAD, UTC, interpreter,
commands and individual exit codes. The four extra gates pass, with the latest
owner-review verifier confirming ten candidates, five recommendations, unchanged
frozen values and PENDING approval. Full historical diff check returns **exit 2,
6,421 known findings**, retained in a compressed raw log and explicit inventory.
It is not counted as a clean whitespace check. The new-change check is separate.

All five local suite/safety/migration/replay commands returned exit 0. The local
exact-replay gate produced the same 23 output hashes as all four successful #46
CI jobs, including all six context captures. HEAD remained unchanged and the
tracked working tree remained clean throughout that local execution.

GitHub additionally runs the unchanged dependency installation and the native
diagnostic CLI shown in `ci.yml`. Native comparisons intentionally retain the
known platform differences; only the explicit exact-replay verifier is the
acceptance result. No historical failing native run is relabeled successful.

Two collection-only issues occurred: Windows rejected an overlong artifact
extraction path, resolved using shorter archive directories; a cross-worktree
Git read encountered the sandbox account's ownership guard, resolved with an
exact-path per-command safe-directory option, without changing global or repo
configuration. Neither altered a test, artifact or gate outcome. An earlier
automatic approval review hit a usage limit before executing an integration
command; its later ordinary retry completed after fresh state inspection.
