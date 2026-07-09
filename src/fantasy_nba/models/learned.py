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
from . import breakout as brk
from . import context as ctx
from . import injuries as inj
from . import recency as rec
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

# Injury/availability features (EXP-015, Step 7) feed the **y_gp model only** — availability
# history is a games-played signal; leaking it into rates/MPG would just add noise columns.
# They're therefore not part of feature_columns(); _fit_models appends them per-target.
GP_EXTRA_FEATURES = inj.INJURY_FEATURES

# Team-context / vacated-minutes features (EXP-009) live in models.context.CONTEXT_FEATURES.

# One regression target per decomposition layer. Labels are prefixed ``y_`` so they never
# collide with the same-named recency-weighted *feature* columns (e.g. feature ``rate_pts`` is
# the recency-weighted input rate; label ``y_rate_pts`` is the actual realized rate).
RATE_TARGETS = [f"y_rate_{s}" for s in COUNTING]
TARGETS = ["y_mpg", "y_gp"] + RATE_TARGETS

# Each target's own Marcel-aggregate *feature* — the anchor for the EXP-013 objective modes.
# ``target_mode="delta"`` trains on (label − anchor) and adds the anchor back at prediction:
# regularization then shrinks toward "league-average *change*" instead of the pool-average
# *level* (which pulls stars down / bench up). ``weight_mode="mover"`` up-weights rows whose
# label moved far from its anchor. y_gp keeps ``weighted_gp`` as its weighting anchor but is
# excluded from delta mode (no meaningful additive anchor for games played).
WEIGHT_ANCHORS = {"y_mpg": "proj_mpg", "y_gp": "weighted_gp",
                  **{f"y_rate_{s}": f"rate_{s}" for s in COUNTING}}
DELTA_ANCHORS = {k: v for k, v in WEIGHT_ANCHORS.items() if k != "y_gp"}

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


