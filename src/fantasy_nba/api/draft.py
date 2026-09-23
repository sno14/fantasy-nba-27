"""Draft-room API (implementation-plan Step 19.7).

One in-process session holds the draft: the pick list, who I am, and which feed is supplying
picks. Everything the UI shows is derived from that — the live board, every team's roster, and
the slot/risk composition panels. The human-entered parts persist to
data/processed/draft_session.json (saved on every mutation, loaded at startup), so a server
restart never loses the picks or "my team".

**The source toggle is the point.** ESPN polling is unverified for live-draft latency (only an
October mock draft settles it), so the UI must be able to fall back to manual entry *mid-draft
without losing state*. Hence: picks live in the session, not in the feed. Switching source
re-seeds the new feed from the picks already recorded, so the toggle is safe at any moment —
which is the only way it's worth having on draft night.

**Composition, not prescription.** The panels report what you have (slot feasibility, risk
concentration vs the league) and stop there. There is no "take player X" number: that needs the
H2H week-win simulator, whose variance layer is unbuilt and gated (Step 19.4). Reporting a
recommendation without it would mean inventing one — see the SD_PG note in the step spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from ..config import PROCESSED_DIR, ROOT
from ..draft import build_player_map
from ..draft.feed import EspnApiError, EspnPollFeed, ManualFeed, Pick
from ..draft.ids import PlayerMap
from ..draft.live import (
    DraftState,
    _fills,
    _slot_priority,
    _starting_slots,
    live_board,
    live_replacement,
)
from ..models.value import load_league
from . import boards

router = APIRouter(prefix="/api/draft")

SOURCES = {
    "manual": "Picks entered by hand — always works, no network.",
    "espn": "Polls the live ESPN league. Live-draft latency is UNVERIFIED until an October "
            "mock draft; fall back to manual if it lags.",
}


@dataclass
class Session:
    """The whole draft room's mutable state. Picks are the source of truth — the board, the
    rosters and every panel are derived, and undo is `picks.pop()`."""

    source: str = "manual"
    league_id: str = ""
    season: int = 2027                 # ESPN's season param = the ENDING year (2026-27)
    my_team_id: int = 0
    picks: list[Pick] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)
    pick_order: list[int] = field(default_factory=list)
    settings: dict | None = None
    pmap: PlayerMap | None = None
    espn_error: str | None = None      # surfaced to the UI rather than raised — never block
    # V3b: live in-season ESPN rosters (espn team_id -> [espn_player_id]). When present they
    # replace the pick-derived ownership for the season views, because mid-season adds/drops
    # diverge from draft night. None = use the draft picks (the pre-season / no-refresh state).
    live_rosters: dict[int, list[int]] | None = None
    live_rosters_asof: str | None = None

    def feed(self) -> ManualFeed:
        m = ManualFeed()
        m._picks = list(self.picks)
        return m


_session = Session()
# Load the cached ESPN map at import: without it "manual needs no network" is false — ESPN is
# the only source of slot eligibility, so an uncached room has no positions.
_session.pmap = PlayerMap.load()

# --------------------------------------------------------------------- persistence
# The room's human-entered state (manual picks, my_team_id, the source toggle, the last
# Connect snapshot) persists to the local cache so a server restart doesn't lose the draft
# or make you re-pick "my team" every launch. Everything else re-derives; pmap has its own
# parquet. NOTE on the pick-order rule (README "Draft room"): what's saved here is only as
# fresh as the last Connect — `order_is_placeholder` travels with it, Connect refreshes it,
# and the mid-Oct 19.1b sweep re-reads everything live. This cache does not weaken that
# rule; it just stops a restart from forgetting what the last live read said.
SESSION_PATH = PROCESSED_DIR / "draft_session.json"


def _save_session() -> None:
    s = _session
    try:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(json.dumps({
            "source": s.source, "league_id": s.league_id, "season": s.season,
            "my_team_id": s.my_team_id,
            "picks": [p.__dict__ for p in s.picks],
            "team_ids": s.team_ids, "pick_order": s.pick_order,
            "settings": s.settings,
            "live_rosters": ({str(t): v for t, v in s.live_rosters.items()}
                             if s.live_rosters else None),
            "live_rosters_asof": s.live_rosters_asof,
        }, indent=1), encoding="utf-8")
    except OSError:
        pass  # persistence is a convenience — never take the room down over it


def _load_session() -> None:
    if not SESSION_PATH.exists():
        return
    try:
        d = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        s = _session
        if d.get("source") in SOURCES:
            s.source = d["source"]
        s.league_id = str(d.get("league_id", ""))
        s.season = int(d.get("season", s.season))
        s.my_team_id = int(d.get("my_team_id", 0))
        s.picks = [Pick(**p) for p in d.get("picks", [])]
        s.team_ids = [int(t) for t in d.get("team_ids", [])]
        s.pick_order = [int(t) for t in d.get("pick_order", [])]
        s.settings = d.get("settings")
        lr = d.get("live_rosters")
        s.live_rosters = ({int(t): [int(x) for x in v] for t, v in lr.items()} if lr else None)
        s.live_rosters_asof = d.get("live_rosters_asof")
    except (ValueError, TypeError, KeyError):
        pass  # corrupt/stale cache → start fresh rather than crash at import


_load_session()


def _env(key: str, default: str = "") -> str:
    """Read a non-secret ESPN_* setting (the league id) from .env / environment.

    Cookies are never read here — `EspnPollFeed` loads them itself and they must not pass
    through the API layer, where they could end up in a response or a log.
    """
    import os

    if v := os.environ.get(key):
        return v
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip().upper() == key:
                    return v.strip().strip("'\"")
    return default


def _board() -> pd.DataFrame:
    """The current draft board (analyst layer on), ranked, with PLAYER_ID/rank/fpts_pg."""
    b = boards.ranked_board(boards.CURRENT_TARGET, "learned", "safe", True).copy()
    if "rank" not in b.columns:
        b["rank"] = range(1, len(b) + 1)
    return b


def _synthetic_teams(league: dict) -> list[int]:
    """Stand-in team ids ``1..N`` for a manual draft with no ESPN connection.

    Without these, manual mode cannot attribute a pick to anyone but me: with no ids there is
    no clock, so every pick falls to my roster and the league panel shows one team. ESPN's
    real ids (non-contiguous) always win when present — see ``synthetic_teams`` in /state, and
    reset the room if you connect mid-draft, since the ids won't line up.
    """
    return list(range(1, int(league.get("teams", 10)) + 1))


def _state() -> DraftState:
    s = _session
    league = _league_cfg()
    team_ids = list(s.team_ids) or _synthetic_teams(league)
    return DraftState(
        picks=list(s.picks), my_team_id=s.my_team_id, league=league,
        eligible_of=(s.pmap.eligible_of if s.pmap else {}),
        to_nba=(s.pmap.to_nba if s.pmap else {}),
        team_ids=team_ids,
        # Synthetic order is just the id order — a placeholder snake so the clock advances.
        # ESPN's drawn order replaces it; never present a synthetic order as real.
        pick_order=list(s.pick_order) or team_ids,
    )


def _roster_source() -> str:
    """"espn_live" once a V3b refresh has stored non-empty live rosters, else "draft"."""
    return "espn_live" if (_session.live_rosters and any(_session.live_rosters.values())) else "draft"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _live_state() -> DraftState:
    """A DraftState whose rosters ARE the live ESPN rosters (V3b) — one synthetic pick per
    rostered player, so every roster / positions / unfilled-slot derivation the pick path
    uses is reused unchanged. The espn ids resolve to PLAYER_IDs through the same cached
    player map as a real pick's ``espn_player_id``."""
    s = _session
    league = _league_cfg()
    lr = s.live_rosters or {}
    team_ids = list(s.team_ids) or sorted(lr) or _synthetic_teams(league)
    picks, n = [], 0
    for tid, espn_ids in lr.items():
        for eid in espn_ids:
            n += 1
            picks.append(Pick(overall=n, team_id=int(tid), espn_player_id=int(eid)))
    return DraftState(
        picks=picks, my_team_id=s.my_team_id, league=league,
        eligible_of=(s.pmap.eligible_of if s.pmap else {}),
        to_nba=(s.pmap.to_nba if s.pmap else {}),
        team_ids=team_ids, pick_order=list(s.pick_order) or team_ids,
    )


