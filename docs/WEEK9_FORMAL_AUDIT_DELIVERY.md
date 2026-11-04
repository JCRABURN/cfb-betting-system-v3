# Week 9 audit delivery and exact verification provenance

The formal audit reconciles 54 eligible finals from separately captured ESPN and
CFBD responses and grades all 54 ATS and 54 totals selections. All preliminary
scores and grades agree; no historical correction is needed. The independent
audit is a separate version, not an overwrite of preliminary evidence.

| Cohort | W-L-P | Hypothetical -110 units |
|---|---:|---:|
| Week 9 ATS, all 54 | 28-26-0 | -0.545455 |
| Week 9 totals, all 54 | 29-25-0 | +1.363636 |
| Governed ATS Top 5 | 3-2-0 | +0.727273 |
| ATS research Top 5 | 3-2-0 | +0.727273 |
| Totals research / original mixed Top 5 | 3-2-0 | +0.727273 |
| Latest human five, approval PENDING | 4-1-0 | +2.636364 |

Overlapping cohorts must not be summed. The October 29 pre-kickoff replacement
of FAU–North Texas Under with SMU–Syracuse Under improved the recorded five by
one win (+1.909091 units); n=1 substitution is not evidence of repeatable human
skill. All earlier review versions remain available.

Week 9 ATS MAE/RMSE/bias: **13.120028 / 15.927294 / +1.840030**.
Totals: **12.108100 / 15.348078 / +1.514258**. Bias is actual minus forecast.
Totals MAE improved versus Week 8 but remains worse than the locked-total
baseline (11.259259). Weeks 5–9 cumulative returns remain negative: ATS -7.909091
and totals -9.818182 units across 279 selections per market. All numerical
improvement proposals remain RESEARCH ONLY; no forecast, selection or policy
is changed.

## Implementation source and actual tested integration tree

- Source: `f7fbfed28f55e556d9a9fc738205937c962f826f`.
- GitHub tested merge: `c19b209aaa75895d2ca63032068d399afeebfab0`.
- Both have tree `6c90f9241fcdb4b6873a471b8503d06d6c51c25b`.
- Merge parents: main `abb4eb26bd1140e66972d2f1143cd587e80960b4`
  and source `f7fbfed28f55e556d9a9fc738205937c962f826f`.
- [Successful implementation CI](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/41859414614).

Each checkout log explicitly records the tested merge SHA. These are actual
runs, not an inference from an earlier commit or a corrected disposable copy.
This document and receipts are a later evidence-delivery change; they do not
retroactively make the earlier test a test of that later commit. The delivery
head receives its own existing GitHub CI run, identified in PR #48's final body
and checks. No claim of final-head success is made before that run completes.

| Environment | Pytest result | Pytest duration |
|---|---|---:|
| Native Windows / Python 3.12.14 | 885 passed, 39 warnings | 408.22 s |
| GitHub Ubuntu / Python 3.11.17 | 885 passed | 271.13 s |
| GitHub Ubuntu / Python 3.12.14 | 885 passed, 39 warnings | 473.04 s |
| GitHub Windows / Python 3.11.9 | 885 passed | 806.11 s |
| GitHub Windows / Python 3.12.10 | 885 passed, 39 warnings | 964.19 s |

Native wrapper elapsed time for pytest is **408.807 seconds**; the pytest
duration is **408.22 seconds**. They measure different intervals of the same
run, and neither replaces the earlier focused 35-test run. The 39 warnings are
existing Python 3.12 datetime deprecations, not hidden test failures.

All existing CI safety, migration, full-suite, historical/prospective replay and
new Week 9 formal replay gates passed in all four environments. The 23 historical
exact-output identities match across the downloaded compatibility artifacts.
The new gate and full-suite test verify all 21 formal audit files byte-for-byte
against the same committed artifacts on all four platforms. Protected inputs,
graded outcomes, cohorts, confidence, ranks and substantive numbers therefore
agree without widening any numerical tolerance.

## Exact native commands and additional checks

The archived receipt records the absolute interpreter, command arguments,
timestamps, return codes, durations, HEAD before/after and source tree.

