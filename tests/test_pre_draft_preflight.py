"""The October freeze preflight must reject stale or merely cached inputs."""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.pre_draft_preflight import audit


AS_OF = date(2026, 10, 14)
LEAGUE = {"teams": 12, "roster": {"PG": 1, "BENCH": 3}}


def _write(path: Path, frame: pd.DataFrame, stamp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    seconds = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp()
    os.utime(path, (seconds, seconds))


def _status(report: dict, key: str) -> str:
    return next(item["status"] for item in report["checks"] if item["key"] == key)


def test_missing_target_data_and_undated_connect_block_review(tmp_path):
    raw = tmp_path / "data/raw"
    processed = tmp_path / "data/processed"
    _write(raw / "preseason_game_logs.parquet", pd.DataFrame({"SEASON": ["2025-26"]}), "2026-07-10T00:00:00")
    _write(raw / "draft_history.parquet", pd.DataFrame({"SEASON": [2025]}), "2026-07-10T00:00:00")
    processed.mkdir(parents=True)
    (processed / "draft_session.json").write_text(json.dumps({"settings": {"size": 12}, "team_ids": list(range(12))}), encoding="utf-8")
    report = audit(tmp_path, AS_OF, LEAGUE)
    assert not report["ready_for_human_review"]
    for key in ("target_preseason_logs", "target_draft_class", "target_schedule", "espn_live_settings"):
        assert _status(report, key) == "blocked"


def test_fresh_source_after_model_blocks_until_regeneration(tmp_path):
    raw = tmp_path / "data/raw"
    processed = tmp_path / "data/processed"
    _write(raw / "preseason_game_logs.parquet", pd.DataFrame({"SEASON": ["2026-27"]}), "2026-10-13T00:00:00")
    _write(raw / "draft_history.parquet", pd.DataFrame({"SEASON": [2026]}), "2026-10-13T00:00:00")
    _write(raw / "transactions.parquet", pd.DataFrame({"date": ["2026-10-11"]}), "2026-10-14T00:00:00")
    _write(raw / "injuries.parquet", pd.DataFrame({"date": ["2026-10-11"]}), "2026-10-13T00:00:00")
    _write(raw / "schedule_2026-27.parquet", pd.DataFrame({"season": ["2026-27"]}), "2026-10-13T00:00:00")
    _write(raw / "market/fantasypros_2026-10-01.parquet", pd.DataFrame({"player": ["Example"]}), "2026-10-13T00:00:00")
    _write(raw / "market/hashtag_2026-10-13.parquet", pd.DataFrame({"player": ["Example"]}), "2026-10-13T00:00:00")
    _write(processed / "learned_ps_2026-27.parquet", pd.DataFrame({"PLAYER_ID": [1]}), "2026-10-13T12:00:00")
    _write(processed / "draft_sheet_2026-27.parquet", pd.DataFrame({"PLAYER_ID": [1]}), "2026-10-13T13:00:00")
    _write(processed / "analyst_triggers_2026-27.parquet", pd.DataFrame({"PLAYER_ID": [1]}), "2026-10-13T14:00:00")
    (processed / "draft_session.json").write_text(json.dumps({
        "settings_connected_at": "2026-10-14T00:00:00+00:00",
        "season": 2027, "league_id": "19350273",
        "settings": {"size": 12, "slot_counts": LEAGUE["roster"]},
        "team_ids": list(range(12)),
    }), encoding="utf-8")
    report = audit(tmp_path, AS_OF, LEAGUE)
    assert _status(report, "transactions_refresh") == "ready"
    assert _status(report, "espn_roster_slots") == "ready"
    assert _status(report, "espn_target_season") == "ready"
    assert _status(report, "learned_ps_board") == "blocked"
    assert not report["ready_for_human_review"]

    for name, stamp in (("learned_ps_2026-27.parquet", "2026-10-14T01:00:00"),
                        ("draft_sheet_2026-27.parquet", "2026-10-14T02:00:00"),
                        ("analyst_triggers_2026-27.parquet", "2026-10-14T03:00:00")):
        seconds = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp()
        os.utime(processed / name, (seconds, seconds))
    report = audit(tmp_path, AS_OF, LEAGUE)
    assert report["ready_for_human_review"]
    assert _status(report, "learned_ps_board") == "ready"