def _league_cfg() -> dict:
    """ESPN's live settings when we have them, else config/league.yaml.

    ESPN is the authority: size / roster slots drift as members join, and replacement level is
    a direct function of teams x starting slots (Step 19.1b).
    """
    y = load_league()
    s = _session.settings
    if s and s.get("size") and s.get("slot_counts"):
        return {**y, "teams": s["size"], "roster": s["slot_counts"]}
    return y


def _roster_panel(state: DraftState, board: pd.DataFrame) -> list[dict]:
    """Per team: players, unfilled starting slots, and risk composition.

    Descriptive only. `risk` / `fpts_p10` come straight off the board's Monte-Carlo ranges;
    they are NOT combined into a team-level distribution — summing independent per-player
    draws would understate correlation and double-count what SD_PG already absorbs (Step
    19.4's whole point). Counting risky players is honest; simulating a roster is not, yet.
    """
    idx = board.set_index("PLAYER_ID")
    remaining = state.remaining_slots()
    names = _session.pmap.names if _session.pmap else {}
    out = []
    for team_id in state.all_team_ids:
        players = []
        for pid in state.rosters.get(team_id, []):
            row = idx.loc[pid] if pid in idx.index else None
            players.append({
                "player_id": int(pid),
                "name": (row["PLAYER_NAME"] if row is not None and "PLAYER_NAME" in row
                         else names.get(pid, f"#{pid}")),
                "positions": sorted(state.eligible_of.get(pid, [])),
                "fpts_pg": _num(row, "fpts_pg"),
                "risk": _num(row, "risk"),
                "fpts_p10": _num(row, "fpts_p10"),
                "fpts_median": _num(row, "fpts_median"),
                "chronic": int(row["inj_chronic_flag"]) if row is not None
                           and "inj_chronic_flag" in row and pd.notna(row["inj_chronic_flag"]) else 0,
            })
        risks = [p["risk"] for p in players if p["risk"] is not None]
        out.append({
            "team_id": int(team_id),
            "is_me": team_id == state.my_team_id,
            "players": players,
            "unfilled": remaining.get(team_id, {}),
            "n_chronic": sum(p["chronic"] for p in players),
            "mean_risk": round(sum(risks) / len(risks), 3) if risks else None,
            "sum_fpts_pg": round(sum(p["fpts_pg"] or 0 for p in players), 1),
        })
    return out


