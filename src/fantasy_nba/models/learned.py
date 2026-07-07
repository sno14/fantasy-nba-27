"""Learned decompositional projection (ROADMAP Stage 7.★ / EXP-007).

Replaces Marcel's *hand-set* layers — fixed 5/4/3 recency weights, a fixed regression
constant, and population aging curves — with **LightGBM regressors trained over the historical
player-season panel**. The decomposition philosophy is unchanged (minutes is the error driver,
EXP-001): one model per target — per-minute **rate** for each counting stat, **MPG**, and
**GP** — composed ``stat_pg = rate × MPG`` and scored through the swappable scoring config.

**This first cut deliberately uses only Marcel-equivalent features** (the player's own
recency-weighted rates, weighted MPG/GP, and age). The hypothesis (EXP-007) is a *tie* with
v2m on the mover metrics: it proves the framework swap loses no signal and is safe to build on.
The context features that actually move risers/fallers (trajectory slopes, vacated minutes,
news) enter as *additional feature groups* in later experiments (EXP-008+) — the whole point of
the architecture is that they become features in one place rather than bolt-on adjustments.

No-leakage: the panel is built only from the ``season_stats`` handed in. In the backtest/eval,
that frame is already restricted to seasons before the target (``backtest.project_models``), so
the model is refit per fold on strictly prior data — features for training season *S* come from
seasons ``< S``, and labels from *S* itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame
from ._core import COUNTING, DEFAULT_REG_MINUTES, DEFAULT_WEIGHTS, _season_start, weighted_aggregates

# Marcel-equivalent feature set: the player's own recency-weighted signal + age. Nothing
# exogenous (no team context, trajectory, or news) — that's the point of EXP-007.
FEATURES = ["from_age", "target_age", "proj_mpg", "weighted_gp", "recent_gp"] + [
    f"rate_{s}" for s in COUNTING
]

# One regression target per decomposition layer. Labels are prefixed ``y_`` so they never
# collide with the same-named recency-weighted *feature* columns (e.g. feature ``rate_pts`` is
# the recency-weighted input rate; label ``y_rate_pts`` is the actual realized rate).
RATE_TARGETS = [f"y_rate_{s}" for s in COUNTING]
TARGETS = ["y_mpg", "y_gp"] + RATE_TARGETS

DEFAULT_LGBM_PARAMS = dict(
    n_estimators=300,
    learning_rate=0.05,
    num_leaves=31,
    min_child_samples=30,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    random_state=0,
    n_jobs=-1,
    verbosity=-1,
)


def _labels(season_stats: pd.DataFrame, season: str, min_minutes: float) -> pd.DataFrame:
    """Realized per-minute rates, MPG and GP for ``season`` (the supervised targets)."""
    cols = ["GP", "MIN"] + list(COUNTING.values())
    a = season_stats[season_stats["SEASON"] == season].groupby("PLAYER_ID", as_index=False)[cols].sum()
    a = a[a["MIN"] >= min_minutes].copy()
    out = pd.DataFrame({"PLAYER_ID": a["PLAYER_ID"]})
    out["y_mpg"] = a["MIN"] / a["GP"]
    out["y_gp"] = a["GP"]
    for canon, src in COUNTING.items():
        out[f"y_rate_{canon}"] = a[src] / a["MIN"]
    return out


def build_panel(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    min_prior_seasons: int = 2,
    min_label_minutes: float = 200.0,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Stack (features as-of-S, labels-in-S) rows over every eligible training season S.

    For each season with at least ``min_prior_seasons`` seasons before it, features are the
    Marcel aggregates computed from data strictly before S, joined to the realized outcomes in
    S. This is the as-of-date supervised panel the GBMs learn on.
    """
    seasons = sorted(season_stats["SEASON"].unique(), key=_season_start)
    frames = []
    for s in seasons:
        prior = season_stats[season_stats["SEASON"].map(_season_start) < _season_start(s)]
        if prior["SEASON"].nunique() < min_prior_seasons:
            continue
        prior_bio = bio[bio["SEASON"].map(_season_start) < _season_start(s)]
        feats = weighted_aggregates(
            prior, prior_bio, s, n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes
        )
        labels = _labels(season_stats, s, min_label_minutes)
        merged = feats.merge(labels, on="PLAYER_ID", how="inner")
        if not merged.empty:
            frames.append(merged)
    if not frames:
        raise ValueError("Empty training panel — need at least a few seasons of history.")
    return pd.concat(frames, ignore_index=True)


def _fit_models(panel: pd.DataFrame, params: dict) -> dict:
    from lightgbm import LGBMRegressor

    X = panel[FEATURES]
    models = {}
    for target in TARGETS:
        model = LGBMRegressor(**params)
        model.fit(X, panel[target])
        models[target] = model
    return models


def project_learned(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    target_season: str,
    cfg: ScoringConfig | None = None,
    params: dict | None = None,
    min_label_minutes: float = 200.0,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Project ``target_season`` with the learned decompositional model.

    Trains one LightGBM per decomposition target on the historical panel drawn from
    ``season_stats`` (already prior-only in the backtest/eval), then predicts for the target
    season and composes a scored stat line — same output schema as ``project_v2``.
    """
    cfg = cfg or load_scoring()
    params = params or DEFAULT_LGBM_PARAMS

    panel = build_panel(
        season_stats, bio, min_label_minutes=min_label_minutes,
        n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes,
    )
    models = _fit_models(panel, params)

    agg = weighted_aggregates(
        season_stats, bio, target_season, n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes
    )
    X = agg[FEATURES]

    pred_mpg = np.clip(models["y_mpg"].predict(X), 0.0, 48.0)
    pred_gp = np.clip(models["y_gp"].predict(X), 1.0, 82.0)

    out = pd.DataFrame(
        {
            "PLAYER_ID": agg["PLAYER_ID"],
            "PLAYER_NAME": agg["PLAYER_NAME"],
            "target_season": target_season,
            "target_age": agg["target_age"].round(1),
            "gp": np.round(pred_gp),
            "mpg": np.round(pred_mpg, 1),
        }
    )
    for canon in COUNTING:
        rate = np.clip(models[f"y_rate_{canon}"].predict(X), 0.0, None)
        out[canon] = (rate * pred_mpg).round(2)

    out["fpts_pg"] = score_frame(out, cfg).round(2)
    out["fpts_total"] = (out["fpts_pg"] * out["gp"]).round(1)
    out = out.sort_values("fpts_total", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out
