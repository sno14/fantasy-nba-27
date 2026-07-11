"""Unit tests for the EXP-030 absorption layer (implementation-plan Step 16).

Synthetic data only, no network — same conventions as test_models.py. These pin the
mechanics: absence detection + strictly-pre-game baselines, blowout exclusion, joint cell
attribution, bounded-fit recovery of planted weights, honest out-event estimation, and the
redistribution arithmetic (proration, Σw ≤ 1, caps, untouched rows byte-identical).
"""

import numpy as np
import pandas as pd

from fantasy_nba.models import absorption as ab
from fantasy_nba.models._core import COUNTING
from fantasy_nba.scoring import ScoringConfig

PTS_ONLY = ScoringConfig(name="pts-only", weights={"pts": 1.0})

SEASON = "2023-24"
POS = {1: 0, 2: 0, 3: 1}  # 1,2 guards; 3 big


def _gl(rows):
    df = pd.DataFrame(rows, columns=["PLAYER_ID", "GAME_ID", "GAME_DATE", "MIN", "FGA"])
    df["SEASON"] = SEASON
    df["PLAYER_NAME"] = df["PLAYER_ID"].map(lambda p: f"p{p}")
    df["TEAM_ABBREVIATION"] = "AAA"
    return df


def _one_absence_logs():
    """Games g1–g5: all of {1 (30min), 2 (18min), 3 (24min)} play. g6: player 1 absent,
    2 plays 30 (+12), 3 plays 27 (+3). g7: 1 absent again but the game is a blowout.
    g8: 1 returns."""
    rows = []
    dates = pd.date_range("2024-01-01", periods=8, freq="D")
    for i, d in enumerate(dates, start=1):
        gid = f"g{i}"
        day = d.strftime("%Y-%m-%d")
        if i <= 5 or i == 8:
            rows += [(1, gid, day, 30.0, 15.0)]
        if i == 6:
            rows += [(2, gid, day, 30.0, 12.0), (3, gid, day, 27.0, 11.0)]
        elif i == 7:
            rows += [(2, gid, day, 34.0, 14.0), (3, gid, day, 30.0, 12.0)]
        else:
            rows += [(2, gid, day, 18.0, 8.0), (3, gid, day, 24.0, 10.0)]
    return _gl(rows)


def test_absorption_dataset_absence_baselines_and_blowout_exclusion():
    team_logs = pd.DataFrame({
        "GAME_ID": [f"g{i}" for i in range(1, 9)],
        "TEAM_ABBREVIATION": ["AAA"] * 8,
        "PLUS_MINUS": [3, -5, 8, 2, -1, 4, -30, 6],  # g7 is the blowout
    })
    ds = ab.absorption_dataset(_one_absence_logs(), team_logs=team_logs, pos_map=POS)

    # Only g6 contributes: g1–g5 have no absence, g7 is a blowout, g8 has 1 back.
    assert set(ds["GAME_ID"]) == {"g6"}
    assert len(ds) == 2

    r2 = ds[ds["PLAYER_ID"] == 2].iloc[0]
    r3 = ds[ds["PLAYER_ID"] == 3].iloc[0]
    # Strictly-pre-game baselines: 18 and 24 MPG -> deltas +12 / +3.
    assert np.isclose(r2["delta_min"], 12.0) and np.isclose(r3["delta_min"], 3.0)
    # Player 1's vacated form (trailing mean incl. his last game) = 30, landing in the
    # same-pos cell for the guard (tier: base 18 -> rotation) and the cross-pos cell for
    # the big (base 24 -> rotation). All other cells stay zero.
    assert np.isclose(r2["vac_sp1_rotation"], 30.0) and np.isclose(r2["vac_sp0_rotation"], 0.0)
    assert np.isclose(r3["vac_sp0_rotation"], 30.0) and np.isclose(r3["vac_sp1_rotation"], 0.0)
    # FGA twins carry the vacated per-game shot volume (player 1's form = 15 FGA/g).
    assert np.isclose(r2["vac_sp1_rotation_fga"], 15.0)
    assert np.isclose(r2["delta_fga"], 12.0 - 8.0)


def test_absorption_dataset_sub_rotation_absence_is_no_signal():
    # Drop player 1's form below the rotation floor -> his absence emits no rows.
    logs = _one_absence_logs()
    logs.loc[logs["PLAYER_ID"] == 1, "MIN"] = 10.0
    ds = ab.absorption_dataset(logs, pos_map=POS)
    assert ds.empty


