"""Single-move streaming scenarios must respect dates, ownership and uncertainty."""

from fantasy_nba.streaming import evaluate_move, prepare_drop, quick_move_score
from fantasy_nba.lineups import calculate_week


def row(pid, fpg, games, *, name=None, status=""):
    return {"PLAYER_ID": pid, "PLAYER_NAME": name or str(pid), "TEAM_ABBREVIATION": "ATL",
            "fpts_pg": fpg, "games": games, "status_override": status,
            "weekly_fpts": (fpg or 0) * len(games)}


def test_three_usable_games_beat_four_with_two_starts():
    days = [f"2026-10-{day:02}" for day in range(20, 25)]
    roster = [row(1, 20, days[:2]), row(2, 1, [])]
    positions = {1: ["PG"], 2: ["PG"], 3: ["PG"], 4: ["PG"]}
    four = evaluate_move(roster, row(3, 10, days[:4]), 2, positions,
                         {"PG": 1}, days, days[0], "before_games")
    three = evaluate_move(roster, row(4, 10, days[2:]), 2, positions,
                          {"PG": 1}, days, days[0], "before_games")
    assert four["pickup_raw_points"] == 40
    assert four["pickup_used_points"] == 20
    assert four["pickup_benched_dates"] == days[:2]
    assert four["usable_delta"] == 20
    assert three["pickup_raw_points"] == three["pickup_used_points"] == 30
    assert three["usable_delta"] == 30
    assert three["usable_delta"] > four["usable_delta"]


def test_effective_date_and_lock_preserve_pre_move_drop_games():
    days = ["2026-10-20", "2026-10-21"]
    roster = [row(1, 8, days)]
    pickup = row(2, 20, days)
    positions = {1: ["C"], 2: ["C"]}
    before = evaluate_move(roster, pickup, 1, positions, {"C": 1}, days,
                           days[1], "before_games")
    after = evaluate_move(roster, pickup, 1, positions, {"C": 1}, days,
                          days[1], "after_games")
    assert before["usable_delta"] == 12  # day one still belongs to the drop
    assert before["pickup_start_dates"] == [days[1]]
    assert after["usable_delta"] == 0
    assert after["pickup_start_dates"] == []
    assert after["drop_lost_starter_points"] == 0


def test_missing_pickup_eligibility_keeps_gain_unknown():
    day = "2026-10-20"
    move = evaluate_move([row(1, 10, [])], row(2, 20, [day]), 1,
                         {1: ["PG"]}, {"PG": 1}, [day], day, "before_games")
    assert move["usable_delta"] is None
    assert move["raw_delta"] == 20
    assert move["after"]["days"][0]["unknown_eligibility"] == [2]


def test_fast_rank_score_matches_exact_reassignment_across_flex_cases():
    from random import Random

    rng = Random(27)
    days = [f"2026-10-{day:02}" for day in range(20, 24)]
    slots = {"PG": 1, "SG": 1, "G": 1, "UTIL": 1}
    choices = [["PG"], ["SG"], ["PG", "SG"], ["C"], []]
    for _ in range(30):
        roster = [row(pid, rng.randint(0, 30), [d for d in days if rng.randint(0, 1)])
                  for pid in range(1, 6)]
        pickup = row(100, rng.randint(0, 30), [d for d in days if rng.randint(0, 1)])
        positions = {pid: rng.choice(choices) for pid in [1, 2, 3, 4, 5, 100]}
        cutoff = rng.choice(days)
        lock = rng.choice(["before_games", "after_games"])
        before = calculate_week(roster, positions, slots, days)
        prepared = prepare_drop(roster, 5, positions, slots, days, cutoff, lock)
        fast = quick_move_score(prepared, before, roster[-1], pickup, positions,
                                days, cutoff, lock)
        exact = evaluate_move(roster, pickup, 5, positions, slots, days, cutoff, lock, before)
        assert fast == (exact["usable_delta"], exact["raw_delta"])


