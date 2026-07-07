"""Fast unit tests for aging + durability helpers (synthetic data, no network)."""

import numpy as np
import pandas as pd
import pytest

from fantasy_nba.models import aging, context, darko, durability, learned, minutes, uncertainty
from fantasy_nba.models._core import COUNTING


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


def test_safe_rank_demotes_the_injury_prone_peer():
    # Two equal-median players; the safe board must rank the durable one ahead of the fragile one.
    r = uncertainty.simulate_ranges(_proj([44.0, 34.0], [72, 52]), _gp_pool(), seed=3)
    # Give them matching medians so only downside separates them.
    board = uncertainty.rank_board(r, method="safe")
    durable = board.index[board["gp"] == 72][0]
    fragile = board.index[board["gp"] == 52][0]
    assert board.loc[durable, "rank"] < board.loc[fragile, "rank"]
    # median ranking is a pure central-estimate sort; ceiling favours upside.
    assert set(uncertainty.rank_board(r, method="median")["rank"]) == {1, 2}


def _synthetic_league(seasons, n_players=40, seed=0):
    """Tiny multi-season panel with all COUNTING source columns + bio ages (no network)."""
    rng = np.random.default_rng(seed)
    ss_rows, bio_rows = [], []
    # Each player has a latent skill; stats scale with it so the model has signal to learn.
    skill = rng.uniform(0.4, 1.6, size=n_players)
    for si, season in enumerate(seasons):
        for pid in range(n_players):
            gp = int(np.clip(rng.normal(68, 10), 20, 82))
            mpg = float(np.clip(rng.normal(26 * skill[pid], 4), 8, 38))
            minutes_total = gp * mpg
            s = skill[pid]
            row = {
                "SEASON": season, "PLAYER_ID": pid, "PLAYER_NAME": f"p{pid}",
                "GP": gp, "MIN": minutes_total,
                "FGM": 7 * s * gp, "FGA": 15 * s * gp, "FG3M": 2 * s * gp,
                "FTM": 3 * s * gp, "FTA": 4 * s * gp, "OREB": 1.2 * s * gp,
                "DREB": 4 * s * gp, "REB": 5.2 * s * gp, "AST": 4 * s * gp,
                "STL": 1.1 * s * gp, "BLK": 0.6 * s * gp, "TOV": 2 * s * gp,
                "PTS": 19 * s * gp,
                "USG_PCT": float(np.clip(0.12 + 0.10 * s, 0.05, 0.40)),
                "TS_PCT": float(np.clip(rng.normal(0.55, 0.03), 0.40, 0.70)),
            }
            ss_rows.append(row)
            bio_rows.append({"SEASON": season, "PLAYER_ID": pid, "AGE": 22 + si})
    return pd.DataFrame(ss_rows), pd.DataFrame(bio_rows)


