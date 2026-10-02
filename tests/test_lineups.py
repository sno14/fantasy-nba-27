"""Feasible daily points are an exact slot assignment, with honest missing-data states."""

from fantasy_nba.lineups import calculate_week
from fantasy_nba.api.season import games_while_active


def row(pid, value, games, name=None):
    return {"PLAYER_ID": pid, "PLAYER_NAME": name or str(pid), "fpts_pg": value,
            "games": games}


def test_scarce_slot_beats_greedy_and_never_reuses_player_or_slot():
    days = ["2026-10-20", "2026-10-21"]
    rows = [row(1, 10, days), row(2, 9, days), row(3, 8, days)]
    positions = {1: ["PG", "SG"], 2: ["PG"], 3: ["SG"]}
    result = calculate_week(rows, positions, {"PG": 1, "SG": 1, "BENCH": 3}, days)
    assert result["raw_points"] == 54
    assert result["usable_points"] == 38
    assert result["benched_points"] == 16
    for day in result["days"]:
        assert {(a["slot"], a["player_id"]) for a in day["assignments"]} == {
            ("PG", 2), ("SG", 1)}
        assert len({a["slot"] for a in day["assignments"]}) == 2
        assert len({a["player_id"] for a in day["assignments"]}) == 2
        assert day["benched_games"] == 1
    assert result["usable_points"] <= result["raw_points"]


def test_flex_slots_crowded_day_and_idle_day():
    days = ["2026-10-20", "2026-10-21"]
    rows = [row(1, 20, days[:1]), row(2, 15, days[:1]), row(3, 12, days[:1])]
    result = calculate_week(rows, {1: ["PG"], 2: ["SG"], 3: ["C"]},
                            {"G": 1, "UTIL": 1, "IR": 1}, days)
    assert result["usable_points"] == 35
    assert result["days"][0]["benched_points"] == 12
    assert result["days"][0]["benched_games"] == 1
    assert result["days"][1]["usable_points"] == 0
    assert result["days"][1]["idle_slots"] == ["G", "UTIL"]


def test_zero_projection_uses_open_legal_slot_on_tie():
    day = "2026-10-20"
    result = calculate_week([row(1, 0, [day])], {1: ["C"]}, {"C": 1}, [day])
    assert result["usable_points"] == 0
    assert result["days"][0]["assignments"][0]["player_id"] == 1
    assert result["days"][0]["idle_slots"] == []


def test_unknown_eligibility_and_projection_are_not_silent_zeroes():
    day = "2026-10-20"
    result = calculate_week([row(1, 20, [day]), row(2, 15, [day]), row(3, None, [day])],
                            {1: ["PG"], 2: [], 3: ["SG"]}, {"PG": 1, "SG": 1}, [day])
    assert result["raw_points"] is None
    assert result["usable_points"] is None
    assert result["benched_points"] is None
    assert result["known_raw_points"] == 35
    assert result["known_usable_points"] == 20
    assert result["days"][0]["unknown_eligibility"] == [2]
    assert result["days"][0]["unknown_projection"] == [3]


def test_unknown_nba_team_does_not_look_like_zero_scheduled_games():
    day = "2026-10-20"
    player = row(1, 20, []) | {"unknown_game_dates": True}
    result = calculate_week([player], {1: ["PG"]}, {"PG": 1}, [day])
    assert result["raw_points"] is None
    assert result["usable_points"] is None
    assert result["unknown_game_dates"] == [1]
    assert result["known_usable_points"] == 0


def test_out_dates_and_no_schedule():
    days = ["2026-10-20", "2026-10-21", "2026-10-22"]
    active = games_while_active(days, "out_until:2026-10-22")
    assert active == ["2026-10-22"]
    rows = [row(1, 30, active), row(2, 40, games_while_active(days, "out_for_season"))]
    result = calculate_week(rows, {1: ["C"], 2: ["C"]}, {"C": 1}, days)
    assert result["raw_points"] == result["usable_points"] == 30
    assert [day["games"] for day in result["days"]] == [0, 0, 1]
    absent = calculate_week(rows, {1: ["C"]}, {"C": 1}, [])
    assert absent["has_schedule"] is False
    assert absent["usable_points"] is None


def test_myteam_and_matchup_use_same_lineup_calculation(monkeypatch):
    from fantasy_nba.api import draft, season

    day = "2026-10-20"
    rosters = {
        "my_team_id": 1, "rosters": {1: [1, 2], 2: [3]},
        "positions": {1: ["PG"], 2: ["PG"], 3: ["PG"]},
        "starting_slots": {"PG": 1}, "slot_source": "league_config",
        "roster_source": "espn_live", "rosters_asof": "2026-10-19T00:00:00Z",
        "has_positions": True, "unfilled": {1: {}, 2: {}},
    }
    weekly = {
        1: {**row(1, 20, [day]), "weekly_fpts": 20, "status_override": ""},
        2: {**row(2, 15, [day]), "weekly_fpts": 15, "status_override": ""},
        3: {**row(3, 25, [day]), "weekly_fpts": 25, "status_override": ""},
    }
    meta = {"week": 1, "week_name": "W1", "start": day, "end": day, "days": [day]}
    monkeypatch.setattr(draft, "current_rosters", lambda: rosters)
    monkeypatch.setattr(season, "_roster_week_rows",
                        lambda pids, week, target: ([weekly[pid] for pid in pids], meta))

    team = season.myteam(week=1, target="2026-27")
    match = season.matchup(week=1, opp=2, target="2026-27")
    assert team["lineup"]["usable_points"] == match["me"]["lineup"]["usable_points"] == 20
    assert team["lineup"]["benched_points"] == 15
    assert team["day_grid"] == [{"day": day, "games": 2, "benched": 1, "starts": 1}]
    assert match["usable_gap"] == -5
    assert match["rosters_asof"] == "2026-10-19T00:00:00Z"
