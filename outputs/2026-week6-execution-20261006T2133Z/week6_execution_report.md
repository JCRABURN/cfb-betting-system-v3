# Week 6 initial execution — local governed draft

**WEEK 6 MARKET COVERAGE**

Locked games: 58
ATS candidates: 58; ATS skips: 0
Totals candidates: 58; Totals skips: 0
Combined market selections: 116

## Custody and timing

The immutable SplashSports source remains the grading and selection lock. Model generation occurred before every reconciled kickoff. The Hawaii–Arizona State one-hour CFBD schedule discrepancy was corrected only in the isolated database using both teams' official 7:30 p.m. MST schedule; the raw provider capture remains preserved.

## Governed ATS Top 5

All 58 governed ATS Confidence values are 1. The ATS Top 5 is a deterministic policy order and is not strength ranked.

- 1. Southern Miss 10.5 at Troy vs Southern Miss
- 2. Jacksonville State -2.5 at Kennesaw State vs Jacksonville State
- 3. New Mexico State 6.5 at Florida International vs New Mexico State
- 4. Sam Houston 13.5 at Liberty vs Sam Houston
- 5. Missouri State 2.5 at Western Kentucky vs Missouri State

## Mixed-market shadow Top 5

Composition: ATS 0; TOTAL 5. This ranks the stored cross-market shadow candidate score, never raw ATS and total point edges. Its probabilities are not empirically validated; totals are not production eligible.

- 1. TOTAL under 53.5: score 0.7197; Confidence 4
- 2. TOTAL over 47.5: score 0.7151; Confidence 4
- 3. TOTAL under 59.5: score 0.6740; Confidence 3
- 4. TOTAL under 61.5: score 0.6725; Confidence 3
- 5. TOTAL over 46.5: score 0.6619; Confidence 3

## Context limitations

ESPN displayed DraftKings spread and total for 57/58 games. The direct Odds API endpoint was unavailable. ESPN does not provide an observation timestamp for each displayed line, so the retrieval timestamp is the only freshness bound. Market lines never replace SplashSports locks.
Open-Meteo kickoff-hour forecasts were captured for 56 games; the other two are domes or have explicit status. All QB starts remain unverified. The ESPN injury feed returned 3 team groups; absence of a record does not mean healthy.
No manual, coaching, travel, injury, or weather point adjustments were made.
Week 5 shadow totals finished 23-33, while the Week 5 ATS card finished 34-22. Those results are review context, not a new policy.

## Owner review

The five decision shortlist rows are human review options and are not sportsbook recommendations. The analytical ATS and totals shortlists are separate from governed and mixed Top 5. All reported market, QB, injury, and weather gaps remain visible in the CSVs.
