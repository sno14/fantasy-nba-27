"""Selection-floor simulation for the mover buckets (EXP-011a / implementation-plan Step 2).

The mover eval buckets players by **realized** year-over-year change, so the "big riser"
bucket is selected partly on positive outcome shocks (mid-season teammate injuries, luck).
Even a perfect conditional-mean forecaster therefore shows *negative* signed bias in the
riser buckets and positive in the faller buckets — part of the measured tail bias is
mathematically irreducible (docs/breakthrough-plan.md §1c).

This module estimates that **floor**: treat the (debiased) model projections as the true
conditional means, resample the model's own residuals as the irreducible shock, re-bucket on
the synthetic outcomes, and measure the bias the by-construction-perfect forecaster shows.
Every later experiment's per-bucket bias is then judged against this floor, not against zero:

    reducible_gap  = measured_bias − floor_bias
    fraction_closed = (bias_old − bias_new) / (bias_old − floor_bias)

Honest caveat (log it with every use): the floor scales with the residual spread of the
*current* model — a genuinely better model shrinks residuals and therefore the floor. Hence
the ``sigma_scale`` sensitivity band, and the rule that the floor is **recomputed whenever a
new default model is adopted** (implementation-plan Step 2).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .eval_movers import BUCKET_LABELS, DEFAULT_BUCKET_EDGES

SIGMA_SCALES = (0.75, 1.0, 1.25)


def selection_floor(
    pool: pd.DataFrame,
    n_draws: int = 1000,
    seed: int = 0,
    sigma_scale: float = 1.0,
    edges: tuple[float, ...] = DEFAULT_BUCKET_EDGES,
) -> pd.DataFrame:
    """Per-bucket signed bias of an oracle forecaster under outcome-conditioned bucketing.

    ``pool`` is one model×season ``eval_movers.pool_frame`` output (needs ``fpts_pg``,
    ``act_fpts_pg``, ``prior_fpts_pg``, ``err``); concatenate seasons for a pooled floor.

    Method (exactly the Step-2 spec): debias the projection to get the synthetic truth
    ``mu``; resample the *centered empirical residuals* (preserves skew/fat tails — no
    normality assumption) scaled by ``sigma_scale``; bucket each synthetic outcome by its
    synthetic delta; report the oracle's per-bucket signed bias / MAE pooled over draws.

    Returns one row per bucket: ``floor_bias``, ``floor_MAE``, ``n_mean`` (expected bucket
    occupancy per draw).
    """
    mu = pool["fpts_pg"].to_numpy(dtype=float) - float(pool["err"].mean())
    resid = pool["act_fpts_pg"].to_numpy(dtype=float) - mu
    resid = resid - resid.mean()
    prior = pool["prior_fpts_pg"].to_numpy(dtype=float)
    n = len(pool)

    rng = np.random.default_rng(seed)
    synth = mu[None, :] + sigma_scale * rng.choice(resid, size=(n_draws, n), replace=True)
    delta = synth - prior[None, :]
    err = mu[None, :] - synth  # oracle's error: conditional mean minus realized

    # np.digitize codes: 0 = below first edge (big faller) ... len(edges) = big riser.
    codes = np.digitize(delta, bins=np.asarray(edges), right=False)
    rows = []
    for code, label in enumerate(BUCKET_LABELS):
        mask = codes == code
        occupancy = mask.sum()
        rows.append({
            "bucket": label,
            "floor_bias": float(err[mask].mean()) if occupancy else np.nan,
            "floor_MAE": float(np.abs(err[mask]).mean()) if occupancy else np.nan,
            "n_mean": occupancy / n_draws,
        })
    return pd.DataFrame(rows)


def floor_table(
    pool: pd.DataFrame,
    n_draws: int = 1000,
    seed: int = 0,
    sigma_scales: tuple[float, ...] = SIGMA_SCALES,
) -> pd.DataFrame:
    """The Step-2 sensitivity band: :func:`selection_floor` at each ``sigma_scale``, stacked.
    The 1.0 row is the headline; 0.75/1.25 bound how much the floor moves if the true
    irreducible spread is smaller/larger than the current model's residuals."""
    frames = []
    for s in sigma_scales:
        f = selection_floor(pool, n_draws=n_draws, seed=seed, sigma_scale=s)
        f.insert(0, "sigma_scale", s)
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def reducible_gap(measured: pd.DataFrame, floor: pd.DataFrame) -> pd.DataFrame:
    """Join a model's measured per-bucket ``signed_bias`` (the eval's ``per_bucket`` rows for
    one model) with the ``sigma_scale == 1.0`` floor and derive the gap every gate uses."""
    f = floor[floor["sigma_scale"] == 1.0][["bucket", "floor_bias"]] if "sigma_scale" in floor else floor
    out = measured.merge(f, on="bucket", how="left")
    out["reducible_gap"] = out["signed_bias"] - out["floor_bias"]
    return out
