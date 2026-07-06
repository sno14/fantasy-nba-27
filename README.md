# Fantasy NBA Projections (2026-27)

A multi-stage system that projects each NBA player's per-game stat line for the upcoming
season and converts it to fantasy points under a configurable scoring system.

See [ROADMAP.md](ROADMAP.md) for the build plan, current progress, and modeling philosophy.

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
data/              raw/ and processed/ caches (gitignored)
tests/
```

## Quick start

```bash
# Pull recent seasons of player data (cached to data/raw/)
python scripts/pull_data.py --seasons 2023-24 2024-25 2025-26

# Score a stat line with your league config
python -c "from fantasy_nba.scoring import load_scoring; print(load_scoring())"
```

## Configuring scoring

Edit `config/scoring.yaml`. The defaults are DraftKings-style placeholders — replace the
weights and bonuses with your league's actual values. The projection engine outputs stat
lines; the scoring module turns them into points, so changing scoring never requires
re-running projections.
