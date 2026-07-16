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
