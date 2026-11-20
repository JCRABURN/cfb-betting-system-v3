# PR56 integration after PR55

1. **Objective.** Update the existing Week12 branch with approved main
   `217600fe1445edc7c0f2a51c04246e5ba38ea0cb`, preserving the independent
   Week11/season audit and Week12 prospective record. Original Week12 parent:
   `880d3f9f7b87313aebb2425efafe5318525eb53e`.
2. **Files changed.** Merge both existing histories; combine `.gitattributes`
   and `.github/workflows/ci.yml`; add the integration inventory verifier,
   six corruption/scope tests, and this integration verification directory.
   Friday adds dated research receipts, a reusable evidence-only comparison
   builder and five tests without changing any earlier artifact.
   The merge was clean: no evidence or model conflict required editing.
3. **Schema.** None. The existing SQLite and PostgreSQL migration checks run
   against disposable copies/inventories; no protected database mutation.
4. **Behavior.** CI checks out the exact PR head SHA and retains every gate
   from both parents. Additional gates verify inherited immutable evidence,
   Week7 indexed custody, Thursday's unchanged full card and fresh context
   provenance. No model, probability, confidence, rank or chip changes.
5. **Tests.** Six new cases reject changed/missing inherited records, permit
   additive evidence, and constrain the new inventory gate to historical
   evidence rather than unrelated application development. Existing audit
   and model seal verifiers still enforce their code/configuration hashes.
   No pre-existing test or validation threshold was weakened.
6. **Exact commands and provenance.** `20261119-v1/local-validation.json`
   and `20261120-v2/local-validation.json` record all 28 local validation
   commands, timestamps, return codes and output hashes. They cover the full
   suite, every executable gate in combined
   CI, all four Week9 owner-review records and the Week10 owner-review record.
   Final inventory/test scope is separately verified in the final-checks
   receipt. GitHub tests the final committed tree on Linux and Windows with
   Python 3.11 and 3.12; its exact run and results are recorded on PR56.
7. **Results.** The complete local suite passed 1,251 tests with 40 warnings
   (39 existing deprecations plus an unavailable pytest cache). All 28
   commands passed after correcting the local runner's erroneous path rewrite
   for a read-only context check. The rejected command and receipt remain in
   v1; the corrected command and remaining gates are in v2. This was an
   invocation error, not an evidence mismatch, and no guard was bypassed.
   The final Friday focused/replay results and exact code hashes are recorded
   in `../2026-week12-refresh/20261120-morning/validation.json`.
   Earlier delivery CI does not certify this integrated head. Preliminary
   inventory verification compared all inherited files except the two merged
   integration configuration files. The final ongoing gate protects 5,741
   evidence files from main and 7,798 from the Week12 parent, without freezing
   unrelated application code. Full-suite and final scope checks are reported
   separately rather than treating overlapping test counts as additive.
8. **Data quality and reproducibility.** Original PDF, all locked lines,
   forecast rows, timestamps, 1,210-file initial seal and Thursday revisions
   are preserved. The Week11 audit remains a closed historical input inventory;
   Week12 additions cannot enter it. Its 57 files/128 forecasts and the
   44-sheet workbook replay independently. No source or result is regenerated
   to conceal a mismatch. Both parent histories remain reachable.
9. **Limitations.** Week12 has no approved common calibrated ATS/totals
   probability scale. The five Unders remain provisional legacy research;
   chips are scoring allocations. Three Tuesday games retain no forecasts;
   two Wednesday games retain late seal custody. Existing audit limitations,
   missing final personnel reports and unconfirmed starters remain explicit.
10. **Risks.** Successful engineering validation does not establish betting
    profitability, calibrated confidence or causal support for contextual
    adjustments. v2.9 remains research only. External-model Week11 submissions
    remain excluded from v3 historical performance and model training.
11. **Rollback.** Before reviewer merge, close PR56 or restore its prior
    branch head with reviewer coordination while retaining these receipts.
    After review/merge, use a reviewed revert scoped to integration changes;
    do not remove PR55 evidence or overwrite frozen Week12 records. No database
    rollback is required. Codex does not self-merge.
12. **Scope and continuation.** No original production repository, unrelated
    NFL work, approved v2.8 implementation or policy was changed. Scratch DBs
    and PDF previews remain untracked. The existing 08:00 America/Chicago
   refresh heartbeat is ACTIVE. Thursday and Friday are complete; Saturday
   remains scheduled, with pause after November21 morning. Continue
    append-only dated receipts for unstarted games and preserve all earlier
    revisions; update PR metadata without rewriting inherited evidence files.
