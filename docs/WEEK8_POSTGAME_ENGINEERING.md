# Week 8 postgame audit engineering record

Objective: grade all 52 ATS and 52 totals from the immutable PR #42 v2 board, reconcile provider scores independently, and add cross-week diagnostic evidence without policy changes.

Base: PR #42 7f42da36f9aef4666bb715d49babde7ee374defa. PR #41 78ed6eb5540f66ba3193f91366c802e27e3cb9c7 contains #35–#40 integrity repairs. Main at review: abb4eb26bd1140e66972d2f1143cd587e80960b4. No PR is merged by this work.

Files: five new scripts (capture_week8_postgame_evidence, build_week8_postgame_audit, research_week8_diagnostics, week8_scoring_sequence_review, week8_numerical_research), tests/test_week8_postgame_audit.py, outputs/2026-week8-postgame-audit/, outputs/2026-week8-audit-research/, this document, and append-only .gitattributes rules for new evidence. No schema changes. Source data/cfb.db is read-only, SHA256 09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842.

Behavior: new versioned audit writer refuses existing outputs; verifier demands exact output/evidence/code/protected hash inventories and deterministic bytes. Score identities agree across ESPN scoreboard, 52 summaries and independent CFBD capture. North Dakota State–New Mexico kickoff discrepancy (02:00 frozen / 02:20 provider) is preserved in a separate reconciliation record; both followed the original seal. All 47 protected files are preserved. Week 8 seal SHA256 355e72a9a07ef3fc48891519655ab52ccd5c4283add5cd5a39f29788cf1beba2.

Tests: overwrite/partial output, missing and extra checksums, contradictory audit status, fabricated approval, provider orientation/final/score conflicts, unqualified closing lines, reversed/incomplete scoring sequences and prior-only numerical folds. Exact commands, using the repository .venv/Scripts/python.exe:

```
python -m pytest tests/test_week8_postgame_audit.py -q
python -m scripts.build_week8_postgame_audit --verify
python -m scripts.week8_scoring_sequence_review --verify
python -m scripts.week8_numerical_research --verify
python -m scripts.seal_week8_board --verify
python -m scripts.verify_week7_audit_integrity
```

The complete suite is required on the actual proposed Week 9 integration branch containing this audit. Final execution results and integration SHA are recorded in docs/WEEK9_EXECUTION_ENGINEERING.md and its verification directory, not inferred from a corrected disposable tree.

Data quality: exactly 104 grades, no missing identities, no duplicate picks, original lines/forecasts/confidence retained. No recorded Week 8 owner-approved five; no owner performance invented. All 52 supplemental scoring sequences validate; zero selected-side covers meet the existing last-five-minutes backdoor definition. That supplement preserves the original conservative unclassified ledger field.

Limitations and risks: CLV remains INCOMPLETE because postgame close labels lack historical timestamps. Full play-by-play neutral-situation pace is not reconstructed. Weeks 5–6 research ordering is retrospective; Weeks 7–8 sealed ordering is genuinely pregame, but newly inspected hypotheses are exploratory. Hypothetical returns risk one unit at -110, not actual wagers. Repeated teams and small cohorts limit causal conclusions. No model, ranking, confidence or v2.8 policy change.

Rollback: leave draft unmerged or revert only the additive audit commits, retaining captured evidence for custody. No database migration or historical regeneration is needed. Existing Week 5 line-ending rules and expected source hashes remain untouched. Original repository and unrelated NFL working-tree changes were not modified.
