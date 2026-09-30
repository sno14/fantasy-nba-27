"""Current platform eligibility is display context, never historical board evidence."""

import importlib

import pandas as pd
import pytest

api = importlib.import_module("fantasy_nba.api.app")


@pytest.mark.parametrize("target,expected,market_date", [
    ("2026-27", [["SF", "SG"], []], "2026-09-30"),
    ("2025-26", [[], []], None),
])
def test_board_positions_do_not_leak_into_historical_views(monkeypatch, tmp_path, target, expected, market_date):
    board = pd.DataFrame([
        {"PLAYER_ID": 10, "PLAYER_NAME": "Wing", "TEAM_ABBREVIATION": "BOS", "rank": 1, "fpts_pg": 40},
        {"PLAYER_ID": 20, "PLAYER_NAME": "Unknown", "TEAM_ABBREVIATION": "NYK", "rank": 2, "fpts_pg": 30},
    ])
    monkeypatch.setattr(api.boards, "data_ready", lambda: True)
    monkeypatch.setattr(api.boards, "ranked_board", lambda *args: board)
    market = tmp_path / "market"
    market.mkdir()
    (market / "fantasypros_2026-09-30.parquet").touch()
    monkeypatch.setattr(api, "RAW_DIR", tmp_path)
    def eligibility():
        assert target == "2026-27", "Historical requests must not read today's eligibility"
        return {10: ["SF", "SG"]}
    monkeypatch.setattr(api, "player_positions", eligibility)
    response = api.board(target=target, model="learned", stance="safe", analyst=False)
    assert [row["positions"] for row in response["rows"]] == expected
    assert [row["rank"] for row in response["rows"]] == [1, 2]
    assert response["market_date"] == market_date
    assert "positions" not in board.columns
