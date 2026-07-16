# Fantasy NBA Projections (2026-27)

A multi-stage system that projects each NBA player's per-game stat line for the upcoming
season and converts it to fantasy points under a configurable scoring system.

See [ROADMAP.md](ROADMAP.md) for the build plan, current progress, and modeling philosophy.

## Documentation map (reading order)

1. **[ROADMAP.md](ROADMAP.md)** — stages, progress checkboxes, key findings. Start here.
2. **[EXPERIMENTS.md](EXPERIMENTS.md)** — the append-only ledger of everything tested
   (adopted *and* rejected), so dead ends are never re-run.
3. **[docs/model-foundation.md](docs/model-foundation.md)** — the architecture decision
   record: why a learned, decompositional, as-of-date model (historical; kept as-is).
4. **[docs/breakthrough-plan.md](docs/breakthrough-plan.md)** — the Stage-7 diagnosis: why
   the riser bias resisted every feature experiment, and where the real headroom is.
5. **[docs/design-critique.md](docs/design-critique.md)** — standing senior-modelling
   review: hidden assumptions, leakage risks, correlation issues, better decompositions,
   and situational handling (injuries, role changes, fouls, blowouts, pace).
6. **[docs/implementation-plan.md](docs/implementation-plan.md)** — **the execution spec**:
   a strictly linear, step-by-step build plan with file-level specs, commands, and
   adopt/reject gates. Active work happens from this file.
7. **[docs/ui-views-plan.md](docs/ui-views-plan.md)** — the web-app view build-out spec
   (V1–V6 manager views: trends, trade targets, waivers, my-team, matchup, schedule
   strength) with its own progress tracker; product work, no ledger entries.
