"""Backtest harness: which model actually helps for *drafting*?

Projects a past season using **only** data from prior seasons (aging curves and the GP curve
are refit on the training years, so there's no leakage), then scores each model against what
actually happened.

Evaluation is restricted to the **draft pool**: each model's own top-N players by projected
season fantasy total (default N=100). This matters — MAE averaged over all ~330 rotation
players rewards accuracy on bench guys nobody drafts and hid that the fancy models don't beat
the baseline where it counts. The headline metric is **Spearman rank correlation** of projected
vs actual fantasy totals within that pool (drafting is a ranking problem), alongside MAE on
minutes, per-game points, and season totals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame
from ._core import COUNTING, _season_start
from .aging import build_aging_curves
from .baseline import project_baseline
from .context import target_team_map
from .durability import build_gp_age_curve
from .learned import DEFAULT_LGBM_PARAMS, project_learned
from .minutes import build_minutes_age_curve
from .projection import project_v2


def _actual(season_stats: pd.DataFrame, season: str, cfg: ScoringConfig, min_minutes: float) -> pd.DataFrame:
    """Actual per-game fantasy points for players who logged >= min_minutes in ``season``."""
    cols = ["GP", "MIN"] + list(COUNTING.values())
    a = season_stats[season_stats["SEASON"] == season].groupby(
        ["PLAYER_ID", "PLAYER_NAME"], as_index=False
    )[cols].sum()
    a = a[a["MIN"] >= min_minutes].copy()
    for canon, src in COUNTING.items():
        a[canon] = a[src] / a["GP"]
    a["act_fpts_pg"] = score_frame(a, cfg)
    a["act_fpts_total"] = a["act_fpts_pg"] * a["GP"]
    a["act_gp"] = a["GP"]
    a["act_mpg"] = a["MIN"] / a["GP"]
    return a[["PLAYER_ID", "PLAYER_NAME", "MIN", "act_gp", "act_mpg", "act_fpts_pg", "act_fpts_total"]]


def _metrics(merged: pd.DataFrame, pred: str, act: str) -> dict:
    err = merged[pred] - merged[act]
    return {
        "n": len(merged),
        "MAE": err.abs().mean(),
        "bias": err.mean(),
        "pearson": merged[pred].corr(merged[act]),
        "spearman": merged[pred].corr(merged[act], method="spearman"),
    }


# Named learned-model configurations for A/B matrices (kwargs passed to ``project_learned``).
# Every experiment variant lives here so eval runs are reproducible from a name — the ledger
# records variant names, and scripts select them via ``--variants``. Rejected/parked variants
# stay listed (EXPERIMENTS.md explains each verdict); re-running them is one flag, not code.
VARIANT_SPECS: dict[str, dict] = {
    # EXP-008 (rejected) / EXP-009 (parked) / EXP-008b (parked) / EXP-009b (rejected):
    "learned_traj": {"use_trajectory": True},
    "learned_ctx": {"use_context": True},
    "learned_recency": {"use_recency": True},
    "learned_rc": {"use_recency": True, "use_context": True},
    # EXP-012 (Step 4) — recency de-confound:
    "learned_recency_s5": {"use_recency": True, "recency_skip_last": 5},
    "learned_recency_s10": {"use_recency": True, "recency_skip_last": 10},
    "learned_recency_trade": {"use_recency": True, "use_trade_split": True},
    "learned_recency_s5_trade": {"use_recency": True, "recency_skip_last": 5, "use_trade_split": True},
    # EXP-013a/b (Step 5) — objective-side changes:
    "learned_delta": {"target_mode": "delta"},
    "learned_w_mover": {"weight_mode": "mover", "weight_alpha": 1.0},
    "learned_w_mover_a05": {"weight_mode": "mover", "weight_alpha": 0.5},
    "learned_w_rel": {"weight_mode": "relevance"},
    # EXP-013d (Step 5d) — scripts/tune_learned.py grid winner (nested: tuned on folds
    # ≤ 2021-22 only), confirmed once on the standard window per rule 10b:
    "learned_tuned": {"params": {**DEFAULT_LGBM_PARAMS, "num_leaves": 63,
                                 "min_child_samples": 30, "learning_rate": 0.05,
                                 "n_estimators": 79}},
    # EXP-014 (Step 6) — team-constrained minutes allocation (needs rosters):
    "learned_alloc": {"minutes_mode": "allocation"},
    # EXP-015 (Step 7) — injury/availability history into the y_gp model only (needs injuries):
    "learned_inj": {"use_injuries": True},
    # EXP-016b (Step 8.4) — honest-map vacated-usage features (needs vacated_table):
    "learned_vac": {"use_vacated": True},
    # EXP-026a (Step 9b) — breakout-archetype features (needs breakout_table):
    "learned_breakout": {"use_breakout": True},
    # EXP-027a/b (Step 9c) — coach-change interactions / preseason-October role (need
    # coach_table / preseason_table):
    "learned_coach": {"use_coach": True},
    "learned_ps": {"use_preseason": True},
    # EXP-031a (Step 17) — depth-chart features into the y_mpg model only (needs depth_table):
    "learned_depth": {"use_depth": True},
}


def project_models(
    target_season: str,
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    cfg: ScoringConfig,
    game_logs: pd.DataFrame | None = None,
    variants: list[str] | dict[str, dict] | None = None,
    seed: int | None = None,
    rosters: pd.DataFrame | None = None,
    injuries: pd.DataFrame | None = None,
    vacated_table: pd.DataFrame | None = None,
    transactions: pd.DataFrame | None = None,
    breakout_table: pd.DataFrame | None = None,
    coach_table: pd.DataFrame | None = None,
    preseason_table: pd.DataFrame | None = None,
    depth_table: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Project ``target_season`` with every model using **only** prior-season data.

    Aging / GP / minutes curves are refit on the training years (seasons strictly before
    the target), so there is no leakage. Returns ``{model_name: projection_frame}`` — the
    shared no-leakage projection step behind both the ranking backtest and the mover eval.

    ``variants`` adds learned-model configurations beyond the four defaults: a list of
    ``VARIANT_SPECS`` names, or a dict of custom ``{name: project_learned-kwargs}``.
    Variants using recency/trade features need ``game_logs``; ``use_context`` and
    ``minutes_mode='allocation'`` variants get their ``target_team_map`` derived here
    automatically (allocation additionally needs ``rosters`` — the historical
    ``team_rosters`` frame, for positions); ``use_injuries`` variants need ``injuries``
    (the resolved spells frame from ``injuries.build_spells`` — it self-restricts to
    spells before each fold's Oct 1, so passing the full frame stays no-leakage).
    ``seed`` overrides LightGBM's
    ``random_state`` for the whole learned family — the seed-stability protocol
    (implementation-plan §0 rules) runs the eval at seeds {0, 1, 2} and averages.
    """
    ty = _season_start(target_season)
    train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
    train_bio = bio[bio["SEASON"].map(_season_start) < ty]
    if train_ss["SEASON"].nunique() < 2:
        raise ValueError(f"Not enough training seasons before {target_season}.")

    curves = build_aging_curves(train_ss, train_bio, save=False)
    gp_curve = build_gp_age_curve(train_ss, train_bio, save=False)
    mpg_curve = build_minutes_age_curve(train_ss, train_bio, save=False)

    base = project_baseline(train_ss, train_bio, target_season, cfg=cfg)
    v2 = project_v2(train_ss, train_bio, target_season, cfg=cfg, curves=curves, gp_curve=gp_curve)
    # v2m: v2 with the Stage 3 minutes aging curve applied to projected MPG.
    v2m = project_v2(
        train_ss, train_bio, target_season, cfg=cfg, curves=curves, gp_curve=gp_curve,
        mpg_curve=mpg_curve, age_minutes=True,
    )

    seed_params = (
        {"params": {**DEFAULT_LGBM_PARAMS, "random_state": seed}} if seed is not None else {}
    )
    # learned: LightGBM decompositional model on Marcel-equivalent features (EXP-007). Trains
    # on the (prior-only) panel inside project_learned, so it stays no-leakage per fold.
    learned = project_learned(train_ss, train_bio, target_season, cfg=cfg, **seed_params)
    models = {"baseline": base, "v2": v2, "v2m": v2m, "learned": learned}

    if variants:
        specs = (
            {name: VARIANT_SPECS[name] for name in variants}
            if not isinstance(variants, dict) else variants
        )
        for name, spec in specs.items():
            kw = dict(spec)
            if seed is not None:
                # Seed must override random_state *inside* whatever params the spec carries
                # (e.g. a tuned-params variant) — never clobber the spec's params wholesale.
                kw["params"] = {**DEFAULT_LGBM_PARAMS, **spec.get("params", {}),
                                "random_state": seed}
            if kw.get("use_recency") or kw.get("use_trade_split"):
                if game_logs is None:
                    raise ValueError(f"Variant {name!r} needs game_logs.")
                kw["game_logs"] = game_logs
            if kw.get("use_context") or kw.get("minutes_mode") == "allocation":
                # Target-season team assignment. With ``transactions`` this is the honest
                # Oct-1 preseason map (EXP-016 correctness fix); without, the old
                # end-of-season approximation (flatters mid-season movers — EXP-009 caveat).
                if transactions is not None:
                    from .rosters import preseason_roster_map

                    kw["target_team_map"] = preseason_roster_map(
                        season_stats, transactions, target_season
                    )
                else:
                    kw["target_team_map"] = target_team_map(season_stats, target_season)
            if kw.get("minutes_mode") == "allocation":
                if rosters is None:
                    raise ValueError(f"Variant {name!r} needs rosters (team_rosters frame).")
                kw["rosters"] = rosters
            if kw.get("use_injuries"):
                if injuries is None:
                    raise ValueError(f"Variant {name!r} needs injuries (spells frame).")
                kw["injury_table"] = injuries
            if kw.get("use_vacated"):
                if vacated_table is None:
                    raise ValueError(f"Variant {name!r} needs vacated_table "
                                     "(rosters.vacated_feature_table).")
                kw["vacated_table"] = vacated_table
            if kw.get("use_breakout"):
                if breakout_table is None:
                    raise ValueError(f"Variant {name!r} needs breakout_table "
                                     "(breakout.breakout_feature_table).")
                kw["breakout_table"] = breakout_table
            if kw.get("use_coach"):
                if coach_table is None:
                    raise ValueError(f"Variant {name!r} needs coach_table "
                                     "(coaches.coach_feature_table).")
                kw["coach_table"] = coach_table
            if kw.get("use_preseason"):
                if preseason_table is None:
                    raise ValueError(f"Variant {name!r} needs preseason_table "
                                     "(preseason.preseason_feature_table).")
                kw["preseason_table"] = preseason_table
            if kw.get("use_depth"):
                if depth_table is None:
                    raise ValueError(f"Variant {name!r} needs depth_table "
                                     "(allocation.depth_feature_table).")
                kw["depth_table"] = depth_table
            models[name] = project_learned(train_ss, train_bio, target_season, cfg=cfg, **kw)
    return models


