"""In-season + schedule-derived endpoints — the manager views V1/V2/V6 of
docs/ui-views-plan.md (V3–V5 land here too; that file is the spec and tracker).

Routes (JSON, under /api):
  trends              V1: risers & fallers — the latest nightly ROS snapshot diffed
                      against the snapshot ~window days back, + per-player sparklines.
                      Snapshot-vs-snapshot only; projections are never recomputed here.
  trade-targets       V2: buy-low / sell-high disagreement finder — market consensus gap
                      (pull_market.py archives) × naive-vs-model heat × 14d trend, with
                      ownership chips from the draft-room session. Signals are shown
                      side by side; there is deliberately no opaque composite score.
  schedule-strength   V6: per-NBA-team weekly game counts, back-to-backs, and games in
                      the fantasy playoff weeks (league.yaml `fantasy_playoff_weeks`,
                      flagged as placeholder until `fantasy_playoff_weeks_confirmed`).

Everything degrades honestly: no snapshots / no market pull / no schedule each produce an
explicit `has_*: false` with the command or calendar date that fills it — never fake rows.
"""

from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd
import yaml
from fastapi import APIRouter, HTTPException, Query

from ..config import CONFIG_DIR, PROCESSED_DIR, RAW_DIR
from ..models.analyst import name_key
from . import boards

router = APIRouter(prefix="/api")

ROS_DIR = PROCESSED_DIR / "ros_board"
MARKET_DIR = RAW_DIR / "market"
LEAGUE_PATH = CONFIG_DIR / "league.yaml"

TREND_WINDOWS = (7, 14, 30)
SPARK_MAX_SNAPSHOTS = 30   # sparkline depth: the trailing month of nightly boards
TREND_TOP = 250            # players carried into the trend/trade payloads
TRADE_TOP = 200


# ------------------------------------------------------------------ ros_board archive
def ros_dates() -> list[str]:
    """Sorted snapshot dates in data/processed/ros_board (update_daily.py output)."""
    if not ROS_DIR.exists():
        return []
    return sorted(p.stem for p in ROS_DIR.glob("*.parquet")
                  if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem))


@lru_cache(maxsize=64)
def _ros_cached(date: str) -> pd.DataFrame:
    # Safe to cache by date: the nightly pipeline never overwrites an existing board
    # for a date (README "Nightly in-season run"), so a snapshot is immutable once written.
    return pd.read_parquet(ROS_DIR / f"{date}.parquet")


def load_ros(date: str) -> pd.DataFrame:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not (ROS_DIR / f"{date}.parquet").exists():
        raise HTTPException(404, f"no ROS snapshot for {date}")
    return _ros_cached(date)


def baseline_date(dates: list[str], latest: str, window_days: int) -> str | None:
    """The newest snapshot at least ``window_days`` older than ``latest``; falls back to
    the oldest available snapshot (an honest shorter window beats no answer)."""
    cut = (pd.Timestamp(latest) - pd.Timedelta(days=window_days)).date().isoformat()
    older = [d for d in dates if d <= cut and d != latest]
    if older:
        return older[-1]
    rest = [d for d in dates if d != latest]
    return rest[0] if rest else None


def trend_join(cur: pd.DataFrame, prev: pd.DataFrame) -> pd.DataFrame:
    """Inner-join two snapshots on PLAYER_ID and compute the mover deltas.

    ``rank_delta = prev_rank − rank`` (positive = riser). Players present in only one
    snapshot are dropped — no fabricated zero-deltas for arrivals/departures.
    """
    prev_cols = [c for c in ("PLAYER_ID", "rank", "fpts_pg", "mpg") if c in prev.columns]
    m = cur.merge(prev[prev_cols], on="PLAYER_ID", how="inner", suffixes=("", "_b"))
    m["rank_delta"] = (m["rank_b"] - m["rank"]).astype(int)
    m["fpts_delta"] = (m["fpts_pg"] - m["fpts_pg_b"]).round(1)
    if "mpg" in m.columns and "mpg_b" in m.columns:
        m["mpg_delta"] = (m["mpg"] - m["mpg_b"]).round(1)
    return m


