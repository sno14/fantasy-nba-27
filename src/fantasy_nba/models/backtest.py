"""Backtest harness: does v2 actually beat the baseline?

Projects a past season using **only** data from prior seasons (aging curves and the GP curve
are refit on the training years, so there's no leakage), then scores both models against what
actually happened. Compares per-game fantasy points (isolates the rate/aging projection) and
full-season totals (adds the games/durability projection).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame
from ._core import COUNTING, _season_start
from .aging import build_aging_curves
from .baseline import project_baseline
from .durability import build_gp_age_curve
from .projection import project_v2


def _actual(season_stats: pd.DataFrame, season: str, cfg: ScoringConfig, min_minutes: float) -> pd.DataFrame:
    """Actual per-game fantasy points for players who logged >= min_minutes in ``season``."""
    cols = ["GP", "MIN"] + list(COUNTING.values())
    a = season_stats[season_stats["SEASON"] == season].groupby(
        ["PLAYER_ID", "PLAYER_NAME"], as_index=False
    )[cols].sum()
    a = a[a["MIN"] >= min_minutes].copy()
    for canon, src in COUNTING.items():
        a[canon] = a[src] / a["GP"]
    a["act_fpts_pg"] = score_frame(a, cfg)
    a["act_fpts_total"] = a["act_fpts_pg"] * a["GP"]
    a["act_gp"] = a["GP"]
    return a[["PLAYER_ID", "PLAYER_NAME", "MIN", "act_gp", "act_fpts_pg", "act_fpts_total"]]


def _metrics(merged: pd.DataFrame, pred: str, act: str) -> dict:
    err = merged[pred] - merged[act]
    return {
        "n": len(merged),
        "MAE": err.abs().mean(),
        "RMSE": float(np.sqrt((err**2).mean())),
        "bias": err.mean(),
        "corr": merged[pred].corr(merged[act]),
    }


def run_backtest(
    target_season: str,
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    cfg: ScoringConfig | None = None,
    min_actual_minutes: float = 500.0,
) -> pd.DataFrame:
    """Return a metrics table comparing baseline vs v2 for ``target_season``."""
    cfg = cfg or load_scoring()
    ty = _season_start(target_season)

    train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
    train_bio = bio[bio["SEASON"].map(_season_start) < ty]
    if train_ss["SEASON"].nunique() < 2:
        raise ValueError(f"Not enough training seasons before {target_season}.")

    curves = build_aging_curves(train_ss, train_bio, save=False)
    gp_curve = build_gp_age_curve(train_ss, train_bio, save=False)

    base = project_baseline(train_ss, train_bio, target_season, cfg=cfg)
    v2 = project_v2(train_ss, train_bio, target_season, cfg=cfg, curves=curves, gp_curve=gp_curve)
    actual = _actual(season_stats, target_season, cfg, min_actual_minutes)

    rows = []
    for name, proj in (("baseline", base), ("v2", v2)):
        m = proj[["PLAYER_ID", "fpts_pg", "fpts_total"]].merge(actual, on="PLAYER_ID", how="inner")
        for metric_name, pred, act in (
            ("fpts_pg", "fpts_pg", "act_fpts_pg"),
            ("fpts_total", "fpts_total", "act_fpts_total"),
        ):
            r = {"model": name, "target": metric_name}
            r.update(_metrics(m, pred, act))
            rows.append(r)

    return pd.DataFrame(rows)
