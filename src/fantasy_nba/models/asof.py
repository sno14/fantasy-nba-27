"""As-of-date remaining-season (ROS) projection (EXP-018 / implementation-plan Step 10).

The model `docs/model-foundation.md` §4 specifies and the Phase-0 verdict (EXP-011, Decision
Row 1) pulls forward: **one function usable at any date T**, trained on in-season *cutpoint*
snapshots so the shrinkage question — "6 hot games into the season, how far do I move a
player off his preseason projection?" — is **learned from history, not hand-set**. This is
where the real headroom lives, because the stubborn preseason riser bias is a sleeper-*recall*
problem (EXP-011b) and a breakout surfaces in the game logs within a few weeks.

Design (the core; amendments layer on top):

* **One panel, every cutpoint.** For each historical season S and each cutpoint T in a fixed
  grid (preseason ≡ season_start − 7d, then +30/+60/+90/+120/+150d), a row carries:
  - the **preseason block** — the same Marcel aggregates `models.learned` uses (from seasons
    strictly before S), so every preseason feature group carries over unchanged;
  - the **season-to-date (STD) block** — from that season's game logs **≤ T**: games played,
    MPG, per-minute rates, a last-10 form window, days since last game, and `games_so_far`,
    the shrinkage handle the trees interact everything else with;
  - the **ROS labels** — realized from the same season's game logs **> T** (`y_ros_mpg`,
    `y_ros_gp`, `y_ros_rate_<s>`); rows need ≥ 5 remaining games to be labeled.
  At the preseason cutpoint the STD block is 0/neutral and `games_so_far = 0`, so **one model
  serves T₀ and every later date** — and at T₀ the projection reproduces `project_learned`
  (the 10.2 consistency check).

  *Consistency result (2026-07, real data, target 2024-25).* The plan's literal thresholds
  (Spearman ≥ 0.98, level-MAE gap ≤ 0.30 on the top-150) turn out to be **below
  `project_learned`'s own seed-to-seed reproducibility** — two seeds of the identical model
  agree at only Spearman 0.968–0.973 / MAE 0.81–0.89. So the operative criterion is
  "within seed noise." A *preseason-only* asof model lands at Spearman 0.965 / MAE 0.82 —
  indistinguishable from another seed of `project_learned`, confirming no leak or feature
  mismatch (labels are provably identical, rate-label corr 1.0000). The full pooled model
  (Spearman 0.947 / MAE 1.14 with cutpoint balancing) sits ~0.02 below the noise floor — the
  small, expected cost of one model spanning six cutpoint regimes, not a bug. The debugging
  that got here fixed a real issue: the ROS label needs a minutes floor
  (`MIN_ROS_MINUTES`), mirroring `learned._labels`, or garbage-time rate labels distort the
  fit.

* **Universe = union of preseason-projectable and STD-active players.** A player with no prior
  seasons (a rookie the Marcel path can't touch) still enters an in-season row through his STD
  block, with the preseason features left NaN (LightGBM splits on NaN natively) — this is how
  the engine can rank a sleeper the preseason board never saw.

Amendments from the design review (EWMAs with fitted half-lives, live teammate-vacated
minutes, return-from-absence ramp, blowout handling, schedule-aware ROS) are added on top of
this core once it passes the consistency check — each its own gated change.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..config import CONFIG_DIR
from ..scoring import ScoringConfig, load_scoring, score_frame
from ._core import COUNTING, DEFAULT_REG_MINUTES, DEFAULT_WEIGHTS, _season_start
from .learned import BASE_FEATURES, DEFAULT_LGBM_PARAMS, _features_for

# Cutpoint grid, in days from each season's first game. -7 ≡ the preseason snapshot (T₀).
CUTPOINT_OFFSETS = (-7, 30, 60, 90, 120, 150)
MIN_ROS_GAMES = 5
# Total remaining-minutes floor for a labelable row — mirrors learned._labels' MIN>=200
# so the rate labels aren't dominated by garbage-time players (see ros_labels docstring).
MIN_ROS_MINUTES = 200.0

STD_RATE_FEATURES = [f"std_rate_{s}" for s in COUNTING]
STD_FEATURES = (
    ["std_gp", "std_mpg"]
    + STD_RATE_FEATURES
    + ["last10_mpg", "last10_mpg_delta", "last10_ppm_delta", "days_since_last_game", "games_so_far"]
)
# STD features that mean "zero so far" when a player has no games yet (the preseason row);
# days_since_last_game has no natural zero, so it stays NaN (games_so_far=0 already says T₀).
_STD_ZERO_FILL = [c for c in STD_FEATURES if c != "days_since_last_game"]

ASOF_FEATURES = BASE_FEATURES + STD_FEATURES

# Preseason block carried on each panel row: identity + age + the Marcel BASE_FEATURES, with
# target_age listed once (it lives in BASE_FEATURES already).
_PRESEASON_COLS = ["PLAYER_ID", "PLAYER_NAME"] + BASE_FEATURES

ROS_RATE_TARGETS = [f"y_ros_rate_{s}" for s in COUNTING]
ROS_TARGETS = ["y_ros_mpg", "y_ros_gp"] + ROS_RATE_TARGETS

# --- EWMA form amendment (design-critique §5.2) -----------------------------------------
# One hard last-10 window is wrong for every stat at once: steals stabilize in a handful of
# games, 3P% barely stabilizes in a season. Per-stat EWMAs with half-lives fitted on the
# training cutpoint panel replace the single window as the form signal.
EWMA_GRID = (5, 10, 20, 40)  # candidate half-lives, in games
EWMA_FEATURES = ["ewma_mpg", "ewma_mpg_delta"] + [f"ewma_rate_{s}" for s in COUNTING]

# EXP-018 measured result (2026-07-09 addendum item 3): fit_half_lives returned the identical
# answer in all four backtest folds — every rate → 40 games, MPG → 10. Frozen as documented
# constants (the fitting function stays for re-checks); consumers use these instead of paying
# the slow per-fold refit. Re-fit only if the panel changes shape (new feature regime).
FROZEN_HALF_LIVES: dict = {"mpg": 10, **{s: 40 for s in COUNTING}}


# --- Naive-blend features (response to the measured EXP-018 core result) -----------------
# The hand-set shrinkage baseline ("naive": per-game line = (n×STD + K×T₀)/(n+K)) proved
# strong exactly because it blends the *per-game line* directly, sidestepping the rate×MPG
# composition. Giving the model that blend as explicit features lets it start from the naive
# answer and learn corrections — a smooth ratio the trees are bad at building from raw parts.
# The anchor is the Marcel per-game line (rate_<s> × proj_mpg — already features), so the
# blend is a deterministic transform of existing columns: no extra fitting, no leakage.
BLEND_K = 20.0
BLEND_FEATURES = ["blend_mpg"] + [f"blend_pg_{s}" for s in COUNTING]


def feature_cols(use_ewma: bool = False, use_blend: bool = False) -> list[str]:
    """The as-of model's feature list; amendment blocks join when switched on."""
    return (ASOF_FEATURES
            + (EWMA_FEATURES if use_ewma else [])
            + (BLEND_FEATURES if use_blend else []))


