"""P9 holds approved per-minute rates and the separate Board-B rate leg."""

import pandas as pd
import pytest
from fastapi import HTTPException

from fantasy_nba.minutes_scenario import minutes_scenario
from fantasy_nba.models.analyst import apply_overrides, name_key
from fantasy_nba.scoring import ScoringConfig, load_scoring, score_frame


def approved_row():
    cfg = load_scoring()
    row = {"PLAYER_ID": 1, "PLAYER_NAME": "Example", "rank": 1, "mpg": 30.0, "gp": 70,
           "pts": 15.0, "reb": 6.0, "ast": 4.0, "fgm": 6.0, "fga": 12.0,
           "fg3m": 1.0, "ftm": 3.0, "fta": 4.0, "stl": 1.0, "blk": 0.5, "tov": 2.0}
    board = pd.DataFrame([row])
    board["fpts_pg"] = score_frame(board, cfg).round(2)
    board["fpts_total"] = (board["fpts_pg"] * board["gp"]).round(1)
    entry = {"name": "Example", "name_key": name_key("Example"), "date": pd.Timestamp("2026-10-05"),
             "category": "role", "kind": "fpts_delta", "value": -2.0,
             "target_mpg": 33.0, "fpts_delta": -2.0, "rank_delta": None,
             "rationale": "test", "_pos": 0}
    return apply_overrides(board, [entry], cfg=cfg).iloc[0].to_dict(), cfg


def test_approved_composite_baseline_and_retained_rate_leg():
    row, cfg = approved_row()
    baseline = minutes_scenario(row, None, cfg)
    assert baseline["enabled"]
    assert baseline["assumed_fpts_pg"] == pytest.approx(row["fpts_pg"])
    assert baseline["minutes_contribution"] == 0
    assert baseline["retained_rate_residual"] == -2
    changed = minutes_scenario(row, 36.0, cfg)
    assert changed["assumed_fpts_pg"] == pytest.approx(
        changed["scored_assumed_fpts_pg"] + changed["retained_rate_residual"], abs=0.01)
    assert changed["fpts_pg_change"] == pytest.approx(changed["minutes_contribution"])
    assert row["mpg"] == 33.0  # the scenario never edits the approved row


def test_scenario_rescores_bonus_instead_of_scaling_final_fpts():
    cfg = ScoringConfig("bonus", {"pts": 1}, {"double_double": 5}, ("pts", "reb"), 10)
    row = {"PLAYER_ID": 2, "PLAYER_NAME": "Bonus", "mpg": 30.0, "pts": 9.0, "reb": 9.0,
           "fpts_pg": 9.0, "analyst_action": "none"}
    result = minutes_scenario(row, 40.0, cfg)
    assert result["enabled"]
    assert result["scored_assumed_fpts_pg"] == 17.0  # 12 points + 5 double-double bonus
    assert result["assumed_fpts_pg"] == 17.0


def test_missing_or_non_reconciling_inputs_disable_scenario():
    row, cfg = approved_row()
    assert not minutes_scenario({**row, "pts": None}, 36, cfg)["enabled"]
    assert not minutes_scenario({**row, "mpg": 0}, 36, cfg)["enabled"]
    assert not minutes_scenario({**row, "fpts_pg": row["fpts_pg"] + 5}, 36, cfg)["enabled"]
    assert not minutes_scenario({**row, "analyst_action": "fpts_delta:nan"}, 36, cfg)["enabled"]


def test_zero_and_out_of_range_assumptions_are_rejected():
    row, cfg = approved_row()
    for value in (0, -1, 0.04, 42.1, float("nan")):
        with pytest.raises(ValueError):
            minutes_scenario(row, value, cfg)
    assert minutes_scenario(row, 36.24, cfg)["assumed_mpg"] == 36.2


def test_local_endpoint_uses_approved_board_and_never_writes(monkeypatch):
    from fantasy_nba.api import minutes as api

    row, cfg = approved_row()
    board = pd.DataFrame([row])
    monkeypatch.setattr(api.boards, "data_ready", lambda: True)
    monkeypatch.setattr(api.boards, "ranked_board", lambda *args: board)
    monkeypatch.setattr(api, "load_scoring", lambda: cfg)
    result = api.player_minutes_scenario(1, mpg=36.0)
    assert result["enabled"] and result["retained_rate_residual"] == -2
    assert board.iloc[0]["mpg"] == 33.0
    with pytest.raises(HTTPException) as exc:
        api.player_minutes_scenario(1, mpg=0)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        api.player_minutes_scenario(99, mpg=30)
    assert exc.value.status_code == 404
