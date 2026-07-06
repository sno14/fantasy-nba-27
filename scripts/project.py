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
from fantasy_nba.models.projection import project_v2
from fantasy_nba.scoring import load_scoring


def main() -> None:
    parser = argparse.ArgumentParser(description="Fantasy projections for a season.")
    parser.add_argument("--target", default="2026-27", help="Season to project (e.g. 2026-27).")
    parser.add_argument("--top", type=int, default=30, help="How many rows to print.")
    parser.add_argument(
        "--model",
        default="v2m",
        choices=["baseline", "v2", "v2m"],
        help="baseline (Marcel); v2 (+ empirical aging curves & durability); "
        "v2m (+ Stage 3 minutes aging curve). Backtests: baseline~v2; v2m improves minutes "
        "MAE and per-game fpts MAE in every tested season.",
    )
    parser.add_argument(
        "--scoring", default=None, help="Path to a scoring YAML (defaults to config/scoring.yaml)."
    )
    parser.add_argument(
        "--ranges", action="store_true",
        help="Add Monte-Carlo risk ranges (floor/median/ceiling totals + risk score). Season "
        "totals are availability-driven and unpredictable, so ranges are the honest output.",
    )
    parser.add_argument(
        "--rank-by", default=None, choices=["safe", "median", "floor", "ceiling"],
        help="Re-rank the board by risk stance (implies --ranges). 'safe' (default when set) "
        "applies a mild downside penalty: as accurate as median but demotes injury-prone players.",
    )
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(args.scoring)

    if args.model == "v2m":
        proj = project_v2(season_stats, bio, target_season=args.target, cfg=cfg, age_minutes=True)
    elif args.model == "v2":
        proj = project_v2(season_stats, bio, target_season=args.target, cfg=cfg)
    else:
        proj = project_baseline(season_stats, bio, target_season=args.target, cfg=cfg)

    show = ["rank", "PLAYER_NAME", "target_age", "gp", "mpg", "pts", "reb", "ast",
            "stl", "blk", "fg3m", "tov", "fpts_pg", "fpts_total"]
    if args.ranges or args.rank_by:
        from fantasy_nba.models.uncertainty import build_gp_pool, rank_board, simulate_ranges

        pool = build_gp_pool(season_stats, bio)
        proj = simulate_ranges(proj, pool)
        show = ["rank", "PLAYER_NAME", "target_age", "gp", "mpg", "fpts_pg",
                "fpts_p10", "fpts_median", "fpts_p90", "risk"]
        if args.rank_by:
            proj = rank_board(proj, method=args.rank_by)
            show = ["rank", "PLAYER_NAME", "target_age", "gp", "mpg", "fpts_pg", "draft_value",
                    "fpts_p10", "fpts_median", "fpts_p90", "risk"]

    path = storage.write(proj, f"{args.model}_{args.target}", layer="processed")
    print(f"Scoring: {cfg.name}  |  players projected: {len(proj):,}")
    print(f"Saved -> {path}\n")

    with_pd_opts(lambda: print(proj[show].head(args.top).to_string(index=False)))


def with_pd_opts(fn):
    import pandas as pd

    with pd.option_context("display.width", 200, "display.max_columns", None):
        fn()


if __name__ == "__main__":
    main()