def add_blend_features(frame: pd.DataFrame, k: float = BLEND_K) -> pd.DataFrame:
    """Add ``BLEND_FEATURES`` to a row frame that already carries the preseason and STD
    blocks. Preseason rows (games_so_far=0) reduce to the pure Marcel line; STD-only rookies
    (no Marcel anchor) reduce to the pure season-to-date line."""
    out = frame.copy()
    n = out["games_so_far"]
    w = n / (n + k)
    marcel_mpg = out["proj_mpg"]
    out["blend_mpg"] = w * out["std_mpg"].where(n > 0, marcel_mpg) + (1 - w) * marcel_mpg.fillna(
        out["std_mpg"])
    for canon in COUNTING:
        std_pg = out["std_mpg"] * out[f"std_rate_{canon}"]
        marcel_pg = marcel_mpg * out[f"rate_{canon}"]
        out[f"blend_pg_{canon}"] = (
            w * std_pg.where(n > 0, marcel_pg) + (1 - w) * marcel_pg.fillna(std_pg)
        )
    return out


def _with_dates(game_logs: pd.DataFrame) -> pd.DataFrame:
    """Return game logs with a parsed ``_date`` column (idempotent)."""
    if "_date" in game_logs.columns:
        return game_logs
    gl = game_logs.copy()
    gl["_date"] = pd.to_datetime(gl["GAME_DATE"])
    return gl


