"""EXP-018 gate (implementation-plan Step 10): does in-season updating earn its complexity?

Per season and cutpoint (+30/+60/+90 days from the season's first game), score three
projections of the **remaining season** (per-game fpts of games strictly after T) on each
projection's own top-150 pool (by projected ROS total):

* ``asof``      — ``project_asof`` (one model per season fold, trained on the cutpoint panel
                  from strictly-prior seasons; predicts at every cutpoint).
* ``frozen_t0`` — ``project_learned`` fit at preseason and never updated (table stakes).
* ``naive``     — the hand-set shrinkage updater: per-game line =
                  ``(games_so_far × STD + K × T₀_proj) / (games_so_far + K)`` with K = 20,
                  built per player from the same game logs ≤ T. Beating this is the evidence
                  the *learned* shrinkage earns its complexity.

Gate: asof beats both on ROS level MAE in ≥ 2 of 3 cutpoints, in 3/4 seasons.

Usage:
    python scripts/eval_asof.py --seasons 2022-23 2023-24 2024-25 2025-26 --seed 0
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models import asof
from fantasy_nba.models._core import COUNTING, _season_start
from fantasy_nba.models.backtest import project_models
from fantasy_nba.scoring import load_scoring, score_frame

GATE_OFFSETS = (30, 60, 90)
NAIVE_K = 20.0


def ros_actual(gl_season: pd.DataFrame, T: pd.Timestamp) -> pd.DataFrame:
    """Realized ROS per-game fantasy line after ``T`` (no floors — actuals are actuals;
    the pool join decides who is scored)."""
    future = gl_season[gl_season["_date"] > T]
    g = future.groupby("PLAYER_ID")
    tot_min = g["MIN"].sum()
    out = pd.DataFrame({"PLAYER_ID": tot_min.index})
    out["act_ros_gp"] = g.size().to_numpy()
    for canon, src in COUNTING.items():
        out[canon] = (g[src].sum() / g.size()).to_numpy()  # per-game
    return out


def naive_board(t0_board: pd.DataFrame, gl_season: pd.DataFrame, T: pd.Timestamp,
                cfg, k: float = NAIVE_K) -> pd.DataFrame:
    """The naive updater: per-stat per-game line shrunk between season-to-date and the frozen
    T₀ projection by games played. Players missing from the T₀ board keep pure STD."""
    played = gl_season[gl_season["_date"] <= T]
    g = played.groupby("PLAYER_ID")
    n = g.size()
    std = pd.DataFrame({"PLAYER_ID": n.index, "games_so_far": n.to_numpy()})
    for canon, src in COUNTING.items():
        std[f"std_{canon}"] = (g[src].sum() / n).to_numpy()  # per-game

    t0 = t0_board[["PLAYER_ID", "gp", "mpg"] + list(COUNTING)].copy()
    m = t0.merge(std, on="PLAYER_ID", how="outer")
    m["games_so_far"] = m["games_so_far"].fillna(0.0)
    out = pd.DataFrame({"PLAYER_ID": m["PLAYER_ID"]})
    w = m["games_so_far"] / (m["games_so_far"] + k)
    for canon in COUNTING:
        proj = pd.to_numeric(m[canon], errors="coerce")
        stdc = pd.to_numeric(m[f"std_{canon}"], errors="coerce")
        # missing T₀ projection (rookie) -> pure STD; missing STD (hasn't played) -> pure T₀
        blend = w * stdc.fillna(proj) + (1 - w) * proj.fillna(stdc)
        out[canon] = blend
    out["fpts_pg"] = score_frame(out, cfg)
    # rank by expected ROS involvement: same shrinkage on GP pace is overkill — use T₀ gp
    # where known, games-so-far pace otherwise (ranking only decides the pool).
    out["gp"] = pd.to_numeric(m["gp"], errors="coerce").fillna(m["games_so_far"])
    out["fpts_total"] = out["fpts_pg"] * out["gp"]
    return out.dropna(subset=["fpts_pg"]).reset_index(drop=True)


def pool_mae(board: pd.DataFrame, actual: pd.DataFrame, cfg, top_n: int = 150) -> tuple[float, int]:
    """ROS level MAE on the board's own top-N by projected ROS total."""
    act = actual.copy()
    act["act_fpts_pg"] = score_frame(act, cfg)
    pool = board.nlargest(top_n, "fpts_total")
    m = pool[["PLAYER_ID", "fpts_pg"]].merge(act[["PLAYER_ID", "act_fpts_pg"]], on="PLAYER_ID")
    return float((m["fpts_pg"] - m["act_fpts_pg"]).abs().mean()), len(m)


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-018 as-of-date gate.")
    parser.add_argument("--seasons", nargs="+",
                        default=["2022-23", "2023-24", "2024-25", "2025-26"])
    parser.add_argument("--cutpoints", nargs="+", type=int, default=list(GATE_OFFSETS))
    parser.add_argument("--top-n", type=int, default=150)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scoring", default=None)
    parser.add_argument("--ewma", action="store_true",
                        help="Add the fitted-half-life EWMA form block (Step 10 amendment).")
    parser.add_argument("--blend", action="store_true",
                        help="Add the naive-blend features (start from the K=20 shrinkage, "
                             "learn corrections).")
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    gl = asof._with_dates(storage.read("player_game_logs"))
    cfg = load_scoring(args.scoring)
    params = {**asof.DEFAULT_LGBM_PARAMS, "random_state": args.seed}

    bounds = asof.season_date_bounds(gl).set_index("SEASON")["start"]
    rows = []
    for season in args.seasons:
        ty = _season_start(season)
        train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
        train_bio = bio[bio["SEASON"].map(_season_start) < ty]
        train_gl = gl[gl["SEASON"].map(_season_start) < ty]

        # fit once per season fold (half-lives, when used, also fit on the training slice only)
        half_lives = asof.fit_half_lives(train_gl) if args.ewma else None
        if half_lives:
            print(f"[{season}] fitted half-lives: {half_lives}", flush=True)
        panel = asof.build_asof_panel(train_ss, train_gl, train_bio, half_lives=half_lives,
                                      use_blend=args.blend)
        models = asof._fit_asof_models(panel, params, use_ewma=args.ewma, use_blend=args.blend)
        t0_board = project_models(season, season_stats, bio, cfg, seed=args.seed)["learned"]
        gl_s = gl[gl["SEASON"] == season]

        for off in args.cutpoints:
            T = bounds[season] + pd.Timedelta(days=off)
            actual = ros_actual(gl_s, T)
            feats = asof.asof_features(gl, season_stats, bio, season, T, half_lives=half_lives,
                                       use_blend=args.blend)
            boards = {
                "asof": asof.predict_board(models, feats, cfg, season),
                "frozen_t0": t0_board,
                "naive": naive_board(t0_board, gl_s, T, cfg),
            }
            for name, b in boards.items():
                mae, n = pool_mae(b, actual, cfg, args.top_n)
                rows.append({"season": season, "cutpoint": off, "model": name,
                             "ros_MAE": mae, "n": n})
            print(f"[{season} +{off}d] " + "  ".join(
                f"{r['model']} {r['ros_MAE']:.3f}" for r in rows[-3:]), flush=True)

    R = pd.DataFrame(rows)
    print("\n=== ROS level MAE by (season, cutpoint) ===")
    print(R.pivot_table(index=["season", "cutpoint"], columns="model",
                        values="ros_MAE").round(3).to_string())

    wide = R.pivot_table(index=["season", "cutpoint"], columns="model", values="ros_MAE")
    wide["beats_frozen"] = wide["asof"] < wide["frozen_t0"]
    wide["beats_naive"] = wide["asof"] < wide["naive"]
    wide["beats_both"] = wide["beats_frozen"] & wide["beats_naive"]
    per_season = wide.groupby("season")["beats_both"].sum()
    print("\ncutpoints where asof beats BOTH, per season (gate: >=2 of 3, in 3/4 seasons):")
    print(per_season.to_string())
    print("\nGATE:", bool((per_season >= 2).sum() >= 3))


if __name__ == "__main__":
    main()
