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
import json
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import yaml
from fastapi import APIRouter, HTTPException, Query

from ..config import CONFIG_DIR, PROCESSED_DIR, RAW_DIR
from ..models.analyst import name_key
from ..lineups import calculate_week
from ..streaming import evaluate_move, prepare_drop, quick_move_score, scenario_days
from . import boards

router = APIRouter(prefix="/api")

ROS_DIR = PROCESSED_DIR / "ros_board"
MARKET_DIR = RAW_DIR / "market"
LEAGUE_PATH = CONFIG_DIR / "league.yaml"

TREND_WINDOWS = (7, 14, 30)
SPARK_MAX_SNAPSHOTS = 30   # sparkline depth: the trailing month of nightly boards
TREND_TOP = 250            # players carried into the trend/trade payloads
TRADE_TOP = 200


@router.get("/today/context")
def today_context(target: str = Query(default=None)) -> dict:
    """Source dates for the daily home. Never infer a league day without its timezone."""
    from .draft import current_rosters

    target = target or boards.CURRENT_TARGET
    own = current_rosters()
    league = (yaml.safe_load(LEAGUE_PATH.read_text(encoding="utf-8"))
              if LEAGUE_PATH.exists() else {}) or {}
    zone_name = league.get("timezone")
    league_date = None
    if isinstance(zone_name, str) and zone_name:
        try:
            league_date = datetime.now(ZoneInfo(zone_name)).date().isoformat()
        except ZoneInfoNotFoundError:
            zone_name = None
    else:
        zone_name = None
    dates = ros_dates()
    schedule_path = RAW_DIR / f"schedule_{target}.parquet"
    schedule_asof = (datetime.fromtimestamp(schedule_path.stat().st_mtime, timezone.utc).isoformat()
                     if schedule_path.exists() else None)
    roster_age_hours = None
    roster_freshness = "draft_only" if own["roster_source"] != "espn_live" else "stale_snapshot"
    if own["roster_source"] == "espn_live" and own["rosters_asof"]:
        try:
            pulled = datetime.fromisoformat(own["rosters_asof"].replace("Z", "+00:00"))
            if pulled.tzinfo is not None:
                age = (datetime.now(timezone.utc) - pulled).total_seconds() / 3600
                if age >= -0.1:
                    roster_age_hours = max(0, round(age, 1))
                    roster_freshness = "fresh_snapshot" if age <= 24 else "stale_snapshot"
        except ValueError:
            pass
    return {
        "league_date": league_date, "league_timezone": zone_name,
        "board": {"source": "ros_snapshot" if dates else "preseason_live_model",
                  "asof": dates[-1] if dates else None},
        "rosters": {"source": own["roster_source"], "asof": own["rosters_asof"],
                    "freshness": roster_freshness, "age_hours": roster_age_hours},
        "schedule": {"source": "local_schedule_file" if schedule_asof else "missing",
                     "asof": schedule_asof},
        "status": {"source": "ros_snapshot" if dates else "unavailable",
                   "asof": dates[-1] if dates else None},
        "note": "Schedule as-of is the local file modification time; ROS date is a snapshot date, not a live status check.",
    }


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


def _change_metadata(date: str) -> dict | None:
    path = ROS_DIR / f"{date}.meta.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(data, dict) or data.get("schema") != 1 or data.get("rankedBy") != "ROS safe season value"
            or not re.fullmatch(r"[0-9a-f]{16}", data.get("scoringKey", ""))
            or not re.fullmatch(r"\d{4}-\d{2}", data.get("season", ""))):
        return None
    return data


@router.get("/changes/versions")
def change_versions() -> dict:
    """Only snapshots with recorded scoring/ranking provenance are comparable."""
    dates = ros_dates()
    versions = []
    for date in dates:
        info = _change_metadata(date)
        if info and info["season"] == boards.CURRENT_TARGET:
            versions.append({"version": date, "asof": date, "season": info["season"],
                             "rankedBy": info["rankedBy"], "scoringKey": info["scoringKey"],
                             "source": "local"})
    return {"schema": 1, "versions": versions, "legacyCount": len(dates) - len(versions)}


