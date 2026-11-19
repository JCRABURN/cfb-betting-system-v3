# November 19 refresh verification

1. **Objective:** complete Thursday's upcoming-game evidence refresh against
   the original Week12 locked lines and preserve every prior forecast.
2. **Files:** two context capture/review wrappers; a deterministic Thursday
   comparison builder; eight new tests in `test_week12_context_refresh.py`;
   new dated readiness, context and refresh directories; delivery navigation
   documentation; exact captured-text whitespace attributes if needed. Raw
   source files are checksummed in their capture manifests.
3. **Schema:** none. No database mutation or migration.
4. **Behavior:** require each official schedule receipt within five minutes;
   use earliest source/provider kickoff; pin dated eligibility provenance;
   reject postkickoff conference evidence; retain old offline replay defaults.
   Updated evidence is separate from forecasts. No model rerun, adjusted
   projection, probability, confidence, rank, chip or selection change.
5. **Tests:** new tests cover stale/future/partially stale schedule receipts,
   earliest-source kickoff exclusion, incorrect schedule provenance,
   postkickoff conference evidence and complete Thursday artifact replay.
   Existing tests were not weakened or changed.
6. **Exact commands:** `validation.json` records all executable arguments,
   outputs, return codes, timestamp, base head and tested source hashes.
   Main command: `../../.venv/Scripts/python.exe -m pytest
   tests/test_week12_context_refresh.py tests/test_week12_source.py
   tests/test_week12_delivery.py -q`. It also records the original seal,
   custody-qualified delivery, fresh context replay, Thursday replay and
   repository safety checks. `week12_revision_ledger` executed with a current
   timestamp and returned zero changes; its receipt is `revision.json`.
7. **Current-environment results:** 41 focused tests passed. All five
   additional recorded verification commands returned zero. The original
   1,210 sealed files and approved model/policy hashes verify. Final staged
   byte and whitespace checks are recorded separately. The previous head's
   1,176-test CI result is historical and does not certify this new change.
8. **Data quality:** 66 original matchups retained, 132 market rows, 126
   historical forecasts, three games without fabricated forecasts; 61
   upcoming/5 started in fresh reconciliation. Started rows are identical.
   Two Wednesday rows remain late custody. All 66 locked spread/total pairs
   are unchanged. Five distinct research games retain chips 1–5. Seven
   prior-week feature payload hashes equal the original execution gate.
9. **Limitations:** no approved common calibrated ATS/totals probabilities;
   no certified combined five. Incomplete final personnel/starting QB,
   gust, field, itinerary and coaching-change confirmation remain explicit.
   Newly captured initial/updated reports are not final clearance.
10. **Risks:** new QB and OL uncertainty and explosive passing evidence
    challenge unchanged raw forecasts. Holding numeric output fixed does
    not endorse the forecast. Missing reports are unavailable, not healthy.
    Statistical consistency does not validate the model's probabilities.
11. **Rollback:** revert only this refresh's wrapper changes if necessary;
    retain dated evidence and revision receipts. Do not replace original
    intake, previous outputs or seal. No schema/DB rollback is needed.
12. **Scope:** no unrelated files, production repository, protected database,
    model or policy implementations changed. Scratch directories remain
    untracked. No wagers, deployment, v2.9 promotion, Week11 external-model
    training use or merge occurred. ChatGPT reviews PR56. Friday/Saturday
    are future refreshes, with the automation paused after Saturday morning.
