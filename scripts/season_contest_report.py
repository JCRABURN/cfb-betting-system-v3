"""Season narrative generated from the reconciled ledger, never hand-edited grades."""
from scripts.week11_audit_report import table


def report(s):
    total=s['total']
    text=['# Actual v3 contest performance — Weeks 1–10','',
          f"**{total['wins']}–{total['losses']}–{total['pushes']}; {total['weighted_points']}/{total['possible_points']} weighted points; {total['units_minus110']:.6f} hypothetical -110 units; {100*total['roi']:.2f}% ROI.**",'',
          'The owner confirmed the later PR #54 attribution correction in this audit task. The 50 Weeks 1–10 submissions are owner-attested v3 model selections. Week 11’s five are retained as external-origin historical source records, without grading, head-to-head comparison, or inclusion in v3 performance. No other model or repository was inspected.', '',
          table(s['weekly'],[('week','Week'),('n','Picks'),('wins','W'),('losses','L'),('pushes','P'),('weighted_points','Points /15'),('units_minus110','Units'),('cumulative_weighted_points','Cumulative points'),('cumulative_units_minus110','Cumulative units')]),'',
          table(s['by_market'],[('market','Market'),('n','Picks'),('wins','W'),('losses','L'),('pushes','P'),('weighted_points','Points'),('possible_points','Available points'),('units_minus110','Units')]),'',
          table(s['weights'],[('contest_weight','Weight'),('n','Picks'),('wins','W'),('losses','L'),('pushes','P'),('weighted_points','Points'),('possible_points','Available points'),('units_minus110','Units')]),'',
          'Weights allocate contest points. They are not probability estimates, model Confidence 1–5, or independent evidence of calibration. Units risk one to win 10/11; they are hypothetical, not a sportsbook recommendation or wager record. No push occurred, so no unverified contest push-points rule affects the result.', '',
          '## Exact weekly selections','']
    for week in range(1,11):
        text += [f'### Week {week}','',table([r for r in s['ledger'] if r['week']==week],
                  [('away','Away'),('home','Home'),('market','Market'),('selection','Selection'),('contest_line','Line'),('contest_weight','Weight'),
                   ('away_score','Away score'),('home_score','Home score'),('grading_margin','Margin'),('result','Grade'),('weighted_points','Points'),
                   ('units_minus110','Units'),('exact_recommendation_cohorts','Exact recommendation matches')]),'']
    text += ['## Corrections and provenance','',
             '- Week 4: all 58 matchups independently reconcile; the submitted five verify at 3–2 and 8/15. Owner attestation establishes model-selected origin; full-card model predictions and original forecast timestamps remain unrecovered.',
             '- Week 5: Texas Tech −13.5, weight 1, is the fifth submitted selection. Delaware +7.5 remains the fifth contextual shortlist recommendation. Both records and their independent grades are preserved.',
             '- Week 7: all five selections and exact lines match the corrected approval artifact. Displayed weights remain separate from the approval artifact’s ordinal confidence.',
             '- Week 11 divergence: the later owner attestation explicitly records a switch to an external model because of dissatisfaction with v3’s low-confidence recommendations. The owner did not independently choose the games. That resolves the claimed unexplained v3 intervening card; no later v3 decision artifact was identified in the merged repository or archived timestamped reviews. External artifacts are outside the owner-confirmed scope.',
             '- The PDF exports were printed November 16. They establish recovered contest entries, not original forecast timestamps, pregame custody, or full-board model outputs. Original ZIP/PDF hashes, page numbers, raw names and displayed lines are retained from PR #54. The original binaries are not available locally for a new extraction or visual inspection.',
             '- CSV source hashes are verified against the original LF Git blobs, with only Git’s documented CRLF checkout conversion normalized. Earlier frozen forecasts and input lines are never overwritten.', '',
             '## Recommendation differences','',
             'The complete difference ledger contains exact matches, same-selection line differences, recommended-but-not-submitted selections, and submissions absent from each recovered cohort. Matchup joins use the canonical resolver and official provider IDs; early synthetic IDs are reconciled through the original matchup. Weeks 1–3 coverage and ranking qualifications remain explicit. Week 4 has submission evidence only. A full-board match does not prove that the specific ranking or contextual layer produced the submission.', '',
             'Each recommendation cohort is evaluated separately. A corresponding submission and recommendation are not pooled as two independent picks. There is no cumulative sum across overlapping methods, revisions, or confidence labels.', '',
             '## Locked lines and kickoff displays','',
             table([r for r in s['locks'] if r['status']!='LINES_MATCH'],[('week','Week'),('away','Away'),('home','Home'),('frozen_home_spread','Original home spread'),('export_home_spread','Export home spread'),('frozen_total','Original total'),('export_total','Export total'),('status','Status'),('source_path','Frozen source')]),'',
             'Missing early totals are explicitly unavailable, not differences assumed to be zero. Every historical input version remains separately identified; repeated discrepancies across source versions are not additional games.', '',
             table(s['kickoff_differences'],[('away','Away'),('home','Home'),('original_display','Earlier display'),('export_display','Export display'),('custody_effect','Effect')]),'',
             'The nine display changes include Ole Miss–Oklahoma moving to Sunday in the export. All original eligibility snapshots, timestamps and late-seal qualifications stay frozen. Later schedule displays never create retrospective pregame custody.', '',
             '## Evidence limits and conclusions','',
             'Actual submitted performance is poor: 40% wins and 55/150 points over 50 picks. Weeks 8–9 improved temporarily before the 0–5 Week 10 card. This short, selected sample does not demonstrate improvement, profitability, or a stable relationship between contest weight and success. The workbook retains every week, including losing weeks.',
             'Provider captures contain 621 accepted contest matches, zero unresolved contest identities and zero cross-provider score conflicts. Non-contest games in the broad provider responses are retained as raw evidence and do not enter the ledger. No database mutation, historical forecast regeneration, production policy promotion or external-model assessment occurred.', '']
    return '\n'.join(text)
