"""Nightly update pipeline (Step 12): one command, safe to cron.

Sequence (each pull is fault-isolated — a failed source warns and the pipeline
continues, so one flaky site never kills the night's board):

1. **Current-season game logs** — full-season refetch, replaced in cache keyed on
   SEASON (``ingest.refresh_season``; endpoint returns the whole season — idempotent).
2. **Injuries + transactions** — incremental prosportstransactions pulls (resume from
   the max cached date; drives the real Edge via Playwright — a browser window opens).
3. **DARKO + market archives** — date-stamped, append-only pulls so the EXP-017b/020
   archives accumulate (the whole point of pulling nightly).
4. **The as-of board** — ``project_asof(today)`` on the adopted EWMA configuration
   (frozen half-lives), with ``config/overrides.yaml`` status caps applied
   (availability only) → append-only ``data/processed/ros_board/<YYYY-MM-DD>.parquet``.
   An existing file for the date is never silently overwritten (``--force`` to redo).
5. **The naive-updater line** (2026-07-09 addendum item 5): the K=20 shrinkage
   benchmark is computed from the frozen T₀ board and emitted next to the asof board
   (``naive_fpts_pg`` / ``naive_rank`` columns + a disagreement report) — the daily
   disagreement between them is itself a signal.

Usage:
    python scripts/update_daily.py                          # live (in season)
    python scripts/update_daily.py --offline --asof 2026-03-01   # dry-run on cached data
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from fantasy_nba.config import PROCESSED_DIR
from fantasy_nba.data import storage
from fantasy_nba.models import asof

ROS_BOARD_DIR = PROCESSED_DIR / "ros_board"
NAIVE_K = 20.0


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _guarded(label: str, fn) -> None:
    """Fault isolation: a failed pull warns loudly and the pipeline continues."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — cron safety beats precision here
        print(f"[WARN] {label} failed ({type(exc).__name__}: {exc}) — continuing.", flush=True)


def run_pulls(season: str) -> None:
    from fantasy_nba.data import ingest

    _guarded("game-log refresh", lambda: ingest.refresh_season("player_game_logs", season))
    pull_injuries = _load_script("pull_injuries")
    _guarded("injuries pull", lambda: pull_injuries.pull_dataset("injuries"))
    _guarded("transactions pull", lambda: pull_injuries.pull_dataset("transactions"))
    pull_darko = _load_script("pull_darko")
    _guarded("DARKO archive", pull_darko.fetch_darko)
    pull_market = _load_script("pull_market")
    for source in ("hashtag", "fantasypros"):
        _guarded(f"market archive ({source})", lambda s=source: pull_market.pull(s))


def naive_line(t0_board: pd.DataFrame, gl_s: pd.DataFrame, T: pd.Timestamp, cfg,
               board: pd.DataFrame) -> pd.DataFrame:
    """Attach the naive-updater benchmark to the asof board + print the disagreement."""
    eval_asof = _load_script("eval_asof")
    naive = eval_asof.naive_board(t0_board, gl_s, T, cfg)
    naive = naive.sort_values("fpts_total", ascending=False).reset_index(drop=True)
    naive["naive_rank"] = range(1, len(naive) + 1)
    naive = naive.rename(columns={"fpts_pg": "naive_fpts_pg"})
    out = board.merge(naive[["PLAYER_ID", "naive_fpts_pg", "naive_rank"]],
                      on="PLAYER_ID", how="left")

    top = out.nsmallest(150, "rank").dropna(subset=["naive_rank"])
    rho = top["rank"].corr(top["naive_rank"], method="spearman")
    top = top.assign(rank_gap=top["naive_rank"] - top["rank"])
    movers = top.reindex(top["rank_gap"].abs().sort_values(ascending=False).index).head(8)
    print(f"[naive] top-150 Spearman asof vs naive: {rho:.3f}; biggest disagreements "
          f"(+ = asof higher):")
    print(movers[["rank", "naive_rank", "PLAYER_NAME", "fpts_pg", "naive_fpts_pg"]]
          .to_string(index=False))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 12 nightly update pipeline.")
    parser.add_argument("--asof", default=None, help="ISO date (default: today).")
    parser.add_argument("--season", default=None,
                        help="Override the date->season inference (e.g. at preseason edges).")
    parser.add_argument("--offline", action="store_true",
                        help="Skip every network pull; project from cached data (dry-run).")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing board for this date (never silent).")
    parser.add_argument("--t0-board", default=None,
                        help="Frozen preseason board parquet for the naive benchmark "
                             "(default: data/processed/learned_<season>.parquet).")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()

    T = pd.Timestamp(args.asof or dt.date.today().isoformat())
    gl = asof._with_dates(storage.read("player_game_logs"))
    try:
        season = args.season or asof._season_for_date(gl, T)
    except ValueError as exc:
        raise SystemExit(f"{exc} — off-season? Pass --asof <in-season date> for a dry-run, "
                         f"or --season to force.") from exc
    print(f"[update_daily] as of {T.date()} → season {season}"
          f"{' (OFFLINE — no pulls)' if args.offline else ''}", flush=True)

    if not args.offline:
        run_pulls(season)
        gl = asof._with_dates(storage.read("player_game_logs"))  # re-read post-refresh

    out_path = ROS_BOARD_DIR / f"{T.date().isoformat()}.parquet"
    if out_path.exists() and not args.force:
        raise SystemExit(f"{out_path} already exists — append-only history; --force to redo.")

    from fantasy_nba.scoring import load_scoring
    cfg = load_scoring()
    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    overrides = asof.load_status_overrides()
    schedule, season_end = None, None
    if storage.exists(f"schedule_{season}"):
        schedule = storage.read(f"schedule_{season}")
        reg = schedule[schedule["regular_season"]]
        season_end = pd.to_datetime(reg["game_date"]).max()
        schedule = reg[pd.to_datetime(reg["game_date"]) > T]
    if overrides:
        print(f"[overrides] {len(overrides)} status override(s) active")

    params = {**asof.DEFAULT_LGBM_PARAMS, "random_state": args.seed}
    board = asof.project_asof(
        str(T.date()), season_stats, gl, bio, cfg=cfg, params=params,
        target_season=season, use_ewma=True,
        status_overrides=overrides, season_end=season_end, schedule=schedule,
    )

    # The naive-updater line (addendum item 5) — needs a frozen T₀ board to anchor on.
    t0_path = Path(args.t0_board) if args.t0_board else PROCESSED_DIR / f"learned_{season}.parquet"
    if t0_path.exists():
        t0_board = pd.read_parquet(t0_path)
        board = naive_line(t0_board, gl[gl["SEASON"] == season], T, cfg, board)
    else:
        print(f"[naive] no T₀ board at {t0_path} — skipping the benchmark line.")

    ROS_BOARD_DIR.mkdir(parents=True, exist_ok=True)
    board.to_parquet(out_path, index=False)
    print(f"\nSaved ROS board -> {out_path}")
    show = [c for c in ("rank", "PLAYER_NAME", "games_so_far", "gp", "mpg", "fpts_pg",
                        "fpts_total", "naive_fpts_pg", "naive_rank", "status_override")
            if c in board.columns]
    with pd.option_context("display.width", 200):
        print(board[show].head(args.top).to_string(index=False))


if __name__ == "__main__":
    main()
