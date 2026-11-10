# Week 10 model execution and pending integration

The unchanged models generated **57 ATS and 57 totals selections** from the
original screenshot lines. All 62 source games reconcile; the two Tuesday finals
and three elapsed Wednesday games are excluded. No historical or already-started
game receives a prospective prediction. There are no missing totals or model
skips. Source DB integrity and foreign-key checks pass and its SHA-256 is unchanged.

Actual model/card source commit: `8afc2a3817fa811fdfe159c20b4b62cc6e8839e0`.
Seal SHA-256: `7868e32c4de6f2154d1f8edfdce01042abf3f7933bb11d3a5509c58f448f9dbd`.
The read-only acceptance wrapper separately pins this original seal and the three
original PR49 source files. The five execution/sealing adapters and original
generated outputs are preserved after sealing. Later verification additions do
not retroactively change the recorded model-code commit.

| Combined research rank | Selection | Frozen forecast | Existing confidence |
|---:|---|---:|---:|
| 1 | UTSA–Florida Atlantic Under 73.5 | 56.62204343751911 | 5 |
| 2 | Texas State–Oregon State Under 72.5 | 56.22188309796162 | 5 |
| 3 | West Virginia–Texas Tech Under 65.5 | 51.58358941361724 | 4 |
| 4 | Air Force–Army Over 45.5 | 57.694350798599 | 4 |
| 5 | James Madison–Southern Miss Under 58.5 | 47.41560149964227 | 4 |

These are **uncalibrated research scores and labels**, not validated probabilities,
owner approval, final contextual recommendations or sportsbook recommendations.
All ATS confidence values remain 1 under the unchanged governed policy. Separate
governed ATS, ATS research, totals research, full boards, Top10 and review candidate
tables are retained under `outputs/2026-week10-prospective/`. QB/personnel/weather
review is explicitly pending; no unsupported numeric adjustment was applied.
CLV remains INCOMPLETE.

Inputs are cumulative statistics strictly through Week9, plus preserved earlier
snapshots for training. The current Week10 capture may include elapsed games for
coverage accounting, but no Week10 result enters model training or target data.
All source, model, card and seal timestamps precede the first eligible kickoff,
November 6 at 00:30 UTC. Source chat receipt, later screenshot recovery and unknown
market quote time remain separate custody fields.

Commands executed successfully on the model source above:

```powershell
python -X utf8 -m scripts.run_week10_execution --source-lines production-weeks/2026-week10-splashsports.csv --source-metadata production-weeks/2026-week10-splashsports-lock-metadata.json --capture-dir outputs/2026-week10-prospective/core-initial --database data/week10-execution.db --output outputs/2026-week10-prospective
python -X utf8 -m scripts.finalize_week10_card --database data/week10-execution.db --output outputs/2026-week10-prospective --source-lines production-weeks/2026-week10-splashsports.csv
python -X utf8 -m scripts.seal_week10_board
```

Subsequent focused test command:
`python -X utf8 -m pytest -q tests/test_week10_continuity.py tests/test_week10_sealed_board.py`
passed **40 tests in 4.76s** on the uncommitted verification additions. This does
not substitute for full-suite or GitHub CI results on a later delivery commit.
Those exact results are retained separately in the PR completion record.

The existing CI workflow gains a read-only Week10 acceptance gate. PR49 currently
targets the PR47 branch, whereas CI triggers only for PRs into main; this explains
its absent workflow runs. The owner requires rebasing onto main after verified
integration of PR48, so that change and CI on the resulting integration are pending
genuine non-author approval and merge of PR48. No workflow/security workaround,
production activation, additional PR or fabricated approval is used.

One initial local preflight correctly stopped when original CRLF checkout bytes
differed from LF Git blobs. Explicit `text eol=crlf` rules for the three original
source files preserve both original Git identities and original receipt hashes;
none of their bytes or values were rewritten. The earlier readiness snapshot,
including its unresolved alias and unavailable-image status, remains preserved
and is superseded by the later source reconciliation and image custody evidence.

Only additive Week10 adapters, tests, evidence and documentation, scoped checkout/
ignore rules and the existing workflow gate changed. No schema, source database,
historical artifact, model, v2.8 policy, unrelated NFL file or original production
repository was modified. Rollback abandons the additive implementation while
retaining all captures and sealed versions; no database restoration is required.
