"""Unit tests for the as-of-date ROS engine (models/asof.py, implementation-plan Step 10).

Synthetic, no network. Covers the STD/ROS arithmetic and the split at T, the label floors,
date→season inference, and the end-to-end T₀ contract (STD neutral, games_so_far=0,
schema, determinism, walk-forward no-leakage).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fantasy_nba.models import asof
from fantasy_nba.models._core import COUNTING
from fantasy_nba.scoring import ScoringConfig

PTS_ONLY = ScoringConfig(name="pts-only", weights={"pts": 1.0})


def _season_games(season: str, start: str, n_games: int) -> list[pd.Timestamp]:
    """Evenly spaced game dates for a season, one every 3 days from ``start``."""
    return [pd.Timestamp(start) + pd.Timedelta(days=3 * i) for i in range(n_games)]


def _synthetic_gamelogs(seasons, starts, n_players=14, games_per=60, seed=0):
    """Consistent (game_logs, season_stats, bio): season_stats is the exact aggregate of the
    per-game logs, so learned and asof labels line up the way they do on real data."""
    rng = np.random.default_rng(seed)
    skill = rng.uniform(0.5, 1.6, size=n_players)
    gl_rows, ss_rows, bio_rows = [], [], []
    for si, (season, start) in enumerate(zip(seasons, starts)):
        dates = _season_games(season, start, games_per)
        for pid in range(n_players):
            s = skill[pid]
            mpg = float(np.clip(rng.normal(24 * s, 3), 6, 38))
            played = dates  # everyone plays every game (keeps the arithmetic checkable)
            tot = {c: 0.0 for c in COUNTING}
            tmin = 0.0
            for d in played:
                mn = float(np.clip(rng.normal(mpg, 3), 2, 44))
                tmin += mn
                per = {"pts": 0.8 * s, "fgm": 0.3 * s, "fga": 0.65 * s, "fg3m": 0.08 * s,
                       "ftm": 0.16 * s, "fta": 0.2 * s, "oreb": 0.05 * s, "dreb": 0.15 * s,
                       "reb": 0.2 * s, "ast": 0.17 * s, "stl": 0.04 * s, "blk": 0.025 * s,
                       "tov": 0.07 * s}
                row = {"SEASON": season, "PLAYER_ID": pid, "PLAYER_NAME": f"p{pid}",
                       "TEAM_ABBREVIATION": "AAA" if pid % 2 else "BBB",
                       "GAME_DATE": d.strftime("%Y-%m-%d"), "MIN": mn}
                for canon, src in COUNTING.items():
                    v = round(per[canon] * mn, 3)
                    row[src] = v
                    tot[canon] += v
                gl_rows.append(row)
            ss_row = {"SEASON": season, "PLAYER_ID": pid, "PLAYER_NAME": f"p{pid}",
                      "TEAM_ABBREVIATION": "AAA" if pid % 2 else "BBB",
                      "GP": len(played), "MIN": tmin, "PF": 2.0 * len(played), "AGE": 22 + si}
            for canon, src in COUNTING.items():
                ss_row[src] = tot[canon]
            ss_rows.append(ss_row)
            bio_rows.append({"SEASON": season, "PLAYER_ID": pid, "AGE": 22 + si})
    return pd.DataFrame(gl_rows), pd.DataFrame(ss_rows), pd.DataFrame(bio_rows)


def test_std_features_arithmetic_and_last10():
    dates = _season_games("2020-21", "2020-10-20", 12)
    T = dates[2]  # first 3 games are on/before T
    rows = []
    mins = [30.0, 20.0, 10.0]
    pts = [30.0, 10.0, 6.0]
    for d, mn, p in zip(dates[:3], mins, pts):
        r = {"PLAYER_ID": 1, "GAME_DATE": d.strftime("%Y-%m-%d"), "MIN": mn,
             "PTS": p, "_date": d}
        for src in COUNTING.values():
            r.setdefault(src, 0.0)
        r["PTS"] = p
        rows.append(r)
    # a later game (after T) must be excluded from STD
    later = {"PLAYER_ID": 1, "GAME_DATE": dates[5].strftime("%Y-%m-%d"), "MIN": 99.0,
             "PTS": 99.0, "_date": dates[5]}
    for src in COUNTING.values():
        later.setdefault(src, 0.0)
    gl = pd.DataFrame(rows + [later])

    f = asof.std_features(gl, T).set_index("PLAYER_ID")
    assert f.loc[1, "std_gp"] == 3
    assert f.loc[1, "std_mpg"] == pytest.approx(20.0)          # (30+20+10)/3
    assert f.loc[1, "std_rate_pts"] == pytest.approx(46.0 / 60.0)  # (30+10+6)/(30+20+10)
    assert f.loc[1, "last10_mpg"] == pytest.approx(20.0)       # <10 games -> all of them
    assert f.loc[1, "days_since_last_game"] == pytest.approx((T - dates[2]).days)
    assert f.loc[1, "games_so_far"] == 3


def test_ros_labels_split_and_floors():
    dates = _season_games("2020-21", "2020-10-20", 20)
    T = dates[9]
    rows = []
    for pid, mn in [(1, 25.0), (2, 6.0)]:  # p1 rotation, p2 garbage-time
        for d in dates[10:]:               # 10 games strictly after T
            r = {"PLAYER_ID": pid, "GAME_DATE": d.strftime("%Y-%m-%d"), "MIN": mn,
                 "PTS": mn, "_date": d}
            for src in COUNTING.values():
                r.setdefault(src, 0.0)
            r["PTS"] = mn
            rows.append(r)
    gl = pd.DataFrame(rows)
    lab = asof.ros_labels(gl, T, min_ros=5, min_ros_minutes=200.0)
    # p1: 10 games * 25 = 250 min -> kept; p2: 10*6 = 60 min < 200 -> dropped by minutes floor
    assert set(lab["PLAYER_ID"]) == {1}
    assert lab.set_index("PLAYER_ID").loc[1, "y_ros_gp"] == 10
    assert lab.set_index("PLAYER_ID").loc[1, "y_ros_mpg"] == pytest.approx(25.0)
    # games floor also bites independently
    assert asof.ros_labels(gl[gl["_date"] >= dates[16]], T, min_ros=5, min_ros_minutes=0.0).empty


def test_season_for_date_inference():
    gl, _, _ = _synthetic_gamelogs(["2019-20", "2020-21"], ["2019-10-22", "2020-10-22"])
    gl = asof._with_dates(gl)
    # a date inside 2020-21's game range
    assert asof._season_for_date(gl, pd.Timestamp("2020-11-15")) == "2020-21"
    # a preseason date 7 days before 2020-21's first game
    assert asof._season_for_date(gl, pd.Timestamp("2020-10-15")) == "2020-21"


def test_project_asof_t0_neutrality_schema_and_determinism():
    seasons = ["2018-19", "2019-20", "2020-21", "2021-22"]
    starts = ["2018-10-16", "2019-10-22", "2020-12-22", "2021-10-19"]
    gl, ss, bio = _synthetic_gamelogs(seasons, starts, games_per=50)
    target = "2021-22"
    start = asof.season_date_bounds(asof._with_dates(gl)).set_index("SEASON").loc[target, "start"]
    T0 = (start - pd.Timedelta(days=7)).strftime("%Y-%m-%d")

    board = asof.project_asof(T0, ss, gl, bio, cfg=PTS_ONLY, target_season=target)
    # schema = project_learned's + [games_so_far, ros_gp_max]
    assert {"rank", "PLAYER_ID", "mpg", "gp", "fpts_pg", "fpts_total",
            "games_so_far", "ros_gp_max"} <= set(board.columns)
    assert (board["games_so_far"] == 0).all()          # nobody has played at T₀
    board2 = asof.project_asof(T0, ss, gl, bio, cfg=PTS_ONLY, target_season=target)
    pd.testing.assert_frame_equal(board, board2)        # deterministic (fixed seed)


def test_blend_features_reduce_to_anchors():
    # T₀ row (games_so_far=0, Marcel present) -> pure Marcel line; rookie row (no Marcel,
    # games played) -> pure STD line.
    row = {"games_so_far": [0.0, 10.0], "std_mpg": [0.0, 30.0], "proj_mpg": [24.0, np.nan]}
    for c in COUNTING:
        row[f"std_rate_{c}"] = [0.0, 1.0]
        row[f"rate_{c}"] = [0.5, np.nan]
    f = asof.add_blend_features(pd.DataFrame(row))
    assert f.loc[0, "blend_mpg"] == pytest.approx(24.0)            # T₀: pure Marcel MPG
    assert f.loc[0, "blend_pg_pts"] == pytest.approx(24.0 * 0.5)   # T₀: Marcel per-game line
    assert f.loc[1, "blend_mpg"] == pytest.approx(30.0)            # rookie: pure STD MPG
    assert f.loc[1, "blend_pg_pts"] == pytest.approx(30.0 * 1.0)   # rookie: STD per-game line


def test_asof_panel_walk_forward_no_leakage():
    # The training panel for a target must contain no rows from the target season itself.
    seasons = ["2018-19", "2019-20", "2020-21", "2021-22"]
    starts = ["2018-10-16", "2019-10-22", "2020-12-22", "2021-10-19"]
    gl, ss, bio = _synthetic_gamelogs(seasons, starts, games_per=40)
    from fantasy_nba.models._core import _season_start
    ty = _season_start("2021-22")
    train_gl = asof._with_dates(gl)[asof._with_dates(gl)["SEASON"].map(_season_start) < ty]
    train_ss = ss[ss["SEASON"].map(_season_start) < ty]
    train_bio = bio[bio["SEASON"].map(_season_start) < ty]
    panel = asof.build_asof_panel(train_ss, train_gl, train_bio)
    assert "2021-22" not in set(panel["season"])
    assert set(panel["cutpoint_offset"]) <= set(asof.CUTPOINT_OFFSETS)
