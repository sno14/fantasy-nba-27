"""Live draft state + dynamic replacement level (implementation-plan Step 19.3).

Removing drafted players and re-ranking is trivial. The part that earns its keep is
**replacement level recomputed after every pick**.

``models/value.py`` computes replacement by greedily filling a *hypothetical* league, and its
own docstring concedes the consequence: in a one-dimension points league with 3 UTIL slots,
VOR ends up "close to a monotone transform of fpts/g" — as a static column it barely reorders
anything. Live, both of that model's unknowns collapse. We know exactly who is gone and
exactly which slots each team still needs, so replacement stops being a league-wide average
and becomes *the level of the best player you could actually still get for the slot you
actually still need*. That is what makes VOR a decision input rather than a restatement.

Design rule: ``DraftState`` is **rebuildable from the pick list alone**. Undo is
``picks.pop()`` + rebuild, never mutation-in-place — on draft night the cheap correct thing
beats the clever thing.

**``teamId`` is not a contiguous 1..N index** (verified 2026-07-15: the team making overall
pick 1 of the 10-team 2025 draft has ``teamId = 15``). So draft order is read off the
observed picks, never derived from ``league["teams"]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..models.value import NON_STARTING, SLOT_GROUPS
from .feed import Pick


def _starting_slots(league: dict) -> dict[str, int]:
    """Per-team starting slots by ESPN slot name, e.g. ``{PG: 1, ..., UTIL: 3}``.

    BENCH/IR are excluded — replacement is the *streaming* level, i.e. what you could roster
    anyway once every starting slot in the league is filled (``value.py``'s convention).
    """
    out: dict[str, int] = {}
    for slot, n in league["roster"].items():
        key = slot.upper()
        if key in NON_STARTING:
            continue
        if key not in SLOT_GROUPS:
            raise ValueError(f"league.yaml roster slot {slot!r} has no position mapping.")
        out[key] = int(n)
    return out


def _fills(slot: str, positions: set[str]) -> bool:
    """Can a player with ``positions`` (PG/SG/SF/PF/C) legally fill ``slot``?

    Uses ESPN's real eligibility rather than value.py's guard/big proxy: G takes PG/SG, F
    takes SF/PF, UTIL takes anyone, and an unknown-position player is UTIL-only.
    """
    if slot == "UTIL":
        return True
    if not positions:
        return False
    if slot == "G":
        return bool(positions & {"PG", "SG"})
    if slot == "F":
        return bool(positions & {"SF", "PF"})
    return slot in positions


@dataclass
class DraftState:
    """The single source of truth the API and every 19.5/19.6 call read.

    Rebuildable from ``picks`` alone — see the module docstring.
    """

    picks: list[Pick] = field(default_factory=list)  # in overall order
    my_team_id: int = 0
    league: dict = field(default_factory=dict)
    eligible_of: dict[int, set[str]] = field(default_factory=dict)  # PLAYER_ID -> positions
    to_nba: dict[int, int] = field(default_factory=dict)            # espn_id -> PLAYER_ID
    #: **Every** team id in the league (``EspnPollFeed.team_ids()``). Load-bearing: team ids
    #: are non-contiguous, so they cannot be synthesized from ``league["teams"]``, and if we
    #: only count teams that have *already picked* then league-wide slot demand is wrong at
    #: exactly the moment the board matters most — pre-draft it would see one team and a
    #: tenth of the real demand, pricing replacement against a pool nobody is competing for.
    team_ids: list[int] = field(default_factory=list)
    #: ESPN's published draft order (``LeagueSettings.pick_order``). Supply it: without it
    #: the order is only recoverable *after* round 1, but survival probability (19.6) is
    #: needed from pick 1 — exactly when it's least knowable. Read it **live** on draft day:
    #: ESPN seeds it with sorted team ids and randomizes shortly before the draft, so a
    #: cached order is worse than none (see ``LeagueSettings.order_is_placeholder``).
    pick_order: list[int] = field(default_factory=list)

    def _nba(self, pick: Pick) -> int | None:
        return self.to_nba.get(pick.espn_player_id, pick.espn_player_id or None)

    @property
    def drafted(self) -> set[int]:
        """PLAYER_IDs already taken by anyone."""
        return {n for p in self.picks if (n := self._nba(p)) is not None}

    @property
    def rosters(self) -> dict[int, list[int]]:
        """team_id -> [PLAYER_ID], in pick order. Every team that has picked appears."""
        out: dict[int, list[int]] = {}
        for p in self.picks:
            n = self._nba(p)
            if n is not None:
                out.setdefault(p.team_id, []).append(n)
        return out

    @property
    def my_roster(self) -> list[int]:
        return self.rosters.get(self.my_team_id, [])

    @property
    def all_team_ids(self) -> list[int]:
        """Every team competing for slots. Falls back to observed ∪ mine when ``team_ids``
        wasn't supplied, but that under-counts demand pre-draft — pass ``team_ids``."""
        if self.team_ids:
            return sorted(self.team_ids)
        return sorted(set(self.rosters) | ({self.my_team_id} if self.my_team_id else set()))

    @property
    def draft_order(self) -> list[int]:
        """Round-1 team order: ESPN's published ``pick_order`` when supplied, else recovered
        from observed round-1 picks. Never assumed from ``league["teams"]`` — team ids are
        non-contiguous.

        The two agree where both exist: verified 2026-07-15 on the played 2025 season, where
        ESPN's ``pickOrder`` and the order recovered from picks were both
        ``[15, 11, 13, 14, 8, 9, 1, 12, 3, 10]``. Observed picks win nothing here — they are
        the fallback, because pre-draft there are none.
        """
        if self.pick_order:
            return list(self.pick_order)
        r1 = sorted((p for p in self.picks if p.round_id == 1), key=lambda p: p.overall)
        seen, order = set(), []
        for p in r1:
            if p.team_id not in seen:
                seen.add(p.team_id)
                order.append(p.team_id)
        return order

    def picks_until_next(self) -> int | None:
        """Picks between now and my next turn, from the observed snake order.

        ``None`` when the order isn't yet observable (round 1 incomplete) or I'm not in it —
        callers must not fabricate a number, since survival probability keys off this.
        """
        order = self.draft_order
        n = len(order)
        if n == 0 or self.my_team_id not in order:
            return None
        made = len(self.picks)
        my_idx = order.index(self.my_team_id)
        for ahead in range(0, 2 * n + 1):
            overall = made + ahead          # 0-based index of that future pick
            rnd, in_rnd = divmod(overall, n)
            seat = in_rnd if rnd % 2 == 0 else n - 1 - in_rnd  # snake
            if seat == my_idx:
                return ahead
        return None

    def remaining_slots(self) -> dict[int, dict[str, int]]:
        """team_id -> unfilled starting slots, after greedily seating each roster.

        Greedy and position-first (a player fills his own position before a composite slot,
        composites before UTIL) — the same spirit as value.py's fill. This is an estimate of
        *demand*, not a claim about anyone's optimal lineup.
        """
        base = _starting_slots(self.league)
        out: dict[int, dict[str, int]] = {}
        for t in self.all_team_ids:
            open_slots = dict(base)
            for pid in self.rosters.get(t, []):
                pos = self.eligible_of.get(pid, set())
                for slot in sorted(open_slots, key=_slot_priority):
                    if open_slots[slot] > 0 and _fills(slot, pos):
                        open_slots[slot] -= 1
                        break
            out[t] = {s: n for s, n in open_slots.items() if n > 0}
        return out


def _slot_priority(slot: str) -> int:
    """Fill specific slots before flexible ones, so a C doesn't burn UTIL while C is open."""
    return {"PG": 0, "SG": 0, "SF": 0, "PF": 0, "C": 0, "G": 1, "F": 1, "UTIL": 2}.get(slot, 3)


def live_replacement(state: DraftState, board: pd.DataFrame) -> dict[str, float]:
    """Replacement fpts/g per slot, from the ACTUAL remaining pool and ACTUAL remaining demand.

    ``board`` needs ``PLAYER_ID``, ``rank``, ``fpts_pg``. Walk the undrafted board in rank
    order, seating each player into the league's still-open slots (summed across all teams);
    once a slot's league-wide demand is exhausted, the next eligible player left on the wire
    *is* that slot's replacement level.

    Returns one level per starting slot plus ``"any"`` (the best player left overall — what an
    unknown-position player is measured against). A slot nobody still needs falls back to
    ``any``: with zero demand, the wire is the alternative.
    """
    demand: dict[str, int] = {}
    for slots in state.remaining_slots().values():
        for s, n in slots.items():
            demand[s] = demand.get(s, 0) + n

    drafted = state.drafted
    pool = board[~board["PLAYER_ID"].isin(drafted)].sort_values("rank")

    levels: dict[str, float] = {}
    for row in pool.itertuples(index=False):
        pos = state.eligible_of.get(int(row.PLAYER_ID), set())
        seated = False
        for slot in sorted(demand, key=_slot_priority):
            if demand[slot] > 0 and _fills(slot, pos):
                demand[slot] -= 1
                seated = True
                break
        if not seated:
            # First player past the league's need for each slot he could fill = replacement.
            for slot in demand:
                if _fills(slot, pos) and slot not in levels:
                    levels[slot] = float(row.fpts_pg)
            levels.setdefault("any", float(row.fpts_pg))

    if not len(pool):
        return {"any": 0.0}
    overall = levels.get("any", float(pool["fpts_pg"].iloc[-1]))
    return {s: levels.get(s, overall) for s in _starting_slots(state.league)} | {"any": overall}


def live_board(state: DraftState, board: pd.DataFrame) -> pd.DataFrame:
    """The board minus drafted players, with live VOR and a re-dense rank.

    ``live_vor`` = fpts/g above the *best* replacement among the slots the player can fill —
    "best" because a multi-eligible player is worth what his scarcest useful slot makes him
    worth, and he can be deployed there.
    """
    repl = live_replacement(state, board)
    out = board[~board["PLAYER_ID"].isin(state.drafted)].copy()

    def _level(pid: int) -> float:
        pos = state.eligible_of.get(int(pid), set())
        cands = [v for s, v in repl.items() if s != "any" and _fills(s, pos)]
        return min(cands) if cands else repl["any"]

    out["live_repl"] = out["PLAYER_ID"].map(_level)
    out["live_vor"] = (out["fpts_pg"] - out["live_repl"]).round(2)
    out["live_rank"] = out["live_vor"].rank(ascending=False, method="first").astype(int)
    return out.sort_values("live_rank")
