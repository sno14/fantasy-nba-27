"""Replacement value / VOR — the decision layer's first column (Step D1.2, critique §9).

Accuracy work optimizes the projection; drafts are won by *relative* value: a player's worth
is his production above what a manager could roster anyway. ``replacement_level`` simulates
the league's draft greedily (board order, ``teams × starting slots``) and reads the level of
the best player left over per position group; ``add_vor`` subtracts it.

Position granularity is the allocation **guard/big** grouping (roster POSITION strings) —
platform eligibility (ESPN's multi-slot rules) is parked *here* (critique §9.7). BENCH/IR
slots are excluded from the fill: replacement is the streaming level, i.e. the best player a
team could pick up *after* every starting slot in the league is filled.

Points-league honesty (the spec's own caveat): with one scoring dimension and 3 UTIL slots,
VOR is close to a monotone transform of fpts/g — if it barely reorders the board, the sanity
report says so and the column ships informational.

.. note:: **The caveat above was measured and it holds (2026-07-16).** Step 19's draft room
   re-computed replacement *live* — real ESPN ``eligibleSlots`` instead of guard/big, and the
   actual remaining pool and slot demand after every pick — on the bet that VOR would stop
   being a restatement of fpts/g. It did not: ``spearman(live_vor, fpts_pg)`` ≈ **0.99 through
   ~110 of 130 picks**, diverging only in the endgame (0.94 by pick 125). Cause: **201 of 353
   ESPN players are multi-eligible**, so slots rarely bind and per-slot replacement spread is
   only ≈2.3 fpts/g. This module's own prescription therefore stands, for the live column too:
   it **ships informational**. Don't re-litigate it with a fancier replacement model — the
   constraint is the league format (one dimension, 3 UTIL), not the estimator. Detail:
   implementation-plan Step 19.3; eligibility itself is unparked in ``draft/ids.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..config import CONFIG_DIR

# Slot name -> allocation position group (0 = guard, 1 = big, None = any).
SLOT_GROUPS: dict[str, int | None] = {
    "PG": 0, "SG": 0, "G": 0,
    "SF": 1, "PF": 1, "F": 1, "C": 1,
    "UTIL": None,
}
NON_STARTING = {"BENCH", "IR"}

GROUP_NAMES = {0: "guard", 1: "big", None: "any"}


def load_league(path: str | Path | None = None) -> dict:
    """Parse ``config/league.yaml`` into a plain dict."""
    path = Path(path) if path else CONFIG_DIR / "league.yaml"
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _slot_counts(league: dict) -> dict[int | None, int]:
    """Starting slots per position group for one team: {0: n_guard, 1: n_big, None: n_any}."""
    counts: dict[int | None, int] = {0: 0, 1: 0, None: 0}
    for slot, n in league["roster"].items():
        key = slot.upper()
        if key in NON_STARTING:
            continue
        if key not in SLOT_GROUPS:
            raise ValueError(f"league.yaml roster slot {slot!r} has no position-group mapping.")
        counts[SLOT_GROUPS[key]] += int(n)
    return counts


def replacement_level(
    board: pd.DataFrame,
    pos_of: pd.Series,
    league: dict,
) -> dict[str, float]:
    """Per-group replacement fpts/g after a greedy league-wide fill of the starting slots.

    ``board`` needs ``PLAYER_ID, rank, fpts_pg``; ``pos_of`` maps PLAYER_ID → group (0/1;
    missing = unknown, fills UTIL only). Greedy = walk the board in rank order, put each
    player into his group's open slot, else an open UTIL, else leave him on the wire.
    Replacement per group = the best fpts/g left on the wire for that group (``any`` = best
    remaining overall — the level an unknown-position player is measured against).
    """
    teams = int(league["teams"])
    open_slots = {g: n * teams for g, n in _slot_counts(league).items()}

    b = board.sort_values("rank")
    remaining_best: dict[str, float] = {}
    for r in b.itertuples(index=False):
        g = pos_of.get(r.PLAYER_ID)
        g = None if pd.isna(g) else int(g)
        if g is not None and open_slots.get(g, 0) > 0:
            open_slots[g] -= 1
        elif open_slots[None] > 0:
            open_slots[None] -= 1
        else:
            name = GROUP_NAMES.get(g, "any")
            remaining_best.setdefault(name, float(r.fpts_pg))
            remaining_best.setdefault("any", float(r.fpts_pg))
    # A group can be exhausted on the wire (tiny synthetic boards): fall back to overall.
    overall = remaining_best.get("any", float(b["fpts_pg"].iloc[-1]))
    return {
        "guard": remaining_best.get("guard", overall),
        "big": remaining_best.get("big", overall),
        "any": overall,
    }


def add_vor(board: pd.DataFrame, pos_of: pd.Series, league: dict) -> pd.DataFrame:
    """Adds ``pos_group`` (guard/big/unknown), ``vor`` (fpts/g above the group's replacement)
    and ``vor_rank``. Original row order is preserved; ``vor_rank`` is dense over the board."""
    repl = replacement_level(board, pos_of, league)
    out = board.copy()
    g = out["PLAYER_ID"].map(pos_of)
    out["pos_group"] = np.where(g.isna(), "unknown", np.where(g == 0, "guard", "big"))
    level = out["pos_group"].map({"guard": repl["guard"], "big": repl["big"],
                                  "unknown": repl["any"]})
    out["vor"] = (out["fpts_pg"] - level).round(2)
    out["vor_rank"] = out["vor"].rank(ascending=False, method="first").astype(int)
    return out