def _spark_series(dates: list[str]) -> dict[int, list[list]]:
    """Per-player trailing [date, fpts_pg, rank] triplets across ``dates``."""
    frames = []
    for d in dates:
        df = _ros_cached(d)
        cols = [c for c in ("PLAYER_ID", "fpts_pg", "rank") if c in df.columns]
        f = df[cols].copy()
        f["date"] = d
        frames.append(f)
    hist = pd.concat(frames, ignore_index=True).sort_values("date")
    out: dict[int, list[list]] = {}
    for pid, g in hist.groupby("PLAYER_ID"):
        out[int(pid)] = [[r.date, round(float(r.fpts_pg), 1), int(r.rank)]
                         for r in g.itertuples(index=False)]
    return out


@router.get("/trends")
def trends(window: int = Query(default=14)) -> dict:
    """V1 — the mover diff between the latest snapshot and one ~window days back."""
    if window not in TREND_WINDOWS:
        raise HTTPException(422, f"window must be one of {TREND_WINDOWS}")
    dates = ros_dates()
    if len(dates) < 2:
        return {"has_history": False, "n_snapshots": len(dates), "window": window,
                "latest": dates[-1] if dates else None, "baseline": None, "rows": [],
                "note": "Trends need ≥2 nightly ROS snapshots — scripts/update_daily.py "
                        "crons from opening night."}
    latest = dates[-1]
    base = baseline_date(dates, latest, window)
    m = trend_join(_ros_cached(latest), _ros_cached(base)).sort_values("rank").head(TREND_TOP)
    spark = _spark_series(dates[-SPARK_MAX_SNAPSHOTS:])
    rows = []
    for r in m.itertuples(index=False):
        pid = int(r.PLAYER_ID)
        rows.append({
            "PLAYER_ID": pid,
            "PLAYER_NAME": r.PLAYER_NAME,
            "TEAM_ABBREVIATION": getattr(r, "TEAM_ABBREVIATION", None),
            "rank": int(r.rank),
            "rank_delta": int(r.rank_delta),
            "fpts_pg": round(float(r.fpts_pg), 1),
            "fpts_delta": round(float(r.fpts_delta), 1),
            "mpg": None if not hasattr(r, "mpg") or pd.isna(r.mpg) else round(float(r.mpg), 1),
            "mpg_delta": None if not hasattr(r, "mpg_delta") or pd.isna(r.mpg_delta)
                         else round(float(r.mpg_delta), 1),
            "status_override": getattr(r, "status_override", "") or "",
            "spark": spark.get(pid, []),
        })
    return {"has_history": True, "n_snapshots": len(dates), "window": window,
            "latest": latest, "baseline": base, "rows": rows}


# ------------------------------------------------------------------ market archive
def latest_market(source: str = "hashtag") -> tuple[str | None, pd.DataFrame]:
    """Newest date-stamped pull from data/raw/market (pull_market.py archive schema:
    consensus_rank, player, team, pos, consensus_value, adp). (None, empty) when no pull."""
    if not MARKET_DIR.exists():
        return None, pd.DataFrame()
    files = sorted(MARKET_DIR.glob(f"{source}_*.parquet"))
    if not files:
        return None, pd.DataFrame()
    date = files[-1].stem.replace(f"{source}_", "")
    return date, pd.read_parquet(files[-1])