8. **[data/manual/bbm_transcripts/README.md](data/manual/bbm_transcripts/README.md)** — the
   analyst-layer workflow contract: BBM transcript drop zone, the triangulation rubric that
   sizes each fpts_delta (model × BBM mechanism × judgment; target-level sizing — delta =
   triangulated target − model base — so magnitude gaps count without stacking; joint
   re-triangulation for multi-mechanism players; uncapped, judgment-sized), the two hard
   rules (fpts_delta/none only; ignore BBM's rank claims), and the proposals → approval →
   overrides lifecycle.

## Setup

```bash
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# bash/macOS/Linux:    source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Layout

```
config/            league + scoring configuration and the analyst layer's files
  scoring.yaml     league scoring definition (confirmed ESPN default points league)
  league.yaml      league structure (D1.1): teams, roster slots, H2H weeks, league_end
  overrides.yaml   in-season availability caps ("out until X") applied by update_daily.py
  analyst_proposals.yaml  workflow-v2 staging: triangulated proposals awaiting review
                   (apply_proposals.py previews + promotes the approved ones)
  analyst_overrides.yaml  the approved analyst layer (board A -> board B; append-only,
                   latest-dated entry per player wins)
.env               local secrets, **gitignored, never committed** — `ESPN_S2` / `ESPN_SWID`
                   (browser cookies for the ESPN draft feed) + `ESPN_LEAGUE_ID`. Credentials
                   never go in config/, which IS committed. See "Draft room" below.
src/fantasy_nba/
  config.py        paths + config loading
  scoring.py       stat line -> fantasy points engine
  data/
    storage.py     Parquet read/write helpers
    ingest.py      nba_api data pulls
  models/          the model library — one module per layer/experiment (EXPERIMENTS.md
                   is the ledger of which are adopted / parked / rejected):
    baseline.py, projection.py, learned.py   Marcel -> v2/v2m -> learned (the default)
    _core.py, aging.py, minutes.py, durability.py  shared core + empirical age/GP curves
    asof.py        in-season as-of-date ROS engine (EXP-018; frozen EWMA half-lives)
    uncertainty.py, floor_sim.py, quantiles.py  risk ranges + eval floors + quantile heads
    injuries.py, absorption.py  injury-history features (EXP-015) + the OUT-redistribution
                   layer (EXP-030)
    analyst.py     analyst overrides board A -> board B + the D2.1 trigger list (EXP-029)
    context.py, recency.py, allocation.py, coaches.py, preseason.py, rosters.py
                   feature groups: team context / last-N form / team-constrained minutes /
                   coach changes / October roles / honest preseason roster maps
    breakout.py, rookies.py, darko.py, value.py  breakout flag, rookie model (rejected),
                   DARKO overlay, VOR
    backtest.py, eval_movers.py  no-leakage backtest + mover-segmented eval
  draft/           the draft room (Step 19; UI at /room) — the layer that runs *during* the
                   draft rather than producing a board and stopping:
    feed.py        where picks come from: the `DraftFeed` protocol + `ManualFeed` (the
                   shipped default and draft-night fallback) / `EspnPollFeed` (the real
                   league) / `FixtureFeed` (recorded payloads, for tests)
    ids.py         ESPN <-> NBA player-id join (normalized names + injuries.ALIASES; 96.8%
                   measured) and ESPN `eligibleSlots` = real PG/SG/SF/PF/C eligibility, the
                   one place in the repo that knows a player is SG *and* SF (models/value.py
                   parks eligibility at guard/big)
    live.py        `DraftState` (rebuildable from the pick list; undo = pop + rebuild) and
                   `live_replacement` / `live_board`: replacement level recomputed from the
                   *actual* remaining pool and *actual* remaining league-wide slot demand.
                   **`live_vor` ships informational** — measured 2026-07-16, it ranks ~identically
                   to plain fpts/g (Spearman 0.99) for ~110 of 130 picks and only bites in the
                   endgame (0.94 at pick 125). value.py's caveat holds: one scoring dimension,
                   3 UTIL slots, and 201/353 players multi-eligible ⇒ slots rarely bind
    (api/draft.py) the room's endpoints: one server-side session holds the picks, so the
                   source toggle is safe mid-draft and undo is just a pop
  api/             FastAPI backend for the web UI (scripts/serve.py): boards with tier
                   breaks, ROS snapshots, player pages, dataset browser, and the
                   analyst-proposal review panel (same code paths as the CLI tools)
frontend/          the web UI (React + Vite + Tailwind; light/dark). `npm run build`
                   emits frontend/dist, which serve.py serves; `npm run dev` proxies
                   /api for frontend development
scripts/
  pull_data.py     CLI to fetch and cache raw data
  project.py       generate the projection / draft board (default model: learned; + risk
                   ranges, --rank-by; --asof DATE = one-off in-season ROS board)
  backtest.py      no-leakage backtest on a top-N draft pool
  eval_movers.py   mover-segmented Stage-7 eval (--variants, --floor, --oracles, --actual-pool,
                   --ci A B (repeatable), --seed; --ranges = EXP-021 coverage-per-bucket
                   scoreboard: learned resid-CDF spreads vs SD_PG=9 — rejected, SD_PG stands)
  eval_quantiles.py  EXP-013c quantile-head eval: pinball loss vs baselines + per-bucket coverage
  tune_learned.py  EXP-013d nested walk-forward LGBM tuner (grid on folds <= 2021-22 only)
  eval_asof.py     EXP-018 in-season gate: project_asof vs frozen-T0 vs naive updater (--ewma, --blend)
                   + EXP-019 diagnostics (--exp019): in-season mover eval w/ per-cutpoint floors,
                   early-riser recall, weekly-grid lead-time, league-horizon sensitivity
                   (--fit-half-lives re-checks the frozen EWMA constants)
                   + EXP-030 (--exp030): OUT-redistribution layer vs plain asof — fitted
                   absorption tiers, treated-segment MAE + clustered CI, lead-time
  pull_injuries.py prosportstransactions scraper (injuries + transactions; drives the real
                   Edge/Chrome via Playwright — a browser window opens; incremental by date)
  eval_gp.py       EXP-015 judgments: GP point estimate (learned_inj) + Monte-Carlo GP tails
  eval_budget.py   EXP-031 judgment: 17.1 team-budget diagnostic (B_team vs 1-reserve target
                   + overshoot-error correlation; the standing "does the budget bind?"
                   instrument) + learned_depth / soft-reconciliation A/Bs (--depth,
                   --reconcile; λ nested on folds <= 2021-22, both rejected)
  eval_breakout.py EXP-026 judgment: breakout board policy vs learned, recall@150 + above-market
  eval_rookies.py  EXP-028 judgment (rejected): rookie model vs pick-order, Spearman gate +
                   archived-market comparison; draft_history dataset feeds it
  pull_market.py   market boards, date-stamped: Hashtag points-league consensus (value) +
                   FantasyPros ADP (availability); --wayback replays archived snapshots
  market_report.py board vs consensus: sleepers/fades (rank_gap + risk) + ADP availability column
  pull_schedule.py season schedule (D1.3): regular-season filter + per-week/B2B/playoff-week
                   derivations; 2026-27 publishes ~mid-Aug (vintage warning until then)
  draft_sheet.py   the decision sheet (D1): VOR vs league replacement + ADP availability +
                   rookie market-seed (market_priced) + breakout_p/ps_* pass-through
  analyst_triggers.py  D2.1 pre-draft review list: top-200 board-vs-consensus rank gaps +
                   breakout flags + severe-injury returnees (18m) + rookies
  apply_analyst.py D2.2 analyst overrides (config/analyst_overrides.yaml): board A -> board B,
                   deterministic + audited; board A's file is never touched. Workflow v2
                   (2026-07-12): entries arrive any time via config/analyst_proposals.yaml
                   (Claude triangulates BBM transcripts x model x own judgment; user
                   approves) and also apply nightly in-season via update_daily.py
  apply_proposals.py  workflow-v2 review tool: preview each proposal's fpts->rank board
                   impact, then --promote approved ones into analyst_overrides.yaml
                   (idempotent; fpts_delta/none only -- refuses rank_delta)
  pull_darko.py    DARKO daily projections pull (Playwright; date-stamped append-only archive)
  darko_report.py  DARKO overlay: minutes/rank disagreement report vs our board
  update_daily.py  Step-12 nightly pipeline: refresh logs + incremental injury/transaction
                   pulls + DARKO/market archives + the as-of ROS board with status overrides
                   (config/overrides.yaml), the EXP-030 OUT-redistribution layer (fitted
                   absorption tiers; redist_mpg audit column; --no-redist to disable),
                   the analyst layer (config/analyst_overrides.yaml applied nightly with
                   audit columns; --no-analyst to disable; fed by the BBM-transcript
                   workflow in data/manual/bbm_transcripts/README.md), and the
                   naive-updater benchmark line
  serve.py         serve the web app (FastAPI + built frontend, one process)
  dev_fixtures.py  synthetic schema-faithful dev cache so the web app runs without the
                   local-only real data (refuses to touch a real cache)
  explore.py       legacy Streamlit explorer (superseded by the web app; still works)
data/              raw/ and processed/ caches (gitignored)
  manual/          hand-curated datasets — committed (the gitignore's manual-data exception):
                   coach_changes.csv = opening-night head-coach changes 2009-10..2026-27,
                   curated from Basketball-Reference coach pages (interim = took over
                   mid-prior-season or opens the season interim); feeds models/coaches.py.
                   bbm_transcripts/ = the BBM video-transcript drop zone that feeds the
                   analyst layer (workflow v2 — rubric + contract in its README);
                   bbm_notes.csv = the extracted per-player fact ledger
docs/              design docs (see the documentation map above)
tests/             unit tests: scoring, model arithmetic, as-of engine, absorption,
                   Stage-7 infra (no-leakage / determinism pins), draft room (ESPN payload
                   traps + the replacement-level invariant)
```

## Quick start

```bash
# Pull recent seasons of player data (cached to data/raw/)
# datasets: player_season_stats, player_game_logs, preseason_game_logs, team_game_logs,
#           team_rosters, player_bio, draft_history (season-independent; one static pull)
python scripts/pull_data.py --seasons 2023-24 2024-25 2025-26

# Pull injury/IL history + player-movement transactions (prosportstransactions;
# first run ~30-60 min per dataset, then incremental by date)
python scripts/pull_injuries.py
python scripts/pull_injuries.py --dataset transactions

# Score a stat line with your league config
python -c "from fantasy_nba.scoring import load_scoring; print(load_scoring())"

# Generate the 2026-27 draft board with risk ranges (safe / median / floor / ceiling).
# Default model = learned (Step 15; switch to learned_ps once October preseason games cache).
# --breakout adds the EXP-026 breakout_p column (informational option-value flag)
# --preseason adds the Step-9c October-role columns (ps_mpg / ps_mpg_delta / ps_start_share)
#   once the target season's preseason games are cached (re-pull preseason_game_logs in Oct)
python scripts/project.py --target 2026-27 --rank-by safe --breakout --preseason --top 50

# In-season: one-off remaining-of-season board as of a date (the cron path is update_daily.py)
python scripts/project.py --asof 2027-01-15 --top 50

# Explore data + projections interactively in the browser (see "Web app" below)
python scripts/serve.py        # -> http://127.0.0.1:8787
```

## Nightly in-season run (Step 12)

One command, safe to cron, from opening night onward:

```bash
python scripts/update_daily.py
```

It (1) re-fetches the current season's game logs (replace-in-cache keyed on SEASON —
history preserved), (2) incrementally extends the injuries/transactions scrapes,
(3) accumulates the date-stamped DARKO + market archives (what makes EXP-017b/020
backtestable next season), (4) writes the as-of ROS board to the append-only
`data/processed/ros_board/<date>.parquet` — with `config/overrides.yaml` status caps
applied (availability only: "out until X" caps ROS games; rates/minutes untouched),
(5) applies the EXP-030 OUT-redistribution layer (minutes of currently-OUT players flow
to teammates by the fitted absorption tiers; `redist_mpg` audit column; `--no-redist`),
(6) applies the analyst layer (effective `config/analyst_overrides.yaml` entries with
`analyst_action`/`model_rank` audit columns; `--no-analyst`; fed by the BBM-transcript
workflow in `data/manual/bbm_transcripts/README.md`), and (7) emits the naive-updater
benchmark alongside (`naive_fpts_pg`/`naive_rank` + a disagreement report — the daily
gap between them is itself a signal). Each pull is fault-isolated; an existing board
for the date is never silently overwritten.
Off-season dry-run: `python scripts/update_daily.py --offline --asof <in-season date>`.

## Web app

`python scripts/serve.py` serves the app at http://127.0.0.1:8787 — a FastAPI backend
(`src/fantasy_nba/api/`) wrapping the same model code the CLI uses, plus a React frontend
(`frontend/`; light/dark, one-time `cd frontend && npm install && npm run build`). Views:

- **Draft Board** — the projection with floor/median/ceiling ranges (SD_PG spread on the
  adopted age × chronic GP pools); choose the target season (past seasons are re-projected
  with no leakage and shown next to actual results, with a top-N hit rate), the projection
  model (**learned** default / baseline / v2 / v2m), and a ranking stance; the **Analyst
  layer (B)** toggle (default on) applies `config/analyst_overrides.yaml` to the current
  season's board — the fpts_delta lands before the ranges are simulated so floor/median/
  ceiling shift with it, an Analyst column + adjusted count appear, and past-season
  backtest boards always stay pure model; the D1 decision columns (VOR, ADP) join
  automatically when the target's draft-sheet parquet exists, with **value/reach chips**
  (ADP vs our rank) and **tier breaks** (unusually large draft-value gaps); an optional
  range dot-plot; search / team filter / column sorting; checkboxes feed **Compare**.
- **ROS (in-season)** — nightly `data/processed/ros_board/` snapshots with the
  naive-updater disagreement panel (populates once `update_daily.py` crons from opening
  night; DARKO disagreement stays in `darko_report.py`).
- **Trends** — risers & fallers: the latest nightly snapshot diffed against one 7/14/30
  days back (rank/FP-G/MPG deltas + a trailing-month sparkline per player), snapshot-vs-
  snapshot only. The in-season "who's moving" radar; needs ≥2 nightly snapshots and says
  so until then. Backed by `/api/trends`.
- **Trade Targets** — the buy-low / sell-high *disagreement finder* (not advice): market
  consensus rank vs ours (`pull_market.py` archives — the likely trade price), the
  naive-vs-model heat gap (hot streaks the model discounts / cold streaks it looks
  through), and the 14-day trend, side by side with owner chips from the Draft Room
  picks. No composite score on purpose. Backed by `/api/trade-targets`.
- **Waivers** — the pickup list: unrostered players (Draft Room picks mark ownership;
  live ESPN rosters are the named V3b enhancement) ranked by ROS FP/G × games in the
  chosen week — with games a flagged-out player will miss removed (`out_until:` /
  `out_for_season` notes) — plus the opportunity chips: `redist_mpg` (inheriting an OUT
  teammate's minutes, EXP-030), `breakout_p`, and the 14-day trend. Backed by
  `/api/waivers`.
- **Weekly** — the streaming planner: pick an NBA week and rank players by **projected
  FP/G × games that week**, so a 4-game week at 25 FP/G (100) beats a 3-game week at 30
  (90) — the volume edge that drives waiver pickups. A per-day game grid shows when each
  team plays; toggle weekdays off to re-total over only the days you'll set a lineup for,
  and tick players to build a streaming group whose per-day game load is charted against
  the 10 startable slots (so you can see when picks collide on the same night). Reads
  `data/raw/schedule_<season>.parquet` (`scripts/pull_schedule.py`; the 2026-27 schedule
  publishes ~mid-August, so the tab says so until then). Backed by `/api/weeks` +
  `/api/weekly`.
- **Players** — drill into one player: projected line (board B), season range, career
  per-game history with FP/G, and per-game minutes trend/volatility from the game logs.
- **Compare** — 2–4 players side by side: projections, ranges, careers overlaid.
- **Analyst** — the workflow-v2 proposal review panel: each
  `config/analyst_proposals.yaml` entry with rationale, triangulation, and its live
  board impact; approve/reject writes only that entry's `status:` line (comments
  preserved), **Promote** runs the `apply_proposals.py --promote` code path (idempotent).
- **Draft Room** — the live draft (Step 19; see "Draft room" below). Manual/ESPN source
  toggle, the board minus drafted players, your roster's unfilled slots via ESPN eligibility
  (the useful signal — orthogonal to value), all ten teams' composition with descriptive risk,
  and a `live_vor` column that is **informational**: it re-ranks almost identically to fpts/g
  until the endgame (see the layout note above).
- **Power Rankings** — once teams draft, every roster ranked by projected **season fantasy
  points** (rate × durability), with total/avg FP/G, best-lineup **Starters** FP/G, **Star
  power** (top-3), **Depth** (players above replacement), summed floor→ceiling spread, mean
  injury risk, chronic-injury and unfilled-lineup-slot counts, and your team flagged. Reads
  the live Draft Room picks (manual or ESPN); a **Simulate mock draft** button best-available
  snake-fills all teams to preview the league before draft night. Backed by `/api/draft/power`
  + `/api/draft/simulate`.
- **Schedule** — schedule strength: teams × fantasy-weeks game-count heatmap with the
  fantasy playoff weeks highlighted (draft tiebreak / trade-deadline tool), plus total
  games and back-to-backs. Banners that `league.yaml`'s `fantasy_playoff_weeks` is a
  placeholder until `fantasy_playoff_weeks_confirmed: true` is set (mid-Aug ESPN
  calendar). Backed by `/api/schedule-strength`.
- **Data** — browse the raw parquet caches (season stats, game logs, bio, rosters, …).

The remaining season views (Waivers / My Team / Matchup planner) are spec'd in
[docs/ui-views-plan.md](docs/ui-views-plan.md) — its tracker is the live build state.

Frontend dev loop: `python scripts/serve.py` + `cd frontend && npm run dev` (Vite on
:5173, `/api` proxied). No local data yet? `python scripts/dev_fixtures.py` writes a
synthetic, schema-faithful cache (marked with `data/raw/FIXTURE_DATA.marker`; the UI
shows a "synthetic data" badge; it refuses to touch a real cache). The legacy Streamlit
explorer (`python -m streamlit run scripts/explore.py`) still works.

## Draft room (Step 19 — `src/fantasy_nba/draft/`)

The live-draft layer: picks arrive, drafted players leave the board, and replacement level is
recomputed from the *actual* remaining pool and the *actual* remaining slot demand across the
league. Open it at **`/room`** in the web app (`python scripts/serve.py`).

**Status: the board + composition views are built and verified.** The prescriptive layer
(H2H week-win simulator, "take player X") is **not** built and is gated — see
`docs/implementation-plan.md` Phase 7. The room reports *composition*, not advice: what each
team has, what it still can't fill, and how much injury risk it carries.

The view carries a **Manual / ESPN source toggle**, switchable mid-draft: picks live
server-side, so if the ESPN poller stalls on the night you flip to Manual and lose nothing.
Manual is the default. Its one dependency is a single **Connect ESPN** click at any point
before the draft — ESPN is the only source of slot eligibility, and the resulting map is
cached to `data/processed/espn_player_map.parquet`, after which manual mode runs fully
offline. Without it there are no positions, so no positional scarcity (the UI says so rather
than pretending).

**ESPN access.** The feed reads a private league, so it needs two browser cookies. Put them in
`.env` at the repo root (**gitignored** — never in `config/`, which is committed):

```
ESPN_S2=<long URL-encoded value>      # F12 > Application > Cookies > fantasy.espn.com
ESPN_SWID={<guid, braces included>}
ESPN_LEAGUE_ID=507458037
```

ESPN session cookies expire — if a call 401s, re-harvest them from the browser before
concluding the league is gone.

**ESPN is the authority; `league.yaml` is the fallback.** League id, team ids, team count,
roster slots and pick order all drift as members join, so read them live rather than trusting
a cached value:

```python
s = feed.league_settings()      # size / slot_counts / pick_order / draft_type / draft_date
s.order_is_placeholder          # True = ESPN's sorted default; the order is not yet drawn
```

Pick order is the sharp edge: ESPN seeds it with sorted team ids and randomizes shortly before
the draft, so **never cache it** — a stale order returns confident nonsense, whereas no order
makes `picks_until_next()` return `None` honestly. Re-verification is on the standing calendar
(`docs/implementation-plan.md` 19.1b, mid-Oct, before the dual freeze — a league resize
re-prices the whole board through replacement level).

```python
from fantasy_nba.draft import EspnPollFeed, build_player_map, DraftState
from fantasy_nba.draft.live import live_board

feed = EspnPollFeed(league_id=507458037, season=2027)   # season = the ENDING year
picks, teams = feed.poll(), feed.team_ids()
pmap = build_player_map(feed.player_universe(), season_stats, season="2025-26")
state = DraftState(picks=picks, my_team_id=3, league=league, team_ids=teams,
                   eligible_of=pmap.eligible_of, to_nba=pmap.to_nba)
live_board(state, board)        # board minus drafted, + live_vor / live_repl / live_rank
```

`ManualFeed` (type the picks) is the shipped default and the draft-night fallback: it needs no
network and takes a pick instantly if the ESPN poller stalls. Three ESPN behaviours are load-
bearing and are pinned by tests — the API host is `lm-api-reads.fantasy.espn.com` (the old
`fantasy.espn.com/apis/v3/...` returns **HTTP 200 with HTML**, so a bare status check
silently "succeeds"); an undrafted league returns a **full pre-allocated pick array** of
`playerId = -1` placeholders; and `teamId` is **not** a contiguous `1..N` index. Details in
`docs/implementation-plan.md` Step 19.1.

## Configuring scoring

`config/scoring.yaml` carries the **confirmed league scoring** (2026-07-10: ESPN default
points league — 10 teams, weekly H2H; structure in `config/league.yaml`). The projection
engine outputs stat lines; the scoring module turns them into points, so if the league ever
customizes, editing the YAML is the only change — projections never re-run.
