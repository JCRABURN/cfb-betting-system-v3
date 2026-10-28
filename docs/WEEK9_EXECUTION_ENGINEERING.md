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
python -m scripts.capture_week9_core --output outputs/2026-week9-prospective/core-initial
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
