# Week 11 board, custody qualification and separate research

## Objective and delivered coverage

Continue draft PR53 on main `d3ba84db74b67a6e4dd8d61e49f28c0759d3a34e`,
which contains merged Week10 PR49 and PR51. All eight original owner images
were recovered, hashed and independently transcribed: **67 original matchups,
134 original contest numbers, zero transcription discrepancies**. ESPN and
CFBD reconciliation identified67 FBS/FBS games, no additional FBS/FCS games,
no unlined schedule gaps and three already-completed Tuesday games. Those
three received no forecasts. The source retains all67 rows.

The unchanged v2.8 adapters generated **64 ATS and64 totals selections** on
November11 at15:37:48.563277 UTC using execution commit
`b3f27eb120487cb4cb71d7b626fe65c14e0bb701`. All64 games have both markets;
missing picks, duplicate locks and model fallbacks are zero. Governed ATS
confidence remains1/5. The totals4/5 and5/5 labels are uncalibrated research
buckets, not demonstrated probabilities. Original ATS/total Top10s, research
Top5s, governed Top5 and legacy mixed Top5 are retained separately.

Full card: `outputs/2026-week11-prospective/WEEK11_BOARD.md` and the corresponding
CSV sheets. No forecast was regenerated using postgame information.

## Material custody limitation

The first cryptographic custody capture occurred **November12 at
12:10:25.542915 UTC**, with sealing code
`7ada8920bece4ba6cd09b1440af0446fa00be14f`. It is explicitly
`LATE_CUSTODY_CAPTURE_NOT_FULL_PREGAME_SEAL`.

Local recorded prediction timestamps precede kickoff for all64 games, but
there is no independently established external pregame seal for Wednesday's
Buffalo–Ball State, Sacramento State–Central Michigan or Massachusetts–Toledo.
Those three forecasts are preserved unchanged, not newly recommended or
retroactively qualified. Capture precedes the recorded kickoffs of the other61
games. Recorded timestamps alone are not independent proof of historical
publication. The strict ordinary seal still rejects capture at/after kickoff;
the separate explicit late-capture mode reports the limitation per game.

Original67-row source SHA256:
`a27f367a38918e188cc2e8aa417b9a1970049ca02d0501789d00ccfdb0b12c22`.
Derived64-row subset SHA256:
`6e48f590e06ec1b69f6e351f1ef0cc679c88b7966c52c224ce48347a46706476`.
Board custody manifest SHA256:
`d6d163f2500fa638ad73da8b4b0da244e9cad4fe456e42d80ea65e36e073868c`.
Source database SHA256 remains
`09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842`.
Model execution used a disposable database; the source database was not written.

## Context and provisional owner review

The initial official-site capture contains159 request records, all successful,
covering18 future games in the union of ATS/total Top10s. The19th game is the
started Sacramento State game and receives no new context. NWS hourly forecasts
cover17 outdoor venues; North Texas–UTSA is indoors. A separate public conference
report capture preserves the Big Ten, Big12 and ACC initial availability
payloads. The read-only public endpoint is the one used by the official
conference embeds; no login, private endpoint or security setting was changed.

Actual site capture: November12 **12:11:56–12:12:30 UTC**. The directory label
`20261112T1220Z-initial` is an artifact identifier, not its authoritative receipt
time. Request and receipt times are stored individually in its manifest.
Conference publication date/time and retrieval time remain separate.

The separately timestamped owner-review JSON/Markdown contains all19 games,
their original numbers, QB/OL/defensive designations where available, prior
Weeks8–10 efficiency/possession samples, rest, travel destination, forecast
weather and separate provider market observations. Unknown final availability
is explicitly INCOMPLETE. Available is not a medical diagnosis, starter
announcement or workload guarantee. Market retrieval time is not a book quote
timestamp or a qualified historical close. CLV remains INCOMPLETE.

Provisional human five, recorded November12 at12:22:37.546924 UTC:

