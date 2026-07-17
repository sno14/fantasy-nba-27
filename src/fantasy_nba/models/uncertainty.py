"""Risk ranges: floor / median / ceiling season totals via Monte Carlo.

Why this exists
---------------
The top-100 backtest showed season fantasy *totals* are dominated by **games played**, which is
nearly unpredictable from box scores (fit R^2 ~ 0.03). A single projected total therefore hides
the thing that most decides draft value: availability risk. Rather than pretend to a point
estimate, we simulate each player's season and report a distribution — so a durable 70-game
player is visibly safer than a boom/bust 55-game star with the same median.

Model
-----
For each player we draw ``n_sims`` seasons:

* **Games played** — sample from the *empirical* distribution of actual GP for draftable
  players (built no-leakage from training seasons), then scale it multiplicatively to the
  player's own projected GP (``proj_gp / pool_median``). This keeps the real, left-skewed injury
  shape (long tail of lost seasons) while letting durability projections shift a player up or
  down. Older players optionally draw from an age-appropriate pool with a fatter left tail;
  with an injury profile (EXP-015 / 7.3b, adopted) the pool buckets by (age × chronic flag).
* **Per-game value** — two paths (Step 14 / EXP-021):

  - **Constant-σ default** (no ``pg_quantiles``): normal around the projected per-game
    fantasy points with sd ``sd_pg`` (the hand-set ``SD_PG = 9`` spread). **This remains
    the default board's spread** — EXP-021 (2026-07-10) rejected the learned replacement:
    total-level dispersion rises era-over-era, so the honestly-lagged learned width
    under-covers; SD_PG's excess width over the true per-game marginal is load-bearing
    (it absorbs the GP × per-game covariance this independent Monte Carlo drops).
  - **Learned ranges** (opt-in, pass a ``pg_quantiles`` frame; re-arm post-2026-27 per the
    EXP-021 ledger note): draw from the piecewise-linear CDF through the player's
    ``fpts_pg_q25/50/75/90`` columns — built by :func:`pg_quantile_frame` from the
    **empirical residual CDF** of walk-forward out-of-sample learned-model residuals
    (:func:`residual_pool`, width-calibrated via :func:`calibrate_resid_scale`). Tails
    extend linearly with the adjacent segment's slope, floored at 0. Per the EXP-013c
    replacement note this CDF — never the rejected quantile heads — is the range source.

``total = per_game_draw * games_draw``; percentiles over the sims give floor / median / ceiling.
Games dominates the spread, exactly as the finding says it should.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._core import _season_start
from .quantiles import QUANTILES as PG_QUANTILES
from .quantiles import quantile_col

MODERN_FROM = 2021  # season-start year: the current lower-availability era (post-covid)
COVID_SEASONS = ("2019-20", "2020-21")
# Prior-season minutes to qualify for the GP pool. 2000 ≈ genuine starters/stars, the tier we
# apply ranges to; a marginal-rotation pool (1000) has a fatter injury tail and mis-calibrates.
DRAFTABLE_MIN_MINUTES = 2000.0
# Residual per-game uncertainty, in fantasy points. NOT just the ~5.6 per-game projection RMSE —
# it's tuned so the resulting *season-total* p10–p90 band covers ~80% on the top-100 backtest, so
# it also absorbs the total-level variance the marginal GP pool misses (breakouts, role changes,
# model bias, and season-wide common health shocks that move a whole cohort together).
SD_PG = 9.0
DEFAULT_QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
SEASON_GAMES = 82


def build_gp_pool(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    max_start_year: int | None = None,
    modern_from: int = MODERN_FROM,
    min_prev_minutes: float = DRAFTABLE_MIN_MINUTES,
    injury_profile: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Empirical actual-GP outcomes for *draftable* players, one row per qualifying player-season.

    A player-season qualifies if the player logged ``>= min_prev_minutes`` the *previous* season
    (i.e. was rotation-caliber and thus draftable). Restricted to the modern, non-covid era and —
    for no-leakage backtesting — to seasons strictly before ``max_start_year``. Columns: ``GP``,
    ``AGE``.

    ``injury_profile`` (EXP-015 / 7.3b): a ``[SEASON, PLAYER_ID, inj_chronic_flag]`` frame
    (``injuries.chronic_flag_table``, as-of each season's Oct 1 — no leakage) adds a ``CHRONIC``
    column so :func:`simulate_ranges` can bucket by (age × chronic) instead of age alone.
    """
    g = season_stats.groupby(["PLAYER_ID", "SEASON"], as_index=False).agg(GP=("GP", "sum"), MIN=("MIN", "sum"))
    ages = bio[["PLAYER_ID", "SEASON", "AGE"]].drop_duplicates(["PLAYER_ID", "SEASON"])
    g = g.merge(ages, on=["PLAYER_ID", "SEASON"], how="left")
    g["yr"] = g["SEASON"].map(_season_start)

    prev = g[["PLAYER_ID", "yr", "MIN"]].copy()
    prev["yr"] = prev["yr"] + 1
    d = g.merge(prev.rename(columns={"MIN": "MIN_prev"}), on=["PLAYER_ID", "yr"], how="inner")
    d = d[d["MIN_prev"] >= min_prev_minutes]
    d = d[~d["SEASON"].isin(COVID_SEASONS)]
    d = d[d["yr"] >= modern_from]
    if max_start_year is not None:
        d = d[d["yr"] < max_start_year]
    if d.empty:  # early backtest seasons may predate the modern window — fall back to all non-covid
        d = g[~g["SEASON"].isin(COVID_SEASONS)]
        if max_start_year is not None:
            d = d[d["yr"] < max_start_year]
    cols = ["GP", "AGE"]
    if injury_profile is not None:
        d = d.merge(injury_profile[["SEASON", "PLAYER_ID", "inj_chronic_flag"]],
                    on=["SEASON", "PLAYER_ID"], how="left")
        d["CHRONIC"] = d["inj_chronic_flag"].fillna(0).astype(int)
        cols.append("CHRONIC")
    return d[cols].reset_index(drop=True)


