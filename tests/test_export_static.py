from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_static.py"
SPEC = importlib.util.spec_from_file_location("export_static", SCRIPT)
assert SPEC and SPEC.loader
EXPORT_STATIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT_STATIC)


def test_public_board_uses_ordinal_fpts_rank_and_preserves_source_ranks() -> None:
    board = pd.DataFrame(
        [
            {"rank": 1, "model_rank": 4, "tier": 1, "PLAYER_ID": 30, "PLAYER_NAME": "Low", "fpts_pg": 30.0},
            {"rank": 3, "model_rank": 2, "tier": 3, "PLAYER_ID": 20, "PLAYER_NAME": "Tie B", "fpts_pg": 40.0},
            {"rank": 2, "model_rank": 1, "tier": 2, "PLAYER_ID": 10, "PLAYER_NAME": "Tie A", "fpts_pg": 40.0},
        ]
    )

    ranked = EXPORT_STATIC._rank_public_board(board)

    assert ranked["PLAYER_NAME"].tolist() == ["Tie A", "Tie B", "Low"]
    assert ranked["rank"].tolist() == [1, 2, 3]
    assert ranked["source_rank"].tolist() == [2, 3, 1]
    assert ranked["model_source_rank"].tolist() == [1, 2, 4]
    assert ranked["source_tier"].tolist() == [2, 3, 1]
    assert ranked["tier"].tolist() == [1.0, 1.0, 2.0]
    assert board["rank"].tolist() == [1, 3, 2]


def test_public_board_rejects_missing_fpts() -> None:
    board = pd.DataFrame([{"rank": 1, "PLAYER_NAME": "No Projection"}])

    with pytest.raises(ValueError, match="fpts_pg"):
        EXPORT_STATIC._rank_public_board(board)


def test_public_snapshot_has_rich_read_only_projection_fields() -> None:
    expected = {
        "tier", "target_age", "draft_value", "vor", "adp", "pts", "reb", "ast",
        "stl", "blk", "fg3m", "tov",
    }

    assert expected <= set(EXPORT_STATIC.PUBLIC_COLUMNS)
    assert "analyst_rationale" not in EXPORT_STATIC.PUBLIC_COLUMNS
