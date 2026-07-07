"""Backtest harness: which model actually helps for *drafting*?

Projects a past season using **only** data from prior seasons (aging curves and the GP curve
are refit on the training years, so there's no leakage), then scores each model against what
actually happened.

Evaluation is restricted to the **draft pool**: each model's own top-N players by projected
season fantasy total (default N=100). This matters — MAE averaged over all ~330 rotation
players rewards accuracy on bench guys nobody drafts and hid that the fancy models don't beat
the baseline where it counts. The headline metric is **Spearman rank correlation** of projected
vs actual fantasy totals within that pool (drafting is a ranking problem), alongside MAE on
minutes, per-game points, and season totals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame
from ._core import COUNTING, _season_start
from .aging import build_aging_curves
from .baseline import project_baseline
from .durability import build_gp_age_curve
from .learned import project_learned
from .minutes import build_minutes_age_curve
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
    a["act_mpg"] = a["MIN"] / a["GP"]
    return a[["PLAYER_ID", "PLAYER_NAME", "MIN", "act_gp", "act_mpg", "act_fpts_pg", "act_fpts_total"]]


def _metrics(merged: pd.DataFrame, pred: str, act: str) -> dict:
    err = merged[pred] - merged[act]
    return {
        "n": len(merged),
        "MAE": err.abs().mean(),
        "bias": err.mean(),
        "pearson": merged[pred].corr(merged[act]),
        "spearman": merged[pred].corr(merged[act], method="spearman"),
    }


def project_models(
    target_season: str,
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    cfg: ScoringConfig,
) -> dict[str, pd.DataFrame]:
    """Project ``target_season`` with every model using **only** prior-season data.

    Aging / GP / minutes curves are refit on the training years (seasons strictly before
    the target), so there is no leakage. Returns ``{model_name: projection_frame}`` — the
    shared no-leakage projection step behind both the ranking backtest and the mover eval.
    """
    ty = _season_start(target_season)
    train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
    train_bio = bio[bio["SEASON"].map(_season_start) < ty]
    if train_ss["SEASON"].nunique() < 2:
        raise ValueError(f"Not enough training seasons before {target_season}.")

    curves = build_aging_curves(train_ss, train_bio, save=False)
    gp_curve = build_gp_age_curve(train_ss, train_bio, save=False)
    mpg_curve = build_minutes_age_curve(train_ss, train_bio, save=False)

    base = project_baseline(train_ss, train_bio, target_season, cfg=cfg)
    v2 = project_v2(train_ss, train_bio, target_season, cfg=cfg, curves=curves, gp_curve=gp_curve)
    # v2m: v2 with the Stage 3 minutes aging curve applied to projected MPG.
    v2m = project_v2(
        train_ss, train_bio, target_season, cfg=cfg, curves=curves, gp_curve=gp_curve,
        mpg_curve=mpg_curve, age_minutes=True,
    )
    # learned: LightGBM decompositional model on Marcel-equivalent features (EXP-007). Trains
    # on the (prior-only) panel inside project_learned, so it stays no-leakage per fold.
    learned = project_learned(train_ss, train_bio, target_season, cfg=cfg)
    # NOTE: season-level trajectory features (project_learned(use_trajectory=True), EXP-008) were
    # A/B'd here and *rejected* — no lift, slightly worse riser buckets (see EXPERIMENTS.md).
    # The capability is kept in learned.py for recombination with recent-window/context signal.
    return {"baseline": base, "v2": v2, "v2m": v2m, "learned": learned}


def run_backtest(
    target_season: str,
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    cfg: ScoringConfig | None = None,
    pool_top_n: int = 100,
) -> pd.DataFrame:
    """Return a metrics table comparing baseline/v2/v2m for ``target_season``.

    Each model is scored on its **own** top-``pool_top_n`` players by projected season fantasy
    total (the players you'd actually draft), so models aren't judged on bench-player noise.
    Players projected into the pool who then didn't play are penalised via the inner join with
    actuals only if they logged at least one game; a projected star who missed the whole season
    simply drops out (a limitation to revisit once injury data exists).
    """
    cfg = cfg or load_scoring()
    projections = project_models(target_season, season_stats, bio, cfg)
    actual = _actual(season_stats, target_season, cfg, min_minutes=0.0)

    rows = []
    for name, proj in projections.items():
        pool = proj.nsmallest(pool_top_n, "rank")  # top-N by projected fantasy total
        m = pool[["PLAYER_ID", "mpg", "fpts_pg", "fpts_total"]].merge(actual, on="PLAYER_ID", how="inner")
        for metric_name, pred, act in (
            ("mpg", "mpg", "act_mpg"),
            ("fpts_pg", "fpts_pg", "act_fpts_pg"),
            ("fpts_total", "fpts_total", "act_fpts_total"),
        ):
            r = {"model": name, "target": metric_name}
            r.update(_metrics(m, pred, act))
            rows.append(r)

    return pd.DataFrame(rows)