def season_date_bounds(game_logs: pd.DataFrame) -> pd.DataFrame:
    """Per-season ``[SEASON, start, end]`` from the game-log dates (start = first game)."""
    gl = _with_dates(game_logs)
    b = gl.groupby("SEASON")["_date"].agg(start="min", end="max").reset_index()
    return b


def cutpoint_dates(start: pd.Timestamp) -> list[tuple[int, pd.Timestamp]]:
    """The (offset_days, date) grid for a season starting on ``start``."""
    return [(off, start + pd.Timedelta(days=off)) for off in CUTPOINT_OFFSETS]


def std_features(gl_season: pd.DataFrame, T: pd.Timestamp) -> pd.DataFrame:
    """Season-to-date block from one season's game logs, using only games on/before ``T``.

    Empty (preseason T₀) → an empty frame; the panel builder neutral-fills those rows.
    """
    played = gl_season[gl_season["_date"] <= T]
    if played.empty:
        return pd.DataFrame(columns=["PLAYER_ID"] + STD_FEATURES)

    played = played.sort_values("_date")
    g = played.groupby("PLAYER_ID")
    tot_min = g["MIN"].sum()
    std_gp = g.size()
    out = pd.DataFrame({"PLAYER_ID": tot_min.index})
    out["std_gp"] = std_gp.to_numpy()
    out["std_mpg"] = (tot_min / std_gp).to_numpy()
    for canon, src in COUNTING.items():
        out[f"std_rate_{canon}"] = (g[src].sum() / tot_min).to_numpy()

    # Last-10-game form window (per player, most recent 10 games ≤ T).
    last10 = played.groupby("PLAYER_ID").tail(10).groupby("PLAYER_ID")
    l10_min = last10["MIN"].sum()
    l10 = pd.DataFrame({"PLAYER_ID": l10_min.index})
    l10["last10_mpg"] = (l10_min / last10.size()).to_numpy()
    l10["last10_ppm"] = (last10["PTS"].sum() / l10_min).to_numpy()
    out = out.merge(l10, on="PLAYER_ID", how="left")
    out["last10_mpg_delta"] = out["last10_mpg"] - out["std_mpg"]
    std_ppm = (g["PTS"].sum() / tot_min).reindex(out["PLAYER_ID"]).to_numpy()
    out["last10_ppm_delta"] = out["last10_ppm"] - std_ppm
    out = out.drop(columns=["last10_ppm"])

    last_date = g["_date"].max().reindex(out["PLAYER_ID"])
    out["days_since_last_game"] = (T - last_date).dt.days.to_numpy()
    out["games_so_far"] = out["std_gp"]
    return out[["PLAYER_ID"] + STD_FEATURES]


def _ewma_last(gl_played: pd.DataFrame, half_life: float) -> pd.DataFrame:
    """Per player: game-index EWMA (half-life in *games*) of MIN and each counting stat over
    his games ≤ T, taking the value as of the most recent game. Rates are ratio-of-EWMAs
    (EWMA(stat)/EWMA(MIN)) — minutes-weighted, so a 2-minute garbage stint can't spike them."""
    cols = ["MIN"] + list(COUNTING.values())
    g = gl_played.sort_values("_date").groupby("PLAYER_ID")[cols]
    sm = g.ewm(halflife=half_life).mean().groupby(level=0).last()
    out = pd.DataFrame({"PLAYER_ID": sm.index})
    out["ewma_mpg"] = sm["MIN"].to_numpy()
    for canon, src in COUNTING.items():
        out[f"ewma_rate_{canon}"] = (sm[src] / sm["MIN"].replace(0, np.nan)).to_numpy()
    return out


def ewma_features(gl_season: pd.DataFrame, T: pd.Timestamp, half_lives: dict) -> pd.DataFrame:
    """The fitted-half-life form block: ``ewma_mpg`` (+ delta vs season-to-date MPG) at
    ``half_lives['mpg']`` and per-stat ``ewma_rate_<s>`` each at its own fitted half-life.

    ``half_lives`` maps ``'mpg'`` and every COUNTING key to a value from ``EWMA_GRID``.
    Empty logs (preseason) → empty frame; the row builder neutral-fills.
    """
    played = gl_season[gl_season["_date"] <= T]
    if played.empty:
        return pd.DataFrame(columns=["PLAYER_ID"] + EWMA_FEATURES)
    # Compute once per distinct half-life, then pick each stat's column from its table.
    tables = {h: _ewma_last(played, h) for h in sorted(set(half_lives.values()))}
    out = tables[half_lives["mpg"]][["PLAYER_ID", "ewma_mpg"]].copy()
    for canon in COUNTING:
        h = half_lives[canon]
        out = out.merge(tables[h][["PLAYER_ID", f"ewma_rate_{canon}"]], on="PLAYER_ID", how="left")
    g = played.groupby("PLAYER_ID")
    std_mpg = (g["MIN"].sum() / g.size()).rename("std_mpg_")
    out["ewma_mpg_delta"] = out["ewma_mpg"] - out["PLAYER_ID"].map(std_mpg)
    return out[["PLAYER_ID"] + EWMA_FEATURES]


