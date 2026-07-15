"""Draft-room unit tests (Step 19.1-19.3). Synthetic, no network.

The ESPN-shaped fixtures below encode facts measured against league 507458037 on 2026-07-15 —
notably the placeholder-pick array and the non-contiguous team ids. They are regression pins:
if someone "simplifies" the placeholder filter away, `test_placeholder_picks_are_not_picks`
fails rather than the draft board silently reporting a completed draft on draft night.
"""

import pandas as pd
import pytest

from fantasy_nba.draft import feed, ids, live


# --------------------------------------------------------------------------------------
# Fixtures shaped like the real payloads
# --------------------------------------------------------------------------------------

def _undrafted_payload(n_slots: int = 130) -> dict:
    """What ESPN actually returns before a draft: a FULL pre-allocated array of -1s."""
    return {"draftDetail": {"drafted": False, "inProgress": False, "picks": [
        {"overallPickNumber": i + 1, "roundId": i // 10 + 1, "roundPickNumber": i % 10 + 1,
         "teamId": 0, "playerId": -1, "keeper": False} for i in range(n_slots)
    ]}}


def _drafted_payload() -> dict:
    """A small completed draft. Team ids are deliberately non-contiguous (15, 7, 3) — the
    real 2025 league's overall-pick-1 team is teamId 15 in a 10-team league."""
    order = [15, 7, 3]
    picks = []
    for i in range(6):  # 2 snake rounds x 3 teams
        rnd, in_rnd = divmod(i, 3)
        seat = in_rnd if rnd % 2 == 0 else 2 - in_rnd
        picks.append({"overallPickNumber": i + 1, "roundId": rnd + 1, "roundPickNumber": in_rnd + 1,
                      "teamId": order[seat], "playerId": 1000 + i, "keeper": False})
    return {"draftDetail": {"drafted": True, "inProgress": False, "picks": picks}}


def _league() -> dict:
    return {"teams": 3, "roster": {"PG": 1, "C": 1, "UTIL": 1, "BENCH": 2, "IR": 1}}


def _board(n: int = 8) -> pd.DataFrame:
    return pd.DataFrame({"PLAYER_ID": list(range(1, n + 1)), "rank": list(range(1, n + 1)),
                         "fpts_pg": [50.0 - 3 * i for i in range(n)]})


# --------------------------------------------------------------------------------------
# 19.1 feed
# --------------------------------------------------------------------------------------

def test_placeholder_picks_are_not_picks():
    """ESPN pre-allocates the full pick array with playerId=-1. Counting them reports a
    finished draft before it starts — the trap this whole filter exists for."""
    payload = _undrafted_payload()
    assert len(payload["draftDetail"]["picks"]) == 130      # the array is full...
    assert feed.parse_picks(payload) == []                  # ...and zero picks were made
    st = feed.parse_status(payload)
    assert (st.drafted, st.in_progress) == (False, False)
    assert st.n_picks_total == 130  # kept, but only as a diagnostic


def test_parse_picks_reads_real_picks_in_order():
    picks = feed.parse_picks(_drafted_payload())
    assert len(picks) == 6
    assert [p.overall for p in picks] == [1, 2, 3, 4, 5, 6]
    assert picks[0].team_id == 15 and picks[0].espn_player_id == 1000


def test_fixture_feed_poll_is_idempotent():
    f = feed.FixtureFeed(_drafted_payload())
    assert f.poll() == f.poll()          # polling twice must not duplicate
    assert len(feed.FixtureFeed(_drafted_payload(), reveal=2).poll()) == 2


def test_manual_feed_add_and_undo():
    m = feed.ManualFeed()
    m.add(team_id=15, espn_player_id=999)
    p2 = m.add(team_id=7, espn_player_id=888)
    assert [p.overall for p in m.poll()] == [1, 2]
    assert m.undo() == p2
    assert [p.espn_player_id for p in m.poll()] == [999]
    m.undo()
    assert m.poll() == [] and m.undo() is None   # undo past empty must not raise


def test_scrub_payload_removes_cookies():
    dirty = {"draftDetail": {"picks": []}, "espn_s2": "SECRET", "nested": {"SWID": "{X}"}}
    clean = feed.scrub_payload(dirty)
    assert "espn_s2" not in clean and "SWID" not in clean["nested"]
    assert "draftDetail" in clean


