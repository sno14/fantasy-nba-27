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
5. **The OUT-redistribution layer** (EXP-030, adopted-tentative — re-affirm Apr 2027):
   minutes of players currently OUT (overrides + open injury spells) flow to same-team
   teammates by the fitted absorption tiers, prorated by expected absence
   (``redist_mpg`` audit column; ``--no-redist`` to disable). Weights fit once per
   season from strictly-prior game logs and cached to
   ``data/processed/absorption_weights_<season>.json``.
6. **The analyst layer** (workflow v2, 2026-07-12 — the living transcript-fed layer):
   effective ``config/analyst_overrides.yaml`` entries apply to the nightly ROS board
   (``analyst_action``/``model_rank`` audit columns; ``--no-analyst`` to disable). The
   in-season ROS adjustment the user named critical: approved judgment moves the board
   the night it lands, not at the next preseason.
7. **The naive-updater line** (2026-07-09 addendum item 5): the K=20 shrinkage
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


def _absorption_weights(season: str, gl: pd.DataFrame) -> dict:
    """EXP-030 absorption weights for ``season``: fit once from strictly-prior game logs,
    cached to ``data/processed/absorption_weights_<season>.json`` (the fit is deterministic
    — no seed protocol — but the dataset build takes minutes, so nightly reuse matters)."""
    import json

    from fantasy_nba.models import absorption as ab
    from fantasy_nba.models import allocation as alloc
    from fantasy_nba.models._core import _season_start

    path = PROCESSED_DIR / f"absorption_weights_{season}.json"
    if path.exists():
        return json.loads(path.read_text())
    ty = _season_start(season)
    train_gl = gl[gl["SEASON"].map(_season_start) < ty]
    team_logs = None
    if storage.exists("team_game_logs"):
        team_logs = storage.read("team_game_logs")
        team_logs = team_logs[team_logs["SEASON"].map(_season_start) < ty]
    pos_map = alloc.pos_group_asof(alloc.position_table(storage.read("team_rosters")), season)
    weights = ab.fit_absorption(ab.absorption_dataset(train_gl, team_logs=team_logs, pos_map=pos_map))
    path.write_text(json.dumps(weights))
    print(f"[redist] absorption weights fit on {weights['n_rows']:,} rows -> {path.name}")
    return weights


def _out_events(board: pd.DataFrame, overrides: list[dict], spells, medians,
                T: pd.Timestamp, season_end: pd.Timestamp) -> pd.DataFrame:
    """OUT events for redistribution: open injury spells (honest median-estimated return)
    ∪ overrides.yaml entries (news-based; matched to the board by the shared name key).
    Per player the **longest** horizon wins — the conservative redistribution window."""
    from fantasy_nba.models import absorption as ab
    from fantasy_nba.models.analyst import name_key

    frames = []
    if spells is not None:
        frames.append(ab.out_events_asof(spells, T, medians))
    rows = []
    keys = board["PLAYER_NAME"].map(name_key)
    for e in overrides or []:
        hits = board.loc[(keys == name_key(e["name"])).to_numpy(), "PLAYER_ID"]
        if len(hits) == 1:  # unmatched names already raised in apply_status_overrides
            rows.append({"PLAYER_ID": hits.iloc[0],
                         "out_until": season_end if e["out_for_season"] else e["out_until"]})
    if rows:
        frames.append(pd.DataFrame(rows))
    if not frames:
        return pd.DataFrame(columns=["PLAYER_ID", "out_until"])
    ev = pd.concat(frames, ignore_index=True)
    return ev.groupby("PLAYER_ID", as_index=False)["out_until"].max()