def current_rosters() -> dict:
    """Ownership for the season views (docs/ui-views-plan.md §A.4): rosters keyed by team id,
    values NBA player ids (DraftState maps ESPN→NBA at ingestion). Two sources, chosen here so
    every season view is consistent:

    * ``roster_source == "espn_live"`` — a **V3b** refresh has pulled live in-season ESPN
      rosters (``mRoster``); these follow adds/drops the draft picks can't, so they win once
      present. ``rosters_asof`` timestamps the pull.
    * ``roster_source == "draft"`` — the draft-session picks (manual / ESPN / Simulate). The
      pre-season default, and the fallback when no live rosters have been pulled.

    Also carries the slot facts the season views reuse rather than reimplement: per-player
    ESPN eligibility and each team's unfilled starting slots (empty maps without the
    Connect-ESPN player map — no positions, no slot math, said honestly)."""
    live = _roster_source() == "espn_live"
    state = _live_state() if live else _state()
    rosters = {int(t): [int(p) for p in pids] for t, pids in state.rosters.items() if pids}
    remaining = state.remaining_slots()
    return {
        "my_team_id": int(state.my_team_id),
        "source": _session.source,
        "roster_source": "espn_live" if live else "draft",
        "rosters_asof": _session.live_rosters_asof if live else None,
        "n_picks": len(_session.picks),
        "rosters": rosters,
        "positions": {int(p): sorted(state.eligible_of.get(p, []))
                      for pids in rosters.values() for p in pids},
        "unfilled": {int(t): remaining.get(t, {}) for t in rosters},
        "has_positions": bool(state.eligible_of),
    }


def _num(row, col: str) -> float | None:
    if row is None or col not in row or pd.isna(row[col]):
        return None
    return round(float(row[col]), 2)


