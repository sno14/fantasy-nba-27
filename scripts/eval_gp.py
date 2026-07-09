"""Step 7.3 judgments for EXP-015 (injury/availability data) — two separate gates.

**(a) GP point estimate** — ``INJURY_FEATURES`` into the y_gp model only (variant
``learned_inj``). Metric: next-season GP MAE + Spearman on the *control model's* top-N
draftable pool (paired — both models judged on the same players, so selection can't differ),
per season + n-weighted pooled, mean over LightGBM seeds {0,1,2} (rule 8), with a
player-clustered paired bootstrap 90% CI on the pooled deltas.
Gate: pooled GP Spearman +0.05 absolute vs control.

**(b) Monte-Carlo GP tails** — ``build_gp_pool(injury_profile=...)`` buckets the empirical
GP pool by (age × chronic flag); the learned board gains ``inj_chronic_flag`` so
``simulate_ranges`` samples chronic players from their own fatter-tailed pool.
Gate: top-100 p10–p90 coverage stays in [78%, 88%] AND safe-rank Spearman improves or
ties, AND named chronic players' p10 drops vs durable peers (3 cases for the ledger —
printed per season under "chronic cases").

Usage
-----
    python scripts/eval_gp.py --seasons 2022-23 2023-24 2024-25 2025-26 --seeds 0 1 2
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models import injuries as inj
from fantasy_nba.models import uncertainty as unc
from fantasy_nba.models._core import _season_start
from fantasy_nba.models.backtest import _actual, project_models
from fantasy_nba.scoring import load_scoring

SAFE_LAMBDA = 0.5  # rank_board's default safe-stance downside penalty


def _spearman(a: pd.Series, b: pd.Series) -> float:
    return float(a.corr(b, method="spearman"))


def _pool_frame(models: dict, season: str, actual: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Control-pool paired frame: learned's top-N joined to both models' GP + actual GP."""
    ctrl = models["learned"].nsmallest(top_n, "rank")[["PLAYER_ID", "gp"]].rename(columns={"gp": "gp_ctrl"})
    cand = models["learned_inj"][["PLAYER_ID", "gp"]].rename(columns={"gp": "gp_inj"})
    m = ctrl.merge(cand, on="PLAYER_ID").merge(actual[["PLAYER_ID", "act_gp"]], on="PLAYER_ID")
    m["season"] = season
    return m


def _gp_metrics(pool: pd.DataFrame) -> dict:
    return {
        "n": len(pool),
        "MAE_ctrl": (pool["gp_ctrl"] - pool["act_gp"]).abs().mean(),
        "MAE_inj": (pool["gp_inj"] - pool["act_gp"]).abs().mean(),
        "spearman_ctrl": _spearman(pool["gp_ctrl"], pool["act_gp"]),
        "spearman_inj": _spearman(pool["gp_inj"], pool["act_gp"]),
    }


def _pooled_gp_metrics(pools: list[pd.DataFrame]) -> dict:
    """n-weighted mean of per-season metrics (Spearman is computed within season, never mixed)."""
    rows = [_gp_metrics(p) for p in pools]
    w = np.array([r["n"] for r in rows], dtype=float)
    out = {"n": int(w.sum())}
    for k in ("MAE_ctrl", "MAE_inj", "spearman_ctrl", "spearman_inj"):
        out[k] = float(np.average([r[k] for r in rows], weights=w))
    return out


def _cluster_bootstrap_ci(pools: list[pd.DataFrame], n_draws: int = 1000, seed: int = 0,
                          alpha: float = 0.10) -> dict:
    """Player-clustered paired bootstrap CI on the pooled (inj − ctrl) metric deltas."""
    all_rows = pd.concat(pools, ignore_index=True)
    players = all_rows["PLAYER_ID"].unique()
    rng = np.random.default_rng(seed)
    by_player = dict(tuple(all_rows.groupby("PLAYER_ID")))
    d_mae, d_rho = [], []
    for _ in range(n_draws):
        draw = pd.concat([by_player[p] for p in rng.choice(players, size=len(players))],
                         ignore_index=True)
        per_season = [g for _, g in draw.groupby("season") if len(g) >= 10]
        if not per_season:
            continue
        m = _pooled_gp_metrics(per_season)
        d_mae.append(m["MAE_inj"] - m["MAE_ctrl"])
        d_rho.append(m["spearman_inj"] - m["spearman_ctrl"])
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)
    return {
        "d_MAE_ci": (float(np.percentile(d_mae, lo)), float(np.percentile(d_mae, hi))),
        "d_spearman_ci": (float(np.percentile(d_rho, lo)), float(np.percentile(d_rho, hi))),
    }