def _age_bucket(age: np.ndarray) -> np.ndarray:
    # Older players carry a fatter left (injury) tail; bucket so they sample from their own pool.
    return np.where(age <= 29, 0, np.where(age <= 33, 1, 2))


def _learned_board(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    season: str,
    cfg,
    params: dict | None,
    seed: int,
    board_cache: dict[str, pd.DataFrame] | None,
) -> pd.DataFrame:
    """Walk-forward learned board for ``season`` (training strictly before it), via the cache."""
    board = board_cache.get(season) if board_cache is not None else None
    if board is None:
        from .learned import DEFAULT_LGBM_PARAMS, project_learned

        sy = _season_start(season)
        tr_ss = season_stats[season_stats["SEASON"].map(_season_start) < sy]
        tr_bio = bio[bio["SEASON"].map(_season_start) < sy]
        board = project_learned(
            tr_ss, tr_bio, season, cfg=cfg,
            params={**(params or DEFAULT_LGBM_PARAMS), "random_state": seed},
        )
        if board_cache is not None:
            board_cache[season] = board
    return board


def _walkforward_seasons(season_stats: pd.DataFrame, target_season: str, n_seasons: int) -> list[str]:
    """The ``n_seasons`` completed seasons immediately before ``target_season``, each with at
    least one training season before it."""
    ty = _season_start(target_season)
    seasons = sorted(
        {s for s in season_stats["SEASON"].unique() if _season_start(s) < ty},
        key=_season_start,
    )
    out = [s for s in seasons[-n_seasons:] if _season_start(s) > _season_start(seasons[0])]
    if not out:
        raise ValueError(f"no walk-forward seasons available before {target_season}")
    return out


