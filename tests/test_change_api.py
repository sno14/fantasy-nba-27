from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi import HTTPException

from fantasy_nba.api import season


def test_local_change_versions_require_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(season, "ROS_DIR", tmp_path)
    monkeypatch.setattr(season.boards, "CURRENT_TARGET", "2026-27")
    season._ros_cached.cache_clear()
    rows = pd.DataFrame([{"PLAYER_ID": 1, "PLAYER_NAME": "Example", "rank": 1,
                          "fpts_pg": 31.5, "mpg": 29, "analyst_rationale": "private"}])
    rows.to_parquet(tmp_path / "2026-10-01.parquet", index=False)
    rows.to_parquet(tmp_path / "2026-10-02.parquet", index=False)
    (tmp_path / "2026-10-02.meta.json").write_text(json.dumps({
        "schema": 1, "season": "2026-27", "rankedBy": "ROS safe season value",
        "scoringKey": "0123456789abcdef"}), encoding="utf-8")
    manifest = season.change_versions()
    assert [item["version"] for item in manifest["versions"]] == ["2026-10-02"]
    assert manifest["legacyCount"] == 1
    snapshot = season.change_version("2026-10-02")
    assert snapshot["rows"][0]["fpts_pg"] == 31.5
    assert "analyst_rationale" not in snapshot["rows"][0]
    assert snapshot["rows"][0]["analyst_action"] is None
    with pytest.raises(HTTPException) as missing:
        season.change_version("2026-10-01")
    assert missing.value.status_code == 404
    season._ros_cached.cache_clear()
