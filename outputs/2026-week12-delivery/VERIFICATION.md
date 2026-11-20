# Week 12 verification and completion boundaries

1. **Objective.** Preserve the November 17 SplashSports source, run approved
   v2.8 logic for every eligible market, publish complete coverage and truthful
   diagnostics in a draft PR, and schedule append-only daily refreshes.
2. **Files changed.** Week12-only source intake, readiness/provider captures,
   original model boards, context receipts/reviews, complete delivery tables,
   revision ledger, Week12 operating/reporting scripts, two test modules,
   exact-byte attributes and two read-only CI acceptance steps. Full scope is
   visible in the PR diff; generated original outputs are immutable.
3. **Schema changes.** None. Existing migrations ran only on a new disposable
   database. The protected `data/cfb.db` SHA remains
   `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.
   Pre/post row counts, applied versions, integrity and foreign-key checks are
   in the ingestion manifest. The disposable DB is not committed.
4. **Behavioral changes.** Adds strict 66-game intake/reconciliation and
   no-overwrite writers; records 63 ATS and 63 totals forecasts plus six
   elapsed-market omissions. Adds exact artifact acceptance and append-only
   revisions that reject altered lines, started rows, duplicate chips, invalid
   confidence and invented common calibration. No model, feature, confidence,
   ranking, master-prompt or production policy changed. No production workflow
   was enabled. The requested task heartbeat is a draft research refresh.
5. **Tests added.** `test_week12_source.py`: 13 source/identity/time/eligibility
   cases. `test_week12_delivery.py`: 20 coverage, duplicate, receipt, late-custody,
   context, immutable revision, chip and numeric-value cases. Earlier tests were
   not weakened or removed.
6. **Commands executed.** Using the repository Python 3.12.14 environment:
   `python -m pytest -q tests/test_week12_source.py tests/test_week11_source_execution.py tests/test_week11_board.py`
   (41 passed); `python -m pytest -q tests/test_week12_source.py tests/test_week12_delivery.py`
   (27 passed before five additional revision cases);
   `python -m pytest -q tests/test_week12_delivery.py` (19 passed after those
   additions). Complete-suite and repository/migration/acceptance commands and
   unedited logs are recorded in `verification-v1/results.json`. Focused final
   revision verification is recorded separately in `verification-v2/`.
   The final combined targeted run including custody-qualified delivery passed
   all 33 tests; `verification-v3/` records that run and exact delivery replay.
7. **Results.** See those machine-readable current-environment logs and the
   PR's exact-head CI link. Passing source and diagnostic checks do not mean
   that the missing calibrated ranking requirement passed. That gate is false.
8. **Data quality.** 66 unique matchups/132 teams and 66 paired spreads/totals;
   zero unresolved teams, reversed identities, duplicates or kickoff conflicts;
   all eight PDF pages visually checked. CFBD and ESPN identities agree. Four
   additional provider FCS-vs-FBS games have no PDF line and are explicitly
   excluded. 63 forecasts per market, zero eligible omissions/fallbacks, five
   distinct research games and chips 1–5 exactly once. All 1,210 sealed files
   match their staged Git bytes. Models use prior-week features through Week11,
   sanctioned point-in-time access and unchanged approved code. Original PDF
   and frozen contest lines are unchanged. External Week11 picks are not used.
9. **Known limitations.** No approved common calibrated ATS/totals ranking;
   totals and mixed policies remain shadow. Every governed ATS confidence is 1.
   Three Tuesday games were already elapsed when execution began. The later
   seal covers 61 forward games and qualifies two Wednesday games as late
   custody, without altering their recorded earlier forecasts. Source print
   time is not forecast custody. Final personnel, many confirmed starters,
   gusts, field conditions and complete coaching-change checks remain missing.
   The UMass supplemental article was retrieved after kickoff and is excluded
   from pregame changes. Daily Thursday–Saturday work is scheduled, not claimed
   already performed.
10. **Risks.** Extreme normal-CDF probabilities can overstate reliability;
    incompatible ATS/totals scores distort mixed ranking. Personnel gaps,
    offensive explosiveness and regression can invalidate the raw Unders.
    Captured official-page text is not medical clearance or independently
    validated causal evidence. The initial seal attempt correctly rejected a
    pregame claim after Wednesday kickoff; the delivered receipt explicitly
    classifies the two late games. It does not improve their custody.
11. **Rollback.** Close the draft PR without merging or revert only its
    Week12 operational commits after reviewer approval. Pause automation
    `week-12-frozen-line-daily-refresh`. Keep source PDF, frozen lines, original
    outputs, hashes and any already issued revisions as historical evidence.
    There is no production database or schema rollback.
12. **Scope confirmation.** No files in the original production repository,
    protected database, model implementation or unrelated NFL work were changed.
    Scratch DBs and PDF previews stay untracked in the isolated worktree.
    The integrated Week11/season audit remains on separate draft PR55. Neither
    PR is self-merged; ChatGPT is the reviewer.

## Corrections preserved in place

The first readiness capture used correct provider requests but copied Week11
manifest labels; intake rejected it. `CAPTURE_CORRECTION.md` identifies the
separate corrected capture. Context review-v2 fixes a passing-leader parser
field and retains review-v1. No original forecast, frozen input or line was
rewritten. Two exact source-text paths retain captured trailing whitespace;
other whitespace checks remain active.

## Daily refresh

Automation `week-12-frozen-line-daily-refresh` is active at 08:00 America/Chicago,
Tuesday–Saturday, with an explicit November 21 morning stop. Since this intake
was recovered on Wednesday, Thursday, Friday and Saturday are the remaining
morning runs. It appends evidence, preserves started-game rows and locked lines,
records all changes and requests ChatGPT review through the draft PR. It cannot
authorize a model promotion or certify unavailable calibration.