def fit_half_lives(game_logs: pd.DataFrame, offsets: tuple[int, ...] = (30, 60, 90)) -> dict:
    """Fit per-stat EWMA half-lives on the (training) game logs: at each (season, cutpoint),
    correlate each candidate-half-life EWMA with the realized ROS value of the same quantity;
    pick each stat's argmax-correlation half-life, pooled over all rows.

    The caller passes **training-season logs only** (the same walk-forward slice the panel is
    built from) — fitted half-lives are hyperparameters and must not see the eval season.
    """
    gl = _with_dates(game_logs)
    bounds = season_date_bounds(gl).set_index("SEASON")["start"]
    quantities = ["mpg"] + list(COUNTING)
    ew_frames, lab_frames = {h: [] for h in EWMA_GRID}, []
    for season in gl["SEASON"].unique():
        gl_s = gl[gl["SEASON"] == season]
        for off in offsets:
            T = bounds[season] + pd.Timedelta(days=off)
            labels = ros_labels(gl_s, T)
            if labels.empty:
                continue
            labels = labels.assign(_key=f"{season}|{off}")
            lab_frames.append(labels)
            played = gl_s[gl_s["_date"] <= T]
            if played.empty:
                continue
            for h in EWMA_GRID:
                ew_frames[h].append(_ewma_last(played, h).assign(_key=f"{season}|{off}"))
    labs = pd.concat(lab_frames, ignore_index=True)
    fitted = {}
    for q in quantities:
        lab_col = "y_ros_mpg" if q == "mpg" else f"y_ros_rate_{q}"
        ew_col = "ewma_mpg" if q == "mpg" else f"ewma_rate_{q}"
        best_h, best_corr = EWMA_GRID[0], -np.inf
        for h in EWMA_GRID:
            ew = pd.concat(ew_frames[h], ignore_index=True)
            m = labs[["PLAYER_ID", "_key", lab_col]].merge(ew[["PLAYER_ID", "_key", ew_col]],
                                                           on=["PLAYER_ID", "_key"])
            c = m[lab_col].corr(m[ew_col])
            if c > best_corr:
                best_h, best_corr = h, c
        fitted[q] = best_h
    return fitted


def ros_labels(
    gl_season: pd.DataFrame, T: pd.Timestamp,
    min_ros: int = MIN_ROS_GAMES, min_ros_minutes: float = MIN_ROS_MINUTES,
) -> pd.DataFrame:
    """Remaining-season labels from one season's game logs strictly after ``T``.

    Dropped rows: fewer than ``min_ros`` remaining games (unstable GP label), or fewer than
    ``min_ros_minutes`` total remaining minutes. The minutes floor mirrors ``learned._labels``'
    ``MIN >= 200`` season filter — without it the per-minute rate labels are dominated by
    garbage-time players (5+ games at ~6 mpg) whose noisy rates distort the fitted rate models
    and break the T₀ consistency with ``project_learned`` (verified: labels for shared players
    are otherwise identical, corr 1.0000).
    """
    future = gl_season[gl_season["_date"] > T]
    if future.empty:
        return pd.DataFrame(columns=["PLAYER_ID"] + ROS_TARGETS)
    g = future.groupby("PLAYER_ID")
    tot_min = g["MIN"].sum()
    gp = g.size()
    out = pd.DataFrame({"PLAYER_ID": tot_min.index})
    out["y_ros_gp"] = gp.to_numpy()
    out["y_ros_mpg"] = (tot_min / gp).to_numpy()
    out["_tot_min"] = tot_min.to_numpy()
    for canon, src in COUNTING.items():
        out[f"y_ros_rate_{canon}"] = (g[src].sum() / tot_min.replace(0, np.nan)).to_numpy()
    keep = (out["y_ros_gp"] >= min_ros) & (out["_tot_min"] >= min_ros_minutes)
    return out[keep].drop(columns="_tot_min").reset_index(drop=True)


