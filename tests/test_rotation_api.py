from __future__ import annotations

import pandas as pd

from fantasy_nba.api.rotation import build_rotation, latest_previews


def test_rotation_keeps_board_and_preview_minutes_separate(tmp_path):
    early = tmp_path / "2026-09-01-knicks.yaml"
    early.write_text("""team: NYK
preview_date: 2026-09-01
sum_budget_mpg: 240
rows:
  - {player: A, budget_mpg: 240, bbm_mpg: '30'}
""", encoding="utf-8")
    late = tmp_path / "2026-09-29-knicks.yaml"
    late.write_text("""team: NYK
preview_date: 2026-09-29
budget_gate: failed - unresolved roster
sum_budget_mpg: null
rows:
  - {player: A, budget_mpg: null, bbm_mpg: '32'}
""", encoding="utf-8")
    base = pd.DataFrame([
        {"PLAYER_ID": 1, "PLAYER_NAME": "A", "TEAM_ABBREVIATION": "NYK", "rank": 2, "mpg": 28.0, "fpts_pg": 30.0},
        {"PLAYER_ID": 2, "PLAYER_NAME": "B", "TEAM_ABBREVIATION": "NYK", "rank": 8, "mpg": None, "fpts_pg": 18.0},
    ])
    approved = base.copy()
    approved.loc[0, "mpg"] = 31.0
    approved.loc[0, "fpts_pg"] = 33.0
    approved["analyst_action"] = ["target_mpg:31", None]
    approved["analyst_date"] = ["2026-09-29", None]
    ros = pd.DataFrame([{"PLAYER_ID": 1, "TEAM_ABBREVIATION": "NYK", "mpg": 32.0,
                         "fpts_pg": 34.0, "redist_mpg": 1.2, "status_override": None}])

    result = build_rotation(base, approved, latest_previews(tmp_path), ros, "2026-10-23")
    team = result["teams"][0]
    assert team["modelMinutes"] == 28.0
    assert team["boardMinutes"] == 31.0
    assert team["gapTo240"] == -209.0
    assert team["boardMissing"] == 1
    assert team["preview"]["date"] == "2026-09-29"
    assert team["preview"]["hasClosedBudget"] is False
    player = team["players"][0]
    assert player["mpgDelta"] == 3.0
    assert player["fpgDelta"] == 3.0
    assert player["previewStatedMpg"] == "32"
    assert player["previewBudgetMpg"] is None
    assert player["rosMpg"] == 32.0 and player["redistMpg"] == 1.2
    assert approved.loc[0, "mpg"] == 31.0  # read-only join


def test_closed_preview_must_have_all_rows_and_exact_budget(tmp_path):
    file = tmp_path / "2026-09-25-hawks.yaml"
    file.write_text("""team: ATL
preview_date: 2026-09-25
budget_gate: passed
sum_budget_mpg: 240
rows:
  - {player: A, budget_mpg: 140, bbm_mpg: '30+'}
  - {player: B, budget_mpg: 100, bbm_mpg: ''}
""", encoding="utf-8")
    frame = pd.DataFrame([
        {"PLAYER_ID": 1, "PLAYER_NAME": "A", "TEAM_ABBREVIATION": "ATL", "rank": 1, "mpg": 32.0, "fpts_pg": 40.0},
        {"PLAYER_ID": 2, "PLAYER_NAME": "B", "TEAM_ABBREVIATION": "ATL", "rank": 2, "mpg": 20.0, "fpts_pg": 20.0},
    ])
    team = build_rotation(frame, frame, latest_previews(tmp_path))["teams"][0]
    assert team["preview"]["hasClosedBudget"] is True
    assert team["players"][0]["previewBudgetMpg"] == 140.0
    file.write_text(file.read_text(encoding="utf-8").replace("budget_mpg: 100", "budget_mpg: null"), encoding="utf-8")
    team = build_rotation(frame, frame, latest_previews(tmp_path))["teams"][0]
    assert team["preview"]["hasClosedBudget"] is False


def test_rotation_uses_current_board_team_assignment():
    old = pd.DataFrame([{"PLAYER_ID": 5, "PLAYER_NAME": "Moved", "TEAM_ABBREVIATION": "BOS",
                         "rank": 10, "mpg": 24.0, "fpts_pg": 25.0}])
    current = old.assign(TEAM_ABBREVIATION="NYK")
    result = build_rotation(old, current)
    assert [team["team"] for team in result["teams"]] == ["NYK"]
    assert result["teams"][0]["modelMinutes"] == 24.0