def attach_market(cur: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """Left-join the market's consensus_rank via the analyst layer's name normalization
    (models.analyst.name_key — the same family every name join in the repo uses), then
    ``market_gap = consensus_rank − rank`` (positive = we're higher on him than the
    market → buy-low candidate). Unmatched names get null gaps (rookie tails are
    expected preseason misses)."""
    out = cur.copy()
    if market.empty:
        out["consensus_rank"] = pd.NA
        out["market_gap"] = pd.NA
        return out
    mk = market.copy()
    mk["name_key"] = mk["player"].map(name_key)
    mk = mk.drop_duplicates("name_key", keep="first")[["name_key", "consensus_rank"]]
    out["name_key"] = out["PLAYER_NAME"].map(name_key)
    out = out.merge(mk, on="name_key", how="left").drop(columns=["name_key"])
    out["market_gap"] = out["consensus_rank"] - out["rank"]
    return out


@router.get("/trade-targets")
def trade_targets() -> dict:
    """V2 — the per-player disagreement table. mode=ros once nightly snapshots exist,
    else the preseason draft board (market gap only — no naive/trend columns yet)."""
    dates = ros_dates()
    if dates:
        cur, mode = _ros_cached(dates[-1]).copy(), "ros"
    else:
        if not boards.data_ready():
            raise HTTPException(503, "No data cached yet — pull data or run dev_fixtures.py.")
        cur, mode = boards.ranked_board(boards.CURRENT_TARGET, "learned", "safe", True), "preseason"

    market_date, market = latest_market("hashtag")
    cur = attach_market(cur, market)

    has_naive = "naive_rank" in cur.columns
    if has_naive:
        # positive = the naive recency-chaser ranks him better than the model = hot streak
        # the model discounts (sell-high signal); negative = cold streak it looks through.
        cur["heat_gap"] = cur["rank"] - cur["naive_rank"]

    trend_by_pid: dict[int, float] = {}
    if len(dates) >= 2:
        tj = trend_join(_ros_cached(dates[-1]), _ros_cached(baseline_date(dates, dates[-1], 14)))
        trend_by_pid = {int(r.PLAYER_ID): float(r.fpts_delta) for r in tj.itertuples(index=False)}

    from .draft import current_rosters  # session-backed; imported late to keep startup light

    own = current_rosters()
    owner_of = {int(pid): int(tid) for tid, pids in own["rosters"].items() for pid in pids}

    cur = cur.sort_values("rank").head(TRADE_TOP)
    rows = []
    for r in cur.itertuples(index=False):
        pid = int(r.PLAYER_ID)
        team_id = owner_of.get(pid)
        rows.append({
            "PLAYER_ID": pid,
            "PLAYER_NAME": r.PLAYER_NAME,
            "TEAM_ABBREVIATION": getattr(r, "TEAM_ABBREVIATION", None),
            "rank": int(r.rank),
            "fpts_pg": round(float(r.fpts_pg), 1),
            "consensus_rank": None if pd.isna(r.consensus_rank) else int(r.consensus_rank),
            "market_gap": None if pd.isna(r.market_gap) else int(r.market_gap),
            "naive_rank": int(r.naive_rank) if has_naive and pd.notna(r.naive_rank) else None,
            "heat_gap": int(r.heat_gap) if has_naive and pd.notna(r.heat_gap) else None,
            "fpts_delta_14": trend_by_pid.get(pid),
            "risk": None if not hasattr(r, "risk") or pd.isna(r.risk) else round(float(r.risk), 2),
            "status_override": getattr(r, "status_override", "") or "",
            "rostered_by": team_id,
            "is_mine": team_id == own["my_team_id"] if team_id is not None else False,
        })
    return {
        "mode": mode,
        "market_date": market_date, "has_market": not market.empty,
        "has_naive": has_naive, "has_trend": bool(trend_by_pid),
        "ownership": bool(owner_of), "my_team_id": own["my_team_id"],
        "rows": rows,
    }


# ------------------------------------------------------------------ waiver wire (V3)
def week_games_by_team(target: str, week: int) -> tuple[dict, dict[str, list[str]]]:
    """One NBA week's (meta, {team: [game dates]}) — the shared join behind V3/V4/V5.
    ``({}, {})`` when no schedule is cached or the week isn't in it."""
    long = boards.team_week_games(target)
    if long.empty:
        return {}, {}
    wk = long[long["week"] == week]
    if wk.empty:
        return {}, {}
    days = sorted(pd.to_datetime(wk["game_date"]).dt.strftime("%Y-%m-%d").unique().tolist())
    by_team = {str(t): sorted(pd.to_datetime(g["game_date"]).dt.strftime("%Y-%m-%d").tolist())
               for t, g in wk.groupby("team")}
    meta = {"week": int(week), "week_name": str(wk["week_name"].iloc[0]),
            "start": days[0], "end": days[-1], "days": days}
    return meta, by_team


_OUT_UNTIL = re.compile(r"^out_until:(\d{4}-\d{2}-\d{2})")


def games_while_active(games: list[str], status_override: str) -> list[str]:
    """Drop week game-dates a flagged-out player will miss (the Step-12 override notes:
    ``out_for_season`` / ``out_until:YYYY-MM-DD`` — the return date's game counts). An
    OUT player's streaming value that week is the games he's actually back for."""
    s = status_override or ""
    if s.startswith("out_for_season"):
        return []
    m = _OUT_UNTIL.match(s)
    if m:
        return [g for g in games if g >= m.group(1)]
    return games


def default_week(week_ends: list[tuple[int, str]], asof: str | None) -> int | None:
    """The week a manager cares about *now*: the first whose last game date is >= the
    as-of date (the latest snapshot), else the final week; the first week preseason."""
    if not week_ends:
        return None
    ordered = sorted(week_ends)
    if asof is None:
        return ordered[0][0]
    for wk, end in ordered:
        if end >= asof:
            return wk
    return ordered[-1][0]


def _week_ends(target: str) -> list[tuple[int, str]]:
    long = boards.team_week_games(target)
    if long.empty:
        return []
    ends = long.groupby("week")["game_date"].max()
    return [(int(w), pd.Timestamp(e).date().isoformat()) for w, e in ends.items()]


@router.get("/waivers")
def waivers(week: int | None = Query(default=None),
            target: str = Query(default=None)) -> dict:
    """V3 — the pickup list: the current pool minus rostered players, ranked by
    ROS FP/G × games in the chosen week, with the opportunity columns attached
    (EXP-030 redist_mpg, breakout_p, 14d trend, status)."""
    target = target or boards.CURRENT_TARGET
    dates = ros_dates()
    if dates:
        cur, mode = _ros_cached(dates[-1]).copy(), "ros"
        asof = dates[-1]
    else:
        if not boards.data_ready():
            raise HTTPException(503, "No data cached yet — pull data or run dev_fixtures.py.")
        cur, mode = boards.ranked_board(boards.CURRENT_TARGET, "learned", "safe", True).copy(), "preseason"
        asof = None

    from .draft import current_rosters  # session-backed

    own = current_rosters()
    rostered = {pid for pids in own["rosters"].values() for pid in pids}
    if rostered:
        cur = cur[~cur["PLAYER_ID"].isin(rostered)]

    sheet_path = PROCESSED_DIR / f"draft_sheet_{target}.parquet"
    breakout: dict[int, float] = {}
    if sheet_path.exists():
        sheet = pd.read_parquet(sheet_path)
        if "breakout_p" in sheet.columns:
            breakout = {int(r.PLAYER_ID): float(r.breakout_p)
                        for r in sheet[["PLAYER_ID", "breakout_p"]].dropna().itertuples(index=False)}

    if week is None:
        week = default_week(_week_ends(target), asof)
    meta, by_team = week_games_by_team(target, week) if week is not None else ({}, {})
    has_schedule = bool(meta)

    trend_by_pid: dict[int, float] = {}
    if len(dates) >= 2:
        tj = trend_join(_ros_cached(dates[-1]), _ros_cached(baseline_date(dates, dates[-1], 14)))
        trend_by_pid = {int(r.PLAYER_ID): float(r.fpts_delta) for r in tj.itertuples(index=False)}

    cur = cur.sort_values("rank").head(TRADE_TOP)
    rows = []
    for r in cur.itertuples(index=False):
        pid = int(r.PLAYER_ID)
        team = getattr(r, "TEAM_ABBREVIATION", None)
        team = str(team) if team is not None and pd.notna(team) else None
        status = getattr(r, "status_override", "") or ""
        games = by_team.get(team, []) if (has_schedule and team) else []
        games = games_while_active(games, status)
        fpg = round(float(r.fpts_pg), 1)
        rows.append({
            "PLAYER_ID": pid,
            "PLAYER_NAME": r.PLAYER_NAME,
            "TEAM_ABBREVIATION": team,
            "rank": int(r.rank),
            "fpts_pg": fpg,
            "games": games,
            "n_games": len(games),
            "weekly_fpts": round(fpg * len(games), 1),
            "redist_mpg": round(float(r.redist_mpg), 1)
                          if hasattr(r, "redist_mpg") and pd.notna(r.redist_mpg) else None,
            "breakout_p": breakout.get(pid),
            "fpts_delta_14": trend_by_pid.get(pid),
            "status_override": status,
        })
    rows.sort(key=lambda x: (x["weekly_fpts"] if has_schedule else -x["rank"]), reverse=True)
    return {
        "mode": mode, "ownership": bool(rostered), "n_rostered": len(rostered),
        "my_team_id": own["my_team_id"], "has_schedule": has_schedule,
        **({k: meta[k] for k in ("week", "week_name", "start", "end", "days")} if meta
           else {"week": week}),
        "rows": rows,
    }


# ------------------------------------------------------------- my team + matchup (V4/V5)
# ESPN default startable slots per day (PG/SG/SF/PF/C/G/F + 3×UTIL) — mirrors the
# Weekly view's DAILY_SLOTS. Purely descriptive: more of your players playing on one
# night than this means games you cannot start.
DAILY_SLOTS = 10


def _board_lookup() -> dict[int, dict]:
    """Current draft board keyed by PLAYER_ID — the range/risk/chronic columns the ROS
    snapshots don't carry."""
    if not boards.data_ready():
        return {}
    b = boards.ranked_board(boards.CURRENT_TARGET, "learned", "safe", True)
    cols = [c for c in ("PLAYER_NAME", "TEAM_ABBREVIATION", "rank", "fpts_pg", "fpts_p10",
                        "fpts_median", "fpts_p90", "risk", "inj_chronic_flag") if c in b.columns]
    return {int(r["PLAYER_ID"]): {c: r[c] for c in cols} for _, r in b[["PLAYER_ID"] + cols].iterrows()}


def _roster_week_rows(pids: list[int], week: int | None, target: str) -> tuple[list[dict], dict]:
    """Per-player weekly rows for one roster + the week meta — the shared V4/V5 core.
    ROS snapshot numbers when they exist (rank/FP-G/status/redist), board ranges/risk
    always, availability-aware week games (`games_while_active`)."""
    dates = ros_dates()
    ros = {}
    if dates:
        snap = _ros_cached(dates[-1])
        ros = {int(r.PLAYER_ID): r for r in snap.itertuples(index=False)}
    board = _board_lookup()
    meta, by_team = week_games_by_team(target, week) if week is not None else ({}, {})

    trend_by_pid: dict[int, float] = {}
    spark: dict[int, list[list]] = {}
    if len(dates) >= 2:
        tj = trend_join(_ros_cached(dates[-1]), _ros_cached(baseline_date(dates, dates[-1], 14)))
        trend_by_pid = {int(r.PLAYER_ID): float(r.fpts_delta) for r in tj.itertuples(index=False)}
        spark = _spark_series(dates[-SPARK_MAX_SNAPSHOTS:])

    def _f(v) -> float | None:
        return None if v is None or pd.isna(v) else round(float(v), 1)

    rows = []
    for pid in pids:
        s, b = ros.get(pid), board.get(pid, {})
        name = getattr(s, "PLAYER_NAME", None) or b.get("PLAYER_NAME") or f"#{pid}"
        team = getattr(s, "TEAM_ABBREVIATION", None) or b.get("TEAM_ABBREVIATION")
        team = str(team) if team is not None and pd.notna(team) else None
        status = (getattr(s, "status_override", "") or "") if s is not None else ""
        fpg = _f(getattr(s, "fpts_pg", None)) if s is not None else _f(b.get("fpts_pg"))
        games = games_while_active(by_team.get(team, []) if (meta and team) else [], status)
        rows.append({
            "PLAYER_ID": pid, "PLAYER_NAME": str(name), "TEAM_ABBREVIATION": team,
            "rank": int(s.rank) if s is not None else
                    (int(b["rank"]) if b.get("rank") is not None else None),
            "fpts_pg": fpg,
            "fpts_p10": _f(b.get("fpts_p10")), "fpts_median": _f(b.get("fpts_median")),
            "fpts_p90": _f(b.get("fpts_p90")),
            "risk": None if b.get("risk") is None or pd.isna(b.get("risk"))
                    else round(float(b["risk"]), 2),
            "chronic": int(b["inj_chronic_flag"]) if b.get("inj_chronic_flag") is not None
                       and pd.notna(b.get("inj_chronic_flag")) else 0,
            "status_override": status,
            "redist_mpg": _f(getattr(s, "redist_mpg", None)) if s is not None else None,
            "fpts_delta_14": trend_by_pid.get(pid),
            "spark": spark.get(pid, []),
            "games": games, "n_games": len(games),
            "weekly_fpts": round((fpg or 0.0) * len(games), 1),
        })
    return rows, meta


def _day_grid(rows: list[dict], days: list[str]) -> list[dict]:
    """Per-day game counts for a roster vs the startable-slot cap. Descriptive."""
    out = []
    for d in days:
        n = sum(1 for r in rows if d in r["games"])
        out.append({"day": d, "games": n, "benched": max(0, n - DAILY_SLOTS)})
    return out


@router.get("/myteam")
def myteam(week: int | None = Query(default=None),
           target: str = Query(default=None)) -> dict:
    """V4 — my roster's dashboard: per-player ROS state + trend + this week's volume,
    and the team block (weekly total, day grid vs startable slots, OUT count, unfilled
    starting slots from the draft room's slot logic)."""
    target = target or boards.CURRENT_TARGET
    from .draft import current_rosters

    own = current_rosters()
    mine = own["rosters"].get(own["my_team_id"], [])
    if not mine:
        return {"has_team": False, "my_team_id": own["my_team_id"],
                "note": ("Teams have rosters but none is marked as yours — set \"my team\" "
                         "in the Draft Room (it defaults to unset)."
                         if own["rosters"] else
                         "No roster yet — draft in the Room (or Simulate a mock draft) "
                         "and your picks become the team this page tracks.")}

    if week is None:
        dates = ros_dates()
        week = default_week(_week_ends(target), dates[-1] if dates else None)
    rows, meta = _roster_week_rows(mine, week, target)
    rows.sort(key=lambda r: (r["fpts_pg"] is None, -(r["fpts_pg"] or 0)))
    days = meta.get("days", [])
    return {
        "has_team": True, "my_team_id": own["my_team_id"],
        "has_positions": own["has_positions"],
        "positions": {str(p): own["positions"].get(p, []) for p in mine},
        "unfilled": own["unfilled"].get(own["my_team_id"], {}),
        "has_schedule": bool(meta),
        **({k: meta[k] for k in ("week", "week_name", "start", "end", "days")} if meta
           else {"week": week}),
        "weekly_total": round(sum(r["weekly_fpts"] for r in rows), 1),
        "day_grid": _day_grid(rows, days),
        "n_out": sum(1 for r in rows if r["status_override"]),
        "daily_slots": DAILY_SLOTS,
        "rows": rows,
    }


@router.get("/matchup")
def matchup(week: int | None = Query(default=None),
            opp: int | None = Query(default=None),
            target: str = Query(default=None)) -> dict:
    """V5 — my week vs an opponent's, descriptively: FP/G × games totals and the
    day-by-day volume grid. **No win probability, no simulation** — the H2H variance
    layer was descoped (implementation-plan 19.4) and SD_PG must never become a weekly
    sigma; this view states game counts and lets the human judge."""
    target = target or boards.CURRENT_TARGET
    from .draft import current_rosters

    own = current_rosters()
    me = own["my_team_id"]
    mine = own["rosters"].get(me, [])
    others = sorted(t for t in own["rosters"] if t != me and own["rosters"][t])
    if not mine or not others:
        return {"has_matchup": False, "my_team_id": me,
                "note": ("Teams have rosters but none is marked as yours — set \"my team\" "
                         "in the Draft Room first."
                         if own["rosters"] and not mine else
                         "A matchup needs my roster and at least one opponent — draft in "
                         "the Room or Simulate a mock draft.")}
    if opp is None or opp not in others:
        opp = others[0]

    if week is None:
        dates = ros_dates()
        week = default_week(_week_ends(target), dates[-1] if dates else None)
    my_rows, meta = _roster_week_rows(mine, week, target)
    opp_rows, _ = _roster_week_rows(own["rosters"][opp], week, target)
    for side in (my_rows, opp_rows):
        side.sort(key=lambda r: -r["weekly_fpts"])
    days = meta.get("days", [])
    my_total = round(sum(r["weekly_fpts"] for r in my_rows), 1)
    opp_total = round(sum(r["weekly_fpts"] for r in opp_rows), 1)
    return {
        "has_matchup": True, "my_team_id": me, "opp_team_id": opp, "opponents": others,
        "has_schedule": bool(meta),
        **({k: meta[k] for k in ("week", "week_name", "start", "end", "days")} if meta
           else {"week": week}),
        "daily_slots": DAILY_SLOTS,
        "me": {"team_id": me, "total": my_total, "rows": my_rows,
               "day_grid": _day_grid(my_rows, days)},
        "opp": {"team_id": opp, "total": opp_total, "rows": opp_rows,
                "day_grid": _day_grid(opp_rows, days)},
        "gap": round(my_total - opp_total, 1),
    }


# ------------------------------------------------------------------ schedule strength
def b2b_count(dates: pd.Series) -> int:
    """Back-to-backs: pairs of consecutive calendar days with a game."""
    ds = pd.to_datetime(pd.Series(sorted(dates.unique())))
    if len(ds) < 2:
        return 0
    return int((ds.diff().dt.days == 1).sum())


@router.get("/schedule-strength")
def schedule_strength(target: str = Query(default=None)) -> dict:
    """V6 — team × week game-count matrix + B2Bs + fantasy-playoff-week games."""
    target = target or boards.CURRENT_TARGET
    long = boards.team_week_games(target)
    league = (yaml.safe_load(LEAGUE_PATH.read_text(encoding="utf-8"))
              if LEAGUE_PATH.exists() else {}) or {}
    playoff_weeks = [int(w) for w in (league.get("fantasy_playoff_weeks") or [])]
    confirmed = bool(league.get("fantasy_playoff_weeks_confirmed", False))
    if long.empty:
        return {"has_schedule": False, "target": target, "playoff_weeks": playoff_weeks,
                "playoff_weeks_confirmed": confirmed, "weeks": [], "teams": [],
                "note": "No schedule cached — run `python scripts/pull_schedule.py` "
                        "(the 2026-27 schedule publishes ~mid-August)."}

    weeks_meta = []
    for wk, g in long.groupby("week"):
        days = sorted(pd.to_datetime(g["game_date"]).dt.strftime("%Y-%m-%d").unique().tolist())
        weeks_meta.append({"week": int(wk), "week_name": str(g["week_name"].iloc[0]),
                           "start": days[0], "end": days[-1]})
    weeks_meta.sort(key=lambda w: w["week"])
    sched_weeks = {w["week"] for w in weeks_meta}

    teams = []
    for team, g in long.groupby("team"):
        by_week = {int(w): int(len(x)) for w, x in g.groupby("week")}
        teams.append({
            "team": str(team),
            "total_games": int(len(g)),
            "b2b": b2b_count(g["game_date"]),
            "playoff_games": int(sum(by_week.get(w, 0) for w in playoff_weeks if w in sched_weeks)),
            "by_week": by_week,
        })
    teams.sort(key=lambda t: (-t["playoff_games"], t["team"]))
    return {"has_schedule": True, "target": target, "playoff_weeks": playoff_weeks,
            "playoff_weeks_confirmed": confirmed, "weeks": weeks_meta, "teams": teams}
