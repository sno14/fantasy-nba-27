"""Curated public rotation summary, derived solely from the published board.

No preview ledger, raw transcript, analyst rationale, roster or availability data
is read here. The file is a view of a dated board snapshot, not a depth chart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD_PATH = ROOT / "static" / "data" / "board.json"
OUT = ROOT / "static" / "data" / "rotation.json"
PLAYER_KEYS = {"id", "name", "rank", "mpg", "fpg", "gp", "fpPerMinute", "positions", "analystAction", "analystDate"}
TEAM_KEYS = {"team", "count", "projectedMinutes", "missingMpg", "gapTo240", "players"}
POSITIONS = {"PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"}


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2) if math.isfinite(number) else None


def public_rotation(board: dict) -> dict:
    if board.get("ranked_by") != "fpts_pg" or not isinstance(board.get("rows"), list) or not board["rows"]:
        raise ValueError("Public rotation requires an FP/G-ranked board")
    season = board.get("season") or (re.search(r"\b\d{4}-\d{2}\b", board.get("title", "")) or [None])[0]
    if not isinstance(season, str) or not re.fullmatch(r"\d{4}-\d{2}", season) or not isinstance(board.get("generated_at"), str):
        raise ValueError("Public rotation requires dated season metadata")
    grouped = defaultdict(list)
    unassigned = 0
    ids = set()
    for row in board["rows"]:
        pid = row.get("PLAYER_ID")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid == 0 or pid in ids:
            raise ValueError("Public rotation requires unique player IDs")
        ids.add(pid)
        if not isinstance(row.get("rank"), int) or row["rank"] < 1:
            raise ValueError("Public rotation requires ordinal ranks")
        team = row.get("TEAM_ABBREVIATION")
        if not isinstance(team, str) or not re.fullmatch(r"[A-Z]{3}", team):
            unassigned += 1
            continue
        mpg, fpg = _number(row.get("mpg")), _number(row.get("fpts_pg"))
        raw_positions = row.get("positions")
        positions = [item for item in raw_positions.split("|") if item in POSITIONS] if isinstance(raw_positions, str) else []
        action = row.get("analyst_action")
        date = row.get("analyst_date")
        grouped[team].append({"id": pid, "name": str(row.get("PLAYER_NAME") or ""),
                              "rank": row["rank"], "mpg": mpg, "fpg": fpg,
                              "gp": _number(row.get("gp")),
                              "fpPerMinute": round(fpg / mpg, 2) if fpg is not None and mpg and mpg > 0 else None,
                              "positions": positions,
                              "analystAction": action if isinstance(action, str) else None,
                              "analystDate": date if isinstance(date, str) else None})
    teams = []
    for team, players in sorted(grouped.items()):
        players.sort(key=lambda item: (item["mpg"] is None, -(item["mpg"] or 0), item["rank"]))
        values = [item["mpg"] for item in players if item["mpg"] is not None]
        teams.append({"team": team, "count": len(players),
                      "projectedMinutes": round(sum(values), 1), "missingMpg": len(players) - len(values),
                      "gapTo240": round(sum(values) - 240, 1), "players": players})
    body = json.dumps(teams, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"schema": 1, "season": season, "sourceBoardGeneratedAt": board["generated_at"],
            "rankedBy": "FP/G ordinal", "source": "published Board B", "version": hashlib.sha256(body).hexdigest()[:12],
            "referenceMinutes": 240, "unassignedPlayers": unassigned, "teams": teams}


def write_public_rotation(board: dict, out: Path = OUT) -> dict:
    data = public_rotation(board)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(out)
    return data


def validate(board_path: Path = BOARD_PATH, out: Path = OUT) -> int:
    board = json.loads(board_path.read_text(encoding="utf-8"))
    expected = public_rotation(board)
    actual = json.loads(out.read_text(encoding="utf-8"))
    if actual != expected:
        raise ValueError("Public rotation is stale, hand-edited or contains extra fields")
    if any(set(team) != TEAM_KEYS or any(set(player) != PLAYER_KEYS for player in team["players"])
           for team in actual["teams"]):
        raise ValueError("Public rotation violates the field allowlist")
    return len(actual["teams"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Validate the committed summary against board.json")
    args = parser.parse_args()
    if args.check:
        print(f"Validated {validate()} curated team summaries")
    else:
        source = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
        print(f"Exported {len(write_public_rotation(source)['teams'])} curated team summaries -> {OUT.relative_to(ROOT)}")