def test_missing_auth_raises_named_error(tmp_path, monkeypatch):
    monkeypatch.delenv("ESPN_S2", raising=False)
    monkeypatch.delenv("ESPN_SWID", raising=False)
    with pytest.raises(feed.EspnApiError, match="Missing"):
        feed.load_espn_auth(env_path=tmp_path / "nope.env")


# --------------------------------------------------------------------------------------
# 19.2 ids
# --------------------------------------------------------------------------------------

def test_normalize_strips_diacritics():
    """ESPN serves 'Nikola Jokic'; our stats carry 'Nikola Jokić'. Same key or the join
    silently loses the best player in the league."""
    assert ids.normalize_name("Nikola Jokić") == ids.normalize_name("Nikola Jokic")
    assert ids.normalize_name("Luka Dončić") == ids.normalize_name("Luka Doncic")
    assert ids.normalize_name("Jaren Jackson Jr.") == ids.normalize_name("Jaren Jackson")


def test_eligible_positions_drops_composite_slots():
    # Edwards: SG(1) + SF(2), plus composite G/F/UTIL/BE that aren't position facts.
    assert ids.eligible_positions([1, 2, 8, 11, 12]) == {"SG", "SF"}
    assert ids.eligible_positions([4, 9, 10, 11]) == {"C"}
    assert ids.eligible_positions(None) == set()


def _stats():
    return pd.DataFrame({"SEASON": ["2024-25"] * 3, "PLAYER_ID": [203999, 1629029, 7],
                         "PLAYER_NAME": ["Nikola Jokić", "Luka Dončić", "Real Player"]})


def test_build_player_map_joins_and_records_unmatched():
    espn = [{"id": 3112335, "fullName": "Nikola Jokic", "eligibleSlots": [4, 11]},
            {"id": 3945274, "fullName": "Luka Doncic", "eligibleSlots": [0, 11]},
            {"id": 999, "fullName": "Derrick Rose", "eligibleSlots": [0]}]  # retired: no stats row
    m = ids.build_player_map(espn, _stats(), season="2024-25")
    assert m.nba_id(3112335) == 203999
    assert m.eligible_of[203999] == {"C"}
    # An ESPN player with no season row is EXPECTED, not a failure.
    assert m.unmatched == ["Derrick Rose"]
    assert m.match_rate == pytest.approx(2 / 3)


def test_unmatched_board_player_hard_fails():
    """The narrow guard: a player we'd actually draft failing to resolve is a real bug."""
    espn = [{"id": 3112335, "fullName": "Nikola Jokic", "eligibleSlots": [4]}]
    with pytest.raises(ValueError, match="board players did not resolve"):
        ids.build_player_map(espn, _stats(), season="2024-25", board_ids={203999, 1629029})


def test_name_collision_hard_fails():
    espn = [{"id": 1, "fullName": "Nikola Jokic", "eligibleSlots": [4]},
            {"id": 2, "fullName": "Nikola Jokić", "eligibleSlots": [4]}]
    with pytest.raises(ValueError, match="collision"):
        ids.build_player_map(espn, _stats(), season="2024-25")


# --------------------------------------------------------------------------------------
# 19.3 live
# --------------------------------------------------------------------------------------

def _state(picks=(), my_team=15, team_ids=(15, 7, 3)):
    return live.DraftState(
        picks=list(picks), my_team_id=my_team, league=_league(),
        eligible_of={1: {"PG"}, 2: {"C"}, 3: {"PG"}, 4: {"C"}, 5: {"PG"},
                     6: {"C"}, 7: {"PG"}, 8: {"C"}},
        to_nba={},  # identity: espn ids == PLAYER_IDs in these fixtures
        team_ids=list(team_ids),
    )


def test_slot_demand_counts_the_whole_league_before_any_pick():
    """Regression pin. `remaining_slots` once counted only teams that had ALREADY picked, so
    pre-draft it saw one team and a third of the real demand — pricing replacement against a
    pool nobody was competing for. Demand must be full at pick 0."""
    st = _state()
    total = sum(sum(v.values()) for v in st.remaining_slots().values())
    assert len(st.remaining_slots()) == 3         # all 3 teams, none has picked
    assert total == 3 * 3                         # 3 teams x (PG + C + UTIL)


