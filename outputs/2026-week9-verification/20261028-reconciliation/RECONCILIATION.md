# PR 45 exact-head verification reconciliation

Reviewed head: `db007694d3ee87d3a2b85feacd1fd9b7a2d10fb0`. Original delivery: `e3a9a10ed63c0aa003d16e88208331d1ff81e170`. This report preserves the earlier records and distinguishes execution evidence from later archival custody.

## Three distinct test runs

| Run | Commit attribution and evidence | Result |
|---|---|---|
| A, October 28 earlier evening | `e3a9a10...`; contemporaneous execution and `20261028-evening/integration-gates.json` identify that tree. Original committed log remains untouched and is also copied as `prior-e3a9a10-203.82s.txt`. | 809 passed, 39 warnings, **203.82s** |
| B, October 28 after delivery commit | `db007694...` according to the contemporaneous tool wrapper's returned HEAD and separate exact-head gate JSON. The original temporary pytest log has now been copied byte-for-byte as `prior-db007694-240.94s.txt`; temporary gate JSON is preserved separately. | 809 passed, 39 warnings, **240.94s** |
| C, fresh reconciliation run | `db007694...` explicitly recorded **before and after** execution, with empty tracked diffs, command, cwd, UTC start/end, exit code and log hash in separate immutable start/completion records. | 809 passed, 39 warnings, **193.64s** |

Runs A and B are not conflicting durations for one run. The prior response failed to place run B's full log and provenance in the PR repository, making its claim less reviewable than run A. This delivery repairs that documentation/custody gap without relabeling A as B or rewriting either log.

Important limitation: the old pytest text logs do not themselves embed a commit SHA. Their commit attribution depends on the contemporaneous execution record and separate metadata. A file's mtime or its later archival hash does not prove its original execution time or commit. The new archive manifest labels this explicitly. Run B's completion wrapper reported `head=db007694d3ee87d3a2b85feacd1fd9b7a2d10fb0`, exit 0, and the temporary log path in the earlier tool transcript; no missing start timestamp has been invented. Run C provides direct, durable before/after commit evidence for the head under review.

Run C began `2026-10-28T23:09:39.055997+00:00` and completed `2026-10-28T23:12:54.187463+00:00`. Python wall time includes wrapper overhead and need not equal pytest's reported duration. All three reported the same 809 passes and 39 existing deprecation warnings. No unexplained test failures occurred.

SHA256 identities:

- Run A log: `ae1d0f99e5ce0bc3116af59faecf658afab9ce556345dc9e5aa8d74d2b87541d`.
- Run B log: `50b4b834f2fd7e32b3ce940a0df030f70dd855981f67e96de8579ff139d78c67`.
- Run C log: `2514b3b838d879caa6c8c3ec1884883b08c9764e85533c862133c9bb500aac5c`.

## Additive scope, ancestry and integrity

`git diff --name-status e3a9a10ed63c0aa003d16e88208331d1ff81e170 db007694d3ee87d3a2b85feacd1fd9b7a2d10fb0` contains exactly **389 additions under outputs/2026-week9-***, zero modifications and zero deletions. No code, test, schema, dependency, source database, original model, historical result or policy changed in that commit.

`git merge-base --is-ancestor` passed for each of these ancestors:

- Main `abb4eb26bd1140e66972d2f1143cd587e80960b4`.
- Repaired #41 `78ed6eb5540f66ba3193f91366c802e27e3cb9c7`.
- #42 `7f42da36f9aef4666bb715d49babde7ee374defa`.
- #43 `43807ae374b9db143c1d9675d7a7cafe6e2f28ba`.
- #44 `922f1f8f8c66ef14674eb9aa20db144a45dada68`.
- Prior #45 delivery `e3a9a10ed63c0aa003d16e88208331d1ff81e170`.

Fresh byte checks compare **118 working-tree files** directly with their protected Git blobs: 66 Week 8 postgame audit files, four additional Week 8 research files, 44 Week 9 prospective files and four original morning owner-review files. The earlier shorthand "66 audit/research files" described the 66-file audit directory; this expanded inventory explicitly includes the separate four-file research directory. Each path/hash is recorded in `fresh-integrity-gates.json`.

Original source DB SHA256 remains `09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`. Week 9 seal SHA256 remains `77aea6d0eefecc6dce014524610294da617d7dab2b6e903a59f8664f664e5460`. The original 54 ATS and 54 totals, lines, timestamps, forecasts, confidence and mixed research ordering remain intact.

Eight read-only gates passed on the exact reviewed head. They replay sealed forecast arithmetic, scores, ranks, rendered board and historical audit outputs. The pregame full-database refit recorded October 28 at 22:42 UTC is retained; no new full-card generation/refit was forced past the kickoff guard now that two Wednesday games have started.

