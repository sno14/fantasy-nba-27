"""Tests for the scoring engine (no network needed)."""

import pandas as pd

from fantasy_nba.scoring import ScoringConfig, score_frame, score_line

CFG = ScoringConfig(
    name="test",
    weights={"pts": 1.0, "reb": 1.25, "ast": 1.5, "stl": 2.0, "blk": 2.0, "tov": -0.5, "fg3m": 0.5},
    bonuses={"double_double": 1.5, "triple_double": 3.0},
)


def test_score_line_basic():
    # 20 pts, 5 reb, 5 ast, 1 stl, 1 blk, 2 tov, 2 3pm; no double-double.
    line = {"pts": 20, "reb": 5, "ast": 5, "stl": 1, "blk": 1, "tov": 2, "fg3m": 2}
    expected = 20 + 5 * 1.25 + 5 * 1.5 + 2 + 2 - 1 + 1  # = 37.25
    assert score_line(line, CFG) == expected


def test_double_double_bonus():
    line = {"pts": 20, "reb": 12, "ast": 3}
    base = 20 + 12 * 1.25 + 3 * 1.5
    assert score_line(line, CFG) == base + 1.5


def test_triple_double_supersedes_double_double():
    line = {"pts": 20, "reb": 11, "ast": 10}
    base = 20 + 11 * 1.25 + 10 * 1.5
    assert score_line(line, CFG) == base + 3.0  # TD bonus only, not TD+DD


def test_score_frame_matches_score_line():
    lines = [
        {"pts": 20, "reb": 5, "ast": 5, "stl": 1, "blk": 1, "tov": 2, "fg3m": 2},
        {"pts": 30, "reb": 12, "ast": 11, "stl": 2, "blk": 0, "tov": 3, "fg3m": 4},
    ]
    df = pd.DataFrame(lines)
    frame_scores = score_frame(df, CFG).tolist()
    line_scores = [score_line(x, CFG) for x in lines]
    assert frame_scores == line_scores


def test_missing_columns_treated_as_zero():
    assert score_line({"pts": 10}, CFG) == 10.0
