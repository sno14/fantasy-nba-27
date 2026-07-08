"""Mover-segmented, draftable-pool evaluation (ROADMAP Stage 7.0 / EXP-006, extended Step 1–3).

The ranking backtest (``backtest.py``) answers "did we rank the stable core right?" and is,
by construction, availability-dominated and **blind to risers and fallers** (EXP-003 ledger
note). This module answers the question Stage 7 actually cares about: **do we get a player's
production *level* right, especially when that level is changing?**

Method (preseason / across-season form):
  * Project ``target_season`` using only prior-season data (shared no-leakage path,
    ``backtest.project_models``).
  * Take each model's own **draftable pool** — top ``pool_top_n`` by projected fantasy total.
  * Every player in the pool has a **prior-season actual** per-game level (the season before
    the target). Define
        actual_delta = actual_pg(target) - prior_pg      (how much the player really moved)
        proj_delta   = proj_pg          - prior_pg        (how much we *said* he'd move)
  * **Bucket players by actual_delta** (big fallers … stable … big risers) and report, per
    bucket, the per-game **level** error (MAE/RMSE) and — the headline — the **signed bias**
    ``mean(proj_pg - actual_pg)``. Shrinking that per-bucket bias *toward the EXP-011 floor*
    (see ``floor_sim.py`` — outcome-conditioned buckets make part of it irreducible) is the
    deliverable.
  * **Directional capture:** does proj_delta even point the right way? Report corr(proj_delta,
    actual_delta) and the fraction of players moved in the correct direction.
  * **Predicted-Δ calibration (Step 1, selection-free):** bucket by ``proj_delta`` instead —
    "when we *say* a player rises ~5, does he?" ``calib_gap = mean_actual_delta −
    mean_proj_delta`` per predicted bucket has no outcome-selection effect and is fully
    reducible in principle.
  * **Oracles (Step 3):** ``oracle_variant`` swaps in actual minutes (rates held) or actual
    rates (minutes held) to decompose the reducible gap into minutes- vs rate-driven shares.

In-season as-of-date cutpoints (the waiver use) arrive with implementation-plan Step 10/11.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame
from ._core import COUNTING, _season_start
from .backtest import _actual, project_models


def _season_before(season: str) -> str:
    """'2024-25' -> '2023-24'."""
    start = _season_start(season) - 1
    return f"{start}-{str(start + 1)[-2:]}"


# Default actual-delta bucket edges in fantasy-points-per-game. Chosen once around the
# roughly symmetric spread of YoY per-game changes in the draftable pool; ``run_mover_eval``
# labels are derived from these so the buckets stay stable across seasons (quantile edges
# would drift season to season and make per-bucket bias incomparable).
DEFAULT_BUCKET_EDGES = (-6.0, -2.0, 2.0, 6.0)
BUCKET_LABELS = ("big faller", "faller", "stable", "riser", "big riser")


def _bucket(delta: pd.Series, edges=DEFAULT_BUCKET_EDGES) -> pd.Series:
    bins = [-np.inf, *edges, np.inf]
    return pd.cut(delta, bins=bins, labels=BUCKET_LABELS)


def pool_frame(
    proj: pd.DataFrame,
    prior: pd.DataFrame,
    actual: pd.DataFrame,
    pool_top_n: int,
    pool: str = "model",
) -> pd.DataFrame:
    """The shared per-model frame behind every Stage-7 metric.

    ``pool="model"`` (default): top-``pool_top_n`` of ``proj`` by projected total (its
    ``rank``). ``pool="actual"`` (critique §3.2 recall view): the **realized** top-``pool_top_n``
    by ``act_fpts_total`` — the sleepers the model never ranked are otherwise invisible, so the
    model-pool riser bias is *understated*. Either selection is inner-joined to ``prior``
    (``[PLAYER_ID, prior_fpts_pg]`` — so "mover" is defined) and ``actual``
    (``[PLAYER_ID, act_fpts_pg, act_fpts_total]`` — so the outcome exists), with
    ``actual_delta``, ``proj_delta``, ``err`` and the actual-Δ ``bucket`` derived.
    """
    if pool == "actual":
        base = (
            actual.nlargest(pool_top_n, "act_fpts_total")[["PLAYER_ID"]]
            .merge(proj[["PLAYER_ID", "fpts_pg"]], on="PLAYER_ID", how="inner")
        )
    elif pool == "model":
        base = proj.nsmallest(pool_top_n, "rank")[["PLAYER_ID", "fpts_pg"]]
    else:
        raise ValueError(f"pool must be 'model' or 'actual', got {pool!r}")
    m = base.merge(prior, on="PLAYER_ID", how="inner").merge(
        actual[["PLAYER_ID", "act_fpts_pg"]], on="PLAYER_ID", how="inner"
    )
    m["actual_delta"] = m["act_fpts_pg"] - m["prior_fpts_pg"]
    m["proj_delta"] = m["fpts_pg"] - m["prior_fpts_pg"]
    m["err"] = m["fpts_pg"] - m["act_fpts_pg"]
    m["bucket"] = _bucket(m["actual_delta"])
    return m


def _actual_lines(season_stats: pd.DataFrame, season: str) -> pd.DataFrame:
    """Actual per-game stat lines (one column per COUNTING stat, prefixed ``act_``) + act_mpg,
    for the oracle variants."""
    cols = ["GP", "MIN"] + list(COUNTING.values())
    a = season_stats[season_stats["SEASON"] == season].groupby("PLAYER_ID", as_index=False)[cols].sum()
    a = a[a["GP"] > 0].copy()
    out = pd.DataFrame({"PLAYER_ID": a["PLAYER_ID"], "act_mpg": a["MIN"] / a["GP"]})
    for canon, src in COUNTING.items():
        out[f"act_{canon}"] = (a[src] / a["GP"]).to_numpy()
    return out


def oracle_variant(
    proj: pd.DataFrame,
    actual_lines: pd.DataFrame,
    cfg: ScoringConfig,
    kind: str,
) -> pd.DataFrame:
    """EXP-011b oracle projections built from a real model's board (Step 3).

    * ``kind='minutes'`` — rescale every projected stat by ``act_mpg / mpg`` (rates held as
      projected, minutes replaced by the truth) and **re-score via** ``score_frame`` (bonuses
      make scoring non-linear — never scale ``fpts_pg`` directly).
    * ``kind='rates'``   — replace each per-game stat with the actual line scaled back to the
      projected minutes (``act_stat × mpg / act_mpg``): rates replaced by truth, minutes held.

    The returned frame keeps the base model's ``rank`` so pool selection stays on the *real*
    board — pooling on oracle ranks would select on the outcome. Players with no actuals drop.
    """
    if kind not in ("minutes", "rates"):
        raise ValueError(f"kind must be 'minutes' or 'rates', got {kind!r}")
    m = proj.merge(actual_lines, on="PLAYER_ID", how="inner").copy()
    m = m[(m["mpg"] > 0) & (m["act_mpg"] > 0)]

    out = m[["rank", "PLAYER_ID", "PLAYER_NAME"]].copy()
    if kind == "minutes":
        ratio = m["act_mpg"] / m["mpg"]
        for canon in COUNTING:
            out[canon] = m[canon] * ratio
    else:
        ratio = m["mpg"] / m["act_mpg"]
        for canon in COUNTING:
            out[canon] = m[f"act_{canon}"] * ratio
    out["fpts_pg"] = score_frame(out, cfg)
    return out


def run_mover_eval(
    target_season: str,
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    cfg: ScoringConfig | None = None,
    pool_top_n: int = 150,
    min_prior_minutes: float = 500.0,
    game_logs: pd.DataFrame | None = None,
    variants: list[str] | dict[str, dict] | None = None,
    oracles: bool = False,
    seed: int | None = None,
    return_pools: bool = False,
    pool: str = "model",
):
    """Mover-segmented level accuracy for one target season.

    Returns ``(per_bucket, directional, per_pred_bucket)`` — plus a ``{model: pool_frame}``
    dict when ``return_pools`` (feeds the floor simulation and the bootstrap CI):
      * ``per_bucket`` — one row per (model, actual-Δ bucket): n, level MAE/RMSE,
        signed bias (proj_pg - act_pg), and mean actual/proj delta.
      * ``directional`` — one row per model: pool size, overall level MAE/bias, delta
        correlation, and directional sign-agreement fraction.
      * ``per_pred_bucket`` — one row per (model, predicted-Δ bucket): the selection-free
        calibration table (``calib_gap = mean_actual_delta − mean_proj_delta``).

    ``variants`` selects extra learned-model configurations by registry name (or as custom
    kwarg dicts) — see ``backtest.VARIANT_SPECS``. ``oracles`` adds the EXP-011b
    minutes/rates oracle rows built from the ``learned`` board. ``seed`` overrides the
    LightGBM ``random_state`` for every learned-family model (the seed-stability protocol).
    ``pool="actual"`` scores the same three tables on the **realized** top-N (recall view,
    critique §3.2); ``directional`` then carries a ``recall`` column — the fraction of the
    realized top-N the model actually ranked into its own top-N.
    """
    cfg = cfg or load_scoring()
    projections = project_models(
        target_season, season_stats, bio, cfg,
        game_logs=game_logs, variants=variants, seed=seed,
    )
    if oracles:
        lines = _actual_lines(season_stats, target_season)
        for kind in ("minutes", "rates"):
            projections[f"oracle_{kind}(learned)"] = oracle_variant(
                projections["learned"], lines, cfg, kind
            )

    actual = _actual(season_stats, target_season, cfg, min_minutes=0.0)[
        ["PLAYER_ID", "act_fpts_pg", "act_fpts_total"]
    ]
    actual_top_ids = set(actual.nlargest(pool_top_n, "act_fpts_total")["PLAYER_ID"])
    prior_season = _season_before(target_season)
    prior = _actual(season_stats, prior_season, cfg, min_minutes=min_prior_minutes)[
        ["PLAYER_ID", "act_fpts_pg"]
    ].rename(columns={"act_fpts_pg": "prior_fpts_pg"})

    bucket_rows: list[pd.DataFrame] = []
    pred_rows: list[pd.DataFrame] = []
    dir_rows: list[dict] = []
    pools: dict[str, pd.DataFrame] = {}
    for name, proj in projections.items():
        m = pool_frame(proj, prior, actual, pool_top_n, pool=pool)
        if m.empty:
            continue
        pools[name] = m
        model_top_ids = set(proj.nsmallest(pool_top_n, "rank")["PLAYER_ID"])
        recall = len(actual_top_ids & model_top_ids) / len(actual_top_ids)

        g = m.groupby("bucket", observed=False)
        per = pd.DataFrame({
            "model": name,
            "bucket": BUCKET_LABELS,
            "n": g.size().reindex(BUCKET_LABELS).values,
            "level_MAE": g["err"].apply(lambda e: e.abs().mean()).reindex(BUCKET_LABELS).values,
            "level_RMSE": g["err"].apply(lambda e: np.sqrt((e ** 2).mean())).reindex(BUCKET_LABELS).values,
            "signed_bias": g["err"].mean().reindex(BUCKET_LABELS).values,
            "mean_actual_delta": g["actual_delta"].mean().reindex(BUCKET_LABELS).values,
            "mean_proj_delta": g["proj_delta"].mean().reindex(BUCKET_LABELS).values,
        })
        bucket_rows.append(per)

        pg = m.groupby(_bucket(m["proj_delta"]), observed=False)
        pred = pd.DataFrame({
            "model": name,
            "bucket": BUCKET_LABELS,
            "n": pg.size().reindex(BUCKET_LABELS).values,
            "mean_proj_delta": pg["proj_delta"].mean().reindex(BUCKET_LABELS).values,
            "mean_actual_delta": pg["actual_delta"].mean().reindex(BUCKET_LABELS).values,
            "level_MAE": pg["err"].apply(lambda e: e.abs().mean()).reindex(BUCKET_LABELS).values,
        })
        pred["calib_gap"] = pred["mean_actual_delta"] - pred["mean_proj_delta"]
        pred_rows.append(pred)

        sign_agree = (np.sign(m["proj_delta"]) == np.sign(m["actual_delta"])).mean()
        dir_rows.append({
            "model": name,
            "pool_n": len(m),
            "level_MAE": m["err"].abs().mean(),
            "level_bias": m["err"].mean(),
            "delta_corr": m["proj_delta"].corr(m["actual_delta"]),
            "dir_sign_acc": sign_agree,
            "recall": recall,
        })

    per_bucket = pd.concat(bucket_rows, ignore_index=True)
    per_pred_bucket = pd.concat(pred_rows, ignore_index=True)
    directional = pd.DataFrame(dir_rows)
    if return_pools:
        return per_bucket, directional, per_pred_bucket, pools
    return per_bucket, directional, per_pred_bucket


def bootstrap_bias_delta_ci(
    pool_a: pd.DataFrame,
    pool_b: pd.DataFrame,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.10,
    on: tuple[str, ...] = ("PLAYER_ID",),
    cluster: str | None = None,
) -> pd.DataFrame:
    """Paired bootstrap CI for the per-bucket signed-bias difference between two models.

    Bucket-bias deltas of a few tenths of a fpt/g can be noise at bucket sizes of tens —
    this is the noise guard the adopt gates use. Pairs the two pools on ``on`` (add
    ``"season"`` for pooled multi-season frames), buckets by the **shared** actual delta,
    and bootstraps ``mean(err_b) − mean(err_a)`` within each bucket. Returns one row per
    bucket: n, observed ``bias_delta``, ``ci_lo``/``ci_hi`` (the (1−alpha) interval).
    A CI straddling 0 means the difference is not resolved at these sample sizes.

    ``cluster`` (design-critique §3.3): panel rows are not independent — the same player
    repeats across seasons with autocorrelated residuals. For pooled multi-season frames
    pass ``cluster="PLAYER_ID"`` to resample whole clusters instead of rows (row bootstrap
    understates the interval width when rows share a cluster).
    """
    a = pool_a[list(on) + ["err", "actual_delta"]].rename(columns={"err": "err_a"})
    b = pool_b[list(on) + ["err"]].rename(columns={"err": "err_b"})
    m = a.merge(b, on=list(on), how="inner")
    m["bucket"] = _bucket(m["actual_delta"])
    m["_diff"] = m["err_b"] - m["err_a"]

    rng = np.random.default_rng(seed)
    rows = []
    for label in BUCKET_LABELS:
        sub = m[m["bucket"] == label]
        n = len(sub)
        if n == 0:
            rows.append({"bucket": label, "n": 0, "bias_delta": np.nan,
                         "ci_lo": np.nan, "ci_hi": np.nan})
            continue
        if cluster is None:
            diff = sub["_diff"].to_numpy(dtype=float)
            idx = rng.integers(0, n, size=(n_boot, n))
            boots = diff[idx].mean(axis=1)
        else:
            # Cluster bootstrap: resample clusters; each draw's mean is the size-weighted
            # mean over the drawn clusters (Σ sums / Σ counts).
            g = sub.groupby(cluster)["_diff"].agg(["sum", "count"])
            sums, counts = g["sum"].to_numpy(float), g["count"].to_numpy(float)
            k = len(g)
            idx = rng.integers(0, k, size=(n_boot, k))
            boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
        rows.append({
            "bucket": label, "n": n, "bias_delta": float(sub["_diff"].mean()),
            "ci_lo": float(np.quantile(boots, alpha / 2)),
            "ci_hi": float(np.quantile(boots, 1 - alpha / 2)),
        })
    return pd.DataFrame(rows)
