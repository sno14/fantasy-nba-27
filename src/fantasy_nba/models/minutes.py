"""Empirical minutes-per-game (MPG) aging curve.

The backtest showed **minutes projection is the dominant error source** — feeding actual
minutes cuts per-game fantasy MAE by ~55%. Yet the baseline/v2 project minutes as a flat
recency-weighted average (``wMIN / wGP``) with *no aging*, while every per-minute rate already
gets its own empirical age curve. This module supplies the missing symmetric piece: how a
player's own MPG trends with age.

Method (same delta method as :mod:`fantasy_nba.models.aging`, minus the era de-trend)
------------------------------------------------------------------------------------
1. Per-player-season MPG = MIN / GP, on rotation-ish seasons (min-minutes + min-games filter).
2. **Delta method:** for each player's consecutive seasons (age a -> a+1) take the change in
   log(MPG), weighted by the harmonic mean of the two seasons' minutes (down-weights noise).
3. Chain the per-age deltas into a cumulative multiplicative curve, normalized to 1.0 at a
   reference age. Light smoothing tames small-sample noise at the age extremes.

No era de-trend is needed: a game is always 48 minutes, so unlike per-minute *rates* (which
drift with league-wide era shifts) MPG has no league-level inflation to remove.

The curve is applied as a **multiplicative trend on the player's own recent MPG**, not a blend
toward a population mean — a 27-year-old may legitimately play 12 or 36 MPG, so an age *level*
prior would destroy that signal. We only nudge by the *expected change* from the player's
current age to the target age.

Caveat: survivor bias (only players who keep playing form consecutive-season pairs) understates
real minutes decline at older ages, same as the rate curves.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import storage
from ._core import _season_start

AGE_REF = 27
AGE_MIN = 19
AGE_MAX = 39
MIN_MINUTES = 250.0  # per-season minutes required to contribute to the curve
MIN_GAMES = 20  # and enough games that MPG isn't a tiny-sample artifact
MPG_CAP = 40.0  # realistic per-game ceiling (league leaders sit ~37-38)
SMOOTH_WINDOW = 3
# How hard to apply the aging trend, in log space (mult ** STRENGTH). Backtested across
# 2022-23..2025-26: the full curve (1.0) over-projects the age decline (worsens minutes bias);
# 0.5 keeps essentially all the minutes-MAE gain with about half the bias inflation.
DEFAULT_STRENGTH = 0.5


def build_minutes_age_curve(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    min_minutes: float = MIN_MINUTES,
    min_games: int = MIN_GAMES,
    smooth_window: int = SMOOTH_WINDOW,
    save: bool = True,
) -> pd.Series:
    """Fit a multiplicative MPG aging curve. Returns a Series indexed by age, ~1.0 at AGE_REF."""
    df = season_stats.groupby(["PLAYER_ID", "SEASON"], as_index=False)[["MIN", "GP"]].sum()
    ages = bio[["PLAYER_ID", "SEASON", "AGE"]].drop_duplicates(["PLAYER_ID", "SEASON"])
    df = df.merge(ages, on=["PLAYER_ID", "SEASON"], how="inner")
    df = df[(df["MIN"] >= min_minutes) & (df["GP"] >= min_games)].copy()
    df["mpg"] = df["MIN"] / df["GP"]
    df["start"] = df["SEASON"].map(_season_start)
    df = df.sort_values(["PLAYER_ID", "start"])

    # Pair each season with the same player's next calendar season.
    nxt = df[["PLAYER_ID", "start", "MIN", "mpg"]].copy()
    nxt["start"] = nxt["start"] - 1
    pairs = df.merge(nxt, on=["PLAYER_ID", "start"], suffixes=("_a", "_b"))
    pairs["age_a"] = pairs["AGE"].round().astype(int)
    pairs["w"] = 2.0 / (1.0 / pairs["MIN_a"] + 1.0 / pairs["MIN_b"])  # harmonic mean of minutes

    a, b = pairs["mpg_a"], pairs["mpg_b"]
    ok = (a > 0) & (b > 0) & np.isfinite(a) & np.isfinite(b)
    sub = pd.DataFrame({"age_a": pairs["age_a"][ok], "dlog": np.log(b[ok] / a[ok]), "w": pairs["w"][ok]})

    ages_idx = list(range(AGE_MIN, AGE_MAX + 1))
    delta = sub.groupby("age_a").apply(
        lambda g: np.average(g["dlog"], weights=g["w"]), include_groups=False
    )
    delta = delta.reindex(ages_idx).fillna(0.0)
    if smooth_window and smooth_window > 1:
        delta = delta.rolling(smooth_window, center=True, min_periods=1).mean()

    # Chain deltas into a cumulative log-curve anchored at AGE_REF, then exponentiate.
    log_factor = pd.Series(0.0, index=ages_idx)
    for age in ages_idx:
        if age == AGE_REF:
            continue
        if age > AGE_REF:
            log_factor[age] = log_factor[age - 1] + delta.get(age - 1, 0.0)
        else:
            log_factor[age] = log_factor[age + 1] - delta.get(age, 0.0)

    curve = pd.Series(np.exp(log_factor.values), index=ages_idx, name="mpg_factor")
    curve.index.name = "age"
    if save:
        storage.write(curve.reset_index(), "minutes_age_curve", layer="processed")
    return curve


def load_minutes_age_curve() -> pd.Series:
    """Load the previously fitted MPG aging curve, indexed by age."""
    df = storage.read("minutes_age_curve", layer="processed")
    return df.set_index("age")["mpg_factor"]


def project_minutes(
    proj_mpg: pd.Series | float,
    from_age: pd.Series | float,
    to_age: pd.Series | float,
    curve: pd.Series,
    strength: float = DEFAULT_STRENGTH,
    mpg_cap: float = MPG_CAP,
) -> pd.Series | float:
    """Age a player's own recency-weighted MPG from ``from_age`` to ``to_age``.

    Multiplies by ``(curve[to_age] / curve[from_age]) ** strength`` — the expected fractional
    change in minutes over that age span, damped by ``strength`` (see ``DEFAULT_STRENGTH``) —
    then clips to a realistic ceiling.
    """
    curve_ages = curve.index.to_numpy(dtype=float)
    curve_vals = curve.to_numpy(dtype=float)

    def _factor(age):
        clipped = np.clip(np.asarray(age, dtype=float), AGE_MIN, AGE_MAX)
        return np.interp(clipped, curve_ages, curve_vals)

    f_from = _factor(from_age)
    f_to = _factor(to_age)
    mult = np.where(f_from > 0, (f_to / f_from) ** strength, 1.0)
    aged = np.asarray(proj_mpg, dtype=float) * mult
    aged = np.clip(aged, 0.0, mpg_cap)

    if isinstance(proj_mpg, pd.Series):
        return pd.Series(aged, index=proj_mpg.index)
    return float(aged)
