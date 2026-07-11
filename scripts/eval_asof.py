"""EXP-018 gate + EXP-019 in-season diagnostics (implementation-plan Steps 10-11).

**EXP-018 gate (default mode):** per season and cutpoint (+30/+60/+90 days from the
season's first game), score three projections of the **remaining season** (per-game fpts
of games strictly after T) on each projection's own top-150 pool (by projected ROS total):

* ``asof``      — ``project_asof`` (one model per season fold, trained on the cutpoint panel
                  from strictly-prior seasons; predicts at every cutpoint).
* ``frozen_t0`` — ``project_learned`` fit at preseason and never updated (table stakes).
* ``naive``     — the hand-set shrinkage updater: per-game line =
                  ``(games_so_far × STD + K × T₀_proj) / (games_so_far + K)`` with K = 20,
                  built per player from the same game logs ≤ T. Beating this is the evidence
                  the *learned* shrinkage earns its complexity.

Gate: asof beats both on ROS level MAE in ≥ 2 of 3 cutpoints, in 3/4 seasons.

**EXP-019 diagnostics (``--exp019``, Step 11)** — runs on the EWMA configuration (the
EXP-018 pooled winner) with the frozen half-lives (rates → 40, MPG → 10), and prints:

1. the **in-season mover eval**: per cutpoint, the pooled per-bucket bias table on each
   model's top-150 ROS pool (``actual_delta_ros = act_ros_pg − prior_full_season_pg``,
   the standard bucket edges) + the per-cutpoint selection floor and reducible gap;
2. **early-riser recall** at +30d: of the realized in-season big risers
   (``act_ros_pg ≥ prior + 6``, ≥ 20 ROS games), the fraction inside our top-150 ROS
   board, and their projected vs realized Δ;
3. the **lead-time metric** (weekly grid — never literal daily re-projection): for each
   confirmed role change (trailing-10 MPG ≥ +6 over baseline, sustained 15 games), the
   first grid date the model's ROS MPG moved ≥ 50% of the realized change, vs the naive
   updater; median/IQR lead days per season;
4. a **league-horizon sensitivity** (amendment D1.3b): the cutpoint ROS MAE table with
   labels truncated at the league end analogue (``league_end_offset_weeks`` before the
   NBA finale) next to the full-season one — do the verdicts move?

Usage:
    python scripts/eval_asof.py --seasons 2022-23 2023-24 2024-25 2025-26 --seed 0
    python scripts/eval_asof.py --seasons 2022-23 2023-24 2024-25 2025-26 \
        --cutpoints 30 60 90 --exp019
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models import asof, floor_sim
from fantasy_nba.models._core import COUNTING, _season_start
from fantasy_nba.models.backtest import _actual, project_models
from fantasy_nba.models.eval_movers import (
    BUCKET_LABELS, _season_before, lead_time_table, pool_frame, role_change_events,
)
from fantasy_nba.models.value import load_league
from fantasy_nba.scoring import load_scoring, score_frame

GATE_OFFSETS = (30, 60, 90)
NAIVE_K = 20.0

# EXP-019 constants (Step 11).
RISER_EDGE = 6.0            # the big-riser bucket edge, ROS form
RISER_MIN_ROS_GP = 20       # a "realized in-season riser" needs a real ROS sample
MIN_PRIOR_MINUTES = 500.0   # prior-season line floor (matches the preseason mover eval)
GRID_STEP_DAYS = 7          # lead-time projection grid (weekly — addendum item 2)
GRID_MAX_DAYS = 182         # last grid offset from season start
LEAD_FRAC = 0.5             # "moved >= 50% of the eventual realized change"

# EXP-030 constants (Step 16).
MIN_ROS_GP_TREATED = 5      # a treated row needs a real ROS sample to be scored


def ros_actual(gl_season: pd.DataFrame, T: pd.Timestamp) -> pd.DataFrame:
    """Realized ROS per-game fantasy line after ``T`` (no floors — actuals are actuals;
    the pool join decides who is scored)."""
    future = gl_season[gl_season["_date"] > T]
    g = future.groupby("PLAYER_ID")
    tot_min = g["MIN"].sum()
    out = pd.DataFrame({"PLAYER_ID": tot_min.index})
    out["act_ros_gp"] = g.size().to_numpy()
    for canon, src in COUNTING.items():
        out[canon] = (g[src].sum() / g.size()).to_numpy()  # per-game
    return out


def naive_board(t0_board: pd.DataFrame, gl_season: pd.DataFrame, T: pd.Timestamp,
                cfg, k: float = NAIVE_K) -> pd.DataFrame:
    """The naive updater: per-stat per-game line shrunk between season-to-date and the frozen
    T₀ projection by games played. Players missing from the T₀ board keep pure STD."""
    played = gl_season[gl_season["_date"] <= T]
    g = played.groupby("PLAYER_ID")
    n = g.size()
    std = pd.DataFrame({"PLAYER_ID": n.index, "games_so_far": n.to_numpy()})
    for canon, src in COUNTING.items():
        std[f"std_{canon}"] = (g[src].sum() / n).to_numpy()  # per-game

    t0 = t0_board[["PLAYER_ID", "gp", "mpg"] + list(COUNTING)].copy()
    m = t0.merge(std, on="PLAYER_ID", how="outer")
    m["games_so_far"] = m["games_so_far"].fillna(0.0)
    out = pd.DataFrame({"PLAYER_ID": m["PLAYER_ID"]})
    w = m["games_so_far"] / (m["games_so_far"] + k)
    for canon in COUNTING:
        proj = pd.to_numeric(m[canon], errors="coerce")
        stdc = pd.to_numeric(m[f"std_{canon}"], errors="coerce")
        # missing T₀ projection (rookie) -> pure STD; missing STD (hasn't played) -> pure T₀
        blend = w * stdc.fillna(proj) + (1 - w) * proj.fillna(stdc)
        out[canon] = blend
    out["fpts_pg"] = score_frame(out, cfg)
    # rank by expected ROS involvement: same shrinkage on GP pace is overkill — use T₀ gp
    # where known, games-so-far pace otherwise (ranking only decides the pool).
    out["gp"] = pd.to_numeric(m["gp"], errors="coerce").fillna(m["games_so_far"])
    out["fpts_total"] = out["fpts_pg"] * out["gp"]
    return out.dropna(subset=["fpts_pg"]).reset_index(drop=True)


def pool_mae(board: pd.DataFrame, actual: pd.DataFrame, cfg, top_n: int = 150) -> tuple[float, int]:
    """ROS level MAE on the board's own top-N by projected ROS total."""
    act = actual.copy()
    act["act_fpts_pg"] = score_frame(act, cfg)
    pool = board.nlargest(top_n, "fpts_total")
    m = pool[["PLAYER_ID", "fpts_pg"]].merge(act[["PLAYER_ID", "act_fpts_pg"]], on="PLAYER_ID")
    return float((m["fpts_pg"] - m["act_fpts_pg"]).abs().mean()), len(m)


