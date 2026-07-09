"""Risk ranges: floor / median / ceiling season totals via Monte Carlo.

Why this exists
---------------
The top-100 backtest showed season fantasy *totals* are dominated by **games played**, which is
nearly unpredictable from box scores (fit R^2 ~ 0.03). A single projected total therefore hides
the thing that most decides draft value: availability risk. Rather than pretend to a point
estimate, we simulate each player's season and report a distribution — so a durable 70-game
player is visibly safer than a boom/bust 55-game star with the same median.

Model
-----
For each player we draw ``n_sims`` seasons:

* **Games played** — sample from the *empirical* distribution of actual GP for draftable
  players (built no-leakage from training seasons), then scale it multiplicatively to the
  player's own projected GP (``proj_gp / pool_median``). This keeps the real, left-skewed injury
  shape (long tail of lost seasons) while letting durability projections shift a player up or
  down. Older players optionally draw from an age-appropriate pool with a fatter left tail.
* **Per-game value** — normal around the projected per-game fantasy points with sd ``sd_pg``
  (the per-game projection is well-behaved, so this is the secondary source of spread).

``total = per_game_draw * games_draw``; percentiles over the sims give floor / median / ceiling.
Games dominates the spread, exactly as the finding says it should.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._core import _season_start

MODERN_FROM = 2021  # season-start year: the current lower-availability era (post-covid)
COVID_SEASONS = ("2019-20", "2020-21")
# Prior-season minutes to qualify for the GP pool. 2000 ≈ genuine starters/stars, the tier we
# apply ranges to; a marginal-rotation pool (1000) has a fatter injury tail and mis-calibrates.
DRAFTABLE_MIN_MINUTES = 2000.0
# Residual per-game uncertainty, in fantasy points. NOT just the ~5.6 per-game projection RMSE —
# it's tuned so the resulting *season-total* p10–p90 band covers ~80% on the top-100 backtest, so
# it also absorbs the total-level variance the marginal GP pool misses (breakouts, role changes,
# model bias, and season-wide common health shocks that move a whole cohort together).
SD_PG = 9.0
DEFAULT_QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
SEASON_GAMES = 82


def build_gp_pool(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    max_start_year: int | None = None,
    modern_from: int = MODERN_FROM,
    min_prev_minutes: float = DRAFTABLE_MIN_MINUTES,
    injury_profile: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Empirical actual-GP outcomes for *draftable* players, one row per qualifying player-season.

    A player-season qualifies if the player logged ``>= min_prev_minutes`` the *previous* season
    (i.e. was rotation-caliber and thus draftable). Restricted to the modern, non-covid era and —
    for no-leakage backtesting — to seasons strictly before ``max_start_year``. Columns: ``GP``,
    ``AGE``.

    ``injury_profile`` (EXP-015 / 7.3b): a ``[SEASON, PLAYER_ID, inj_chronic_flag]`` frame
    (``injuries.chronic_flag_table``, as-of each season's Oct 1 — no leakage) adds a ``CHRONIC``
    column so :func:`simulate_ranges` can bucket by (age × chronic) instead of age alone.
    """
    g = season_stats.groupby(["PLAYER_ID", "SEASON"], as_index=False).agg(GP=("GP", "sum"), MIN=("MIN", "sum"))
    ages = bio[["PLAYER_ID", "SEASON", "AGE"]].drop_duplicates(["PLAYER_ID", "SEASON"])
    g = g.merge(ages, on=["PLAYER_ID", "SEASON"], how="left")
    g["yr"] = g["SEASON"].map(_season_start)

    prev = g[["PLAYER_ID", "yr", "MIN"]].copy()
    prev["yr"] = prev["yr"] + 1
    d = g.merge(prev.rename(columns={"MIN": "MIN_prev"}), on=["PLAYER_ID", "yr"], how="inner")
    d = d[d["MIN_prev"] >= min_prev_minutes]
    d = d[~d["SEASON"].isin(COVID_SEASONS)]
    d = d[d["yr"] >= modern_from]
    if max_start_year is not None:
        d = d[d["yr"] < max_start_year]
    if d.empty:  # early backtest seasons may predate the modern window — fall back to all non-covid
        d = g[~g["SEASON"].isin(COVID_SEASONS)]
        if max_start_year is not None:
            d = d[d["yr"] < max_start_year]
    cols = ["GP", "AGE"]
    if injury_profile is not None:
        d = d.merge(injury_profile[["SEASON", "PLAYER_ID", "inj_chronic_flag"]],
                    on=["SEASON", "PLAYER_ID"], how="left")
        d["CHRONIC"] = d["inj_chronic_flag"].fillna(0).astype(int)
        cols.append("CHRONIC")
    return d[cols].reset_index(drop=True)


def _age_bucket(age: np.ndarray) -> np.ndarray:
    # Older players carry a fatter left (injury) tail; bucket so they sample from their own pool.
    return np.where(age <= 29, 0, np.where(age <= 33, 1, 2))


