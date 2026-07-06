"""v2 projection: shared core + empirical per-stat aging curves + durability model.

Same recency-weighted, regressed per-minute rates as the baseline, but:
  * each stat is aged with its own empirical curve (:mod:`fantasy_nba.models.aging`) from the
    player's effective current age to the target-season age, instead of one flat multiplier;
  * games played come from the age-aware durability model (:mod:`fantasy_nba.models.durability`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame
from . import durability
from ._core import COUNTING, DEFAULT_REG_MINUTES, DEFAULT_WEIGHTS, weighted_aggregates
from .aging import AGE_MAX, AGE_MIN, load_curves


def project_v2(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    target_season: str,
    cfg: ScoringConfig | None = None,
    curves: pd.DataFrame | None = None,
    gp_curve: pd.Series | None = None,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Project a per-game stat line + fantasy points for ``target_season`` (v2 model)."""
    cfg = cfg or load_scoring()
    curves = curves if curves is not None else load_curves()
    gp_curve = gp_curve if gp_curve is not None else durability.load_gp_age_curve()

    agg = weighted_aggregates(
        season_stats, bio, target_season, n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes
    )

    proj_gp = durability.project_games(agg["recent_gp"], agg["weighted_gp"], agg["target_age"], gp_curve)

    out = pd.DataFrame(
        {
            "PLAYER_ID": agg["PLAYER_ID"],
            "PLAYER_NAME": agg["PLAYER_NAME"],
            "target_season": target_season,
            "target_age": agg["target_age"].round(1),
            "gp": proj_gp,
            "mpg": agg["proj_mpg"].round(1),
        }
    )

    curve_ages = curves.index.values
    from_age = np.clip(agg["from_age"].to_numpy(), AGE_MIN, AGE_MAX)
    to_age = np.clip(agg["target_age"].to_numpy(), AGE_MIN, AGE_MAX)
    mpg = agg["proj_mpg"].to_numpy()

    for canon in COUNTING:
        col = curves[canon].to_numpy()
        f_from = np.interp(from_age, curve_ages, col)
        f_to = np.interp(to_age, curve_ages, col)
        mult = np.where(f_from > 0, f_to / f_from, 1.0)
        out[canon] = (mpg * agg[f"rate_{canon}"].to_numpy() * mult).round(2)

    out["fpts_pg"] = score_frame(out, cfg).round(2)
    out["fpts_total"] = (out["fpts_pg"] * out["gp"]).round(1)
    out = out.sort_values("fpts_total", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out