def ros_actual_scored(gl_season: pd.DataFrame, T: pd.Timestamp, cfg,
                      end: pd.Timestamp | None = None) -> pd.DataFrame:
    """ROS actuals scored for pooling: ``[PLAYER_ID, act_ros_gp, act_fpts_pg,
    act_fpts_total]``. ``end`` truncates the label window (the league-horizon view —
    the fantasy league ends before the NBA finale, so deployed ROS cuts there too)."""
    sub = gl_season if end is None else gl_season[gl_season["_date"] <= end]
    a = ros_actual(sub, T)
    if a.empty:
        return pd.DataFrame(columns=["PLAYER_ID", "act_ros_gp", "act_fpts_pg", "act_fpts_total"])
    a["act_fpts_pg"] = score_frame(a, cfg)
    a["act_fpts_total"] = a["act_fpts_pg"] * a["act_ros_gp"]
    return a[["PLAYER_ID", "act_ros_gp", "act_fpts_pg", "act_fpts_total"]]


def _rank_board(b: pd.DataFrame) -> pd.DataFrame:
    out = b.sort_values("fpts_total", ascending=False).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out


def _grid_mpg_asof(models: dict, preseason: pd.DataFrame, gl_s: pd.DataFrame,
                   dates: list[pd.Timestamp], half_lives: dict) -> pd.DataFrame:
    """Weekly-grid ROS-MPG projections ``[date, PLAYER_ID, mpg]`` — the fold's models are
    fitted once, the preseason block computed once; only the STD/EWMA blocks move per date
    (the Step-11.3 cost control: never refit, never literal daily re-projection)."""
    cols = models["_feature_cols"]
    frames = []
    for T in dates:
        sub = gl_s[gl_s["_date"] <= T]
        ew = asof.ewma_features(sub, T, half_lives) if half_lives else None
        feats = asof._row_frame(preseason, asof.std_features(sub, T), ew)
        for c in cols:
            if c not in feats.columns:
                feats[c] = np.nan
        mpg = np.clip(models["y_ros_mpg"].predict(feats[cols]), 0.0, 48.0)
        frames.append(pd.DataFrame({"date": T, "PLAYER_ID": feats["PLAYER_ID"].to_numpy(),
                                    "mpg": mpg}))
    return pd.concat(frames, ignore_index=True)


