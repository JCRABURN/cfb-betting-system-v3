# Verification and integration status

Research input/code source: `46fe7652baafc9c61f6c7234e6d1d6661fbe257f`.
Prospective evidence delivery: `15b84e40e70a6c9876b9888659db32ee7b5fe641`.
Original main base: `abb4eb26bd1140e66972d2f1143cd587e80960b4`.
Audit source: `950df28202ee01c3cb1a11777170cdba628a0cfe`.
Week 10 source: `5823b6dd2d0321fd91ad1a8ce474b192fd21c9c1`.

Initial native Windows Python 3.12.14 research check: `python -m pytest
tests/test_confidence_research.py -q`, 23 passed in 43.22 seconds on the then
uncommitted test/verification additions to `15b84e4`. This does not claim those
tests existed in that commit. Subsequent full-tree receipts supersede its coverage.

Initial [GitHub run 42135915549](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/42135915549)
at source `15b84e40e70a6c9876b9888659db32ee7b5fe641`: Ubuntu/Python 3.11.18,
632 passed, 2 failed in 112.83 seconds. This was before the new research tests
were committed. Repository safety and both migration checks passed.

Both failures are original Week 5 custody assertions:

- `tests/test_week5_postgame_audit.py::test_audit_is_complete_and_never_rewrites_frozen_week5_inputs`
- `tests/test_week5_review.py::test_v4_hash_custody_and_locked_snapshot_unchanged`

First differing file is
`outputs/2026-week5-execution-20260930-v4/prior-evidence/week1-postgame-audit.csv`.
The historical expected SHA256 is
`b9248fd7db2ba2cde5ba3674f61683522d9a6f885811441846368f82092dcf20`.
The existing main Git blob (Linux LF checkout) is
`0b7da8cd62a9b878e6da6398c0f786e023993a47fc4b4176fc86eb3d02f03759`.
An in-memory CRLF rendering matches the expected SHA exactly. Twenty-five of
the 91 manifest entries have this same original checkout-representation issue;
all 91 match in the current Windows checkout. No historical file or expected
hash was changed to conceal it. The research input pack preserves exact source
Git blobs and documents their identities separately from checkout custody.

The narrow research branch deliberately does not import cumulative dependency
repairs. Existing PR #48's repair/integration must pass its own review and gates;
then this branch must be integrated and retested against that accepted main tree.
No existing test is skipped, weakened or suppressed, and no duplicate CI or
operational workflow is introduced.

Full native Windows/Python 3.12.14 at
`ccab2f5ad2f3258b3c66c47a13e3f81ec6fd9a6f`: **659 passed, 1 failed, 39 warnings
in 179.87 seconds**. All 26 research tests pass. Holdout/source/cohort checks,
supplement/table replay, repository safety and both migration checks pass.
The full receipt and logs are in `verification/20261106-v1/`.

The Windows failure reaches a different original Week 5 custody assertion:
`outputs/2026-week5-review-20261001/provider-evidence/odds-draftkings-current.json`.
Its original expected/main Git-blob SHA is
`208588eeaf00646b62bbb67e579e7cbcbb4c2d25aabf13e035ff2c5133a4a9c1`,
but Windows CRLF checkout SHA is
`92d16a4ea9b4b1766c3f453541baff5a6455f0ad07976d277a2708e6656a9e43`.
An in-memory LF rendering matches the original expected SHA; the source file
was not changed. `verification/windows-base-custody-differences.json` records it.

[GitHub run 42137106385](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/42137106385)
tests source `ccab2f5ad2f3258b3c66c47a13e3f81ec6fd9a6f`, merge tree
`832f90deb494fa7c15d501bf2a2d29841e29315c`, into main
`abb4eb26bd1140e66972d2f1143cd587e80960b4`. Ubuntu/Python 3.11.18:
**658 passed, 2 failed in 169.59 seconds**, including all 26 research tests
passing and only the two original Week 5 failures identified above. Original
research input hashes, canonical numerical replay and sealed prospective rows
therefore agree between these Windows and Linux executions. Safety and migration
gates pass. This is not an all-green CI result.

The source database is `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`
before and after the full native run; read-only SQLite integrity is `ok`.
The original Week 10 initial seal in the separate execution worktree is still
`7868e32c4de6f2154d1f8edfdce01042abf3f7933bb11d3a5509c58f448f9dbd`.
There are no changes under application, database, historical outputs, config,
or workflow paths relative to the base. `verification/changed-files-at-ccab2f5.txt`
enumerates that tested tree's complete diff.

The next delivery removes one extra blank line from generated `TABLES.md`
through its renderer, adds evidence, and makes the verification receipt command
return nonzero when any recorded gate fails (its original JSON correctly recorded
FAIL but its process exit was zero). A new adversarial test covers that receipt
behavior. These changes do not modify any estimator, protocol, numerical result,
original byte seal or prospective shadow. Subsequent CI identifies its own exact
tested head; the runs above must not be relabeled as tests of later commits.

Independent approval remains absent; no reviewer has been designated. CI is
not independent PR approval. **HOLD**: no merge, model promotion, owner selection
approval or operational activation is authorized by this research result.
