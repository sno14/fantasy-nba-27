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
            {"rank": 1, "model_rank": 4, "PLAYER_ID": 30, "PLAYER_NAME": "Low", "fpts_pg": 30.0},
            {"rank": 3, "model_rank": 2, "PLAYER_ID": 20, "PLAYER_NAME": "Tie B", "fpts_pg": 40.0},
            {"rank": 2, "model_rank": 1, "PLAYER_ID": 10, "PLAYER_NAME": "Tie A", "fpts_pg": 40.0},
        ]
    )

    ranked = EXPORT_STATIC._rank_public_board(board)

    assert ranked["PLAYER_NAME"].tolist() == ["Tie A", "Tie B", "Low"]
    assert ranked["rank"].tolist() == [1, 2, 3]
    assert ranked["source_rank"].tolist() == [2, 3, 1]
    assert ranked["model_source_rank"].tolist() == [1, 2, 4]
    assert board["rank"].tolist() == [1, 3, 2]


def test_public_board_rejects_missing_fpts() -> None:
    board = pd.DataFrame([{"rank": 1, "PLAYER_NAME": "No Projection"}])

    with pytest.raises(ValueError, match="fpts_pg"):
        EXPORT_STATIC._rank_public_board(board)
