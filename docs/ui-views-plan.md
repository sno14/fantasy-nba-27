# UI views build plan — the six manager views (V1–V6)

Status: **the execution spec for the web-app view build-out** (started 2026-07-16, user
decision same day: build all six). Product work — **no EXPERIMENTS.md entries** (Appendix-B
rule: the ledger records model experiments; these views render already-adopted outputs).
Work from this file exactly like `docs/implementation-plan.md`: specs are binding, the
tracker below is the hand-off state between sessions, and each landed view updates its row
**in the same commit**. README "Web app" + the ROADMAP Stage-5 web-app bullet get one line
per shipped view, same commit.

**Why these six (session 2026-07-16, user-approved):** the system already computes the
signals a manager needs in-season — nightly ROS snapshots, market archives, the naive-vs-asof
disagreement, OUT-redistribution, the schedule pull — but the UI only shows single-date
state. V1–V6 surface the *deltas, disagreements and rosters*: catching risers early is the
project's stated #1 in-season job, and the trade/waiver/lineup decisions are where a
projection edge converts to wins.

## Hard constraints (inherited — do not relax)

1. **Descriptive, never prescriptive win-probability.** The H2H variance layer (19.4) was
   descoped: `SD_PG=9` is season-total-calibrated and must never become a per-game/weekly
   sigma. V5 (Matchup) shows FP/G × games sums and day grids — **no win %, no sim**. If a
   future session is tempted, read implementation-plan 19.4 first.
2. **Remote sessions have no real data** (`data/raw`/`data/processed` are local-only;
   stats.nba.com blocked). Every view must run on `scripts/dev_fixtures.py` output and
   **degrade honestly** on missing inputs (the Weekly tab's "schedule publishes ~mid-August"
   pattern): say what's missing and which command/date fills it, never fake it.
3. **Same code paths as the CLI** where one exists (house rule from the first web-app
   commit). Market joins use `models.analyst.name_key`; roster/slot logic reuses
   `api/draft.py` helpers; no reimplementations that can drift.
4. **In-season data lights up on the standing calendar** — nightly `ros_board/` snapshots
   start at the opening-night cron; market re-pulls Sept; schedule ~mid-Aug. Views must be
   useful the day they ship (fixtures) and the day the real data arrives (empty states).

## Progress tracker  ← update in the same commit as the work

| View | What | Backend | Frontend | Tests | Shipped |
|---|---|---|---|---|---|
| A | Shared foundations: `api/season.py` router + trend/market loaders + fixture extension + nav sections | ☑ | ☑ (nav) | ☑ | ☑ 2026-07-16 |
| V1 | Trends — risers & fallers from the ros_board archive | ☑ | ☑ | ☑ | ☑ 2026-07-16 |
| V6 | Schedule strength — playoff-week games + B2B per NBA team | ☑ | ☑ | ☑ | ☑ 2026-07-16 |
| V2 | Trade targets — buy-low / sell-high disagreement finder | ☑ | ☑ | ☑ | ☑ 2026-07-16 |
| V3 | Waiver wire — unrostered pool × this-week games × opportunity | ☑ | ☑ | ☑ | ☑ 2026-07-16 |
| V4 | My Team — roster dashboard | ☑ | ☑ | ☑ (shared helpers) | ☑ 2026-07-16 |
| V5 | Matchup planner — descriptive H2H week totals | ☑ | ☑ | ☑ (shared helpers) | ☑ 2026-07-16 |
| V3b | Live ESPN rosters — in-season ownership from `mRoster` | ☑ | ☑ | ☑ | ☑ 2026-07-17 |

Build order: **A → V1 → V6 → V2 → V3 → V4 → V5.** V3–V5 share the ownership helper (§A.4)
which ships with A; V4/V5 reuse V3's week-games join; V5 reuses V4's per-roster totals.

## Session hand-off notes (append, dated, newest first)

