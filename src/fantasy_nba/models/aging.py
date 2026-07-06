"""Empirical per-stat aging curves via the era-detrended delta method.

The baseline used one crude multiplier for every stat. Reality is stat-specific: blocks and
rim-finishing fade fast with age, while assists and free-throw rate age gracefully. This
module measures those curves from history.

Method
------
1. Per-minute rate for each stat, per player-season (min-minutes filter to cut noise).
2. **Era de-trend:** divide each rate by that season's league (minutes-weighted) mean, giving
   a relative *index*. This removes league-wide era shifts (e.g. the 3PA explosion) so the
   curve reflects individual aging, not the league changing around the player.
3. **Delta method:** for each player's consecutive seasons (age a -> a+1) take the change in
   log(index), weighted by the harmonic mean of the two seasons' minutes. Average across all
   players at each age.
4. Chain the per-age deltas into a cumulative multiplicative curve, normalized to 1.0 at a
   reference age (27). Light smoothing tames small-sample noise at the age extremes.

Caveats (documented, not yet fixed):
* Survivor bias — only players good enough to keep playing appear in consecutive-season pairs,
  so real-world decline is somewhat understated at older ages.
* Zero-heavy stats (e.g. 3PM for non-shooters) drop out of the log-delta, biasing those curves
  toward players who already do that thing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import storage
from ._core import COUNTING, _season_start

AGE_REF = 27
AGE_MIN = 19
AGE_MAX = 39
MIN_MINUTES = 500.0  # per-season minutes required to contribute to the curve
SMOOTH_WINDOW = 3


def _player_season_rates(season_stats: pd.DataFrame, bio: pd.DataFrame, min_minutes: float) -> pd.DataFrame:
    """One row per qualified player-season with per-minute rates and era-relative indices."""
    src_cols = ["MIN", "GP"] + list(COUNTING.values())
    df = season_stats.groupby(["PLAYER_ID", "SEASON"], as_index=False)[src_cols].sum()

    ages = bio[["PLAYER_ID", "SEASON", "AGE"]].drop_duplicates(["PLAYER_ID", "SEASON"])
    df = df.merge(ages, on=["PLAYER_ID", "SEASON"], how="inner")
    df = df[df["MIN"] >= min_minutes].copy()
    df["start"] = df["SEASON"].map(_season_start)

    for canon, src in COUNTING.items():
        df[f"{canon}_rate"] = df[src] / df["MIN"]
        # League minutes-weighted mean rate for each season -> relative index.
        league = df.groupby("SEASON").apply(
            lambda g, col=f"{canon}_rate": np.average(g[col], weights=g["MIN"]),
            include_groups=False,
        )
        df[f"{canon}_idx"] = df[f"{canon}_rate"] / df["SEASON"].map(league)

    return df


def build_aging_curves(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    min_minutes: float = MIN_MINUTES,
    smooth_window: int = SMOOTH_WINDOW,
    save: bool = True,
) -> pd.DataFrame:
    """Fit and return per-stat aging curves.

    Returns a DataFrame indexed by integer ``age`` (AGE_MIN..AGE_MAX) with one column per
    stat, each a multiplicative factor normalized to 1.0 at ``AGE_REF``.
    """
    rates = _player_season_rates(season_stats, bio, min_minutes)
    rates = rates.sort_values(["PLAYER_ID", "start"])

    # Pair each season with the same player's next calendar season.
    nxt = rates.copy()
    nxt["start"] = nxt["start"] - 1
    idx_cols = [f"{c}_idx" for c in COUNTING]
    pairs = rates.merge(
        nxt[["PLAYER_ID", "start", "MIN"] + idx_cols],
        on=["PLAYER_ID", "start"],
        suffixes=("_a", "_b"),
    )
    pairs["age_a"] = pairs["AGE"].round().astype(int)
    # Harmonic mean of the two seasons' minutes -> weight (down-weights small samples).
    pairs["w"] = 2.0 / (1.0 / pairs["MIN_a"] + 1.0 / pairs["MIN_b"])

    ages = list(range(AGE_MIN, AGE_MAX + 1))
    curves = pd.DataFrame({"age": ages}).set_index("age")

    for canon in COUNTING:
        a = pairs[f"{canon}_idx_a"]
        b = pairs[f"{canon}_idx_b"]
        ok = (a > 0) & (b > 0) & np.isfinite(a) & np.isfinite(b)
        sub = pd.DataFrame(
            {"age_a": pairs["age_a"][ok], "dlog": np.log(b[ok] / a[ok]), "w": pairs["w"][ok]}
        )
        # Mean log-change from age a -> a+1, minutes-weighted.
        delta = sub.groupby("age_a").apply(
            lambda g: np.average(g["dlog"], weights=g["w"]), include_groups=False
        )
        delta = delta.reindex(ages).fillna(0.0)
        if smooth_window and smooth_window > 1:
            delta = delta.rolling(smooth_window, center=True, min_periods=1).mean()

        # Chain deltas into a cumulative log-curve anchored at AGE_REF, then exponentiate.
        log_factor = pd.Series(0.0, index=ages)
        for age in ages:
            if age == AGE_REF:
                continue
            if age > AGE_REF:
                log_factor[age] = log_factor[age - 1] + delta.get(age - 1, 0.0)
            else:  # walk downward from the reference age
                log_factor[age] = log_factor[age + 1] - delta.get(age, 0.0)
        curves[canon] = np.exp(log_factor.values)

    if save:
        storage.write(curves.reset_index(), "aging_curves", layer="processed")
    return curves


def load_curves() -> pd.DataFrame:
    """Load previously fitted aging curves, indexed by age."""
    return storage.read("aging_curves", layer="processed").set_index("age")


def _factor(curves: pd.DataFrame, stat: str, age: float) -> float:
    """Aging multiplier for a stat at a (clamped) age, interpolated between integer ages."""
    age = float(np.clip(age, AGE_MIN, AGE_MAX))
    lo = int(np.floor(age))
    hi = min(lo + 1, AGE_MAX)
    frac = age - lo
    col = curves[stat]
    return float(col.loc[lo] * (1 - frac) + col.loc[hi] * frac)


def aging_multiplier(curves: pd.DataFrame, stat: str, from_age: float, to_age: float) -> float:
    """Factor to move a stat's rate measured at ``from_age`` to ``to_age``."""
    base = _factor(curves, stat, from_age)
    if base == 0:
        return 1.0
    return _factor(curves, stat, to_age) / base
