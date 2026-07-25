"""Fast unit tests for aging + durability helpers (synthetic data, no network)."""

import numpy as np
import pandas as pd
import pytest

from fantasy_nba.models import (
    aging, analyst, breakout, coaches, context, darko, durability, injuries, learned, minutes,
    preseason, recency, rookies, rosters, uncertainty, value,
)
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


def test_chronic_profile_pool_fattens_left_tail():
    # Chronic pool rows carry a much fatter left tail; with the (age × chronic) profile the
    # chronic player's p10 must drop vs an identical durable peer (EXP-015 / 7.3b wiring).
    durable_gp = [82, 80, 78, 76, 74, 72, 70, 68, 66, 64] * 6
    chronic_gp = [70, 62, 55, 48, 40, 34, 28, 22, 16, 10] * 6
    pool = pd.DataFrame({
        "GP": durable_gp + chronic_gp,
        "AGE": [27] * 120,
        "CHRONIC": [0] * 60 + [1] * 60,
    })
    proj = _proj([40.0, 40.0], [65, 65])
    proj["inj_chronic_flag"] = [0, 1]
    r = uncertainty.simulate_ranges(proj, pool, seed=2)
    assert r.loc[1, "fpts_p10"] < r.loc[0, "fpts_p10"]

    # Without the flag column on proj, the pool's CHRONIC column is ignored — byte-identical
    # to running on a pool that never had it (same seed, same rng path).
    plain_proj = _proj([40.0, 40.0], [65, 65])
    r_plain = uncertainty.simulate_ranges(plain_proj, pool, seed=2)
    r_nochronic = uncertainty.simulate_ranges(plain_proj, pool.drop(columns="CHRONIC"), seed=2)
    assert (r_plain["fpts_p10"] == r_nochronic["fpts_p10"]).all()

    # Small chronic bucket (< 30 rows) falls back to the age-only pool: the chronic penalty
    # (vs the fat 60-row chronic pool above) must essentially vanish.
    small = pd.DataFrame({
        "GP": durable_gp + [70, 68, 66],
        "AGE": [27] * 63,
        "CHRONIC": [0] * 60 + [1] * 3,
    })
    r_small = uncertainty.simulate_ranges(proj, small, seed=2)
    assert r_small.loc[1, "fpts_p10"] > r.loc[1, "fpts_p10"] + 100  # penalty gone
    assert abs(r_small.loc[1, "fpts_p10"] - r_small.loc[0, "fpts_p10"]) < 120  # ~= durable peer


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


