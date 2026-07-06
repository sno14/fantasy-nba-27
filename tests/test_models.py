"""Fast unit tests for aging + durability helpers (synthetic data, no network)."""

import numpy as np
import pandas as pd

from fantasy_nba.models import aging, durability


def _flat_curves():
    ages = range(aging.AGE_MIN, aging.AGE_MAX + 1)
    return pd.DataFrame({"pts": 1.0, "reb": 1.0}, index=pd.Index(ages, name="age"))


def _declining_curve():
    ages = list(range(aging.AGE_MIN, aging.AGE_MAX + 1))
    # 1.0 at AGE_REF, linear decline of 0.02/yr after, mild rise before.
    vals = [1.0 - 0.02 * (a - aging.AGE_REF) for a in ages]
    return pd.DataFrame({"pts": vals}, index=pd.Index(ages, name="age"))


def test_flat_curve_multiplier_is_one():
    c = _flat_curves()
    assert aging.aging_multiplier(c, "pts", 22, 30) == 1.0


def test_declining_curve_ages_down():
    c = _declining_curve()
    # Moving from 28 to 32 on a declining curve must reduce production.
    assert aging.aging_multiplier(c, "pts", 28, 32) < 1.0


def test_factor_interpolates_between_ages():
    c = _declining_curve()
    f28, f29 = c["pts"].loc[28], c["pts"].loc[29]
    assert np.isclose(aging._factor(c, "pts", 28.5), (f28 + f29) / 2)


def test_factor_clamps_out_of_range_age():
    c = _declining_curve()
    # Ages beyond the fitted range clamp to the endpoints rather than extrapolating.
    assert aging._factor(c, "pts", 99) == aging._factor(c, "pts", aging.AGE_MAX)


def test_project_games_blends_and_clamps():
    curve = pd.Series(70.0, index=range(aging.AGE_MIN, aging.AGE_MAX + 1))
    curve.index.name = "age"
    # Healthy recent history + healthy age prior -> high but <= 82.
    gp = durability.project_games(recent_gp=80, weighted_gp=78, age=25, curve=curve)
    assert 1 <= gp <= 82

    # A vectorized call returns a Series of the right length, all within bounds.
    out = durability.project_games(
        recent_gp=pd.Series([82, 10, 50]),
        weighted_gp=pd.Series([80, 20, 55]),
        age=pd.Series([24, 36, 29]),
        curve=curve,
    )
    assert len(out) == 3 and out.between(1, 82).all()
