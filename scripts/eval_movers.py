"""Mover-segmented, draftable-pool eval (ROADMAP Stage 7.0 / EXP-006).

Quantifies the current models' bias on players whose production *level* changed year over
year — the "risers & fallers" the ranking backtest is blind to.

Example
-------
    python scripts/eval_movers.py --seasons 2022-23 2023-24 2024-25 2025-26
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models.eval_movers import run_mover_eval
from fantasy_nba.scoring import load_scoring


def main() -> None:
    parser = argparse.ArgumentParser(description="Mover-segmented draftable-pool eval.")
    parser.add_argument("--seasons", nargs="+", default=["2023-24", "2024-25", "2025-26"])
    parser.add_argument("--top-n", type=int, default=150, help="Draftable pool size.")
    parser.add_argument("--scoring", default=None)
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(args.scoring)

    per_bucket_frames, dir_frames = [], []
    for season in args.seasons:
        per_bucket, directional = run_mover_eval(
            season, season_stats, bio, cfg=cfg, pool_top_n=args.top_n
        )
        per_bucket.insert(0, "season", season)
        directional.insert(0, "season", season)
        per_bucket_frames.append(per_bucket)
        dir_frames.append(directional)

    per_bucket = pd.concat(per_bucket_frames, ignore_index=True)
    directional = pd.concat(dir_frames, ignore_index=True)

    with pd.option_context("display.width", 200, "display.max_columns", None):
        print("\n=== Directional capture (per model, per season) ===")
        print(directional.round(3).to_string(index=False))

        print("\n=== Per-bucket level error & signed bias (pooled across seasons) ===")
        pooled = (
            per_bucket.dropna(subset=["n"])
            .assign(w=lambda d: d["n"])
            .groupby(["model", "bucket"], observed=False)
            .apply(
                lambda g: pd.Series({
                    "n": g["n"].sum(),
                    "level_MAE": (g["level_MAE"] * g["w"]).sum() / g["w"].sum(),
                    "signed_bias": (g["signed_bias"] * g["w"]).sum() / g["w"].sum(),
                    "mean_actual_delta": (g["mean_actual_delta"] * g["w"]).sum() / g["w"].sum(),
                    "mean_proj_delta": (g["mean_proj_delta"] * g["w"]).sum() / g["w"].sum(),
                }),
                include_groups=False,
            )
            .reset_index()
        )
        # Order buckets faller -> riser for readability.
        order = ["big faller", "faller", "stable", "riser", "big riser"]
        pooled["bucket"] = pd.Categorical(pooled["bucket"], categories=order, ordered=True)
        pooled = pooled.sort_values(["model", "bucket"])
        print(pooled.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
