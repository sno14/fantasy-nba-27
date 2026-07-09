"""CLI to fetch and cache raw NBA data.

Examples
--------
    python scripts/pull_data.py --seasons 2023-24 2024-25 2025-26
    python scripts/pull_data.py --seasons 2025-26 --datasets player_season_stats team_rosters
"""

from __future__ import annotations

import argparse

from fantasy_nba.data import ingest


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and cache raw NBA data via nba_api.")
    parser.add_argument(
        "--seasons",
        nargs="+",
        required=True,
        help="Seasons in nba_api form, e.g. 2024-25 2025-26",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["player_season_stats", "player_game_logs"],
        choices=sorted(ingest._DATASETS) + sorted(ingest._STATIC_DATASETS),
        help="Which datasets to pull.",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Reuse existing cache instead of refetching.",
    )
    args = parser.parse_args()

    ingest.pull_seasons(
        seasons=args.seasons,
        datasets=args.datasets,
        refresh=not args.no_refresh,
    )


if __name__ == "__main__":
    main()
