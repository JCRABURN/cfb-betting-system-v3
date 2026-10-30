# Week 9 execution and context engineering record

Objective: reconcile all six original screenshots, lock all eligible contest lines, run unchanged ATS/totals pipelines prospectively, and preserve separate context and owner-review decisions.

Ancestry: #41 78ed6eb5540f66ba3193f91366c802e27e3cb9c7 → #42 7f42da36f9aef4666bb715d49babde7ee374defa → #43 43807ae374b9db143c1d9675d7a7cafe6e2f28ba. Model adapters/source lock commit 93f818fea5dc49a49b6bb1c1a569d8f25817c898. Actual proposed integration adds the separate Week 8 audit branch; final integration SHA/results follow below. No remote PR merge is performed.

The board was generated 2026-10-28 03:07:42.987616 UTC (Tuesday 22:07 CDT) and sealed 03:07:48.578763 UTC. First eligible kickoff is 2026-10-28 23:00 UTC. Seal SHA256 77aea6d0eefecc6dce014524610294da617d7dab2b6e903a59f8664f664e5460. Local sealing and later GitHub push are separate custody events; no remote publication timestamp is backdated.

Files: new Week 9 capture/lock/execution/finalization/component-seal/board-seal/context/review-verifier scripts and tests; data/ingest/2026-week9-independent-screenshot-review.csv; production-weeks/2026-week9*; outputs/2026-week9-prospective/, context/, owner-review/, elapsed-results/, verification/; this document; additive .gitattributes/.gitignore rules. Existing production model modules and v2.8 policy are unchanged. No schema migrations; execution uses ignored disposable data/week9-execution.db. Original data/cfb.db SHA256 is 09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842.

Coverage: 56 screenshot rows independently compared, zero transcription discrepancies; 56 scheduled and market-lined FBS games; two elapsed exclusions; 54 eligible games / 54 ATS / 54 totals; zero duplicates, silent omissions or skipped predictions. All six image bytes and actual chat receipt are retained. Original image capture/market posting timestamps are unknown. Delaware 35–WKU 21 and Sam Houston 3–Missouri State 24 are separately captured audit-only finals and excluded from modeling. Sam Houston was LIVE at screenshot receipt, not final.

Confidence: governed ATS is uniformly 1 with null governed uncertainty. Totals confidence is the existing uncalibrated research bucket. Original ATS, totals, governed and mixed Top 5 groups remain intact. Human review is a separate ten-candidate artifact with ordinal confidence, zero numeric projection adjustments and owner approval PENDING. The mixed list contains five totals because its score scale is not comparable to ATS; 18 totals scores exceed the maximum ATS score.

Initial validation: 15 Week 9 continuity tests passed; full execution tree before additional context tests passed 777 tests / 39 warnings in 196.03s. Added context/owner-review checks passed 11 tests in 9.24s. These do not substitute for the final integrated suite below.

Exact pipeline commands (repository .venv/Scripts/python.exe):

```
python -m scripts.capture_week9_core --output-directory outputs/2026-week9-prospective/core-initial
python -m scripts.run_week9_execution --source-lines production-weeks/2026-week9-splashsports.csv --source-metadata production-weeks/2026-week9-splashsports-lock-metadata.json --capture-dir outputs/2026-week9-prospective/core-initial --database data/week9-execution.db --output outputs/2026-week9-prospective
python -m scripts.finalize_week9_card --database data/week9-execution.db --output outputs/2026-week9-prospective --source-lines production-weeks/2026-week9-splashsports.csv
python -m scripts.seal_week9_board
python -m scripts.seal_week9_board --verify
python -m scripts.capture_week9_context --output outputs/2026-week9-context/20261028T1320Z
python -m scripts.review_week9_context --capture outputs/2026-week9-context/20261028T1320Z --verify
python -m scripts.verify_week9_owner_review outputs/2026-week9-owner-review/20261028-morning/owner_review_shortlist.json
python -m pytest -q
```

Do not rerun writers on original paths. New context capture paths must be unique. Read-only verifiers are safe. Daily heartbeat continues through October 31 morning, then pauses; later wakeups must not collect postgame material as pregame evidence. Past-kickoff ESPN/weather captures are skipped, and late owner-review recommendations are rejected.

Current context: 54 ESPN summaries, 54 NWS kickoff forecasts and 22 official team sites plus discovered articles. Morning capture has 162 nonweather records and zero unavailable responses. Supplemental explicit URL archival attempts include three 404s, recorded honestly. Navy preview remains web-retrieved evidence with archival uncertainty. Complete backup/OL/defensive availability, gusts, field condition and team itineraries remain unavailable. Timezone names retained; numeric offsets unavailable because local tzdata is missing. Current market quotes are retrieval-time context, not historical closes.

Failures and resolutions: initial restricted-network capture failed visibly and is preserved under verification/core-failed-sandbox; authorized network capture succeeded separately. Initial local timezone lookup failed; missing offsets now remain explicit nulls rather than invented values. Temporary approval-service usage exhaustion prevented a prior push; subsequent authorized pushes succeeded. One previously sealed Week 8 source trailing-space warning is preserved, not silently edited. No failing audit gate is waived.

CI: fresh GitHub check-runs queries show zero runs at #41/#42/#43 heads. The connector rejected the workflows collection endpoint; that is an access gap, not proof of an empty workflow configuration. Local test logs are evidence, not GitHub CI success.

Risks: incomplete injury lists, uncalibrated confidence, large totals residual tails, early weather uncertainty, absent historical CLV. No sportsbook recommendation or actual wager return claimed. Source receipt was after Tuesday action, so no retroactive Tuesday prediction exists. Policy proposals remain RESEARCH ONLY.

