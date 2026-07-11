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
config/            scoring weights and other configuration
  scoring.yaml     league scoring definition (edit to match your league)
src/fantasy_nba/
  config.py        paths + config loading
  scoring.py       stat line -> fantasy points engine
  data/
    storage.py     Parquet read/write helpers
    ingest.py      nba_api data pulls
  models/          projection models (baseline first)
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
                   deterministic + audited; board A's file is never touched
  darko_report.py  DARKO overlay: minutes/rank disagreement report (pull_darko.py fetches)
  update_daily.py  Step-12 nightly pipeline: refresh logs + incremental injury/transaction
                   pulls + DARKO/market archives + the as-of ROS board with status overrides
                   (config/overrides.yaml), the EXP-030 OUT-redistribution layer (fitted
                   absorption tiers; redist_mpg audit column; --no-redist to disable),
                   and the naive-updater benchmark line
  explore.py       local interactive Streamlit explorer
data/              raw/ and processed/ caches (gitignored)
  manual/          hand-curated datasets — committed (the gitignore's manual-data exception):
                   coach_changes.csv = opening-night head-coach changes 2009-10..2026-27,
                   curated from Basketball-Reference coach pages (interim = took over
                   mid-prior-season or opens the season interim); feeds models/coaches.py
tests/
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

# Explore data + projections interactively in the browser
python -m streamlit run scripts/explore.py
```

## Nightly in-season run (Step 12)

One command, safe to cron, from opening night onward:

```bash
python scripts/update_daily.py
```

It (1) re-fetches the current season's game logs (replace-in-cache keyed on SEASON —
history preserved), (2) incrementally extends the injuries/transactions scrapes,
(3) accumulates the date-stamped DARKO + market archives (what makes EXP-017b/020
backtestable next season), and (4) writes the as-of ROS board to the append-only
`data/processed/ros_board/<date>.parquet` — with `config/overrides.yaml` status caps
applied (availability only: "out until X" caps ROS games; rates/minutes untouched) and
the naive-updater benchmark emitted alongside (`naive_fpts_pg`/`naive_rank` + a
disagreement report — the daily gap between them is itself a signal). Each pull is
fault-isolated; an existing board for the date is never silently overwritten.
Off-season dry-run: `python scripts/update_daily.py --offline --asof <in-season date>`.

## Interactive explorer

`python -m streamlit run scripts/explore.py` opens a local web app with four tabs:

- **Draft Board** — the projection with floor/median/ceiling ranges (SD_PG spread on the
  adopted age × chronic GP pools); choose the target season (past seasons are re-projected
  with no leakage and shown next to actual results, with a top-N hit rate), the projection
  model (**learned** default / baseline / v2 / v2m), and a ranking stance; the D1 decision
  columns (VOR, VOR rank, ADP) join automatically when the target's draft-sheet parquet
  exists; search and filter by team.
- **ROS (in-season)** — the latest nightly `data/processed/ros_board/` snapshot with the
  naive-updater disagreement table (populates once `update_daily.py` crons from opening
  night; DARKO/market disagreement stays in `darko_report.py` / `market_report.py`).
- **Player** — drill into one player: projected line, career per-game history, and per-game
  minutes trend/volatility from the game logs.
- **Data** — browse the raw datasets (season stats, game logs, bio, rosters).

## Configuring scoring

`config/scoring.yaml` carries the **confirmed league scoring** (2026-07-10: ESPN default
points league — 10 teams, weekly H2H; structure in `config/league.yaml`). The projection
engine outputs stat lines; the scoring module turns them into points, so if the league ever
customizes, editing the YAML is the only change — projections never re-run.