def feature_columns(
    use_trajectory: bool,
    use_context: bool = False,
    use_recency: bool = False,
    use_trade_split: bool = False,
    use_vacated: bool = False,
    use_breakout: bool = False,
) -> list[str]:
    """Feature set for the learned model — Marcel-equivalent, optionally + trajectory (EXP-008),
    + team-context/vacated-minutes (EXP-009), + within-season recency (EXP-008b),
    + the post-trade split (EXP-012; requires ``use_recency``), + the honest-map
    vacated-usage group (EXP-016b), and/or + the breakout-archetype group (EXP-026a)."""
    return (
        BASE_FEATURES
        + (TRAJ_FEATURES if use_trajectory else [])
        + (ctx.CONTEXT_FEATURES if use_context else [])
        + (rec.RECENCY_FEATURES if use_recency else [])
        + (rec.TRADE_FEATURES if use_trade_split else [])
        + (ctx.VACATED_FEATURES if use_vacated else [])
        + (brk.BREAKOUT_FEATURES if use_breakout else [])
    )


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
    context_feats: pd.DataFrame | None = None,
    recency_feats: pd.DataFrame | None = None,
    injury_feats: pd.DataFrame | None = None,
    vacated_feats: pd.DataFrame | None = None,
    breakout_feats: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Marcel aggregates (+ trajectory / team-context / recency / injury features) for ``target_season``.

    ``prior`` is prior-only (drives the Marcel aggregates and trajectory). Team-context, recency
    and injury features are computed by the caller (they need, respectively, the target-season team
    map, the precomputed game-log table, and the spells table with an as-of date) and passed in as
    ``[PLAYER_ID, *feats]`` frames to merge here.
    """
    feats = weighted_aggregates(
        prior, prior_bio, target_season, n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes
    )
    if use_trajectory:
        traj = trajectory_features(prior, target_season, n_seasons=n_seasons)
        feats = feats.merge(traj, on="PLAYER_ID", how="left")
        # Players with a single prior season get no slope — neutral fills, not NaN.
        for col in TRAJ_FEATURES:
            feats[col] = feats[col].fillna(0.0)
    if context_feats is not None:
        feats = feats.merge(context_feats, on="PLAYER_ID", how="left")
        for col in ctx.CONTEXT_FEATURES:
            feats[col] = feats[col].fillna(0.0)
    if recency_feats is not None:
        feats = feats.merge(recency_feats, on="PLAYER_ID", how="left")
        # Neutral fill for every joined column (RECENCY_FEATURES + TRADE_FEATURES when present).
        for col in recency_feats.columns:
            if col != "PLAYER_ID":
                feats[col] = feats[col].fillna(0.0)
    if injury_feats is not None:
        feats = feats.merge(injury_feats, on="PLAYER_ID", how="left")
        # No spell history = healthy: counts/flags 0, recency at its cap (max distance).
        for col in inj.INJURY_FEATURES:
            fill = inj.RECENCY_CAP_DAYS if col == "inj_recency_days" else 0
            feats[col] = pd.to_numeric(feats[col], errors="coerce").fillna(fill)
    if vacated_feats is not None:
        feats = feats.merge(vacated_feats, on="PLAYER_ID", how="left")
        # Off the Oct-1 map (unsigned on draft day) = no team vacancy to inherit.
        for col in ctx.VACATED_FEATURES:
            feats[col] = feats[col].fillna(0.0)
    if breakout_feats is not None:
        feats = feats.merge(breakout_feats, on="PLAYER_ID", how="left")
        # Missing = no archetype signal; unknown pedigree = undrafted sentinel.
        for col in brk.BREAKOUT_FEATURES:
            fill = brk.UNDRAFTED_PICK if col == "draft_pick" else 0.0
            feats[col] = feats[col].fillna(fill)
    return feats


def build_panel(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    use_trajectory: bool = False,
    use_context: bool = False,
    recency_table: pd.DataFrame | None = None,
    trade_table: pd.DataFrame | None = None,
    injury_table: pd.DataFrame | None = None,
    vacated_table: pd.DataFrame | None = None,
    breakout_table: pd.DataFrame | None = None,
    min_prior_seasons: int = 2,
    min_label_minutes: float = 200.0,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Stack (features as-of-S, labels-in-S) rows over every eligible training season S.

    For each season with at least ``min_prior_seasons`` seasons before it, features are the
    Marcel aggregates (+ trajectory when ``use_trajectory``, + team-context when ``use_context``,
    + within-season recency when ``recency_table`` is given) computed from data strictly before S,
    joined to the realized outcomes in S. The team-context features additionally read S's *team
    assignment* (a preseason roster fact, not an outcome) — ``season_stats`` contains S here, so
    ``context_for_season`` can slice it; ``recency_features`` self-restricts to seasons ``< S``.
    ``injury_table`` (the resolved spells frame, EXP-015) adds the availability features as-of
    Oct 1 of each S — ``injury_features`` self-restricts to spells strictly before that date.
    ``vacated_table`` (``rosters.vacated_feature_table``, EXP-016b) is SEASON-keyed and sliced
    per S — each block was built from the honest Oct-1 map + prior-season stats only.
    """
    seasons = sorted(season_stats["SEASON"].unique(), key=_season_start)
    frames = []
    for s in seasons:
        prior = season_stats[season_stats["SEASON"].map(_season_start) < _season_start(s)]
        if prior["SEASON"].nunique() < min_prior_seasons:
            continue
        prior_bio = bio[bio["SEASON"].map(_season_start) < _season_start(s)]
        context_feats = ctx.context_for_season(season_stats, s) if use_context else None
        recency_feats = (
            rec.recency_features(recency_table, s, trade_table)
            if recency_table is not None else None
        )
        injury_feats = (
            inj.injury_features(injury_table, f"{_season_start(s)}-10-01")
            if injury_table is not None else None
        )
        vacated_feats = (
            vacated_table.loc[vacated_table["SEASON"] == s, ["PLAYER_ID"] + ctx.VACATED_FEATURES]
            if vacated_table is not None else None
        )
        breakout_feats = (
            breakout_table.loc[breakout_table["SEASON"] == s, ["PLAYER_ID"] + brk.BREAKOUT_FEATURES]
            if breakout_table is not None else None
        )
        feats = _features_for(
            prior, prior_bio, s, use_trajectory, n_seasons, weights, reg_minutes,
            context_feats, recency_feats, injury_feats, vacated_feats, breakout_feats,
        )
        labels = _labels(season_stats, s, min_label_minutes)
        merged = feats.merge(labels, on="PLAYER_ID", how="inner")
        if not merged.empty:
            frames.append(merged)
    if not frames:
        raise ValueError("Empty training panel — need at least a few seasons of history.")
    return pd.concat(frames, ignore_index=True)