```powershell
python -X utf8 -m pytest -q
python -X utf8 scripts/verify_repo_safety.py
python -X utf8 -m scripts.verify_migrations
python -X utf8 -m scripts.verify_cloud_migrations
python -X utf8 -m scripts.verify_replay_compat --output outputs/2026-week9-postgame-verification/20261104T153427Z-native/compatibility.json
python -X utf8 -m scripts.build_week9_formal_audit --verify
python -X utf8 -m scripts.seal_week8_board --verify
python -X utf8 -m scripts.week8_scoring_sequence_review --verify
python -X utf8 -m scripts.pdf_evidence_review
python -X utf8 -m scripts.seal_week9_board --verify
git diff --check 190c8949edcf8da806908b567d4daa59b605f1cd c19b209aaa75895d2ca63032068d399afeebfab0
git diff --check abb4eb26bd1140e66972d2f1143cd587e80960b4 c19b209aaa75895d2ca63032068d399afeebfab0
```

All Python commands returned 0. The new audit delta's whitespace check returned
0. The complete inherited integration diff returned **2**, with **6,421 known
trailing-whitespace findings** in five unchanged files: 4,589 FAU PDF-extracted
text lines, 1,397 JMU lines, 433 UNT lines, one Week 7 context line and one
protected Week 8 audit-code line. Exact baseline/current Git blob identities are
recorded in `whitespace-adjudication.json`. This is not reported as a clean full
whitespace check. Separate PDF reading copies replay successfully; original
source bytes and protected code are preserved, and no validation suppression is
introduced.

The one optional advanced-stats 404 was retained and superseded by the successful
documented endpoint capture; it was never treated as score evidence. A GitHub
status request was temporarily not executed because automatic approval review
hit a usage limit; the authorized read-only request succeeded after continuation.
Neither event is concealed as a passed check. There are zero failing tests or
unexplained integrity-gate failures in the recorded implementation runs.

## Custody, changes and merge recommendation

The pinned inventory checks **2,729 files**, including the **125 original
protected artifacts**, all original Week 9 sealed inputs/reviews and the new
source captures. SQLite integrity is `ok`, foreign-key violations are zero, row
counts are recorded and its original hash is unchanged. Original Week 8 evidence
and Week 9 seals pass. CLV remains INCOMPLETE for all 108 picks despite 312
pregame market observations: no qualified closing timestamp exists. No owner
approval artifact is invented.

Implementation change scope is the eight new capture/audit modules, one new
35-case test module, the custody fixture, 21 audit outputs, timestamped source
captures, documentation, byte-preserving attributes and one added read-only
step in the existing CI workflow. The final delivery adds only verification
receipts and documentation. No schema, database, v2.8 policy, source line,
historical score/forecast, model output or unrelated application file changes.
Full file inventories and hashes are in the manifests and PR diff.

Exact current dependencies are ancestors of the source and tested merge:

| Order | PR | Head |
|---:|---|---|
| 1 | #44 | `c3513d47d43ba3753496e0bca50a109b7836358a` |
| 2 | #45 | `a664aa6347307d4d5c7ef14634a37df7fc8c8a31` |
| 3 | #46 | `c63b2f7beadfd01ec2ece3a1af0052d8f5915cd3` |
| 4 | #47 | `0d9a4b56bd49e3fbef4326aa7a5bd6eec9d13e29` |
| 5 | #48 | Week 9 formal audit and later evidence delivery |

**HOLD for independent review and governed dependency integration.** No reviewer
is designated and PRs #46–#48 have no reviews. Existing COMMENTED reviews on
#44/#45 are not APPROVED. All five PRs remain draft/open and unmerged. The
six operational workflows remain disabled; only Pull Request Tests is active,
with read token permissions and review approval permission disabled.

Missing historical CLV alone is not an unrelated code-merge blocker. New research
is not a profitability or calibration certification. Future policy adoption
requires predeclared walk-forward validation, explicit owner approval and a new
version; this work performs none of those promotions.

Rollback: abandon/revert only the additive implementation while retaining raw
captures, receipts and historical versions for custody. No migration recovery is
needed. No unrelated files or original production repository were modified.