Rollback: leave drafts unmerged or revert additive execution/context commits, retaining immutable source and sealed evidence for audit. Ignore/discard only the disposable execution database if needed; never regenerate source cfb.db. No production rollout, secret change, schema migration or unrelated file edit. Root NFL work and original repository remain untouched.


## Final integration validation — October 28 morning

Draft audit PR #44: https://github.com/JCRABURN/cfb-betting-system-v3/pull/44 at 922f1f8f8c66ef14674eb9aa20db144a45dada68. Draft execution PR #45: https://github.com/JCRABURN/cfb-betting-system-v3/pull/45. Actual integration commit tested: bcd1b603dc70b24e0154d5a2f8b5cef5c0bc48ed (parents preserve both workstreams). Subsequent delivery commits contain verification evidence/documentation only.

`python -m pytest -q`: **807 passed, 39 warnings, 215.06 seconds**, exit 0. Warnings are existing datetime.utcnow deprecations. Full stdout/stderr: outputs/2026-week9-verification/integrated-full-suite.txt. All eight commands in integrated-gates.json exited 0: Week 7 strict integrity; Week 8 seal, audit, scoring supplement and numerical research replay; Week 9 seal, context replay and owner-review validation. Week 7 checks 419 custody items and replays 10 outputs; Week 8 checks 47 protected files, 57 evidence files and eight output files. Missing CLV remains explicitly INCOMPLETE.

The read-only disposable-database refit reproduces every numerical component, fit, feature cutoff and metadata field exactly after canonical JSON serialization, excluding only its newly sampled `generated_at_utc` capture timestamp. Initial native/serialized whole-object comparisons failed because of JSON tuple/list representation and that runtime timestamp; the field-level diff identified only the timestamp after serialization. No model tolerance was introduced and no original timestamp or artifact was rewritten. Original/replay times and exact computation hash are in model-refit-replay.json. Database integrity and foreign keys passed; its SHA256 remained cf8d121b62c4d80f63558bd0d32df688ae6141e7d16dc23224a3ec1b28592bba.

All prior PR #42 tracked blobs are unchanged except additive .gitattributes/.gitignore rules; no prior path was deleted. PR #43 original CSV/manifest bytes match their exact source commit. Detailed counts and full changed-file lists are in protected-artifact-integration-check.json and week8-changed-files.txt / week9-changed-files.txt. New verification files accompany this delivery; source snapshots and sealed forecasts are unchanged.

Fresh GitHub checks for #41–#45: zero check runs, zero statuses, zero PR-triggered workflow runs at recorded heads. GitHub's aggregate status is pending due to absence, not a failing or passing CI job. Independent review remains outstanding. Recommend integration review in ancestry order #35–#38, screenshot #39, repair #40/#41, board #42, then source #43 plus audit #44, finally #45. Do not squash away custody commits without preserving their references. Retarget stacked #43 after #42 integration if needed. Do not merge a changed or unverified head. Missing historical CLV alone does not block unrelated integrity/evidence code; it does block claims of complete CLV evidence or approved policy promotion.

No unexplained test failures remain. One known trailing whitespace warning in already hashed Week 8 audit source is retained; the transient append-only attributes merge conflict was resolved preserving both sides. Three supplemental archive 404s, missing tzdata offsets and historical CLV/availability gaps are explicit limitations. No owner approval, model promotion, live wager, unrelated edit or production release occurred.


A final continuity check identified that a later daily review must retain original timestamps for already-started games. The additive owner-review verifier now permits this only when the entire started-game row matches the previous saved review exactly; missing prior custody or any post-kickoff change fails. Two adversarial tests were added (9 owner-review tests passed in 0.43s). A final complete-suite run follows this small correctness change, with its own log and commit reference; the earlier 807-test result remains preserved.

Merge recommendation clarification: the dependency order above is a review order. Do not individually merge an earlier defective audit writer/verifier simply because it is an ancestor. Accept the repaired aggregate tree containing #41, then its verified dependents after independent review; preserve ancestry and evidence. All #35–#45 remain open drafts as of the recorded snapshot. No GitHub CI jobs or owner approval are inferred.

Capture-code custody clarification: the initial core provider manifest records HEAD #43 at request time, while the newly written Week 9 capture adapter was still uncommitted. That HEAD is not a claim that the adapter existed in #43. Its exact LF-normalized code hash matches the later 93f818f commit made before predictions and sealing; raw payload/request times are unchanged. See capture-code-custody-clarification.json. The Week 8 capture/audit additions likewise become committed evidence in #44; their manifests preserve source/audit code hashes rather than pretending postgame collection was pregame.


## Final result after continuity safeguard

Actual proposed integration code commit **2631bfcf41c6c8c87f7d81246af58fdbc62389b2**: `C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.venv/Scripts/python.exe -m pytest -q` completed with **809 passed, 39 existing deprecation warnings, zero failures in 193.74 seconds**, exit 0. Log: outputs/2026-week9-verification/final-full-suite.txt; machine-readable summary: final-verification-summary.json. Later delivery commit adds only logs, source-custody clarification, projection-component presentation and documentation; tested code is unchanged.

Original owner-review references: 17 archived references match URL, SHA256 and receipt timestamp; Navy's preview remains explicitly web-retrieved with a failed direct archive. `PROJECTION_COMPONENTS.md` shows the separate frozen totals-model away/home score components beside the ATS margin, preventing the two independent fits from being silently combined.

Recommended owner-review five, pending approval: Northwestern +3.5 (human C3), Navy +30.5 (C2), Southern Miss–ULM Under 56.5 (C2), San Jose State +14.5 (C1), FAU–North Texas Under 77.5 (C1). The last two are low conviction. Original model confidence/order stays intact; all ten candidates and exclusion reasons remain available. This is a contest shortlist, not validated wager advice.