def _sample_weight(
    panel: pd.DataFrame, target: str, weight_mode: str | None, weight_alpha: float
) -> np.ndarray | None:
    """Training-row weights for the EXP-013b objective modes (labels are fair game at train time).

    * ``"mover"``     — ``1 + alpha × |label − anchor| / MAD(label − anchor)``: rows whose outcome
      moved far from their own Marcel anchor count more, so the loss stops being dominated by the
      stable majority. ``alpha`` is unitless (deviation is MAD-scaled).
    * ``"relevance"`` — ``clip(recency-weighted avg season minutes / 2000, 0.25, 2)``: draftable
      players count more, bench noise less.
    """
    if weight_mode is None:
        return None
    if weight_mode == "mover":
        dev = (panel[target] - panel[WEIGHT_ANCHORS[target]]).abs()
        mad = float(dev.median())
        return (1.0 + weight_alpha * dev / max(mad, 1e-9)).to_numpy()
    if weight_mode == "relevance":
        avg_min = panel["wMIN"] / panel["w"].replace(0, np.nan)
        return np.clip((avg_min / 2000.0).fillna(0.25).to_numpy(), 0.25, 2.0)
    raise ValueError(f"weight_mode must be None, 'mover' or 'relevance', got {weight_mode!r}")


def _fit_models(
    panel: pd.DataFrame,
    params: dict,
    feature_cols: list[str],
    target_mode: str = "level",
    weight_mode: str | None = None,
    weight_alpha: float = 1.0,
    gp_extra_cols: list[str] | None = None,
) -> dict:
    """One LightGBM per target. ``gp_extra_cols`` (EXP-015 injury features) extend the
    feature set of the **y_gp model only** — the other targets never see them."""
    if target_mode not in ("level", "delta"):
        raise ValueError(f"target_mode must be 'level' or 'delta', got {target_mode!r}")
    from lightgbm import LGBMRegressor

    models = {}
    for target in TARGETS:
        cols = feature_cols + (gp_extra_cols or []) if target == "y_gp" else feature_cols
        label = panel[target]
        if target_mode == "delta" and target in DELTA_ANCHORS:
            label = label - panel[DELTA_ANCHORS[target]]  # train on change from own anchor
        model = LGBMRegressor(**params)
        model.fit(panel[cols], label,
                  sample_weight=_sample_weight(panel, target, weight_mode, weight_alpha))
        models[target] = model
    return models


def _predict_target(
    models: dict, target: str, X: pd.DataFrame, agg: pd.DataFrame, target_mode: str
) -> np.ndarray:
    """Predict one target, adding the anchor back in delta mode (anchors are feature columns,
    so ``agg`` always carries them)."""
    pred = models[target].predict(X)
    if target_mode == "delta" and target in DELTA_ANCHORS:
        pred = pred + agg[DELTA_ANCHORS[target]].to_numpy(dtype=float)
    return pred


