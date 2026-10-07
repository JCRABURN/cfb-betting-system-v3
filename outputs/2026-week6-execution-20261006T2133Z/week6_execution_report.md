# Week 6 initial execution — local governed draft

**WEEK 6 MARKET COVERAGE**

Locked games: 58
ATS candidates: 58; ATS skips: 0
Totals candidates: 58; Totals skips: 0
Combined market selections: 116

## Custody and timing

Authoritative locked-line domain snapshot SHA-256: `f2723f75d94c2c3e4edaadf618cbb71866f3cf2d8b59c62fe48ab84bad6c2c75`. This is the committed execution-v9 lock custody hash; the earlier execution-v8 timestamp-specific hash is not the card's hash. The SplashSports source remains the immutable grading and selection lock. Model generation preceded every reconciled kickoff; this review used only the sealed pregame files. The one-hour Hawai'i–Arizona State CFBD schedule discrepancy was corrected only in the isolated execution database using both teams' official 7:30 p.m. MST schedules; the raw provider capture was retained and the locked spread and total were unchanged.

## OFFICIAL GOVERNED ATS TOP 5

The 58 governed ATS Confidence values are all 1. This Top 5 is deterministic policy order, not a strength ranking.

- 1. Southern Miss 10.5 — Southern Miss at Troy
- 2. Jacksonville State -2.5 — Jacksonville State at Kennesaw State
- 3. New Mexico State 6.5 — New Mexico State at Florida International
- 4. Sam Houston 13.5 — Sam Houston at Liberty
- 5. Missouri State 2.5 — Missouri State at Western Kentucky

## MIXED-MARKET SHADOW TOP 5 — SCALE-LIMITED RESEARCH ORDERING

SHADOW SCORE ORDERING WITH CROSS-MARKET SCALE LIMITATION. Research only; unchanged 0 ATS / 5 TOTAL composition. Stored scores order the 116 frozen candidates, but they are not validated cross-market probabilities or overall confidence. ATS policy caps selected probability at 0.60; TOTAL scores use UNCALIBRATED_NORMAL_SHADOW. Week 5 ATS was 34-22 and shadow totals were 23-33.

- 1. UCF at Oklahoma State: under 53.5 (stored score 0.7197)
- 2. Tulane at Army: over 47.5 (stored score 0.7151)
- 3. UCLA at Oregon: under 59.5 (stored score 0.6740)
- 4. Arizona at West Virginia: under 61.5 (stored score 0.6725)
- 5. Central Michigan at Ohio: over 46.5 (stored score 0.6619)

## CROSS-MARKET SCORE SCALE DIAGNOSTIC

ATS 58: minimum 0.5007, median 0.5197, maximum 0.5896.
TOTAL 58: minimum 0.5040, median 0.5749, maximum 0.7197.
TOTAL scores above the best ATS score: 25. This distribution reflects different, unvalidated market score scales, not evidence that 25 totals are stronger than every ATS side.

## WEEK 6 DECISION SHORTLIST — ADVERSARIAL HUMAN REVIEW

Five separate qualitative owner-review options from the frozen analytical shortlists. This is neither the mixed score order nor a sportsbook recommendation; ranks are review order, not model strength.

- 1. ATS Vanderbilt 10.5 — Ole Miss at Vanderbilt; Four prior FBS games per team and no prior 35-point blowout make this large raw ATS edge less sample-fragile than the higher-scoring Ball State and Massachusetts ATS options. The locked Vanderbilt +10.5 is half a point better than the captured current +10.0. Week 5 ATS was 34-22. This ATS review option displaces higher-scoring totals because their uncalibrated normal scores cannot be compared as validated probabilities with ATS scores. Primary failure mode: Ole Miss offense exceeds the unadjusted margin forecast; QB and injury status remain unverified, and Vanderbilt has prior FCS exposure.
- 2. TOTAL under 53.5 — UCF at Oklahoma State; The frozen projection is 9.74 points below the locked 53.5, and the lock is one point better for the Under than the captured 52.5. It survives review despite Week 5 shadow totals at 23-33, unvalidated normal probability, 16.73-point uncertainty, and unverified QB starts because both the raw gap and observed lock advantage are explicit in the pre-kickoff evidence; it remains a shadow review option only. Primary failure mode: Offensive pace or unverified QB/injury conditions defeat the Under; one team has only three prior FBS games and both have prior blowout exposure.
- 3. TOTAL over 47.5 — Tulane at Army; The frozen projection is 9.51 points above the locked 47.5, and the lock is one point better for the Over than the captured 48.5. It survives review despite Week 5 shadow totals at 23-33, unvalidated normal probability, 16.73-point uncertainty, and unverified QB starts because the raw gap and observed lock advantage are recorded separately; no production eligibility is inferred. Primary failure mode: Army pace or unverified QB/injury conditions suppress scoring; one team has only three prior FBS games and there is prior FCS/blowout exposure.
- 4. TOTAL under 55.5 — San Diego State at Oregon State; The locked Under 55.5 is two points better than the captured 53.5 and both teams have four prior FBS games. This market evidence gives it a distinct review case despite a lower stored score than the mixed Top 5. Week 5 shadow totals were 23-33; the normal score is unvalidated, uncertainty is 16.73 points, and QB starts are unverified, so this is only an owner review option. Primary failure mode: The projected 5.76-point Under gap is smaller than the model's uncertainty; unverified QB/injury conditions and prior FCS/blowout exposure could erase it.
- 5. ATS Stanford 37.5 — Stanford at Notre Dame; Five prior FBS games per team and no prior FCS exposure provide a more inspectable ATS sample than several higher-scoring ATS options. The frozen raw edge is 12.30 points. Week 5 ATS was 34-22. This ATS review option displaces higher-scoring totals because their uncalibrated normal scores have no validated common scale with ATS; the captured market is one point better than the lock, which limits the case. Primary failure mode: The 37.5-point spread is exposed to blowout-tail error, both teams have prior 35-point blowouts, QB/injury status is unverified, and current market movement is against the lock.

## Context limitations

ESPN displayed DraftKings spread and total for 57/58 games; the direct Odds API endpoint was unavailable. ESPN does not supply per-line observation timestamps, so retrieval time is the only freshness bound. These observations never replace SplashSports locks. Open-Meteo kickoff-hour forecasts were captured for 56 games; the other two are domes or have explicit status. QB starters remain unverified. The ESPN injury feed returned three team groups; absent records do not establish health. Weather and market observations are the frozen Oct 6 captures. No manual, coaching, travel, injury, or weather point adjustment, model change, or policy change was made.
