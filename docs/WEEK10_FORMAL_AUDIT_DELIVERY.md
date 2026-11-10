# Week 10 formal audit delivery

The append-only audit reconciles all 57 eligible finals independently from ESPN and CFBD and grades 114 frozen selections. Both markets finished 26-31 (-7.363636 units each). Controlled-logistic combined Top 5 finished 1-4, with no improvement over the original ATS research Top 5. The human-review five finished 0-5. These are not owner-approved or submitted contest picks.

## Scope and ancestry

This focused PR depends on PR #49 at a2a98cf460be6564d7df3dafe81ba7f467b807c9, which descends from integrated main 1aa711e4ba3cc1baa9c6a493bba9ef87e988f0d1. PR #50 remains separate and research-only: exact frozen protocol, holdout, seals and results are archived from 8b6ee3b5c7b32113587c8d8ce730ff7750e2c0a8. Late reporting addenda are identified separately and are not represented as preregistration.

Files added: capture_week10_postgame.py; build_week10_formal_audit.py; week10_audit_{sources,grading,diagnostics,game_process,forensics,report}.py; week10_research_{audit,metrics}.py; adversarial audit tests and input custody fixture; timestamped provider evidence, versioned audit outputs and source preservation records. The existing .gitattributes adds byte-preservation rules for these new paths. The existing CI workflow adds the exact PR #49 dependency branch trigger and a read-only Week 10 audit gate; no checks are removed or operational workflows activated.

No schema changes, database mutations, application prediction changes, v2.8 changes or historical artifact changes. The original 62 matchup source and all 57 ATS/57 totals selections remain unchanged. Five games had already elapsed at source receipt/generation and remain explicitly excluded. The original source does not establish FBS-versus-FCS contest coverage; no retrospective prediction is created for Merrimack-Wake Forest.

## Verification

The authoritative report and all row-level tables are in outputs/2026-week10-postgame-audit/v2/. v1 and its exact generating code are retained; v2 strengthens capture-status and exact-file-coverage checks without changing scores or numerical results. 3,266 pinned inputs, the original historical custody controls, database integrity and the Week 10 prospective seal are checked on every replay. Original source bytes retain exact SHA-256 checks; normalized LF hashing is limited to implementation-source identity.

Added 36 adversarial tests cover altered inputs/lines, missing or extra checksums, contradictory statuses, numerical tampering, nonfinal/duplicate/misoriented scores, changed research membership/probabilities/timestamps, overwrite refusal and ambiguous scoring sequences. Initial focused execution: 36 passed in 26.47 seconds on native Windows Python 3.12.14.

Full delivery verification commands (actual final results and exact source/tested merge identities are recorded in the PR delivery record and native execution receipts):

```text
python -X utf8 scripts/verify_repo_safety.py
python -X utf8 -m scripts.verify_migrations
python -X utf8 -m scripts.verify_cloud_migrations
python -X utf8 -m scripts.verify_replay_compat --output <receipt>/compatibility.json
python -X utf8 -m scripts.build_week9_formal_audit --verify
python -X utf8 -m scripts.week9_scoring_process_v2 --verify
python -X utf8 -m scripts.verify_week10_acceptance
python -X utf8 -m scripts.verify_week10_owner_review outputs/2026-week10-owner-review/20261105-afternoon-decision/owner-review.json
python -X utf8 -m scripts.build_week10_formal_audit --verify
python -X utf8 -m pytest -q
```

CI uses the existing four-job Ubuntu/Windows Python 3.11/3.12 matrix against the actual PR merge tree. A green predecessor run is not evidence for this audit head. No CI success is presumed in this document.

## Limits, risks and review gates

All CLV remains INCOMPLETE: no timestamp-qualified closing quotes. Play volume is not clock-adjusted pace; drive definitions differ by provider. Backdoor labels require validated scoring sequences. Missing verified OL snap data and causal counterfactuals prevent numerical injury attribution. Six historical weeks and one prospective experimental week cannot validate a new ranking or confidence policy. All numerical proposals remain RESEARCH ONLY.

Require successful exact-tree CI, technical review of the cumulative dependency and focused audit, and preserved dependency ancestry before any merge consideration. No automatic merge or owner approval. Rollback abandons or reverts the added implementation while preserving captured evidence and every original frozen artifact. The scoped diff contains no unrelated work.
