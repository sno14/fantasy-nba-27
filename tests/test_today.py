"""Daily-home source dates never invent a league date or live player status."""

from datetime import datetime, timezone

from fantasy_nba.api import season


def test_today_context_missing_timezone_and_sources(tmp_path, monkeypatch):
    league = tmp_path / "league.yaml"
    league.write_text("teams: 12\n", encoding="utf-8")
    monkeypatch.setattr(season, "LEAGUE_PATH", league)
    monkeypatch.setattr(season, "RAW_DIR", tmp_path)
    monkeypatch.setattr(season, "ros_dates", lambda: [])
    from fantasy_nba.api import draft
    monkeypatch.setattr(draft, "current_rosters", lambda: {"roster_source": "draft", "rosters_asof": None})

    result = season.today_context(target="2026-27")
    assert result["league_date"] is None
    assert result["board"] == {"source": "preseason_live_model", "asof": None}
    assert result["status"] == {"source": "unavailable", "asof": None}
    assert result["schedule"] == {"source": "missing", "asof": None}
    assert result["rosters"] == {"source": "draft", "asof": None, "freshness": "draft_only", "age_hours": None}


def test_today_context_uses_configured_zone_and_distinct_source_dates(tmp_path, monkeypatch):
    league = tmp_path / "league.yaml"
    league.write_text("timezone: UTC\n", encoding="utf-8")
    (tmp_path / "schedule_2026-27.parquet").write_bytes(b"cache")
    monkeypatch.setattr(season, "LEAGUE_PATH", league)
    monkeypatch.setattr(season, "RAW_DIR", tmp_path)
    monkeypatch.setattr(season, "ros_dates", lambda: ["2026-10-20"])
    from fantasy_nba.api import draft
    monkeypatch.setattr(draft, "current_rosters", lambda: {"roster_source": "espn_live", "rosters_asof": "2025-10-21T01:00:00Z"})

    result = season.today_context(target="2026-27")
    assert result["league_date"] == datetime.now(timezone.utc).date().isoformat()
    assert result["board"] == {"source": "ros_snapshot", "asof": "2026-10-20"}
    assert result["status"] == {"source": "ros_snapshot", "asof": "2026-10-20"}
    assert result["rosters"]["asof"] == "2025-10-21T01:00:00Z"
    assert result["rosters"]["freshness"] == "stale_snapshot"
    assert result["schedule"]["asof"]


def test_today_context_future_dated_roster_is_not_fresh(tmp_path, monkeypatch):
    league = tmp_path / "league.yaml"
    league.write_text("timezone: UTC\n", encoding="utf-8")
    monkeypatch.setattr(season, "LEAGUE_PATH", league)
    monkeypatch.setattr(season, "RAW_DIR", tmp_path)
    monkeypatch.setattr(season, "ros_dates", lambda: [])
    from fantasy_nba.api import draft
    monkeypatch.setattr(draft, "current_rosters", lambda: {"roster_source": "espn_live", "rosters_asof": "2099-01-01T00:00:00Z"})
    result = season.today_context(target="2026-27")
    assert result["rosters"]["freshness"] == "stale_snapshot"
    assert result["rosters"]["age_hours"] is None