def _seat_best(players: list[dict], starting: dict[str, int], unconstrained: bool) -> float:
    """Sum of the strongest legal starting lineup's FP/G — seat players by descending FP/G,
    each into the most specific open slot they fill. Bench players don't count. With no
    eligibility data every player can fill anything, so this degrades to the top-N by FP/G.

    A greedy heuristic, not a provably optimal assignment; with 3 flexible UTIL slots and heavy
    multi-eligibility it lands on the optimum in the cases that matter (matches value.py's
    seating spirit)."""
    open_slots = dict(starting)
    total = 0.0
    for p in sorted(players, key=lambda x: -(x["fpts_pg"] or 0)):
        pos = p["positions"]
        for slot in sorted(open_slots, key=_slot_priority):
            if open_slots[slot] > 0 and _fills(slot, pos, unconstrained):
                open_slots[slot] -= 1
                total += p["fpts_pg"] or 0
                break
    return total


def _power_rankings(state: DraftState, board: pd.DataFrame) -> list[dict]:
    """Per-team draft-strength aggregates from the drafted rosters. Descriptive, like the rest
    of the room: these sum independent per-player projections — a team-strength index, not a
    win-probability (that needs the gated H2H simulator). Season-total floor/ceiling are summed
    p10/p90 and so ignore cross-player correlation; read them as indicative spread."""
    idx = board.set_index("PLAYER_ID")
    starting = _starting_slots(_league_cfg())
    remaining = state.remaining_slots()
    repl_any = live_replacement(state, board).get("any", 0.0)
    names = _session.pmap.names if _session.pmap else {}

    rows = []
    for team_id in state.all_team_ids:
        players = []
        for pid in state.rosters.get(team_id, []):
            row = idx.loc[pid] if pid in idx.index else None
            players.append({
                "name": (row["PLAYER_NAME"] if row is not None and "PLAYER_NAME" in row
                         else names.get(pid, f"#{pid}")),
                "positions": set(state.eligible_of.get(pid, [])),
                "fpts_pg": _num(row, "fpts_pg"),
                "fpts_total": _num(row, "fpts_total"),
                "fpts_p10": _num(row, "fpts_p10"),
                "fpts_p90": _num(row, "fpts_p90"),
                "risk": _num(row, "risk"),
                "chronic": int(row["inj_chronic_flag"]) if row is not None
                           and "inj_chronic_flag" in row and pd.notna(row["inj_chronic_flag"]) else 0,
            })
        fpg = [p["fpts_pg"] for p in players if p["fpts_pg"] is not None]
        risks = [p["risk"] for p in players if p["risk"] is not None]
        top3 = sorted(fpg, reverse=True)[:3]
        best = max(players, key=lambda p: p["fpts_pg"] or 0.0) if players else None
        unfilled = sum(remaining.get(team_id, {}).values())
        rows.append({
            "team_id": int(team_id),
            "is_me": team_id == state.my_team_id,
            "n_players": len(players),
            "total_fpts_pg": round(sum(fpg), 1),
            "avg_fpts_pg": round(sum(fpg) / len(fpg), 1) if fpg else 0.0,
            "total_fpts_season": round(sum(p["fpts_total"] or 0 for p in players)),
            "starters_fpts_pg": round(_seat_best(players, starting, state.no_positions), 1),
            "star_power": round(sum(top3), 1),          # top-3 FP/G — elite talent concentration
            "best_player": best["name"] if best else None,
            "best_fpts_pg": best["fpts_pg"] if best else None,
            "depth": sum(1 for v in fpg if v >= repl_any),   # starters above replacement level
            "floor_season": round(sum(p["fpts_p10"] or 0 for p in players)),
            "ceiling_season": round(sum(p["fpts_p90"] or 0 for p in players)),
            "mean_risk": round(sum(risks) / len(risks), 3) if risks else None,
            "n_chronic": sum(p["chronic"] for p in players),
            "unfilled_starts": int(unfilled),
        })
    # Power rank = projected season total (bakes in both scoring rate and durability).
    rows.sort(key=lambda r: r["total_fpts_season"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["power_rank"] = i
    return rows


@router.get("/state")
def draft_state(top: int = Query(default=120, le=400)) -> dict:
    """Everything the room renders: config, live board, rosters, composition."""
    if not boards.data_ready():
        raise HTTPException(503, "No data cached — run pull_data.py or dev_fixtures.py.")
    s = _session
    board = _board()
    state = _state()
    lb = live_board(state, board)
    cols = [c for c in ("live_rank", "rank", "tier", "PLAYER_ID", "PLAYER_NAME",
                        "TEAM_ABBREVIATION", "fpts_pg", "live_vor", "live_repl", "fpts_p10",
                        "fpts_median", "fpts_p90", "risk", "adp", "vor", "fpts_pg_change",
                        "analyst_action", "radar_label", "radar_round_gap", "radar_reasons")
            if c in lb.columns]
    rows = json.loads(lb[cols].head(top).to_json(orient="records"))
    for r in rows:
        pid = r.get("PLAYER_ID")
        r["positions"] = sorted(state.eligible_of.get(pid, [])) if pid else []

    return {
        "source": s.source,
        "sources": SOURCES,
        "league_id": s.league_id or _env("ESPN_LEAGUE_ID"),
        "season": s.season,
        "my_team_id": s.my_team_id,
        "team_ids": state.all_team_ids,
        "settings": s.settings,
        "espn_error": s.espn_error,
        "espn_ready": bool(s.pmap) and bool(s.team_ids),
        "has_positions": not state.no_positions,
        # True = team ids are 1..N stand-ins, not ESPN's (which are non-contiguous). The UI
        # must say so: a synthetic clock is a convenience, not the real draft order.
        "synthetic_teams": not s.team_ids,
        "n_picks": len(s.picks),
        "picks": [{"overall": p.overall, "team_id": p.team_id,
                   "player_id": (s.pmap.to_nba.get(p.espn_player_id, p.espn_player_id)
                                 if s.pmap else p.espn_player_id),
                   "espn_player_id": p.espn_player_id} for p in s.picks],
        "picks_until_next": state.picks_until_next(),
        "on_the_clock": _on_the_clock(state),
        "replacement": {k: round(v, 2) for k, v in live_replacement(state, board).items()},
        "rosters": _roster_panel(state, board),
        "board": rows,
    }


@router.get("/power")
def power_rankings() -> dict:
    """League power rankings from the current drafted rosters (the same in-session picks the
    room holds). Empty `teams` with `n_picks == 0` = nobody drafted yet."""
    if not boards.data_ready():
        raise HTTPException(503, "No data cached — run pull_data.py or dev_fixtures.py.")
    s = _session
    state = _state()
    board = _board()
    league = _league_cfg()
    roster_size = sum(int(n) for slot, n in league["roster"].items() if slot.upper() != "IR")
    return {
        "n_picks": len(s.picks),
        "my_team_id": s.my_team_id,
        "n_teams": state.n_teams,
        "roster_size": roster_size,
        "has_positions": not state.no_positions,
        "synthetic_teams": not s.team_ids,
        "starting_slots": _starting_slots(league),
        "teams": _power_rankings(state, board),
    }


@router.post("/simulate")
def simulate(rounds: int = Query(default=0, ge=0, le=30)) -> dict:
    """Auto-complete the draft: fill every team to a full roster by best-available snake,
    keeping any picks already made. A preview convenience so Power Rankings (and the room)
    have data before draft night — undo/reset apply exactly as they do to manual picks."""
    if not boards.data_ready():
        raise HTTPException(503, "No data cached — run pull_data.py or dev_fixtures.py.")
    s = _session
    league = _league_cfg()
    board = _board().sort_values("rank")
    n_teams = _state().n_teams
    if rounds <= 0:
        rounds = sum(int(n) for slot, n in league["roster"].items() if slot.upper() != "IR")
    target = n_teams * rounds
    order = _state().draft_order
    if not order:
        raise HTTPException(422, "No draft order available to simulate — connect ESPN first.")

    added = 0
    while len(s.picks) < target and added <= target:
        state = _state()
        team_id = _on_the_clock(state)
        if team_id is None:
            break
        pool = board[~board["PLAYER_ID"].isin(state.drafted)]
        if pool.empty:
            break
        pid = int(pool.iloc[0]["PLAYER_ID"])
        espn_id = next((e for e, n in (s.pmap.to_nba.items() if s.pmap else []) if n == pid), pid)
        s.picks.append(Pick(overall=len(s.picks) + 1, team_id=team_id, espn_player_id=espn_id,
                            round_id=len(s.picks) // max(n_teams, 1) + 1))
        added += 1
    _save_session()
    return {"n_picks": len(s.picks), "added": added, "rounds": rounds, "n_teams": n_teams}


@router.post("/connect")
def connect(
    league_id: str = Query(default=""),
    season: int = Query(default=2027, ge=2000, le=2100),
    my_team_id: int = Query(default=0, ge=0),
    watch: bool = Query(default=False),
) -> dict:
    """Pull live ESPN settings + teams + the player map. Safe to re-run (it is the 19.1b
    re-verification in one call): league id / teams / slots / pick order all drift."""
    s = _session
    next_league_id = (league_id or _env("ESPN_LEAGUE_ID")).strip()
    if not next_league_id:
        raise HTTPException(422, "No league id — set ESPN_LEAGUE_ID in .env or pass league_id.")
    if not next_league_id.isdigit():
        raise HTTPException(422, "ESPN league id must contain digits only.")
    try:
        feed = EspnPollFeed(league_id=next_league_id, season=season)
        settings = feed.league_settings()
        team_ids = feed.team_ids()
        if my_team_id and my_team_id not in team_ids:
            raise HTTPException(
                422, f"Team {my_team_id} is not in ESPN league {next_league_id}."
            )
        next_settings = {
            "size": settings.size, "slot_counts": settings.slot_counts,
            "pick_order": settings.pick_order, "draft_type": settings.draft_type,
            "draft_date": settings.draft_date, "seconds_per_pick": settings.seconds_per_pick,
            "order_is_placeholder": settings.order_is_placeholder,
            "is_scheduled": settings.is_scheduled,
        }
        pmap = build_player_map(feed.player_universe(), boards.raw("player_season_stats"))
        picks = feed.poll() if watch else None

        # Commit only after every remote read succeeds. A bad mock URL must not leave the
        # session half-switched away from a working draft.
        s.league_id = next_league_id
        s.season = season
        s.team_ids = team_ids
        s.pick_order = settings.pick_order
        s.settings = next_settings
        s.pmap = pmap
        if my_team_id:
            s.my_team_id = my_team_id
        elif s.my_team_id not in team_ids:
            s.my_team_id = 0
        if watch:
            s.source = "espn"
            s.picks = picks or []
        s.pmap.save()          # so manual mode works offline from here on
        s.espn_error = None
        _save_session()
    except EspnApiError as e:
        s.espn_error = str(e)
        raise HTTPException(502, str(e))
    return {"ok": True, "settings": s.settings, "team_ids": s.team_ids,
            "source": s.source, "my_team_id": s.my_team_id, "n_picks": len(s.picks),
            "match_rate": round(s.pmap.match_rate, 3), "n_unmatched": len(s.pmap.unmatched)}


@router.post("/source")
def set_source(source: str = Query(...)) -> dict:
    """Switch feed. **Picks are preserved** — they live in the session, not the feed, so this
    is safe mid-draft. That is the whole reason the toggle exists: if ESPN lags on the night,
    flip to manual and keep going."""
    if source not in SOURCES:
        raise HTTPException(422, f"source must be one of {list(SOURCES)}")
    _session.source = source
    _save_session()
    return {"source": source, "n_picks": len(_session.picks)}


@router.post("/config")
def set_config(my_team_id: int = Query(...)) -> dict:
    """Set which league team is mine. Persisted — pick it once, not every launch (My
    Team / Matchup / the trade view's "mine" chips all key off it)."""
    _session.my_team_id = my_team_id
    _save_session()
    return {"my_team_id": my_team_id}


@router.post("/refresh")
def refresh() -> dict:
    """Poll ESPN for picks. Never raises into the UI — errors surface as `espn_error` so a
    stalled poller can't take the room down mid-draft."""
    s = _session
    if s.source != "espn":
        return {"n_picks": len(s.picks), "skipped": "source is manual"}
    try:
        feed = EspnPollFeed(league_id=s.league_id or _env("ESPN_LEAGUE_ID"), season=s.season)
        picks = feed.poll()
        s.picks = picks           # ESPN is authoritative for its own picks
        s.espn_error = None
        _save_session()
        return {"n_picks": len(picks), "status": feed.status().__dict__}
    except EspnApiError as e:
        s.espn_error = str(e)
        return {"n_picks": len(s.picks), "espn_error": str(e)}


@router.post("/rosters/refresh")
def refresh_rosters() -> dict:
    """V3b — pull live in-season ESPN rosters (``mRoster``) and make them the ownership source
    for every season view (Waivers / My Team / Matchup / Trades). Independent of the pick
    source toggle: rosters can be refreshed whether picks come from ESPN or were typed/simulated.

    Never raises into the UI — a stalled or unauthorized poll surfaces as ``espn_error`` and
    leaves the current ownership untouched. An **empty** roster set (undrafted season, or
    ``mRoster`` not yet populated) does **not** overwrite the pick-based ownership: it reports
    ``n_rostered: 0`` so a pre-season click can't wipe a simulated or hand-entered draft."""
    s = _session
    try:
        feed = EspnPollFeed(league_id=s.league_id or _env("ESPN_LEAGUE_ID"), season=s.season)
        rosters = feed.league_rosters()
        s.espn_error = None
    except EspnApiError as e:
        s.espn_error = str(e)
        return {"espn_error": str(e), "roster_source": _roster_source()}
    total = sum(len(v) for v in rosters.values())
    if total == 0:
        return {"n_rostered": 0, "roster_source": _roster_source(),
                "note": "ESPN rosters are empty (undrafted, or mRoster not yet populated) — "
                        "ownership stays on the draft picks until real rosters exist."}
    s.live_rosters = {int(t): [int(x) for x in v] for t, v in rosters.items()}
    s.live_rosters_asof = _now_iso()
    _save_session()
    to_nba = s.pmap.to_nba if s.pmap else {}
    mapped = sum(1 for v in rosters.values() for e in v if int(e) in to_nba)
    return {"n_rostered": total, "mapped": mapped, "n_teams": len(rosters),
            "rosters_asof": s.live_rosters_asof, "roster_source": "espn_live",
            "has_positions": bool(to_nba),
            "note": None if to_nba else "Connect ESPN once to cache the player map — without "
                    "it these rosters have no PLAYER_ID join and no positions."}


@router.post("/rosters/clear")
def clear_rosters() -> dict:
    """Drop the V3b live rosters and revert every season view to the draft-session picks."""
    _session.live_rosters = None
    _session.live_rosters_asof = None
    _save_session()
    return {"roster_source": "draft"}


@router.post("/pick")
def add_pick(player_id: int = Query(...), team_id: int = Query(default=0)) -> dict:
    """Record a manual pick. `player_id` is our PLAYER_ID; `team_id` defaults to whoever is
    on the clock by the published order."""
    s = _session
    state = _state()
    if not team_id:
        team_id = _on_the_clock(state) or s.my_team_id
    espn_id = next((e for e, n in (s.pmap.to_nba.items() if s.pmap else []) if n == player_id),
                   player_id)
    s.picks.append(Pick(overall=len(s.picks) + 1, team_id=team_id, espn_player_id=espn_id,
                        round_id=len(s.picks) // max(len(state.all_team_ids), 1) + 1))
    _save_session()
    return {"n_picks": len(s.picks), "team_id": team_id, "player_id": player_id}


@router.post("/undo")
def undo() -> dict:
    """Drop the last pick. Misclicks happen and the draft does not pause."""
    p = _session.picks.pop() if _session.picks else None
    _save_session()
    return {"n_picks": len(_session.picks), "undone": p.overall if p else None}


@router.post("/reset")
def reset() -> dict:
    """Clear the picks (my_team_id and the source survive — reset is for redoing a
    draft, not for forgetting who I am)."""
    _session.picks = []
    _save_session()
    return {"n_picks": 0}


def _on_the_clock(state: DraftState) -> int | None:
    """Whose turn it is, by the published snake order. None when the order isn't known —
    never guessed."""
    order = state.draft_order
    if not order:
        return None
    n = len(order)
    rnd, in_rnd = divmod(len(state.picks), n)
    return order[in_rnd if rnd % 2 == 0 else n - 1 - in_rnd]
