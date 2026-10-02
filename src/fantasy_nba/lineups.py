"""Pure, exact daily starting-lineup calculation for points-league planning.

Only known ESPN core eligibility is seated. Missing eligibility or FP/G makes the
corresponding usable total unknown; the known-player optimum remains a lower bound.
The output is a projection, never an ESPN lineup submission.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .models.value import NON_STARTING, SLOT_GROUPS

CORE = {"PG", "SG", "SF", "PF", "C"}


def _eligible(slot: str, positions: set[str]) -> bool:
    if slot == "UTIL":
        return bool(positions & CORE)
    if slot == "G":
        return bool(positions & {"PG", "SG"})
    if slot == "F":
        return bool(positions & {"SF", "PF"})
    return slot in positions


def _slots(starting: Mapping[str, int]) -> list[tuple[str, int, str]]:
    slots = []
    for raw, count in starting.items():
        slot = raw.upper()
        if slot in NON_STARTING:
            continue
        if slot not in SLOT_GROUPS or isinstance(count, bool) or int(count) != count or count < 0:
            raise ValueError(f"Invalid starting slot: {raw}={count}")
        for index in range(1, int(count) + 1):
            slots.append((slot, index, f"{slot} {index}" if count > 1 else slot))
    return slots


def _day_states(
    playing: Sequence[dict], positions: Mapping[int | str, Sequence[str]],
    slots: list[tuple[str, int, str]],
) -> tuple[dict[int, tuple[float, tuple[int | None, ...]]], list[int], list[int], float]:
    """All best partial matchings, keyed by occupied-slot mask."""
    unknown_eligibility = []
    unknown_projection = []
    candidates = []
    known_raw = 0.0
    for row in playing:
        pid = int(row["PLAYER_ID"])
        value = row.get("fpts_pg")
        if (value is None or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            unknown_projection.append(pid)
        else:
            known_raw += float(value)
        eligible = {str(p).upper() for p in (positions.get(pid) or positions.get(str(pid)) or [])} & CORE
        if not eligible:
            unknown_eligibility.append(pid)
        if eligible and pid not in unknown_projection:
            candidates.append((row, eligible, float(value)))

    empty = (None,) * len(slots)
    states: dict[int, tuple[float, tuple[int | None, ...]]] = {0: (0.0, empty)}
    for row, eligible, value in candidates:
        pid = int(row["PLAYER_ID"])
        next_states = states.copy()
        for mask, (score, assigned) in states.items():
            for i, (slot, _, _) in enumerate(slots):
                bit = 1 << i
                if mask & bit or not _eligible(slot, eligible):
                    continue
                new_mask, new_score = mask | bit, score + value
                old = next_states.get(new_mask)
                if old is None or new_score > old[0] + 1e-9:
                    seat = list(assigned)
                    seat[i] = pid
                    next_states[new_mask] = (new_score, tuple(seat))
        states = next_states
    return states, unknown_eligibility, unknown_projection, known_raw


def prepared_day_scores(
    rows: Sequence[dict], positions: Mapping[int | str, Sequence[str]],
    starting: Mapping[str, int], days: Sequence[str],
) -> dict:
    """Reusable exact day states for scoring many possible single-player additions.

    For each slot, ``free_slot_best`` is the strongest existing lineup that leaves
    it open. Adding one player can occupy exactly one such slot, so this gives the
    exact post-add score in O(number of eligible slots) per candidate/day.
    """
    slots = _slots(starting)
    out = []
    for day in days:
        playing = sorted((r for r in rows if day in r["games"]), key=lambda r: int(r["PLAYER_ID"]))
        states, missing_pos, missing_fpg, _ = _day_states(playing, positions, slots)
        base_score = max(score for score, _ in states.values())
        free = [max(score for mask, (score, _) in states.items() if not mask & (1 << i))
                for i in range(len(slots))]
        out.append({"day": day, "base_score": base_score, "free_slot_best": free,
                    "exact": not missing_pos and not missing_fpg})
    return {"slots": [slot for slot, _, _ in slots], "days": out,
            "exact": not any(row.get("unknown_game_dates") for row in rows) and
                     all(day["exact"] for day in out)}


def calculate_week(
    rows: Sequence[dict], positions: Mapping[int | str, Sequence[str]],
    starting: Mapping[str, int], days: Sequence[str],
) -> dict:
    """Maximize FP/G independently each day across legal, unique player-slot pairs.

    ``rows`` contain PLAYER_ID, PLAYER_NAME, fpts_pg and availability-filtered games.
    An empty ``days`` means no verified schedule, rather than a zero-point week.
    """
    slots = _slots(starting)
    if len({r["PLAYER_ID"] for r in rows}) != len(rows):
        raise ValueError("Duplicate roster player ID")
    if not days:
        return {"has_schedule": False, "raw_points": None, "known_raw_points": 0.0,
                "usable_points": None, "known_usable_points": 0.0,
                "benched_points": None, "unknown_game_dates": [], "exact": False, "days": []}

    unknown_game_dates = sorted(int(r["PLAYER_ID"]) for r in rows if r.get("unknown_game_dates"))

    daily = []
    for day in days:
        playing = sorted((r for r in rows if day in r["games"]), key=lambda r: int(r["PLAYER_ID"]))
        states, unknown_eligibility, unknown_projection, known_raw = _day_states(
            playing, positions, slots)
        # If points tie (for example a zero-FP/G player), prefer a legal start
        # over an idle slot so the assignment and benched-game count stay useful.
        _, (usable, assignment) = max(states.items(),
                                      key=lambda item: (item[1][0], item[0].bit_count()))
        by_id = {int(row["PLAYER_ID"]): row for row in playing}
        assignments = [
            {"slot": label, "player_id": pid, "player_name": str(by_id[pid]["PLAYER_NAME"]),
             "fpts_pg": round(float(by_id[pid]["fpts_pg"]), 1)}
            for (_, _, label), pid in zip(slots, assignment) if pid is not None
        ]
        exact = not unknown_eligibility and not unknown_projection
        raw = round(known_raw, 1) if not unknown_projection else None
        usable = round(usable, 1)
        daily.append({
            "day": day, "games": len(playing), "raw_points": raw,
            "known_raw_points": round(known_raw, 1),
            "usable_points": usable if exact else None,
            "known_usable_points": usable,
            "benched_points": round(max(0.0, known_raw - usable), 1) if exact else None,
            "benched_games": len(playing) - len(assignments) if exact else None,
            "assignments": assignments,
            "idle_slots": [label for (_, _, label), pid in zip(slots, assignment) if pid is None],
            "unknown_eligibility": unknown_eligibility,
            "unknown_projection": unknown_projection,
            "exact": exact,
        })
    exact = not unknown_game_dates and all(day["exact"] for day in daily)
    known_raw = round(sum(day["known_raw_points"] for day in daily), 1)
    known_usable = round(sum(day["known_usable_points"] for day in daily), 1)
    raw = (known_raw if not unknown_game_dates and
           all(not day["unknown_projection"] for day in daily) else None)
    return {"has_schedule": True, "raw_points": raw, "known_raw_points": known_raw,
            "usable_points": known_usable if exact else None,
            "known_usable_points": known_usable,
            "benched_points": round(max(0.0, known_raw - known_usable), 1) if exact else None,
            "unknown_game_dates": unknown_game_dates, "exact": exact, "days": daily}
