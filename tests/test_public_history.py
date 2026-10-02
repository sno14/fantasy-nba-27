from __future__ import annotations

import json

from scripts.public_history import HISTORY_COLUMNS, archive_public_board, public_snapshot
from scripts.validate_public_history import validate


def board(stamp: str, fpts: float = 30.0) -> dict:
    return {
        "season": "2026-27", "ranked_by": "fpts_pg", "scoring_key": "0123456789abcdef",
        "generated_at": stamp,
        "rows": [{"PLAYER_ID": 1, "PLAYER_NAME": "Example", "TEAM_ABBREVIATION": "NYK",
                  "rank": 1, "fpts_pg": fpts, "mpg": 28.0,
                  "analyst_action": None, "analyst_date": None,
                  "analyst_rationale": "private research", "notes": "private watchlist"}],
    }


def test_history_redacts_and_preserves_same_day_versions(tmp_path):
    first = board("2026-10-02T09:00:00+00:00")
    second = board("2026-10-02T09:00:00+00:00", 31)
    old = public_snapshot(first)
    new = public_snapshot(second)
    assert old["version"] != new["version"]
    assert set(old["rows"][0]) == set(HISTORY_COLUMNS)
    assert "private" not in json.dumps(old)
    archive_public_board(first, tmp_path)
    manifest = archive_public_board(second, tmp_path)
    assert len(manifest["versions"]) == 2
    assert all((tmp_path / item["file"]).exists() for item in manifest["versions"])
    assert validate(tmp_path) == 2


def test_history_retains_thirty_and_does_not_delete_unknown_files(tmp_path):
    protected = tmp_path / "do-not-delete.json"
    protected.write_text("kept", encoding="utf-8")
    for hour in range(31):
        archive_public_board(board(f"2026-10-02T{hour // 60:02d}:{hour % 60:02d}:00+00:00", 30 + hour), tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["versions"]) == 30
    assert len(list(tmp_path.glob("v-*.json"))) == 30
    assert protected.read_text(encoding="utf-8") == "kept"