@router.get("/changes/version/{date}")
def change_version(date: str) -> dict:
    if date not in ros_dates():
        raise HTTPException(404, "No ROS snapshot for that date")
    info = _change_metadata(date)
    if not info or info["season"] != boards.CURRENT_TARGET:
        raise HTTPException(404, "This snapshot has no verified comparison provenance")
    frame = load_ros(date)
    required = {"PLAYER_ID", "PLAYER_NAME", "rank", "fpts_pg"}
    if not required <= set(frame.columns):
        raise HTTPException(503, "ROS snapshot lacks required comparison fields")
    columns = [column for column in ("PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "rank",
                                      "fpts_pg", "mpg", "analyst_action", "analyst_date")
               if column in frame.columns]
    rows = json.loads(frame[columns].to_json(orient="records", date_format="iso"))
    for row in rows:
        for key in ("TEAM_ABBREVIATION", "mpg", "analyst_action", "analyst_date"):
            row.setdefault(key, None)
    return {"schema": 1, "version": date, "asof": date, "season": info["season"],
            "rankedBy": info["rankedBy"], "scoringKey": info["scoringKey"],
            "source": "local", "rows": rows}


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
        "roster_source": own["roster_source"], "rosters_asof": own["rosters_asof"],
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
        "roster_source": own["roster_source"], "rosters_asof": own["rosters_asof"],
        "my_team_id": own["my_team_id"], "has_schedule": has_schedule,
        **({k: meta[k] for k in ("week", "week_name", "start", "end", "days")} if meta
           else {"week": week}),
        "rows": rows,
    }


# ------------------------------------------------------------- my team + matchup (V4/V5)
# Starting slots come from the configured league; legal daily starts are calculated
# by the exact assignment helper shared by My Team, Matchup and future scenarios.


def _board_lookup() -> dict[int, dict]:
    """Current draft board keyed by PLAYER_ID — the range/risk/chronic columns the ROS
    snapshots don't carry."""
    if not boards.data_ready():
        return {}
    b = boards.ranked_board(boards.CURRENT_TARGET, "learned", "safe", True)
    cols = [c for c in ("PLAYER_NAME", "TEAM_ABBREVIATION", "rank", "fpts_pg", "fpts_total", "fpts_p10",
                        "fpts_median", "fpts_p90", "risk", "inj_chronic_flag") if c in b.columns]
    return {int(r["PLAYER_ID"]): {c: (None if pd.isna(r[c]) else r[c]) for c in cols}
            for _, r in b[["PLAYER_ID"] + cols].iterrows()}


def _roster_week_rows(pids: list[int], week: int | None, target: str,
                      board_lookup: dict[int, dict] | None = None) -> tuple[list[dict], dict]:
    """Per-player weekly rows for one roster + the week meta — the shared V4/V5 core.
    ROS snapshot numbers when they exist (rank/FP-G/status/redist), board ranges/risk
    always, availability-aware week games (`games_while_active`)."""
    dates = ros_dates()
    ros = {}
    if dates:
        snap = _ros_cached(dates[-1])
        ros = {int(r.PLAYER_ID): r for r in snap.itertuples(index=False)}
    board = board_lookup if board_lookup is not None else _board_lookup()
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
            "fpts_total": (_f(getattr(s, "fpts_total", None)) if s is not None
                           else _f(b.get("fpts_total"))),
            "projection_source": "ros" if s is not None else "preseason" if b else "missing",
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
            "unknown_game_dates": bool(meta and not team and not status.startswith("out_for_season")),
            "weekly_fpts": round((fpg or 0.0) * len(games), 1),
        })
    return rows, meta


def _day_grid(lineup: dict) -> list[dict]:
    """Compatibility grid backed by eligible assignments rather than a count cap."""
    return [{"day": d["day"], "games": d["games"], "benched": d["benched_games"],
             "starts": len(d["assignments"])} for d in lineup["days"]]


