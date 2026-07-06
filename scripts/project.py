"""Generate baseline projections for a target season and save the ranked table.

Example
-------
    python scripts/project.py --target 2026-27 --top 30
"""

from __future__ import annotations

import argparse
import sys

# Windows consoles default to cp1252, which can't print accented player names (Jokić, etc.).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fantasy_nba.data import storage
from fantasy_nba.models.baseline import project_baseline
from fantasy_nba.scoring import load_scoring


def main() -> None:
    parser = argparse.ArgumentParser(description="Baseline fantasy projections for a season.")
    parser.add_argument("--target", default="2026-27", help="Season to project (e.g. 2026-27).")
    parser.add_argument("--top", type=int, default=30, help="How many rows to print.")
    parser.add_argument(
        "--scoring", default=None, help="Path to a scoring YAML (defaults to config/scoring.yaml)."
    )
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(args.scoring)

    proj = project_baseline(season_stats, bio, target_season=args.target, cfg=cfg)

    path = storage.write(proj, f"baseline_{args.target}", layer="processed")
    print(f"Scoring: {cfg.name}  |  players projected: {len(proj):,}")
    print(f"Saved -> {path}\n")

    show = ["rank", "PLAYER_NAME", "target_age", "gp", "mpg", "pts", "reb", "ast",
            "stl", "blk", "fg3m", "tov", "fpts_pg", "fpts_total"]
    with_pd_opts(lambda: print(proj[show].head(args.top).to_string(index=False)))


def with_pd_opts(fn):
    import pandas as pd

    with pd.option_context("display.width", 200, "display.max_columns", None):
        fn()


if __name__ == "__main__":
    main()
