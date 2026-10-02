from __future__ import annotations

import json

from scripts.public_rotation import PLAYER_KEYS, TEAM_KEYS, public_rotation, validate, write_public_rotation


def test_public_rotation_is_derived_and_redacted(tmp_path):
    board = {"title": "Fantasy NBA 2026-27 Board B", "ranked_by": "fpts_pg",
             "generated_at": "2026-09-29T13:00:00+00:00", "rows": [
                 {"PLAYER_ID": 1, "PLAYER_NAME": "A", "TEAM_ABBREVIATION": "NYK", "rank": 1,
                  "mpg": 30, "fpts_pg": 35, "gp": 70, "positions": "PG|SG", "analyst_action": "target_mpg:30",
                  "analyst_date": "2026-09-29", "analyst_rationale": "private", "notes": "secret"},
                 {"PLAYER_ID": 2, "PLAYER_NAME": "B", "TEAM_ABBREVIATION": "NYK", "rank": 2,
                  "mpg": None, "fpts_pg": 20, "gp": None, "positions": None},
             ]}
    data = public_rotation(board)
    assert data["season"] == "2026-27"
    assert data["teams"][0]["projectedMinutes"] == 30
    assert data["teams"][0]["missingMpg"] == 1
    assert set(data["teams"][0]) == TEAM_KEYS
    assert set(data["teams"][0]["players"][0]) == PLAYER_KEYS
    assert "private" not in json.dumps(data) and "secret" not in json.dumps(data)
    board_file = tmp_path / "board.json"
    board_file.write_text(json.dumps(board), encoding="utf-8")
    out = tmp_path / "rotation.json"
    write_public_rotation(board, out)
    assert validate(board_file, out) == 1
    data["teams"][0]["players"][0]["analystRationale"] = "leak"
    out.write_text(json.dumps(data), encoding="utf-8")
    try:
        validate(board_file, out)
    except ValueError:
        pass
    else:
        raise AssertionError("Private additions must fail validation")
