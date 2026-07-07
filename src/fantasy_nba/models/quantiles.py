"""Direct per-game fantasy-points quantile models (EXP-013c / implementation-plan Step 5c).

Why a separate module: quantiles do **not** compose across the decomposition — the q75 of
``rate × MPG`` is not ``q75(rate) × q75(MPG)`` — so per-target quantile heads can't be combined
into a per-game fantasy quantile. Instead we train LightGBM quantile regressors **directly on
the realized per-game fantasy points** (composed from the panel's labels and scored through the
swappable config), sharing the learned model's feature set.

Role in the system: the **point estimate stays decompositional** (``models.learned``); this
frame exists only to replace the hand-set ``SD_PG = 9`` spread in ``models.uncertainty`` with
per-player, learned spreads (implementation-plan Step 14). It is judged on **pinball loss**
and **per-bucket coverage**, never on point accuracy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame
from ._core import COUNTING, DEFAULT_REG_MINUTES, DEFAULT_WEIGHTS
from .learned import BASE_FEATURES, DEFAULT_LGBM_PARAMS, _features_for, build_panel

QUANTILES = (0.25, 0.50, 0.75, 0.90)


def quantile_col(q: float) -> str:
    """0.25 -> 'fpts_pg_q25'."""
    return f"fpts_pg_q{int(round(q * 100))}"


def panel_fpts_label(panel: pd.DataFrame, cfg: ScoringConfig) -> pd.Series:
    """Realized per-game fantasy points for each panel row: compose the *label* stat line
    (``y_rate_<s> × y_mpg``) and score it — the supervised target for the quantile heads."""
    line = pd.DataFrame({canon: panel[f"y_rate_{canon}"] * panel["y_mpg"] for canon in COUNTING})
    return score_frame(line, cfg)


def fit_fpts_quantiles(
    panel: pd.DataFrame,
    feature_cols: list[str],
    cfg: ScoringConfig,
    params: dict | None = None,
    quantiles: tuple[float, ...] = QUANTILES,
) -> dict[float, object]:
    """One LightGBM quantile regressor per q, trained on the as-of-date panel."""
    from lightgbm import LGBMRegressor

    base = dict(params or DEFAULT_LGBM_PARAMS)
    base.pop("objective", None)  # we set it per head
    X = panel[feature_cols]
    y = panel_fpts_label(panel, cfg)
    return {
        q: LGBMRegressor(objective="quantile", alpha=q, **base).fit(X, y) for q in quantiles
    }


def predict_quantiles(models: dict[float, object], X: pd.DataFrame) -> pd.DataFrame:
    """Predict all quantile columns; rows are re-sorted ascending across the heads so the
    output is always monotone (independently-trained heads can cross on individual rows)."""
    qs = sorted(models)
    raw = np.column_stack([models[q].predict(X) for q in qs])
    raw.sort(axis=1)
    return pd.DataFrame({quantile_col(q): raw[:, i] for i, q in enumerate(qs)}, index=X.index)


def pinball_loss(y_true, y_pred, q: float) -> float:
    """Mean pinball (quantile) loss — the metric of record for EXP-013c. Lower is better;
    a forecast at the true conditional quantile minimizes it."""
    d = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(np.mean(np.maximum(q * d, (q - 1.0) * d)))


def project_fpts_quantiles(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    target_season: str,
    cfg: ScoringConfig | None = None,
    params: dict | None = None,
    quantiles: tuple[float, ...] = QUANTILES,
    min_label_minutes: float = 200.0,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Per-player per-game fantasy-point quantiles for ``target_season``.

    Mirrors ``project_learned``'s no-leakage plumbing (``season_stats`` must already be
    prior-only in backtests) on the Marcel-equivalent feature set. Returns
    ``[PLAYER_ID, PLAYER_NAME, fpts_pg_q25, ..., fpts_pg_q90]`` — joinable onto any board by
    PLAYER_ID. Adopted feature groups can be added here later exactly as in ``project_learned``.
    """
    cfg = cfg or load_scoring()
    panel = build_panel(
        season_stats, bio, min_label_minutes=min_label_minutes,
        n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes,
    )
    models = fit_fpts_quantiles(panel, BASE_FEATURES, cfg, params=params, quantiles=quantiles)

    agg = _features_for(
        season_stats, bio, target_season, use_trajectory=False,
        n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes,
    )
    out = predict_quantiles(models, agg[BASE_FEATURES]).clip(lower=0.0)
    out.insert(0, "PLAYER_ID", agg["PLAYER_ID"].to_numpy())
    out.insert(1, "PLAYER_NAME", agg["PLAYER_NAME"].to_numpy())
    return out.reset_index(drop=True)
