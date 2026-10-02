"""Read-only two-team trade sandbox. No endpoint in this router mutates a roster."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import yaml
from fastapi import APIRouter, HTTPException, Query

from ..models.analyst import name_key
from ..trade_sandbox import apply_trade, summarize_roster
from . import boards, season
from .draft import current_rosters, player_positions

router = APIRouter(prefix="/api")


def _ids(value: str) -> list[int]:
    return season._id_list(value)


def _ownership_age(asof: str | None, source: str) -> tuple[str, float | None]:
    if source != "espn_live":
        return "draft_only", None
    if not asof:
        return "stale_snapshot", None
    try:
        pulled = datetime.fromisoformat(asof.replace("Z", "+00:00"))
        if pulled.tzinfo is not None:
            hours = max(0, round((datetime.now(timezone.utc) - pulled).total_seconds() / 3600, 1))
            return ("fresh_snapshot" if hours <= 24 else "stale_snapshot"), hours
    except ValueError:
        pass
    return "stale_snapshot", None


def _market_reference(rows: list[dict]) -> tuple[str | None, list[dict]]:
    market_date, market = season.latest_market("hashtag")
    by_name = {}
    if not market.empty and {"player", "consensus_rank"} <= set(market.columns):
        for market_row in market.itertuples(index=False):
            key = name_key(str(market_row.player))
            if key not in by_name and pd.notna(market_row.consensus_rank):
                by_name[key] = int(market_row.consensus_rank)
    out = []
    for row in rows:
        consensus = by_name.get(name_key(row["PLAYER_NAME"]))
        out.append({**row, "consensus_rank": consensus,
                    "market_gap": consensus - row["rank"]
                    if consensus is not None and row.get("rank") is not None else None})
    return market_date, out


def _playoff_volume(before_a: list[dict], after_a: list[dict],
                    before_b: list[dict], after_b: list[dict], target: str) -> dict | None:
    league = (yaml.safe_load(season.LEAGUE_PATH.read_text(encoding="utf-8"))
              if season.LEAGUE_PATH.exists() else {}) or {}
    if not league.get("fantasy_playoff_weeks_confirmed"):
        return None
    weeks = sorted({int(w) for w in league.get("fantasy_playoff_weeks") or []})
    if not weeks:
        return None
    schedule = boards.team_week_games(target)
    if schedule.empty:
        return None
    counts = {(str(team), int(week)): len(group) for (team, week), group
              in schedule.groupby(["team", "week"])}
    known_teams = set(schedule["team"].astype(str))

    def volume(rows: list[dict]) -> dict[str, int | None]:
        return {str(week): (sum(counts.get((row["TEAM_ABBREVIATION"], week), 0)
                                for row in rows) if all(row["TEAM_ABBREVIATION"] in known_teams for row in rows)
                            else None) for week in weeks}

    return {"weeks": weeks, "metric": "raw rostered game counts, not feasible starts",
            "a_before": volume(before_a), "a_after": volume(after_a),
            "b_before": volume(before_b), "b_after": volume(after_b)}


@router.get("/trade-sandbox")
def trade_sandbox(
    team_a: int | None = Query(default=None), team_b: int | None = Query(default=None),
    out_a: str = Query(default=""), out_b: str = Query(default=""),
    drop_a: str = Query(default=""), drop_b: str = Query(default=""),
    pickup_a: str = Query(default=""), pickup_b: str = Query(default=""),
    week: int | None = Query(default=None), start: str | None = Query(default=None),
    end: str | None = Query(default=None), target: str = Query(default=None),
) -> dict:
    """Validate ownership and compare both rosters before/after a proposed trade."""
    target = target or boards.CURRENT_TARGET
    own = current_rosters()
    rosters = own["rosters"]
    team_ids = sorted(t for t, ids in rosters.items() if ids)
    if len(team_ids) < 2:
        return {"has_teams": False, "note": "Two rostered league teams are needed. Load or simulate rosters in the Draft Room."}
    team_a = team_a if team_a is not None else (own["my_team_id"] if own["my_team_id"] in team_ids else team_ids[0])
    team_b = team_b if team_b is not None else next((t for t in team_ids if t != team_a), None)
    if team_a not in team_ids or team_b not in team_ids or team_a == team_b:
        raise HTTPException(422, "Select two distinct rostered league teams")
    dates = season.ros_dates()
    if week is None:
        week = season.default_week(season._week_ends(target), dates[-1] if dates else None)
    meta, _ = season.week_games_by_team(target, week) if week is not None else ({}, {})
    if meta:
        start, end = start or meta["start"], end or meta["end"]
        try:
            for value in (start, end):
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError(value)
        except ValueError as exc:
            raise HTTPException(422, "Dates must be valid YYYY-MM-DD values") from exc
        if start > end or start < meta["start"] or end > meta["end"]:
            raise HTTPException(422, "Comparison dates must fall within the selected week")
        days = [day for day in meta["days"] if start <= day <= end]
    else:
        start, end, days = None, None, []
    a_ids, b_ids = rosters[team_a], rosters[team_b]
    outgoing_a, outgoing_b = _ids(out_a), _ids(out_b)
    drops_a, drops_b = _ids(drop_a), _ids(drop_b)
    pickups_a, pickups_b = _ids(pickup_a), _ids(pickup_b)
    board_lookup = season._board_lookup()
    projection_source = "ros" if dates else "preseason"
    positions = player_positions() | own["positions"]
    rostered = {pid for players in rosters.values() for pid in players}
    ros = season._ros_cached(dates[-1]) if dates else pd.DataFrame()
    ros_by_id = {int(row.PLAYER_ID): row for row in ros.itertuples(index=False)} if not ros.empty else {}
    pool_ids = list(ros_by_id) if dates else list(board_lookup)
    available_ids = [pid for pid in dict.fromkeys(pool_ids) if pid not in rostered]
    available = []
    for pid in available_ids:
        s, b = ros_by_id.get(pid), board_lookup.get(pid, {})
        fpg = getattr(s, "fpts_pg", None) if s is not None else b.get("fpts_pg")
        status = getattr(s, "status_override", "") if s is not None else ""
        available.append({"player_id": pid,
                          "name": str(getattr(s, "PLAYER_NAME", None) or b.get("PLAYER_NAME") or f"#{pid}"),
                          "team": getattr(s, "TEAM_ABBREVIATION", None) or b.get("TEAM_ABBREVIATION"),
                          "fpts_pg": None if fpg is None or pd.isna(fpg) else round(float(fpg), 1),
                          "status": str(status) if status is not None and pd.notna(status) else ""})
    wire_fpg = max((row["fpts_pg"] for row in available
                    if row["fpts_pg"] is not None and not row["status"].startswith("out_")), default=None)
    selected_ids = list(dict.fromkeys(a_ids + b_ids + pickups_a + pickups_b))
    selected, _ = season._roster_week_rows(selected_ids, week, target, board_lookup=board_lookup)
    market_date, selected_rows = _market_reference(selected)
    all_rows = {row["PLAYER_ID"]: row for row in selected_rows}
    a_rows = [all_rows[pid] for pid in a_ids]
    b_rows = [all_rows[pid] for pid in b_ids]
    capacity = sum(n for slot, n in own["roster_slots"].items() if slot != "IR")
    ir_slots = own["roster_slots"].get("IR", 0)
    ownership_status, age_hours = _ownership_age(own["rosters_asof"], own["roster_source"])
    base = {
        "has_teams": True, "team_a": team_a, "team_b": team_b, "my_team_id": own["my_team_id"],
        "teams": [{"team_id": tid, "n_players": len(rosters[tid])} for tid in team_ids],
        "a_roster": a_rows, "b_roster": b_rows, "available": available,
        "roster_source": own["roster_source"], "rosters_asof": own["rosters_asof"],
        "ownership_status": ownership_status, "ownership_age_hours": age_hours,
        "projection_source": projection_source, "projection_asof": dates[-1] if dates else None,
        "market_date": market_date, "wire_fpts_pg": wire_fpg,
        "starting_slots": own["starting_slots"], "slot_source": own["slot_source"],
        "standard_roster_capacity": capacity, "ir_slots": ir_slots,
        "ir_assignments_known": False,
        "has_schedule": bool(meta), "week": week, "week_name": meta.get("week_name"),
        "start": start, "end": end, "days": days, "scenario": None,
        "note": "Read-only scenario. ESPN trade review, roster locks and IR placement are not verified here.",
    }
    if not any((outgoing_a, outgoing_b, drops_a, drops_b, pickups_a, pickups_b)):
        return base
    try:
        move = apply_trade(a_ids, b_ids, set(available_ids), outgoing_a, outgoing_b,
                           drops_a, drops_b, pickups_a, pickups_b)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    a_after = [all_rows[pid] for pid in move["a_after"]]
    b_after = [all_rows[pid] for pid in move["b_after"]]
    a_before = summarize_roster(a_rows, positions, own["starting_slots"], days,
                                projection_source, wire_fpg)
    b_before = summarize_roster(b_rows, positions, own["starting_slots"], days,
                                projection_source, wire_fpg)
    a_summary = summarize_roster(a_after, positions, own["starting_slots"], days,
                                 projection_source, wire_fpg)
    b_summary = summarize_roster(b_after, positions, own["starting_slots"], days,
                                 projection_source, wire_fpg)
    return {**base, "scenario": {
        "out_a": outgoing_a, "out_b": outgoing_b, "drop_a": drops_a, "drop_b": drops_b,
        "pickup_a": pickups_a, "pickup_b": pickups_b,
        "a_after_ids": move["a_after"], "b_after_ids": move["b_after"],
        "released_ids": move["released_ids"], "acquired_ids": move["acquired_ids"],
        "a": {"before": a_before, "after": a_summary, "rows_after": a_after,
              "roster_delta": move["a_roster_delta"]},
        "b": {"before": b_before, "after": b_summary, "rows_after": b_after,
              "roster_delta": move["b_roster_delta"]},
        "capacity": {"standard": capacity, "ir_slots": ir_slots,
                     "a_after_over_standard": len(a_after) > capacity,
                     "b_after_over_standard": len(b_after) > capacity,
                     "status": "conditional_ir_unknown"},
        "playoff_volume": _playoff_volume(a_rows, a_after, b_rows, b_after, target),
    }}
