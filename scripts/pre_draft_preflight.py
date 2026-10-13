"""Read-only mid-October readiness check before the D2.3 dual freeze.

This inspects local cache vintages and the last *dated* ESPN Connect. It never
fetches data, regenerates a board, writes an override, or performs a freeze.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fantasy_nba.config import ROOT
from fantasy_nba.models.value import load_league


def _check(key: str, ready: bool, detail: str) -> dict:
    return {"key": key, "status": "ready" if ready else "blocked", "detail": detail}


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _dataset(path: Path, column: str, expected: str, key: str) -> dict:
    if not path.is_file():
        return _check(key, False, f"Missing {path.name}.")
    try:
        data = pd.read_parquet(path, columns=[column])
        values = data[column].dropna().astype(str)
        matched = int((values == expected).sum())
        latest = values.max() if not values.empty else "none"
    except (OSError, ValueError, KeyError) as exc:
        return _check(key, False, f"Cannot read {path.name}: {type(exc).__name__}.")
    return _check(key, matched > 0,
                  f"{path.name}: {matched} target rows; latest {column}={latest}; cache modified {_mtime(path).date()}.")


def _recent_cache(path: Path, as_of: date, key: str, days: int = 7) -> dict:
    if not path.is_file():
        return _check(key, False, f"Missing {path.name}.")
    modified = _mtime(path).date()
    return _check(key, as_of - timedelta(days=days) <= modified <= as_of,
                  f"{path.name} last modified {modified}; require a refresh within {days} days of {as_of}.")


def _market_cache(directory: Path, source: str, as_of: date) -> tuple[dict, Path]:
    files = sorted(directory.glob(f"{source}_*.parquet"))
    path = files[-1] if files else directory / f"{source}_missing.parquet"
    if not files:
        return _check(f"{source}_market", False, f"No {source} market cache."), path
    stamp = path.stem.removeprefix(f"{source}_")
    try:
        vintage = date.fromisoformat(stamp) if "-" in stamp else datetime.strptime(stamp, "%Y%m%d").date()
    except ValueError:
        return _check(f"{source}_market", False, f"Cannot date {path.name}."), path
    ready = as_of - timedelta(days=30) <= vintage <= as_of
    return _check(f"{source}_market", ready,
                  f"Latest {source} source is {path.name}, vintage {vintage}; require at most 30 days old."), path


def _generated_after(path: Path, dependencies: list[Path], key: str) -> dict:
    if not path.is_file():
        return _check(key, False, f"Missing {path.name}.")
    missing = [dependency.name for dependency in dependencies if not dependency.is_file()]
    if missing:
        return _check(key, False, f"Cannot validate {path.name} before {', '.join(missing)} exists.")
    newest = max(dependencies, key=_mtime)
    return _check(key, _mtime(path) >= _mtime(newest),
                  f"{path.name} modified {_mtime(path).isoformat()} vs latest input {newest.name} {_mtime(newest).isoformat()}.")


def _espn_session(path: Path, as_of: date, league: dict, target: str) -> list[dict]:
    if not path.is_file():
        return [_check("espn_live_settings", False, "No saved ESPN Connect; run the live 19.1b sweep.")]
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [_check("espn_live_settings", False, "The saved draft session is unreadable.")]
    stamp = session.get("settings_connected_at")
    try:
        connected = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if isinstance(stamp, str) else None
        connected_date = connected.astimezone(timezone.utc).date() if connected and connected.tzinfo else None
    except ValueError:
        connected_date = None
    if not connected_date or not as_of - timedelta(days=1) <= connected_date <= as_of:
        return [_check("espn_live_settings", False,
                       "No ESPN Connect timestamp within one day; cached settings and pick order are not live proof.")]
    settings = session.get("settings") or {}
    team_ids = session.get("team_ids") or []
    size = settings.get("size")
    slots = settings.get("slot_counts")
    checks = [
        _check("espn_target_season", session.get("season") == int(target[:4]) + 1,
               f"Saved ESPN season {session.get('season')}; target ending year {int(target[:4]) + 1}."),
        _check("espn_league_id", str(session.get("league_id") or "").isdigit(),
               "A numeric ESPN league ID was saved by Connect; confirm it is this season's league."),
        _check("espn_league_size", size == league.get("teams"),
               f"ESPN size {size}; league.yaml teams {league.get('teams')}; Connect {connected_date}."),
        _check("espn_roster_slots", slots == league.get("roster"),
               f"ESPN roster slots {'match' if slots == league.get('roster') else 'differ from'} league.yaml."),
        _check("espn_team_ids", isinstance(team_ids, list) and len(team_ids) == size and len(set(team_ids)) == size,
               f"{len(team_ids)} distinct cached team IDs for ESPN size {size}."),
    ]
    return checks


def audit(root: Path, as_of: date, league: dict) -> dict:
    target = f"{as_of.year}-{str(as_of.year + 1)[-2:]}" if as_of.month >= 7 else f"{as_of.year - 1}-{str(as_of.year)[-2:]}"
    raw, processed = root / "data/raw", root / "data/processed"
    preseason = raw / "preseason_game_logs.parquet"
    draft_history = raw / "draft_history.parquet"
    transactions = raw / "transactions.parquet"
    injuries = raw / "injuries.parquet"
    model = processed / f"learned_ps_{target}.parquet"
    sheet = processed / f"draft_sheet_{target}.parquet"
    schedule = raw / f"schedule_{target}.parquet"
    fantasypros_check, fantasypros = _market_cache(raw / "market", "fantasypros", as_of)
    hashtag_check, hashtag = _market_cache(raw / "market", "hashtag", as_of)
    checks = [
        _dataset(preseason, "SEASON", target, "target_preseason_logs"),
        _recent_cache(preseason, as_of, "preseason_refresh"),
        _dataset(draft_history, "SEASON", str(as_of.year), "target_draft_class"),
        _recent_cache(draft_history, as_of, "draft_history_refresh"),
        _recent_cache(transactions, as_of, "transactions_refresh"),
        _recent_cache(injuries, as_of, "injuries_refresh"),
        _dataset(schedule, "season", target, "target_schedule"),
        fantasypros_check,
        hashtag_check,
        _generated_after(model, [preseason, transactions, injuries, schedule], "learned_ps_board"),
        _generated_after(sheet, [model, draft_history, fantasypros], "draft_sheet"),
        _generated_after(processed / f"analyst_triggers_{target}.parquet", [sheet, hashtag], "analyst_triggers"),
    ]
    checks.extend(_espn_session(processed / "draft_session.json", as_of, league, target))
    return {"as_of": as_of.isoformat(), "target": target, "ready_for_human_review":
            all(item["status"] == "ready" for item in checks), "checks": checks,
            "manual_gates": ["Re-read ESPN settings and pick order on draft day.",
                             "Run a real ESPN mock draft and measure poll latency; keep manual entry available.",
                             "Re-review effective analyst entries, then approve and commit the dual freeze before opening night."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Local audit date, YYYY-MM-DD.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable results.")
    args = parser.parse_args()
    report = audit(ROOT, date.fromisoformat(args.as_of), load_league())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Pre-draft preflight {report['as_of']} ({report['target']})")
        for check in report["checks"]:
            print(f"  {check['status'].upper():7} {check['key']}: {check['detail']}")
        print("  Human gates: " + " ".join(report["manual_gates"]))
    return 0 if report["ready_for_human_review"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
