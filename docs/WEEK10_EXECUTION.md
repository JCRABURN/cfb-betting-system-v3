# Week 10 prospective execution and custody

This extends existing PR #49. It does not create another cumulative integration PR.
PR #48 remains the primary historical integration candidate, pending genuine
non-author approval. Rebase #49 only after that approved integration is on main.

All nine original screenshots were recovered from `Review PR 38 Audit`, with
their original chat receipt times, recovery time and SHA-256 hashes recorded.
Independent visual transcription agrees with all 62 original spreads and totals.
Seven original image-row references were wrong: JMU/Southern Miss is image 2 row
1, and the remaining six image-2 rows shift down one. The three original PR49
files remain unchanged. The separate screenshot custody/reconciliation records
supersede only those references. Original image creation/market quote time is
unknown; receipt time is not represented as posting time.

The explicit Week10 resolver profile maps the staged `Miami OH` to the original
image/provider identity `Miami (OH)` at the canonical resolver boundary. This
prevents a generic prefix match to Miami (FL) without editing historical resolver
code or any original source row. The Buffalo/Miami game is elapsed and excluded.

As of the November 4 evening CST preparation, all 62 FBS schedule games reconcile:
57 upcoming, two Tuesday finals, three already-started Wednesday games. No new
prediction is made for those five elapsed games. Chicago uses CST UTC-06 during
November 3–7; all displayed prospective times match the captured UTC schedule.

The model adapters reuse unchanged ATS and totals business logic, confidence
policies and research ranking. Inputs end at Week9; no Week10 outcome or statistic
enters training or target inputs. Only a disposable database is mutated. Original
`data/cfb.db`, v2.8, historical lines, forecasts, approvals and seals are unchanged.
Research scores are not validated winning probabilities, and the mixed Top5
retains the existing incomparable-score warning. No selection is owner approved.

New files: five Week10 source/execution/component/card/seal adapters, independent
screenshot review and resolver profile, timestamped captures and custody evidence,
production-week source metadata, and `tests/test_week10_continuity.py`. Attribute
rules preserve original PR49 Git LF blobs and original CRLF receipt hashes across
platforms; other new evidence is byte-preserved. The disposable DB is ignored.
There are no schema, model, application-policy or security-setting changes.

Initial command actually run: `python -X utf8 -m pytest -q
tests/test_week10_continuity.py`: **30 passed in 1.40s** before the implementation
commit. Tests reject line replacement, target contamination, duplicate/missing
games, kickoff errors, contradictory completed scores and every partial card
output overwrite. This is not a claim of completed model execution or later CI.

Execution commands, after committing the adapters:

```powershell
python -X utf8 -m scripts.run_week10_execution --source-lines production-weeks/2026-week10-splashsports.csv --source-metadata production-weeks/2026-week10-splashsports-lock-metadata.json --capture-dir outputs/2026-week10-prospective/core-initial --database data/week10-execution.db --output outputs/2026-week10-prospective
python -X utf8 -m scripts.finalize_week10_card --database data/week10-execution.db --output outputs/2026-week10-prospective --source-lines production-weeks/2026-week10-splashsports.csv
python -X utf8 -m scripts.seal_week10_board
python -X utf8 -m scripts.seal_week10_board --verify
```

Source preparation and card writing refuse existing outputs. A failed version
must be preserved and superseded, never overwritten. Final numerical results,
full-suite checks and exact tested commits belong in a separate delivery record.
CI of the eventual main integration cannot be claimed before that tree exists.
No operational workflow is activated. Rollback means abandoning the additive
execution while retaining captured evidence; no source DB restoration is needed.
Unrelated NFL work and the original production repository are untouched.
