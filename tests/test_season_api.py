"""Season-view API helpers (docs/ui-views-plan.md V1/V2/V6) — pure-function tests on
hand-built frames, house style (no data cache, no network)."""

import pandas as pd
import pytest

from fantasy_nba.api.season import attach_market, b2b_count, baseline_date, trend_join


# ------------------------------------------------------------------ baseline_date (V1)
DATES = ["2027-01-04", "2027-01-06", "2027-01-10", "2027-01-15"]


def test_baseline_picks_newest_at_or_beyond_window():
    # 15th minus 7d = the 8th; newest snapshot <= the 8th is the 6th.
    assert baseline_date(DATES, "2027-01-15", 7) == "2027-01-06"


def test_baseline_exact_hit():
    # 15th minus 5d = the 10th — an exact snapshot counts.
    assert baseline_date(DATES, "2027-01-15", 5) == "2027-01-10"


def test_baseline_falls_back_to_oldest_when_window_precedes_archive():
    assert baseline_date(DATES, "2027-01-15", 30) == "2027-01-04"


def test_baseline_none_with_single_snapshot():
    assert baseline_date(["2027-01-15"], "2027-01-15", 7) is None


# ------------------------------------------------------------------ trend_join (V1)
def _snap(rows):
    return pd.DataFrame(rows, columns=["PLAYER_ID", "PLAYER_NAME", "rank", "fpts_pg", "mpg"])


def test_trend_join_delta_signs_and_arrival_drop():
    prev = _snap([(1, "Riser", 20, 30.0, 28.0), (2, "Faller", 5, 40.0, 34.0),
                  (3, "Stable", 10, 35.0, 30.0)])
    cur = _snap([(1, "Riser", 8, 36.5, 33.0), (2, "Faller", 15, 34.0, 30.0),
                 (3, "Stable", 10, 35.0, 30.0), (4, "Arrival", 50, 20.0, 20.0)])
    m = trend_join(cur, prev).set_index("PLAYER_ID")
    assert 4 not in m.index  # present in one snapshot only -> dropped, no fake zero-delta
    assert m.loc[1, "rank_delta"] == 12 and m.loc[1, "fpts_delta"] == pytest.approx(6.5)
    assert m.loc[1, "mpg_delta"] == pytest.approx(5.0)
    assert m.loc[2, "rank_delta"] == -10 and m.loc[2, "fpts_delta"] == pytest.approx(-6.0)
    assert m.loc[3, "rank_delta"] == 0 and m.loc[3, "fpts_delta"] == pytest.approx(0.0)


def test_trend_join_without_mpg_columns():
    prev = _snap([(1, "A", 3, 30.0, 25.0)]).drop(columns=["mpg"])
    cur = _snap([(1, "A", 2, 31.0, 26.0)]).drop(columns=["mpg"])
    m = trend_join(cur, prev)
    assert "mpg_delta" not in m.columns and m.loc[0, "rank_delta"] == 1


# ------------------------------------------------------------------ attach_market (V2)
def test_market_join_normalizes_accents_and_signs_the_gap():
    cur = pd.DataFrame({"PLAYER_ID": [1, 2, 3],
                        "PLAYER_NAME": ["Luka Dončić", "Nikola Jokić", "No Market Row"],
                        "rank": [2, 1, 3]})
    mk = pd.DataFrame({"consensus_rank": [9, 1], "player": ["Luka Doncic", "Nikola Jokic"],
                       "team": ["LAL", "DEN"], "pos": ["PG", "C"],
                       "consensus_value": [None, None], "adp": [None, None]})
    out = attach_market(cur, mk).set_index("PLAYER_ID")
    # market_gap = consensus_rank - rank: +7 = we're higher on him than the market (buy low).
    assert out.loc[1, "market_gap"] == 7
    assert out.loc[2, "market_gap"] == 0
    assert pd.isna(out.loc[3, "market_gap"])  # unmatched name -> null, never fabricated


