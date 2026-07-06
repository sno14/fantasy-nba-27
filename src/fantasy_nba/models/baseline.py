"""Marcel-style baseline projection.

The honest benchmark every fancier model must beat. Adapted from Tom Tango's "Marcel the
Monkey" method (the standard simple baseline in baseball) to NBA per-minute rates:

1. **Recency-weight** the last N seasons (default 3, weights 5/4/3), weighted by minutes.
2. **Regress** each per-minute rate toward the league mean; the fewer minutes a player has
   logged, the harder his rate is pulled toward average (small-sample skepticism).
3. **Age curve** applied to production rates (rough single curve, peak ~27).
4. **Project minutes & games** from recency-weighted playing time.

Steps 1-2 (and the shared aggregation) live in :mod:`fantasy_nba.models._core`. This module
supplies the baseline's crude single age curve and naive games projection. The v2 model
(:mod:`fantasy_nba.models.projection`) swaps in empirical per-stat aging and a durability
model while reusing the same core.

Caveats: only players active in the most recent season are projected; double/triple-double
bonuses are applied to the average line (undercounts).
"""

from __future__ import annotations

import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame
from ._core import COUNTING, DEFAULT_REG_MINUTES, DEFAULT_WEIGHTS, _season_start, weighted_aggregates

# Re-exported for backwards compatibility (older imports used baseline.COUNTING / _season_start).
__all__ = ["project_baseline", "COUNTING", "_season_start"]

AGE_PIVOT = 27.0
AGE_YOUNG_SLOPE = 0.010  # per year below pivot (improvement)
AGE_OLD_SLOPE = 0.008  # per year above pivot (decline)
AGE_FACTOR_BOUNDS = (0.80, 1.10)
DURABILITY_PRIOR = 66.0  # league-ish games-played anchor
DURABILITY_WEIGHT = 0.35  # how hard projected GP is pulled toward the prior


def _age_factor(age: float) -> float:
    if pd.isna(age):
        return 1.0
    if age < AGE_PIVOT:
        f = 1.0 + (AGE_PIVOT - age) * AGE_YOUNG_SLOPE
    else:
        f = 1.0 - (age - AGE_PIVOT) * AGE_OLD_SLOPE
    lo, hi = AGE_FACTOR_BOUNDS
    return min(hi, max(lo, f))


def project_baseline(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    target_season: str,
    cfg: ScoringConfig | None = None,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Project a per-game stat line + fantasy points for ``target_season`` (baseline model)."""
    cfg = cfg or load_scoring()

    agg = weighted_aggregates(
        season_stats, bio, target_season, n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes
    )

    age_factor = agg["target_age"].map(_age_factor)
    proj_gp = (DURABILITY_WEIGHT * DURABILITY_PRIOR + (1 - DURABILITY_WEIGHT) * agg["weighted_gp"])
    proj_gp = proj_gp.clip(1, 82).round()

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
    for canon in COUNTING:
        out[canon] = (agg["proj_mpg"] * agg[f"rate_{canon}"] * age_factor).round(2)

    out["fpts_pg"] = score_frame(out, cfg).round(2)
    out["fpts_total"] = (out["fpts_pg"] * out["gp"]).round(1)
    out = out.sort_values("fpts_total", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out
