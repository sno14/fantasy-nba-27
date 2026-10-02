"""Read-only team rotation diagnostics from current boards and dated local evidence.

The 240-minute line is a reference, never a constraint on the model. Preview budget
allocations are separate historical judgments, never applied to projection rows.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
import yaml
from fastapi import APIRouter, HTTPException

from ..config import MANUAL_DIR
from ..models.analyst import name_key
from . import boards
from .draft import player_positions
from .season import load_ros, ros_dates

router = APIRouter(prefix="/api")
PREVIEW_DIR = MANUAL_DIR / "bbm_team_previews"
REFERENCE_MINUTES = 240.0


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2) if math.isfinite(number) else None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def latest_previews(directory: Path = PREVIEW_DIR) -> dict[str, dict]:
    """Choose the latest dated ledger per team; a failed new gate supersedes old budgets."""
    selected: dict[str, tuple[str, dict]] = {}
    if not directory.exists():
        return {}
    for path in directory.glob("*.yaml"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.yaml", path.name):
            continue
        try:
            ledger = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(ledger, dict) or not isinstance(ledger.get("rows"), list):
                continue
            team = ledger.get("team")
            stamp = str(ledger.get("preview_date", ""))
            date.fromisoformat(stamp)
            if not isinstance(team, str) or not re.fullmatch(r"[A-Z]{3}", team):
                continue
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if team not in selected or (stamp, path.name) > (selected[team][0], selected[team][1]["_file"]):
            selected[team] = (stamp, {**ledger, "_file": path.name})
    return {team: item[1] for team, item in selected.items()}


def _preview_info(ledger: dict | None, names: list[str]) -> tuple[dict | None, dict[str, dict]]:
    if not ledger:
        return None, {}
    source_rows = [row for row in ledger["rows"] if isinstance(row, dict) and isinstance(row.get("player"), str)]
    budget_values = [_number(row.get("budget_mpg")) for row in source_rows]
    gate = _text(ledger.get("budget_gate")) or ""
    budget_valid = (bool(source_rows) and all(value is not None and value >= 0 for value in budget_values)
                    and abs(sum(budget_values) - REFERENCE_MINUTES) < 0.11
                    and _number(ledger.get("sum_budget_mpg")) == REFERENCE_MINUTES
                    and not gate.lower().startswith("failed"))
    by_key: dict[str, list[dict]] = defaultdict(list)
    for row in source_rows:
        by_key[name_key(row["player"])].append(row)
    matched = {name: by_key[name_key(name)][0] for name in names if len(by_key[name_key(name)]) == 1}
    info = {"date": str(ledger["preview_date"]), "hasClosedBudget": budget_valid,
            "budgetMinutes": REFERENCE_MINUTES if budget_valid else None,
            "matchedPlayers": len(matched), "ledgerPlayers": len(source_rows),
            "note": "Dated preview allocation; separate from today's board." if budget_valid else
                    "No closed 240-minute allocation in the latest preview; quoted figures remain dated evidence."}
    return info, matched


def build_rotation(board_a: pd.DataFrame, board_b: pd.DataFrame,
                   previews: dict[str, dict] | None = None,
                   ros: pd.DataFrame | None = None, ros_date: str | None = None,
                   positions: dict[int, list[str]] | None = None) -> dict:
    """Join by stable player ID, retain missing values, and keep evidence sources apart."""
    previews = previews or {}
    positions = positions or {}
    base = {int(row.PLAYER_ID): row for row in board_a.itertuples(index=False)}
    ros_rows = {int(row.PLAYER_ID): row for row in ros.itertuples(index=False)} if ros is not None and "PLAYER_ID" in ros.columns else {}
    has_redist = ros is not None and "redist_mpg" in ros.columns
    grouped: dict[str, list] = defaultdict(list)
    unassigned = 0
    for row in board_b.itertuples(index=False):
        team = _text(getattr(row, "TEAM_ABBREVIATION", None))
        if team:
            grouped[team].append(row)
        else:
            unassigned += 1
    teams = []
    for team in sorted(grouped):
        entries = grouped[team]
        preview, preview_rows = _preview_info(previews.get(team), [str(row.PLAYER_NAME) for row in entries])
        players = []
        for row in entries:
            pid = int(row.PLAYER_ID)
            old = base.get(pid)
            mpg, fpg = _number(getattr(row, "mpg", None)), _number(getattr(row, "fpts_pg", None))
            model_mpg = _number(getattr(old, "mpg", None)) if old is not None else None
            model_fpg = _number(getattr(old, "fpts_pg", None)) if old is not None else None
            evidence = preview_rows.get(str(row.PLAYER_NAME))
            snapshot = ros_rows.get(pid)
            if snapshot is not None and "TEAM_ABBREVIATION" in ros.columns and _text(getattr(snapshot, "TEAM_ABBREVIATION", None)) != team:
                snapshot = None
            players.append({
                "id": pid, "name": str(row.PLAYER_NAME), "team": team,
                "rank": int(row.rank), "positions": positions.get(pid, []),
                "modelMpg": model_mpg, "mpg": mpg, "mpgDelta": round(mpg - model_mpg, 2) if mpg is not None and model_mpg is not None else None,
                "modelFpg": model_fpg, "fpg": fpg, "fpgDelta": round(fpg - model_fpg, 2) if fpg is not None and model_fpg is not None else None,
                "modelFpPerMinute": round(model_fpg / model_mpg, 2) if model_fpg is not None and model_mpg and model_mpg > 0 else None,
                "fpPerMinute": round(fpg / mpg, 2) if fpg is not None and mpg and mpg > 0 else None,
                "analystAction": _text(getattr(row, "analyst_action", None)),
                "analystDate": _text(getattr(row, "analyst_date", None)),
                "analystCategory": _text(getattr(row, "analyst_category", None)),
                "previewStatedMpg": _text(evidence.get("bbm_mpg")) if evidence else None,
                "previewBudgetMpg": _number(evidence.get("budget_mpg")) if evidence and preview and preview["hasClosedBudget"] else None,
                "rosMpg": _number(getattr(snapshot, "mpg", None)) if snapshot is not None else None,
                "rosFpg": _number(getattr(snapshot, "fpts_pg", None)) if snapshot is not None else None,
                "status": _text(getattr(snapshot, "status_override", None)) if snapshot is not None else None,
                "redistMpg": _number(getattr(snapshot, "redist_mpg", None)) if snapshot is not None and has_redist else None,
            })
        players.sort(key=lambda item: (item["mpg"] is None, -(item["mpg"] or 0), item["rank"]))
        model_values = [item["modelMpg"] for item in players if item["modelMpg"] is not None]
        board_values = [item["mpg"] for item in players if item["mpg"] is not None]
        teams.append({"team": team, "players": players, "count": len(players),
                      "modelMinutes": round(sum(model_values), 1), "modelMissing": len(players) - len(model_values),
                      "boardMinutes": round(sum(board_values), 1), "boardMissing": len(players) - len(board_values),
                      "gapTo240": round(sum(board_values) - REFERENCE_MINUTES, 1),
                      "preview": preview})
    return {"target": boards.CURRENT_TARGET, "model": "learned", "stance": "safe",
            "rankedBy": "safe season value", "referenceMinutes": REFERENCE_MINUTES,
            "unassignedPlayers": unassigned, "rosDate": ros_date,
            "hasRedistribution": has_redist, "teams": teams}


@router.get("/rotation")
def rotation() -> dict:
    if not boards.data_ready():
        raise HTTPException(503, "No cached player data for rotation diagnostics")
    target = boards.CURRENT_TARGET
    model = boards.ranked_board(target, "learned", "safe", apply_analyst=False)
    approved = boards.ranked_board(target, "learned", "safe", apply_analyst=True)
    dates = [item for item in ros_dates() if f"{target[:4]}-10-01" <= item < f"{int(target[:4]) + 1}-10-01"]
    latest = dates[-1] if dates else None
    snapshot = load_ros(latest) if latest else None
    return build_rotation(model, approved, latest_previews(), snapshot, latest, player_positions())