def run_backtest(
    target_season: str,
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    cfg: ScoringConfig | None = None,
    pool_top_n: int = 100,
) -> pd.DataFrame:
    """Return a metrics table comparing baseline/v2/v2m for ``target_season``.

    Each model is scored on its **own** top-``pool_top_n`` players by projected season fantasy
    total (the players you'd actually draft), so models aren't judged on bench-player noise.
    Players projected into the pool who then didn't play are penalised via the inner join with
    actuals only if they logged at least one game; a projected star who missed the whole season
    simply drops out (a limitation to revisit once injury data exists).
    """
    cfg = cfg or load_scoring()
    projections = project_models(target_season, season_stats, bio, cfg)
    actual = _actual(season_stats, target_season, cfg, min_minutes=0.0)

    rows = []
    for name, proj in projections.items():
        pool = proj.nsmallest(pool_top_n, "rank")  # top-N by projected fantasy total
        m = pool[["PLAYER_ID", "mpg", "fpts_pg", "fpts_total"]].merge(actual, on="PLAYER_ID", how="inner")
        for metric_name, pred, act in (
            ("mpg", "mpg", "act_mpg"),
            ("fpts_pg", "fpts_pg", "act_fpts_pg"),
            ("fpts_total", "fpts_total", "act_fpts_total"),
        ):
            r = {"model": name, "target": metric_name}
            r.update(_metrics(m, pred, act))
            rows.append(r)

    return pd.DataFrame(rows)
