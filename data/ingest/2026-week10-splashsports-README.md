# 2026 Week 10 — SplashSports screenshot staging

Received Wednesday November 4, 2026 across **9 screenshots**.

- **62 unique games** with a signed spread on both teams and an O/U total.
- **2 Tuesday Nov 3 finals** (Ohio 28–20 Akron, Buffalo 34–31 Miami OH) excluded from prospective forecasts.
- **60 screenshot-marked upcoming games** from Nov 4–7; re-check kickoff eligibility at actual model execution time.
- **All screenshot spread/total values are preserved here as staged source, not independently timestamp-qualified Tuesday-market locks.**
- Screenshot time display has no verified timezone. Original screenshot image bytes are not in this branch and must not be asserted archived.
- Source file shape matches Week 9: `date,away_team,home_team,away_spread,home_spread,total,status,final_away,final_home,source`.
- Aliases are normalized in CSV; verify against screenshots + canonical team IDs before promoting an immutable lock.
- This is *capture-only*. No model has been executed, no line is frozen by a model seal yet, no Top 5 created. No policy, Week 9 audit, historical data or database changed.
- User requires full ATS and totals board with Confidence 1–5 for all eligible games, and separately labeled governed/research and combined Top 5. Do not assume uncalibrated totals and ATS scores are comparable.
- Do not allow Wednesday-Friday results to contaminate any game whose pregame model cutoff precedes those results; full card sealed after first kickoff cannot be represented as pregame.
