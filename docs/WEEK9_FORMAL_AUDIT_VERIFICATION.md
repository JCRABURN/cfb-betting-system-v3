# Week 9 formal audit implementation and verification

## Objective and scope

Complete the formal postgame audit on the PR #48 branch, retaining the five
preliminary On3 files as an explicitly non-authoritative baseline. The baseline
is `190c8949edcf8da806908b567d4daa59b605f1cd`; repaired dependency PR #47 is
`0d9a4b56bd49e3fbef4326aa7a5bd6eec9d13e29` and is already an ancestor.

The authoritative calculation report is
`outputs/2026-week9-postgame-audit/v1/WEEK9_FORMAL_AUDIT.md`.
Machine-readable output, including all 108 selections, cohorts, 54-game process
statistics, confidence diagnostics and Weeks 5–9 comparisons, is alongside it.

## Files and behavior

- `scripts/capture_week9_postgame.py`: explicit live capture of ESPN scoreboard,
  54 summaries and six CFBD endpoints. Every returned body is preserved with
  request/receipt times, endpoint parameters and raw/stored SHA-256 values.
- `scripts/capture_week9_advanced_supplement.py`: separate capture of the documented
  advanced endpoint. The original `/games/advanced` 404 body and failed status
  remain intact; the supplemental `/stats/game/advanced` request returned 230
  team-game records, including both sides of all 54 eligible matchups.
- `scripts/week9_audit_sources.py`: exact source coverage, final status,
  orientation and score reconciliation; pregame schedule checks.
- `scripts/week9_audit_grading.py`: independent decimal ATS/totals grading;
  frozen cohorts, validated scoring sequences and original human review custody.
- `scripts/week9_audit_diagnostics.py`: explicit stable sums, exact fractional
  -110 returns, canonical six-decimal statistical reporting, nonoverlapping rank
  segments, calibration, correlations and retrospective walk-forward proposals.
- `scripts/week9_audit_game_process.py`: actual volume, explosives, offensive and
  defensive efficiency, observed passers and non-offensive scoring evidence.
- `scripts/week9_audit_report.py`: report derived from those tables.
- `scripts/build_week9_formal_audit.py`: exclusive new-version writer and
  read-only exact-byte verifier; fixed input inventory and exact output coverage.
- `tests/test_week9_formal_audit.py`: 35 tests including adversarial cases.
- `tests/fixtures/week9_formal_audit/input-custody-v1.json`: separately pinned
  source inventory, including all 125 previously recorded protected artifacts.
- `.gitattributes`: byte-preserving checkout for the original preliminary and new
  formal evidence/audit directories and the new checksum fixture.
- `.github/workflows/ci.yml`: adds a read-only Week 9 audit gate to the existing
  four-environment Pull Request Tests matrix. No workflow duplication, production
  activation, permission change, required-check removal or test skip.
- `outputs/2026-week9-postgame-evidence/`: timestamped original and supplemental
  postgame captures; no pregame source replacements.
- `outputs/2026-week9-postgame-audit/v1/`: 21 deterministic audit outputs.

Schema changes: none. Database mutations: none. Model, rankings, contest lines,
confidence, owner approval and v2.8 policy changes: none. New proposals are
RESEARCH ONLY. No historical script protected by an existing manifest changed.

## Commands and results actually executed during development

Native environment: Windows, Python 3.12.14, repository `.venv`.

```powershell
python -X utf8 -m scripts.capture_week9_postgame
python -X utf8 -m scripts.capture_week9_advanced_supplement
python -X utf8 -m scripts.build_week9_formal_audit
python -X utf8 -m pytest -q tests/test_week9_formal_audit.py
```

The score capture completed all 56 essential requests. One optional wrong-path
advanced request returned 404; its body is preserved, not erased or treated as
success. The documented supplemental endpoint succeeded. All 54 scores match
both primary provider captures and the preliminary scoreboard; all 108 grades
and six-decimal preliminary forecast errors reconcile. All 54 scoring sequences
validate. The focused suite passed **35 tests in 5.13 seconds** on the uncommitted
implementation based on `190c8949...`; this is not a claim about a later commit.

Complete-suite, safety, dependency replay and GitHub CI receipts are recorded in
the separate final verification delivery record with their actual source/tested
merge identities. Until those receipts exist, their status is PENDING; do not
reinterpret the focused test result as a full-suite pass.

## Data quality and remaining limitations

The audit checks 54 unique frozen games per market, all 54 finals from both
providers, integer scores, IDs/orientation, completed status, exact pregame lines,
confidence 1–5, all research ranks 1–54, five-member cohorts and each original
human review. Original protected hashes match. Source SQLite integrity and
foreign-key checks are read-only; its original hash is
`09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.

CLV is INCOMPLETE: no qualified timestamped closing prices exist. Earlier
timestamped observations and postgame provider-labeled odds cannot fill that gap.
Historical missing CLV alone does not block unrelated integrity fixes. The two
score providers can share upstream data. Personnel participation is descriptive,
not medical clearance or causal injury attribution. All new subgroups/proposals
are retrospective exploration; Weeks 5–6 research ordering is retrospective even
though the underlying predictions were pregame. Confidence samples are small.

## Review, risks and rollback

Review the complete additive diff and require independent APPROVED review; no
reviewer has been designated. The PR author, a COMMENTED review and this agent's
self-review do not satisfy that requirement. No PR is merged by this work.

The material analytical risk is overstating a small-sample rebound or treating
research scores as probabilities. The report retains negative cumulative returns,
market-baseline errors, uncertainty and every prior review to prevent that.

Rollback is to abandon/revert the additive implementation and retain all raw
captures and prior versions for custody. No migration or database restoration is
needed. Unrelated NFL changes in the primary worktree are excluded. No file in the
original production repository is touched.
