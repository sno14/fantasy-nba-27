"""Where draft picks come from (implementation-plan Step 19.1).

The ESPN live-draft feed is the one genuinely unverified piece of the draft room, so it is
isolated behind a narrow protocol: everything downstream consumes ``list[Pick]`` and neither
knows nor cares whether a human typed it or ESPN served it.

    ManualFeed    picks entered by hand — the shipped default and the draft-night fallback
    EspnPollFeed  the real ESPN league (credentials verified 2026-07-15)
    FixtureFeed   recorded payloads — how the tests run, no network

**Verified against league 507458037 on 2026-07-15** (do not "correct" these back):

* Host is ``lm-api-reads.fantasy.espn.com``. The old ``fantasy.espn.com/apis/v3/...`` is dead
  and fails in the worst way — **HTTP 200 with the SPA's HTML** — so a bare ``status_code ==
  200`` check passes and the parse then explodes. :func:`_get_json` asserts the content-type.
* ``season`` is the season's *ending* year (2026-27 -> 2027).
* **ESPN pre-allocates placeholder picks.** An undrafted season returns a full 130-pick array
  (10 teams x 13 rounds) whose entries carry ``playerId = -1``. Diffing on ``len(picks)``
  concludes the draft is complete before it starts. :func:`parse_picks` filters ``playerId >
  0``; draft state comes from the ``drafted`` / ``inProgress`` flags, never the pick count.
* **``teamId`` is not a contiguous 1..N index** — the team making overall pick 1 of the 10-team
  2025 draft has ``teamId = 15``. Never derive draft order from ``league["teams"]``; read it
  off the observed picks (see :mod:`.live`).

Auth: ``espn_s2`` + ``SWID`` come from the environment or the gitignored ``.env`` at the repo
root — never from ``config/`` (committed). They authenticate as the user: never log them,
and :func:`scrub_payload` strips them before a payload is recorded as a fixture.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import ROOT

ESPN_HOST = "lm-api-reads.fantasy.espn.com"  # VERIFIED 2026-07-15; see module docstring
ESPN_DEAD_HOST = "fantasy.espn.com"  # returns HTTP 200 + HTML — never use for the API
REQUEST_TIMEOUT = 30

#: ESPN's placeholder pick marker. An undrafted league returns a *full* pick array of these.
EMPTY_PLAYER_ID = -1

#: ESPN lineup-slot ids -> names. 0-4 are the true positions; the rest are composite/bench
#: slots. Verified 2026-07-15 (Edwards [SG, SF], Harden [PG, SG], Giannis [PF, C], Jokic [C]).
#:
#: Slot 12 is deliberately ``BENCH``, not ESPN's own ``BE``: this table is the translation
#: boundary, and ``config/league.yaml`` + ``models.value.NON_STARTING`` already say ``BENCH``.
#: Emitting ``BE`` would make ESPN's live settings blow up as a drop-in replacement for the
#: YAML (`ValueError: roster slot 'BE' has no position-group mapping`) — exactly the swap
#: LeagueSettings exists to enable. Translate once, here.
SLOT_NAMES: dict[int, str] = {
    0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C",
    5: "G", 6: "F", 7: "SG/SF", 8: "G/F", 9: "PF/C", 10: "F/C", 11: "UTIL",
    12: "BENCH", 13: "IR",
}
#: The subset that is a real position claim — what slot_feasibility matches against.
POSITION_SLOTS = (0, 1, 2, 3, 4)


class EspnApiError(RuntimeError):
    """ESPN returned something that isn't the JSON we asked for.

    Raised loudly and by name because the common failure is *silent*: the dead host answers
    HTTP 200 with HTML, so anything that trusts the status code alone gets a parse error far
    from the real cause.
    """


@dataclass(frozen=True)
class Pick:
    """One made pick. Placeholder rows (``playerId = -1``) never become a ``Pick``."""

    overall: int
    team_id: int
    espn_player_id: int
    round_id: int = 0
    round_pick: int = 0
    keeper: bool = False


@dataclass(frozen=True)
class LeagueSettings:
    """League structure **as ESPN currently reports it** — read live, never cached.

    Every field here is mutable right up to draft night (user, 2026-07-15: "the league id and
    draft order and teams likely will change as new people are joining"), so this is the
    authority and ``config/league.yaml`` is the fallback. Verified 2026-07-15 against league
    507458037: ``lineupSlotCounts`` matched ``league.yaml`` exactly, and ``size`` matched
    ``teams: 10``.

    ``pick_order`` is the trap: ESPN pre-populates it with **sorted team ids** as a
    placeholder and randomizes it shortly before the draft. Season 2027 currently reads
    ``[1, 3, 8, 9, 10, 11, 12, 13, 14, 15]`` (sorted = not yet drawn) while the played 2025
    season reads ``[15, 11, 13, 14, 8, 9, 1, 12, 3, 10]`` (drawn). :meth:`order_is_placeholder`
    is the honest test — never trust a cached order.
    """

    size: int
    pick_order: list[int]
    slot_counts: dict[str, int]      # ESPN slot NAME -> count, e.g. {"PG": 1, ..., "UTIL": 3}
    draft_type: str                  # "SNAKE" | "AUCTION" | ...
    draft_date: int | None           # epoch ms; None = not yet scheduled
    seconds_per_pick: int            # verified 60 — the real interactivity budget for 19.6

    @property
    def order_is_placeholder(self) -> bool:
        """True when ``pick_order`` is still ESPN's sorted default (order not yet drawn).

        A false negative is possible — a randomized draw *could* come out sorted (1 in 10! for
        10 teams) — so this is a warning, not a gate.
        """
        return self.pick_order == sorted(self.pick_order)

    @property
    def is_scheduled(self) -> bool:
        return self.draft_date is not None


@dataclass(frozen=True)
class DraftStatus:
    """League-level draft state. ``drafted``/``in_progress`` are the real signals — the pick
    count is not (see the placeholder trap in the module docstring)."""

    drafted: bool
    in_progress: bool
    n_picks_total: int  # includes placeholders — diagnostic only, never a completion test


class DraftFeed(Protocol):
    """Everything downstream depends on this and nothing more."""

    def poll(self) -> list[Pick]:
        """All picks made so far, in overall order. Idempotent: polling twice yields the same
        list, so callers diff rather than accumulate."""
        ...

    def status(self) -> DraftStatus: ...


# --------------------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------------------

def load_espn_auth(env_path: Path | None = None) -> dict[str, str]:
    """``{espn_s2, SWID}`` from the environment, falling back to the gitignored ``.env``.

    Never logs or returns anything else. Raises if either is missing — a partial cookie pair
    produces a 401 that reads like "the league is gone", which wastes a lot of time.
    """
    env = {k: v for k in ("ESPN_S2", "ESPN_SWID") if (v := os.environ.get(k))}
    path = env_path or ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip().upper(), v.strip().strip("'\""))
    missing = [k for k in ("ESPN_S2", "ESPN_SWID") if not env.get(k)]
    if missing:
        raise EspnApiError(
            f"Missing {', '.join(missing)}. Put them in {path} (gitignored) or the environment "
            f"— browser F12 > Application > Cookies > fantasy.espn.com. Never in config/."
        )
    return {"espn_s2": env["ESPN_S2"], "SWID": env["ESPN_SWID"]}


def scrub_payload(payload: dict | list) -> dict | list:
    """Payload with any cookie-ish keys removed — call before writing a test fixture."""
    banned = {"espn_s2", "swid", "cookie", "set-cookie", "authorization"}

    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items() if k.lower() not in banned}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    return walk(payload)


# --------------------------------------------------------------------------------------
# Payload parsing (pure — the fixture tests run entirely through these)
# --------------------------------------------------------------------------------------

def parse_picks(payload: dict | list) -> list[Pick]:
    """``mDraftDetail`` payload -> the picks actually made, in overall order.

    **Filters ESPN's placeholder rows** (``playerId = -1``): an undrafted league returns a
    full pre-allocated array of them, so an unfiltered read reports a completed draft before
    the draft starts. Verified 2026-07-15: seasons 2026/2027 return 130 picks, 0 real.
    """
    detail = _draft_detail(payload)
    picks = []
    for p in detail.get("picks") or []:
        pid = int(p.get("playerId", EMPTY_PLAYER_ID))
        if pid <= 0:  # placeholder — not a pick
            continue
        picks.append(Pick(
            overall=int(p.get("overallPickNumber", 0)),
            team_id=int(p.get("teamId", 0)),
            espn_player_id=pid,
            round_id=int(p.get("roundId", 0)),
            round_pick=int(p.get("roundPickNumber", 0)),
            keeper=bool(p.get("keeper", False)),
        ))
    return sorted(picks, key=lambda x: x.overall)


def parse_status(payload: dict | list) -> DraftStatus:
    d = _draft_detail(payload)
    return DraftStatus(
        drafted=bool(d.get("drafted", False)),
        in_progress=bool(d.get("inProgress", False)),
        n_picks_total=len(d.get("picks") or []),
    )


def parse_settings(payload: dict | list) -> LeagueSettings:
    """``mSettings`` payload -> :class:`LeagueSettings`.

    ``lineupSlotCounts`` is keyed by ESPN's numeric slot id **as a string** ({"0": 1, ...});
    it is translated to names here so callers never juggle raw ids.
    """
    d = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(d, dict):
        raise EspnApiError(f"Unexpected mSettings payload type: {type(payload).__name__}")
    s = d.get("settings") or {}
    ds = s.get("draftSettings") or {}
    raw_slots = (s.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    slots = {SLOT_NAMES[int(k)]: int(v) for k, v in raw_slots.items()
             if int(v) > 0 and int(k) in SLOT_NAMES}
    return LeagueSettings(
        size=int(s.get("size", 0)),
        pick_order=[int(t) for t in (ds.get("pickOrder") or [])],
        slot_counts=slots,
        draft_type=str(ds.get("type", "")),
        draft_date=ds.get("date"),
        seconds_per_pick=int(ds.get("timePerSelection", 0) or 0),
    )


def parse_rosters(payload: dict | list) -> dict[int, list[int]]:
    """``mRoster`` payload -> ``{team_id: [espn_player_id]}`` for every team (V3b).

    **Empty on an undrafted season** (verified 2026-07-15: ``mRoster`` carries no roster
    entries until players are actually on teams) — the caller then keeps the draft-session
    picks as the ownership source. Post-draft this is the truth the picks miss: it moves with
    every in-season add/drop, which is the whole point of V3b.

    Robust to two shapes ESPN uses: ``playerId`` on the entry, or the id nested under
    ``playerPoolEntry.player.id``; both are read. Placeholder rows (``id <= 0``) are dropped,
    the same discipline as :func:`parse_picks`. ``teamId`` is **not** a contiguous 1..N index
    (module docstring) — team ids come straight off ``teams[].id``, never a range.
    """
    d = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(d, dict):
        raise EspnApiError(f"Unexpected mRoster payload type: {type(payload).__name__}")
    out: dict[int, list[int]] = {}
    for t in d.get("teams") or []:
        if "id" not in t:
            continue
        ids: list[int] = []
        for e in ((t.get("roster") or {}).get("entries")) or []:
            pid = int(e.get("playerId", 0) or 0)
            if pid <= 0:  # fall back to the nested player id ESPN sometimes uses
                pid = int(((e.get("playerPoolEntry") or {}).get("player") or {}).get("id", 0) or 0)
            if pid > 0:
                ids.append(pid)
        out[int(t["id"])] = ids
    return out


def _draft_detail(payload: dict | list) -> dict:
    d = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(d, dict):
        raise EspnApiError(f"Unexpected mDraftDetail payload type: {type(payload).__name__}")
    return d.get("draftDetail") or {}


# --------------------------------------------------------------------------------------
# Implementations
# --------------------------------------------------------------------------------------

class ManualFeed:
    """Picks entered by hand. The shipped default and the draft-night fallback.

    Not a consolation prize: it makes the whole room testable without a live draft, and it is
    what takes the pick instantly if the ESPN poller stalls when it matters.
    """

    def __init__(self) -> None:
        self._picks: list[Pick] = []

    def add(self, team_id: int, espn_player_id: int, keeper: bool = False) -> Pick:
        """Append the next overall pick. Returns it so the caller can echo what it recorded."""
        pick = Pick(overall=len(self._picks) + 1, team_id=int(team_id),
                    espn_player_id=int(espn_player_id), keeper=keeper)
        self._picks.append(pick)
        return pick

    def undo(self) -> Pick | None:
        """Drop the last pick (misclicks happen and the draft does not pause)."""
        return self._picks.pop() if self._picks else None

    def poll(self) -> list[Pick]:
        return list(self._picks)

    def status(self) -> DraftStatus:
        return DraftStatus(drafted=False, in_progress=bool(self._picks),
                           n_picks_total=len(self._picks))


class FixtureFeed:
    """Replays a recorded ``mDraftDetail`` payload. No network — how the tests run.

    ``reveal`` caps how many picks ``poll`` returns, so a recorded draft can be stepped
    through to simulate one arriving live.
    """

    def __init__(self, payload: dict | list, reveal: int | None = None) -> None:
        self._all = parse_picks(payload)
        self._status = parse_status(payload)
        self.reveal = reveal

    def poll(self) -> list[Pick]:
        return self._all if self.reveal is None else self._all[: self.reveal]

    def status(self) -> DraftStatus:
        return self._status

    @classmethod
    def from_file(cls, path: str | Path, reveal: int | None = None) -> FixtureFeed:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), reveal=reveal)


class EspnPollFeed:
    """Polls the real ESPN league. Credentials + endpoint verified 2026-07-15.

    **Still unverified — the load-bearing unknown:** whether ``mDraftDetail`` refreshes fast
    enough *during* a live draft. ESPN's draft room uses its own real-time channel; the
    ``inProgress`` flag existing proves nothing about latency. Only an October mock draft
    answers it, so ``ManualFeed`` stays the shipped default until then.
    """

    def __init__(self, league_id: str | int, season: int,
                 cookies: dict[str, str] | None = None) -> None:
        self.league_id = str(league_id)
        self.season = int(season)  # the season's ENDING year: 2026-27 -> 2027
        self._cookies = cookies or load_espn_auth()

    @property
    def base_url(self) -> str:
        return (f"https://{ESPN_HOST}/apis/v3/games/fba/seasons/{self.season}"
                f"/segments/0/leagues/{self.league_id}")

    def _draft_payload(self) -> dict | list:
        return _get_json(self.base_url, {"view": "mDraftDetail"}, self._cookies)

    def poll(self) -> list[Pick]:
        return parse_picks(self._draft_payload())

    def status(self) -> DraftStatus:
        return parse_status(self._draft_payload())

    def league_settings(self) -> LeagueSettings:
        """Live league structure from ``mSettings``. Prefer this over ``config/league.yaml``:
        size, roster slots and pick order are all mutable until draft night."""
        return parse_settings(_get_json(self.base_url, {"view": "mSettings"}, self._cookies))

    def team_ids(self) -> list[int]:
        """Every team id in the league, from ``mTeam``.

        Needed **before** the draft: team ids are non-contiguous and are otherwise only
        learned as teams pick, which makes league-wide slot demand wrong exactly when the
        board matters most (see ``live.DraftState.team_ids``).
        """
        payload = _get_json(self.base_url, {"view": "mTeam"}, self._cookies)
        d = payload[0] if isinstance(payload, list) and payload else payload
        return sorted(int(t["id"]) for t in (d.get("teams") or []) if "id" in t)

    def player_universe(self, limit: int = 400) -> list[dict]:
        """Raw ESPN player rows (name + ``eligibleSlots`` + id) for :mod:`.ids`.

        Uses ``kona_player_info`` with an ``X-Fantasy-Filter`` header — **not** ``mRoster``,
        which is empty on an undrafted season (verified 2026-07-15).
        """
        flt = {"players": {"limit": int(limit),
                           "sortPercOwned": {"sortAsc": False, "sortPriority": 1}}}
        payload = _get_json(self.base_url, {"view": "kona_player_info"}, self._cookies,
                            extra_headers={"X-Fantasy-Filter": json.dumps(flt)})
        d = payload[0] if isinstance(payload, list) and payload else payload
        return [e["player"] for e in (d.get("players") or []) if e.get("player")]

    def league_rosters(self) -> dict[int, list[int]]:
        """Live in-season rosters from ``mRoster`` -> ``{team_id: [espn_player_id]}`` (V3b).

        The ownership source once the season starts: as managers add/drop, this diverges
        from the draft-day picks and becomes the truth for the Waivers / My Team / Matchup
        views (docs/ui-views-plan.md §V3b). **Empty on an undrafted season** (``mRoster`` has
        no entries yet, verified 2026-07-15) — the API keeps the pick-based ownership until
        real rosters exist. The espn ids are mapped to our ``PLAYER_ID`` by the caller via the
        cached player map (:mod:`.ids`), exactly like a pick's ``espn_player_id``.
        """
        return parse_rosters(_get_json(self.base_url, {"view": "mRoster"}, self._cookies))


def _get_json(url: str, params: dict, cookies: dict,
              extra_headers: dict | None = None) -> dict | list:
    """GET + parse, refusing to trust a bare HTTP 200.

    The dead host answers 200 with HTML, so content-type is the only honest success test.
    """
    import requests  # local import: the pure parsers above stay importable without it

    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", **(extra_headers or {})}
    r = requests.get(url, params=params, headers=headers, cookies=cookies,
                     timeout=REQUEST_TIMEOUT)
    ctype = r.headers.get("content-type", "")
    if not ctype.startswith("application/json"):
        raise EspnApiError(
            f"Expected JSON from {url}, got content-type {ctype!r} (HTTP {r.status_code}). "
            f"If the host is {ESPN_DEAD_HOST!r} this is the known dead-endpoint trap — it "
            f"answers 200 with SPA HTML. Use {ESPN_HOST!r}."
        )
    if r.status_code == 401:
        raise EspnApiError(
            "ESPN says 401 (not authorized). ESPN session cookies expire — re-harvest "
            "espn_s2 + SWID from the browser before concluding the league is gone."
        )
    if r.status_code != 200:
        raise EspnApiError(f"HTTP {r.status_code} from {url}: {r.text[:200]}")
    return r.json()