@router.get("/myteam")
def myteam(week: int | None = Query(default=None),
           target: str = Query(default=None)) -> dict:
    """V4 — roster state and exact daily feasible starts for the chosen week."""
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
    lineup = calculate_week(rows, own["positions"], own["starting_slots"], days)
    return {
        "has_team": True, "my_team_id": own["my_team_id"],
        "roster_source": own["roster_source"], "rosters_asof": own["rosters_asof"],
        "has_positions": own["has_positions"],
        "positions": {str(p): own["positions"].get(p, []) for p in mine},
        "unfilled": own["unfilled"].get(own["my_team_id"], {}),
        "has_schedule": bool(meta),
        **({k: meta[k] for k in ("week", "week_name", "start", "end", "days")} if meta
           else {"week": week}),
        "weekly_total": lineup["raw_points"],
        "lineup": lineup,
        "day_grid": _day_grid(lineup),
        "n_out": sum(1 for r in rows if r["status_override"]),
        "daily_slots": sum(own["starting_slots"].values()),
        "starting_slots": own["starting_slots"], "slot_source": own["slot_source"],
        "rows": rows,
    }


@router.get("/matchup")
def matchup(week: int | None = Query(default=None),
            opp: int | None = Query(default=None),
            target: str = Query(default=None)) -> dict:
    """V5 — compare feasible daily starts and raw weekly volume, descriptively.

    No win probability: SD_PG is not a weekly sigma (implementation-plan 19.4).
    """
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
    my_lineup = calculate_week(my_rows, own["positions"], own["starting_slots"], days)
    opp_lineup = calculate_week(opp_rows, own["positions"], own["starting_slots"], days)
    my_total = my_lineup["raw_points"]
    opp_total = opp_lineup["raw_points"]
    return {
        "has_matchup": True, "my_team_id": me, "opp_team_id": opp, "opponents": others,
        "roster_source": own["roster_source"], "rosters_asof": own["rosters_asof"],
        "has_schedule": bool(meta),
        **({k: meta[k] for k in ("week", "week_name", "start", "end", "days")} if meta
           else {"week": week}),
        "daily_slots": sum(own["starting_slots"].values()),
        "starting_slots": own["starting_slots"], "slot_source": own["slot_source"],
        "me": {"team_id": me, "total": my_total, "rows": my_rows,
               "lineup": my_lineup, "day_grid": _day_grid(my_lineup)},
        "opp": {"team_id": opp, "total": opp_total, "rows": opp_rows,
                "lineup": opp_lineup, "day_grid": _day_grid(opp_lineup)},
        "gap": (round(my_lineup["raw_points"] - opp_lineup["raw_points"], 1)
                if my_lineup["raw_points"] is not None and opp_lineup["raw_points"] is not None
                else None),
        "usable_gap": (round(my_lineup["usable_points"] - opp_lineup["usable_points"], 1)
                       if my_lineup["exact"] and opp_lineup["exact"] else None),
    }


def _id_list(value: str) -> list[int]:
    if not value:
        return []
    try:
        result = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise HTTPException(422, "Player IDs must be comma-separated integers") from exc
    if len(result) != len(set(result)) or len(result) > 30:
        raise HTTPException(422, "Player IDs must be unique, with at most 30 selections")
    return result


