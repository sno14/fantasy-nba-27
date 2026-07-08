"""Step 5d (EXP-013d): walk-forward LightGBM hyperparameter tuner — nested selection.

`DEFAULT_LGBM_PARAMS` were set once in EXP-007 and never tuned. This script grids over
`num_leaves × min_child_samples × learning_rate`, with `n_estimators` chosen by early
stopping on the **last training season** of each fold (never the eval season).

**Nested selection (implementation-plan rule 10b, design-critique §3.1):** the grid is
scored ONLY on folds targeting seasons ≤ 2021-22 (`--tune-seasons`); the winning combo is
then confirmed **once** on the standard 4-season eval window — this script prints the exact
confirm commands, it does not run them. Never grid-search directly on the verdict seasons.

Selection metric: pooled (n-weighted) top-N-pool level MAE across the tuning folds, with
riser-bucket signed bias reported alongside (the EXP-013d gate is "MAE improves AND riser
bias not worse"). The final refit per combo goes through `project_learned` itself, so the
tuned configuration is exactly what production would run.

Usage:
    python scripts/tune_learned.py                       # full grid (27 combos, slow — ~1h)
    python scripts/tune_learned.py --quick               # coarse 8-combo grid first pass
    python scripts/tune_learned.py --seed 1              # rule-8 seed stability re-run
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models._core import DEFAULT_REG_MINUTES, DEFAULT_WEIGHTS, _season_start
from fantasy_nba.models.backtest import _actual
from fantasy_nba.models.eval_movers import _season_before, pool_frame
from fantasy_nba.models.learned import (
    BASE_FEATURES,
    DEFAULT_LGBM_PARAMS,
    TARGETS,
    _features_for,
    _labels,
    project_learned,
)
from fantasy_nba.scoring import load_scoring

FULL_GRID = {
    "num_leaves": [15, 31, 63],
    "min_child_samples": [10, 30, 60],
    "learning_rate": [0.03, 0.05, 0.10],
}
# --quick: the corners + center — enough to see whether the surface is flat before paying
# for the full grid.
QUICK_GRID = {
    "num_leaves": [15, 63],
    "min_child_samples": [10, 60],
    "learning_rate": [0.03, 0.10],
}
MAX_ESTIMATORS = 2000
EARLY_STOP_ROUNDS = 50


def season_tagged_panel(train_ss: pd.DataFrame, train_bio: pd.DataFrame) -> pd.DataFrame:
    """`learned.build_panel` with a `label_season` column — the early-stopping split key.

    Mirrors build_panel exactly (base features only: tuning runs on the plain `learned`
    configuration, the current default model).
    """
    seasons = sorted(train_ss["SEASON"].unique(), key=_season_start)
    frames = []
    for s in seasons:
        prior = train_ss[train_ss["SEASON"].map(_season_start) < _season_start(s)]
        if prior["SEASON"].nunique() < 2:
            continue
        prior_bio = train_bio[train_bio["SEASON"].map(_season_start) < _season_start(s)]
        feats = _features_for(
            prior, prior_bio, s, False, 3, DEFAULT_WEIGHTS, DEFAULT_REG_MINUTES
        )
        labels = _labels(train_ss, s, 200.0)
        merged = feats.merge(labels, on="PLAYER_ID", how="inner")
        if not merged.empty:
            merged["label_season"] = s
            frames.append(merged)
    if not frames:
        raise ValueError("Empty tuning panel — need at least a few seasons of history.")
    return pd.concat(frames, ignore_index=True)


def early_stopped_n_estimators(panel: pd.DataFrame, combo: dict, seed: int) -> int:
    """Median best-iteration over all decomposition targets, validated on the fold's last
    training season (never the eval season)."""
    import lightgbm as lgb
    from lightgbm import LGBMRegressor

    last = max(panel["label_season"], key=_season_start)
    tr, va = panel[panel["label_season"] != last], panel[panel["label_season"] == last]
    if tr.empty or va.empty:
        raise ValueError(f"Degenerate early-stopping split (last={last}).")
    params = {**DEFAULT_LGBM_PARAMS, **combo,
              "n_estimators": MAX_ESTIMATORS, "random_state": seed}
    best_iters = []
    for target in TARGETS:
        model = LGBMRegressor(**params)
        model.fit(
            tr[BASE_FEATURES], tr[target],
            eval_set=[(va[BASE_FEATURES], va[target])],
            callbacks=[lgb.early_stopping(EARLY_STOP_ROUNDS, verbose=False)],
        )
        best_iters.append(model.best_iteration_ or MAX_ESTIMATORS)
    return int(np.median(best_iters))


def score_fold(
    target_season: str,
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    cfg,
    params: dict,
    pool_top_n: int,
) -> dict:
    """Project one fold with `project_learned(params=…)` (the production path) and score
    its own top-N pool: level MAE + riser/big-riser signed bias."""
    ty = _season_start(target_season)
    train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
    train_bio = bio[bio["SEASON"].map(_season_start) < ty]
    proj = project_learned(train_ss, train_bio, target_season, cfg=cfg, params=params)

    actual = _actual(season_stats, target_season, cfg, min_minutes=0.0)[
        ["PLAYER_ID", "act_fpts_pg"]
    ]
    prior = _actual(season_stats, _season_before(target_season), cfg, min_minutes=500.0)[
        ["PLAYER_ID", "act_fpts_pg"]
    ].rename(columns={"act_fpts_pg": "prior_fpts_pg"})
    m = pool_frame(proj, prior, actual, pool_top_n)
    riser = m[m["bucket"].isin(["riser", "big riser"])]
    return {
        "n": len(m),
        "level_MAE": m["err"].abs().mean(),
        "riser_bias": riser["err"].mean() if not riser.empty else np.nan,
        "n_riser": len(riser),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-013d nested walk-forward LGBM tuner.")
    parser.add_argument("--tune-seasons", nargs="+",
                        default=["2017-18", "2018-19", "2019-20", "2020-21", "2021-22"],
                        help="Grid-scored folds. Rule 10b: keep ≤ 2021-22 — never the "
                             "standard eval window.")
    parser.add_argument("--top-n", type=int, default=150)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scoring", default=None)
    parser.add_argument("--quick", action="store_true", help="Coarse 8-combo corner grid.")
    args = parser.parse_args()

    offenders = [s for s in args.tune_seasons if _season_start(s) > _season_start("2021-22")]
    if offenders:
        raise SystemExit(
            f"Tuning folds {offenders} overlap the standard eval window (> 2021-22) — "
            "that breaks nested selection (rule 10b). Refusing to run."
        )

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(args.scoring)

    grid = QUICK_GRID if args.quick else FULL_GRID
    combos = [dict(zip(grid, vals)) for vals in itertools.product(*grid.values())]
    print(f"Grid: {len(combos)} combos × {len(args.tune_seasons)} folds "
          f"(seed {args.seed}, pool top-{args.top_n})")

    # Early-stopping panels are combo-independent per fold — build once each.
    panels: dict[str, pd.DataFrame] = {}
    for s in args.tune_seasons:
        ty = _season_start(s)
        train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
        train_bio = bio[bio["SEASON"].map(_season_start) < ty]
        panels[s] = season_tagged_panel(train_ss, train_bio)

    rows = []
    for i, combo in enumerate(combos, 1):
        t0 = time.time()
        fold_metrics = []
        for s in args.tune_seasons:
            n_est = early_stopped_n_estimators(panels[s], combo, args.seed)
            params = {**DEFAULT_LGBM_PARAMS, **combo,
                      "n_estimators": n_est, "random_state": args.seed}
            fm = score_fold(s, season_stats, bio, cfg, params, args.top_n)
            fm["season"], fm["n_estimators"] = s, n_est
            fold_metrics.append(fm)
        f = pd.DataFrame(fold_metrics)
        rows.append({
            **combo,
            "med_n_estimators": int(f["n_estimators"].median()),
            "pooled_MAE": float(np.average(f["level_MAE"], weights=f["n"])),
            "pooled_riser_bias": float(np.average(f["riser_bias"], weights=f["n_riser"])),
        })
        print(f"[{i:>2}/{len(combos)}] {combo} -> MAE {rows[-1]['pooled_MAE']:.3f} "
              f"riser_bias {rows[-1]['pooled_riser_bias']:.3f} "
              f"n_est~{rows[-1]['med_n_estimators']} ({time.time()-t0:.0f}s)")

    results = pd.DataFrame(rows).sort_values("pooled_MAE").reset_index(drop=True)
    print("\n=== Grid results (tuning folds only — NOT the verdict window) ===")
    print(results.round(4).to_string(index=False))

    # Reference: the current defaults, scored the same way.
    ref = []
    for s in args.tune_seasons:
        fm = score_fold(s, season_stats, bio, cfg,
                        {**DEFAULT_LGBM_PARAMS, "random_state": args.seed}, args.top_n)
        ref.append(fm)
    r = pd.DataFrame(ref)
    print(f"\nCurrent DEFAULT_LGBM_PARAMS on the same folds: "
          f"MAE {np.average(r['level_MAE'], weights=r['n']):.3f}  "
          f"riser_bias {np.average(r['riser_bias'], weights=r['n_riser']):.3f}")

    w = results.iloc[0]
    winner = {k: w[k] for k in grid} | {"n_estimators": int(w["med_n_estimators"])}
    print(f"\nWinner (by pooled tuning-fold MAE): {winner}")
    print("\nNext (rule 10b — confirm ONCE on the standard window, seeds 0/1/2):")
    print("  1. Add a registry variant in backtest.VARIANT_SPECS, e.g.")
    print(f"     \"learned_tuned\": {{\"params\": {{**DEFAULT_LGBM_PARAMS, "
          f"**{ {k: (float(v) if k == 'learning_rate' else int(v)) for k, v in winner.items()} } }}}}")
    print("  2. python scripts/eval_movers.py --variants learned_tuned --ci learned learned_tuned"
          " --seed 0   (then 1, 2)")
    print("  3. Gate: pooled level MAE improves AND riser bias not worse (rule 8). "
          "Only then update DEFAULT_LGBM_PARAMS.")


if __name__ == "__main__":
    main()