def _grid_mpg_naive(t0_board: pd.DataFrame, gl_s: pd.DataFrame,
                    dates: list[pd.Timestamp], k: float = NAIVE_K) -> pd.DataFrame:
    """The naive comparator's MPG on the same grid: ``(n×STD + K×T₀)/(n+K)``."""
    t0 = t0_board.drop_duplicates("PLAYER_ID").set_index("PLAYER_ID")["mpg"]
    frames = []
    for T in dates:
        played = gl_s[gl_s["_date"] <= T]
        g = played.groupby("PLAYER_ID")
        n = g.size()
        std_mpg = g["MIN"].sum() / n
        ids = t0.index.union(n.index)
        nn = n.reindex(ids).fillna(0.0)
        w = nn / (nn + k)
        blended = (w * std_mpg.reindex(ids).fillna(t0.reindex(ids))
                   + (1 - w) * t0.reindex(ids).fillna(std_mpg.reindex(ids)))
        frames.append(pd.DataFrame({"date": T, "PLAYER_ID": ids.to_numpy(),
                                    "mpg": blended.to_numpy()}))
    return pd.concat(frames, ignore_index=True)


def _bucket_table(m: pd.DataFrame) -> pd.DataFrame:
    """Pooled per-bucket rows (same arithmetic as ``run_mover_eval``'s per-bucket block)."""
    g = m.groupby("bucket", observed=False)
    return pd.DataFrame({
        "bucket": BUCKET_LABELS,
        "n": g.size().reindex(BUCKET_LABELS).values,
        "level_MAE": g["err"].apply(lambda e: e.abs().mean()).reindex(BUCKET_LABELS).values,
        "signed_bias": g["err"].mean().reindex(BUCKET_LABELS).values,
        "mean_actual_delta": g["actual_delta"].mean().reindex(BUCKET_LABELS).values,
        "mean_proj_delta": g["proj_delta"].mean().reindex(BUCKET_LABELS).values,
    })


