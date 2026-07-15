"""Live draft state + dynamic replacement level (implementation-plan Step 19.3).

``models/value.py`` computes replacement by greedily filling a *hypothetical* league. Live, its
two unknowns collapse: we know exactly who is gone and exactly which slots each team still
needs, so replacement becomes the level of the best player you could actually still get for a
slot you actually still need.

**Measured verdict (2026-07-16) — read this before believing the column does much.** The claim
this module was built on ("live VOR turns VOR from a restatement of fpts/g into a decision
input") is **false for most of a draft**. Measured on the real league + the shipped board:

    picks made:            0      40      80     110     125
    spearman(live_vor,
             fpts_pg):  0.995   0.994   0.992   0.991   0.943
    top-20 disagreements:   2       3       1       2       9

So for ~110 of 130 picks live VOR ranks essentially identically to plain fpts/g. It only earns
its keep in the **endgame**, once the pool is drained enough that slots finally bind. This is
exactly ``value.py``'s standing caveat holding — one scoring dimension, 3 UTIL slots — and the
mechanism is multi-eligibility: **201 of 353 ESPN players fill more than one slot**, so a slot
is almost never genuinely scarce (per-slot replacement spread ≈ 2.3 fpts/g). Per that module's
own instruction ("if it barely reorders the board, the sanity report says so and the column
ships informational"), ``live_vor`` ships **informational**.

What the room is actually worth, in order: (1) drafted players leave the board; (2) **slot
feasibility** — what you can no longer fill, which is orthogonal to value and is the honest
form of "do I have too many guards"; (3) live VOR, in the last rounds.

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


def _fills(slot: str, positions: set[str], unconstrained: bool = False) -> bool:
    """Can a player with ``positions`` (PG/SG/SF/PF/C) legally fill ``slot``?

    Uses ESPN's real eligibility rather than value.py's guard/big proxy: G takes PG/SG, F
    takes SF/PF, UTIL takes anyone, and an unknown-position player is UTIL-only (value.py's
    rule — an unknown player shouldn't be assumed to plug a scarce slot).

    ``unconstrained`` is the *no data at all* case: before ESPN has ever been connected we
    know nobody's position, and applying "unknown ⇒ UTIL-only" to the entire league would fill
    just the UTIL slots and leave replacement absurdly high (41.98 fpts/g — no such waiver
    player exists). With zero information the honest fallback is no position constraint, which
    degrades exactly to ``models/value.py``'s classic league-wide fill.
    """
    if unconstrained or slot == "UTIL":
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
        """Team ids we can name. May be *fewer* than the league's size — see
        :meth:`n_teams` / :meth:`total_demand`, which is what replacement must use."""
        if self.team_ids:
            return sorted(self.team_ids)
        return sorted(set(self.rosters) | ({self.my_team_id} if self.my_team_id else set()))

    @property
    def no_positions(self) -> bool:
        """True when we hold no eligibility data for anyone (ESPN never connected, no cached
        map). Distinct from one player being unknown — see :func:`_fills`."""
        return not self.eligible_of

    @property
    def n_teams(self) -> int:
        """The league's **size**. Deliberately not ``len(all_team_ids)``.

        Demand needs a *count*, not ids: before ESPN is connected we know from
        ``league.yaml`` that ten teams are competing even though we cannot yet name one of
        them. Conflating the two is what made replacement degenerate to "best player
        available" (a 56.6 fpts/g "waiver level") on an untouched board.
        """
        return int(self.league.get("teams", 0)) or len(self.all_team_ids)

    def total_demand(self) -> dict[str, int]:
        """League-wide unfilled starting slots, counting teams we cannot yet name.

        Known teams contribute what they still need; each of the ``n_teams - len(named)``
        unknown teams contributes a **full** slate, because an unidentified team drafts just
        as hard as an identified one.
        """
        total: dict[str, int] = {}
        for slots in self.remaining_slots().values():
            for s, n in slots.items():
                total[s] = total.get(s, 0) + n
        unknown = max(self.n_teams - len(self.all_team_ids), 0)
        if unknown:
            for s, n in _starting_slots(self.league).items():
                total[s] = total.get(s, 0) + n * unknown
        return total

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
                    if open_slots[slot] > 0 and _fills(slot, pos, self.no_positions):
                        open_slots[slot] -= 1
                        break
            out[t] = {s: n for s, n in open_slots.items() if n > 0}
        return out


def _slot_priority(slot: str) -> int:
    """Fill specific slots before flexible ones, so a C doesn't burn UTIL while C is open."""
    return {"PG": 0, "SG": 0, "SF": 0, "PF": 0, "C": 0, "G": 1, "F": 1, "UTIL": 2}.get(slot, 3)


def live_replacement(state: DraftState, board: pd.DataFrame) -> dict[str, float]:
    """Replacement fpts/g per slot, from the ACTUAL remaining pool and ACTUAL remaining demand.

    ``board`` needs ``PLAYER_ID``, ``rank``, ``fpts_pg``. Two distinct steps:

    1. **Seat** the undrafted pool in ``rank`` order (our best guess at how the league drafts)
       until league-wide slot demand is exhausted. Each player takes exactly **one** slot — he
       can only occupy one roster spot.
    2. **Level** each slot at the **best remaining fpts/g among the unseated players eligible
       for it** — so a PF/C sets the level for **both** PF and C. He is a genuine alternative
       at either, which is the whole point of multi-eligibility.

    **Why step 2 is a max, not "the next player in rank order"** (bug fixed 2026-07-16, found
    by the user asking how multi-eligibility is handled): taking the *first* unseated player
    in rank order silently assumes rank order == fpts/g order. It isn't — the shipped board
    ranks by the risk-adjusted ``safe`` stance, so the leftovers include high-scoring risky
    players and "first unseated" was not "best available". That made the level incoherent (a
    ``safe`` ordering priced in fpts/g) and stance-dependent: PF read 29.09 / 34.86 / 31.49 on
    identical pools ranked by fpts_pg / safe / median. Replacement is a fact about the wire —
    it must not move when we change our mind about ranking.

    **Consequence worth knowing: multi-eligibility FLATTENS positional scarcity.** When the
    best player left is a PF/C, PF and C have the *same* replacement — one man is the
    alternative at both. With 201 of 353 ESPN players multi-eligible, per-slot levels sit
    close together, which is ``models/value.py``'s standing caveat (in a one-dimension points
    league with 3 UTIL slots, VOR ≈ a monotone transform of fpts/g) holding rather than being
    escaped. The live number is still worth computing — it *moves* as the pool drains, which
    the static column cannot — but do not expect dramatic per-slot spreads, and treat any that
    appear as a bug until proven otherwise.

    Returns one level per starting slot plus ``"any"`` (best left overall — what an
    unknown-position player is measured against).

    Demand comes from :meth:`DraftState.total_demand`, which counts unnamed teams — using
    only the teams we can name makes this number meaningless before ESPN is connected.
    """
    demand = state.total_demand()
    pool = board[~board["PLAYER_ID"].isin(state.drafted)].sort_values("rank")
    if not len(pool):
        return {s: 0.0 for s in list(_starting_slots(state.league)) + ["any"]}

    # 1. Seat in draft order.
    unseated: list[tuple[set[str], float]] = []
    for row in pool.itertuples(index=False):
        pos = state.eligible_of.get(int(row.PLAYER_ID), set())
        for slot in sorted(demand, key=_slot_priority):
            if demand[slot] > 0 and _fills(slot, pos, state.no_positions):
                demand[slot] -= 1
                break
        else:
            unseated.append((pos, float(row.fpts_pg)))

    # 2. Level each slot at the BEST remaining eligible player.
    levels: dict[str, float] = {}
    for slot in _starting_slots(state.league):
        cands = [v for pos, v in unseated if _fills(slot, pos, state.no_positions)]
        if cands:
            levels[slot] = max(cands)
    overall = max((v for _, v in unseated), default=float(pool["fpts_pg"].iloc[-1]))
    return {s: levels.get(s, overall) for s in _starting_slots(state.league)} | {"any": overall}


def live_board(state: DraftState, board: pd.DataFrame) -> pd.DataFrame:
    """The board minus drafted players, with live VOR and a re-dense rank.

    ``live_vor`` = fpts/g above the **lowest** replacement among the slots the player can fill.
    Lowest, because a multi-eligible player gets deployed where the alternative is *weakest*:
    a PF/C whose PF replacement is 34 and C replacement is 30 is played at C and is worth
    ``fpts_pg - 30``. Taking the max would price him at his easiest-to-fill slot and understate
    him.
    """
    repl = live_replacement(state, board)
    out = board[~board["PLAYER_ID"].isin(state.drafted)].copy()

    def _level(pid: int) -> float:
        pos = state.eligible_of.get(int(pid), set())
        cands = [v for s, v in repl.items()
                 if s != "any" and _fills(s, pos, state.no_positions)]
        return min(cands) if cands else repl["any"]

    out["live_repl"] = out["PLAYER_ID"].map(_level)
    out["live_vor"] = (out["fpts_pg"] - out["live_repl"]).round(2)
    out["live_rank"] = out["live_vor"].rank(ascending=False, method="first").astype(int)
    return out.sort_values("live_rank")
