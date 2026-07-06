"""Games-played (durability) model.

The baseline projected games by regressing recent GP toward a flat league anchor (66). That
ignores that injury risk rises with age. Here we fit an **age -> expected games** curve from
history and blend a player's recent availability toward the age-appropriate expectation.

Still deliberately simple: real durability also depends on injury history, position, and
minutes load — refinements for later. But an age-aware prior already beats a flat constant,
especially for older stars.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import storage
from ._core import _season_start

DUR_MIN_MINUTES = 200.0  # only rotation-ish player-seasons inform the curve
AGE_MIN = 19
AGE_MAX = 40
RECENT_BLEND = 0.55  # weight on the player's own recent GP vs. the age prior
SMOOTH_WINDOW = 3


def build_gp_age_curve(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    min_minutes: float = DUR_MIN_MINUTES,
    smooth_window: int = SMOOTH_WINDOW,
    save: bool = True,
) -> pd.Series:
    """Fit expected games played as a function of age. Returns a Series indexed by age."""
    df = season_stats.groupby(["PLAYER_ID", "SEASON"], as_index=False)[["GP", "MIN"]].sum()
    ages = bio[["PLAYER_ID", "SEASON", "AGE"]].drop_duplicates(["PLAYER_ID", "SEASON"])
    df = df.merge(ages, on=["PLAYER_ID", "SEASON"], how="inner")
    df = df[df["MIN"] >= min_minutes].copy()

    # Exclude the covid-shortened seasons so the GP prior reflects normal 82-game years.
    df = df[~df["SEASON"].isin({"2019-20", "2020-21"})]
    df["age"] = df["AGE"].round().astype(int)

    curve = df.groupby("age")["GP"].mean().reindex(range(AGE_MIN, AGE_MAX + 1))
    curve = curve.interpolate(limit_direction="both")
    if smooth_window and smooth_window > 1:
        curve = curve.rolling(smooth_window, center=True, min_periods=1).mean()
    curve = curve.clip(1, 82)
    curve.name = "expected_gp"
    curve.index.name = "age"

    if save:
        storage.write(curve.reset_index(), "gp_age_curve", layer="processed")
    return curve


def load_gp_age_curve() -> pd.Series:
    df = storage.read("gp_age_curve", layer="processed")
    return df.set_index("age")["expected_gp"]


def project_games(
    recent_gp: pd.Series | float,
    weighted_gp: pd.Series | float,
    age: pd.Series | float,
    curve: pd.Series,
    recent_blend: float = RECENT_BLEND,
) -> pd.Series | float:
    """Projected games = blend(recent availability, age-based expectation).

    ``recent_gp`` is last season's games; ``weighted_gp`` the recency-weighted average.
    We use the average of those two as the player's availability signal, then blend toward
    the age prior.
    """
    prior = _lookup(curve, age)
    own = 0.5 * _to_num(recent_gp) + 0.5 * _to_num(weighted_gp)
    projected = recent_blend * own + (1 - recent_blend) * prior
    if isinstance(projected, pd.Series):
        return projected.clip(1, 82).round()
    return float(np.clip(round(projected), 1, 82))


def _to_num(x):
    return x if isinstance(x, pd.Series) else float(x)


def _lookup(curve: pd.Series, age):
    """Age -> expected GP, clamped to the fitted age range."""
    if isinstance(age, pd.Series):
        a = age.clip(AGE_MIN, AGE_MAX).round().astype(int)
        return a.map(curve).fillna(curve.mean())
    a = int(np.clip(round(age), AGE_MIN, AGE_MAX))
    return float(curve.get(a, curve.mean()))