def test_fit_absorption_recovers_planted_weights():
    rng = np.random.default_rng(0)
    n = 600
    ds = pd.DataFrame(0.0, index=range(n), columns=[
        c for cc in ab.CELL_COLS for c in (cc, f"{cc}_fga")])
    ds["vac_sp1_rotation"] = rng.uniform(15, 35, n)
    half = rng.random(n) < 0.5
    ds.loc[half, "vac_sp0_starter"] = rng.uniform(15, 35, half.sum())
    ds["delta_min"] = (0.5 * ds["vac_sp1_rotation"] + 0.15 * ds["vac_sp0_starter"]
                       + rng.normal(0, 0.5, n))
    ds["vac_sp1_rotation_fga"] = ds["vac_sp1_rotation"] / 2
    ds["delta_fga"] = 0.4 * ds["vac_sp1_rotation_fga"] + rng.normal(0, 0.3, n)
    ds["season"], ds["GAME_ID"], ds["team"], ds["PLAYER_ID"], ds["n_out"] = (
        SEASON, "g1", "AAA", 1, 1)

    w = ab.fit_absorption(ds)
    assert abs(w["theta"]["vac_sp1_rotation"] - 0.5) < 0.05
    assert abs(w["theta"]["vac_sp0_starter"] - 0.15) < 0.05
    assert all(v >= 0 for v in w["theta"].values())          # bounded fit
    assert abs(w["theta_fga"]["vac_sp1_rotation"] - 0.4) < 0.05
    # The reality-anchor table exposes every cell in both heads.
    tbl = ab.absorption_table(w)
    assert len(tbl) == 6 and {"theta_min", "theta_fga"} <= set(tbl.columns)


def test_out_events_honest_estimate_vs_oracle():
    T = pd.Timestamp("2024-01-20")
    spells = pd.DataFrame({
        "PLAYER_ID": [9, 8, 7],
        "start": pd.to_datetime(["2024-01-10", "2023-12-11", "2023-11-01"]),
        "end": pd.to_datetime(["2024-02-09", "2024-04-09", "2023-11-20"]),  # 7's is closed
        "days": [30, 120, 19],
        "notes": ["sprained ankle", "torn acl surgery", "rest"],
    })
    medians = {"normal": 14.0, "severe": 90.0}
    ev = ab.out_events_asof(spells, T, medians).set_index("PLAYER_ID")
    assert set(ev.index) == {9, 8}
    # 9: elapsed 10 of expected 14 -> max(4, MIN_REMAINING_DAYS=7) -> T+7.
    assert ev.loc[9, "out_until"] == T + pd.Timedelta(days=7)
    # 8 (severe): elapsed 40 of expected 90 -> T+50.
    assert ev.loc[8, "out_until"] == T + pd.Timedelta(days=50)
    # Oracle mode (live: out_until comes from real news) uses the recorded end.
    oracle = ab.out_events_asof(spells, T).set_index("PLAYER_ID")
    assert oracle.loc[9, "out_until"] == pd.Timestamp("2024-02-09")


def _board():
    rows = []
    for pid, name, gp, mpg, pts in [(1, "star", 40, 30.0, 24.0), (2, "backup", 50, 18.0, 9.0),
                                    (3, "big", 50, 24.0, 14.0), (4, "other_team", 50, 20.0, 10.0)]:
        r = {"rank": pid, "PLAYER_ID": pid, "PLAYER_NAME": name, "gp": gp, "mpg": mpg,
             **{c: 0.0 for c in COUNTING}, "pts": pts}
        r["fpts_pg"] = pts
        r["fpts_total"] = round(pts * gp, 1)
        rows.append(r)
    return pd.DataFrame(rows)


TEAMS = {1: "AAA", 2: "AAA", 3: "AAA", 4: "BBB"}
THETA = {c: 0.0 for c in ab.CELL_COLS} | {"vac_sp1_rotation": 0.5, "vac_sp0_rotation": 0.1}
WEIGHTS = {"theta": THETA, "intercept": 0.0,
           "theta_fga": {c: 0.0 for c in ab.CELL_COLS}, "intercept_fga": 0.0}


