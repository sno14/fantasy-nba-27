"""Trade scenarios reconcile ownership, value and uncertainty without mutation."""

import pandas as pd
import pytest
from fastapi import HTTPException

from fantasy_nba.trade_sandbox import apply_trade, summarize_roster


def row(pid, fpg=20, games=None, source="preseason"):
    return {"PLAYER_ID": pid, "PLAYER_NAME": f"Player {pid}", "TEAM_ABBREVIATION": "ATL",
            "rank": pid, "fpts_pg": fpg, "fpts_total": fpg * 50 if fpg is not None else None,
            "projection_source": source, "games": games or [],
            "status_override": "", "risk": 0.2, "fpts_p10": 500, "fpts_p90": 1500}


def test_even_and_uneven_trade_reconcile_without_mutating_inputs():
    a, b = [1, 2], [3, 4]
    even = apply_trade(a, b, {5}, [1], [3])
    assert even["a_after"] == [2, 3]
    assert even["b_after"] == [4, 1]
    assert a == [1, 2] and b == [3, 4]

    uneven = apply_trade(a, b, {5}, [1], [3, 4], drop_a=[2], pickup_b=[5])
    assert uneven["a_after"] == [3, 4]
    assert uneven["b_after"] == [1, 5]
    assert uneven["released_ids"] == [2] and uneven["acquired_ids"] == [5]
    assert len(uneven["a_after"]) + len(uneven["b_after"]) == 4


@pytest.mark.parametrize("kwargs", [
    {"out_a": [], "out_b": [3]},
    {"out_a": [1, 1], "out_b": [3]},
    {"out_a": [3], "out_b": [1]},
    {"out_a": [1], "out_b": [3, 4]},  # missing receiving-side drop
    {"out_a": [1], "out_b": [3], "pickup_a": [5]},  # no vacancy
    {"out_a": [1], "out_b": [3], "pickup_b": [3]},  # rostered pickup
])
def test_invalid_selections_rejected(kwargs):
    with pytest.raises(ValueError):
        apply_trade([1, 2], [3, 4], {5}, **kwargs)


def test_summary_requires_common_season_horizon_and_keeps_risk_individual():
    rows = [row(1, 20, ["2026-10-20"]), row(2, 10, ["2026-10-20"])]
    summary = summarize_roster(rows, {1: ["PG"], 2: ["PG"]}, {"PG": 1},
                               ["2026-10-20"], "preseason", 12)
    assert summary["fpts_pg_total"] == 30
    assert summary["season_total"] == 1500
    assert summary["starter_fpts_pg"] == 20
    assert summary["week"]["usable_points"] == 20
    assert summary["depth_above_wire"] == 1
    assert len(summary["risk_players"]) == 2
    assert "team_risk" not in summary and "team_p10" not in summary

    mixed = summarize_roster([rows[0], row(2, 10, source="ros")],
                             {1: ["PG"], 2: ["PG"]}, {"PG": 1}, [], "preseason", 12)
    assert mixed["season_total"] is None
    assert mixed["week"]["usable_points"] is None


def test_playoff_volume_requires_confirmed_calendar_and_known_teams(tmp_path, monkeypatch):
    from fantasy_nba.api import trade_sandbox as api

    league_path = tmp_path / "league.yaml"
    league_path.write_text("fantasy_playoff_weeks: [19]\n", encoding="utf-8")
    monkeypatch.setattr(api.season, "LEAGUE_PATH", league_path)
    schedule = pd.DataFrame([{"team": "ATL", "week": 19}, {"team": "ATL", "week": 19},
                             {"team": "BOS", "week": 19}])
    monkeypatch.setattr(api.boards, "team_week_games", lambda _: schedule)
    atl, bos, unknown = row(1), {**row(2), "TEAM_ABBREVIATION": "BOS"}, {**row(3), "TEAM_ABBREVIATION": "XXX"}
    assert api._playoff_volume([atl], [bos], [bos], [atl], "2026-27") is None
    league_path.write_text("fantasy_playoff_weeks: [19]\nfantasy_playoff_weeks_confirmed: true\n", encoding="utf-8")
    comparison = api._playoff_volume([atl], [bos], [unknown], [bos], "2026-27")
    assert comparison["a_before"] == {"19": 2}
    assert comparison["a_after"] == {"19": 1}
    assert comparison["b_before"] == {"19": None}


def test_api_two_sides_uneven_cost_and_no_roster_write(monkeypatch):
    from fantasy_nba.api import season
    from fantasy_nba.api import trade_sandbox as api

    day = "2026-10-20"
    rows = {1: row(1, 30, [day]), 2: row(2, 10, [day]),
            3: row(3, 25, [day]), 4: row(4, 15, [day]), 5: row(5, 12, [day])}
    meta = {"week": 1, "week_name": "W1", "start": day, "end": day, "days": [day]}
    rosters = {8: [1, 2], 15: [3, 4]}
    own = {"my_team_id": 8, "rosters": rosters,
           "positions": {pid: ["PG"] for pid in rows},
           "starting_slots": {"PG": 1},
           "roster_slots": {"PG": 1, "BENCH": 3, "IR": 1},
           "slot_source": "league_config", "roster_source": "draft",
           "rosters_asof": None}
    monkeypatch.setattr(api, "current_rosters", lambda: own)
    monkeypatch.setattr(api, "player_positions", lambda: own["positions"])
    monkeypatch.setattr(season, "ros_dates", lambda: [])
    monkeypatch.setattr(season, "week_games_by_team", lambda *_: (meta, {}))
    monkeypatch.setattr(season, "_board_lookup", lambda: {pid: {} for pid in rows})
    monkeypatch.setattr(season, "_roster_week_rows",
                        lambda ids, week, target, **kwargs: ([rows[pid] for pid in ids], meta))
    monkeypatch.setattr(season, "latest_market", lambda *_: (None, pd.DataFrame()))
    monkeypatch.setattr(season, "LEAGUE_PATH", api.season.LEAGUE_PATH)

    result = api.trade_sandbox(team_a=8, team_b=15, out_a="1", out_b="3,4",
                               drop_a="2", drop_b="", pickup_a="", pickup_b="5",
                               week=1, start=None, end=None, target="2026-27")
    scenario = result["scenario"]
    assert scenario["a_after_ids"] == [3, 4]
    assert scenario["b_after_ids"] == [1, 5]
    assert scenario["a"]["before"]["fpts_pg_total"] == 40
    assert scenario["a"]["after"]["fpts_pg_total"] == 40
    assert scenario["a"]["before"]["week"]["usable_points"] == 30
    assert scenario["a"]["after"]["week"]["usable_points"] == 25
    assert scenario["a"]["after"]["season_total"] == 2000
    assert scenario["playoff_volume"] is None  # placeholder playoff calendar is not compared
    assert result["ownership_status"] == "draft_only"
    assert rosters == {8: [1, 2], 15: [3, 4]}

    with pytest.raises(HTTPException) as exc:
        api.trade_sandbox(team_a=8, team_b=15, out_a="1", out_b="4",
                          drop_a="2", drop_b="", pickup_a="", pickup_b="",
                          week=1, start=None, end=None, target="2026-27")
    assert exc.value.status_code == 422
