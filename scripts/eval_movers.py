"""Mover-segmented, draftable-pool eval (ROADMAP Stage 7.0 / EXP-006, extended Steps 1–5).

Quantifies the models' bias on players whose production *level* changed year over year — the
"risers & fallers" the ranking backtest is blind to — plus the Stage-7 diagnostics:
predicted-Δ calibration (Step 1), the selection floor (Step 2, --floor), the minutes/rates
oracle decomposition (Step 3, --oracles), A/B variants by registry name (Steps 4–5,
--variants), a paired bootstrap CI between two models (--ci), and the seed-stability
protocol (--seed).

Examples
--------
    # metric of record:
    python scripts/eval_movers.py --seasons 2022-23 2023-24 2024-25 2025-26
    # Phase-0 diagnostics (Steps 2–3):
    python scripts/eval_movers.py --seasons 2022-23 2023-24 2024-25 2025-26 --floor --oracles
    # Step-4 A/B with a noise guard on the verdict:
    python scripts/eval_movers.py --variants learned_recency learned_recency_s5 \
        --ci learned_recency learned_recency_s5 --seed 0
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

import numpy as np

from fantasy_nba.data import storage
from fantasy_nba.models import floor_sim
from fantasy_nba.models.backtest import VARIANT_SPECS
from fantasy_nba.models.eval_movers import bootstrap_bias_delta_ci, range_coverage, run_mover_eval
from fantasy_nba.scoring import load_scoring

BUCKET_ORDER = ["big faller", "faller", "stable", "riser", "big riser"]
SAFE_LAMBDA = 0.5  # rank_board's default safe-stance downside penalty


def _needs_game_logs(variant_names: list[str]) -> bool:
    return any(
        VARIANT_SPECS[v].get("use_recency") or VARIANT_SPECS[v].get("use_trade_split")
        for v in variant_names
    )


def _needs_rosters(variant_names: list[str]) -> bool:
    return any(VARIANT_SPECS[v].get("minutes_mode") == "allocation" for v in variant_names)


def _needs_injuries(variant_names: list[str]) -> bool:
    return any(VARIANT_SPECS[v].get("use_injuries") for v in variant_names)


def _needs_vacated(variant_names: list[str]) -> bool:
    return any(VARIANT_SPECS[v].get("use_vacated") for v in variant_names)


def _needs_breakout(variant_names: list[str]) -> bool:
    return any(VARIANT_SPECS[v].get("use_breakout") for v in variant_names)


def _needs_coach(variant_names: list[str]) -> bool:
    return any(VARIANT_SPECS[v].get("use_coach") for v in variant_names)


def _needs_preseason(variant_names: list[str]) -> bool:
    return any(VARIANT_SPECS[v].get("use_preseason") for v in variant_names)


def _pooled(per_bucket: pd.DataFrame, value_cols: list[str]) -> pd.DataFrame:
    """n-weighted mean of per-bucket metrics across seasons, ordered faller -> riser."""
    pooled = (
        per_bucket.dropna(subset=["n"])
        .assign(w=lambda d: d["n"])
        .groupby(["model", "bucket"], observed=False)
        .apply(
            lambda g: pd.Series(
                {"n": g["n"].sum(), **{c: (g[c] * g["w"]).sum() / g["w"].sum() for c in value_cols}}
            ),
            include_groups=False,
        )
        .reset_index()
    )
    pooled["bucket"] = pd.Categorical(pooled["bucket"], categories=BUCKET_ORDER, ordered=True)
    return pooled.sort_values(["model", "bucket"])


def _coverage_delta_ci(rows_base: pd.DataFrame, rows_new: pd.DataFrame, bucket: str | None = None,
                       n_boot: int = 2000, seed: int = 0, alpha: float = 0.10) -> dict:
    """Player-clustered paired bootstrap CI on the coverage delta (new − base) — rule 8's
    noise guard applied to a proportion instead of a bias."""
    a = rows_base[["PLAYER_ID", "season", "bucket", "covered"]].rename(columns={"covered": "cov_a"})
    b = rows_new[["PLAYER_ID", "season", "covered"]].rename(columns={"covered": "cov_b"})
    m = a.merge(b, on=["PLAYER_ID", "season"], how="inner")
    if bucket is not None:
        m = m[m["bucket"] == bucket]
    m["_d"] = m["cov_b"].astype(float) - m["cov_a"].astype(float)
    g = m.groupby("PLAYER_ID")["_d"].agg(["sum", "count"])
    sums, counts = g["sum"].to_numpy(float), g["count"].to_numpy(float)
    k = len(g)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n_boot, k))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return {
        "bucket": bucket or "ALL", "n": int(len(m)), "delta": float(m["_d"].mean()),
        "ci_lo": float(np.quantile(boots, alpha / 2)),
        "ci_hi": float(np.quantile(boots, 1 - alpha / 2)),
    }


def _ranges_section(args, season_stats, bio, cfg, learned_pools: list[pd.DataFrame]) -> None:
    """Step 14 / EXP-021: learned ranges (empirical residual CDF) vs the SD_PG=9 baseline.

    Both spread models share the adopted (age × chronic) GP pools (EXP-015 / 7.3b), so the
    only difference under test is the per-game spread. Prints the coverage-per-mover-bucket
    scoreboard (pooled), per-season top-100 board coverage + safe/ceiling Spearman, and the
    player-clustered CI on the coverage delta.
    """
    from fantasy_nba.models import uncertainty as unc
    from fantasy_nba.models._core import _season_start
    from fantasy_nba.models.backtest import _actual
    from fantasy_nba.models.learned import DEFAULT_LGBM_PARAMS, project_learned

    from fantasy_nba.models import injuries as inj_mod

    spells = chronic_table = None
    if storage.exists("injuries"):
        spells, _ = inj_mod.build_spells(storage.read("injuries"), season_stats)
        chronic_table = inj_mod.chronic_flag_table(
            spells, sorted(season_stats["SEASON"].unique(), key=_season_start))
    else:
        print("[ranges] no injuries pull cached — GP pools fall back to age-only buckets")

    seed = args.seed if args.seed is not None else DEFAULT_LGBM_PARAMS.get("random_state", 0)
    params = {**DEFAULT_LGBM_PARAMS, "random_state": seed}
    board_cache: dict[str, pd.DataFrame] = {}

    def _board(season: str) -> pd.DataFrame:
        if season not in board_cache:
            ty = _season_start(season)
            tr_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
            tr_bio = bio[bio["SEASON"].map(_season_start) < ty]
            board_cache[season] = project_learned(tr_ss, tr_bio, season, cfg=cfg, params=params)
        return board_cache[season]

    SPREADS = ("sd_pg9", "resid_cdf", "resid_cdf_cal")
    cov_rows = {k: [] for k in SPREADS}          # per-player covered flags (for the CI)
    cov_tables = {k: [] for k in SPREADS}        # per-season per-bucket tables
    board_metrics = []
    for season, pool_m in zip(args.seasons, learned_pools):
        ty = _season_start(season)
        board = _board(season).copy()
        resid = unc.residual_pool(season_stats, bio, season, cfg, pool_top_n=args.top_n,
                                  params=params, seed=seed, board_cache=board_cache)
        scale, scale_table = unc.calibrate_resid_scale(
            season_stats, bio, season, cfg, resid=resid, top_n=args.top_n,
            injury_profile=chronic_table, spells=spells,
            params=params, seed=seed, board_cache=board_cache,
        )
        if spells is not None:
            flags = inj_mod.injury_features(spells, f"{ty}-10-01")[["PLAYER_ID", "inj_chronic_flag"]]
            board = board.merge(flags, on="PLAYER_ID", how="left")
            board["inj_chronic_flag"] = board["inj_chronic_flag"].fillna(0).astype(int)
        tr_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
        tr_bio = bio[bio["SEASON"].map(_season_start) < ty]
        gp_pool = unc.build_gp_pool(tr_ss, tr_bio, max_start_year=ty, injury_profile=chronic_table)
        actual = _actual(season_stats, season, cfg, min_minutes=0.0)
        qframe = unc.pg_quantile_frame(board, resid)
        qframe_cal = unc.pg_quantile_frame(board, resid * scale)
        print(f"[ranges] {season}: resid pool n={len(resid)}, "
              f"resid q25/50/75/90 = {np.round(np.quantile(resid, (0.25, 0.5, 0.75, 0.9)), 2)}, "
              f"calibrated scale = {scale} "
              f"(walk-forward cov by scale: {dict(zip(scale_table['scale'], scale_table['coverage'].round(3)))})")

        for kind, pq in (("sd_pg9", None), ("resid_cdf", qframe), ("resid_cdf_cal", qframe_cal)):
            sim = unc.simulate_ranges(board, gp_pool, pg_quantiles=pq, seed=0)
            table, rows = range_coverage(pool_m, sim, actual, return_rows=True)
            table.insert(0, "season", season)
            rows = rows.copy()
            rows["season"] = season
            cov_tables[kind].append(table)
            cov_rows[kind].append(rows)

            top = sim.nsmallest(100, "rank").merge(
                actual[["PLAYER_ID", "act_fpts_total"]], on="PLAYER_ID", how="inner")
            safe = top["fpts_median"] - SAFE_LAMBDA * (top["fpts_median"] - top["fpts_p10"])
            board_metrics.append({
                "season": season, "spread": kind, "n": len(top),
                "coverage_top100": float(top["act_fpts_total"].between(top["fpts_p10"], top["fpts_p90"]).mean()),
                "safe_spearman": float(safe.corr(top["act_fpts_total"], method="spearman")),
                "ceiling_spearman": float(top["fpts_p90"].corr(top["act_fpts_total"], method="spearman")),
                "median_spearman": float(top["fpts_median"].corr(top["act_fpts_total"], method="spearman")),
            })

    print("\n" + "#" * 78)
    print("# RANGES (Step 14 / EXP-021) — learned resid-CDF spread vs SD_PG=9, shared GP pools")
    print("#" * 78)
    print("\n=== Coverage per actual-Δ bucket (learned pool, pooled; target: big riser ≥ 0.70, ALL in [0.78, 0.88]) ===")
    pooled = []
    for kind in SPREADS:
        t = pd.concat(cov_tables[kind], ignore_index=True)
        p = (t.assign(covered_n=t["n"] * t["coverage"])
              .groupby("bucket", observed=False)[["n", "covered_n"]].sum().reset_index())
        p["coverage"] = p["covered_n"] / p["n"].replace(0, np.nan)
        p.insert(0, "spread", kind)
        order = BUCKET_ORDER + ["ALL"]
        p["bucket"] = pd.Categorical(p["bucket"], categories=order, ordered=True)
        pooled.append(p.sort_values("bucket")[["spread", "bucket", "n", "coverage"]])
    print(pd.concat(pooled, ignore_index=True).round(3).to_string(index=False))

    print("\n=== Top-100 board: coverage + safe/ceiling/median Spearman (per season) ===")
    bm = pd.DataFrame(board_metrics)
    print(bm.round(3).to_string(index=False))
    print("pooled means by spread:")
    print(bm.groupby("spread")[["coverage_top100", "safe_spearman", "ceiling_spearman",
                                "median_spearman"]].mean().round(4).to_string())

    rows_base = pd.concat(cov_rows["sd_pg9"], ignore_index=True)
    for cand in ("resid_cdf", "resid_cdf_cal"):
        rows_new = pd.concat(cov_rows[cand], ignore_index=True)
        ci = pd.DataFrame([
            _coverage_delta_ci(rows_base, rows_new),
            _coverage_delta_ci(rows_base, rows_new, bucket="big riser"),
            _coverage_delta_ci(rows_base, rows_new, bucket="riser"),
        ])
        print(f"\n=== Paired player-clustered 90% CI: coverage delta ({cand} − sd_pg9) ===")
        print(ci.round(3).to_string(index=False))
    print("GATE (EXP-021, judged on resid_cdf_cal): ALL coverage in [0.78, 0.88] AND big-riser "
          "coverage improves vs sd_pg9 AND safe/ceiling Spearman not worse (seeds {0,1,2}, rule 8).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mover-segmented draftable-pool eval.")
    parser.add_argument("--seasons", nargs="+", default=["2022-23", "2023-24", "2024-25", "2025-26"])
    parser.add_argument("--top-n", type=int, default=150, help="Draftable pool size.")
    parser.add_argument("--scoring", default=None)
    parser.add_argument("--variants", nargs="*", default=[], choices=sorted(VARIANT_SPECS),
                        metavar="NAME",
                        help=f"Learned-model A/B variants to add: {', '.join(sorted(VARIANT_SPECS))}")
    parser.add_argument("--recency", action="store_true",
                        help="Back-compat alias for --variants learned_recency learned_rc "
                             "(the EXP-008b/009b pair).")
    parser.add_argument("--actual-pool", action="store_true",
                        help="Also print the recall view (critique §3.2): the three tables "
                             "scored on the realized top-N instead of each model's own pool, "
                             "plus each model's recall of the realized top-N. Model-pool bias "
                             "understates riser bias because missed sleepers are invisible.")
    parser.add_argument("--floor", action="store_true",
                        help="Step 2: print the selection-floor table (learned model, pooled) "
                             "at sigma scales 0.75/1.0/1.25, and the derived reducible gap.")
    parser.add_argument("--oracles", action="store_true",
                        help="Step 3: add oracle_minutes/oracle_rates rows built from the "
                             "learned board (EXP-011b decomposition).")
    parser.add_argument("--ci", nargs=2, metavar=("MODEL_A", "MODEL_B"), action="append",
                        help="Paired bootstrap 90%% CI on per-bucket bias delta (B − A), pooled "
                             "across seasons — the noise guard for adopt gates. Repeatable "
                             "(one pair per flag) so a single run covers several candidates.")
    parser.add_argument("--seed", type=int, default=None,
                        help="Override LightGBM random_state for all learned models. The "
                             "seed-stability protocol: run at 0/1/2 and average before judging "
                             "a gate.")
    parser.add_argument("--ranges", action="store_true",
                        help="Step 14 (EXP-021): add the coverage-per-mover-bucket scoreboard — "
                             "learned ranges (walk-forward empirical residual CDF per-game "
                             "spread, EXP-013c note) vs the SD_PG=9 baseline, both on the "
                             "adopted (age × chronic) GP pools, plus top-100 safe/ceiling "
                             "Spearman and a player-clustered CI on the coverage delta.")
    args = parser.parse_args()

    variants = list(dict.fromkeys(args.variants + (["learned_recency", "learned_rc"] if args.recency else [])))

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    game_logs = storage.read("player_game_logs") if _needs_game_logs(variants) else None
    rosters = storage.read("team_rosters") if _needs_rosters(variants) else None
    cfg = load_scoring(args.scoring)

    injuries = None
    if _needs_injuries(variants):
        from fantasy_nba.models import injuries as inj_mod

        injuries, join_stats = inj_mod.build_spells(storage.read("injuries"), season_stats)
        print(f"[injuries] spells={len(injuries):,} match_rate={join_stats['match_rate']:.3f}")

    vacated_table = transactions = None
    if _needs_vacated(variants):
        from fantasy_nba.models import rosters as rosters_mod

        transactions = storage.read("transactions")
        vacated_table = rosters_mod.vacated_feature_table(
            season_stats, transactions, storage.read("team_rosters"),
        )
        print(f"[vacated] table rows={len(vacated_table):,} over "
              f"{vacated_table['SEASON'].nunique()} seasons (honest Oct-1 maps)")

    breakout_table = None
    if _needs_breakout(variants):
        from fantasy_nba.models import breakout as brk_mod

        breakout_table = brk_mod.breakout_feature_table(season_stats, bio, cfg)
        print(f"[breakout] table rows={len(breakout_table):,} over "
              f"{breakout_table['SEASON'].nunique()} seasons")

    coach_table = None
    if _needs_coach(variants):
        from fantasy_nba.models import coaches as coa_mod

        coach_table = coa_mod.coach_feature_table(
            season_stats, storage.read("transactions"), bio,
        )
        n_new = int(coach_table["new_coach"].sum())
        print(f"[coach] table rows={len(coach_table):,} over "
              f"{coach_table['SEASON'].nunique()} seasons ({n_new:,} new-coach player-rows)")

    preseason_table = None
    if _needs_preseason(variants):
        from fantasy_nba.models import preseason as pre_mod

        preseason_table = pre_mod.preseason_feature_table(
            storage.read("preseason_game_logs"), season_stats,
        )
        print(f"[preseason] table rows={len(preseason_table):,} over "
              f"{preseason_table['SEASON'].nunique()} seasons")

    def _run_view(pool_kind: str):
        per_bucket_frames, dir_frames, pred_frames = [], [], []
        pools_by_model: dict[str, list[pd.DataFrame]] = {}
        for season in args.seasons:
            per_bucket, directional, per_pred, pools = run_mover_eval(
                season, season_stats, bio, cfg=cfg, pool_top_n=args.top_n,
                game_logs=game_logs, variants=variants, oracles=args.oracles,
                seed=args.seed, return_pools=True, pool=pool_kind, rosters=rosters,
                injuries=injuries, vacated_table=vacated_table, transactions=transactions,
                breakout_table=breakout_table, coach_table=coach_table,
                preseason_table=preseason_table,
            )
            for frame in (per_bucket, directional, per_pred):
                frame.insert(0, "season", season)
            per_bucket_frames.append(per_bucket)
            dir_frames.append(directional)
            pred_frames.append(per_pred)
            for name, pool in pools.items():
                pool = pool.copy()
                pool["season"] = season
                pools_by_model.setdefault(name, []).append(pool)
        return (
            pd.concat(per_bucket_frames, ignore_index=True),
            pd.concat(dir_frames, ignore_index=True),
            pd.concat(pred_frames, ignore_index=True),
            pools_by_model,
        )

    per_bucket, directional, per_pred, pools_by_model = _run_view("model")

    with pd.option_context("display.width", 220, "display.max_columns", None):
        print("\n=== Directional capture (per model, per season) ===")
        print(directional.round(3).to_string(index=False))

        print("\n=== Per-bucket level error & signed bias (actual-Δ buckets, pooled) ===")
        pooled = _pooled(per_bucket, ["level_MAE", "signed_bias", "mean_actual_delta", "mean_proj_delta"])
        print(pooled.round(3).to_string(index=False))

        print("\n=== Predicted-Δ calibration (selection-free; calib_gap -> 0 is perfect) ===")
        pooled_pred = _pooled(per_pred, ["mean_proj_delta", "mean_actual_delta", "calib_gap", "level_MAE"])
        print(pooled_pred.round(3).to_string(index=False))

        if args.floor:
            pooled_learned = pd.concat(pools_by_model["learned"], ignore_index=True)
            floors = floor_sim.floor_table(pooled_learned)
            print("\n=== Selection floor (learned, pooled; sigma sensitivity band) ===")
            print(floors.round(3).to_string(index=False))
            measured = pooled[pooled["model"] == "learned"][["bucket", "signed_bias"]]
            gap = floor_sim.reducible_gap(measured, floors)
            print("\n=== Reducible gap (measured bias − floor @ sigma 1.0) ===")
            print(gap.round(3).to_string(index=False))

        for a, b in (args.ci or []):
            if a not in pools_by_model or b not in pools_by_model:
                raise SystemExit(f"--ci models must be in the run; have {sorted(pools_by_model)}")
            ci = bootstrap_bias_delta_ci(
                pd.concat(pools_by_model[a], ignore_index=True),
                pd.concat(pools_by_model[b], ignore_index=True),
                on=("PLAYER_ID", "season"),
                cluster="PLAYER_ID",  # rows repeat players across seasons (rule 11)
            )
            print(f"\n=== Paired bootstrap 90% CI (player-clustered): bias delta ({b} − {a}) ===")
            print(ci.round(3).to_string(index=False))
            print("(CI straddling 0 => difference unresolved at this sample size; see plan rules.)")

        if args.ranges:
            _ranges_section(args, season_stats, bio, cfg, pools_by_model["learned"])

        if args.actual_pool:
            ap_bucket, ap_dir, ap_pred, _ = _run_view("actual")
            print("\n" + "#" * 78)
            print("# RECALL VIEW — tables scored on the REALIZED top-N (critique §3.2)")
            print("#" * 78)
            recall = ap_dir[["model", "recall"]].drop_duplicates("model")
            print("\n=== Model recall of the realized top-N (fraction pooled) ===")
            print(recall.round(3).to_string(index=False))
            print("\n=== Per-bucket signed bias on the realized pool (pooled) ===")
            ap_pooled = _pooled(ap_bucket, ["level_MAE", "signed_bias", "mean_actual_delta", "mean_proj_delta"])
            print(ap_pooled.round(3).to_string(index=False))
            print("\n=== Predicted-Δ calibration on the realized pool (pooled) ===")
            ap_pooled_pred = _pooled(ap_pred, ["mean_proj_delta", "mean_actual_delta", "calib_gap", "level_MAE"])
            print(ap_pooled_pred.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
