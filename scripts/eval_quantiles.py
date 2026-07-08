"""EXP-013c (implementation-plan Step 5c): judge the direct fpts quantile heads.

Per season (no-leakage: quantile heads and the learned point estimate both train on
strictly-prior seasons), on the learned model's own top-N pool:

* **Pinball loss** at each q — the quantile heads vs three comparators built around the
  learned point estimate:
    - ``normal_sigma``  — constant-spread normal, sigma = that season's pooled residual std
      (the SD_PG analogue). NOTE: sigma is computed from the *eval season's* residuals, an
      in-sample advantage handed to the baseline on purpose — beating an advantaged baseline
      makes the verdict safe.
    - ``resid_quant``   — empirical residual quantiles added to the point estimate (the
      stronger, non-normal version of the same idea; same in-sample advantage).
    - ``pool_quant``    — unconditional empirical pool quantiles (player-independent).
* **Coverage** — fraction of pool actuals ≤ each predicted quantile; target within ±5pp of
  nominal, overall and per actual-Δ bucket (the big-riser escape rate is the Step-14 target).

Gate (plan Appendix A, 013c): adopt as Step-14 input if the heads beat ``normal_sigma`` on
pinball overall AND in the riser bucket.

Usage:
    python scripts/eval_quantiles.py --seasons 2022-23 2023-24 2024-25 2025-26 --seed 0
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
from scipy.stats import norm

from fantasy_nba.data import storage
from fantasy_nba.models._core import _season_start
from fantasy_nba.models.backtest import _actual
from fantasy_nba.models.eval_movers import _season_before, pool_frame
from fantasy_nba.models.learned import DEFAULT_LGBM_PARAMS, project_learned
from fantasy_nba.models.quantiles import (
    QUANTILES,
    pinball_loss,
    project_fpts_quantiles,
    quantile_col,
)
from fantasy_nba.scoring import load_scoring

RISER_BUCKETS = ("riser", "big riser")


def season_frames(season, season_stats, bio, cfg, pool_top_n, seed):
    """One season's evaluation frame: the learned pool joined to actuals, prior and the
    quantile-head predictions (all trained prior-only)."""
    ty = _season_start(season)
    train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
    train_bio = bio[bio["SEASON"].map(_season_start) < ty]
    params = {**DEFAULT_LGBM_PARAMS, "random_state": seed}

    proj = project_learned(train_ss, train_bio, season, cfg=cfg, params=params)
    quants = project_fpts_quantiles(train_ss, train_bio, season, cfg=cfg, params=params)

    actual = _actual(season_stats, season, cfg, min_minutes=0.0)[["PLAYER_ID", "act_fpts_pg"]]
    prior = _actual(season_stats, _season_before(season), cfg, min_minutes=500.0)[
        ["PLAYER_ID", "act_fpts_pg"]
    ].rename(columns={"act_fpts_pg": "prior_fpts_pg"})
    m = pool_frame(proj, prior, actual, pool_top_n).merge(quants, on="PLAYER_ID", how="left")
    return m.dropna(subset=[quantile_col(q) for q in QUANTILES])


def comparator_columns(m: pd.DataFrame) -> pd.DataFrame:
    """Add the three baseline quantile predictions (see module docstring for their
    deliberate in-sample advantage)."""
    m = m.copy()
    resid = m["act_fpts_pg"] - m["fpts_pg"]
    sigma = float(resid.std())
    for q in QUANTILES:
        m[f"normal_sigma_q{int(q*100)}"] = m["fpts_pg"] + sigma * norm.ppf(q)
        m[f"resid_quant_q{int(q*100)}"] = m["fpts_pg"] + float(resid.quantile(q))
        m[f"pool_quant_q{int(q*100)}"] = float(m["act_fpts_pg"].quantile(q))
    return m


def pinball_table(m: pd.DataFrame, subset: str) -> pd.DataFrame:
    """Pinball loss per (method, q) on a row subset ('all' or 'riser')."""
    d = m if subset == "all" else m[m["bucket"].isin(RISER_BUCKETS)]
    rows = []
    for method, col_fn in (
        ("quantile_heads", lambda q: quantile_col(q)),
        ("normal_sigma", lambda q: f"normal_sigma_q{int(q*100)}"),
        ("resid_quant", lambda q: f"resid_quant_q{int(q*100)}"),
        ("pool_quant", lambda q: f"pool_quant_q{int(q*100)}"),
    ):
        row = {"method": method, "subset": subset, "n": len(d)}
        for q in QUANTILES:
            row[f"pb_q{int(q*100)}"] = pinball_loss(d["act_fpts_pg"], d[col_fn(q)], q)
        row["pb_mean"] = float(np.mean([row[f"pb_q{int(q*100)}"] for q in QUANTILES]))
        rows.append(row)
    return pd.DataFrame(rows)


def coverage_table(m: pd.DataFrame) -> pd.DataFrame:
    """Coverage per q: overall and per actual-Δ bucket (quantile heads only)."""
    rows = []
    groups = [("ALL", m)] + [(b, g) for b, g in m.groupby("bucket", observed=True)]
    for name, g in groups:
        row = {"bucket": str(name), "n": len(g)}
        for q in QUANTILES:
            row[f"cov_q{int(q*100)}"] = float((g["act_fpts_pg"] <= g[quantile_col(q)]).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-013c quantile-head eval.")
    parser.add_argument("--seasons", nargs="+", default=["2022-23", "2023-24", "2024-25", "2025-26"])
    parser.add_argument("--top-n", type=int, default=150)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scoring", default=None)
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(args.scoring)

    frames = []
    for season in args.seasons:
        m = comparator_columns(
            season_frames(season, season_stats, bio, cfg, args.top_n, args.seed)
        )
        m["season"] = season
        frames.append(m)
    pooled = pd.concat(frames, ignore_index=True)

    with pd.option_context("display.width", 220, "display.max_columns", None):
        print(f"\n=== Pinball loss (pooled {len(args.seasons)} seasons, seed {args.seed}; "
              "lower is better) ===")
        pb = pd.concat([pinball_table(pooled, "all"), pinball_table(pooled, "riser")],
                       ignore_index=True)
        print(pb.round(3).to_string(index=False))

        print("\n=== Coverage — quantile heads (target: within ±5pp of nominal) ===")
        print(coverage_table(pooled).round(3).to_string(index=False))

        print("\n=== Per-season pinball mean (quantile heads vs normal_sigma) ===")
        rows = []
        for season, g in pooled.groupby("season"):
            for sub in ("all", "riser"):
                t = pinball_table(g, sub).set_index("method")
                rows.append({
                    "season": season, "subset": sub,
                    "heads": t.loc["quantile_heads", "pb_mean"],
                    "normal_sigma": t.loc["normal_sigma", "pb_mean"],
                    "win": t.loc["quantile_heads", "pb_mean"] < t.loc["normal_sigma", "pb_mean"],
                })
        print(pd.DataFrame(rows).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
