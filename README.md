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
5. **[docs/implementation-plan.md](docs/implementation-plan.md)** — **the execution spec**:
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
  project.py       generate the projection / draft board (+ risk ranges, --rank-by)
  backtest.py      no-leakage backtest on a top-N draft pool
  explore.py       local interactive Streamlit explorer
data/              raw/ and processed/ caches (gitignored)
tests/
```

## Quick start

```bash
# Pull recent seasons of player data (cached to data/raw/)
python scripts/pull_data.py --seasons 2023-24 2024-25 2025-26

# Score a stat line with your league config
python -c "from fantasy_nba.scoring import load_scoring; print(load_scoring())"

# Generate the 2026-27 draft board with risk ranges (safe / median / floor / ceiling)
python scripts/project.py --target 2026-27 --rank-by safe --top 50

# Explore data + projections interactively in the browser
python -m streamlit run scripts/explore.py
```

## Interactive explorer

`python -m streamlit run scripts/explore.py` opens a local web app with three tabs:

- **Draft Board** — the projection with floor/median/ceiling ranges; choose the target season
  (past seasons are re-projected with no leakage and shown next to actual results, with a
  top-N hit rate), the projection model (baseline / v2 / v2m), and a ranking stance; search
  and filter by team.
- **Player** — drill into one player: projected line, career per-game history, and per-game
  minutes trend/volatility from the game logs.
- **Data** — browse the raw datasets (season stats, game logs, bio, rosters).

## Configuring scoring

Edit `config/scoring.yaml`. The defaults are DraftKings-style placeholders — replace the
weights and bonuses with your league's actual values. The projection engine outputs stat
lines; the scoring module turns them into points, so changing scoring never requires
re-running projections.