def project_learned(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    target_season: str,
    cfg: ScoringConfig | None = None,
    params: dict | None = None,
    use_trajectory: bool = False,
    use_context: bool = False,
    target_team_map: pd.DataFrame | None = None,
    use_recency: bool = False,
    game_logs: pd.DataFrame | None = None,
    recency_skip_last: int = 0,
    use_trade_split: bool = False,
    use_injuries: bool = False,
    injury_table: pd.DataFrame | None = None,
    use_vacated: bool = False,
    vacated_table: pd.DataFrame | None = None,
    use_breakout: bool = False,
    breakout_table: pd.DataFrame | None = None,
    target_mode: str = "level",
    weight_mode: str | None = None,
    weight_alpha: float = 1.0,
    minutes_mode: str = "regression",
    rosters: pd.DataFrame | None = None,
    min_label_minutes: float = 200.0,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Project ``target_season`` with the learned decompositional model.

    Trains one LightGBM per decomposition target on the historical panel drawn from
    ``season_stats`` (already prior-only in the backtest/eval), then predicts for the target
    season and composes a scored stat line — same output schema as ``project_v2``. ``use_trajectory``
    adds the EXP-008 trajectory features; ``use_context`` adds the EXP-009 team-context features,
    which need the target-season team assignment — pass ``target_team_map`` (``[PLAYER_ID, team]``)
    since ``season_stats`` here is prior-only and doesn't contain the target season. ``use_recency``
    adds the EXP-008b within-season last-N-game features — pass ``game_logs`` (``recency_features``
    self-restricts to seasons before the target, so passing the full frame is safe).

    EXP-012 knobs (need ``use_recency``): ``recency_skip_last`` trims each prior season's final
    played games from the recency window (rest/tanking de-confound); ``use_trade_split`` adds the
    post-trade ``TRADE_FEATURES`` (game logs must carry ``TEAM_ABBREVIATION``).
    EXP-015 knob (Step 7): ``use_injuries`` adds the ``INJURY_FEATURES`` (prosportstransactions
    availability history) to the **y_gp model only** — pass ``injury_table`` (the resolved
    spells frame from ``injuries.build_spells``; ``injury_features`` self-restricts to spells
    before Oct 1 of each season, so passing the full frame is safe).
    EXP-016b knob (Step 8.4): ``use_vacated`` adds the honest-map ``VACATED_FEATURES`` —
    pass ``vacated_table`` (``rosters.vacated_feature_table``, SEASON-keyed; must cover the
    training seasons *and* the target season).
    EXP-013 knobs: ``target_mode='delta'`` trains on change-from-own-anchor instead of levels;
    ``weight_mode`` ∈ {``'mover'``, ``'relevance'``} re-weights training rows (see
    :func:`_sample_weight`), scaled by ``weight_alpha``.
    EXP-014 knob (Step 6): ``minutes_mode='allocation'`` swaps **only the minutes layer** for
    the team-constrained share model (``models.allocation``) — needs ``rosters`` (the
    historical ``team_rosters`` frame, for positions) and ``target_team_map`` (the
    target-season team assignment). Players without a mappable position/team fall back to
    the regression minutes. Rates and GP are untouched.
    """
    cfg = cfg or load_scoring()
    params = params or DEFAULT_LGBM_PARAMS
    if use_trade_split and not use_recency:
        raise ValueError("use_trade_split requires use_recency (both ride the game-log tables).")
    if use_injuries and injury_table is None:
        raise ValueError("use_injuries needs injury_table (the spells frame from injuries.build_spells).")
    if use_vacated and vacated_table is None:
        raise ValueError("use_vacated needs vacated_table (rosters.vacated_feature_table).")
    if use_breakout and breakout_table is None:
        raise ValueError("use_breakout needs breakout_table (breakout.breakout_feature_table).")
    if minutes_mode not in ("regression", "allocation"):
        raise ValueError(f"minutes_mode must be 'regression' or 'allocation', got {minutes_mode!r}")
    if minutes_mode == "allocation" and (rosters is None or target_team_map is None):
        raise ValueError("minutes_mode='allocation' needs rosters (team_rosters frame) and "
                         "target_team_map ([PLAYER_ID, team]).")
    feature_cols = feature_columns(use_trajectory, use_context, use_recency, use_trade_split,
                                   use_vacated, use_breakout)

    recency_table = trade_table = None
    if use_recency:
        if game_logs is None:
            raise ValueError("use_recency needs game_logs ([PLAYER_ID, SEASON, GAME_DATE, MIN, PTS]).")
        # Computed once, sliced per fold.
        recency_table = rec.season_recency_table(game_logs, skip_last=recency_skip_last)
        trade_table = rec.trade_split_table(game_logs) if use_trade_split else None

    panel = build_panel(
        season_stats, bio, use_trajectory=use_trajectory, use_context=use_context,
        recency_table=recency_table, trade_table=trade_table,
        injury_table=injury_table if use_injuries else None,
        vacated_table=vacated_table if use_vacated else None,
        breakout_table=breakout_table if use_breakout else None,
        min_label_minutes=min_label_minutes,
        n_seasons=n_seasons, weights=weights, reg_minutes=reg_minutes,
    )
    models = _fit_models(
        panel, params, feature_cols,
        target_mode=target_mode, weight_mode=weight_mode, weight_alpha=weight_alpha,
        gp_extra_cols=GP_EXTRA_FEATURES if use_injuries else None,
    )

    context_feats = None
    if use_context:
        if target_team_map is None:
            raise ValueError(
                "use_context inference needs target_team_map ([PLAYER_ID, team]); season_stats is "
                "prior-only. Pass context.target_team_map(full_stats, target) or a roster-derived map."
            )
        context_feats = ctx.team_context_features(
            season_stats, target_team_map, ctx.season_before(target_season)
        )

    recency_feats = (
        rec.recency_features(recency_table, target_season, trade_table) if use_recency else None
    )
    injury_feats = (
        inj.injury_features(injury_table, f"{_season_start(target_season)}-10-01")
        if use_injuries else None
    )
    vacated_feats = None
    if use_vacated:
        vacated_feats = vacated_table.loc[
            vacated_table["SEASON"] == target_season, ["PLAYER_ID"] + ctx.VACATED_FEATURES
        ]
        if vacated_feats.empty:
            raise ValueError(f"vacated_table has no rows for target season {target_season!r} — "
                             "build it with the target season included.")
    breakout_feats = None
    if use_breakout:
        breakout_feats = breakout_table.loc[
            breakout_table["SEASON"] == target_season, ["PLAYER_ID"] + brk.BREAKOUT_FEATURES
        ]
        if breakout_feats.empty:
            raise ValueError(f"breakout_table has no rows for target season {target_season!r} — "
                             "build it with the target season included.")

    agg = _features_for(
        season_stats, bio, target_season, use_trajectory, n_seasons, weights, reg_minutes,
        context_feats, recency_feats, injury_feats, vacated_feats, breakout_feats,
    )
    X = agg[feature_cols]
    X_gp = agg[feature_cols + GP_EXTRA_FEATURES] if use_injuries else X

    pred_mpg = np.clip(_predict_target(models, "y_mpg", X, agg, target_mode), 0.0, 48.0)
    pred_gp = np.clip(_predict_target(models, "y_gp", X_gp, agg, target_mode), 1.0, 82.0)

    if minutes_mode == "allocation":
        from . import allocation as alloc

        pos_table = alloc.position_table(rosters)
        share_panel = alloc.build_share_panel(season_stats, pos_table)
        share_model = alloc.fit_share_model(share_panel, params)
        # Rookie reserve measured on the training slice only (critique §2.8 — season_stats
        # is prior-only here in backtests; the caller owns that contract).
        reserve = alloc.rookie_reserve(season_stats)
        feats = alloc.share_features_for(season_stats, target_team_map, pos_table, target_season)
        shares = alloc.predict_shares(share_model, feats, reserve)
        total_scale = alloc.mean_team_total_minutes(season_stats)
        min_total = agg["PLAYER_ID"].map(shares.set_index("PLAYER_ID")["share_norm"]) * total_scale
        mpg_alloc = np.clip(min_total.to_numpy(dtype=float) / pred_gp, 0.0, 42.0)
        # Players outside the roster/position map keep the regression minutes.
        pred_mpg = np.where(np.isnan(mpg_alloc), pred_mpg, mpg_alloc)

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
        rate = np.clip(_predict_target(models, f"y_rate_{canon}", X, agg, target_mode), 0.0, None)
        out[canon] = (rate * pred_mpg).round(2)

    out["fpts_pg"] = score_frame(out, cfg).round(2)
    out["fpts_total"] = (out["fpts_pg"] * out["gp"]).round(1)
    out = out.sort_values("fpts_total", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out
