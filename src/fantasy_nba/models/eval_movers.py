"""Mover-segmented, draftable-pool evaluation (ROADMAP Stage 7.0 / EXP-006).

The ranking backtest (``backtest.py``) answers "did we rank the stable core right?" and is,
by construction, availability-dominated and **blind to risers and fallers** (EXP-003 ledger
note). This module answers the question Stage 7 actually cares about: **do we get a player's
production *level* right, especially when that level is changing?**

Method (preseason / across-season form):
  * Project ``target_season`` using only prior-season data (shared no-leakage path,
    ``backtest.project_models``).
  * Take each model's own **draftable pool** — top ``pool_top_n`` by projected fantasy total.
  * Every player in the pool has a **prior-season actual** per-game level (the season before
    the target). Define
        actual_delta = actual_pg(target) - prior_pg      (how much the player really moved)
        proj_delta   = proj_pg          - prior_pg        (how much we *said* he'd move)
  * **Bucket players by actual_delta** (big fallers … stable … big risers) and report, per
    bucket, the per-game **level** error (MAE/RMSE) and — the headline — the **signed bias**
    ``mean(proj_pg - actual_pg)``. The structural prediction of a mean-reverting model is a
    *negative* bias in the riser bucket (we under-project them) and a *positive* bias in the
    faller bucket (we over-project them). Shrinking that per-bucket bias is the deliverable.
  * **Directional capture:** does proj_delta even point the right way? Report corr(proj_delta,
    actual_delta) and the fraction of players moved in the correct direction.

This is the "baseline the disease" harness. In-season as-of-date cutpoints (the waiver use)
are a planned extension — they need game-log-date granularity and are noted in ROADMAP 7.0.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring
from ._core import _season_start
from .backtest import _actual, project_models


def _season_before(season: str) -> str:
    """'2024-25' -> '2023-24'."""
    start = _season_start(season) - 1
    return f"{start}-{str(start + 1)[-2:]}"


# Default actual-delta bucket edges in fantasy-points-per-game. Chosen once around the
# roughly symmetric spread of YoY per-game changes in the draftable pool; ``run_mover_eval``
# labels are derived from these so the buckets stay stable across seasons (quantile edges
# would drift season to season and make per-bucket bias incomparable).
DEFAULT_BUCKET_EDGES = (-6.0, -2.0, 2.0, 6.0)
BUCKET_LABELS = ("big faller", "faller", "stable", "riser", "big riser")


def _bucket(delta: pd.Series, edges=DEFAULT_BUCKET_EDGES) -> pd.Series:
    bins = [-np.inf, *edges, np.inf]
    return pd.cut(delta, bins=bins, labels=BUCKET_LABELS)


def run_mover_eval(
    target_season: str,
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    cfg: ScoringConfig | None = None,
    pool_top_n: int = 150,
    min_prior_minutes: float = 500.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mover-segmented level accuracy for one target season.

    Returns ``(per_bucket, directional)``:
      * ``per_bucket`` — one row per (model, actual-delta bucket): n, level MAE/RMSE,
        signed bias (proj_pg - act_pg), and mean actual/proj delta.
      * ``directional`` — one row per model: pool size, overall level MAE/bias, delta
        correlation, and directional sign-agreement fraction.
    """
    cfg = cfg or load_scoring()
    projections = project_models(target_season, season_stats, bio, cfg)

    actual = _actual(season_stats, target_season, cfg, min_minutes=0.0)[
        ["PLAYER_ID", "act_fpts_pg"]
    ]
    prior_season = _season_before(target_season)
    prior = _actual(season_stats, prior_season, cfg, min_minutes=min_prior_minutes)[
        ["PLAYER_ID", "act_fpts_pg"]
    ].rename(columns={"act_fpts_pg": "prior_fpts_pg"})

    bucket_rows: list[pd.DataFrame] = []
    dir_rows: list[dict] = []
    for name, proj in projections.items():
        pool = proj.nsmallest(pool_top_n, "rank")[["PLAYER_ID", "fpts_pg"]]
        # Restrict to players with a prior-season level so "mover" is defined, and who
        # actually played the target season (inner joins).
        m = pool.merge(prior, on="PLAYER_ID", how="inner").merge(actual, on="PLAYER_ID", how="inner")
        if m.empty:
            continue
        m["actual_delta"] = m["act_fpts_pg"] - m["prior_fpts_pg"]
        m["proj_delta"] = m["fpts_pg"] - m["prior_fpts_pg"]
        m["err"] = m["fpts_pg"] - m["act_fpts_pg"]
        m["bucket"] = _bucket(m["actual_delta"])

        g = m.groupby("bucket", observed=False)
        per = pd.DataFrame({
            "model": name,
            "bucket": BUCKET_LABELS,
            "n": g.size().reindex(BUCKET_LABELS).values,
            "level_MAE": g["err"].apply(lambda e: e.abs().mean()).reindex(BUCKET_LABELS).values,
            "level_RMSE": g["err"].apply(lambda e: np.sqrt((e ** 2).mean())).reindex(BUCKET_LABELS).values,
            "signed_bias": g["err"].mean().reindex(BUCKET_LABELS).values,
            "mean_actual_delta": g["actual_delta"].mean().reindex(BUCKET_LABELS).values,
            "mean_proj_delta": g["proj_delta"].mean().reindex(BUCKET_LABELS).values,
        })
        bucket_rows.append(per)

        sign_agree = (np.sign(m["proj_delta"]) == np.sign(m["actual_delta"])).mean()
        dir_rows.append({
            "model": name,
            "pool_n": len(m),
            "level_MAE": m["err"].abs().mean(),
            "level_bias": m["err"].mean(),
            "delta_corr": m["proj_delta"].corr(m["actual_delta"]),
            "dir_sign_acc": sign_agree,
        })

    per_bucket = pd.concat(bucket_rows, ignore_index=True)
    directional = pd.DataFrame(dir_rows)
    return per_bucket, directional