def apply_redistribution(board: pd.DataFrame, gl: pd.DataFrame, season: str, T: pd.Timestamp,
                         season_stats: pd.DataFrame, cfg, overrides: list[dict],
                         season_end: pd.Timestamp | None) -> pd.DataFrame:
    """The EXP-030 layer: flow OUT players' minutes to teammates on tonight's board."""
    from fantasy_nba.models import absorption as ab
    from fantasy_nba.models import allocation as alloc
    from fantasy_nba.models import injuries as inj

    gl_s = gl[gl["SEASON"] == season]
    if gl_s.empty:
        print("[redist] no games yet this season — nothing to redistribute.")
        return board
    weights = _absorption_weights(season, gl)
    spells = medians = None
    if storage.exists("injuries"):
        spells, _ = inj.build_spells(storage.read("injuries"), season_stats)
        medians = ab.spell_duration_medians(spells[spells["start"] < T])
    if season_end is None:  # no schedule pull yet — the same fallback the override caps use
        season_end = gl_s["_date"].min() + pd.Timedelta(days=asof.SEASON_LENGTH_DAYS)
    ev = _out_events(board, overrides, spells, medians, T, season_end)
    if ev.empty:
        print("[redist] no OUT events tonight.")
        return board
    pos_map = alloc.pos_group_asof(alloc.position_table(storage.read("team_rosters")), season)
    out = ab.redistribute_board(board, ev, ab.team_map_asof(gl_s, T), pos_map, weights,
                                T, season_end, cfg)
    moved = out[out["redist_mpg"] > 0]
    top = ", ".join(f"{r.PLAYER_NAME} +{r.redist_mpg:.1f}" for r in
                    moved.nlargest(5, "redist_mpg").itertuples())
    print(f"[redist] {len(ev)} OUT tonight; {len(moved)} teammates adjusted (top mpg: {top})")
    return out


def _base_then(entries: list[dict], t0_path: Path | None) -> dict[str, float]:
    """The model's pre-analyst base fpts_pg *when each bridge entry was written*
    (Step 18.1), keyed by name_key. Recovered from the earliest ros_board snapshot
    dated on/after the entry (its stored fpts_pg minus the fpts_delta its audit column
    says was applied), falling back to the frozen preseason board A for entries older
    than the archive. An entry checkable by neither (e.g. dated today, first night) is
    skipped — it becomes checkable tomorrow."""
    from fantasy_nba.models.analyst import (BRIDGE_CATEGORIES, effective_overrides,
                                            name_key, parse_fpts_delta)

    dates = sorted(p.stem for p in ROS_BOARD_DIR.glob("*.parquet")) \
        if ROS_BOARD_DIR.exists() else []
    t0 = pd.read_parquet(t0_path) if t0_path and t0_path.exists() else None
    snaps: dict[str, pd.DataFrame] = {}
    out: dict[str, float] = {}
    for e in effective_overrides(entries):
        if e["kind"] != "fpts_delta" or e["category"] not in BRIDGE_CATEGORIES:
            continue
        snap_date = next((d for d in dates if d >= e["date"].date().isoformat()), None)
        if snap_date is not None:
            snap = snaps.setdefault(snap_date, pd.read_parquet(
                ROS_BOARD_DIR / f"{snap_date}.parquet"))
            hit = snap[snap["PLAYER_NAME"].map(name_key) == e["name_key"]]
            if not hit.empty:
                r = hit.iloc[0]
                out[e["name_key"]] = float(r["fpts_pg"]) - parse_fpts_delta(
                    str(r.get("analyst_action", "")))
                continue
        if t0 is not None:  # pure-model board A — no delta to strip
            hit = t0[t0["PLAYER_NAME"].map(name_key) == e["name_key"]]
            if not hit.empty:
                out[e["name_key"]] = float(hit.iloc[0]["fpts_pg"])
    return out


