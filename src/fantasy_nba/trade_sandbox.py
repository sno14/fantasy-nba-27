"""Pure, read-only two-team trade scenarios over current roster IDs.

Roster ownership is validated before any metrics are calculated. Uneven trades
require explicit drops from the side receiving extra players; the side losing a
roster spot can optionally name unrostered pickups. No ESPN mutation occurs.
"""

from __future__ import annotations

from collections.abc import Sequence

from .lineups import calculate_week


def apply_trade(
    a_roster: Sequence[int], b_roster: Sequence[int], available: set[int],
    out_a: Sequence[int], out_b: Sequence[int], drop_a: Sequence[int] = (),
    drop_b: Sequence[int] = (), pickup_a: Sequence[int] = (),
    pickup_b: Sequence[int] = (),
) -> dict:
    a, b = list(map(int, a_roster)), list(map(int, b_roster))
    out_a, out_b = list(map(int, out_a)), list(map(int, out_b))
    drop_a, drop_b = list(map(int, drop_a)), list(map(int, drop_b))
    pickup_a, pickup_b = list(map(int, pickup_a)), list(map(int, pickup_b))
    if not out_a or not out_b:
        raise ValueError("Both teams must send at least one player")
    if len(a) != len(set(a)) or len(b) != len(set(b)) or set(a) & set(b):
        raise ValueError("Current rosters contain duplicate ownership")
    chosen = out_a + out_b + drop_a + drop_b + pickup_a + pickup_b
    if len(chosen) != len(set(chosen)):
        raise ValueError("A player can appear only once in the scenario")
    if not set(out_a + drop_a) <= set(a) or not set(out_b + drop_b) <= set(b):
        raise ValueError("Outgoing and drop players must belong to their selected team")
    if not set(pickup_a + pickup_b) <= available:
        raise ValueError("Optional pickups must be currently unrostered")

    surplus_a = len(out_b) - len(out_a)
    surplus_b = -surplus_a
    if len(drop_a) != max(0, surplus_a) or len(drop_b) != max(0, surplus_b):
        raise ValueError("The side receiving extra players must select one drop per extra player")
    if len(pickup_a) > max(0, -surplus_a) or len(pickup_b) > max(0, -surplus_b):
        raise ValueError("Optional pickups cannot exceed the vacated roster spots")

    a_after = [pid for pid in a if pid not in set(out_a + drop_a)] + out_b + pickup_a
    b_after = [pid for pid in b if pid not in set(out_b + drop_b)] + out_a + pickup_b
    if len(a_after) != len(set(a_after)) or len(b_after) != len(set(b_after)) or set(a_after) & set(b_after):
        raise ValueError("Trade result contains duplicate ownership")
    if len(a_after) + len(b_after) != len(a) + len(b) - len(drop_a) - len(drop_b) + len(pickup_a) + len(pickup_b):
        raise ValueError("Trade result does not reconcile")
    return {
        "a_after": a_after, "b_after": b_after,
        "a_roster_delta": len(a_after) - len(a),
        "b_roster_delta": len(b_after) - len(b),
        "released_ids": drop_a + drop_b,
        "acquired_ids": pickup_a + pickup_b,
    }


def summarize_roster(
    rows: Sequence[dict], positions: dict[int, list[str]],
    starting_slots: dict[str, int], days: Sequence[str],
    projection_source: str, wire_fpts_pg: float | None,
) -> dict:
    """Comparable roster measures, with missing data kept null.

    Season totals are summed only when every player shares the same projection
    horizon/source. Player risk ranges remain individual, never summed into a
    spurious team confidence interval.
    """
    fpg = [row.get("fpts_pg") for row in rows]
    fpg_total = round(sum(fpg), 1) if all(v is not None for v in fpg) else None
    season = [row.get("fpts_total") for row in rows]
    common = all(row.get("projection_source") == projection_source for row in rows)
    season_total = round(sum(season), 1) if common and all(v is not None for v in season) else None
    static_rows = [{**row, "games": ["all"], "unknown_game_dates": False} for row in rows]
    starter = calculate_week(static_rows, positions, starting_slots, ["all"])
    week = calculate_week(rows, positions, starting_slots, days)
    return {
        "n_players": len(rows), "fpts_pg_total": fpg_total,
        "fpts_pg_avg": round(fpg_total / len(rows), 1) if fpg_total is not None and rows else None,
        "season_total": season_total, "season_total_common_source": common,
        "starter_fpts_pg": starter["usable_points"],
        "known_starter_fpts_pg": starter["known_usable_points"],
        "starter_exact": starter["exact"],
        "starter_assignments": starter["days"][0]["assignments"],
        "open_slots": starter["days"][0]["idle_slots"],
        "depth_above_wire": (sum(v > wire_fpts_pg for v in fpg)
                             if wire_fpts_pg is not None and all(v is not None for v in fpg)
                             else None),
        "wire_fpts_pg": wire_fpts_pg,
        "week": week,
        "risk_players": [{"player_id": row["PLAYER_ID"], "name": row["PLAYER_NAME"],
                          "risk": row.get("risk"), "fpts_p10": row.get("fpts_p10"),
                          "fpts_p90": row.get("fpts_p90")}
                         for row in rows],
    }