def test_project_learned_schema_bounds_and_determinism():
    seasons = ["2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons)
    fast = {**learned.DEFAULT_LGBM_PARAMS, "n_estimators": 25}

    out = learned.project_learned(ss, bio, "2023-24", params=fast)
    out2 = learned.project_learned(ss, bio, "2023-24", params=fast)

    expected = {"rank", "PLAYER_ID", "PLAYER_NAME", "gp", "mpg", "fpts_pg", "fpts_total", *COUNTING}
    assert expected <= set(out.columns)
    assert out["gp"].between(1, 82).all()
    assert out["mpg"].between(0, 48).all()
    assert (out[list(COUNTING)] >= 0).all().all()  # clamped non-negative rates
    assert np.allclose(out["fpts_total"], (out["fpts_pg"] * out["gp"]).round(1))
    assert list(out["rank"]) == list(range(1, len(out) + 1))
    # random_state is fixed -> identical projections across runs.
    assert np.allclose(out["fpts_pg"].to_numpy(), out2["fpts_pg"].to_numpy())


def test_trajectory_features_slope_sign_and_learned_traj_runs():
    seasons = ["2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons)
    # Force one player's MPG to rise monotonically so the slope must come out positive.
    riser = 0
    for i, season in enumerate(seasons):
        mask = (ss["SEASON"] == season) & (ss["PLAYER_ID"] == riser)
        ss.loc[mask, "MIN"] = ss.loc[mask, "GP"] * (12 + 6 * i)  # 12,18,24,30 MPG

    traj = learned.trajectory_features(ss, "2023-24")
    assert set(learned.TRAJ_FEATURES) <= set(traj.columns)
    assert traj.loc[traj["PLAYER_ID"] == riser, "mpg_slope"].iloc[0] > 0

    # The trajectory variant (EXP-008, rejected but retained) still produces a valid board.
    fast = {**learned.DEFAULT_LGBM_PARAMS, "n_estimators": 25}
    out = learned.project_learned(ss, bio, "2023-24", params=fast, use_trajectory=True)
    assert out["gp"].between(1, 82).all() and out["mpg"].between(0, 48).all()


def test_darko_name_normalization_and_join():
    # Accents and suffixes must not break the name join to DARKO (which uses ASCII, no suffix).
    assert darko.normalize_name("Nikola Jokić") == darko.normalize_name("Nikola Jokic")
    assert darko.normalize_name("Kevin Porter Jr.") == "kevin porter"

    board = pd.DataFrame({
        "rank": [1, 2, 3],
        "PLAYER_NAME": ["Nikola Jokić", "Kevin Porter Jr.", "Nobody Here"],
        "mpg": [34.0, 25.0, 20.0],
    })
    dk = pd.DataFrame({
        "name_key": ["nikola jokic", "kevin porter"],
        "darko_name": ["Nikola Jokic", "Kevin Porter"],
        "darko_rank": pd.array([1, 200], dtype="Int64"),
        "darko_mpg": [38.0, 33.0],
        "darko_dpm": [7.4, -1.0],
        "darko_value": [90.0, 5.0],
    })
    joined, stats = darko.join_board(board, dk)
    assert stats["n_matched"] == 2 and stats["n_board"] == 3  # 'Nobody Here' is unmatched

    gaps = darko.minutes_disagreement(joined, top_n=3, min_gap=4.0)
    # Kevin Porter: 25 - 33 = -8 (we project fewer minutes than DARKO); shows up, Jokić (-4) too.
    kp = gaps.loc[gaps["PLAYER_NAME"] == "Kevin Porter Jr.", "mpg_gap"].iloc[0]
    assert kp == -8.0


def test_team_context_vacated_minutes_math():
    # Prior season: team AAA has P1(1000), P2(800), P3(600); team BBB has P4(900).
    prior = pd.DataFrame({
        "SEASON": ["2022-23"] * 4,
        "PLAYER_ID": [1, 2, 3, 4],
        "TEAM_ABBREVIATION": ["AAA", "AAA", "AAA", "BBB"],
        "MIN": [1000.0, 800.0, 600.0, 900.0],
    })
    # Target season: P1 stays AAA; P2 leaves for BBB; P3 leaves the league; P5 is a newcomer on AAA.
    team_map = pd.DataFrame({"PLAYER_ID": [1, 4, 2, 5], "team": ["AAA", "BBB", "BBB", "AAA"]})

    feat = context.team_context_features(prior, team_map, "2022-23").set_index("PLAYER_ID")

    # AAA vacated P2+P3 = 1400 of its prior 2400 -> turnover 1400/2400.
    assert feat.loc[5, "team_turnover_share"] == pytest.approx(1400 / 2400)
    # Normalized by league avg team-min = (2400+900)/2 = 1650.
    assert feat.loc[5, "team_vacated_min_norm"] == pytest.approx(1400 / 1650)
    # Newcomer P5 has no prior role; returning P1's prior share is 1000/2400.
    assert feat.loc[5, "own_prev_min_share"] == 0.0
    assert feat.loc[1, "own_prev_min_share"] == pytest.approx(1000 / 2400)