def test_market_join_empty_market_keeps_shape():
    cur = pd.DataFrame({"PLAYER_ID": [1], "PLAYER_NAME": ["A"], "rank": [1]})
    out = attach_market(cur, pd.DataFrame())
    assert "market_gap" in out.columns and pd.isna(out["market_gap"]).all()


# ------------------------------------------------------------------ b2b_count (V6)
def test_b2b_counts_consecutive_days_only():
    dates = pd.Series(pd.to_datetime(
        ["2026-11-02", "2026-11-03",              # one B2B
         "2026-11-05",
         "2026-11-07", "2026-11-08", "2026-11-09"]))  # a 3-in-3 = two B2B pairs
    assert b2b_count(dates) == 3


def test_b2b_zero_on_sparse_schedule():
    assert b2b_count(pd.Series(pd.to_datetime(["2026-11-02", "2026-11-04"]))) == 0


# ------------------------------------------------------------------ default_week (V3)
def test_default_week_picks_first_week_still_in_progress_or_ahead():
    ends = [(1, "2026-10-25"), (2, "2026-11-01"), (3, "2026-11-08")]
    from fantasy_nba.api.season import default_week

    assert default_week(ends, "2026-10-30") == 2   # week 1 already finished
    assert default_week(ends, "2026-11-01") == 2   # last day of week 2 still counts
    assert default_week(ends, "2026-12-25") == 3   # past the schedule -> final week
    assert default_week(ends, None) == 1           # preseason -> first week
    assert default_week([], "2026-10-30") is None


# ------------------------------------------------------------- games_while_active (V3)
def test_out_until_drops_games_before_the_return_date():
    from fantasy_nba.api.season import games_while_active

    games = ["2027-01-11", "2027-01-13", "2027-01-15", "2027-01-17"]
    assert games_while_active(games, "out_until:2027-01-14") == ["2027-01-15", "2027-01-17"]
    # The return date's own game counts ("back on the 15th").
    assert games_while_active(games, "out_until:2027-01-15") == ["2027-01-15", "2027-01-17"]
    # The pipeline appends a gp-cap suffix: "out_until:… (gp 40->28)" — still parses.
    assert games_while_active(games, "out_until:2027-01-14 (gp 40->28)") == ["2027-01-15", "2027-01-17"]
    assert games_while_active(games, "out_for_season") == []
    assert games_while_active(games, "") == games


# ------------------------------------------------------- draft-session persistence
def test_session_roundtrip_survives_restart(tmp_path, monkeypatch):
    """A server restart must not lose the human-entered room state: manual picks,
    my_team_id, the source toggle, and the last Connect snapshot."""
    from fantasy_nba.api import draft as d
    from fantasy_nba.draft.feed import Pick

    monkeypatch.setattr(d, "SESSION_PATH", tmp_path / "draft_session.json")
    saved = d.Session(source="espn", league_id="507458037", season=2027, my_team_id=3,
                      picks=[Pick(overall=1, team_id=3, espn_player_id=4066, round_id=1)],
                      team_ids=[1, 3, 7], pick_order=[3, 7, 1])
    monkeypatch.setattr(d, "_session", saved)
    d._save_session()

    fresh = d.Session()  # what a restarted process starts from
    monkeypatch.setattr(d, "_session", fresh)
    d._load_session()
    assert fresh.my_team_id == 3 and fresh.source == "espn"
    assert fresh.team_ids == [1, 3, 7] and fresh.pick_order == [3, 7, 1]
    assert len(fresh.picks) == 1 and fresh.picks[0] == saved.picks[0]


def test_session_load_tolerates_missing_and_corrupt_files(tmp_path, monkeypatch):
    from fantasy_nba.api import draft as d

    monkeypatch.setattr(d, "SESSION_PATH", tmp_path / "nope.json")
    fresh = d.Session()
    monkeypatch.setattr(d, "_session", fresh)
    d._load_session()  # missing -> no-op
    assert fresh.my_team_id == 0 and not fresh.picks

    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(d, "SESSION_PATH", tmp_path / "bad.json")
    d._load_session()  # corrupt -> start fresh, never crash at import
    assert fresh.my_team_id == 0 and not fresh.picks