def test_returning_vet_universe_and_zero_blast_radius():
    # EXP-032: a player absent from the most-recent season is off the board by default, but
    # projected when listed in returning_vet_ids — and adding him must NOT move any other player.
    seasons = ["2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons)
    vet = 5
    ss = ss[~((ss["PLAYER_ID"] == vet) & (ss["SEASON"] == "2022-23"))].copy()  # missed last season
    fast = {**learned.DEFAULT_LGBM_PARAMS, "n_estimators": 25}

    base = learned.project_learned(ss, bio, "2023-24", params=fast)
    withvet = learned.project_learned(ss, bio, "2023-24", params=fast, returning_vet_ids={vet})

    assert vet not in set(base["PLAYER_ID"])                 # dropped by default
    assert vet in set(withvet["PLAYER_ID"])                  # included when listed
    vrow = withvet.set_index("PLAYER_ID").loc[vet]
    assert bool(vrow["returning_vet"]) is True
    assert not withvet[withvet["PLAYER_ID"] != vet]["returning_vet"].any()
    # aging uses the vet's OWN last-played season (2021-22, age 24) + 2 yrs to 2023-24 = 26,
    # not the under-aged recent_age+gap fallback.
    assert abs(float(vrow["target_age"]) - 26.0) < 1e-6
    # zero blast radius: every other player's per-game projection is byte-identical.
    m = base.merge(withvet, on="PLAYER_ID", suffixes=("_b", "_v"))
    assert np.allclose(m["fpts_pg_b"].to_numpy(), m["fpts_pg_v"].to_numpy(), atol=0.0)


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


def test_project_learned_use_injuries_runs_and_only_moves_gp():
    seasons = ["2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons)
    fast = {**learned.DEFAULT_LGBM_PARAMS, "n_estimators": 25}
    # Player 3 misses chunks of every season (3 spells/season -> chronic).
    rows = []
    for yr in (2019, 2020, 2021, 2022):
        for m0, m1 in ((11, 12), (1, 2), (3, 4)):
            y = yr if m0 >= 10 else yr + 1
            rows.append({"date": pd.Timestamp(f"{y}-{m0:02d}-01"), "direction": "out",
                         "notes": "sore knee", "PLAYER_ID": 3})
            rows.append({"date": pd.Timestamp(f"{y}-{m1:02d}-01"), "direction": "in",
                         "notes": "activated", "PLAYER_ID": 3})
    spells = injuries.injury_spells(pd.DataFrame(rows))

    base = learned.project_learned(ss, bio, "2023-24", params=fast)
    with_inj = learned.project_learned(ss, bio, "2023-24", params=fast,
                                       use_injuries=True, injury_table=spells)
    assert with_inj["gp"].between(1, 82).all() and with_inj["mpg"].between(0, 48).all()
    # Injury features feed the y_gp model only: per-game stat lines must be untouched.
    m = base.merge(with_inj, on="PLAYER_ID", suffixes=("_a", "_b"))
    assert np.allclose(m["mpg_a"], m["mpg_b"])
    assert np.allclose(m["pts_a"], m["pts_b"])


def test_preseason_roster_map_applies_dated_offseason_moves():
    # Prior season 2023-24: P1 & P2 on BOS, P3 on MIA (names unique -> resolution is by name).
    ss = pd.DataFrame({
        "PLAYER_ID": [1, 2, 3],
        "PLAYER_NAME": ["Alpha One", "Beta Two", "Gamma Three"],
        "SEASON": ["2023-24"] * 3,
        "TEAM_ABBREVIATION": ["BOS", "BOS", "MIA"],
        "MIN": [2000.0, 1500.0, 1800.0],
    })
    tx = pd.DataFrame({
        "date": ["2024-07-06", "2024-07-06", "2024-08-01", "2024-11-01"],
        "team": ["Celtics", "Heat", "Celtics", "Suns"],
        "acquired": ["", "• Beta Two", "", "• Gamma Three"],
        "relinquished": ["• Beta Two", "", "• Alpha One", ""],
        "notes": ["traded to Heat", "traded from Celtics", "waived", "signed (post-cutoff)"],
        "category": ["movement"] * 4,
    })
    m = rosters.preseason_roster_map(ss, tx, "2024-25").set_index("PLAYER_ID")
    assert m.loc[2, "team"] == "MIA"     # July trade applied
    assert 1 not in m.index              # waived, unsigned on Oct 1 -> off the map
    assert m.loc[3, "team"] == "MIA"     # November signing is after the cutoff -> prior team

    # Era-resolved nicknames: Hornets = New Orleans before 2013, Charlotte after 2014.
    assert rosters.team_abbreviation("Hornets", pd.Timestamp("2010-01-01")) == "NOH"
    assert rosters.team_abbreviation("Hornets", pd.Timestamp("2015-01-01")) == "CHA"
    assert rosters.team_abbreviation("Nets", pd.Timestamp("2011-07-01")) == "NJN"
    assert rosters.team_abbreviation("SuperSonics", pd.Timestamp("2010-01-01")) is None

    # Validation: P2 opens the season on MIA (agrees), P3 opens on PHX (legit miss).
    logs = pd.DataFrame({
        "SEASON": ["2024-25"] * 6,
        "PLAYER_ID": [2, 2, 2, 3, 3, 3],
        "GAME_DATE": ["2024-10-23", "2024-10-25", "2024-10-27"] * 2,
        "MIN": [30.0] * 6,
        "TEAM_ABBREVIATION": ["MIA"] * 3 + ["PHX"] * 3,
    })
    v = rosters.validate_roster_map(m.reset_index(), logs, "2024-25")
    assert v["n"] == 2 and v["agreement"] == pytest.approx(0.5)
    assert list(v["misses"]["PLAYER_ID"]) == [3]


def test_project_learned_use_vacated_runs():
    seasons = ["2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons)
    fast = {**learned.DEFAULT_LGBM_PARAMS, "n_estimators": 25}
    # Synthetic SEASON-keyed vacated table covering panel seasons + the target.
    rng = np.random.default_rng(1)
    rows = []
    for s in seasons[2:] + ["2023-24"]:
        for pid in range(40):
            rows.append({"SEASON": s, "PLAYER_ID": pid,
                         "vac_min_share_pos": rng.uniform(0, 0.3),
                         "vac_usg_pos": rng.uniform(0, 0.08),
                         "vac_fga_pm": rng.uniform(0, 0.3),
                         "vac_ast_pm": rng.uniform(0, 0.15),
                         "star_departed": int(rng.random() < 0.2),
                         "arrivals_usg_pos": rng.uniform(0, 0.08)})
    table = pd.DataFrame(rows)
    out = learned.project_learned(ss, bio, "2023-24", params=fast,
                                  use_vacated=True, vacated_table=table)
    assert out["gp"].between(1, 82).all() and out["mpg"].between(0, 48).all()
    with pytest.raises(ValueError, match="no rows for target"):
        learned.project_learned(ss, bio, "2024-25", params=fast,
                                use_vacated=True, vacated_table=table)


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


def _breakout_league():
    """Three seasons, two players: P1 is the textbook breakout archetype (rising fpts/min,
    usage up at held TS%, low minutes, age 23); P2 is declining with a TS collapse."""
    rows, bio_rows = [], []
    spec = {  # (season, pid): (mpg, pts_per_game, usg, ts)
        ("2021-22", 1): (16, 6.0, 0.16, 0.55), ("2022-23", 1): (18, 9.0, 0.19, 0.56),
        ("2023-24", 1): (20, 12.0, 0.22, 0.57),
        ("2021-22", 2): (30, 18.0, 0.25, 0.56), ("2022-23", 2): (30, 15.0, 0.23, 0.52),
        ("2023-24", 2): (30, 12.0, 0.21, 0.48),
    }
    for (season, pid), (mpg, ppg, usg, ts) in spec.items():
        gp = 70
        rows.append({
            "SEASON": season, "PLAYER_ID": pid, "PLAYER_NAME": f"p{pid}",
            "GP": gp, "MIN": gp * mpg,
            **{src: (ppg if src == "PTS" else 1.0) * gp for src in
               ["FGM", "FGA", "FG3M", "FTM", "FTA", "OREB", "DREB", "REB", "AST",
                "STL", "BLK", "TOV", "PTS"]},
            "USG_PCT": usg, "TS_PCT": ts,
        })
        yr = int(season[:4])
        bio_rows.append({"SEASON": season, "PLAYER_ID": pid, "AGE": (22 if pid == 1 else 28) + yr - 2021,
                         "DRAFT_NUMBER": "15" if pid == 1 else "Undrafted"})
    return pd.DataFrame(rows), pd.DataFrame(bio_rows)


def test_breakout_features_archetype_math():
    ss, bio = _breakout_league()
    t = breakout.breakout_feature_table(ss, bio).set_index(["SEASON", "PLAYER_ID"])

    f1 = t.loc[("2024-25", 1)] if ("2024-25", 1) in t.index else t.loc[("2023-24", 1)]
    # As-of 2023-24, P1 has one prior rise (2022-23 > 2021-22) -> streak 1; as more seasons
    # accrue the streak caps at 2. Check the 2023-24 block explicitly:
    f = t.loc[("2023-24", 1)]
    assert f["improve_streak_2y"] == 1
    assert f["usg_slope_held_ts"] == pytest.approx(0.03)   # ΔUSG at held TS
    assert f["mpg_headroom"] == pytest.approx(36 - 18)
    assert f["age_22_24"] == 1 and f["draft_pick"] == 15
    assert f["years_experience"] == 2
    g = t.loc[("2023-24", 2)]
    assert g["improve_streak_2y"] == 0
    assert g["usg_slope_held_ts"] == 0.0                    # TS collapsed -> gated to 0
    assert g["age_22_24"] == 0 and g["draft_pick"] == breakout.UNDRAFTED_PICK

    labels = breakout.breakout_labels(ss).set_index(["SEASON", "PLAYER_ID"])["y_breakout"]
    assert labels.loc[("2022-23", 1)] == 0   # +3 fpts/g-ish, below the +6 edge
    assert labels.loc[("2022-23", 2)] == 0


def test_breakout_policy_boosts_flagged_but_never_core():
    board = pd.DataFrame({
        "rank": range(1, 101),
        "PLAYER_ID": range(1, 101),
        "PLAYER_NAME": [f"p{i}" for i in range(1, 101)],
    })
    scores = pd.DataFrame({"PLAYER_ID": [95, 96, 30], "breakout_p": [0.9, 0.8, 0.99]})
    # boost 60 would carry both past the core -> the clamp stops them right after it.
    out = breakout.apply_breakout_policy(board, scores, k=2, core=50, boost=60)
    # The core is untouched: ranks 1..50 are the same players (30 is core -> not flagged).
    assert list(out.loc[out["rank"] <= 50, "PLAYER_ID"]) == list(range(1, 51))
    assert out.loc[out["PLAYER_ID"] == 95, "rank"].iloc[0] == 51
    assert out.loc[out["PLAYER_ID"] == 96, "rank"].iloc[0] == 52
    assert out["breakout_flag"].sum() == 2
    # A bounded boost moves a flagged player by ~boost, not to the core.
    out40 = breakout.apply_breakout_policy(board, scores, k=2, core=50, boost=40)
    r95 = out40.loc[out40["PLAYER_ID"] == 95, "rank"].iloc[0]
    assert 50 < r95 <= 57
    # Determinism: same input, same output.
    out2 = breakout.apply_breakout_policy(board, scores, k=2, core=50, boost=60)
    assert (out["PLAYER_ID"] == out2["PLAYER_ID"]).all()


def test_vacated_usage_features_math():
    # Prior season: AAA has P1 (guard star, departs), P2 (guard, stays), P3 (big, stays);
    # BBB has P4 (guard, stays). Target map: P1 -> BBB; everyone else returns.
    prior = pd.DataFrame({
        "SEASON": ["2023-24"] * 4,
        "PLAYER_ID": [1, 2, 3, 4],
        "TEAM_ABBREVIATION": ["AAA", "AAA", "AAA", "BBB"],
        "MIN": [1000.0, 800.0, 600.0, 900.0],
        "GP": [25, 40, 30, 45],           # P1 mpg = 40 (star threshold needs >= 30)
        "USG_PCT": [0.30, 0.20, 0.18, 0.22],
        "FGA": [500.0, 300.0, 200.0, 400.0],
        "AST": [250.0, 100.0, 50.0, 150.0],
    })
    team_map = pd.DataFrame({"PLAYER_ID": [1, 2, 3, 4], "team": ["BBB", "AAA", "AAA", "BBB"]})
    pos_of = pd.Series({1: 0, 2: 0, 3: 1, 4: 0})  # guards except P3

    f = context.vacated_features(prior, team_map, "2023-24", pos_of).set_index("PLAYER_ID")

    share1 = 1000 / 2400  # P1's share of AAA minutes
    # P2 (guard on AAA): P1's departure is same-pos vacancy; star flag set (usg .30, mpg 40).
    assert f.loc[2, "vac_min_share_pos"] == pytest.approx(share1)
    assert f.loc[2, "vac_usg_pos"] == pytest.approx(0.30 * share1)
    assert f.loc[2, "vac_fga_pm"] == pytest.approx(500 / 2400)
    assert f.loc[2, "vac_ast_pm"] == pytest.approx(250 / 2400)
    assert f.loc[2, "star_departed"] == 1
    # P3 (big on AAA): no same-pos departure, but team-level shot vacancy is shared.
    assert f.loc[3, "vac_min_share_pos"] == 0.0
    assert f.loc[3, "vac_fga_pm"] == pytest.approx(500 / 2400)
    # P4 (guard on BBB): P1 arrives in his position group -> usage compression.
    assert f.loc[4, "arrivals_usg_pos"] == pytest.approx(0.30 * share1)
    assert f.loc[4, "vac_min_share_pos"] == 0.0 and f.loc[4, "star_departed"] == 0
    # P1 himself (now on BBB): sees BBB's (zero) vacancy, not AAA's — and his own arriving
    # usage is not compression against himself.
    assert f.loc[1, "vac_min_share_pos"] == 0.0
    assert f.loc[1, "arrivals_usg_pos"] == 0.0


def test_recency_last_n_window_and_leakage():
    # Player 1 plays 40 games in 2022-23: first 20 at 20 MPG, last 20 at 34 MPG (role surged late).
    dates = pd.date_range("2022-11-01", periods=40, freq="2D").strftime("%Y-%m-%d")
    mins = [20.0] * 20 + [34.0] * 20
    logs = pd.DataFrame({
        "SEASON": ["2022-23"] * 40,
        "PLAYER_ID": [1] * 40,
        "GAME_DATE": dates,
        "MIN": mins,
        "PTS": [m * 0.5 for m in mins],  # constant 0.5 pts/min -> recent_ppm_delta ~ 0
    })
    table = recency.season_recency_table(logs, window=20)
    feat = recency.recency_features(table, "2023-24").set_index("PLAYER_ID")

    # Season MPG = mean(20*20, 34*20)/40 = 27; recent (last 20) = 34 -> delta +7.
    assert feat.loc[1, "recent_mpg"] == pytest.approx(34.0)
    assert feat.loc[1, "recent_mpg_delta"] == pytest.approx(7.0)
    assert feat.loc[1, "recent_games"] == 20
    assert feat.loc[1, "recent_ppm_delta"] == pytest.approx(0.0)  # constant rate

    # No-leakage: asking for the same season the games are in yields nothing (games are not < target).
    assert recency.recency_features(table, "2022-23").empty


def _raw_injuries(rows):
    """Verbatim-scrape-shaped frame: (date, team, acquired, relinquished, notes)."""
    return pd.DataFrame(rows, columns=["date", "team", "acquired", "relinquished", "notes"])


def test_injury_spell_pairing_on_three_transaction_sequence():
    # The implementation-plan 7.2 synthetic sequence: out -> in (closed spell), then an
    # unclosed out (season-ending) that must be capped at UNCLOSED_SPELL_DAYS.
    raw = _raw_injuries([
        ("2023-01-01", "Suns", "", "• Test Player", "sprained left ankle (out)"),
        ("2023-01-15", "Suns", "• Test Player", "", "returned to lineup"),
        ("2023-03-01", "Suns", "", "• Test Player", "torn ACL (out for season)"),
    ])
    events = injuries.explode_events(raw)
    events["PLAYER_ID"] = 7  # bypass name resolution for the pairing test
    spells = injuries.injury_spells(events)

    assert len(spells) == 2
    first, second = spells.iloc[0], spells.iloc[1]
    assert first["days"] == 14 and str(first["end"].date()) == "2023-01-15"
    assert second["days"] == injuries.UNCLOSED_SPELL_DAYS  # no acquire row -> capped
    assert "ankle" in first["notes"]

    # Feature arithmetic as-of the following Oct 1 (preseason contract).
    feats = injuries.injury_features(spells, "2023-10-01").set_index("PLAYER_ID")
    assert feats.loc[7, "inj_events_1y"] == 2
    assert feats.loc[7, "inj_days_1y"] == 14 + injuries.UNCLOSED_SPELL_DAYS
    # Last spell ended Mar 1 + 120d = Jun 29; Oct 1 is 94 days later.
    assert feats.loc[7, "inj_recency_days"] == 94
    assert feats.loc[7, "inj_chronic_flag"] == 0  # 2 spells < CHRONIC_MIN_SPELLS
    assert feats.loc[7, "inj_bodypart_severe"] == 1  # "torn ACL" matches the severe regex

    # No-leakage: as-of a date before everything -> no rows for the player.
    assert injuries.injury_features(spells, "2022-10-01").empty


def test_injury_features_windows_and_chronic_flag():
    # Three spells inside 2 years -> chronic; an old spell outside 3y is invisible.
    events = pd.DataFrame({
        "date": pd.to_datetime([
            "2018-01-01", "2018-01-10",   # old spell, > 3y before as_of
            "2023-11-01", "2023-11-08",
            "2024-01-01", "2024-01-21",
            "2024-03-01", "2024-03-06",
        ]),
        "direction": ["out", "in"] * 4,
        "notes": ["sore knee"] * 8,
        "PLAYER_ID": [1] * 8,
    })
    spells = injuries.injury_spells(events)
    feats = injuries.injury_features(spells, "2024-10-01").set_index("PLAYER_ID")
    assert feats.loc[1, "inj_events_1y"] == 3
    assert feats.loc[1, "inj_events_3y"] == 3  # 2018 spell out of window
    assert feats.loc[1, "inj_days_1y"] == 7 + 20 + 5
    assert feats.loc[1, "inj_chronic_flag"] == 1
    assert feats.loc[1, "inj_bodypart_severe"] == 0


def test_injury_name_resolution_team_disambiguation_and_hard_fail():
    # Two players sharing a normalized name on different teams (the Jalen/Jaylin lesson).
    ss = pd.DataFrame({
        "PLAYER_ID": [11, 22, 33],
        "PLAYER_NAME": ["Sam Same", "Sam Same", "Only One"],
        "SEASON": ["2023-24"] * 3,
        "TEAM_ABBREVIATION": ["OKC", "PHI", "BOS"],
    })
    raw = _raw_injuries([
        ("2024-01-05", "Thunder", "", "• Sam Same", "sore knee"),   # team resolves -> 11
        ("2024-01-06", "Celtics", "", "• Only One", "rest"),        # unique name -> 33
    ])
    events = injuries.explode_events(raw)
    resolved, stats = injuries.resolve_players(events, ss)
    assert stats["match_rate"] == 1.0
    by_name = resolved.set_index("pst_name")["PLAYER_ID"]
    assert by_name["Sam Same"] == 11 and by_name["Only One"] == 33

    # A colliding name with no team hit must hard-fail (never silently keep one row).
    raw_bad = _raw_injuries([("2024-01-05", "Lakers", "", "• Sam Same", "sore knee")])
    with pytest.raises(ValueError, match="disambiguated"):
        injuries.resolve_players(injuries.explode_events(raw_bad), ss)

    # Ongoing spell as-of mid-absence: only elapsed days count (no future leakage).
    ev = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-03-01"]),
        "direction": ["out", "in"],
        "notes": ["fractured foot"] * 2,
        "PLAYER_ID": [5, 5],
    })
    spells = injuries.injury_spells(ev)
    mid = injuries.injury_features(spells, "2024-02-01").set_index("PLAYER_ID")
    assert mid.loc[5, "inj_days_1y"] == 31  # Jan 1 -> Feb 1 only
    assert mid.loc[5, "inj_recency_days"] == 0  # still out


def test_coach_feature_table_interactions_and_depth():
    # Prior season 2023-24: AAA has P1 (young, minutes leader) + P2 (veteran backup);
    # BBB has P3. Only AAA gets a new (interim) coach for 2024-25.
    ss = pd.DataFrame({
        "SEASON": ["2023-24"] * 3,
        "PLAYER_ID": [1, 2, 3],
        "TEAM_ABBREVIATION": ["AAA", "AAA", "BBB"],
        "MIN": [1800.0, 900.0, 1500.0],
        "GP": [70, 60, 65],
    })
    bio = pd.DataFrame({
        "SEASON": ["2023-24"] * 3, "PLAYER_ID": [1, 2, 3], "AGE": [21, 28, 25],
    })
    tx = pd.DataFrame(columns=["date", "team", "acquired", "relinquished", "notes"])
    cc = pd.DataFrame({
        "season": ["2024-25"], "team": ["AAA"], "new_coach": ["New Guy"], "interim": [1],
    })

    t = coaches.coach_feature_table(ss, tx, bio, cc, seasons=["2024-25"])
    f = t.set_index("PLAYER_ID")

    assert f.loc[1, "new_coach"] == 1 and f.loc[1, "new_coach_interim"] == 1
    assert f.loc[1, "new_coach_x_depth"] == 1          # minutes leader -> depth rank 1
    assert f.loc[1, "new_coach_x_young"] == 1          # target age 22
    assert f.loc[2, "new_coach_x_depth"] == 2          # backup -> depth rank 2
    assert f.loc[2, "new_coach_x_young"] == 0          # target age 29
    assert f.loc[3, ["new_coach", "new_coach_interim",
                     "new_coach_x_depth", "new_coach_x_young"]].eq(0).all()


def test_coach_changes_csv_loads_and_is_clean():
    # Guards the committed manual dataset itself: schema, no dup (season, team),
    # interim binary, full curated era present.
    df = coaches.load_coach_changes()
    assert set(df["interim"].unique()) <= {0, 1}
    assert df["team"].str.len().eq(3).all()
    seasons = set(df["season"])
    assert {"2009-10", "2013-14", "2020-21", "2026-27"} <= seasons
    assert "2017-18" not in seasons  # the offseason with zero changes — a real fact, not a gap
    # 2026-27 rows match the June-2026 tracker state (6 completed hires).
    assert len(df[df["season"] == "2026-27"]) == 6


def test_preseason_feature_table_role_math_and_bubble_filter():
    # 2024-25 preseason: team 100 plays two October games; six players -> top-5 MIN proxy.
    rows = []
    mins_g1 = {1: 30, 2: 25, 3: 20, 4: 15, 5: 10, 6: 5}   # P6 not a "starter"
    for pid, m in mins_g1.items():
        rows.append({"SEASON": "2024-25", "PLAYER_ID": pid, "TEAM_ID": 100,
                     "GAME_ID": "G1", "GAME_DATE": "2024-10-05", "MIN": m})
    for pid, m in {1: 30, 3: 28, 4: 22, 5: 18, 6: 25}.items():  # P2 sits game 2
        rows.append({"SEASON": "2024-25", "PLAYER_ID": pid, "TEAM_ID": 100,
                     "GAME_ID": "G2", "GAME_DATE": "2024-10-08", "MIN": m})
    # 2019-20 frame: one real October game + one July-2020 bubble scrimmage (must be dropped).
    rows.append({"SEASON": "2019-20", "PLAYER_ID": 7, "TEAM_ID": 200,
                 "GAME_ID": "G3", "GAME_DATE": "2019-10-06", "MIN": 20})
    rows.append({"SEASON": "2019-20", "PLAYER_ID": 8, "TEAM_ID": 200,
                 "GAME_ID": "G4", "GAME_DATE": "2020-07-22", "MIN": 30})
    logs = pd.DataFrame(rows)

    prior = pd.DataFrame({
        "SEASON": ["2023-24"], "PLAYER_ID": [1], "MIN": [1750.0], "GP": [70],  # 25 MPG
    })
    t = preseason.preseason_feature_table(logs, prior)

    f = t[t["SEASON"] == "2024-25"].set_index("PLAYER_ID")
    assert f.loc[1, "ps_mpg"] == pytest.approx(30.0)
    assert f.loc[1, "ps_start_share"] == pytest.approx(1.0)   # top-5 both games
    assert f.loc[1, "ps_mpg_delta"] == pytest.approx(5.0)     # 30 vs prior 25 MPG
    assert f.loc[2, "ps_mpg"] == pytest.approx(25.0)          # one appearance
    assert f.loc[2, "ps_start_share"] == pytest.approx(0.5)   # started 1 of the team's 2
    assert f.loc[6, "ps_start_share"] == pytest.approx(0.5)   # 6th man in G1, top-5 in G2
    assert pd.isna(f.loc[2, "ps_mpg_delta"])                  # no prior season -> NaN, not 0

    b = t[t["SEASON"] == "2019-20"]
    assert set(b["PLAYER_ID"]) == {7}                         # bubble scrimmage row filtered


def test_project_learned_coach_and_preseason_variants_run():
    seasons = ["2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons)
    fast = {**learned.DEFAULT_LGBM_PARAMS, "n_estimators": 25}

    # Season-keyed synthetic tables covering the training seasons + target (the contract).
    blocks = []
    for s in seasons[1:] + ["2023-24"]:
        pids = ss["PLAYER_ID"].unique()
        blocks.append(pd.DataFrame({
            "SEASON": s, "PLAYER_ID": pids,
            "new_coach": (pids % 3 == 0).astype(int),
            "new_coach_interim": 0,
            "new_coach_x_depth": (pids % 3 == 0).astype(int) * (pids % 12 + 1),
            "new_coach_x_young": (pids % 6 == 0).astype(int),
            "ps_mpg": 20.0 + (pids % 10),
            "ps_mpg_delta": (pids % 5) - 2.0,
            "ps_start_share": (pids % 4) / 4.0,
        }))
    table = pd.concat(blocks, ignore_index=True)
    coach_t = table[["SEASON", "PLAYER_ID"] + coaches.COACH_FEATURES]
    ps_t = table[["SEASON", "PLAYER_ID"] + preseason.PRESEASON_FEATURES]
    # Half the pool has no preseason rows -> NaN path through LightGBM must work.
    ps_t = ps_t[ps_t["PLAYER_ID"] % 2 == 0]

    out_c = learned.project_learned(ss, bio, "2023-24", params=fast,
                                    use_coach=True, coach_table=coach_t)
    out_p = learned.project_learned(ss, bio, "2023-24", params=fast,
                                    use_preseason=True, preseason_table=ps_t)
    for out in (out_c, out_p):
        assert out["gp"].between(1, 82).all() and out["mpg"].between(0, 48).all()

    with pytest.raises(ValueError, match="coach_table"):
        learned.project_learned(ss, bio, "2023-24", params=fast, use_coach=True)
    with pytest.raises(ValueError, match="preseason_table"):
        learned.project_learned(ss, bio, "2023-24", params=fast, use_preseason=True)


def test_rookie_cohorts_and_pick_helpers():
    ss = pd.DataFrame({
        "SEASON": ["2020-21", "2021-22", "2021-22", "2022-23", "2022-23"],
        "PLAYER_ID": [1, 1, 2, 2, 3],
    })
    c = rookies.rookie_cohorts(ss)
    # P1's first row is the cache's first season -> excluded; P2 debuts 2021-22; P3 2022-23.
    assert set(map(tuple, c[["SEASON", "PLAYER_ID"]].to_numpy())) == {("2021-22", 2), ("2022-23", 3)}

    assert rookies.pick_bucket(1) == "1-5"
    assert rookies.pick_bucket(14) == "6-14"
    assert rookies.pick_bucket(rookies.UNDRAFTED_PICK) == "61-61"


def _rookie_panel(seasons, n=30, seed=0):
    """Synthetic cohorts where value declines in pick (signal for both model and baseline)."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in seasons:
        for i in range(n):
            pick = float(i * 2 + 1) if i < 25 else float(rookies.UNDRAFTED_PICK)
            mpg = max(6.0, 30.0 - 0.4 * pick + rng.normal(0, 2))
            fpm = max(0.3, 1.0 - 0.008 * pick + rng.normal(0, 0.05))
            rows.append({
                "SEASON": s, "PLAYER_ID": hash((s, i)) % 10**8, "PLAYER_NAME": f"r{i}",
                "overall_pick": pick, "log_pick": np.log(pick),
                "undrafted": int(pick >= rookies.UNDRAFTED_PICK),
                "rookie_age": 20.0 + (i % 4), "years_since_draft": 0.0, "intl_flag": i % 5 == 0,
                "n_same_pos": float(i % 6),
                **{c: 0.0 for c in rookies.VACATED_FEATURES},
                "y_mpg": mpg, "y_fpts_pm": fpm, "y_gp": max(10.0, 75.0 - 0.5 * pick),
                "min": mpg * 60,
            })
    return pd.DataFrame(rows)


def test_rookie_baseline_is_pick_monotone_and_model_runs():
    panel = _rookie_panel(["2019-20", "2020-21", "2021-22", "2022-23"])
    base = rookies.pick_order_baseline(panel, "2022-23")
    # Bucket-mean value curve: strictly better buckets never value below worse buckets.
    by_bucket = base.groupby(base["overall_pick"].map(rookies.pick_bucket))["fpts_pg"].first()
    assert by_bucket["1-5"] >= by_bucket["15-30"] >= by_bucket["61-61"]
    # Undrafted rookies carry the sentinel and land in the last bucket.
    assert (base.loc[base["undrafted"] == 1, "overall_pick"] == rookies.UNDRAFTED_PICK).all()

    proj = rookies.project_rookies(panel, "2022-23")
    assert {"mpg", "fpts_pm", "fpts_pg", "gp", "fpts_total"} <= set(proj.columns)
    assert proj["mpg"].between(0, 40).all() and (proj["fpts_pm"] >= 0).all()
    # Walk-forward contract: a target with no prior cohorts must hard-fail.
    with pytest.raises(ValueError):
        rookies.project_rookies(panel, "2019-20")


def test_rookie_gp_curve_is_empirical_bucket_mean():
    panel = _rookie_panel(["2019-20", "2020-21"])
    train = panel[panel["SEASON"] == "2019-20"]
    curve = rookies.gp_by_pick_bucket(train)
    top = train[train["overall_pick"] <= 5]["y_gp"].mean()
    assert curve["1-5"] == pytest.approx(top)


def test_replacement_level_and_vor_greedy_math():
    # 1-team league, 1 G + 1 big + 1 UTIL: board of 3 guards + 2 bigs, descending value.
    league = {"teams": 1, "roster": {"PG": 1, "C": 1, "UTIL": 1, "BENCH": 2}}
    board = pd.DataFrame({
        "PLAYER_ID": [1, 2, 3, 4, 5],
        "rank": [1, 2, 3, 4, 5],
        "fpts_pg": [50.0, 45.0, 40.0, 35.0, 30.0],
    })
    pos_of = pd.Series({1: 0, 2: 0, 3: 1, 4: 0, 5: 1})  # G G B G B

    # Greedy: P1 -> PG, P2 -> UTIL (guard slot gone), P3 -> C; P4/P5 hit the wire.
    repl = value.replacement_level(board, pos_of, league)
    assert repl["guard"] == pytest.approx(35.0)   # P4, the first guard left over
    assert repl["big"] == pytest.approx(30.0)     # P5
    assert repl["any"] == pytest.approx(35.0)     # best remaining overall

    out = value.add_vor(board, pos_of, league)
    assert out.loc[out["PLAYER_ID"] == 1, "vor"].iloc[0] == pytest.approx(50.0 - 35.0)
    assert out.loc[out["PLAYER_ID"] == 3, "vor"].iloc[0] == pytest.approx(40.0 - 30.0)
    assert out.loc[out["PLAYER_ID"] == 4, "vor"].iloc[0] == pytest.approx(0.0)
    # BENCH slots never enter the fill; vor_rank is a dense permutation.
    assert sorted(out["vor_rank"]) == [1, 2, 3, 4, 5]


def test_vor_unknown_position_measures_against_overall_wire():
    league = {"teams": 1, "roster": {"UTIL": 1}}
    board = pd.DataFrame({"PLAYER_ID": [1, 2], "rank": [1, 2], "fpts_pg": [20.0, 10.0]})
    pos_of = pd.Series(dtype=float)  # nobody has a known position
    out = value.add_vor(board, pos_of, league)
    assert (out["pos_group"] == "unknown").all()
    assert out.loc[out["PLAYER_ID"] == 1, "vor"].iloc[0] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Analyst pass (Step D2 / EXP-029): override arithmetic + trigger list
# ---------------------------------------------------------------------------

def _analyst_board(n=6):
    """Rank-ordered synthetic board with the columns apply_overrides touches."""
    return pd.DataFrame({
        "PLAYER_ID": range(1, n + 1),
        "PLAYER_NAME": [f"Player {i}" for i in range(1, n + 1)],
        "rank": range(1, n + 1),
        "fpts_pg": [40.0 - 4 * i for i in range(n)],
        "gp": [70.0] * n,
        "fpts_total": [(40.0 - 4 * i) * 70.0 for i in range(n)],
    })


def _ov(name, kind="none", value=0.0, date="2026-10-05", category="role", pos=0):
    return {"name": name, "name_key": analyst.name_key(name), "date": pd.Timestamp(date),
            "category": category, "kind": kind, "value": float(value),
            "rationale": "test", "_pos": pos}


def test_load_overrides_parses_and_validates(tmp_path):
    good = tmp_path / "good.yaml"
    good.write_text(
        "- name: LeBron James\n  date: 2026-10-05\n  category: role\n"
        "  action: {rank_delta: -8}\n  rationale: beat-writer reporting\n"
        "- name: Some Rookie\n  date: 2026-10-06\n  category: rookie\n"
        "  action: none\n  rationale: reviewed, no change\n",
        encoding="utf-8")
    entries = analyst.load_overrides(good)
    assert [e["kind"] for e in entries] == ["rank_delta", "none"]
    assert entries[0]["value"] == -8.0

    empty = tmp_path / "empty.yaml"
    empty.write_text("# only comments\n[]\n", encoding="utf-8")
    assert analyst.load_overrides(empty) == []

    for bad_body in (
        # bad category
        "- name: X\n  date: 2026-10-05\n  category: vibes\n  action: none\n  rationale: r\n",
        # two-key action
        "- name: X\n  date: 2026-10-05\n  category: role\n"
        "  action: {rank_delta: -8, fpts_delta: 1}\n  rationale: r\n",
        # unknown action key
        "- name: X\n  date: 2026-10-05\n  category: role\n"
        "  action: {mpg_delta: 3}\n  rationale: r\n",
        # empty rationale
        "- name: X\n  date: 2026-10-05\n  category: role\n  action: none\n  rationale: ' '\n",
        # missing date
        "- name: X\n  category: role\n  action: none\n  rationale: r\n",
    ):
        bad = tmp_path / "bad.yaml"
        bad.write_text(bad_body, encoding="utf-8")
        with pytest.raises(ValueError):
            analyst.load_overrides(bad)


def test_effective_overrides_latest_dated_correction_wins():
    entries = [
        _ov("Player 2", "rank_delta", -1, date="2026-10-01", pos=0),
        _ov("Player 2", "none", date="2026-10-07", pos=1),   # the dated correction
        _ov("Player 3", "fpts_delta", 2.0, date="2026-10-02", pos=2),
    ]
    eff = analyst.effective_overrides(entries)
    assert len(eff) == 2
    assert {e["name_key"]: e["kind"] for e in eff}["player 2"] == "none"


def test_apply_overrides_none_records_without_moving():
    board = _analyst_board()
    out = analyst.apply_overrides(board, [_ov("Player 3")])
    assert list(out["PLAYER_ID"]) == list(board["PLAYER_ID"])
    row = out[out["PLAYER_ID"] == 3].iloc[0]
    assert row["analyst_action"] == "none" and row["analyst_category"] == "role"
    assert row["model_rank"] == 3 and row["rank"] == 3
    # untouched rows carry empty audit fields
    assert (out.loc[out["PLAYER_ID"] != 3, "analyst_action"] == "").all()
    # the input frame is not mutated
    assert "analyst_action" not in board.columns


def test_apply_overrides_rank_delta_moves_and_clips():
    out = analyst.apply_overrides(_analyst_board(), [_ov("Player 5", "rank_delta", -3)])
    assert list(out["PLAYER_ID"]) == [1, 5, 2, 3, 4, 6]
    assert list(out["rank"]) == [1, 2, 3, 4, 5, 6]
    assert out.loc[out["PLAYER_ID"] == 5, "model_rank"].iloc[0] == 5

    # clips at the board edges rather than walking off them
    up = analyst.apply_overrides(_analyst_board(), [_ov("Player 2", "rank_delta", -99)])
    assert list(up["PLAYER_ID"])[0] == 2
    down = analyst.apply_overrides(_analyst_board(), [_ov("Player 2", "rank_delta", 99)])
    assert list(down["PLAYER_ID"])[-1] == 2


def test_apply_overrides_fpts_delta_adjusts_and_repositions():
    board = _analyst_board()  # fpts_pg: 40 36 32 28 24 20
    out = analyst.apply_overrides(board, [_ov("Player 4", "fpts_delta", 6.0)])
    row = out[out["PLAYER_ID"] == 4].iloc[0]
    assert row["fpts_pg"] == pytest.approx(34.0)
    assert row["fpts_total"] == pytest.approx(34.0 * 70.0)
    # 34 fpts/g slots between P2 (36) and P3 (32)
    assert list(out["PLAYER_ID"]) == [1, 2, 4, 3, 5, 6]
    assert list(out["rank"]) == [1, 2, 3, 4, 5, 6]
    # equal totals keep the incumbent ahead (stable)
    tie = analyst.apply_overrides(board, [_ov("Player 4", "fpts_delta", 4.0)])  # -> 32, ties P3
    assert list(tie["PLAYER_ID"]) == [1, 2, 3, 4, 5, 6]


def test_apply_overrides_unmatched_or_ambiguous_name_raises():
    with pytest.raises(ValueError, match="matches no board row"):
        analyst.apply_overrides(_analyst_board(), [_ov("Nobody Here")])
    dup = _analyst_board()
    dup.loc[5, "PLAYER_NAME"] = "Player 1"
    with pytest.raises(ValueError, match="board rows"):
        analyst.apply_overrides(dup, [_ov("Player 1", "rank_delta", -1)])


def test_trigger_list_flags_each_category():
    board = pd.DataFrame({
        "PLAYER_ID": [1, 2, 3, 4],
        "PLAYER_NAME": ["Alpha One", "Beta Two", "Gamma Three", "Rookie Seed"],
        "rank": [1, 2, 60, 90],
        "breakout_p": [0.0, 0.0, 0.9, 0.0],
        "breakout_flag": [0, 0, 1, 0],
        "market_priced": [0, 0, 0, 1],
    })
    consensus = pd.DataFrame({
        "player": ["Alpha One", "Beta Two", "Gamma Three", "Rookie Seed", "Consensus Only"],
        "consensus_rank": [1, 40, 55, 88, 120],
    })
    consensus["name_key"] = consensus["player"].map(analyst.name_key)
    known = set(board.loc[board["market_priced"] == 0, "PLAYER_NAME"].map(analyst.name_key))

    trig = analyst.trigger_list(board, consensus, known_keys=known, returnee_ids={2})
    by_name = trig.set_index("PLAYER_NAME")["triggers"].str.split(",").to_dict()
    assert "Alpha One" not in by_name                      # no gap, no flags
    assert set(by_name["Beta Two"]) == {"rank_gap", "injury_returnee"}
    assert "breakout" in by_name["Gamma Three"]
    assert set(by_name["Rookie Seed"]) == {"rookie"}
    assert set(by_name["Consensus Only"]) == {"not_on_board", "rookie"}
    # sorted by best rank on either list
    assert list(trig["PLAYER_NAME"])[0] == "Beta Two"


def test_severe_returnees_windows_on_spell_end():
    spells = pd.DataFrame({
        "PLAYER_ID": [1, 2, 3],
        "start": pd.to_datetime(["2026-01-01", "2024-01-01", "2026-02-01"]),
        "end": pd.to_datetime(["2026-06-01", "2024-06-01", "2026-05-01"]),
        "days": [151, 151, 89],
        "notes": ["torn ACL surgery", "torn achilles", "sore hamstring"],
    })
    out = analyst.severe_returnees(spells, "2026-10-01")
    assert out == {1}  # 2 ended outside 18m; 3 isn't severe


# ---------------------------------------------------------------------------
# EXP-019 (Step 11): role-change detection + lead-time arithmetic
# ---------------------------------------------------------------------------

def _role_change_log(pre=(20.0, 20), post=(30.0, 30), pid=1, start="2024-10-20"):
    """One player's season log: `pre` games at one MPG level, then `post` at another,
    one game every 2 days."""
    mins = [pre[0]] * pre[1] + [post[0]] * post[1]
    dates = pd.date_range(start, periods=len(mins), freq="2D")
    return pd.DataFrame({"PLAYER_ID": pid, "MIN": mins, "_date": dates})


def test_role_change_detected_with_correct_baseline_and_change():
    from fantasy_nba.models.eval_movers import role_change_events

    ev = role_change_events(_role_change_log())
    assert len(ev) == 1
    e = ev.iloc[0]
    # Baseline is the pre-jump level; realized change ~ +10 (well past the +6 edge).
    assert e["baseline_mpg"] == pytest.approx(20.0, abs=0.5)
    assert e["realized_change"] == pytest.approx(10.0, abs=1.0)
    # Onset: first game where the trailing-10 window clears baseline + 6 -> inside the
    # post-jump run; confirmation completes 15 games later.
    assert e["onset_date"] > pd.Timestamp("2024-10-20")
    assert (e["confirm_date"] - e["onset_date"]).days == pytest.approx(30, abs=2)


def test_role_change_ignores_small_or_unsustained_rises():
    from fantasy_nba.models.eval_movers import role_change_events

    small = role_change_events(_role_change_log(pre=(20.0, 20), post=(24.0, 30)))
    assert small.empty  # +4 < the +6 edge
    # A 10-game spike that falls back is never confirmed for 15 further games.
    mins = [20.0] * 20 + [30.0] * 10 + [20.0] * 25
    log = pd.DataFrame({"PLAYER_ID": 1, "MIN": mins,
                        "_date": pd.date_range("2024-10-20", periods=len(mins), freq="2D")})
    assert role_change_events(log).empty


def test_lead_time_table_first_move_and_sign():
    from fantasy_nba.models.eval_movers import lead_time_table

    events = pd.DataFrame({
        "PLAYER_ID": [1, 2],
        "onset_date": pd.to_datetime(["2024-12-01", "2024-12-01"]),
        "confirm_date": pd.to_datetime(["2024-12-31", "2024-12-31"]),
        "baseline_mpg": [20.0, 20.0],
        "realized_change": [10.0, 10.0],   # threshold = 20 + 0.5*10 = 25
    })
    grid = pd.date_range("2024-12-10", periods=5, freq="7D")  # 12-10 .. 2025-01-07
    proj = pd.concat([
        # player 1 crosses 25 on the 2nd grid date (12-17): lead = 31-17 = +14
        pd.DataFrame({"date": grid, "PLAYER_ID": 1, "mpg": [22.0, 26.0, 27.0, 28.0, 28.0]}),
        # player 2 only crosses after confirmation (01-07): negative lead
        pd.DataFrame({"date": grid, "PLAYER_ID": 2, "mpg": [21.0, 21.0, 22.0, 23.0, 26.0]}),
    ])
    lt = lead_time_table(events, proj)
    p1 = lt[lt["PLAYER_ID"] == 1].iloc[0]
    assert p1["detected"] and p1["lead_days"] == pytest.approx(14.0)
    p2 = lt[lt["PLAYER_ID"] == 2].iloc[0]
    assert p2["detected"] and p2["lead_days"] == pytest.approx(-7.0)
    # never crossing -> undetected, NaN lead
    lt0 = lead_time_table(events.assign(realized_change=100.0), proj)
    assert (~lt0["detected"]).all() and lt0["lead_days"].isna().all()


# ---------------------------------------------------------------------------
# Step 14 / EXP-021: learned ranges (empirical residual CDF -> piecewise CDF draws)
# ---------------------------------------------------------------------------

def test_piecewise_pg_draws_inverts_knots_and_extends_tails():
    qv = np.array([[10.0, 20.0, 30.0, 40.0]])
    u = np.array([[0.0, 0.25, 0.50, 0.75, 0.90, 1.0]])
    out = uncertainty._piecewise_pg_draws(qv, u)
    # Knots invert exactly; the lower tail extends with the q25-q50 slope down to the
    # 0-floor, the upper tail with the q75-q90 slope.
    assert np.allclose(out[0], [0.0, 10.0, 20.0, 30.0, 40.0, 40.0 + (0.10 / 0.15) * 10.0])


def test_pg_quantile_frame_shifts_by_residual_quantiles_and_clips():
    resid = np.array([-8.0, -4.0, 0.0, 4.0, 8.0])
    proj = pd.DataFrame({"PLAYER_ID": [1, 2], "fpts_pg": [30.0, 2.0]})
    qf = uncertainty.pg_quantile_frame(proj, resid)
    qcols = ["fpts_pg_q25", "fpts_pg_q50", "fpts_pg_q75", "fpts_pg_q90"]
    exp = np.quantile(resid, (0.25, 0.50, 0.75, 0.90))
    assert np.allclose(qf.loc[0, qcols].to_numpy(dtype=float), 30.0 + exp)
    # A low point estimate + negative residual quantile clips at 0, never negative.
    assert float(qf.loc[1, "fpts_pg_q25"]) == 0.0


def test_simulate_ranges_pg_quantiles_wider_cdf_wider_band_and_row_fallback():
    proj = _proj([30.0, 30.0, 30.0], [65, 65, 65])
    proj["PLAYER_ID"] = [1, 2, 3]
    qf = pd.DataFrame({
        "PLAYER_ID": [1, 2],  # player 3 missing -> falls back to the normal path
        "fpts_pg_q25": [29.0, 20.0],
        "fpts_pg_q50": [30.0, 30.0],
        "fpts_pg_q75": [31.0, 40.0],
        "fpts_pg_q90": [32.0, 48.0],
    })
    r1 = uncertainty.simulate_ranges(proj, _gp_pool(), pg_quantiles=qf, seed=5)
    r2 = uncertainty.simulate_ranges(proj, _gp_pool(), pg_quantiles=qf, seed=5)
    assert (r1["fpts_p10"] == r2["fpts_p10"]).all()  # seeded -> reproducible
    band = r1["fpts_p90"] - r1["fpts_p10"]
    assert band[1] > band[0]           # wider per-game CDF -> wider total band
    assert r1["fpts_p10"].notna().all() and r1["fpts_p90"].notna().all()
    assert band[2] > band[0]           # SD_PG=9 fallback is wider than the narrow CDF


def test_residual_pool_walks_prior_pools_via_board_cache():
    from fantasy_nba.models.backtest import _actual
    from fantasy_nba.scoring import load_scoring

    seasons = ["2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons)
    cfg = load_scoring()

    # Prefill fake boards (actual + constant +1.0 bias) for the two residual seasons of a
    # 2022-23 target -> residual_pool must consume the cache (no LightGBM fit) and return
    # residuals of exactly -1.0 from seasons strictly before the target.
    cache = {}
    for s in ("2020-21", "2021-22"):
        a = _actual(ss, s, cfg, min_minutes=0.0)
        board = a[["PLAYER_ID", "PLAYER_NAME"]].copy()
        board["fpts_pg"] = a["act_fpts_pg"] + 1.0
        board["fpts_total"] = board["fpts_pg"] * a["act_gp"]
        board = board.sort_values("fpts_total", ascending=False).reset_index(drop=True)
        board["rank"] = range(1, len(board) + 1)
        cache[s] = board

    resid = uncertainty.residual_pool(ss, bio, "2022-23", cfg, n_seasons=2,
                                      pool_top_n=10, board_cache=cache)
    assert len(resid) > 0
    assert np.allclose(resid, -1.0)
    assert "2022-23" not in cache  # the target season itself is never projected here


def test_calibrate_resid_scale_walkforward_monotone_and_best_pick():
    from fantasy_nba.models.backtest import _actual
    from fantasy_nba.scoring import load_scoring

    # Pre-modern season labels so build_gp_pool's fallback pool (non-covid, < season) exists.
    seasons = ["2012-13", "2013-14", "2014-15", "2015-16"]
    ss, bio = _synthetic_league(seasons)
    cfg = load_scoring()

    cache = {}
    for s in ("2013-14", "2014-15"):
        a = _actual(ss, s, cfg, min_minutes=0.0)
        board = a[["PLAYER_ID", "PLAYER_NAME"]].copy()
        board["fpts_pg"] = a["act_fpts_pg"] + 3.0  # biased -> narrow bands miss some actuals
        board["gp"] = a["act_gp"]
        board["target_age"] = 25.0
        board["fpts_total"] = board["fpts_pg"] * board["gp"]
        board = board.sort_values("fpts_total", ascending=False).reset_index(drop=True)
        board["rank"] = range(1, len(board) + 1)
        cache[s] = board

    resid = np.array([-6.0, -3.0, -1.0, 0.0, 1.0, 3.0, 6.0])
    best, table = uncertainty.calibrate_resid_scale(
        ss, bio, "2015-16", cfg, resid=resid, n_seasons=2, top_n=20, board_cache=cache)
    assert list(table["scale"]) == list(uncertainty.DEFAULT_RESID_SCALES)
    # Wider per-game CDF -> total-band coverage never decreases.
    assert (table["coverage"].diff().dropna() >= -1e-9).all()
    # The returned scale is the argmin of |coverage - target| (0.83 default).
    expect = table.loc[(table["coverage"] - 0.83).abs().idxmin(), "scale"]
    assert best == expect
    assert "2015-16" not in cache  # target never projected during calibration


# ---------------------------------------------------------------------------
# Step 18 — analyst-delta lifecycle: staleness flag + optional decay
# ---------------------------------------------------------------------------

def test_decay_factor_shape():
    assert analyst.decay_factor(0) == 1.0
    assert analyst.decay_factor(analyst.DECAY_FULL_GAMES) == 1.0
    mid = (analyst.DECAY_FULL_GAMES + analyst.DECAY_ZERO_GAMES) / 2
    assert analyst.decay_factor(mid) == pytest.approx(0.5)
    assert analyst.decay_factor(analyst.DECAY_ZERO_GAMES) == 0.0
    assert analyst.decay_factor(100) == 0.0


def test_apply_overrides_decay_scales_bridge_deltas_only():
    board = _analyst_board().assign(games_so_far=[20.0] * 6)  # halfway through the taper
    entries = [_ov("Player 4", "fpts_delta", 4.0, category="role", pos=0),
               _ov("Player 5", "fpts_delta", 4.0, category="injury", pos=1)]
    out = analyst.apply_overrides(board, entries, decay_from="games_so_far")
    role = out[out["PLAYER_ID"] == 4].iloc[0]
    injury = out[out["PLAYER_ID"] == 5].iloc[0]
    # role/hype = bridge -> half strength at 20 games; injury exempt -> full delta.
    assert role["fpts_pg"] == pytest.approx(28.0 + 2.0)
    assert role["analyst_decay_factor"] == pytest.approx(0.5)
    assert injury["fpts_pg"] == pytest.approx(24.0 + 4.0)
    assert injury["analyst_decay_factor"] == pytest.approx(1.0)
    # the audit action string keeps the ENTRY's delta (the factor column is the audit)
    assert role["analyst_action"] == "fpts_delta:+4"


def test_apply_overrides_without_decay_is_unchanged_and_validates_column():
    board = _analyst_board()
    out = analyst.apply_overrides(board, [_ov("Player 4", "fpts_delta", 4.0)])
    assert "analyst_decay_factor" not in out.columns
    assert out[out["PLAYER_ID"] == 4].iloc[0]["fpts_pg"] == pytest.approx(28.0 + 4.0)
    with pytest.raises(ValueError):
        analyst.apply_overrides(board, [], decay_from="games_so_far")  # column absent


def test_parse_fpts_delta_recovers_snapshot_base():
    assert analyst.parse_fpts_delta("fpts_delta:+3.5") == 3.5
    assert analyst.parse_fpts_delta("fpts_delta:-2") == -2.0
    assert analyst.parse_fpts_delta("none") == 0.0
    assert analyst.parse_fpts_delta("rank_delta:-8") == 0.0
    assert analyst.parse_fpts_delta("") == 0.0


def test_stale_entries_flags_caught_up_bridges_only():
    entries = [
        _ov("Riser Caught", "fpts_delta", 4.0, category="role", pos=0),
        _ov("Riser Partial", "fpts_delta", 4.0, category="hype", pos=1),
        _ov("Faller Caught", "fpts_delta", -3.0, category="role", pos=2),
        _ov("Injury Guy", "fpts_delta", 4.0, category="injury", pos=3),   # exempt
        _ov("No History", "fpts_delta", 4.0, category="role", pos=4),     # unskippable base
    ]
    base_then = {"riser caught": 20.0, "riser partial": 20.0, "faller caught": 30.0,
                 "injury guy": 20.0}
    base_now = {"riser caught": 24.5,    # rose >= +4 -> stale
                "riser partial": 22.0,   # rose only +2 -> not stale
                "faller caught": 26.5,   # fell >= |-3| -> stale (mirrored rule)
                "injury guy": 30.0, "no history": 30.0}
    rep = {r["name"]: r for r in analyst.stale_entries(entries, base_now, base_then)}
    assert rep["Riser Caught"]["stale"] and rep["Riser Caught"]["caught_up"] == 4.5
    assert not rep["Riser Partial"]["stale"]
    assert rep["Faller Caught"]["stale"]
    assert "Injury Guy" not in rep      # exempt category never reported
    assert "No History" not in rep      # missing base -> skipped, never guessed


def test_stale_entries_opposite_direction_move_is_not_stale():
    # The base FELL under an upgrade delta — the model disagrees; that is not "caught up".
    entries = [_ov("Diverging", "fpts_delta", 4.0, category="role")]
    rep = analyst.stale_entries(entries, {"diverging": 15.0}, {"diverging": 20.0})
    assert rep[0]["stale"] is False


def test_update_daily_staleness_end_to_end(tmp_path, monkeypatch, capsys):
    """18.1 through the real nightly code path: an old snapshot supplies base-then, the
    caught-up bridge flags analyst_stale on tonight's board, the report names it."""
    import importlib.util
    from pathlib import Path as _P

    spec = importlib.util.spec_from_file_location(
        "update_daily", _P(__file__).resolve().parents[1] / "scripts" / "update_daily.py")
    ud = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ud)

    # The archive: a snapshot on the entry date, pre-analyst base 20 (action empty).
    ros = tmp_path / "ros_board"
    ros.mkdir()
    pd.DataFrame({"PLAYER_NAME": ["Bridge Guy"], "fpts_pg": [20.0],
                  "analyst_action": [""]}).to_parquet(ros / "2027-01-05.parquet")
    monkeypatch.setattr(ud, "ROS_BOARD_DIR", ros)

    # The overrides file the nightly run reads.
    import fantasy_nba.config as cfg_mod
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "analyst_overrides.yaml").write_text(
        "- name: Bridge Guy\n  date: 2027-01-05\n  category: role\n"
        "  action: {fpts_delta: 4.0}\n  rationale: new starter per BBM\n", encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", cfg_dir)

    # Tonight's pre-analyst board: the model's base has risen 20 -> 24.5 (> the +4 delta).
    board = pd.DataFrame({"PLAYER_ID": [1], "PLAYER_NAME": ["Bridge Guy"], "rank": [1],
                          "fpts_pg": [24.5], "gp": [40.0], "fpts_total": [980.0],
                          "games_so_far": [25.0]})
    out = ud.apply_analyst_layer(board, decay=True, t0_path=None)
    row = out.iloc[0]
    assert bool(row["analyst_stale"]) is True
    # decay at 25 games -> factor 0.25 of the +4 delta on the risen base.
    assert row["analyst_decay_factor"] == pytest.approx(0.25)
    assert row["fpts_pg"] == pytest.approx(24.5 + 1.0)
    text = capsys.readouterr().out
    assert "consider retiring" in text and "Bridge Guy" in text
