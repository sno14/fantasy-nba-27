"""Pure single-add/drop planning scenarios over the exact daily lineup engine.

The effective date and daily lock timing are explicit assumptions. This module
never asserts that ESPN would permit a transaction or submits one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import math

from .lineups import CORE, _eligible, calculate_week, prepared_day_scores


def scenario_days(days: Sequence[str], start: str, end: str) -> list[str]:
    if start > end:
        raise ValueError("Start date must not follow end date")
    return [day for day in days if start <= day <= end]


def move_cutoff(effective_date: str, lock_rule: str) -> str:
    """First game date affected by a move assumed effective on ``effective_date``."""
    if lock_rule not in {"before_games", "after_games"}:
        raise ValueError("lock_rule must be before_games or after_games")
    return effective_date


def _affected(day: str, cutoff: str, lock_rule: str) -> bool:
    return day >= cutoff if lock_rule == "before_games" else day > cutoff


def prepare_drop(
    roster_rows: Sequence[dict], drop_id: int,
    positions: Mapping[int | str, Sequence[str]], starting: Mapping[str, int],
    days: Sequence[str], effective_date: str, lock_rule: str,
) -> dict:
    """Cache exact post-drop day states once for many possible pickups."""
    move_cutoff(effective_date, lock_rule)
    rows = []
    for row in roster_rows:
        if int(row["PLAYER_ID"]) == drop_id:
            rows.append({**row, "games": [day for day in row["games"]
                                           if not _affected(day, effective_date, lock_rule)],
                         "unknown_game_dates": bool(row.get("unknown_game_dates")) and
                         any(not _affected(day, effective_date, lock_rule) for day in days)})
        else:
            rows.append(row)
    return prepared_day_scores(rows, positions, starting, days)


def quick_move_score(
    prepared: dict, before: dict, drop: dict, pickup: dict,
    positions: Mapping[int | str, Sequence[str]], days: Sequence[str],
    effective_date: str, lock_rule: str,
) -> tuple[float | None, float | None]:
    """Exact marginal usable/raw deltas without rebuilding assignments per pickup."""
    pid = int(pickup["PLAYER_ID"])
    eligible = {str(p).upper() for p in (positions.get(pid) or positions.get(str(pid)) or [])} & CORE
    active = [day for day in days if day in pickup["games"] and
              _affected(day, effective_date, lock_rule)]
    value = pickup.get("fpts_pg")
    valid_value = (isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) and value >= 0)
    unknown_dates = bool(pickup.get("unknown_game_dates")) and any(
        _affected(day, effective_date, lock_rule) for day in days)
    usable_delta = None
    if (before["usable_points"] is not None and prepared["exact"] and not unknown_dates
            and (not active or (eligible and valid_value))):
        total = 0.0
        for day in prepared["days"]:
            best = day["base_score"]
            if day["day"] in active:
                for i, slot in enumerate(prepared["slots"]):
                    if _eligible(slot, eligible):
                        best = max(best, day["free_slot_best"][i] + float(value))
            total += best
        usable_delta = round(total - before["usable_points"], 1)
    lost_games = sum(day in days and _affected(day, effective_date, lock_rule)
                     for day in drop["games"])
    drop_value = drop.get("fpts_pg")
    valid_drop = (isinstance(drop_value, (int, float)) and not isinstance(drop_value, bool)
                  and math.isfinite(drop_value) and drop_value >= 0)
    raw_delta = None
    if (before["raw_points"] is not None and not unknown_dates and
            (not active or valid_value) and (not lost_games or valid_drop)):
        raw_delta = round((float(value) * len(active) if active else 0.0) -
                          (float(drop_value) * lost_games if lost_games else 0.0), 1)
    return usable_delta, raw_delta


def evaluate_move(
    roster_rows: Sequence[dict], pickup: dict, drop_id: int,
    positions: Mapping[int | str, Sequence[str]], starting: Mapping[str, int],
    days: Sequence[str], effective_date: str, lock_rule: str,
    before: dict | None = None,
) -> dict:
    """Compare the same roster before and after one assumed add/drop.

    The dropped player remains available before the move takes effect. The pickup
    contributes only on later dates; all other roster games stay unchanged.
    """
    move_cutoff(effective_date, lock_rule)
    if drop_id not in {int(row["PLAYER_ID"]) for row in roster_rows}:
        raise ValueError("Drop player is not on the selected roster")
    pickup_id = int(pickup["PLAYER_ID"])
    if pickup_id in {int(row["PLAYER_ID"]) for row in roster_rows}:
        raise ValueError("Pickup is already on the selected roster")
    before = before or calculate_week(roster_rows, positions, starting, days)
    after_rows = []
    for row in roster_rows:
        if int(row["PLAYER_ID"]) == drop_id:
            after_rows.append({**row, "games": [day for day in row["games"]
                                                if not _affected(day, effective_date, lock_rule)],
                               "unknown_game_dates": bool(row.get("unknown_game_dates")) and
                               any(not _affected(day, effective_date, lock_rule) for day in days)})
        else:
            after_rows.append(row)
    add_games = [day for day in pickup["games"] if _affected(day, effective_date, lock_rule)]
    after_rows.append({**pickup, "games": add_games,
                       "unknown_game_dates": bool(pickup.get("unknown_game_dates")) and
                       any(_affected(day, effective_date, lock_rule) for day in days)})
    after = calculate_week(after_rows, positions, starting, days)

    drop_lost = sum(a["fpts_pg"] for day in before["days"]
                    if _affected(day["day"], effective_date, lock_rule)
                    for a in day["assignments"] if a["player_id"] == drop_id)
    add_starts = [day["day"] for day in after["days"]
                  if any(a["player_id"] == pickup_id for a in day["assignments"])]
    add_playing = [day for day in days if day in add_games]
    add_benched = [day for day in add_playing if day not in add_starts]
    add_used = sum(a["fpts_pg"] for day in after["days"]
                   for a in day["assignments"] if a["player_id"] == pickup_id)
    add_raw = (round(float(pickup["fpts_pg"]) * len(add_playing), 1)
               if pickup.get("fpts_pg") is not None else None)
    before_usable, after_usable = before["usable_points"], after["usable_points"]
    before_raw, after_raw = before["raw_points"], after["raw_points"]
    return {
        "drop_id": drop_id, "pickup_id": pickup_id,
        "before": before, "after": after,
        "usable_delta": (round(after_usable - before_usable, 1)
                         if before_usable is not None and after_usable is not None else None),
        "raw_delta": (round(after_raw - before_raw, 1)
                      if before_raw is not None and after_raw is not None else None),
        "drop_lost_starter_points": round(drop_lost, 1) if before["exact"] else None,
        "pickup_used_points": round(add_used, 1) if after["exact"] else None,
        "pickup_raw_points": add_raw,
        "pickup_start_dates": add_starts,
        "pickup_benched_dates": add_benched,
        "pickup_eligible_game_dates": add_playing,
    }