def test_all_team_ids_falls_back_to_observed_when_not_supplied():
    st = live.DraftState(picks=[feed.Pick(overall=1, team_id=9, espn_player_id=1)],
                         my_team_id=15, league=_league())
    assert st.all_team_ids == [9, 15]


def test_draft_order_read_from_picks_not_league_size():
    """teamId is NOT a contiguous 1..N index — order must come off observed picks."""
    st = _state(feed.parse_picks(_drafted_payload()))
    assert st.draft_order == [15, 7, 3]
    assert st.picks_until_next() is None or isinstance(st.picks_until_next(), int)


def test_picks_until_next_snakes():
    order = [15, 7, 3]
    picks = [feed.Pick(overall=i + 1, team_id=order[i], espn_player_id=100 + i, round_id=1,
                       round_pick=i + 1) for i in range(3)]
    # Round 1 done (3 picks). Snake: round 2 goes 3, 7, 15 -> team 15 picks last => 2 ahead.
    assert live.DraftState(picks=picks, my_team_id=15, league=_league()).picks_until_next() == 2
    # Team 3 just picked at the turn, so it picks again immediately.
    assert live.DraftState(picks=picks, my_team_id=3, league=_league()).picks_until_next() == 0


def test_picks_until_next_none_before_order_observed():
    """Pre-draft, with no published order supplied, there is nothing to know — and it must
    not be fabricated: survival probability keys off this number."""
    assert live.DraftState(picks=[], my_team_id=15, league=_league()).picks_until_next() is None


def test_published_pick_order_works_at_pick_one():
    """The gap `pick_order` closes: order is needed from pick 1, but is only *recoverable*
    after round 1. ESPN publishes it, so supply it."""
    st = live.DraftState(picks=[], my_team_id=3, league=_league(), pick_order=[15, 7, 3])
    assert st.draft_order == [15, 7, 3]
    assert st.picks_until_next() == 2       # I'm 3rd of 3, nothing picked yet


def test_published_order_and_observed_order_agree():
    """Cross-validation pinned: on the real played 2025 season both routes returned
    [15, 11, 13, 14, 8, 9, 1, 12, 3, 10]."""
    picks = feed.parse_picks(_drafted_payload())          # observed order -> [15, 7, 3]
    from_picks = live.DraftState(picks=picks, my_team_id=15, league=_league()).draft_order
    published = live.DraftState(picks=picks, my_team_id=15, league=_league(),
                                pick_order=[15, 7, 3]).draft_order
    assert from_picks == published == [15, 7, 3]


def test_settings_parse_and_placeholder_order_detection():
    """ESPN seeds pickOrder with SORTED team ids and randomizes before the draft — a cached
    order is worse than none. Shapes are the real 2027 (placeholder) vs 2025 (drawn)."""
    def payload(order):
        return {"settings": {"size": 10, "rosterSettings": {
            "lineupSlotCounts": {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1,
                                 "11": 3, "12": 3, "13": 1, "7": 0}},
            "draftSettings": {"pickOrder": order, "type": "SNAKE", "date": None,
                              "timePerSelection": 60}}}
    placeholder = feed.parse_settings(payload([1, 3, 8, 9, 10, 11, 12, 13, 14, 15]))
    drawn = feed.parse_settings(payload([15, 11, 13, 14, 8, 9, 1, 12, 3, 10]))
    assert placeholder.order_is_placeholder is True      # sorted = not yet drawn
    assert drawn.order_is_placeholder is False
    assert placeholder.is_scheduled is False             # date None = unscheduled
    assert placeholder.seconds_per_pick == 60
    # Slot counts translate id -> name, drop zeros, and match config/league.yaml exactly.
    assert placeholder.slot_counts == {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 1,
                                       "G": 1, "F": 1, "UTIL": 3, "BENCH": 3, "IR": 1}