def residual_pool(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    target_season: str,
    cfg=None,
    *,
    n_seasons: int = 4,
    pool_top_n: int = 150,
    min_prior_minutes: float = 500.0,
    params: dict | None = None,
    seed: int = 0,
    board_cache: dict[str, pd.DataFrame] | None = None,
) -> np.ndarray:
    """Out-of-sample per-game residuals (``actual − projected``) feeding the learned ranges.

    The EXP-013c replacement note: the Step-14 range source is the **empirical residual
    CDF**, not learned quantile heads. This collects it honestly — for each of the
    ``n_seasons`` completed seasons immediately before ``target_season``, fit the learned
    model on strictly-prior seasons, take its own top-``pool_top_n`` pool (the same
    ``pool_frame`` construction as the mover eval), and keep ``act_fpts_pg − fpts_pg``.
    Nothing dated on/after ``target_season`` is touched.

    ``board_cache`` (optional ``{season: learned board}``): filled as a side effect, so an
    eval script sweeping several targets shares the walk-forward fits instead of refitting.
    """
    from ..scoring import load_scoring
    from .backtest import _actual
    from .eval_movers import _season_before, pool_frame

    cfg = cfg or load_scoring()
    resid_seasons = _walkforward_seasons(season_stats, target_season, n_seasons)

    parts: list[np.ndarray] = []
    for s in resid_seasons:
        board = _learned_board(season_stats, bio, s, cfg, params, seed, board_cache)
        actual = _actual(season_stats, s, cfg, min_minutes=0.0)[
            ["PLAYER_ID", "act_fpts_pg", "act_fpts_total"]
        ]
        prior = _actual(season_stats, _season_before(s), cfg, min_minutes=min_prior_minutes)[
            ["PLAYER_ID", "act_fpts_pg"]
        ].rename(columns={"act_fpts_pg": "prior_fpts_pg"})
        m = pool_frame(board, prior, actual, pool_top_n)
        parts.append((m["act_fpts_pg"] - m["fpts_pg"]).to_numpy(dtype=float))
    return np.concatenate(parts)


def pg_quantile_frame(
    proj: pd.DataFrame,
    resid: np.ndarray,
    quantiles: tuple[float, ...] = PG_QUANTILES,
) -> pd.DataFrame:
    """Per-player per-game quantile columns from the empirical residual CDF.

    ``fpts_pg_qXX = fpts_pg + quantile(resid, q)`` — one set of residual offsets shifts
    every player's point estimate (a per-player heteroscedastic version was the rejected
    EXP-013c quantile heads). Returns ``[PLAYER_ID, fpts_pg_q25, ..., fpts_pg_q90]``,
    clipped at 0, ready for ``simulate_ranges(pg_quantiles=...)``.
    """
    offsets = np.quantile(np.asarray(resid, dtype=float), quantiles)
    out = proj[["PLAYER_ID"]].copy()
    for q, off in zip(quantiles, offsets):
        out[quantile_col(q)] = (proj["fpts_pg"] + off).clip(lower=0.0)
    return out


DEFAULT_RESID_SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)