def test_redistribute_board_flows_prorated_minutes_and_rescores():
    T, season_end = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-01")
    out_events = pd.DataFrame({"PLAYER_ID": [1], "out_until": [season_end]})  # f = 1
    b = ab.redistribute_board(_board(), out_events, TEAMS, POS | {4: 0}, WEIGHTS,
                              T, season_end, PTS_ONLY)
    b = b.set_index("PLAYER_ID")
    # Backup (same-pos rotation, w=0.5): 18 -> 33; big (cross-pos rotation, w=0.1): 24 -> 27.
    assert np.isclose(b.loc[2, "mpg"], 33.0) and np.isclose(b.loc[2, "redist_mpg"], 15.0)
    assert np.isclose(b.loc[3, "mpg"], 27.0)
    # Rates held: pts scale with minutes; fpts re-scored through the config; totals follow.
    assert np.isclose(b.loc[2, "pts"], round(9.0 * 33 / 18, 2))
    assert np.isclose(b.loc[2, "fpts_pg"], b.loc[2, "pts"])
    assert np.isclose(b.loc[2, "fpts_total"], round(b.loc[2, "fpts_pg"] * 50, 1))
    # The OUT player and the other team's player are untouched, byte-identical.
    for pid in (1, 4):
        for col in ["gp", "mpg", "pts", "fpts_pg", "fpts_total"]:
            assert b.loc[pid, col] == _board().set_index("PLAYER_ID").loc[pid, col]

    # Proration: return halfway to season end -> exactly half the flow.
    halfway = T + (season_end - T) / 2
    ev2 = pd.DataFrame({"PLAYER_ID": [1], "out_until": [halfway]})
    b2 = ab.redistribute_board(_board(), ev2, TEAMS, POS | {4: 0}, WEIGHTS,
                               T, season_end, PTS_ONLY).set_index("PLAYER_ID")
    assert np.isclose(b2.loc[2, "redist_mpg"], 7.5)


def test_redistribute_normalizes_when_weights_exceed_one_and_caps_mpg():
    theta = {c: 1.0 for c in ab.CELL_COLS}
    weights = {"theta": theta, "intercept": 0.0, "theta_fga": theta, "intercept_fga": 0.0}
    T, season_end = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-01")
    out_events = pd.DataFrame({"PLAYER_ID": [1], "out_until": [season_end]})
    b = ab.redistribute_board(_board(), out_events, TEAMS, POS | {4: 0}, weights,
                              T, season_end, PTS_ONLY).set_index("PLAYER_ID")
    # Σw = 2 -> scaled to 1: the 30 vacated minutes split 15/15; big capped later anyway.
    assert np.isclose(b.loc[2, "redist_mpg"] + b.loc[3, "redist_mpg"], 30.0)
    assert b.loc[2, "mpg"] <= ab.MPG_CAP and b.loc[3, "mpg"] <= ab.MPG_CAP

    # A sub-rotation OUT player (mpg < 15) triggers nothing.
    board = _board()
    board.loc[board["PLAYER_ID"] == 1, "mpg"] = 10.0
    b3 = ab.redistribute_board(board, out_events, TEAMS, POS | {4: 0}, weights,
                               T, season_end, PTS_ONLY)
    assert (b3["redist_mpg"] == 0).all()


def test_redistribute_mpg_grid_moves_only_out_windows():
    dates = [pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-25")]
    grid = pd.concat([
        pd.DataFrame({"date": d, "PLAYER_ID": [1, 2, 3], "mpg": [30.0, 18.0, 24.0]})
        for d in dates
    ], ignore_index=True)
    spells = pd.DataFrame({
        "PLAYER_ID": [1], "start": [pd.Timestamp("2024-01-01")],
        "end": [pd.Timestamp("2024-01-15")], "days": [14], "notes": ["knee"],
    })
    gl_season = ab._with_dates(_one_absence_logs())
    out = ab.redistribute_mpg_grid(grid, spells, {"normal": 14.0, "severe": 90.0},
                                   gl_season, POS, WEIGHTS, pd.Timestamp("2024-03-01"))
    d1 = out[out["date"] == dates[0]].set_index("PLAYER_ID")
    d2 = out[out["date"] == dates[1]].set_index("PLAYER_ID")
    assert d1.loc[2, "mpg"] > 18.0          # spell open on Jan 5 -> flow to the backup
    assert np.isclose(d2.loc[2, "mpg"], 18.0)  # spell closed by Jan 25 -> untouched
