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

from fantasy_nba.data import storage
from fantasy_nba.models import floor_sim
from fantasy_nba.models.backtest import VARIANT_SPECS
from fantasy_nba.models.eval_movers import bootstrap_bias_delta_ci, run_mover_eval
from fantasy_nba.scoring import load_scoring

BUCKET_ORDER = ["big faller", "faller", "stable", "riser", "big riser"]


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