def run_exp019(args, season_stats, bio, gl, cfg, params) -> None:
    """Step 11: the three EXP-019 diagnostics + the league-horizon sensitivity."""
    bounds_df = asof.season_date_bounds(gl)
    starts = bounds_df.set_index("SEASON")["start"]
    ends = bounds_df.set_index("SEASON")["end"]
    league = load_league()
    off_weeks = int(league.get("league_end_offset_weeks") or 0)
    half_lives = asof.FROZEN_HALF_LIVES
    print(f"[exp019] EWMA config, frozen half-lives {half_lives}; "
          f"league horizon = NBA finale − {off_weeks} weeks", flush=True)

    pools: dict[tuple[str, int], list[pd.DataFrame]] = {}
    mae_rows, recall_rows, lead_rows = [], [], []

    for season in args.seasons:
        ty = _season_start(season)
        train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
        train_bio = bio[bio["SEASON"].map(_season_start) < ty]
        train_gl = gl[gl["SEASON"].map(_season_start) < ty]

        panel = asof.build_asof_panel(train_ss, train_gl, train_bio, half_lives=half_lives)
        models = asof._fit_asof_models(panel, params, use_ewma=True)
        t0_board = project_models(season, season_stats, bio, cfg, seed=args.seed)["learned"]
        gl_s = gl[gl["SEASON"] == season]
        league_end = ends[season] - pd.Timedelta(weeks=off_weeks)
        prior = _actual(season_stats, _season_before(season), cfg,
                        min_minutes=MIN_PRIOR_MINUTES)[["PLAYER_ID", "act_fpts_pg"]]
        prior = prior.rename(columns={"act_fpts_pg": "prior_fpts_pg"})
        preseason_block = asof._preseason_block(
            season_stats, bio, season, 3, asof.DEFAULT_WEIGHTS, asof.DEFAULT_REG_MINUTES)

        for off in args.cutpoints:
            T = starts[season] + pd.Timedelta(days=off)
            feats = asof.asof_features(gl, season_stats, bio, season, T, half_lives=half_lives)
            boards = {
                "asof": asof.predict_board(models, feats, cfg, season),
                "frozen_t0": t0_board,
                "naive": _rank_board(naive_board(t0_board, gl_s, T, cfg)),
            }
            act_full = ros_actual_scored(gl_s, T, cfg)
            act_lh = ros_actual_scored(gl_s, T, cfg, end=league_end)
            for name, b in boards.items():
                m = pool_frame(b, prior, act_full, args.top_n)
                pools.setdefault((name, off), []).append(m.assign(season=season))
                m_lh = pool_frame(b, prior, act_lh, args.top_n)
                mae_rows.append({"season": season, "cutpoint": off, "model": name,
                                 "full": float(m["err"].abs().mean()),
                                 "league_horizon": float(m_lh["err"].abs().mean())})

            # 2. early-riser recall (the waiver question) at the +30d cutpoint.
            if off == 30:
                r = act_full[act_full["act_ros_gp"] >= RISER_MIN_ROS_GP].merge(prior, on="PLAYER_ID")
                risers = r[r["act_fpts_pg"] - r["prior_fpts_pg"] >= RISER_EDGE]
                top = boards["asof"].nsmallest(args.top_n, "rank")[["PLAYER_ID", "fpts_pg"]]
                hit = risers.merge(top, on="PLAYER_ID", how="left")
                captured = hit[hit["fpts_pg"].notna()]
                recall_rows.append({
                    "season": season, "n_risers": len(risers),
                    "recall@150": len(captured) / len(risers) if len(risers) else np.nan,
                    "mean_realized_delta": float((risers["act_fpts_pg"] - risers["prior_fpts_pg"]).mean()),
                    "mean_proj_delta_captured": float((captured["fpts_pg"] - captured["prior_fpts_pg"]).mean())
                    if len(captured) else np.nan,
                })
            print(f"[{season} +{off}d] pooled", flush=True)

        # 3. lead-time on the weekly grid (fit once per fold; cheap predicts per date).
        events = role_change_events(gl_s)
        dates = [starts[season] + pd.Timedelta(days=d)
                 for d in range(GRID_STEP_DAYS, GRID_MAX_DAYS + 1, GRID_STEP_DAYS)]
        grids = {
            "asof": _grid_mpg_asof(models, preseason_block, gl_s, dates, half_lives),
            "naive": _grid_mpg_naive(t0_board, gl_s, dates),
        }
        for name, grid in grids.items():
            lt = lead_time_table(events, grid, frac=LEAD_FRAC)
            det = lt[lt["detected"]]
            lead_rows.append({
                "season": season, "model": name, "n_events": len(events),
                "detected": float(lt["detected"].mean()) if len(lt) else np.nan,
                "median_lead_days": float(det["lead_days"].median()) if len(det) else np.nan,
                "iqr_lo": float(det["lead_days"].quantile(0.25)) if len(det) else np.nan,
                "iqr_hi": float(det["lead_days"].quantile(0.75)) if len(det) else np.nan,
            })
        print(f"[{season}] lead-time: {len(events)} confirmed role changes", flush=True)

    # ---- 1. in-season mover eval: pooled per-bucket tables + per-cutpoint floors ----
    print("\n=== EXP-019.1 in-season mover eval (pooled, per cutpoint) ===")
    for off in args.cutpoints:
        floor = None
        for name in ("asof", "naive", "frozen_t0"):
            m = pd.concat(pools[(name, off)], ignore_index=True)
            tbl = _bucket_table(m)
            if name == "asof":
                floor = floor_sim.selection_floor(m, seed=args.seed)
                tbl = tbl.merge(floor[["bucket", "floor_bias"]], on="bucket")
                tbl["reducible_gap"] = tbl["signed_bias"] - tbl["floor_bias"]
            print(f"\n[+{off}d] {name}")
            print(tbl.round(3).to_string(index=False))
        dir_rows = []
        for name in ("asof", "naive", "frozen_t0"):
            m = pd.concat(pools[(name, off)], ignore_index=True)
            dir_rows.append({
                "model": name, "pool_n": len(m),
                "level_MAE": m["err"].abs().mean(), "level_bias": m["err"].mean(),
                "delta_corr": m["proj_delta"].corr(m["actual_delta"]),
                "dir_sign_acc": (np.sign(m["proj_delta"]) == np.sign(m["actual_delta"])).mean(),
            })
        print(f"\n[+{off}d] directional")
        print(pd.DataFrame(dir_rows).round(3).to_string(index=False))

    # ---- 2. early-riser recall ----
    print("\n=== EXP-019.2 early-riser recall at +30d (asof top-150 ROS board) ===")
    R = pd.DataFrame(recall_rows)
    print(R.round(3).to_string(index=False))
    if len(R):
        n = R["n_risers"].sum()
        pooled = (R["recall@150"] * R["n_risers"]).sum() / n if n else np.nan
        print(f"pooled recall@150: {pooled:.3f} over {int(n)} realized in-season big risers")

    # ---- 3. lead-time ----
    print("\n=== EXP-019.3 lead-time (weekly grid, >=50% of realized MPG change) ===")
    L = pd.DataFrame(lead_rows)
    print(L.round(2).to_string(index=False))
    pooled = L.groupby("model")[["detected", "median_lead_days"]].mean()
    print("\nper-model means across seasons (positive lead = moved before confirmation):")
    print(pooled.round(2).to_string())

    # ---- 4. league-horizon sensitivity (amendment D1.3b) ----
    print("\n=== EXP-019.4 league-horizon sensitivity (ROS MAE, labels cut at league end) ===")
    M = pd.DataFrame(mae_rows)
    wide = M.pivot_table(index=["season", "cutpoint"], columns="model",
                         values=["full", "league_horizon"])
    print(wide.round(3).to_string())
    flips = 0
    for hz in ("full", "league_horizon"):
        w = M.pivot_table(index=["season", "cutpoint"], columns="model", values=hz)
        M_v = (w["asof"] < w["naive"]).rename(hz)
        flips = M_v if hz == "full" else (flips != M_v).sum()
    print(f"\n'asof beats naive' cells that flip under the league horizon: {int(flips)} "
          f"of {M[['season', 'cutpoint']].drop_duplicates().shape[0]}")