def test_api_budget_ownership_injury_and_rank(monkeypatch):
    from fantasy_nba.api import draft, season

    days = ["2026-10-20", "2026-10-21", "2026-10-22"]
    rows = {
        1: row(1, 20, days[:1], name="Starter"),
        2: row(2, 1, [], name="Drop"),
        3: row(3, 25, days, name="Already rostered"),
        100: row(100, 10, days, name="Healthy pickup"),
        101: row(101, 30, [], name="Out pickup", status="out_for_season"),
    }
    meta = {"week": 1, "week_name": "W1", "start": days[0], "end": days[-1], "days": days}
    own = {"my_team_id": 1, "rosters": {1: [1, 2], 2: [3]},
           "positions": {1: ["PG"], 2: ["PG"], 3: ["PG"]},
           "starting_slots": {"PG": 1}, "roster_source": "draft", "rosters_asof": None}
    monkeypatch.setattr(draft, "current_rosters", lambda: own)
    monkeypatch.setattr(draft, "player_positions", lambda: {pid: ["PG"] for pid in rows})
    monkeypatch.setattr(season, "ros_dates", lambda: [])
    monkeypatch.setattr(season, "_board_lookup", lambda: {pid: {} for pid in rows})
    monkeypatch.setattr(season, "_roster_week_rows",
                        lambda ids, week, target: ([rows[pid] for pid in ids], meta))

    def call(**kwargs):
        return season.streaming(
            week=1, start=None, end=None, effective_date=None,
            lock_rule="before_games", drops="2", keep="", acquisitions_used=0,
            acquisition_limit=2, rules_confirmed=False, pickup_id=None,
            target="2026-27", **kwargs)

    ranked = call()
    assert ranked["projection_source"] == "preseason"
    assert ranked["ownership_status"] == "draft_only"
    assert ranked["rules"]["source"] == "unverified"
    assert ranked["rules"]["budget_status"] == "under_assumed_limit"
    assert ranked["evaluated_count"] == 1
    assert ranked["results"][0]["pickup_id"] == 100
    assert ranked["results"][0]["usable_delta"] == 20

    multi = season.streaming(week=1, start=None, end=None, effective_date=None,
                             lock_rule="before_games", drops="1,2", keep="",
                             acquisitions_used=0, acquisition_limit=2,
                             rules_confirmed=True, pickup_id=100, target="2026-27")
    assert multi["evaluated_count"] == 2
    assert [r["drop_id"] for r in multi["results"]] == [2, 1]
    assert multi["rules"]["source"] == "user_assumption"

    from fastapi import HTTPException
    try:
        season.streaming(week=1, start=None, end=None, effective_date=None,
                         lock_rule="before_games", drops="2", keep="2",
                         acquisitions_used=0, acquisition_limit=2,
                         rules_confirmed=False, pickup_id=None, target="2026-27")
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("A kept player cannot be dropped")

    blocked = season.streaming(week=1, start=None, end=None, effective_date=None,
                               lock_rule="before_games", drops="2", keep="",
                               acquisitions_used=2, acquisition_limit=2,
                               rules_confirmed=False, pickup_id=None, target="2026-27")
    assert blocked["rules"]["budget_status"] == "blocked"
    assert blocked["results"] == []

    out = season.streaming(week=1, start=None, end=None, effective_date=None,
                           lock_rule="before_games", drops="2", keep="",
                           acquisitions_used=None, acquisition_limit=None,
                           rules_confirmed=False, pickup_id=101, target="2026-27")
    assert out["results"][0]["pickup_status"] == "out_for_season"
    assert out["results"][0]["usable_delta"] == 0


def test_no_schedule_does_not_rank_moves(monkeypatch):
    from fantasy_nba.api import draft, season

    own = {"my_team_id": 1, "rosters": {1: [1]}, "positions": {1: ["PG"]},
           "starting_slots": {"PG": 1}, "roster_source": "draft", "rosters_asof": None}
    monkeypatch.setattr(draft, "current_rosters", lambda: own)
    monkeypatch.setattr(draft, "player_positions", lambda: own["positions"])
    monkeypatch.setattr(season, "_roster_week_rows", lambda *_: ([row(1, 10, [])], {}))
    result = season.streaming(week=1, start=None, end=None, effective_date=None,
                              lock_rule="before_games", drops="1", keep="",
                              acquisitions_used=None, acquisition_limit=None,
                              rules_confirmed=False, pickup_id=None, target="2026-27")
    assert result["has_schedule"] is False
    assert result["results"] == []