- **2026-07-17 (session 4): V3b live ESPN rosters shipped.** `EspnPollFeed.league_rosters()`
  reads the `mRoster` view → `{team_id: [espn_id]}` (pure `feed.parse_rosters()`, robust to
  the entry-level `playerId` and nested `playerPoolEntry.player.id` shapes, drops `<=0`
  placeholders, keeps non-contiguous team ids — pinned by three fixture tests). The API stores
  live rosters on the session (`live_rosters`, persisted, str↔int key round-trip) and
  `current_rosters()` **prefers them** over the pick-derived rosters when present, via a
  synthetic-pick `_live_state()` that reuses every roster/positions/unfilled derivation — so
  every season view (Waivers/My Team/Matchup/Trades) follows in-season adds/drops with no
  per-view change. New endpoints `POST /api/draft/rosters/{refresh,clear}` (refresh never
  raises — a stalled/unauthorized poll surfaces `espn_error`; an **empty** `mRoster` does NOT
  overwrite pick ownership, so a pre-draft click can't wipe a simulated draft). Every
  ownership response now carries `roster_source` + `rosters_asof`. Frontend: a "↻ ESPN rosters"
  button + "use picks" revert on Waivers (invalidates the four season caches, then reloads),
  and a "live ESPN rosters" chip on My Team/Matchup. **Verified against the real league
  (507458037):** the live `mRoster` call succeeds and parses empty (undrafted → `n_rostered:0`,
  the honest fallback), and the override/persist/clear paths are covered by two API tests.
  Suite 156 green, tsc + build clean. This closes the last open item in this plan.

- **2026-07-16 (session 3): draft-session persistence.** User question exposed that the
  room's Session (my_team_id, source, manual picks, Connect snapshot) was in-memory only
  — every relaunch forgot "my team" and a manual draft. Now persisted to
  `data/processed/draft_session.json` (`_save_session()` on every mutating endpoint incl.
  simulate; `_load_session()` at import; corrupt/missing file → fresh session, never a
  crash). Verified by an actual server restart (team id + 130 picks survive; /api/myteam
  populates immediately). Reset clears picks but keeps my_team_id/source. The persisted
  pick order is only as fresh as the last Connect — `order_is_placeholder` travels with
  it; the mid-Oct 19.1b live re-read rule is unchanged (README "Draft room" documents
  this). Suite 144 green.

- **2026-07-16 (session 2, close-out): ALL SIX VIEWS SHIPPED.** V4/V5 done via the
  shared `_roster_week_rows()` / `_day_grid()` core in `season.py` (ROS snapshot numbers
  + board ranges/risk/chronic + availability-aware week games); `current_rosters()` now
  also carries per-player positions, per-team `unfilled` slots, and `has_positions`, so
  the slot math stays owned by `api/draft.py`. Distinct empty states for "no picks" vs
  "picks but my-team unset" (my_team_id defaults to 0 — set it in the Draft Room; the
  smoke path is POST /api/draft/config?my_team_id=3 → /api/draft/simulate). Suite 142
  green (the earlier note's "146" was a miscount), build + tsc clean, every view driven
  in the browser. Remaining named follow-up: **V3b** (live ESPN rosters) — nothing else
  is open in this plan.

- **2026-07-16 (session 2, this branch, later):** V3 shipped too (suite 146 green;
  built + driven in the browser; ownership verified via /api/draft/simulate then reset).
  Two V3 learnings that bind V4/V5: (1) the real `status_override` note format is
  `out_until:YYYY-MM-DD` / `out_for_season` (models/asof.py) — the fixture now matches,
  and `games_while_active()` in `season.py` drops the week games a flagged-out player
  misses (V4/V5 weekly totals MUST reuse it); (2) `week_games_by_team()` +
  `default_week()` exist in `season.py` — don't re-derive the week join. Next: §V4 then
  §V5.
- **2026-07-16 (session 2, this branch):** A + V1 + V6 + V2 built and verified (pytest
  suite green incl. new `tests/test_season_api.py`; `npm run build` + `tsc` clean; driven
  against the fixture cache). V3 is next: everything it needs already exists —
  `current_rosters()` in `api/draft.py`, `week_games_by_team()` in `api/season.py`,
  fixture ros_board carries `redist_mpg`. Follow §V3 verbatim, then §V4, §V5.

## A — Shared foundations

**A.1 New router `src/fantasy_nba/api/season.py`** (register in `app.py` like the draft
router, before the SPA mount): all V1–V5 endpoints + V6. Keep `app.py` untouched beyond
`app.include_router(season_router)`.

**A.2 ROS-archive helpers (in `season.py`):**
```python
def ros_dates() -> list[str]                      # sorted snapshot dates (PROCESSED_DIR/ros_board)
def load_ros(date: str) -> pd.DataFrame           # one snapshot (validated date, 404 on miss)
def baseline_date(dates, latest, window_days)     # newest date <= latest - window (else oldest)
def trend_frame(window_days: int) -> dict         # latest vs baseline join on PLAYER_ID:
    # rank, rank_delta (= baseline_rank - rank; positive = riser), fpts_pg, fpts_delta,
    # mpg, mpg_delta, status_override, + spark: trailing per-date [date, fpts_pg, rank]
    # capped at the last 30 snapshots, players capped at current-rank top 250.
```
Deltas are **snapshot-vs-snapshot** (the nightly board already contains the model's full
knowledge per date) — never recompute projections here.

**A.3 Market loader (in `season.py`):** `latest_market(source="hashtag") -> (date, df) |
(None, empty)` from `RAW_DIR/market/<source>_<date>.parquet` (the `pull_market.py`
archive; schema `consensus_rank, player, team, pos, consensus_value, adp`). Join to boards
via `models.analyst.name_key` on `player` — the same normalization family the analyst layer
uses; unmatched names drop out silently (rookie tails are expected misses).

**A.4 Ownership helper — `current_rosters()` in `api/draft.py` (public, next to
`_state()`):** returns `{"my_team_id", "rosters": {team_id: [nba_player_ids]}, "n_picks",
"source"}` from the live draft session (manual or ESPN picks; simulate fills it too). This
is the **post-draft** ownership source V2–V5 use. *In-season live rosters (adds/drops) now
override the picks when pulled — V3b, shipped 2026-07-17; `current_rosters()` also returns
`roster_source`/`rosters_asof` to say which source is active.*

**A.5 Fixture extension (`scripts/dev_fixtures.py`):** the two ros_board snapshots become
**twelve** (2027-01-04 … 2027-01-15, daily), generated with a persistent per-player level
plus **engineered movers** — ~8 risers ramping +3…+8 fpts_pg across the window, ~8 fallers
mirroring, everyone else drifting ±noise — so V1/V2 demonstrably work. `naive_fpts_pg` =
level + extra weight on the last days' move (so hot streaks show naive>model, the V2
sell-high signal). Keep `redist_mpg` on ~6 rows (feeds V3). Add a market fixture:
`data/raw/market/hashtag_2026-12-28.parquet` in the §A.3 schema, ranks = a noisy re-rank of
the board **with ~10 deliberate big gaps** (market much lower/higher than us) so V2 has
buy-low/sell-high rows. Real names must go through the same generator as the board so joins
hit.

**A.6 Nav sections (`frontend/src/App.tsx`):** the sidebar grows to 15 links — group it.
`NAV` entries gain `section: "Draft" | "Season" | "Research"`; render section labels.
Draft = Draft Board, Draft Room, Power Rankings. Season = ROS, Trends, Trades, Waivers,
My Team, Matchup, Weekly. Research = Players, Compare, Analyst, Schedule, Data.

**A.7 Tests (`tests/test_season_api.py`):** pure-function unit tests on tiny hand-built
frames (house style — no cache dependency): `baseline_date` window arithmetic;
`trend_frame` delta signs (a riser gets positive `rank_delta` and `fpts_delta`); market
join hits on an accented name (`Dončić`); V6 B2B counting; V2 signal signs (§V2). Endpoint
smoke tests only where they don't need the full cache.

## V1 — Trends (risers & fallers)   `/trends`

**Job:** catch movers early — the first view a manager opens in-season. Day-over-day the
nightly archive already encodes everything the model learned; this view is the diff.

**API `GET /api/trends?window=14`** (window ∈ {7, 14, 30}):
```
{ has_history: bool,            // false until >= 2 snapshots (empty state names the cron)
  latest, baseline: "YYYY-MM-DD", n_snapshots,
  rows: [{ PLAYER_ID, PLAYER_NAME, TEAM_ABBREVIATION, rank, rank_delta, fpts_pg,
           fpts_delta, mpg, mpg_delta, status_override, spark: [[date, fpts_pg, rank]] }] }
```
`rank_delta = baseline_rank − rank` (positive = riser). Players present in only one of the
two snapshots are dropped (no fake zero-deltas).

**Frontend `views/Trends.tsx`:** window Segmented (7d/14d/30d) · Risers/Fallers/All
Segmented (filter on sign of `fpts_delta`) · search + team filter + topN like Weekly ·
DataTable sorted by |fpts_delta| desc with signed delta chips (green/red), an inline
**sparkline** cell (new `Sparkline` in `components/charts.tsx`: tiny SVG polyline of
`spark` fpts values, ~110×26), MPG delta column (minutes moves lead FP moves — the
mechanism column), status chip when `status_override` set. Row click → `/players/:id`.
Empty state: "Trends need ≥2 nightly snapshots — `update_daily.py` crons from opening
night" (+ fixture badge covers dev).

## V6 — Schedule strength   `/schedule`

**Job:** which NBA teams play the most when it matters — fantasy playoff weeks (draft
tiebreak + trade-deadline tool) — plus per-week volume and B2B load.

**API `GET /api/schedule-strength?target=`**:
```
{ has_schedule, target, playoff_weeks: [19,20,21],   // from league.yaml fantasy_playoff_weeks
  playoff_weeks_confirmed: false,                    // stays false while league.yaml carries the
                                                     // placeholder — UI shows the caveat
  weeks: [{week, week_name, start, end}],
  teams: [{ team, total_games, b2b, playoff_games, by_week: {week: n} }] }
```
B2B = pairs of consecutive calendar dates per team. `playoff_weeks_confirmed` keys off a
`fantasy_playoff_weeks_confirmed: true` line the user adds to `league.yaml` once the ESPN
matchup calendar lands (mid-Aug calendar item) — until then the view banners "placeholder
playoff weeks".

**Frontend `views/Schedule.tsx`:** one heat-mapped table — teams × weeks, cell = games that
week (0–4 shaded), playoff-week columns highlighted, sortable summary columns (total, B2B,
playoff games; default sort = playoff games desc). Same empty state as Weekly when no
schedule is cached.

## V2 — Trade targets (buy low / sell high)   `/trades`

**Job:** a *disagreement finder*, not advice (EXP-017's framing): where our valuation
diverges from (a) the market consensus — what leaguemates likely believe, i.e. the trade
price — and (b) the naive recency-chaser — what a hot/cold streak looks like without a
model. Both gaps already exist in the repo (market_report.py CLI; naive columns on every
snapshot); this joins them per player with the V1 trend.

**Signals (all shown; no opaque composite score — house honesty rule):**
- `market_gap = consensus_rank − rank` (positive = we're higher on him than the market →
  **buy low**; negative → the market pays more than we think he's worth → **sell high**).
- `heat_gap = rank − naive_rank` (positive = the naive updater ranks him better than the
  model → hot streak the model discounts → sell-high signal; negative = cold streak the
  model looks through → buy-low signal). Preseason (no snapshots) this is null.
- `fpts_delta_14` from V1 (context column, null preseason).

**API `GET /api/trade-targets`**: base = latest ROS snapshot when one exists, else the
current draft board (preseason mode). Returns `{ mode: "ros"|"preseason", market_date,
has_market, has_naive, rows: [{ …ids/team, rank, fpts_pg, consensus_rank, market_gap,
naive_rank, heat_gap, fpts_delta_14, risk, rostered_by, is_mine }] }` for the top ~200.
`rostered_by`/`is_mine` from `current_rosters()` (null when no picks yet) — buy-low rows
are actionable when *someone else* rosters him; sell-high when *I* do.

**Frontend `views/Trades.tsx`:** Buy low / Sell high Segmented → filters rows on
`market_gap` sign (fallback `heat_gap` when no market pull), sorted by |gap| desc; columns:
our rank vs market rank with a gap chip, heat chip ("hot +12" / "cold −9"), 14d trend,
risk meter, owner chip ("mine" highlighted). Banner states name the missing input
(`pull_market.py` for market, nightly cron for naive/trend) — the view still renders with
whichever signals exist.

## V3 — Waiver wire   `/waivers`

**Job:** the in-season pickup list: best *available* players by ROS value × games this
week, with the opportunity signal (who benefits from current OUTs) attached.

**API `GET /api/waivers?week=`**: pool = latest ROS snapshot (else board) **minus all
rostered ids** from `current_rosters()`; when there are no picks at all, `ownership: false`
and the pool is everyone (banner: "connect/draft to mark rostered players").
Per row: ids/team, rank, fpts_pg, `n_games`/`weekly_fpts` for the chosen week (reuse the
`/api/weekly` join — extract its by-team week-games map into a shared
`week_games_by_team(target, week)` helper in `season.py` rather than duplicating),
`redist_mpg` (positive = inheriting minutes from an OUT teammate **right now** — the
EXP-030 layer as a pickup flag), `breakout_p` when the draft sheet carries it,
`status_override`, `fpts_delta_14` (V1 join — rising FAs first).
Default sort: `weekly_fpts` desc. `week` defaults to the first schedule week ≥ the latest
snapshot date (else the first week).

**Frontend `views/Waivers.tsx`:** week Select (reuse Weekly's `/api/weeks` pattern) ·
search/team/topN · chips: "＋4.1 MPG (redist)" when `redist_mpg > 0.5`, breakout %, OUT
status, 14d trend arrows. Banner when `ownership: false`.

**V3b (SHIPPED 2026-07-17):** live ESPN rosters — `EspnPollFeed.league_rosters()` reads the
`mRoster` view → `{team_id: [espn_ids]}` (pure `feed.parse_rosters()`, pinned by fixture
tests same as 19.1's payload traps), stored on the session and mapped to nba ids via the
cached player map. `current_rosters()` **prefers live rosters over the draft picks** when
present (a synthetic-pick `_live_state()` reuses the roster/slot logic), so all of V2–V5
follow in-season adds/drops. `POST /api/draft/rosters/refresh` (button on Waivers) /
`…/clear` (revert). Never overwrites pick ownership with an empty `mRoster` (pre-draft
safety). Uses the cookie auth already in `.env`. See the 2026-07-17 hand-off note.

## V4 — My Team   `/myteam`

**Job:** the daily home page: my roster's health, this week's volume, and who's trending
which way — the "do I need to act today?" view.

**API `GET /api/myteam?week=`**: my ids from `current_rosters()` (404-with-message when
empty → UI offers Draft Room / Simulate). Per player: board/ROS row (rank, fpts_pg,
floor/median/ceiling, risk, chronic flag), `status_override`, `fpts_delta_14` + spark (V1),
`n_games`/`weekly_fpts` (V3's helper), positions (draft map when cached). Team block:
weekly total, per-day game counts vs the 10 startable slots (Weekly's `DAILY_SLOTS`
convention), count of OUT players, `unfilled` slots via the draft room's seat logic
(reuse `_roster_panel`'s pieces from `api/draft.py` — refactor, don't copy).

**Frontend `views/MyTeam.tsx`:** roster DataTable (sparkline, range strip, risk meter,
status/trend chips) + a summary card row (weekly FP, games by day mini-grid, OUT count,
unfilled slots) + quick links (player page, Trades filtered to mine, Waivers for the same
week).

## V5 — Matchup planner   `/matchup`

**Job:** my week vs an opponent's week, descriptively: projected totals from FP/G × games
and the day-by-day collision grid. **No win probability** (constraint #1).

**API `GET /api/matchup?week=&opp=`**: both rosters from `current_rosters()` (`opp`
defaults to the first non-me team with players). Per side: V4's per-player weekly rows +
`total_weekly_fpts`, per-day `{date: games}` capped at `DAILY_SLOTS` starts (surplus shown
as "benched games" — games you can't start). Also `gap = my_total − opp_total` and each
side's day-grid so the UI can show *where* the week is won on volume.

**Frontend `views/Matchup.tsx`:** opponent Select (team ids from the draft session, "Team
3 (me)" flagged) · two roster columns with totals · a shared per-day grid (bars per side
per day, startable-slot cap line — Weekly's group chart pattern) · a "volume gap" callout
listing my zero-game days with a link to Waivers for that week (the streaming hint,
stated as game counts, not probabilities).

## Verification (every view, before its tracker tick)

```bash
python -m pytest tests/ -q                      # green, including test_season_api.py
cd frontend && npx tsc -b --noEmit && npm run build
python scripts/dev_fixtures.py --force          # regenerate, then drive the view
python scripts/serve.py                         # click through: data present, degraded, empty
```
Degraded modes to actually click, per view: no schedule (V3/V4/V5/V6 + week pickers), <2
snapshots (V1/V2 trend columns), no market pull (V2), no picks (V2 chips, V3 ownership,
V4/V5 empty states).

## Doc upkeep when a view ships (same commit)

README "Web app" bullet + ROADMAP Stage-5 web-app bullet line + this tracker/hand-off.
EXPERIMENTS.md: nothing (product). implementation-plan: nothing (this file owns view specs;
its Appendix-B matrix gains this file's row on the first commit that adds it).