## Exact verification commands

Working directory: `C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.worktrees/week9-execution`. `python` below is `C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.venv/Scripts/python.exe`.

```text
python -m pytest -q
python -m scripts.verify_week7_audit_integrity
python -m scripts.seal_week8_board --verify
python -m scripts.build_week8_postgame_audit --verify
python -m scripts.week8_scoring_sequence_review --verify
python -m scripts.week8_numerical_research --verify
python -m scripts.seal_week9_board --verify
python -m scripts.review_week9_context --capture outputs/2026-week9-context/20261029T1147Z-thursday-gate --verify
python -m scripts.verify_week9_owner_review outputs/2026-week9-owner-review/20261029-morning-decision/owner_review_shortlist.json
python outputs/2026-week9-verification/20261028-reconciliation/derive_thursday_diagnostics.py
```

Capture and initial derivation were also executed for both new context versions with `scripts.capture_week9_context --output <directory>` and `scripts.review_week9_context --capture <directory>`. Capture directories are `outputs/2026-week9-context/20261028T2310Z-thursday-gate` and `outputs/2026-week9-context/20261029T1147Z-thursday-gate`. The diagnostic script is a read-only research recipe, not a production implementation; its deterministic JSON replay is checked. No tests were added or modified.

## Thursday context, quality and limits

The Thursday capture succeeded for 158 nonweather records and 52 weather forecasts. Two elapsed Wednesday games were intentionally skipped, not silently omitted. Their original card rows stay sealed. The new market ledger contains 104 provider-attributed observations for 52 future games; started games are excluded from pregame qualification. Provider quote time, freshness and ATS/total juice are unavailable. Historical CLV remains **INCOMPLETE**; no market close was fabricated.

The revised human five is Northwestern +3.5 (2), Navy +30.5 (2), Southern Miss–ULM Under 56.5 (2), SMU–Syracuse Under 58.5 (1), Troy +20.5 (1). FAU–North Texas Under 77.5 moves to alternative rank 6, with its original model forecast retained. All ten candidates and prior revisions remain available. Human confidence is uncalibrated and separate from model confidence. No owner approval is inferred.

Official pregame notes for FAU, UNT and JMU were retrieved Wednesday and Thursday; PDF bytes were identical across captures. FAU and UNT depth/explosive pages were visually inspected. Depth-chart listing does not establish game-day medical availability. Sun Belt availability requests returned HTTP 404; no substitute third-party status was promoted to official clearance. No currently verified full QB/OL/defense clearance exists for the Thursday candidates. No new numerical injury/weather adjustment was invented.

The JMU 50.3 home scoring figure includes 87 points against FCS Wagner; the FBS-only home average is 38.0 (n=3). Troy's road average is 11.0 (n=3). FAU/UNT diagnostics are outcome-informed exploration from only five audited games, not a new reliability policy. Full reasoning and personnel details appear in the new owner review.

Non-test operational issues: a Windows wildcard invocation of rg failed and was rerun with explicit glob filters; a PDF text extraction warning about rotated text prompted plain extraction and visual page checks; Poppler emitted font warnings but the inspected relevant pages were readable. No historical file was edited to hide these issues. Git's sandbox warning about the global ignore file did not prevent the explicit repository status/diff checks.

## CI and merge recommendation

GitHub still reports zero check runs, zero commit statuses and zero Actions runs for `db007694...`. Two reviews are COMMENTED (one at e3a9a10 and one at db007694), neither APPROVED. The stored API snapshot preserves these facts. The repository defines a PR test workflow, but the absence of execution is unexplained; local passes are not independent CI.

The test-log reconciliation is resolved by preserving both old runs and adding run C with durable commit provenance. **Keep #44 and #45 draft pending independent review and CI verification.** Preserve repaired #41 ancestry, #42/#43 source custody, and #44 before dependent #45. Do not merge defective ancestors separately. Missing historical CLV does not block unrelated integrity/evidence code; unresolved personnel blocks calling the contest decision fully cleared, not the arithmetic audit.

## Delivery scope and rollback

This follow-up adds only timestamped captures, immutable copies of test records, a separate human review, descriptive research output/recipe and verification documentation. It does not alter the reviewed db007694 tree. If these additions are committed later, the new evidence-delivery SHA must be distinguished from the tested db007694 SHA; no new-head full-suite execution is claimed without a corresponding run record.

Exact path inventory and final custody hashes accompany this report. No schema changes, source DB mutations, test changes, model changes, production scheduling, unrelated NFL edits, owner approval or merge. Rollback by leaving the evidence commit unmerged or superseding the human review with a new timestamped record, retaining all custody history; no database recovery is needed.