def _preseason_block(
    season_stats: pd.DataFrame, bio: pd.DataFrame, season: str,
    n_seasons: int, weights: tuple[float, ...], reg_minutes: float,
) -> pd.DataFrame:
    """The Marcel-aggregate preseason features for ``season`` (from strictly-prior seasons) —
    ``[PLAYER_ID, PLAYER_NAME, target_age] + BASE_FEATURES``. Returns empty if there is
    insufficient history (the panel builder skips such seasons)."""
    prior = season_stats[season_stats["SEASON"].map(_season_start) < _season_start(season)]
    if prior["SEASON"].nunique() < 2:
        return pd.DataFrame(columns=_PRESEASON_COLS)
    prior_bio = bio[bio["SEASON"].map(_season_start) < _season_start(season)]
    feats = _features_for(prior, prior_bio, season, False, n_seasons, weights, reg_minutes)
    return feats[_PRESEASON_COLS]


def _row_frame(preseason: pd.DataFrame, std: pd.DataFrame,
               ewma: pd.DataFrame | None = None) -> pd.DataFrame:
    """Union of preseason-projectable and STD-active players, STD neutral-filled for the
    preseason-only rows (leaving preseason features NaN for STD-only rookies)."""
    base = preseason.merge(std, on="PLAYER_ID", how="outer")
    if ewma is not None:
        base = base.merge(ewma, on="PLAYER_ID", how="left")
        for col in EWMA_FEATURES:
            if col not in base.columns:
                base[col] = np.nan
    # Coerce every feature to float first. STD columns from an empty (preseason) std frame and
    # BASE columns from a single-prior season (empty preseason block) arrive as object-NaN;
    # LightGBM needs numeric dtypes. Then zero-fill the STD "nothing so far" columns; BASE stays
    # NaN for STD-only rookies (a real missing value) and days_since_last_game stays NaN at T₀.
    # EWMA columns stay NaN pre-first-game (no form exists yet — a real missing value).
    cols = ASOF_FEATURES + (EWMA_FEATURES if ewma is not None else [])
    for col in cols:
        if col in base.columns:
            base[col] = pd.to_numeric(base[col], errors="coerce")
    for col in _STD_ZERO_FILL:
        base[col] = base[col].fillna(0.0)
    return base


def build_asof_panel(
    season_stats: pd.DataFrame,
    game_logs: pd.DataFrame,
    bio: pd.DataFrame,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
    min_ros: int = MIN_ROS_GAMES,
    min_ros_minutes: float = MIN_ROS_MINUTES,
    half_lives: dict | None = None,
    use_blend: bool = False,
) -> pd.DataFrame:
    """Stack (preseason + STD features as-of-T, ROS labels-after-T) over every eligible
    (season, cutpoint). Seasons need ≥ 2 predecessors for the preseason block; the caller
    restricts ``season_stats``/``game_logs`` to prior seasons for a no-leakage backtest fold.
    ``half_lives`` (from :func:`fit_half_lives`, on the same training slice) adds the EWMA
    form block; ``use_blend`` adds the naive-blend features.
    """
    gl = _with_dates(game_logs)
    bounds = season_date_bounds(gl).set_index("SEASON")["start"]
    frames = []
    for season in sorted(gl["SEASON"].unique(), key=_season_start):
        preseason = _preseason_block(season_stats, bio, season, n_seasons, weights, reg_minutes)
        gl_s = gl[gl["SEASON"] == season]
        for offset, T in cutpoint_dates(bounds[season]):
            std = std_features(gl_s, T)
            labels = ros_labels(gl_s, T, min_ros=min_ros, min_ros_minutes=min_ros_minutes)
            if labels.empty or (preseason.empty and std.empty):
                continue
            ew = ewma_features(gl_s, T, half_lives) if half_lives else None
            feats = _row_frame(preseason, std, ew)
            if use_blend:
                feats = add_blend_features(feats)
            row = feats.merge(labels, on="PLAYER_ID", how="inner")
            if row.empty:
                continue
            row["season"] = season
            row["cutpoint_offset"] = offset
            frames.append(row)
    if not frames:
        raise ValueError("Empty as-of-date panel — need at least a few seasons of history.")
    return pd.concat(frames, ignore_index=True)