@router.get("/streaming")
def streaming(
    week: int | None = Query(default=None), start: str | None = Query(default=None),
    end: str | None = Query(default=None), effective_date: str | None = Query(default=None),
    lock_rule: str = Query(default="before_games"), drops: str = Query(default=""),
    keep: str = Query(default=""), acquisitions_used: int | None = Query(default=None),
    acquisition_limit: int | None = Query(default=None),
    rules_confirmed: bool = Query(default=False), pickup_id: int | None = Query(default=None),
    target: str = Query(default=None),
) -> dict:
    """One assumed add/drop, ranked by incremental *feasible* FP over a date range.

    No ESPN transaction is sent. Acquisition, waiver, lock, timezone and IR rules
    are not in the saved draft settings; the chosen effective date is conditional.
    """
    from datetime import date, datetime, timezone
    from .draft import current_rosters, player_positions

    target = target or boards.CURRENT_TARGET
    own = current_rosters()
    projection_dates = ros_dates()
    mine = own["rosters"].get(own["my_team_id"], [])
    if not mine:
        return {"has_team": False, "note": "Set My Team and load its roster in the Draft Room first."}
    if week is None:
        week = default_week(_week_ends(target), projection_dates[-1] if projection_dates else None)
    roster_rows, meta = _roster_week_rows(mine, week, target)
    positions = player_positions() | own["positions"]
    rostered = {int(pid) for pids in own["rosters"].values() for pid in pids}
    ownership_age_hours = None
    if own["roster_source"] == "espn_live" and own["rosters_asof"]:
        try:
            pulled = datetime.fromisoformat(own["rosters_asof"].replace("Z", "+00:00"))
            if pulled.tzinfo is not None:
                ownership_age_hours = max(0, round((datetime.now(timezone.utc) - pulled).total_seconds() / 3600, 1))
        except ValueError:
            pass
    ownership_status = ("fresh_snapshot" if ownership_age_hours is not None and ownership_age_hours <= 24
                        else "stale_snapshot" if own["roster_source"] == "espn_live"
                        else "draft_only")
    picked_drops, kept = _id_list(drops), _id_list(keep)
    if any(pid not in mine for pid in picked_drops + kept):
        raise HTTPException(422, "Drop and keep choices must belong to My Team")
    if set(picked_drops) & set(kept):
        raise HTTPException(422, "A kept player cannot also be a drop candidate")
    if lock_rule not in {"before_games", "after_games"}:
        raise HTTPException(422, "lock_rule must be before_games or after_games")
    if acquisitions_used is not None and acquisitions_used < 0:
        raise HTTPException(422, "acquisitions_used must be non-negative")
    if acquisition_limit is not None and acquisition_limit < 0:
        raise HTTPException(422, "acquisition_limit must be non-negative")
    budget_status = ("unknown" if acquisitions_used is None or acquisition_limit is None else
                     "blocked" if acquisitions_used >= acquisition_limit else "under_assumed_limit")
    rules = {
        "source": "user_assumption" if rules_confirmed else "unverified",
        "unverified": ["acquisition limit", "waiver processing", "daily/weekly locks",
                       "league timezone", "IR transaction treatment"],
        "budget_status": budget_status, "acquisitions_used": acquisitions_used,
        "acquisition_limit": acquisition_limit,
        "note": "Effective date and lock timing are scenario assumptions, not verified ESPN transaction rules.",
    }
    base = {
        "has_team": True, "has_schedule": bool(meta), "my_team_id": own["my_team_id"],
        "projection_source": "ros" if projection_dates else "preseason",
        "projection_asof": projection_dates[-1] if projection_dates else None,
        "roster_source": own["roster_source"], "rosters_asof": own["rosters_asof"],
        "ownership_status": ownership_status, "ownership_age_hours": ownership_age_hours,
        "rules": rules, "roster": roster_rows, "selected_drops": picked_drops,
        "keep": kept, "starting_slots": own["starting_slots"],
        "week": week, "candidate_choices": [], "results": [], "evaluated_count": 0,
    }
    if not meta:
        return {**base, "note": "No cached schedule for this week; run the scheduled local schedule update before comparing moves."}
    start, end = start or meta["start"], end or meta["end"]
    effective_date = effective_date or start
    try:
        for value in (start, end, effective_date):
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError(value)
    except ValueError as exc:
        raise HTTPException(422, "Dates must be valid YYYY-MM-DD values") from exc
    if start < meta["start"] or end > meta["end"] or start > end:
        raise HTTPException(422, "Date range must be within the selected week")
    if not start <= effective_date <= end:
        raise HTTPException(422, "Effective date must be within the selected range")
    days = scenario_days(meta["days"], start, end)
    before = calculate_week(roster_rows, positions, own["starting_slots"], days)
    base.update({"week_name": meta["week_name"], "start": start, "end": end,
                 "days": days, "effective_date": effective_date, "lock_rule": lock_rule,
                 "before": before})
    if not days:
        return {**base, "note": "No NBA games fall in the selected date range."}
    if budget_status == "blocked":
        return {**base, "note": "Acquisition count meets or exceeds the assumed limit; no move is available."}
    if projection_dates:
        ids = [int(pid) for pid in _ros_cached(projection_dates[-1])["PLAYER_ID"].tolist()]
    else:
        ids = list(_board_lookup())
    candidate_ids = [pid for pid in dict.fromkeys(ids) if pid not in rostered]
    candidates, _ = _roster_week_rows(candidate_ids, week, target)
    base["candidate_choices"] = [
        {"player_id": row["PLAYER_ID"], "name": row["PLAYER_NAME"],
         "team": row["TEAM_ABBREVIATION"], "fpts_pg": row["fpts_pg"],
         "status": row["status_override"]} for row in candidates]
    if not picked_drops:
        return {**base, "note": "Select one or more players you would consider dropping."}
    if pickup_id is not None:
        if pickup_id in rostered:
            raise HTTPException(422, "Selected pickup is already rostered")
        if pickup_id not in candidate_ids:
            raise HTTPException(404, "Selected pickup is absent from the current board")
        candidates = [row for row in candidates if row["PLAYER_ID"] == pickup_id]
    # A player with no games in the selected range cannot add production. Keep
    # injured/no-game candidates only for a direct lookup, where the zero is useful.
    if pickup_id is None:
        candidates = [row for row in candidates if any(day in days for day in row["games"])
                      or row.get("unknown_game_dates")]
    scored = []
    by_drop = {row["PLAYER_ID"]: row for row in roster_rows}
    for drop_id in picked_drops:
        prepared = prepare_drop(roster_rows, drop_id, positions, own["starting_slots"],
                                days, effective_date, lock_rule)
        for candidate in candidates:
            usable_delta, raw_delta = quick_move_score(
                prepared, before, by_drop[drop_id], candidate, positions,
                days, effective_date, lock_rule)
            scored.append({"drop_id": drop_id, "candidate": candidate,
                           "usable_delta": usable_delta, "raw_delta": raw_delta})
    scored.sort(key=lambda row: (row["usable_delta"] is None,
                                 -(row["usable_delta"] if row["usable_delta"] is not None else -1e9),
                                 -(row["raw_delta"] if row["raw_delta"] is not None else -1e9),
                                 row["candidate"]["PLAYER_NAME"], row["drop_id"]))
    results = []
    for item in scored[:50]:
        drop_id, candidate = item["drop_id"], item["candidate"]
        move = evaluate_move(roster_rows, candidate, drop_id, positions,
                             own["starting_slots"], days, effective_date, lock_rule, before)
        if move["usable_delta"] != item["usable_delta"] or move["raw_delta"] != item["raw_delta"]:
            raise RuntimeError("Streaming quick score disagrees with exact lineup result")
        results.append({
                **move, "pickup_name": candidate["PLAYER_NAME"],
                "drop_name": by_drop[drop_id]["PLAYER_NAME"],
                "pickup_team": candidate["TEAM_ABBREVIATION"],
                "pickup_fpts_pg": candidate["fpts_pg"],
                "pickup_status": candidate["status_override"],
                "pickup_positions": positions.get(candidate["PLAYER_ID"], []),
                "ownership_status": ownership_status,
            })
    return {**base, "results": results, "evaluated_count": len(scored),
            "unknown_count": sum(row["usable_delta"] is None for row in scored),
            "truncated": len(scored) > 50,
            "note": "All results are conditional on your effective-date, lock and league-rule assumptions."}


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
