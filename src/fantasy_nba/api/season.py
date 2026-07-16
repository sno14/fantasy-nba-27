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
