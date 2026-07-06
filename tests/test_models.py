"""Fast unit tests for aging + durability helpers (synthetic data, no network)."""

import numpy as np
import pandas as pd

from fantasy_nba.models import aging, durability, minutes, uncertainty


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


def _mpg_curve():
    """Peaks at AGE_REF, ramps up before, declines after — like the real fitted curve."""
    ages = list(range(minutes.AGE_MIN, minutes.AGE_MAX + 1))
    vals = [1.0 - 0.03 * abs(a - minutes.AGE_REF) for a in ages]
    return pd.Series(vals, index=pd.Index(ages, name="age"), name="mpg_factor")


def test_project_minutes_ages_veteran_down_and_youngster_up():
    c = _mpg_curve()
    # Same 30 MPG level: a 33-yr-old is trended below it, a 21-yr-old above it.
    assert minutes.project_minutes(30.0, from_age=30, to_age=33, curve=c) < 30.0
    assert minutes.project_minutes(24.0, from_age=21, to_age=24, curve=c) > 24.0


def test_project_minutes_strength_zero_is_identity():
    c = _mpg_curve()
    assert minutes.project_minutes(28.0, from_age=22, to_age=34, curve=c, strength=0.0) == 28.0


def test_project_minutes_caps_and_vectorizes():
    c = _mpg_curve()
    out = minutes.project_minutes(
        pd.Series([36.0, 8.0, 25.0]),
        from_age=pd.Series([26, 33, 22]),
        to_age=pd.Series([27, 35, 24]),
        curve=c,
    )
    assert len(out) == 3 and (out <= minutes.MPG_CAP).all() and (out >= 0).all()


def _gp_pool():
    # A plausible left-skewed star GP distribution (median ~68, injury tail).
    gp = [82, 80, 78, 76, 74, 72, 70, 68, 66, 62, 58, 52, 44, 30, 20]
    return pd.DataFrame({"GP": gp, "AGE": [27] * len(gp)})


def _proj(fpts_pg, gp, age=27):
    return pd.DataFrame({"PLAYER_NAME": [f"p{i}" for i in range(len(gp))],
                         "fpts_pg": fpts_pg, "gp": gp, "target_age": age})


def test_ranges_are_ordered_and_deterministic():
    proj = _proj([40.0, 30.0], [70, 60])
    r1 = uncertainty.simulate_ranges(proj, _gp_pool(), seed=7)
    r2 = uncertainty.simulate_ranges(proj, _gp_pool(), seed=7)
    assert (r1["fpts_p10"] <= r1["fpts_median"]).all()
    assert (r1["fpts_median"] <= r1["fpts_p90"]).all()
    assert (r1["fpts_p10"] == r2["fpts_p10"]).all()  # seeded -> reproducible


def test_durable_player_has_higher_floor_than_fragile_peer():
    # Same per-game value; the higher projected-GP player should have a higher floor total.
    r = uncertainty.simulate_ranges(_proj([40.0, 40.0], [74, 52]), _gp_pool(), seed=1)
    assert r.loc[0, "fpts_p10"] > r.loc[1, "fpts_p10"]
