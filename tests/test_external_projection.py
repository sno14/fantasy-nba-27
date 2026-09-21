from __future__ import annotations

import pandas as pd

from fantasy_nba.models.analyst import name_key
from fantasy_nba.models.external_projection import (
    SEED_CLASS,
    canonical_team,
    overlay_external_projection,
)


def test_canonical_team_uses_nba_stats_abbreviations() -> None:
    assert canonical_team("SA") == "SAS"
    assert canonical_team("GS") == "GSW"
    assert canonical_team("NY") == "NYK"
    assert canonical_team("FA") != "FA"


def test_overlay_updates_teams_and_appends_missing_projection_rows() -> None:
    board = pd.DataFrame({
        "PLAYER_ID": [1],
        "PLAYER_NAME": ["Existing Player"],
        "TEAM_ABBREVIATION": ["OLD"],
        "fpts_pg": [40.0],
        "gp": [60.0],
        "mpg": [30.0],
    })
    external = pd.DataFrame({
        "player": ["Existing Player", "Known Veteran", "New Rookie"],
        "name_key": [name_key(n) for n in ("Existing Player", "Known Veteran", "New Rookie")],
        "team": ["SA", "NY", "GS"],
        "external_fpts_pg": [50.0, 29.5, 25.0],
        "adp": [10.0, 100.0, 120.0],
        "gp": [70, 60, 72],
        "mpg": [35.0, 31.2, 29.0],
    })
    stats = pd.DataFrame({
        "SEASON": ["2024-25"],
        "PLAYER_ID": [99],
        "PLAYER_NAME": ["Known Veteran"],
    })

    got = overlay_external_projection(board, external, stats).set_index("PLAYER_NAME")

    # Existing values remain model-owned; only the current display team is reconciled.
    assert got.loc["Existing Player", "TEAM_ABBREVIATION"] == "SAS"
    assert got.loc["Existing Player", "fpts_pg"] == 40.0
    assert got.loc["Known Veteran", "PLAYER_ID"] == 99
    assert got.loc["New Rookie", "PLAYER_ID"] < 0
    assert got.loc["New Rookie", "TEAM_ABBREVIATION"] == "GSW"
    assert got.loc["New Rookie", "fpts_pg"] == 25.0
    assert got.loc["New Rookie", "fpts_total"] == 1800.0
    assert got.loc["New Rookie", "seed_class"] == SEED_CLASS
    assert got.loc["New Rookie", "market_priced"] == 1


def test_board_only_ids_are_stable() -> None:
    board = pd.DataFrame(columns=["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION"])
    external = pd.DataFrame({
        "player": ["New Rookie"],
        "name_key": [name_key("New Rookie")],
        "team": ["MEM"],
        "external_fpts_pg": [25.0],
        "adp": [120.0],
        "gp": [72],
        "mpg": [29.0],
    })
    stats = pd.DataFrame(columns=["SEASON", "PLAYER_ID", "PLAYER_NAME"])

    first = overlay_external_projection(board, external, stats).iloc[0]["PLAYER_ID"]
    second = overlay_external_projection(board, external, stats).iloc[0]["PLAYER_ID"]
    assert first == second
    assert first < 0