TREATED_MAX_RANK = 200  # treated-segment rows must be fantasy-relevant on the asof board


def _treated_ci(treated: pd.DataFrame, col_a: str, col_b: str,
                n_boot: int = 2000, seed: int = 0, alpha: float = 0.10) -> dict:
    """Player-clustered paired bootstrap CI on mean(|err_b|) − mean(|err_a|) over the
    treated rows (rule 8's noise guard; negative = the candidate is more accurate)."""
    m = treated.copy()
    m["_d"] = m[col_b].abs() - m[col_a].abs()
    g = m.groupby("PLAYER_ID")["_d"].agg(["sum", "count"])
    sums, counts = g["sum"].to_numpy(float), g["count"].to_numpy(float)
    k = len(g)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n_boot, k))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return {"n": int(len(m)), "delta_MAE": float(m["_d"].mean()),
            "ci_lo": float(np.quantile(boots, alpha / 2)),
            "ci_hi": float(np.quantile(boots, 1 - alpha / 2))}


def run_exp030(args, season_stats, bio, gl, cfg, params) -> None:
    """Step 16 (EXP-030): the OUT-redistribution layer vs the plain asof board.

    Judged on the **treated segment** — touched rows (redist_mpg > 0) inside the asof
    board's top-``TREATED_MAX_RANK`` — because redistribution is a no-op elsewhere and
    aggregates dilute. Also prints: the fitted absorption tiers (reality anchor vs the DFS
    folk numbers), the untouched-identity check, top-150 pool MAE context (asof / redist /
    naive), and the lead-time comparison on the weekly grid.
    """
    from fantasy_nba.models import absorption as ab
    from fantasy_nba.models import allocation as alloc
    from fantasy_nba.models import injuries as inj

    spells, join_stats = inj.build_spells(storage.read("injuries"), season_stats)
    print(f"[exp030] injury spells={len(spells):,} match_rate={join_stats['match_rate']:.3f}")
    team_logs = storage.read("team_game_logs")
    ptable = alloc.position_table(storage.read("team_rosters"))

    bounds_df = asof.season_date_bounds(gl)
    starts = bounds_df.set_index("SEASON")["start"]
    ends = bounds_df.set_index("SEASON")["end"]
    half_lives = asof.FROZEN_HALF_LIVES

    fitted_tables, treated_frames, mae_rows, lead_rows = [], [], [], []
    untouched_mismatches = 0
    for season in args.seasons:
        ty = _season_start(season)
        train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
        train_bio = bio[bio["SEASON"].map(_season_start) < ty]
        train_gl = gl[gl["SEASON"].map(_season_start) < ty]
        train_tl = team_logs[team_logs["SEASON"].map(_season_start) < ty]

        # Absorption weights + spell-duration medians: training data only (walk-forward).
        pos_map = alloc.pos_group_asof(ptable, season)
        ds = ab.absorption_dataset(train_gl, team_logs=train_tl, pos_map=pos_map)
        weights = ab.fit_absorption(ds)
        fitted_tables.append(ab.absorption_table(weights).assign(season=season))
        medians = ab.spell_duration_medians(spells[spells["start"] < starts[season]])
        print(f"[{season}] absorption fit on {weights['n_rows']:,} rows / "
              f"{weights['n_team_games']:,} team-games; medians={medians}", flush=True)

        panel = asof.build_asof_panel(train_ss, train_gl, train_bio, half_lives=half_lives)
        models = asof._fit_asof_models(panel, params, use_ewma=True)
        t0_board = project_models(season, season_stats, bio, cfg, seed=args.seed)["learned"]
        gl_s = gl[gl["SEASON"] == season]
        season_end = ends[season]

        for off in args.cutpoints:
            T = starts[season] + pd.Timedelta(days=off)
            feats = asof.asof_features(gl, season_stats, bio, season, T, half_lives=half_lives)
            base = asof.predict_board(models, feats, cfg, season)
            ev = ab.out_events_asof(spells, T, medians)
            redist = ab.redistribute_board(
                base, ev, ab.team_map_asof(gl_s, T), pos_map, weights, T, season_end, cfg)
            naive = _rank_board(naive_board(t0_board, gl_s, T, cfg))
            act = ros_actual_scored(gl_s, T, cfg)

            m = base[["PLAYER_ID", "rank", "fpts_pg"]].rename(columns={"fpts_pg": "fpts_asof"}).merge(
                redist[["PLAYER_ID", "fpts_pg", "redist_mpg"]].rename(columns={"fpts_pg": "fpts_redist"}),
                on="PLAYER_ID")
            unt = m[m["redist_mpg"] == 0]
            untouched_mismatches += int((unt["fpts_asof"] != unt["fpts_redist"]).sum())

            tr = (m[(m["redist_mpg"] > 0) & (m["rank"] <= TREATED_MAX_RANK)]
                  .merge(naive[["PLAYER_ID", "fpts_pg"]].rename(columns={"fpts_pg": "fpts_naive"}),
                         on="PLAYER_ID", how="left")
                  .merge(act[["PLAYER_ID", "act_fpts_pg", "act_ros_gp"]], on="PLAYER_ID", how="inner"))
            tr = tr[tr["act_ros_gp"] >= MIN_ROS_GP_TREATED]
            for name in ("asof", "redist", "naive"):
                tr[f"err_{name}"] = tr[f"fpts_{name}"] - tr["act_fpts_pg"]
            treated_frames.append(tr.assign(season=season, cutpoint=off))

            for name, b in (("asof", base), ("asof_redist", redist), ("naive", naive)):
                mae, n = pool_mae(b, ros_actual(gl_s, T), cfg, args.top_n)
                mae_rows.append({"season": season, "cutpoint": off, "model": name,
                                 "ros_MAE": mae, "n": n})
            print(f"[{season} +{off}d] treated n={len(tr)} (out tonight: {len(ev)})", flush=True)

        # Lead-time on the weekly grid: asof vs asof+redistribution.
        preseason_block = asof._preseason_block(
            season_stats, bio, season, 3, asof.DEFAULT_WEIGHTS, asof.DEFAULT_REG_MINUTES)
        events = role_change_events(gl_s)
        dates = [starts[season] + pd.Timedelta(days=d)
                 for d in range(GRID_STEP_DAYS, GRID_MAX_DAYS + 1, GRID_STEP_DAYS)]
        grid_asof = _grid_mpg_asof(models, preseason_block, gl_s, dates, half_lives)
        grids = {
            "asof": grid_asof,
            "asof_redist": ab.redistribute_mpg_grid(grid_asof, spells, medians, gl_s,
                                                    pos_map, weights, season_end),
        }
        for name, grid in grids.items():
            lt = lead_time_table(events, grid, frac=LEAD_FRAC)
            det = lt[lt["detected"]]
            lead_rows.append({
                "season": season, "model": name, "n_events": len(events),
                "detected": float(lt["detected"].mean()) if len(lt) else np.nan,
                "median_lead_days": float(det["lead_days"].median()) if len(det) else np.nan,
            })
        print(f"[{season}] lead-time: {len(events)} confirmed role changes", flush=True)

    with pd.option_context("display.width", 220, "display.max_columns", None):
        print("\n=== EXP-030 fitted absorption tiers (reality anchor: same-pos backup takes "
              "the plurality; DFS folk numbers ~12-15/3-5/2-3 min per 30 vacated) ===")
        ft = pd.concat(fitted_tables, ignore_index=True)
        pooled_ft = ft.groupby(["relation", "teammate_tier"], sort=False)[
            ["theta_min", "mpg_if_30_vacated", "theta_fga"]].mean().reset_index()
        print(pooled_ft.round(3).to_string(index=False))

        tr = pd.concat(treated_frames, ignore_index=True)
        print(f"\n=== Treated segment (touched rows, asof rank <= {TREATED_MAX_RANK}, "
              f"ROS gp >= {MIN_ROS_GP_TREATED}) ===")
        rows = []
        for (off), g in tr.groupby("cutpoint"):
            rows.append({"cutpoint": off, "n": len(g),
                         "MAE_asof": g["err_asof"].abs().mean(),
                         "MAE_redist": g["err_redist"].abs().mean(),
                         "MAE_naive": g["err_naive"].abs().mean(),
                         "bias_asof": g["err_asof"].mean(),
                         "bias_redist": g["err_redist"].mean(),
                         "mean_redist_mpg": g["redist_mpg"].mean()})
        rows.append({"cutpoint": "ALL", "n": len(tr),
                     "MAE_asof": tr["err_asof"].abs().mean(),
                     "MAE_redist": tr["err_redist"].abs().mean(),
                     "MAE_naive": tr["err_naive"].abs().mean(),
                     "bias_asof": tr["err_asof"].mean(),
                     "bias_redist": tr["err_redist"].mean(),
                     "mean_redist_mpg": tr["redist_mpg"].mean()})
        print(pd.DataFrame(rows).round(3).to_string(index=False))

        ci = _treated_ci(tr, "err_asof", "err_redist", seed=args.seed)
        print(f"\npaired player-clustered 90% CI on treated ΔMAE (redist − asof): "
              f"{ci['delta_MAE']:+.3f} [{ci['ci_lo']:+.3f}, {ci['ci_hi']:+.3f}] "
              f"(n={ci['n']}; negative = redistribution more accurate)")
        print(f"untouched-row identity mismatches (must be 0): {untouched_mismatches}")

        print("\n=== Top-150 pool ROS MAE context (aggregate dilutes the treated effect) ===")
        M = pd.DataFrame(mae_rows)
        print(M.pivot_table(index=["season", "cutpoint"], columns="model",
                            values="ros_MAE").round(3).to_string())

        print("\n=== Lead-time (weekly grid) ===")
        L = pd.DataFrame(lead_rows)
        print(L.round(2).to_string(index=False))
        print(L.groupby("model")[["detected", "median_lead_days"]].mean().round(2).to_string())

        print("\nGATE (EXP-030): treated ΔMAE < 0 with CI excluding 0, untouched mismatches "
              "= 0, lead-time/detection not worse (seeds {0,1,2}, rule 8).")


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-018 as-of-date gate.")
    parser.add_argument("--seasons", nargs="+",
                        default=["2022-23", "2023-24", "2024-25", "2025-26"])
    parser.add_argument("--cutpoints", nargs="+", type=int, default=list(GATE_OFFSETS))
    parser.add_argument("--top-n", type=int, default=150)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scoring", default=None)
    parser.add_argument("--ewma", action="store_true",
                        help="Add the fitted-half-life EWMA form block (Step 10 amendment).")
    parser.add_argument("--blend", action="store_true",
                        help="Add the naive-blend features (start from the K=20 shrinkage, "
                             "learn corrections).")
    parser.add_argument("--exp019", action="store_true",
                        help="Step 11 diagnostics: in-season mover eval + floors, early-riser "
                             "recall, lead-time (weekly grid), league-horizon sensitivity. "
                             "Runs the EWMA config with the frozen half-lives.")
    parser.add_argument("--fit-half-lives", action="store_true",
                        help="Re-fit EWMA half-lives per fold instead of the frozen constants "
                             "(rates→40, MPG→10 — identical in all four folds; slow).")
    parser.add_argument("--exp030", action="store_true",
                        help="Step 16 (EXP-030): the OUT-redistribution layer vs the plain "
                             "asof board — fitted absorption tiers, treated-segment ROS MAE "
                             "+ clustered CI, untouched-identity check, lead-time.")
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    gl = asof._with_dates(storage.read("player_game_logs"))
    cfg = load_scoring(args.scoring)
    params = {**asof.DEFAULT_LGBM_PARAMS, "random_state": args.seed}

    if args.exp019:
        run_exp019(args, season_stats, bio, gl, cfg, params)
        return
    if args.exp030:
        run_exp030(args, season_stats, bio, gl, cfg, params)
        return

    bounds = asof.season_date_bounds(gl).set_index("SEASON")["start"]
    rows = []
    for season in args.seasons:
        ty = _season_start(season)
        train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
        train_bio = bio[bio["SEASON"].map(_season_start) < ty]
        train_gl = gl[gl["SEASON"].map(_season_start) < ty]

        # fit once per season fold; half-lives default to the frozen constants (they fit
        # identically in all four folds — addendum 2026-07-09 item 3) unless a re-check
        # is requested via --fit-half-lives (then fit on the training slice only).
        half_lives = None
        if args.ewma:
            half_lives = asof.fit_half_lives(train_gl) if args.fit_half_lives else asof.FROZEN_HALF_LIVES
            print(f"[{season}] half-lives ({'fitted' if args.fit_half_lives else 'frozen'}): "
                  f"{half_lives}", flush=True)
        panel = asof.build_asof_panel(train_ss, train_gl, train_bio, half_lives=half_lives,
                                      use_blend=args.blend)
        models = asof._fit_asof_models(panel, params, use_ewma=args.ewma, use_blend=args.blend)
        t0_board = project_models(season, season_stats, bio, cfg, seed=args.seed)["learned"]
        gl_s = gl[gl["SEASON"] == season]

        for off in args.cutpoints:
            T = bounds[season] + pd.Timedelta(days=off)
            actual = ros_actual(gl_s, T)
            feats = asof.asof_features(gl, season_stats, bio, season, T, half_lives=half_lives,
                                       use_blend=args.blend)
            boards = {
                "asof": asof.predict_board(models, feats, cfg, season),
                "frozen_t0": t0_board,
                "naive": naive_board(t0_board, gl_s, T, cfg),
            }
            for name, b in boards.items():
                mae, n = pool_mae(b, actual, cfg, args.top_n)
                rows.append({"season": season, "cutpoint": off, "model": name,
                             "ros_MAE": mae, "n": n})
            print(f"[{season} +{off}d] " + "  ".join(
                f"{r['model']} {r['ros_MAE']:.3f}" for r in rows[-3:]), flush=True)

    R = pd.DataFrame(rows)
    print("\n=== ROS level MAE by (season, cutpoint) ===")
    print(R.pivot_table(index=["season", "cutpoint"], columns="model",
                        values="ros_MAE").round(3).to_string())

    wide = R.pivot_table(index=["season", "cutpoint"], columns="model", values="ros_MAE")
    wide["beats_frozen"] = wide["asof"] < wide["frozen_t0"]
    wide["beats_naive"] = wide["asof"] < wide["naive"]
    wide["beats_both"] = wide["beats_frozen"] & wide["beats_naive"]
    per_season = wide.groupby("season")["beats_both"].sum()
    print("\ncutpoints where asof beats BOTH, per season (gate: >=2 of 3, in 3/4 seasons):")
    print(per_season.to_string())
    print("\nGATE:", bool((per_season >= 2).sum() >= 3))


if __name__ == "__main__":
    main()
