"""Render actual audit outcomes and limitations without promoting a model."""


def record(r):return f"{r['wins']}-{r['losses']}-{r['pushes']}"
def number(v):return 'N/A' if v is None else f'{v:.6f}'


def report(custody,grades,members,d,p,research,findings,clv,sequences):
    lines=['# Week 10 forensic audit','',
           'All 57 eligible games are final and agree across ESPN summaries, ESPN scoreboard and CFBD. All 114 independent grades agree with the separately graded frozen PR50 baseline. No missing eligible game or unexplained score discrepancy remains.',
           '', 'All selections, lines, forecasts, confidence, ranks, timestamps, screenshots and owner-review versions remain unchanged. Master Prompt v2.8 is unchanged. No owner-approved five was identified; research and human-review cohorts are not submitted contest picks. All new analyses and numerical proposals are RESEARCH ONLY.',
           '', '## Full card and sportsbook-line baseline','',
           '| Market | N | W-L-P | Hit rate | -110 units | MAE | RMSE | Bias actual-model | Line MAE | Line RMSE |',
           '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in d['weekly']:
        if r['week']=='10':lines.append(f"| {r['market']} | {r['n']} | {record(r)} | {r['hit_rate']:.2%} | {number(r['units_minus110'])} | {number(r['mae'])} | {number(r['rmse'])} | {number(r['bias_actual_minus_prediction'])} | {number(r['locked_line_baseline_mae'])} | {number(r['locked_line_baseline_rmse'])} |")
    lines+=['','Returns risk one unit per selection: win +10/11, loss -1, push zero. The locked-line baseline is a point forecast comparator, not a wager with an invented winning side. Full ATS and totals grades are in week10_ats_audit.csv and week10_totals_audit.csv.',
            '', '## Every frozen cohort','', '| Cohort | N | W-L-P | -110 units |','|---|---:|---|---:|']
    for r in d['frozen_cohorts']:lines.append(f"| {r['cohort']} | {r['n']} | {record(r)} | {number(r['units_minus110'])} |")
    lines+=['','Overlapping cohorts must not be added together. Research ranks 1–5, 6–10 and 11+ are nonoverlapping within each market. Original Top10 equals the first two segments. No historical ordering has been rewritten.','',
            '## Frozen PR50 prospective experiment','',
            '| Candidate | ATS Top5 W-L-P / units | Totals Top5 W-L-P / units | Combined Top5 W-L-P / units |','|---|---|---|---|']
    lookup={r['cohort']:r for r in research['cohorts']}
    for candidate in research['protocol']['candidates']:
        values=[]
        for scope in ('ATS','TOTAL','COMBINED'):
            r=lookup[candidate+':'+scope];values.append('NO SELECTIONS — forecast-only baseline' if not r['bets'] else f"{record(r)} / {number(r['units_minus110'])}")
        lines.append('| '+candidate+' | '+' | '.join(values)+' |')
    lines+=['', 'The controlled-logistic combined Top5 did not improve selection quality in this prospective week. It retained four losing ATS picks and replaced the ATS benchmark’s winning Middle Tennessee pick with a winning Miami–Notre Dame Under: zero unit gain. Its five picks differ entirely from the frozen combined five, but both also finished 1–4. Better retrospective Weeks6–9 results did not establish a stronger Week10 five.',
            '', 'The totals-only EDGE_LOGIT candidate went 4–1; it remains a reported secondary candidate, not a retrospectively selected winning policy. All seven candidates remain in the diagnostics. No candidate is retuned using Week10 outcomes.',
            '', research['caveat'], '',
            '| Primary comparison | Exact shared picks | Unit difference | Jaccard | Leave-one-game-out gain range |',
            '|---|---:|---:|---:|---|']
    for r in research['primary_paired']:lines.append(f"| {r['left']} vs {r['right']} | {len(r['shared'])} | {number(r['unit_difference'])} | {number(r['exact_market_side_jaccard'])} | {r['leave_one_game_out_gain_range']} |")
    lines+=['','One win in five has a Wilson 95% interval of roughly 3.6%–62.4%; the human 0–5 interval is 0%–43.4%. These intervals additionally assume independence that repeated teams/week effects can violate. One prospective week cannot yield a defensible week-cluster improvement interval. No significance, profitability or Confidence3–5 promotion is supported.',
            '', '## Full-card experimental accuracy and probability diagnostics','',
            '| Market | Candidate | W-L-P | Units | MAE | RMSE | AUC | Brier | ECE | 80% coverage | 90% coverage |',
            '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in research['full_card']:
        lines.append(f"| {r['market']} | {r['candidate']} | {record(r)} | {number(r['units_minus110'])} | {number(r['mae'])} | {number(r['rmse'])} | {number(r['auc'])} | {number(r['brier'])} | {number(r['ece'])} | {number(r['interval_coverage']['0.8'])} | {number(r['interval_coverage']['0.9'])} |")
    lines+=['','Fixed probability bins, confidence buckets, interval widths and prior-only exact-pick bootstrap stability are in research_audit.json. Original confidence labels are not calibrated probabilities. The frozen protocol and candidate parameters are retained in that file and the exact PR50 source archive.',
            '', '## Five largest forecast failures','',
            '| Market | Game (away at home) | Final away-home | Projection | Actual target | Absolute error | Process evidence |',
            '|---|---|---|---:|---:|---:|---|']
    for x in findings['largest_five']:
        r=x['selection'];g=x['process'];lines.append(f"| {r['market']} | {r['away']} at {r['home']} | {r['away_score']}-{r['home_score']} | {float(r['raw_projection']):.6f} | {r['actual_model_target']} | {abs(float(r['forecast_error_actual_minus_predicted'])):.6f} | {g['provider_advanced_offensive_plays']} plays; {g['provider_advanced_offensive_drives']} drives; {g['total_yards']} yards; {g['explosive_pass_20_plus']+g['explosive_rush_10_plus']} classified explosives; {g['non_offensive_points_with_bundled_conversions']} non-offensive points |")
    lines+=['','ATS projection is home margin; totals projection is combined points. Large forecast failure is distinct from losing a contest pick: some poor margin forecasts still select the winning underdog. Full ordered misses, observed passers and team efficiency are retained without omitting such cases.',
            '', '## Fundamental logic and review failures','',
            '1. The raw ATS model reduces each matchup to one cumulative EPA differential. The total model has only four cumulative offense/defense EPA levels. QB changes, OL availability, injuries, possessions and explosive-play rates do not directly enter these sealed forecasts. These are demonstrable feature omissions, not a quantified injury explanation.',
            '2. Large model-line gaps are often model errors. Both full-card MAE and RMSE again lose to the locked-line baseline. Research totals Top5 went 1–4 despite its largest estimated advantages. Its model MAE was 26.170 versus the line’s 15.900. Comparing uncalibrated ATS and totals scores does not make a reliable combined ranking.',
            '3. A tempo-only repair is insufficient. Boise State–Colorado State produced 102 points with only 130 provider offensive plays and 23 drives: 1,182 yards, 25 classified explosives and zero non-offensive points. West Virginia–Texas Tech combined both volume and explosive efficiency: 31 drives and 1,220 yards. These are different failure modes.',
            '4. UTSA–FAU reached 89 points with 151 plays, 28 drives, 988 yards and 28 classified explosives, without non-offensive scoring. The human review correctly recognized risk in that Under but did not choose better replacements. Its entire five lost.',
            '5. The controlled ranking did not rescue the strongest five. Its substitution exchanged a winner for a winner and kept four losers. Improved labels or ordering are not demonstrated selection improvement.',
            '', findings['personnel_limit'], '',
            'Scoring classifications use validated scoring sequences. Defensive sack-fumble touchdowns require corroborating ESPN/CFBD IDs, clocks, scoring-team identity, score progression and descriptions. Troy’s zero-yard end-zone recovery is explicitly classified separately; no return distance is fabricated. Play volume is not clock-adjusted tempo; provider drive definitions and explosive-play filters are documented in game_process_evidence.json.',
            '', '## Human review attribution','']
    for r in findings['human_value']:
        lines.append(f"{r['cohort']}: {r['unit_difference']:.6f} units versus the original combined five. Shared picks cancel. Added: "+'; '.join(f"{x['selection']} {x['locked_line']} ({x['result']})" for x in r['added'])+'. Removed: '+'; '.join(f"{x['away']}–{x['home']} {x['selection']} {x['locked_line']} ({x['result']})" for x in r['removed'])+'.')
    lines+=['','## Weeks5–10 comparison','', '| Week | Market | N | W-L-P | Units | Model MAE | Line MAE | Model RMSE | Line RMSE |','|---|---|---:|---|---:|---:|---:|---:|---:|']
    for r in d['weekly']:lines.append(f"| {r['week']} | {r['market']} | {r['n']} | {record(r)} | {number(r['units_minus110'])} | {number(r['mae'])} | {number(r['locked_line_baseline_mae'])} | {number(r['rmse'])} | {number(r['locked_line_baseline_rmse'])} |")
    lines+=['',d['evidence_boundary'],'','AUC and edge/rank discrimination, favorite/underdog, home/away, road favorites, spread/total size, Overs/Unders, confidence and nonoverlapping ranking segments are in the cross-week diagnostic tables. Six-week paired forecast-error uncertainty uses 2,000 seeded week-block resamples; repeated-team and one-season limitations remain.','',
            '## Numerical proposals — RESEARCH ONLY','']
    for r in findings['numeric_candidates']:lines.extend([f"- **{r['name']}**: {r['parameters']} Evidence: {r['evidence']} Validation: {r['requirements']}"])
    lines+=['','No new model, calibrated confidence, v2.9 policy, market substitution or owner approval is authorized by this audit. Keep all unsuccessful candidates for future comparison. The statistical minima are necessary, not sufficient.',
            '', '## Custody, exclusions, CLV and engineering','',
            f"{custody['input_files_verified']} pinned inputs verify. Original historical custody verifies {custody['historical']['input_files_verified']} inputs and {custody['historical']['original_protected_files_verified']} protected artifacts; source database remains {custody['source_database_sha256']} with integrity ok and zero foreign-key violations.",
            '', 'All 62 original SplashSports matchups/spreads/totals reconcile. Five elapsed games were excluded before execution:']
    for r in custody['source_reconciliation']['excluded']:lines.append(f"- {r['away']} at {r['home']}: {r['reason']}; kickoff {r['kickoff_utc']}.")
    lines+=['',custody['source_reconciliation']['evidence_boundary'],'',
            f"CLV INCOMPLETE: {len(clv['observations'])} archived market observations, zero qualified closes. {clv['reason']}",
            '', 'Replay: `python -X utf8 -m scripts.build_week10_formal_audit --verify`. Generation refuses an existing output directory. Exact input/output hash coverage and status contradictions fail closed. Forecasts are read, never regenerated. The existing CI matrix covers Ubuntu/Windows and Python3.11/3.12. Exact source/tested-merge SHAs, actual test outcomes and workflow links belong to the delivery record; this generated report does not invent a future CI success.',
            '', 'No schema or database mutation. New audit modules, evidence, tests and documentation are additive; only scoped byte-preservation rules and existing CI triggers/gates are extended. Rollback abandons/reverts the audit implementation while retaining all source captures and frozen versions. No operational workflow activation or PR merge.', '']
    return '\n'.join(lines)