def calibrate_resid_scale(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    target_season: str,
    cfg=None,
    *,
    resid: np.ndarray,
    scales: tuple[float, ...] = DEFAULT_RESID_SCALES,
    target_coverage: float = 0.83,
    n_seasons: int = 4,
    top_n: int = 150,
    injury_profile: pd.DataFrame | None = None,
    spells: pd.DataFrame | None = None,
    params: dict | None = None,
    seed: int = 0,
    sim_seed: int = 0,
    board_cache: dict[str, pd.DataFrame] | None = None,
) -> tuple[float, pd.DataFrame]:
    """Width multiplier for the residual-CDF spread, calibrated walk-forward (EXP-021).

    Why: the raw per-game residual CDF is the *honest per-game marginal*, but the Monte
    Carlo multiplies independent per-game and GP draws — the covariance between them
    (injury rust, role shocks moving both) plus model bias made ``SD_PG = 9`` deliberately
    wider than the ~5.6 per-game residual spread. The learned replacement therefore keeps
    the empirical residual *shape* (the right-tail skew the normal can't express) and
    calibrates one width scalar so that simulated total-band [p10, p90] coverage on the
    ``n_seasons`` seasons before ``target_season`` is closest to ``target_coverage``.
    Every input is dated strictly before ``target_season`` — no leakage into the target.

    Honest caveat (for the ledger's skeptic pass): ``resid`` is typically pooled over the
    same calibration seasons, so each season's coverage uses a CDF that includes its own
    residuals (~1/n_seasons of the pool). That mildly favours fit *within* the calibration
    window but hands nothing from the target season.

    Returns ``(best_scale, table)`` where ``table`` has one row per scale with its pooled
    walk-forward coverage on each board's top-``top_n``.
    """
    from ..scoring import load_scoring
    from .backtest import _actual

    cfg = cfg or load_scoring()
    cal_seasons = _walkforward_seasons(season_stats, target_season, n_seasons)

    prepared = []
    for s in cal_seasons:
        board = _learned_board(season_stats, bio, s, cfg, params, seed, board_cache).copy()
        sy = _season_start(s)
        tr_ss = season_stats[season_stats["SEASON"].map(_season_start) < sy]
        tr_bio = bio[bio["SEASON"].map(_season_start) < sy]
        gp_pool = build_gp_pool(tr_ss, tr_bio, max_start_year=sy, injury_profile=injury_profile)
        if spells is not None:
            from .injuries import injury_features

            flags = injury_features(spells, f"{sy}-10-01")[["PLAYER_ID", "inj_chronic_flag"]]
            board = board.merge(flags, on="PLAYER_ID", how="left")
            board["inj_chronic_flag"] = board["inj_chronic_flag"].fillna(0).astype(int)
        actual = _actual(season_stats, s, cfg, min_minutes=0.0)[["PLAYER_ID", "act_fpts_total"]]
        prepared.append((board, gp_pool, actual))

    resid = np.asarray(resid, dtype=float)
    rows = []
    for scale in scales:
        covered = n_total = 0
        for board, gp_pool, actual in prepared:
            qf = pg_quantile_frame(board, resid * scale)
            sim = simulate_ranges(board, gp_pool, pg_quantiles=qf, seed=sim_seed)
            m = sim.nsmallest(top_n, "rank").merge(actual, on="PLAYER_ID", how="inner")
            covered += int(m["act_fpts_total"].between(m["fpts_p10"], m["fpts_p90"]).sum())
            n_total += len(m)
        rows.append({"scale": scale, "coverage": covered / n_total, "n": n_total})
    table = pd.DataFrame(rows)
    best = float(table.loc[(table["coverage"] - target_coverage).abs().idxmin(), "scale"])
    return best, table


