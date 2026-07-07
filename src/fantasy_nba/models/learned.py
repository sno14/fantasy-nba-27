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
BASE_FEATURES = ["from_age", "target_age", "proj_mpg", "weighted_gp", "recent_gp"] + [
    f"rate_{s}" for s in COUNTING
]

# Trajectory / momentum features (EXP-008): season-over-season *slopes* and recent levels the
# recency-weighted aggregates collapse away. The breakout research points at minutes↑ and
# usage↑ held at stable TS% for the young cohort — Marcel's fixed 5/4/3 blend damps exactly
# this signal (it only sees a weighted average, never the trend). These give the tree the
# trajectory so age×trajectory interactions can express "still-improving young player".
TRAJ_FEATURES = [
    "mpg_slope", "mpg_delta", "usg_slope", "usg_last", "usg_delta",
    "ts_last", "ts_std", "n_obs",
]

FEATURES = BASE_FEATURES  # back-compat default (Marcel-equivalent); see feature_columns().

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


def feature_columns(use_trajectory: bool) -> list[str]:
    """Feature set for the learned model — Marcel-equivalent, optionally + trajectory (EXP-008)."""
    return BASE_FEATURES + (TRAJ_FEATURES if use_trajectory else [])


def _slope_by_player(long: pd.DataFrame, value: str) -> pd.Series:
    """OLS slope of ``value`` vs season year, per player (0 when a single season is observed)."""
    d = long.dropna(subset=[value])
    xbar = d.groupby("PLAYER_ID")["year"].transform("mean")
    ybar = d.groupby("PLAYER_ID")[value].transform("mean")
    num = ((d["year"] - xbar) * (d[value] - ybar)).groupby(d["PLAYER_ID"]).sum()
    den = ((d["year"] - xbar) ** 2).groupby(d["PLAYER_ID"]).sum()
    slope = (num / den).replace([np.inf, -np.inf], np.nan).fillna(0.0)  # den==0 → single season
    return slope


def trajectory_features(
    season_stats: pd.DataFrame,
    target_season: str,
    n_seasons: int = 3,
) -> pd.DataFrame:
    """Per-player season-over-season trajectory features from the ``n_seasons`` before target.

    Uses only seasons strictly before ``target_season`` (the caller already passes a prior-only
    frame in the panel/inference paths, so this is doubly safe). Multi-team season rows are
    collapsed with minutes-weighted USG/TS. Returns one row per PLAYER_ID.
    """
    seasons = sorted(season_stats["SEASON"].unique(), key=_season_start, reverse=True)[:n_seasons]
    df = season_stats[season_stats["SEASON"].isin(seasons)].copy()
    df["wUSG"] = df["USG_PCT"] * df["MIN"]
    df["wTS"] = df["TS_PCT"] * df["MIN"]
    p = df.groupby(["PLAYER_ID", "SEASON"], as_index=False).agg(
        MIN=("MIN", "sum"), GP=("GP", "sum"), wUSG=("wUSG", "sum"), wTS=("wTS", "sum")
    )
    p["year"] = p["SEASON"].map(_season_start)
    p["MPG"] = p["MIN"] / p["GP"]
    p["USG"] = p["wUSG"] / p["MIN"]
    p["TS"] = p["wTS"] / p["MIN"]
    p = p.sort_values(["PLAYER_ID", "year"])

    g = p.groupby("PLAYER_ID")
    last = g.last()
    first = g.first()
    out = pd.DataFrame(index=last.index)
    out["mpg_slope"] = _slope_by_player(p, "MPG")
    out["mpg_delta"] = last["MPG"] - first["MPG"]
    out["usg_slope"] = _slope_by_player(p, "USG")
    out["usg_last"] = last["USG"]
    out["usg_delta"] = last["USG"] - first["USG"]
    out["ts_last"] = last["TS"]
    out["ts_std"] = g["TS"].std().fillna(0.0)  # NaN for single season → 0 (no observed variation)
    out["n_obs"] = g.size()
    return out.reset_index()


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


def _features_for(
    prior: pd.DataFrame,
    prior_bio: pd.DataFrame,
    target_season: str,
    use_trajectory: bool,
    n_seasons: int,
    weights: tuple[float, ...],
    reg_minutes: float,
) -> pd.DataFrame:
    """Marcel aggregates (+ trajectory features if requested) for ``target_season``, prior-only."""
    feats = weighted_aggregates(
        prior, prior_bio, target_season, n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes
    )
    if use_trajectory:
        traj = trajectory_features(prior, target_season, n_seasons=n_seasons)
        feats = feats.merge(traj, on="PLAYER_ID", how="left")
        # Players with a single prior season get no slope — neutral fills, not NaN.
        for col in TRAJ_FEATURES:
            feats[col] = feats[col].fillna(0.0)
    return feats


def build_panel(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    use_trajectory: bool = False,
    min_prior_seasons: int = 2,
    min_label_minutes: float = 200.0,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Stack (features as-of-S, labels-in-S) rows over every eligible training season S.

    For each season with at least ``min_prior_seasons`` seasons before it, features are the
    Marcel aggregates (+ trajectory features when ``use_trajectory``) computed from data strictly
    before S, joined to the realized outcomes in S. This is the as-of-date supervised panel.
    """
    seasons = sorted(season_stats["SEASON"].unique(), key=_season_start)
    frames = []
    for s in seasons:
        prior = season_stats[season_stats["SEASON"].map(_season_start) < _season_start(s)]
        if prior["SEASON"].nunique() < min_prior_seasons:
            continue
        prior_bio = bio[bio["SEASON"].map(_season_start) < _season_start(s)]
        feats = _features_for(prior, prior_bio, s, use_trajectory, n_seasons, weights, reg_minutes)
        labels = _labels(season_stats, s, min_label_minutes)
        merged = feats.merge(labels, on="PLAYER_ID", how="inner")
        if not merged.empty:
            frames.append(merged)
    if not frames:
        raise ValueError("Empty training panel — need at least a few seasons of history.")
    return pd.concat(frames, ignore_index=True)


def _fit_models(panel: pd.DataFrame, params: dict, feature_cols: list[str]) -> dict:
    from lightgbm import LGBMRegressor

    X = panel[feature_cols]
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
    use_trajectory: bool = False,
    min_label_minutes: float = 200.0,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Project ``target_season`` with the learned decompositional model.

    Trains one LightGBM per decomposition target on the historical panel drawn from
    ``season_stats`` (already prior-only in the backtest/eval), then predicts for the target
    season and composes a scored stat line — same output schema as ``project_v2``. When
    ``use_trajectory`` is set, adds the EXP-008 season-over-season trajectory features.
    """
    cfg = cfg or load_scoring()
    params = params or DEFAULT_LGBM_PARAMS
    feature_cols = feature_columns(use_trajectory)

    panel = build_panel(
        season_stats, bio, use_trajectory=use_trajectory, min_label_minutes=min_label_minutes,
        n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes,
    )
    models = _fit_models(panel, params, feature_cols)

    agg = _features_for(
        season_stats, bio, target_season, use_trajectory, n_seasons, weights, reg_minutes
    )
    X = agg[feature_cols]

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
