"""EXP-028 judgment (Step 9d): rookie model vs the draft-pick-order baseline.

Gate: pooled rookie-cohort Spearman (predicted vs realized fpts/g) beats pick-order by
>= +0.05 with MAE not worse, rule-8 guarded (seeds {0,1,2} + a paired bootstrap CI on the
pooled Spearman delta). Where preseason market archives exist (2022-23 / 2023-24 Hashtag),
the market's rookie ordering is reported informationally on the matched subset.

Example
-------
    python scripts/eval_rookies.py --seasons 2022-23 2023-24 2024-25 2025-26
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from fantasy_nba.config import RAW_DIR
from fantasy_nba.data import storage
from fantasy_nba.models import rookies
from fantasy_nba.models.darko import normalize_name
from fantasy_nba.scoring import load_scoring

MARKET_ARCHIVES = {  # cohort season -> vintage-verified preseason snapshot (EXP-017b audit)
    "2022-23": "hashtag_20221005.parquet",
    "2023-24": "hashtag_20231005.parquet",
}


def _labeled(test: pd.DataFrame) -> pd.DataFrame:
    """Eval universe: rookies with a valid label (>= MIN_LABEL_MINUTES). Applies identically
    to model and baseline — a no-show rookie has no rank to score either way."""
    t = test.dropna(subset=["y_mpg", "y_fpts_pm"]).copy()
    t["act_fpts_pg"] = t["y_mpg"] * t["y_fpts_pm"]
    t["act_total"] = t["act_fpts_pg"] * t["y_gp"]
    return t


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-028 rookie-model gate.")
    parser.add_argument("--seasons", nargs="+", default=["2022-23", "2023-24", "2024-25", "2025-26"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--scoring", default=None)
    parser.add_argument("--boot", type=int, default=2000, help="Bootstrap draws for the CI.")
    args = parser.parse_args()

    cfg = load_scoring(args.scoring)
    season_stats = storage.read("player_season_stats")
    panel = rookies.build_rookie_panel(
        season_stats, storage.read("player_bio"), storage.read("draft_history"),
        storage.read("transactions"), storage.read("team_rosters"), cfg=cfg,
    )
    n_lab = panel.dropna(subset=["y_mpg"]).shape[0]
    print(f"[panel] {len(panel):,} rookies over {panel['SEASON'].nunique()} cohorts "
          f"({n_lab:,} with >= {rookies.MIN_LABEL_MINUTES:.0f} min labels)")

    rows, deltas_by_seed = [], {}
    per_player_frames = []
    for seed in args.seeds:
        params = {**rookies.DEFAULT_ROOKIE_PARAMS, "random_state": seed}
        for season in args.seasons:
            proj = rookies.project_rookies(panel, season, params=params)
            base = rookies.pick_order_baseline(panel, season)
            t = _labeled(proj)
            bmap = base.set_index("PLAYER_ID")
            t["base_fpts_pg"] = t["PLAYER_ID"].map(bmap["fpts_pg"])
            t["base_total"] = t["PLAYER_ID"].map(bmap["fpts_total"])

            sp_model = spearmanr(t["fpts_pg"], t["act_fpts_pg"]).statistic
            sp_base = spearmanr(-t["overall_pick"], t["act_fpts_pg"]).statistic
            sp_model_tot = spearmanr(t["fpts_total"], t["act_total"]).statistic
            sp_base_tot = spearmanr(-t["overall_pick"], t["act_total"]).statistic
            mae_model = (t["fpts_pg"] - t["act_fpts_pg"]).abs().mean()
            mae_base = (t["base_fpts_pg"] - t["act_fpts_pg"]).abs().mean()
            rows.append({
                "seed": seed, "season": season, "n": len(t),
                "sp_model": sp_model, "sp_pick": sp_base, "sp_delta": sp_model - sp_base,
                "sp_model_tot": sp_model_tot, "sp_pick_tot": sp_base_tot,
                "mae_model": mae_model, "mae_pick": mae_base,
            })
            t["seed"] = seed
            t["season"] = season
            per_player_frames.append(
                t[["seed", "season", "PLAYER_ID", "overall_pick", "fpts_pg",
                   "act_fpts_pg", "base_fpts_pg"]]
            )

    res = pd.DataFrame(rows)
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print("\n=== Per (seed, season) — Spearman vs realized rookie fpts/g ===")
        print(res.round(3).to_string(index=False))
        pooled = res.groupby("seed").apply(
            lambda g: pd.Series({
                "sp_model": np.average(g["sp_model"], weights=g["n"]),
                "sp_pick": np.average(g["sp_pick"], weights=g["n"]),
                "sp_delta": np.average(g["sp_delta"], weights=g["n"]),
                "sp_model_tot": np.average(g["sp_model_tot"], weights=g["n"]),
                "sp_pick_tot": np.average(g["sp_pick_tot"], weights=g["n"]),
                "mae_model": np.average(g["mae_model"], weights=g["n"]),
                "mae_pick": np.average(g["mae_pick"], weights=g["n"]),
            }), include_groups=False)
        print("\n=== Pooled (n-weighted across seasons) per seed — gate: sp_delta >= +0.05, MAE not worse ===")
        print(pooled.round(3).to_string())

    # Paired bootstrap 90% CI on the pooled Spearman delta (resample rookies within season),
    # on the seed-0 predictions (the ranking is nearly seed-stable; seeds guard the mean).
    pp = pd.concat(per_player_frames, ignore_index=True)
    pp0 = pp[pp["seed"] == args.seeds[0]]
    rng = np.random.default_rng(0)
    boot = []
    for _ in range(args.boot):
        ds, ns = [], []
        for season, g in pp0.groupby("season"):
            b = g.sample(len(g), replace=True, random_state=rng.integers(2**31))
            if b["act_fpts_pg"].nunique() < 3:
                continue
            sm = spearmanr(b["fpts_pg"], b["act_fpts_pg"]).statistic
            sb = spearmanr(-b["overall_pick"], b["act_fpts_pg"]).statistic
            ds.append(sm - sb)
            ns.append(len(b))
        boot.append(np.average(ds, weights=ns))
    lo, hi = np.percentile(boot, [5, 95])
    print(f"\n=== Paired bootstrap 90% CI, pooled Spearman delta (model − pick-order): "
          f"[{lo:+.3f}, {hi:+.3f}] ===")

    # Informational: the market's rookie ordering on the archived preseason boards.
    print("\n=== Market comparison (informational; matched archived-board rookies only) ===")
    for season, fname in MARKET_ARCHIVES.items():
        if season not in args.seasons:
            continue
        market = pd.read_parquet(RAW_DIR / "market" / fname)
        t = pp0[pp0["season"] == season].copy()
        stats_names = storage.read("player_season_stats").drop_duplicates("PLAYER_ID", keep="last")
        t["name_key"] = t["PLAYER_ID"].map(
            stats_names.set_index("PLAYER_ID")["PLAYER_NAME"]).map(normalize_name)
        m = t.merge(market[["name_key", "consensus_rank"]], on="name_key", how="inner")
        if len(m) < 3:
            print(f"{season}: <3 rookies matched on the archived board — skipped")
            continue
        sp_mkt = spearmanr(-m["consensus_rank"], m["act_fpts_pg"]).statistic
        sp_mod = spearmanr(m["fpts_pg"], m["act_fpts_pg"]).statistic
        sp_pick = spearmanr(-m["overall_pick"], m["act_fpts_pg"]).statistic
        print(f"{season}: n={len(m)} matched | market {sp_mkt:+.3f} | model {sp_mod:+.3f} | "
              f"pick-order {sp_pick:+.3f}")


if __name__ == "__main__":
    main()