def _piecewise_pg_draws(qv: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Inverse of the piecewise-linear CDF through (q25, q50, q75, q90) knots.

    ``qv``: (n, 4) row-sorted quantile values; ``u``: (n, sims) uniforms. Between knots the
    CDF is linear; below p=0.50 and above p=0.75 the *tail expressions double as the
    adjacent segment* — i.e. the lower tail extends with the q25–q50 slope and the upper
    tail with the q75–q90 slope (the Step-14 spec), floored at 0.
    """
    q25, q50, q75, q90 = (qv[:, i][:, None] for i in range(4))
    lo = q50 + (u - 0.50) / 0.25 * (q50 - q25)   # u < 0.50, incl. lower tail
    mid = q50 + (u - 0.50) / 0.25 * (q75 - q50)  # 0.50 <= u < 0.75
    hi = q75 + (u - 0.75) / 0.15 * (q90 - q75)   # u >= 0.75, incl. upper tail
    return np.clip(np.where(u < 0.50, lo, np.where(u < 0.75, mid, hi)), 0.0, None)


def simulate_ranges(
    proj: pd.DataFrame,
    gp_pool: pd.DataFrame,
    sd_pg: float = SD_PG,
    n_sims: int = 4000,
    quantiles: tuple[float, ...] = DEFAULT_QUANTILES,
    seed: int = 0,
    pg_quantiles: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Add simulated total-fantasy-point ranges to a projection frame.

    ``proj`` needs ``fpts_pg``, ``gp`` and ``target_age``. Returns a copy with ``fpts_p10 ..
    fpts_p90`` (per ``quantiles``), ``fpts_median``, and a ``risk`` score (relative width of the
    p10–p90 band). Ranking-neutral: rows and order are preserved.

    When ``gp_pool`` carries a ``CHRONIC`` column (``build_gp_pool(injury_profile=...)``) *and*
    ``proj`` carries ``inj_chronic_flag`` (EXP-015 / 7.3b), draws bucket by (age × chronic) so
    chronically-injured players sample a GP pool with their own fatter left tail. A
    (age × chronic) bucket under 30 rows falls back to its age-only pool (the ``_age_bucket``
    guard pattern), then to the full pool.

    ``pg_quantiles`` (Step 14 / EXP-021, the learned ranges): a ``pg_quantile_frame``-shaped
    frame (``PLAYER_ID`` + ``fpts_pg_q25/50/75/90``). Per-game draws then come from the
    piecewise-linear CDF through those quantiles (:func:`_piecewise_pg_draws`) instead of
    ``normal(fpts_pg, sd_pg)``; both frames must carry ``PLAYER_ID``. Players missing from
    the frame (or with NaN quantiles) fall back to the normal path row-by-row.
    """
    rng = np.random.default_rng(seed)
    out = proj.copy().reset_index(drop=True)
    n = len(out)

    pg = out["fpts_pg"].to_numpy(dtype=float)[:, None]
    proj_gp = out["gp"].to_numpy(dtype=float)
    ages = out["target_age"].to_numpy(dtype=float)

    # Bucket the empirical pool by age; scale each player's draws to their own projected GP.
    pool_gp = gp_pool["GP"].to_numpy(dtype=float)
    pool_age_buck = _age_bucket(gp_pool["AGE"].to_numpy(dtype=float))
    age_pools = {b: pool_gp[pool_age_buck == b] for b in (0, 1, 2)}
    age_pools = {b: (v if len(v) >= 30 else pool_gp) for b, v in age_pools.items()}  # guard small buckets

    use_chronic = "CHRONIC" in gp_pool.columns and "inj_chronic_flag" in out.columns
    if use_chronic:
        pool_chronic = gp_pool["CHRONIC"].to_numpy(dtype=int)
        player_chronic = out["inj_chronic_flag"].fillna(0).to_numpy(dtype=int)
        buckets = {}
        for b in (0, 1, 2):
            for c in (0, 1):
                v = pool_gp[(pool_age_buck == b) & (pool_chronic == c)]
                buckets[b + 3 * c] = v if len(v) >= 30 else age_pools[b]
        player_buck = _age_bucket(ages) + 3 * player_chronic
    else:
        buckets = age_pools
        player_buck = _age_bucket(ages)

    gp_draws = np.empty((n, n_sims))
    for b, pool in buckets.items():
        rows = np.where(player_buck == b)[0]
        if len(rows) == 0:
            continue
        med = np.median(pool)
        samp = rng.choice(pool, size=(len(rows), n_sims), replace=True)
        # Additive re-centering: shift the empirical shape so its median = the player's proj_gp.
        # Preserves the real left-skewed injury spread (an injury costs ~the same games at any
        # baseline) and avoids the right-side compression a multiplicative scale + 82-cap causes.
        shift = (proj_gp[rows] - med)[:, None]
        gp_draws[rows] = np.clip(samp + shift, 1, SEASON_GAMES)

    if pg_quantiles is not None:
        qcols = [quantile_col(q) for q in PG_QUANTILES]
        qm = out[["PLAYER_ID"]].merge(pg_quantiles[["PLAYER_ID"] + qcols], on="PLAYER_ID", how="left")
        qv = np.sort(qm[qcols].to_numpy(dtype=float), axis=1)  # monotone per row by construction
        have_q = ~np.isnan(qv).any(axis=1)
        u = rng.random((n, n_sims))
        normal_draws = np.clip(pg + rng.normal(0.0, sd_pg, size=(n, n_sims)), 0, None)
        with np.errstate(invalid="ignore"):  # NaN rows are routed to the normal fallback
            pg_draws = np.where(have_q[:, None], _piecewise_pg_draws(qv, u), normal_draws)
    else:
        pg_draws = np.clip(pg + rng.normal(0.0, sd_pg, size=(n, n_sims)), 0, None)
    totals = pg_draws * gp_draws

    qs = np.quantile(totals, quantiles, axis=1)  # shape (len(quantiles), n)
    for i, q in enumerate(quantiles):
        out[f"fpts_p{int(round(q * 100))}"] = qs[i].round(0)
    if 0.50 in quantiles:
        out["fpts_median"] = out[f"fpts_p50"]
    else:
        out["fpts_median"] = np.quantile(totals, 0.5, axis=1).round(0)
    lo, hi = out.get("fpts_p10"), out.get("fpts_p90")
    if lo is not None and hi is not None:
        out["risk"] = ((hi - lo) / out["fpts_median"].clip(lower=1)).round(3)
    return out


RANK_METHODS = ("safe", "median", "floor", "ceiling")


def rank_board(proj: pd.DataFrame, method: str = "safe", risk_lambda: float = 0.5) -> pd.DataFrame:
    """Re-sort a projection (with risk ranges) into a draft board by risk stance.

    * ``median``  — rank by expected total (``fpts_median``). Most accurate central estimate.
    * ``safe``    — rank by ``fpts_median - risk_lambda * (fpts_median - fpts_p10)``: a mild
      downside penalty. Backtests as accurate as ``median`` (Spearman ~0.57) while demoting
      injury-prone players, so it's the default — free bust protection.
    * ``floor``   — rank by ``fpts_p10`` (max safety) / ``ceiling`` — rank by ``fpts_p90`` (max upside).

    Returns a copy sorted descending by the chosen value, with ``draft_value`` and a renumbered
    ``rank``. Requires the range columns from :func:`simulate_ranges`.
    """
    if method not in RANK_METHODS:
        raise ValueError(f"method must be one of {RANK_METHODS}, got {method!r}")
    out = proj.copy()
    med = out["fpts_median"]
    if method == "median":
        val = med
    elif method == "floor":
        val = out["fpts_p10"]
    elif method == "ceiling":
        val = out["fpts_p90"]
    else:  # safe: blend median with its downside
        val = med - risk_lambda * (med - out["fpts_p10"])
    miss = val.isna()
    if miss.any() and "adp" in out.columns:
        # D1.5 market-priced rows (rookies / returning vets seeded from ADP) have no
        # simulated ranges, so every stance value is NaN and they would sink to the
        # bottom. Price them by interpolating THIS stance's value curve at their market
        # rank instead — they slot where the market says under every stance, without
        # fabricating ranges (risk/p10/p90 stay NaN). Rows with no market rank either
        # stay NaN and sink, unranked.
        real = np.sort(val[~miss].to_numpy(dtype=float))[::-1]
        pos = np.arange(1, len(real) + 1, dtype=float)
        anchor = pd.to_numeric(out.loc[miss, "adp"], errors="coerce")
        val = val.copy()
        val.loc[miss] = np.interp(anchor.clip(1, len(real)), pos, real)
    out["draft_value"] = val.round(0)
    out = out.sort_values("draft_value", ascending=False).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out
