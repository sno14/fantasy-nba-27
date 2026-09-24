"""Draft-room unit tests (Step 19.1-19.3). Synthetic, no network.

The ESPN-shaped fixtures below encode facts measured against league 507458037 on 2026-07-15 —
notably the placeholder-pick array and the non-contiguous team ids. They are regression pins:
if someone "simplifies" the placeholder filter away, `test_placeholder_picks_are_not_picks`
fails rather than the draft board silently reporting a completed draft on draft night.
"""

import pandas as pd
import pytest

from fantasy_nba.draft import feed, ids, live
from fantasy_nba.draft.radar import add_draft_radar


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


def test_draft_radar_requires_price_gap_and_names_support() -> None:
    board = pd.DataFrame([
        {"rank": 24, "model_rank": 38, "adp": 76.5, "fpts_pg_change": 8.7, "risk": .88,
         "analyst_action": "target_mpg:33"},
        {"rank": 50, "adp": 63, "fpts_pg_change": 0.5, "risk": .8,
         "analyst_action": ""},
        {"rank": 80, "adp": 45, "fpts_pg_change": -5.0, "risk": 1.1,
         "analyst_action": "fpts_delta:-2"},
        {"rank": 40, "adp": 45, "fpts_pg_change": 8.0, "risk": .8,
         "analyst_action": "target_mpg:34"},
    ])

    out = add_draft_radar(board, teams=12)

    assert out["radar_label"].tolist() == ["strong_target", "target", "strong_fade", ""]
    assert out.loc[0, "radar_round_gap"] == 4.38
    assert out.loc[0, "radar_reasons"] == (
        "ADP 4.4 rounds later | +8.7 FP/G projection | positive role adjustment")
    assert "wide downside range" in out.loc[2, "radar_reasons"]


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


def _roster_payload() -> dict:
    """`mRoster` shape (V3b). Team ids are non-contiguous (15, 3) like the real league, and
    the second team uses the nested `playerPoolEntry.player.id` form ESPN also emits — both
    must parse to the same flat id list."""
    return {"teams": [
        {"id": 15, "roster": {"entries": [
            {"playerId": 1001, "lineupSlotId": 0},
            {"playerId": 1002, "lineupSlotId": 12},
        ]}},
        {"id": 3, "roster": {"entries": [
            {"playerPoolEntry": {"player": {"id": 2001}}, "lineupSlotId": 4},
        ]}},
    ]}


def test_parse_rosters_reads_both_id_shapes_and_keeps_team_ids():
    r = feed.parse_rosters(_roster_payload())
    assert r == {15: [1001, 1002], 3: [2001]}   # non-contiguous ids preserved, nested id read


def test_parse_rosters_empty_on_undrafted_season():
    """mRoster carries no entries until players are on teams — must be empty, not raise, so
    ownership falls back to the draft picks (V3b's honest degraded state)."""
    payload = {"teams": [{"id": 15, "roster": {"entries": []}}, {"id": 3}]}
    assert feed.parse_rosters(payload) == {15: [], 3: []}
    assert feed.parse_rosters({"teams": []}) == {}
    # list-wrapped payload (ESPN sometimes returns [ {...} ]) is unwrapped like the other views
    assert feed.parse_rosters([_roster_payload()]) == {15: [1001, 1002], 3: [2001]}


def test_parse_rosters_drops_placeholder_ids():
    """Same discipline as parse_picks: a <=0 id is a placeholder, never a rostered player."""
    payload = {"teams": [{"id": 7, "roster": {"entries": [
        {"playerId": -1}, {"playerId": 0}, {"playerId": 555},
    ]}}]}
    assert feed.parse_rosters(payload) == {7: [555]}


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


def test_build_player_map_resolves_returning_player_absent_from_latest_season():
    stats = pd.DataFrame({
        "SEASON": ["2024-25", "2025-26"],
        "PLAYER_ID": [1630169, 203999],
        "PLAYER_NAME": ["Tyrese Haliburton", "Nikola Jokić"],
    })
    espn = [{"id": 4396993, "fullName": "Tyrese Haliburton", "eligibleSlots": [0, 1, 11]}]

    m = ids.build_player_map(espn, stats)

    assert m.nba_id(4396993) == 1630169
    assert m.eligible_of[1630169] == {"PG", "SG"}


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


def test_demand_counts_unnamed_teams():
    """Regression pin #2 (found by the UI, 2026-07-16). Demand needs a team COUNT, not team
    IDs. Before ESPN is connected we cannot name a single team, but league.yaml says how many
    are competing — counting only named teams made replacement collapse to "best player
    available" (a 56.6 fpts/g "waiver level" on an untouched board)."""
    st = live.DraftState(picks=[], my_team_id=0, league=_league(), team_ids=[])   # nothing known
    assert st.all_team_ids == []          # cannot name any team...
    assert st.n_teams == 3                # ...but the league still has three
    assert st.total_demand() == {"PG": 3, "C": 3, "UTIL": 3}   # full slate x 3 teams


def test_demand_mixes_named_and_unnamed_teams():
    st = _state(team_ids=(15,))           # only one of the league's 3 teams is named
    st.picks.append(feed.Pick(overall=1, team_id=15, espn_player_id=1))  # a PG to team 15
    d = st.total_demand()
    assert d["PG"] == 2   # team 15's PG filled; the 2 unnamed teams still need one each
    assert d["C"] == 3 and d["UTIL"] == 3