| Rank | Selection | Unchanged forecast | Human confidence |
|---:|---|---:|---:|
|1|Duke+13.5 at Miami|Miami by4.52|2/5|
|2|Colorado State–Washington State Under67.5|55.17 total|2/5|
|3|Boston College+28.5 at Notre Dame|Notre Dame by17.59|1/5|
|4|Colorado+10.5 vs Houston|Houston by2.33|1/5|
|5|Michigan+11.5 at Oregon|Oregon by1.91|1/5|

These are tentative contextual judgments, not approved contest submissions,
validated probabilities or a new ranking policy. There is no diversification
quota. Original mixed research ordering remains: Texas Tech–Oklahoma State
U73.5, FAU–Tulsa U74.5, North Texas–UTSA U76.5, Kansas–West Virginia U67.5,
Colorado State–Washington State U67.5. Four are excluded from the human five
because the documented offensive and explosive-play risks undermine reliance
on their unusually large model gaps. The full review states each exclusion
and the reasons/risks for all alternatives, including Northwestern's QB absence,
Wyoming's doubtful QB and Hawaii's forecast23mph wind.

Source-backed material findings include OSU43.9PPG and5.5% three-and-outs;
FAU40.8PPG and a five-game3+ passing-TD streak; WVU allowing70 plays of20+ yards;
Texas State's last-game84 plays/13 drives and58.33% offensive success rate;
Duke's four sacks allowed; and Michigan/Oregon OL/QB/defensive availability.
These findings cause no invented point adjustments. Final Friday/Saturday
reports, actual starters and snap-share implications remain unresolved.

## Research only: what improved and what did not

The existing chronological Weeks6–10 exploration was designed after Week10;
it is retrospective, not prospective validation. Week10 had57 selections per
market, both26–31, hypothetical risk-one-unit -110 return **-7.363636 units**.
Positive market blends retain the same sides and therefore the same full-card
record. Better point error alone does not demonstrate better selection quality.

| Week10 market/method | MAE | RMSE | Brier | AUC |
|---|---:|---:|---:|---:|
|ATS locked-line baseline|12.7982|16.6714|.2500|.5000|
|ATS25% model|13.0045|16.8984|.2675|.3734|
|ATS50% model|13.3381|17.1975|.2730|.3685|
|ATS original point/Gaussian|14.1223|17.9962|.2848|.4132|
|Totals locked-line baseline|13.1316|16.1236|.2500|.5000|
|Totals25% model|13.5249|16.6787|.2625|.3151|
|Totals50% model|13.9542|17.3314|.2747|.2928|
|Totals original point/Gaussian|15.1550|18.8875|.3009|.2940|

Line-baseline probability .5 is scored on the original sides, not a bet.
Prior-frequency totals calibration had Brier.2478/AUC.6067 on Week10, but this
single retrospective fold does not validate it. The25% combined Top5 was0–5;
50% was1–4. No evidence here justifies stronger confidence or model promotion.
All fold-level calibration bins, returns and Top5 memberships remain in
`research/week11_validation/results-v2.json` unchanged.

A new independent forward shadow was recorded **November12 at12:19:39.330262
UTC**, before the remaining61 recorded kickoffs. It preserves610 market/method
rows across locked-line,25%,50%, original Gaussian and prior-frequency methods,
plus every experimental combined Top5. It uses only audited Weeks5–10 training.
The three started Wednesday games are excluded from new research; original
benchmark memberships are retained, including the already-started ATS member.
The four still-future original ATS benchmark members are a separate paired
comparison; no retrospective replacement is made.

The drive prototype is deliberately incomplete:147 provider drive rows have
offensive score changes incompatible with the recorded drive result. Both teams
in each anomaly are quarantined. Only14 of61 matchups have sufficient untainted
prior-drive data;47 receive an explicit blocked row, no imputation. Raw provider
responses are unchanged. Some anomalous fields span multiple scores on a single
drive, including a31-point delta; no TD=7 reconstruction is used. Lack of genuine
historical pregame drive snapshots also blocks a valid historical drive backtest.

