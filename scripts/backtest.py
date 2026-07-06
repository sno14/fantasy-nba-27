"""Backtest baseline vs v2 on one or more past seasons.

Example
-------
    python scripts/backtest.py --seasons 2023-24 2024-25
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models.backtest import run_backtest
from fantasy_nba.scoring import load_scoring


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest projection models against actuals.")
    parser.add_argument("--seasons", nargs="+", default=["2023-24", "2024-25"])
    parser.add_argument("--top-n", type=int, default=100,
                        help="Draft-pool size: score each model on its top-N by projected total.")
    parser.add_argument("--scoring", default=None)
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(args.scoring)

    frames = []
    for season in args.seasons:
        res = run_backtest(season, season_stats, bio, cfg=cfg, pool_top_n=args.top_n)
        res.insert(0, "season", season)
        frames.append(res)

    table = pd.concat(frames, ignore_index=True)
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(table.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
