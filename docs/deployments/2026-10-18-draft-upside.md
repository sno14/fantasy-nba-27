# Draft upside, playoff schedules and refreshed ADP — October 18, 2026

The approved draft-context release covers the public static board and the local
React/FastAPI app. Existing production, availability and rankings are preserved.
This is a scoped publication of public artifacts; unrelated local changes and
private analyst research are excluded.

Product tracker:

- [x] Screen all top 200 by availability Draft #, plus Leonard Miller.
- [x] Add Breakout potential, Opportunity flyer, Recovery bet and Established
  role profiles, with a path, obstacle and already-priced workload.
- [x] Add 35 conditional FP/G scenarios with explicit minutes/rate arithmetic,
  target pick ranges and earliest-pick limits; three additional price-only cases.
- [x] Show scheduled playoff matchup games and detail for back-to-back second
  nights and light NBA days. Expected player appearances remain in Risk view.
- [x] Refresh ESPN platform ADP: 574 unique matches; every top-200 player covered.
  Provider observations October 17 UTC; retrieved October 18 Sydney.
- [x] Use availability Draft # for the market price signal, independently of
  the upside profile. No legacy safe-rank comparison drives the new signal.
- [x] Deliver details and filters in both boards and draft rooms, including
  mobile cards and the updated top-200 CSV.
- [x] Keep Aday Mara on a separate final-round watchlist without fabricated FP/G.
- [x] Verify all 599 preexisting non-market fields unchanged; A/B snapshots and
  availability overlay remain byte-identical. Preserve existing mock picks.
- [x] Pass 60 focused Python tests, production frontend build, history/rotation/
  minutes validators, static JS syntax and read-only desktop/mobile checks.

Conditional upside cases are editorial favorable outcomes, not calibrated
percentiles or new projections. Pick limits are judgment, not an assurance of
availability. Competing teammates' scenarios need not be jointly achievable.
Playoff totals refer to February 1–14, February 15–March 7 and March 8–21, 2027.
No second playoff adjustment is applied to Effective FP/G or Draft #.

The user-supplied episode was accessible only through metadata and indexed
excerpts. Nine private fact notes and a no-change/defer ledger were recorded;
no central analyst changes were proposed or promoted. Incremental transactions
refreshed through October 14; the feed still lags draft day. No team edits were
invented. The projection workflow hold and live ESPN latency retest remain open.

Skeptic pass: selection used the existing draft order plus specifically raised
names, never realized outcomes. This is prospective, deterministic judgment with
no refit, seed search, accuracy claim or retry of rejected models. Preseason
shooting and incomplete rotations cannot alone establish a permanent increase.

Public board SHA-256:
`55145606473578b72a3758d13f5fad69144187fac6742b6124b84d02caef4819`.
Availability overlay SHA-256 remains:
`f9d57d16c7c695b6ee91df8564fe81a686f7aefe2fc4fadbfb212c2f3a243a75`.

Public: https://sno14.github.io/fantasy-nba-27/ . Local app:
http://127.0.0.1:8787/ . Static preview: http://127.0.0.1:8788/ .
Publication is complete only after the Pages workflow and live artifact checks
pass. The private deployment evidence records the released commit and result.