Week11 outcome metrics are PENDING. The frozen protocol requires all candidates,
including failures, MAE/RMSE, Brier/AUC/calibration, hit rates/returns, overlapping
versus changed selections and clustered uncertainty after independent finals.
No method is selected based on Week11 results. PR50 remains separate; no new
Confidence3–5, v2.9 or policy promotion is authorized.

## Engineering, verification and review gates

New execution adapters: `week11_eligibility.py`, `prepare_week11_source.py`,
`run_week11_execution.py`, `finalize_week11_card.py`, `seal_week11_components.py`,
`seal_week11_board.py`. New context/research/acceptance helpers:
`week11_context.py`, `capture_week11_availability.py`, `review_week11_context.py`,
`verify_week11_acceptance.py`, `research/week11_validation/forward_shadow.py`.
Evidence is append-only under the Week11 readiness/prospective/context/owner-review
directories; no older evidence, model implementation or v2.8 policy changed.
**No schema changes or new dependencies.**

Adversarial tests cover absent/extra checksum entries, modified lines/forecasts,
confidence and ranking changes, approval/status contradictions, backdating,
started-game exclusion, image/source tampering, late custody, incomplete markets,
drive anomalies and research replay. The existing workflow retains all gates,
adds Week11 acceptance and fetches full git history so original execution commits
can be independently inspected. Token permissions and operational workflows are
unchanged. `.gitattributes` preserves new evidence bytes and recognizes CRLF only
for affected CSV/two JSON artifacts while retaining other whitespace checks.

Executed initial board/source suite: **28 passed in51.19s**. Earlier eligibility
head8fb6756: native1097 tests passed and all four GitHub matrix jobs passed in
[run43047080672](https://github.com/JCRABURN/cfb-betting-system-v3/actions/runs/43047080672).
That result is not claimed for the expanded board. Final native/matrix results
and exact source/tested-merge SHAs must be recorded in PR53 before acceptance.
The expanded focused suite (`tests/test_week11_context_shadow.py`,
`tests/test_week11_board.py`, `tests/test_week11_source_execution.py`) passed
**39 tests in106.32s** before final delivery. Staged diff whitespace checking
passed with zero findings after preserving the original CRLF representations.

Commands for the exact final integration tree:

```text
python -m pytest -q
python scripts/verify_repo_safety.py
python -m scripts.verify_migrations
python -m scripts.verify_cloud_migrations
python -m scripts.verify_replay_compat --output <new-verification-directory>/compatibility.json
python -m scripts.build_week9_formal_audit --verify
python -m scripts.week9_scoring_process_v2 --verify
python -m scripts.verify_week10_acceptance
python -m scripts.build_week10_formal_audit --verify
python -m scripts.prepare_week11_readiness --verify
python -m research.week11_validation.anchor_diagnostics_v2 --verify
python -m scripts.verify_week11_transcription
python -m scripts.verify_week11_acceptance
git diff --check <base>...HEAD
```

Observed failures retained in the work log: relative capture-path handling failed
before outputs existed and was fixed atb3f27eb; an initial source-order assertion
identified reverse attachment ordering; ordinary late sealing correctly fails;
raw CRLF was flagged by diff whitespace checking and preserved with narrow CRLF
attributes; console cp1252 could not print a few Unicode article characters and
was corrected only for terminal display; drive scoring inconsistencies blocked
the initial forward build before writing, then produced explicit quarantine.
No original evidence was regenerated to hide a failure.

HOLD pending full final-tree CI and independent technical review. Owner betting
approval remains PENDING regardless of technical checks. Remaining limitations
include three unproven pregame seals, final personnel/market timestamps, unknown
wind gusts and unvalidated ranking reliability. Rollback reverts new helpers and
workflow additions while retaining historical source/evidence commits; it requires
no source-database restoration or migration. No unrelated work is included.