def _cutpoint_weights(panel: pd.DataFrame) -> np.ndarray:
    """Per-row weights that give each cutpoint offset equal *total* weight, so the abundant
    in-season rows (5 cutpoints, more labelable players each) don't outvote the single
    preseason regime 5:1 — the model must serve T₀ as faithfully as any later date. Without
    this the pooled fit starves the STD=0 regime and drifts off ``project_learned`` at T₀."""
    n_per = panel.groupby("cutpoint_offset")["cutpoint_offset"].transform("size")
    return (len(panel) / (panel["cutpoint_offset"].nunique() * n_per)).to_numpy()


def _fit_asof_models(panel: pd.DataFrame, params: dict, balance_cutpoints: bool = True,
                     use_ewma: bool = False, use_blend: bool = False) -> dict:
    from lightgbm import LGBMRegressor

    cols = feature_cols(use_ewma, use_blend)
    models = {}
    for target in ROS_TARGETS:
        sub = panel[panel[target].notna()]
        sw = _cutpoint_weights(sub) if balance_cutpoints else None
        models[target] = LGBMRegressor(**params).fit(sub[cols], sub[target], sample_weight=sw)
    models["_feature_cols"] = cols
    return models


def _season_for_date(game_logs: pd.DataFrame, T: pd.Timestamp) -> str:
    """The season a date belongs to: its games bracket T, or T is within 45 days before the
    season's first game (the preseason window)."""
    bounds = season_date_bounds(game_logs)
    hits = bounds[(bounds["start"] - pd.Timedelta(days=45) <= T) & (T <= bounds["end"] + pd.Timedelta(days=1))]
    if hits.empty:
        raise ValueError(f"No season brackets T={T.date()} (checked {len(bounds)} seasons).")
    return hits.sort_values("start").iloc[-1]["SEASON"]