def apply_analyst_layer(board: pd.DataFrame, decay: bool = False,
                        t0_path: Path | None = None) -> pd.DataFrame:
    """The in-season analyst layer (workflow v2): apply the effective
    ``config/analyst_overrides.yaml`` entries to tonight's ROS board via the same
    unit-tested arithmetic as the preseason board B. No file = no entries = board
    unchanged (plus audit columns when entries exist).

    Step 18: prints the **staleness report** (18.1) — for each role/hype fpts_delta,
    tonight's pre-analyst base vs the base when the entry was written; entries the
    model has caught up to are flagged ``analyst_stale`` on the board and named
    "consider retiring" (post a later-dated ``none``/reduced entry — never edit).
    ``decay=True`` (18.2, ``--analyst-decay``, off by default pending its validation
    gate) tapers bridge deltas by games_so_far via ``analyst.decay_factor``."""
    from fantasy_nba.config import CONFIG_DIR
    from fantasy_nba.models.analyst import (apply_overrides, effective_overrides,
                                            load_overrides, name_key, stale_entries)

    path = CONFIG_DIR / "analyst_overrides.yaml"
    if not path.exists():
        return board
    entries = load_overrides(path)
    if not entries:
        return board

    # 18.1 — computed on the PRE-analyst base, before tonight's deltas land.
    base_now = {name_key(n): float(f) for n, f in
                zip(board["PLAYER_NAME"], board["fpts_pg"]) if pd.notna(f)}
    report = stale_entries(entries, base_now, _base_then(entries, t0_path))

    decay_col = "games_so_far" if (decay and "games_so_far" in board.columns) else None
    if decay and decay_col is None:
        print("[analyst] --analyst-decay ignored: board has no games_so_far column.")
    out = apply_overrides(board, entries, decay_from=decay_col)

    moved = out[~out["analyst_action"].isin(["", "none"])]
    print(f"[analyst] {len(effective_overrides(entries))} effective entrie(s); "
          f"{len(moved)} move the board tonight"
          f"{' (decay ON)' if decay_col else ''}:")
    if not moved.empty:
        cols = [c for c in ("PLAYER_NAME", "analyst_category", "analyst_action",
                            "analyst_decay_factor", "model_rank", "rank") if c in moved.columns]
        with pd.option_context("display.width", 200):
            print(moved[cols].to_string(index=False))

    stale_keys = {r["name_key"]: r for r in report if r["stale"]}
    keys = out["PLAYER_NAME"].map(name_key)
    out["analyst_stale"] = keys.map(lambda k: k in stale_keys)
    for r in report:
        line = (f"[analyst-stale] {r['name']} ({r['category']} {r['delta']:+g}): base "
                f"{r['base_then']} -> {r['base_now']} (caught up {r['caught_up']:+g})")
        print(line + ("  ** model has caught up — consider retiring (post a later-dated "
                      "none/reduced entry)" if r["stale"] else ""))
    return out


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
    parser.add_argument("--no-redist", action="store_true",
                        help="Skip the EXP-030 OUT-redistribution layer (plain asof board).")
    parser.add_argument("--no-analyst", action="store_true",
                        help="Skip the analyst-overrides layer (pure model + availability).")
    parser.add_argument("--analyst-decay", action="store_true",
                        help="Step 18.2 (OFF by default pending its validation gate): taper "
                             "role/hype fpts_deltas by games played so far — full through "
                             "~10 games, gone by ~30, when the EWMA has learned the role.")
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

    # The EXP-030 OUT-redistribution layer (adopted-tentative; fault-isolated like the pulls
    # — a failed redistribution warns and the plain board ships).
    if not args.no_redist:
        try:
            board = apply_redistribution(board, gl, season, T, season_stats, cfg,
                                         overrides, season_end)
        except Exception as exc:  # noqa: BLE001 — cron safety beats precision here
            print(f"[WARN] redistribution failed ({type(exc).__name__}: {exc}) — "
                  f"shipping the plain board.", flush=True)

    # The analyst layer (workflow v2) — approved judgment applies nightly. NOT fault-
    # isolated on purpose: a malformed override must fail the run loudly (a silently
    # dropped entry is a wrong board with no audit trail — same stance as the caps).
    t0_path = Path(args.t0_board) if args.t0_board else PROCESSED_DIR / f"learned_{season}.parquet"
    if not args.no_analyst:
        board = apply_analyst_layer(board, decay=args.analyst_decay, t0_path=t0_path)

    # The naive-updater line (addendum item 5) — needs a frozen T₀ board to anchor on.
    if t0_path.exists():
        t0_board = pd.read_parquet(t0_path)
        board = naive_line(t0_board, gl[gl["SEASON"] == season], T, cfg, board)
    else:
        print(f"[naive] no T₀ board at {t0_path} — skipping the benchmark line.")

    ROS_BOARD_DIR.mkdir(parents=True, exist_ok=True)
    board.to_parquet(out_path, index=False)
    print(f"\nSaved ROS board -> {out_path}")
    show = [c for c in ("rank", "PLAYER_NAME", "games_so_far", "gp", "mpg", "redist_mpg",
                        "fpts_pg", "fpts_total", "naive_fpts_pg", "naive_rank",
                        "status_override", "analyst_action", "analyst_stale")
            if c in board.columns]
    with pd.option_context("display.width", 200):
        print(board[show].head(args.top).to_string(index=False))


if __name__ == "__main__":
    main()