def _ranges_frame(board: pd.DataFrame, gp_pool: pd.DataFrame, actual: pd.DataFrame,
                  top_n: int, sim_seed: int = 0) -> pd.DataFrame:
    """Simulated ranges on the board's top-N, joined to actual totals."""
    sim = unc.simulate_ranges(board, gp_pool, seed=sim_seed)
    top = sim.nsmallest(top_n, "rank")
    m = top.merge(actual[["PLAYER_ID", "act_fpts_total"]], on="PLAYER_ID", how="inner")
    m["covered"] = m["act_fpts_total"].between(m["fpts_p10"], m["fpts_p90"])
    m["safe_value"] = m["fpts_median"] - SAFE_LAMBDA * (m["fpts_median"] - m["fpts_p10"])
    return m


def _tail_metrics(m: pd.DataFrame) -> dict:
    return {
        "n": len(m),
        "coverage": float(m["covered"].mean()),
        "safe_spearman": _spearman(m["safe_value"], m["act_fpts_total"]),
        "median_spearman": _spearman(m["fpts_median"], m["act_fpts_total"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-015 judgments: GP point estimate + MC tails.")
    parser.add_argument("--seasons", nargs="+", default=["2022-23", "2023-24", "2024-25", "2025-26"])
    parser.add_argument("--top-n", type=int, default=150, help="Draftable pool for the GP judgment (a).")
    parser.add_argument("--top-n-ranges", type=int, default=100, help="Pool for the coverage judgment (b).")
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--scoring", default=None)
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    raw_inj = storage.read("injuries")
    cfg = load_scoring(args.scoring)

    spells, join_stats = inj.build_spells(raw_inj, season_stats)
    print("=== Injury name-join report (gate: >= 95% of events matched) ===")
    print({k: v for k, v in join_stats.items() if k != "top_unmatched"})
    print("top unmatched:", join_stats["top_unmatched"])

    all_seasons = sorted(season_stats["SEASON"].unique(), key=_season_start)
    chronic_table = inj.chronic_flag_table(spells, all_seasons)

    actuals = {s: _actual(season_stats, s, cfg, min_minutes=0.0) for s in args.seasons}

    # ---- project every (seed, season) once; both judgments consume the same boards ----
    per_seed_gp: dict[int, dict] = {}
    per_seed_tail: dict[int, dict] = {}
    for seed in args.seeds:
        gp_pools, tail_rows = [], {"base": [], "inj": []}
        chronic_cases = []
        for season in args.seasons:
            models = project_models(season, season_stats, bio, cfg,
                                    variants=["learned_inj"], seed=seed, injuries=spells)
            gp_pools.append(_pool_frame(models, season, actuals[season], args.top_n))

            # (b) tails — learned board, base pool vs (age × chronic) profile pool.
            ty = _season_start(season)
            train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
            train_bio = bio[bio["SEASON"].map(_season_start) < ty]
            board = models["learned"]
            flags = inj.injury_features(spells, f"{ty}-10-01")[["PLAYER_ID", "inj_chronic_flag"]]
            board_flagged = board.merge(flags, on="PLAYER_ID", how="left")
            board_flagged["inj_chronic_flag"] = board_flagged["inj_chronic_flag"].fillna(0).astype(int)

            pool_base = unc.build_gp_pool(train_ss, train_bio, max_start_year=ty)
            pool_prof = unc.build_gp_pool(train_ss, train_bio, max_start_year=ty,
                                          injury_profile=chronic_table)
            m_base = _ranges_frame(board, pool_base, actuals[season], args.top_n_ranges)
            m_inj = _ranges_frame(board_flagged, pool_prof, actuals[season], args.top_n_ranges)
            m_base["season"] = m_inj["season"] = season
            tail_rows["base"].append(m_base)
            tail_rows["inj"].append(m_inj)

            # chronic-vs-durable evidence: chronic players' p10 move, with a durable
            # same-median peer for contrast (ledger names 3 of these).
            cmp_cols = ["PLAYER_NAME", "fpts_median", "fpts_p10"]
            cc = m_inj[m_inj["inj_chronic_flag"] == 1][["PLAYER_ID"] + cmp_cols].rename(
                columns={"fpts_median": "median_inj", "fpts_p10": "p10_inj"})
            if not cc.empty:
                base_idx = m_base.set_index("PLAYER_ID")
                cc["p10_base"] = cc["PLAYER_ID"].map(base_idx["fpts_p10"])
                durable = m_inj[m_inj["inj_chronic_flag"] == 0]
                cc["peer"] = cc["median_inj"].map(
                    lambda v: durable.iloc[(durable["fpts_median"] - v).abs().argmin()]["PLAYER_NAME"])
                cc["peer_p10"] = cc["median_inj"].map(
                    lambda v: durable.iloc[(durable["fpts_median"] - v).abs().argmin()]["fpts_p10"])
                cc["season"] = season
                chronic_cases.append(cc)

        per_seed_gp[seed] = {
            "per_season": [_gp_metrics(p) | {"season": p["season"].iloc[0]} for p in gp_pools],
            "pooled": _pooled_gp_metrics(gp_pools),
            "pools": gp_pools,
        }
        per_seed_tail[seed] = {
            kind: {
                "per_season": [_tail_metrics(m) | {"season": m["season"].iloc[0]} for m in rows],
                "pooled": _tail_metrics(pd.concat(rows, ignore_index=True)),
            }
            for kind, rows in tail_rows.items()
        }
        per_seed_tail[seed]["chronic_cases"] = (
            pd.concat(chronic_cases, ignore_index=True) if chronic_cases else pd.DataFrame()
        )

    with pd.option_context("display.width", 220, "display.max_columns", None):
        print("\n################ (a) GP point estimate — learned_inj vs learned ################")
        for seed in args.seeds:
            r = per_seed_gp[seed]
            print(f"\n--- seed {seed} ---")
            print(pd.DataFrame(r["per_season"]).round(4).to_string(index=False))
            print("pooled:", {k: round(v, 4) for k, v in r["pooled"].items()})
        pooled_rows = pd.DataFrame([per_seed_gp[s]["pooled"] for s in args.seeds])
        mean_d_rho = (pooled_rows["spearman_inj"] - pooled_rows["spearman_ctrl"]).mean()
        spread = (pooled_rows["spearman_inj"] - pooled_rows["spearman_ctrl"]).max() - \
                 (pooled_rows["spearman_inj"] - pooled_rows["spearman_ctrl"]).min()
        mean_d_mae = (pooled_rows["MAE_inj"] - pooled_rows["MAE_ctrl"]).mean()
        print(f"\nmean over seeds: Δspearman = {mean_d_rho:+.4f} (seed spread {spread:.4f}), "
              f"ΔMAE = {mean_d_mae:+.3f}")
        ci = _cluster_bootstrap_ci(per_seed_gp[args.seeds[0]]["pools"])
        print(f"paired player-clustered 90% CI (seed {args.seeds[0]}): "
              f"Δspearman {tuple(round(x, 4) for x in ci['d_spearman_ci'])}, "
              f"ΔMAE {tuple(round(x, 3) for x in ci['d_MAE_ci'])}")
        print("GATE (a): pooled GP Spearman +0.05 absolute, beyond seed spread.")

        print("\n################ (b) Monte-Carlo tails — (age × chronic) profile pool ################")
        for seed in args.seeds:
            t = per_seed_tail[seed]
            print(f"\n--- seed {seed} ---")
            for kind in ("base", "inj"):
                print(f"[{kind}] per-season:")
                print(pd.DataFrame(t[kind]["per_season"]).round(4).to_string(index=False))
                print(f"[{kind}] pooled:", {k: round(v, 4) for k, v in t[kind]["pooled"].items()})
        cases = per_seed_tail[args.seeds[0]]["chronic_cases"]
        if not cases.empty:
            cases["p10_drop"] = cases["p10_base"] - cases["p10_inj"]
            print(f"\n--- chronic cases (seed {args.seeds[0]}; p10_base = age-only pool) ---")
            cols = ["season", "PLAYER_NAME", "median_inj", "p10_base", "p10_inj", "p10_drop",
                    "peer", "peer_p10"]
            print(cases.sort_values("p10_drop", ascending=False)[cols].round(0).to_string(index=False))
        print("\nGATE (b): pooled coverage in [0.78, 0.88] AND safe_spearman(inj) >= safe_spearman(base)"
              " AND 3 named chronic cases with p10 drop vs durable peers.")


if __name__ == "__main__":
    main()