def test_replacement_is_sane_on_an_untouched_board():
    """The bug as the user would have seen it: with no picks and no ESPN, replacement must be
    the level past the league's FULL starting demand — not the best player on the board."""
    board = _board(n=30)
    # Every player fills every slot, so demand-counting is the only thing under test.
    st = live.DraftState(picks=[], my_team_id=0, league=_league(), team_ids=[],
                         eligible_of={i: {"PG", "C"} for i in range(1, 31)})
    repl = live.live_replacement(st, board)["any"]
    assert repl < board["fpts_pg"].max(), "must not degenerate to the best player available"
    # 3 teams x 3 starting slots (PG+C+UTIL) = 9 seated, so #10 (index 9) is the wire.
    assert repl == pytest.approx(board["fpts_pg"].iloc[9])


def test_replacement_respects_unfillable_slots():
    """The complement: if nobody can fill a slot, that slot's demand never consumes players.
    An all-PG pool leaves the 3 C slots open, so only 3 PG + 3 UTIL = 6 seat and #7 is the
    wire — not #10. Position eligibility is a real constraint, not decoration."""
    board = _board(n=30)
    st = live.DraftState(picks=[], my_team_id=0, league=_league(), team_ids=[],
                         eligible_of={i: {"PG"} for i in range(1, 31)})
    assert live.live_replacement(st, board)["any"] == pytest.approx(board["fpts_pg"].iloc[6])


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

    s = feed.parse_settings({"settings": {"size": 12, "rosterSettings": {
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


def test_multi_eligible_player_sets_replacement_for_every_slot_he_fills():
    """User's question, 2026-07-16: does a PF/C count toward BOTH PF and C replacement?
    Yes — he is a real alternative at either, so he levels both."""
    board = pd.DataFrame({"PLAYER_ID": [1, 2], "rank": [1, 2], "fpts_pg": [50.0, 40.0]})
    st = live.DraftState(
        picks=[], my_team_id=0, team_ids=[1],
        league={"teams": 1, "roster": {"PF": 1, "C": 1, "UTIL": 0}},
        eligible_of={1: {"PF"}, 2: {"PF", "C"}},   # #2 is the hybrid, unseated after #1 takes PF
    )
    repl = live.live_replacement(st, board)
    assert repl["PF"] == 40.0 and repl["C"] == 40.0, "the PF/C hybrid must level BOTH slots"


def test_multi_eligibility_flattens_positional_scarcity():
    """The consequence of the above, and the correction to an earlier false claim: when the
    best player left is multi-eligible, the slots he covers share one replacement level.
    Scarcity spreads come from slots he CANNOT fill."""
    board = pd.DataFrame({"PLAYER_ID": [1, 2, 3], "rank": [1, 2, 3],
                          "fpts_pg": [50.0, 44.0, 20.0]})
    st = live.DraftState(
        picks=[], my_team_id=0, team_ids=[1],
        league={"teams": 1, "roster": {"PG": 1, "PF": 1, "C": 1}},
        eligible_of={1: {"PG"}, 2: {"PF", "C"}, 3: {"PG"}},
    )
    repl = live.live_replacement(st, board)
    # #2 seats at PF; the best unseated PF/C-eligible is nobody -> PF & C fall back to "any".
    # #3 (PG, 20.0) is unseated and levels PG. PG is genuinely scarcer than the flexible slots.
    assert repl["PG"] == 20.0
    assert repl["PF"] == repl["C"], "slots covered by the same leftovers share a level"


def test_replacement_does_not_depend_on_ranking_stance():
    """Regression pin (bug found 2026-07-16 via the user's multi-eligibility question).

    Replacement is a fact about the WIRE: given the same pool and the same demand, re-ordering
    the board must not move it. The old code walked in `rank` order and took the FIRST unseated
    player's fpts_pg, which silently assumed rank == fpts order. On the shipped `safe` board it
    didn't hold, and PF read 29.09 / 34.86 / 31.49 for fpts_pg / safe / median rankings of an
    identical pool. Now the level is the MAX over unseated eligibles, so a permutation that
    seats the same players yields the same level.
    """
    ids, fpts = list(range(1, 13)), [50.0 - 2 * i for i in range(12)]
    elig = {i: ({"PG"} if i % 2 else {"C"}) for i in ids}
    league = {"teams": 1, "roster": {"PG": 1, "C": 1, "UTIL": 1}}

    # Rank A = by fpts. Rank B = a permutation that seats the SAME three players (ids 1,2,3),
    # just in a different internal order. The level must be identical.
    a = pd.DataFrame({"PLAYER_ID": ids, "rank": range(1, 13), "fpts_pg": fpts})
    order_b = [3, 1, 2] + ids[3:]
    b = pd.DataFrame({"PLAYER_ID": order_b, "rank": range(1, 13),
                      "fpts_pg": [fpts[ids.index(i)] for i in order_b]})
    mk = lambda df: live.DraftState(picks=[], my_team_id=0, team_ids=[1], league=league,
                                    eligible_of=elig)
    ra, rb = live.live_replacement(mk(a), a), live.live_replacement(mk(b), b)
    assert ra == rb, f"replacement moved with ranking order: {ra} vs {rb}"


def test_live_board_drops_drafted_and_reranks():
    board = _board()
    st = _state([feed.Pick(overall=1, team_id=7, espn_player_id=1)])
    lb = live.live_board(st, board)
    assert 1 not in set(lb["PLAYER_ID"])
    assert lb["live_rank"].tolist() == sorted(lb["live_rank"].tolist())
    assert {"live_vor", "live_repl", "live_rank"} <= set(lb.columns)