def simulate_ranges(
    proj: pd.DataFrame,
    gp_pool: pd.DataFrame,
    sd_pg: float = SD_PG,
    n_sims: int = 4000,
    quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
    seed: int = 0,
) -> pd.DataFrame:
    """Add simulated total-fantasy-point ranges to a projection frame.

    ``proj`` needs ``fpts_pg``, ``gp`` and ``target_age``. Returns a copy with ``fpts_p10 ..
    fpts_p90`` (per ``quantiles``), ``fpts_median``, and a ``risk`` score (relative width of the
    p10–p90 band). Ranking-neutral: rows and order are preserved.

    When ``gp_pool`` carries a ``CHRONIC`` column (``build_gp_pool(injury_profile=...)``) *and*
    ``proj`` carries ``inj_chronic_flag`` (EXP-015 / 7.3b), draws bucket by (age × chronic) so
    chronically-injured players sample a GP pool with their own fatter left tail. A
    (age × chronic) bucket under 30 rows falls back to its age-only pool (the ``_age_bucket``
    guard pattern), then to the full pool.
    """
    rng = np.random.default_rng(seed)
    out = proj.copy().reset_index(drop=True)
    n = len(out)

    pg = out["fpts_pg"].to_numpy(dtype=float)[:, None]
    proj_gp = out["gp"].to_numpy(dtype=float)
    ages = out["target_age"].to_numpy(dtype=float)

    # Bucket the empirical pool by age; scale each player's draws to their own projected GP.
    pool_gp = gp_pool["GP"].to_numpy(dtype=float)
    pool_age_buck = _age_bucket(gp_pool["AGE"].to_numpy(dtype=float))
    age_pools = {b: pool_gp[pool_age_buck == b] for b in (0, 1, 2)}
    age_pools = {b: (v if len(v) >= 30 else pool_gp) for b, v in age_pools.items()}  # guard small buckets

    use_chronic = "CHRONIC" in gp_pool.columns and "inj_chronic_flag" in out.columns
    if use_chronic:
        pool_chronic = gp_pool["CHRONIC"].to_numpy(dtype=int)
        player_chronic = out["inj_chronic_flag"].fillna(0).to_numpy(dtype=int)
        buckets = {}
        for b in (0, 1, 2):
            for c in (0, 1):
                v = pool_gp[(pool_age_buck == b) & (pool_chronic == c)]
                buckets[b + 3 * c] = v if len(v) >= 30 else age_pools[b]
        player_buck = _age_bucket(ages) + 3 * player_chronic
    else:
        buckets = age_pools
        player_buck = _age_bucket(ages)

    gp_draws = np.empty((n, n_sims))
    for b, pool in buckets.items():
        rows = np.where(player_buck == b)[0]
        if len(rows) == 0:
            continue
        med = np.median(pool)
        samp = rng.choice(pool, size=(len(rows), n_sims), replace=True)
        # Additive re-centering: shift the empirical shape so its median = the player's proj_gp.
        # Preserves the real left-skewed injury spread (an injury costs ~the same games at any
        # baseline) and avoids the right-side compression a multiplicative scale + 82-cap causes.
        shift = (proj_gp[rows] - med)[:, None]
        gp_draws[rows] = np.clip(samp + shift, 1, SEASON_GAMES)

    pg_draws = np.clip(pg + rng.normal(0.0, sd_pg, size=(n, n_sims)), 0, None)
    totals = pg_draws * gp_draws

    qs = np.quantile(totals, quantiles, axis=1)  # shape (len(quantiles), n)
    for i, q in enumerate(quantiles):
        out[f"fpts_p{int(round(q * 100))}"] = qs[i].round(0)
    if 0.50 in quantiles:
        out["fpts_median"] = out[f"fpts_p50"]
    else:
        out["fpts_median"] = np.quantile(totals, 0.5, axis=1).round(0)
    lo, hi = out.get("fpts_p10"), out.get("fpts_p90")
    if lo is not None and hi is not None:
        out["risk"] = ((hi - lo) / out["fpts_median"].clip(lower=1)).round(3)
    return out


RANK_METHODS = ("safe", "median", "floor", "ceiling")


def rank_board(proj: pd.DataFrame, method: str = "safe", risk_lambda: float = 0.5) -> pd.DataFrame:
    """Re-sort a projection (with risk ranges) into a draft board by risk stance.

    * ``median``  — rank by expected total (``fpts_median``). Most accurate central estimate.
    * ``safe``    — rank by ``fpts_median - risk_lambda * (fpts_median - fpts_p10)``: a mild
      downside penalty. Backtests as accurate as ``median`` (Spearman ~0.57) while demoting
      injury-prone players, so it's the default — free bust protection.
    * ``floor``   — rank by ``fpts_p10`` (max safety) / ``ceiling`` — rank by ``fpts_p90`` (max upside).

    Returns a copy sorted descending by the chosen value, with ``draft_value`` and a renumbered
    ``rank``. Requires the range columns from :func:`simulate_ranges`.
    """
    if method not in RANK_METHODS:
        raise ValueError(f"method must be one of {RANK_METHODS}, got {method!r}")
    out = proj.copy()
    med = out["fpts_median"]
    if method == "median":
        val = med
    elif method == "floor":
        val = out["fpts_p10"]
    elif method == "ceiling":
        val = out["fpts_p90"]
    else:  # safe: blend median with its downside
        val = med - risk_lambda * (med - out["fpts_p10"])
    out["draft_value"] = val.round(0)
    out = out.sort_values("draft_value", ascending=False).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out