def test_espn_settings_are_drop_in_for_league_yaml():
    """The whole point of LeagueSettings: when the league changes (new members, resized
    roster), ESPN is the authority and league.yaml is the fallback. So ESPN's slot_counts
    must be usable *as* league["roster"] — which means slot 12 is BENCH, not ESPN's own "BE"
    (value.NON_STARTING says BENCH, and an unmapped slot name raises)."""
    from fantasy_nba.models.value import load_league

    s = feed.parse_settings({"settings": {"size": 10, "rosterSettings": {
        "lineupSlotCounts": {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1,
                             "11": 3, "12": 3, "13": 1}},
        "draftSettings": {"pickOrder": [], "type": "SNAKE", "date": None,
                          "timePerSelection": 60}}})
    # Drop-in: must not raise, and must agree with the committed config.
    st = live.DraftState(league={"teams": s.size, "roster": s.slot_counts},
                         my_team_id=1, team_ids=[1])
    assert st.remaining_slots()[1] == {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 1,
                                       "G": 1, "F": 1, "UTIL": 3}   # BENCH/IR excluded
    assert s.slot_counts == load_league()["roster"], "ESPN settings drifted from league.yaml"
    assert s.size == load_league()["teams"]


def test_state_rebuilds_from_picks_and_undo_is_pure():
    picks = feed.parse_picks(_drafted_payload())
    st = _state(picks)
    before = st.drafted
    st.picks.pop()
    assert len(st.drafted) == len(before) - 1  # rebuilt, not mutated in place


def test_remaining_slots_shrink_as_roster_fills():
    st = _state()
    assert st.remaining_slots()[15] == {"PG": 1, "C": 1, "UTIL": 1}
    st.picks.append(feed.Pick(overall=1, team_id=15, espn_player_id=1))  # a PG
    assert st.remaining_slots()[15] == {"C": 1, "UTIL": 1}               # PG filled, not UTIL


def test_live_replacement_falls_as_pool_drains():
    """The point of the whole module: replacement is a live number, and taking players off
    the board makes what's left on the wire worse.

    NOTE the earlier version of this test asserted the same direction and passed for the
    WRONG reason — with demand growing as teams appeared, it measured demand, not drainage.
    `team_ids` is fixed here so the pool is the only thing that changes.
    """
    board = _board(n=12)
    st = _state(team_ids=(15, 7, 3))
    before = live.live_replacement(st, board)["any"]
    for i in range(1, 5):  # four good players leave the board
        st.picks.append(feed.Pick(overall=i, team_id=7, espn_player_id=i))
    after = live.live_replacement(st, board)["any"]
    assert after < before, f"replacement must degrade as the pool drains ({before} -> {after})"


def test_replacement_is_flat_when_the_draft_follows_board_order():
    """The real correctness property, verified against the live league 2026-07-15.

    If picks come off the top of the board, the pool and the league's slot demand drain at
    the same rate, so replacement must hold ~flat — it is a statement about the *wire*, not
    about how many picks have happened. A version that drifted here would silently re-price
    every VOR as the draft went on. (An earlier build rose 29 -> 45 because demand fell to
    zero while the pool didn't; that was the whole-league-demand bug.)
    """
    board = _board(n=30)                       # fpts_pg 50, 47, 44, ...
    st = _state(team_ids=(15, 7, 3))           # 3 teams x (PG + C + UTIL) = 9 starting slots
    st.eligible_of = {i: ({"PG"} if i % 2 else {"C"}) for i in range(1, 31)}
    baseline = live.live_replacement(st, board)["any"]
    for i in range(1, 10):                     # take the top 9 in board order
        st.picks.append(feed.Pick(overall=i, team_id=(15, 7, 3)[(i - 1) % 3],
                                  espn_player_id=i))
        assert live.live_replacement(st, board)["any"] == pytest.approx(baseline), (
            f"replacement drifted at pick {i} — pool and demand must drain together")


def test_live_board_drops_drafted_and_reranks():
    board = _board()
    st = _state([feed.Pick(overall=1, team_id=7, espn_player_id=1)])
    lb = live.live_board(st, board)
    assert 1 not in set(lb["PLAYER_ID"])
    assert lb["live_rank"].tolist() == sorted(lb["live_rank"].tolist())
    assert {"live_vor", "live_repl", "live_rank"} <= set(lb.columns)
