"""The web UI's API — run it with `python scripts/serve.py` (uvicorn under the hood).

Routes (all JSON, under /api):
  meta                     scoring/league config, seasons, models, data status
  board                    draft board: target x model x stance x analyst layer, with tiers
  ros / ros/{date}         nightly remaining-of-season snapshots (update_daily.py output)
  weeks / weekly           weekly planner: NBA-week index + per-player FP/G × games that week
  player/{id}              one player: board-B row, career per-game history, minutes logs
  datasets / datasets/{n}  raw parquet browser (paged, filterable)
  proposals                analyst-proposal review panel (+ status PATCH + promote POST)
  draft/*                  the live draft room (Step 19): state / connect / source / pick /
                           undo / refresh — manual or ESPN feed, switchable mid-draft

The built frontend (frontend/dist) is served from "/" when present, with an SPA fallback,
so one process serves the whole app. During frontend dev, Vite proxies /api here instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import CONFIG_DIR, MANUAL_DIR, PROCESSED_DIR, RAW_DIR, ROOT
from ..models.analyst import apply_overrides, name_key, parse_overrides
from ..models.uncertainty import rank_board
from ..scoring import load_scoring
from . import boards
from .draft import router as draft_router
from .season import router as season_router

PROPOSALS_PATH = CONFIG_DIR / "analyst_proposals.yaml"
LEAGUE_PATH = CONFIG_DIR / "league.yaml"
DIST_DIR = ROOT / "frontend" / "dist"

DATASET_LABELS = {
    "player_season_stats": "Season stats — per-player-season totals + advanced",
    "player_game_logs": "Game logs — one row per player per game",
    "player_bio": "Bio — age, height, draft",
    "team_rosters": "Current rosters",
    "injuries": "Injury / IL history (prosportstransactions)",
    "transactions": "Player-movement transactions (prosportstransactions)",
}

app = FastAPI(title="fantasy-nba-27", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Draft room (Step 19). Registered before the SPA static mount so /api/draft/* wins.
app.include_router(draft_router)
# Season views V1-V6 (docs/ui-views-plan.md): trends / trade-targets / schedule-strength.
app.include_router(season_router)


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → JSON-safe records (NaN → null, numpy scalars → native)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _require_data() -> None:
    if not boards.data_ready():
        raise HTTPException(
            503,
            "No data cached yet. Run `python scripts/pull_data.py --seasons …` (real) or "
            "`python scripts/dev_fixtures.py` (synthetic dev fixtures).",
        )


# ------------------------------------------------------------------------------------ meta
@app.get("/api/meta")
def meta() -> dict:
    cfg = load_scoring()
    league = yaml.safe_load(LEAGUE_PATH.read_text(encoding="utf-8")) if LEAGUE_PATH.exists() else {}
    ss = boards.raw("player_season_stats")
    seasons = sorted(ss["SEASON"].unique().tolist()) if not ss.empty else []
    return {
        "scoring": {"name": cfg.name, "weights": cfg.weights},
        "league": {k: league.get(k) for k in ("name", "platform", "teams", "format")},
        "target_seasons": boards.TARGET_SEASONS,
        "current_target": boards.CURRENT_TARGET,
        "models": boards.MODELS,
        "stances": boards.STANCES,
        "data_ready": boards.data_ready(),
        "data_seasons": [seasons[0], seasons[-1]] if seasons else None,
        "fixture": (RAW_DIR / "FIXTURE_DATA.marker").exists(),
    }


# ----------------------------------------------------------------------------------- board
@app.get("/api/board")
def board(
    target: str = Query(default=boards.CURRENT_TARGET),
    model: str = Query(default="learned"),
    stance: str = Query(default="safe"),
    analyst: bool = Query(default=True),
) -> dict:
    _require_data()
    if target not in boards.TARGET_SEASONS:
        raise HTTPException(422, f"target must be one of {boards.TARGET_SEASONS}")
    if model not in boards.MODELS:
        raise HTTPException(422, f"model must be one of {list(boards.MODELS)}")
    if stance not in boards.STANCES:
        raise HTTPException(422, f"stance must be one of {list(boards.STANCES)}")

    b = boards.ranked_board(target, model, stance, analyst)
    cols = [c for c in (
        "rank", "tier", "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "target_age",
        "gp", "mpg", "fpts_pg", "fpts_total", "draft_value", "fpts_p10", "fpts_median",
        "fpts_p90", "risk", "analyst_action", "analyst_category", "analyst_date",
        "model_rank", "vor", "vor_rank", "adp", "market_priced",
        "actual_rank", "act_fpts_pg", "act_fpts_total", "act_gp",
    ) if c in b.columns]
    analyst_applied = bool(
        analyst and target == boards.CURRENT_TARGET and "analyst_action" in b.columns)
    n_adjusted = int((~b["analyst_action"].fillna("").isin(["", "none"])).sum()) \
        if analyst_applied else 0
    return {
        "target": target, "model": model, "stance": stance,
        "analyst_applied": analyst_applied, "n_adjusted": n_adjusted,
        "has_actuals": "actual_rank" in b.columns,
        "teams": sorted(b["TEAM_ABBREVIATION"].dropna().unique().tolist()),
        "rows": _records(b[cols]),
    }


# ------------------------------------------------------------------------------------- ros
@app.get("/api/ros")
def ros_index() -> dict:
    ros_dir = PROCESSED_DIR / "ros_board"
    snaps = sorted(p.stem for p in ros_dir.glob("*.parquet")) if ros_dir.exists() else []
    return {"snapshots": snaps}


@app.get("/api/ros/{date}")
def ros_snapshot(date: str) -> dict:
    path = PROCESSED_DIR / "ros_board" / f"{date}.parquet"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not path.exists():
        raise HTTPException(404, f"no ROS snapshot for {date}")
    df = pd.read_parquet(path)
    cols = [c for c in ("rank", "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION",
                        "games_so_far", "gp", "mpg", "fpts_pg", "fpts_total",
                        "naive_fpts_pg", "naive_rank", "status_override", "redist_mpg",
                        "analyst_action", "analyst_decay_factor", "analyst_stale")
            if c in df.columns]
    out = df[cols].copy()
    if {"rank", "naive_rank"} <= set(out.columns):
        out["rank_gap"] = out["naive_rank"] - out["rank"]
    return {"date": date, "rows": _records(out)}


# ------------------------------------------------------------------------------ weekly plan
def _week_days(long: pd.DataFrame) -> list[str]:
    return sorted(pd.to_datetime(long["game_date"]).dt.strftime("%Y-%m-%d").unique().tolist())


@app.get("/api/weeks")
def weeks(target: str = Query(default=boards.CURRENT_TARGET)) -> dict:
    """The NBA-week index for the weekly planner's week picker. `has_schedule` is False
    until `scripts/pull_schedule.py` caches the season (published ~mid-August)."""
    long = boards.team_week_games(target)
    if long.empty:
        return {"target": target, "has_schedule": False, "weeks": []}
    out = []
    for wk, g in long.groupby("week"):
        days = _week_days(g)
        out.append({
            "week": int(wk),
            "week_name": str(g["week_name"].iloc[0]),
            "start": days[0], "end": days[-1], "days": days,
            "n_games": int(len(g) // 2),  # each game is two team-rows in the long form
        })
    out.sort(key=lambda w: w["week"])
    return {"target": target, "has_schedule": True, "weeks": out}


@app.get("/api/weekly")
def weekly(
    target: str = Query(default=boards.CURRENT_TARGET),
    week: int = Query(...),
    model: str = Query(default="learned"),
    stance: str = Query(default="safe"),
    analyst: bool = Query(default=True),
) -> dict:
    """Per-player weekly value for one NBA week: projected FP/G × games that week, plus the
    per-day game dates so the UI can re-total over a subset of days (the day toggles)."""
    _require_data()
    if target not in boards.TARGET_SEASONS:
        raise HTTPException(422, f"target must be one of {boards.TARGET_SEASONS}")
    if model not in boards.MODELS:
        raise HTTPException(422, f"model must be one of {list(boards.MODELS)}")
    if stance not in boards.STANCES:
        raise HTTPException(422, f"stance must be one of {list(boards.STANCES)}")

    long = boards.team_week_games(target)
    if long.empty:
        raise HTTPException(
            404, "No schedule cached for this season — run `python scripts/pull_schedule.py` "
                 "(the 2026-27 schedule publishes ~mid-August).")
    wk = long[long["week"] == week]
    if wk.empty:
        raise HTTPException(404, f"week {week} is not in the {target} schedule")
    days = _week_days(wk)
    by_team: dict[str, list[str]] = {
        str(team): sorted(pd.to_datetime(g["game_date"]).dt.strftime("%Y-%m-%d").tolist())
        for team, g in wk.groupby("team")
    }

    b = boards.ranked_board(target, model, stance, analyst)
    rows = []
    for r in b.itertuples(index=False):
        fpg = getattr(r, "fpts_pg", None)
        if fpg is None or pd.isna(fpg):
            continue
        team = getattr(r, "TEAM_ABBREVIATION", None)
        team = str(team) if team is not None and pd.notna(team) else None
        games = by_team.get(team, []) if team else []
        # Round FP/G first so the displayed value × games equals the weekly total exactly
        # (and matches the client's re-total when days are toggled off).
        fpg_r = round(float(fpg), 1)
        rows.append({
            "PLAYER_ID": int(r.PLAYER_ID),
            "PLAYER_NAME": r.PLAYER_NAME,
            "TEAM_ABBREVIATION": team,
            "rank": int(r.rank),
            "fpts_pg": fpg_r,
            "gp": None if pd.isna(getattr(r, "gp", np.nan)) else round(float(r.gp)),
            "games": games,
            "n_games": len(games),
            "weekly_fpts": round(fpg_r * len(games), 1),
        })
    rows.sort(key=lambda x: x["weekly_fpts"], reverse=True)
    return {
        "target": target, "week": week, "week_name": str(wk["week_name"].iloc[0]),
        "start": days[0], "end": days[-1], "days": days,
        "teams": sorted({t for t in (r["TEAM_ABBREVIATION"] for r in rows) if t}),
        "rows": rows,
    }


# ---------------------------------------------------------------------------------- player
@app.get("/api/players")
def players() -> dict:
    """Search index: every player on the current board, cheapest possible payload."""
    _require_data()
    b = boards.ranked_board(boards.CURRENT_TARGET, "learned", "safe", True)
    return {"rows": _records(b[["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "rank"]])}


def _player_provenance(player_name: str) -> dict:
    """The analyst-layer provenance behind board B for one player, surfaced on the Player
    page (data/manual/bbm_transcripts workflow): the extracted BBM facts
    (``data/manual/bbm_notes.csv``) and the **full** analyst-override history
    (``config/analyst_overrides.yaml`` — append-only, so superseded and ``none`` verdicts
    show too), newest first, with the currently-effective entry flagged. Both join on the
    same ``name_key`` the layer itself uses; absent files degrade to empty lists."""
    from ..models.analyst import load_overrides, name_key

    key = name_key(player_name)

    notes: list[dict] = []
    npath = MANUAL_DIR / "bbm_notes.csv"
    if npath.exists():
        nf = pd.read_csv(npath)
        if "player" in nf.columns:
            nf = nf[nf["player"].map(name_key) == key]
            if "date" in nf.columns:
                nf = nf.sort_values("date", ascending=False)
            notes = _records(nf[[c for c in ("date", "team", "claim_type", "direction",
                                             "quote", "source_file") if c in nf.columns]])

    overrides: list[dict] = []
    opath = CONFIG_DIR / "analyst_overrides.yaml"
    if opath.exists():
        mine = [e for e in load_overrides(opath) if e["name_key"] == key]
        mine.sort(key=lambda e: (e["date"], e["_pos"]), reverse=True)  # newest first
        for i, e in enumerate(mine):
            unit = {"fpts_delta": "fpts/g", "rank_delta": "rank"}.get(e["kind"], "")
            overrides.append({
                "date": e["date"].date().isoformat(),
                "category": e["category"],
                "action": "none" if e["kind"] == "none" else f"{e['value']:+g} {unit}".strip(),
                "rationale": e["rationale"],
                "effective": i == 0,   # newest-dated (tie broken by file pos) is what applies
            })

    return {"bbm_notes": notes, "overrides": overrides}


@app.get("/api/player/{player_id}")
def player(player_id: int) -> dict:
    _require_data()
    b = boards.ranked_board(boards.CURRENT_TARGET, "learned", "safe", True)
    hit = b[b["PLAYER_ID"] == player_id]
    if hit.empty:
        raise HTTPException(404, f"player {player_id} not on the current board")
    row = hit.iloc[0]

    cfg = load_scoring()
    ss = boards.raw("player_season_stats")
    hist = ss[ss["PLAYER_ID"] == player_id].copy()
    agg = {c: (c, "sum") for c in
           ("GP", "MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV",
            "FGM", "FGA", "FTM", "FTA") if c in hist.columns}
    hist = hist.groupby("SEASON", as_index=False).agg(
        AGE=("AGE", "max"), TEAM=("TEAM_ABBREVIATION", "last"),
        USG=("USG_PCT", "mean") if "USG_PCT" in hist.columns else ("GP", "size"),
        **agg).sort_values("SEASON")
    per_game = hist.copy()
    w = cfg.weights
    per_game["FPTS"] = (
        w.get("pts", 0) * hist.get("PTS", 0) + w.get("fg3m", 0) * hist.get("FG3M", 0)
        + w.get("fgm", 0) * hist.get("FGM", 0) + w.get("fga", 0) * hist.get("FGA", 0)
        + w.get("ftm", 0) * hist.get("FTM", 0) + w.get("fta", 0) * hist.get("FTA", 0)
        + w.get("reb", 0) * hist.get("REB", 0) + w.get("ast", 0) * hist.get("AST", 0)
        + w.get("stl", 0) * hist.get("STL", 0) + w.get("blk", 0) * hist.get("BLK", 0)
        + w.get("tov", 0) * hist.get("TOV", 0))
    gp = per_game["GP"].clip(lower=1)
    for c in ("MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV", "FPTS"):
        if c in per_game.columns:
            per_game[c] = (per_game[c] / gp).round(1)
    per_game = per_game.rename(columns={"MIN": "MPG"})
    career_cols = [c for c in ("SEASON", "AGE", "TEAM", "GP", "MPG", "PTS", "REB", "AST",
                               "STL", "BLK", "FG3M", "TOV", "USG", "FPTS") if c in per_game.columns]

    gl = boards.raw("player_game_logs")
    games: list[dict] = []
    latest = None
    if not gl.empty:
        plog = gl[gl["PLAYER_ID"] == player_id]
        if not plog.empty:
            latest = plog["SEASON"].max()
            cur = plog[plog["SEASON"] == latest].sort_values("GAME_DATE")
            games = _records(cur[[c for c in ("GAME_DATE", "MIN", "PTS") if c in cur.columns]])

    proj_cols = [c for c in (
        "rank", "tier", "PLAYER_NAME", "TEAM_ABBREVIATION", "target_age", "gp", "mpg",
        "fpts_pg", "fpts_total", "fpts_p10", "fpts_median", "fpts_p90", "risk",
        "analyst_action", "analyst_category", "analyst_date", "model_rank",
        "vor", "vor_rank", "adp",
        "pts", "reb", "ast", "stl", "blk", "fg3m", "tov", "fgm", "fga", "ftm", "fta",
    ) if c in b.columns]
    return {
        "projection": _records(hit[proj_cols])[0],
        "career": _records(per_game[career_cols]),
        "game_log_season": latest,
        "game_log": games,
        **_player_provenance(row["PLAYER_NAME"]),
    }


# -------------------------------------------------------------------------------- datasets
@app.get("/api/datasets")
def datasets() -> dict:
    from ..data import storage

    return {"datasets": [
        {"name": n, "label": lbl, "cached": storage.exists(n)}
        for n, lbl in DATASET_LABELS.items()
    ]}


@app.get("/api/datasets/{name}")
def dataset(
    name: str,
    season: str | None = None,
    q: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    from ..data import storage

    if name not in DATASET_LABELS:
        raise HTTPException(404, f"unknown dataset {name!r}")
    if not storage.exists(name):
        raise HTTPException(404, f"{name} is not cached — pull it first")
    df = storage.read(name)
    seasons = sorted(df["SEASON"].unique().tolist(), reverse=True) if "SEASON" in df.columns else []
    if season and "SEASON" in df.columns:
        df = df[df["SEASON"] == season]
    namecol = next((c for c in ("PLAYER_NAME", "PLAYER") if c in df.columns), None)
    if q and namecol:
        df = df[df[namecol].astype(str).str.contains(q, case=False, na=False)]
    total = len(df)
    page = df.iloc[offset:offset + limit]
    return {"name": name, "columns": list(df.columns), "total": total,
            "seasons": seasons, "rows": _records(page)}


# ------------------------------------------------------------------------------- proposals
def _load_proposals_raw() -> list[dict]:
    if not PROPOSALS_PATH.exists():
        return []
    return yaml.safe_load(PROPOSALS_PATH.read_text(encoding="utf-8")) or []


@app.get("/api/proposals")
def proposals() -> dict:
    """The review panel: every proposal + its live board impact (pure-model board A,
    same recipe as `apply_proposals.py` preview)."""
    raw = _load_proposals_raw()
    out = [{k: p.get(k) for k in
            ("name", "date", "category", "action", "rationale", "status", "preview",
             "triangulation")} for p in raw]
    for p, src in zip(out, raw):
        p["date"] = str(src.get("date", ""))
        act = src.get("action")
        p["action_str"] = act if act == "none" else (
            f"{list(act)[0]}:{float(list(act.values())[0]):+g}" if isinstance(act, dict) else str(act))

    impact: dict[str, dict] = {}
    if boards.data_ready() and raw:
        try:
            base = boards.compute_board(boards.CURRENT_TARGET, "learned", False,
                                        boards.overrides_mtime())
            board_a = rank_board(base, "safe")
            entries = parse_overrides(
                [{k: p[k] for k in ("name", "date", "category", "action", "rationale")}
                 for p in raw], source="proposals")
            after = apply_overrides(board_a, entries).set_index("PLAYER_ID")
            before = board_a.set_index("PLAYER_ID")
            key_to_pid = {name_key(n): pid for pid, n in before["PLAYER_NAME"].items()}
            for p, e in zip(out, entries):
                pid = key_to_pid.get(e["name_key"])
                if pid is None:
                    impact[p["name"]] = {"on_board": False}
                    continue
                impact[p["name"]] = {
                    "on_board": True,
                    "fpts_old": round(float(before.loc[pid, "fpts_pg"]), 1),
                    "fpts_new": round(float(after.loc[pid, "fpts_pg"]), 1),
                    "rank_old": int(after.loc[pid, "model_rank"]),
                    "rank_new": int(after.loc[pid, "rank"]),
                }
        except Exception as exc:  # preview is best-effort; the list must still render
            impact = {"_error": {"message": str(exc)}}
    counts: dict[str, int] = {}
    for p in out:
        counts[p.get("status") or "?"] = counts.get(p.get("status") or "?", 0) + 1
    return {"proposals": out, "impact": impact, "counts": counts}


_STATUS_VALUES = ("proposed", "approved", "rejected")


@app.patch("/api/proposals/{name}/{date}")
def set_proposal_status(name: str, date: str, status: str = Query(...)) -> dict:
    """Flip one proposal's `status:` line in config/analyst_proposals.yaml — a surgical
    text edit (comments and formatting preserved), verified by re-parsing the file.
    This is the user's review action, the same as editing the file by hand."""
    if status not in _STATUS_VALUES:
        raise HTTPException(422, f"status must be one of {_STATUS_VALUES}")
    raw = _load_proposals_raw()
    match = [p for p in raw if p.get("name") == name and str(p.get("date")) == date]
    if not match:
        raise HTTPException(404, f"no proposal {name!r} dated {date}")

    text = PROPOSALS_PATH.read_text(encoding="utf-8")
    # The entry block starts at "- name: <name>" and runs to the next top-level "- name:".
    blocks = list(re.finditer(r"(?m)^- name:\s*(.+?)\s*$", text))
    target_span = None
    for i, m in enumerate(blocks):
        block_name = m.group(1).strip().strip("\"'")
        end = blocks[i + 1].start() if i + 1 < len(blocks) else len(text)
        block = text[m.start():end]
        if block_name == name and re.search(rf"(?m)^  date:\s*{re.escape(date)}\s*$", block):
            target_span = (m.start(), end, block)
            break
    if target_span is None:
        raise HTTPException(409, "could not locate the entry block in the YAML text")
    start, end, block = target_span
    new_block, n = re.subn(r"(?m)^(  status:\s*)\S+\s*$", rf"\g<1>{status}", block, count=1)
    if n != 1:
        raise HTTPException(409, "entry has no single status line to rewrite")
    new_text = text[:start] + new_block + text[end:]

    reparsed = yaml.safe_load(new_text) or []
    if len(reparsed) != len(raw):  # the edit must not change the entry count
        raise HTTPException(500, "rewrite validation failed — file left untouched")
    PROPOSALS_PATH.write_text(new_text, encoding="utf-8")
    return {"name": name, "date": date, "status": status}


@app.post("/api/proposals/promote")
def promote_proposals() -> dict:
    """Promote status=approved proposals into config/analyst_overrides.yaml — the exact
    same code path as `python scripts/apply_proposals.py --promote` (idempotent)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "apply_proposals", ROOT / "scripts" / "apply_proposals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    raw = _load_proposals_raw()
    overrides_path = CONFIG_DIR / "analyst_overrides.yaml"
    existing = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or []
    have = {(name_key(e["name"]), str(pd.Timestamp(e["date"]).date())) for e in existing}
    would = [p["name"] for p in raw if p.get("status") == "approved"
             and (name_key(p["name"]), str(pd.Timestamp(p["date"]).date())) not in have]
    try:
        mod.promote(raw, overrides_path)
    except SystemExit as exc:  # the script raises SystemExit on validation failures
        raise HTTPException(422, str(exc)) from exc
    boards.compute_board.cache_clear()  # overrides changed — boards must recompute
    return {"promoted": would}


# ---------------------------------------------------------------- static frontend (built)
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (DIST_DIR / path).resolve()
        if path and target.is_file() and target.is_relative_to(DIST_DIR):
            return FileResponse(target)
        return FileResponse(DIST_DIR / "index.html")