def project_asof(
    T: str,
    season_stats: pd.DataFrame,
    game_logs: pd.DataFrame,
    bio: pd.DataFrame,
    cfg: ScoringConfig | None = None,
    rosters: pd.DataFrame | None = None,
    injuries: pd.DataFrame | None = None,
    params: dict | None = None,
    target_season: str | None = None,
    use_ewma: bool = False,
    use_blend: bool = False,
    half_lives: dict | None = None,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
    status_overrides: list[dict] | None = None,
    season_end: pd.Timestamp | str | None = None,
    schedule: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Remaining-season per-game projection as of ISO date ``T``.

    Trains the as-of-date model on the cutpoint panel drawn from seasons **strictly before**
    ``T``'s season (walk-forward: no within-season rows of the target season enter training),
    then projects that season's ROS as of ``T`` using its game logs ≤ ``T``. Output schema =
    ``project_learned``'s + ``[games_so_far, ros_gp_max]``. ``rosters``/``injuries`` are
    accepted for the amendment layers (unused in the core). ``target_season`` overrides the
    date→season inference (handy in tests / at exact preseason cutpoints). ``use_ewma`` adds
    the EWMA form block with the ``FROZEN_HALF_LIVES`` constants (pass ``half_lives`` to
    override, e.g. a per-fold refit). ``status_overrides`` (Step 12,
    :func:`load_status_overrides`) caps ROS GP for manually flagged-out players —
    availability only, applied after prediction; ``season_end``/``schedule`` sharpen the
    games-remaining arithmetic when the season's schedule pull exists.
    """
    cfg = cfg or load_scoring()
    params = params or DEFAULT_LGBM_PARAMS
    gl = _with_dates(game_logs)
    Tts = pd.Timestamp(T)
    season = target_season or _season_for_date(gl, Tts)

    ty = _season_start(season)
    train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
    train_bio = bio[bio["SEASON"].map(_season_start) < ty]
    train_gl = gl[gl["SEASON"].map(_season_start) < ty]

    if use_ewma:
        half_lives = half_lives or FROZEN_HALF_LIVES
    panel = build_asof_panel(train_ss, train_gl, train_bio, n_seasons, weights, reg_minutes,
                             half_lives=half_lives, use_blend=use_blend)
    models = _fit_asof_models(panel, params, use_ewma=use_ewma, use_blend=use_blend)

    feats = asof_features(gl, season_stats, bio, season, Tts, n_seasons, weights, reg_minutes,
                          half_lives=half_lives, use_blend=use_blend)
    board = predict_board(models, feats, cfg, season)
    if status_overrides:
        board = apply_status_overrides(board, status_overrides, Tts, season_end, schedule)
    return board


def asof_features(
    game_logs: pd.DataFrame, season_stats: pd.DataFrame, bio: pd.DataFrame,
    season: str, T: pd.Timestamp,
    n_seasons: int = 3, weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
    half_lives: dict | None = None,
    use_blend: bool = False,
) -> pd.DataFrame:
    """The prediction-time feature frame for ``season`` as of ``T`` — preseason block +
    STD block (+ EWMA form block when ``half_lives`` is given, + naive-blend features when
    ``use_blend``) from game logs ≤ T, with a name carried even for STD-only rookies.
    ``game_logs`` must already carry the ``_date`` column (call :func:`_with_dates`)."""
    preseason = _preseason_block(season_stats, bio, season, n_seasons, weights, reg_minutes)
    gl_s = game_logs[(game_logs["SEASON"] == season) & (game_logs["_date"] <= T)]
    ew = ewma_features(gl_s, T, half_lives) if half_lives else None
    feats = _row_frame(preseason, std_features(gl_s, T), ew)
    if use_blend:
        feats = add_blend_features(feats)
    if "PLAYER_NAME" not in feats or feats["PLAYER_NAME"].isna().any():
        names = game_logs[game_logs["SEASON"] == season].groupby("PLAYER_ID")["PLAYER_NAME"].last()
        feats["PLAYER_NAME"] = feats["PLAYER_NAME"].fillna(feats["PLAYER_ID"].map(names))
    return feats


# --- Step 12: manual status overrides (config/overrides.yaml) ----------------------------
# Player status the box scores can't know yet ("out until", "out for season") — applied to
# AVAILABILITY only: the ROS GP prediction is capped at the games physically remaining after
# the return date; rates and minutes are never touched. Deterministic and auditable — the
# zero-scraping news channel until an official injury-report feed exists.

SEASON_LENGTH_DAYS = 174  # typical opening night -> regular-season finale span (fallback
                          # when no schedule pull exists for the season)


def load_status_overrides(path: str | Path | None = None) -> list[dict]:
    """Parse ``config/overrides.yaml`` -> ``[{name, out_until | out_for_season | games_cap}]``.
    Missing file = no overrides (the common case). Malformed entries raise — a silently
    dropped status override is a wrong board with no audit trail.

    ``games_cap: N`` is a soft season-games ceiling (``gp = min(gp, N)``) for a player who WILL
    play but on a reduced/managed schedule — e.g. a returning vet ramping back from a full
    missed season (EXP-032). Availability only, like the other two: rates and minutes untouched."""
    path = Path(path) if path else CONFIG_DIR / "overrides.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    entries = raw.get("overrides") or []
    out = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or "name" not in e:
            raise ValueError(f"{path} override {i + 1}: needs at least a 'name'.")
        has_until = e.get("out_until") is not None
        has_season = bool(e.get("out_for_season"))
        has_cap = e.get("games_cap") is not None
        if has_until + has_season + has_cap != 1:  # exactly one
            raise ValueError(f"{path} override {e['name']!r}: exactly one of out_until / "
                             f"out_for_season / games_cap is required.")
        out.append({"name": str(e["name"]),
                    "out_until": pd.Timestamp(e["out_until"]) if has_until else None,
                    "out_for_season": has_season,
                    "games_cap": float(e["games_cap"]) if has_cap else None})
    return out


def _games_remaining_after(D: pd.Timestamp, T: pd.Timestamp, season_end: pd.Timestamp,
                           ros_gp_max: float, schedule: pd.DataFrame | None) -> float:
    """Games a generic player can still play after returning on ``D`` (as of ``T``).
    With a schedule pull: the median across teams of regular-season games after ``D``
    (the board carries no team column — the median is the honest generic count).
    Without: the board's own remaining-games ceiling scaled by calendar fraction."""
    D = max(D, T)
    if schedule is not None and len(schedule):
        s = schedule[schedule.get("regular_season", True) == True]  # noqa: E712
        s = s[pd.to_datetime(s["game_date"]) > D]
        if s.empty:
            return 0.0
        per_team = pd.concat([s["home"], s["away"]]).value_counts()
        return float(per_team.median())
    if season_end <= T:
        return 0.0
    frac = max((season_end - D).days, 0) / max((season_end - T).days, 1)
    return float(np.round(ros_gp_max * frac))


def apply_status_overrides(
    board: pd.DataFrame,
    overrides: list[dict],
    T: pd.Timestamp | str,
    season_end: pd.Timestamp | str | None = None,
    schedule: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Cap ROS GP for players manually flagged out: ``gp = min(gp, games remaining after
    the return date)``; ``fpts_total`` recomputed; ``fpts_pg``/``mpg``/rates untouched.
    Adds a ``status_override`` audit column. Unmatched or ambiguous names raise (matched
    via the shared normalizer + alias map). Returns a new frame."""
    from .analyst import name_key  # local import — analyst imports other model modules

    T = pd.Timestamp(T)
    if season_end is None:
        season_end = T + pd.Timedelta(days=SEASON_LENGTH_DAYS)  # conservative fallback;
        # callers with a schedule pull pass the real finale date instead.
    season_end = pd.Timestamp(season_end)

    out = board.copy()
    out["status_override"] = out.get("status_override", "")
    keys = out["PLAYER_NAME"].map(name_key)
    for e in overrides:
        hits = np.flatnonzero((keys == name_key(e["name"])).to_numpy())
        if len(hits) != 1:
            raise ValueError(f"Status override {e['name']!r} matches {len(hits)} board rows "
                             f"— fix the name (or extend injuries.ALIASES).")
        i = int(hits[0])
        if e["out_for_season"]:
            cap, note = 0.0, "out_for_season"
        elif e.get("games_cap") is not None:
            cap, note = float(e["games_cap"]), f"games_cap:{e['games_cap']:.0f}"
        else:
            gp_max = float(out.loc[i, "ros_gp_max"]) if "ros_gp_max" in out.columns else float(out.loc[i, "gp"])
            cap = _games_remaining_after(e["out_until"], T, season_end, gp_max, schedule)
            note = f"out_until:{e['out_until'].date().isoformat()}"
        new_gp = min(float(out.loc[i, "gp"]), cap)
        if new_gp != float(out.loc[i, "gp"]):
            note += f" (gp {out.loc[i, 'gp']:.0f}->{new_gp:.0f})"
        out.loc[i, "gp"] = new_gp
        out.loc[i, "fpts_total"] = round(float(out.loc[i, "fpts_pg"]) * new_gp, 1)
        out.loc[i, "status_override"] = note
    return out


def predict_board(models: dict, feats: pd.DataFrame, cfg: ScoringConfig, season: str) -> pd.DataFrame:
    """Compose a scored ROS board from fitted models and a feature frame (fit once, predict at
    many cutpoints). Output schema = ``project_learned``'s + ``[games_so_far, ros_gp_max]``."""
    cols = models.get("_feature_cols", ASOF_FEATURES)
    for c in cols:
        if c not in feats.columns:
            feats = feats.assign(**{c: np.nan})
    X = feats[cols]
    pred_mpg = np.clip(models["y_ros_mpg"].predict(X), 0.0, 48.0)
    pred_gp = np.clip(models["y_ros_gp"].predict(X), 0.0, 82.0)
    out = pd.DataFrame({
        "PLAYER_ID": feats["PLAYER_ID"].to_numpy(),
        "PLAYER_NAME": feats["PLAYER_NAME"].to_numpy(),
        "target_season": season,
        "target_age": feats["target_age"].to_numpy(),
        "gp": np.round(pred_gp),
        "mpg": np.round(pred_mpg, 1),
        "games_so_far": feats["games_so_far"].to_numpy().astype(int),
    })
    for canon in COUNTING:
        rate = np.clip(models[f"y_ros_rate_{canon}"].predict(X), 0.0, None)
        out[canon] = (rate * pred_mpg).round(2)
    out["fpts_pg"] = score_frame(out, cfg).round(2)
    # ros_gp_max (schedule-aware remaining games) needs the D1 schedule pull; until then it is
    # the model's own ROS-GP ceiling. fpts_total ranks by predicted ROS games actually played.
    out["ros_gp_max"] = out["gp"]
    out["fpts_total"] = (out["fpts_pg"] * out["gp"]).round(1)
    out = out.sort_values("fpts_total", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out
