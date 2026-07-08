"""Unit tests for the Stage-7 infrastructure (implementation-plan Steps 1–6 code).

Synthetic data only, no network — same conventions as test_models.py. These tests pin the
*mechanics* (arithmetic, no-leakage, monotonicity, determinism); the adopt/reject verdicts
need real data and run locally per docs/implementation-plan.md.
"""

import numpy as np
import pandas as pd
import pytest

from fantasy_nba.models import allocation, floor_sim, learned, quantiles, recency
from fantasy_nba.models._core import COUNTING
from fantasy_nba.models.backtest import VARIANT_SPECS, project_models
from fantasy_nba.models.eval_movers import (
    bootstrap_bias_delta_ci,
    oracle_variant,
    pool_frame,
    run_mover_eval,
)
from fantasy_nba.scoring import ScoringConfig

PTS_ONLY = ScoringConfig(name="pts-only", weights={"pts": 1.0})


# ---------------------------------------------------------------- shared synthetic fixtures

def _synthetic_league(seasons, n_players=40, seed=0):
    """Tiny multi-season panel with all COUNTING source columns + bio ages (no network).
    Mirrors test_models.py's helper (kept local: test modules don't import each other)."""
    rng = np.random.default_rng(seed)
    ss_rows, bio_rows = [], []
    skill = rng.uniform(0.4, 1.6, size=n_players)
    for si, season in enumerate(seasons):
        for pid in range(n_players):
            gp = int(np.clip(rng.normal(68, 10), 20, 82))
            mpg = float(np.clip(rng.normal(26 * skill[pid], 4), 8, 38))
            s = skill[pid]
            row = {
                "SEASON": season, "PLAYER_ID": pid, "PLAYER_NAME": f"p{pid}",
                "TEAM_ABBREVIATION": "AAA" if pid % 2 else "BBB",
                "GP": gp, "MIN": gp * mpg,
                "FGM": 7 * s * gp, "FGA": 15 * s * gp, "FG3M": 2 * s * gp,
                "FTM": 3 * s * gp, "FTA": 4 * s * gp, "OREB": 1.2 * s * gp,
                "DREB": 4 * s * gp, "REB": 5.2 * s * gp, "AST": 4 * s * gp,
                "STL": 1.1 * s * gp, "BLK": 0.6 * s * gp, "TOV": 2 * s * gp,
                "PTS": 19 * s * gp,
                "USG_PCT": float(np.clip(0.12 + 0.10 * s, 0.05, 0.40)),
                "TS_PCT": float(np.clip(rng.normal(0.55, 0.03), 0.40, 0.70)),
            }
            ss_rows.append(row)
            bio_rows.append({"SEASON": season, "PLAYER_ID": pid, "AGE": 22 + si})
    return pd.DataFrame(ss_rows), pd.DataFrame(bio_rows)


FAST = {**learned.DEFAULT_LGBM_PARAMS, "n_estimators": 25}


# ----------------------------------------------------------------- Step 1: pool_frame / calib

def test_pool_frame_deltas_buckets_and_joins():
    proj = pd.DataFrame({"rank": [1, 2, 3], "PLAYER_ID": [1, 2, 3],
                         "fpts_pg": [40.0, 30.0, 20.0]})
    prior = pd.DataFrame({"PLAYER_ID": [1, 2], "prior_fpts_pg": [33.0, 31.0]})  # 3 has no prior
    actual = pd.DataFrame({"PLAYER_ID": [1, 2, 3], "act_fpts_pg": [42.0, 28.0, 21.0]})

    m = pool_frame(proj, prior, actual, pool_top_n=3).set_index("PLAYER_ID")
    assert 3 not in m.index  # no prior-season level -> "mover" undefined -> excluded
    assert m.loc[1, "actual_delta"] == pytest.approx(9.0)   # 42 - 33 -> big riser
    assert m.loc[1, "proj_delta"] == pytest.approx(7.0)
    assert m.loc[1, "err"] == pytest.approx(-2.0)
    assert str(m.loc[1, "bucket"]) == "big riser"
    assert str(m.loc[2, "bucket"]) == "faller"              # 28 - 31 = -3


def test_pool_frame_actual_pool_selects_on_realized_total():
    # Player 4 is a sleeper the model ranked low (rank 9) but who posts a big realized total.
    proj = pd.DataFrame({"rank": [1, 2, 3, 9], "PLAYER_ID": [1, 2, 3, 4],
                         "fpts_pg": [40.0, 30.0, 20.0, 12.0]})
    prior = pd.DataFrame({"PLAYER_ID": [1, 2, 3, 4], "prior_fpts_pg": [33.0, 31.0, 22.0, 5.0]})
    actual = pd.DataFrame({"PLAYER_ID": [1, 2, 3, 4],
                           "act_fpts_pg": [42.0, 28.0, 21.0, 30.0],
                           "act_fpts_total": [100.0, 90.0, 40.0, 95.0]})
    # top-3 by realized total = players 1 (100), 4 (95), 2 (90); player 3 (40) drops out.
    m = pool_frame(proj, prior, actual, pool_top_n=3, pool="actual").set_index("PLAYER_ID")
    assert set(m.index) == {1, 2, 4}
    assert str(m.loc[4, "bucket"]) == "big riser"           # 30 - 5 = 25, a missed sleeper
    # the model-pool default is unaffected: top-3 by rank = 1,2,3 (byte-identical behaviour).
    mm = pool_frame(proj, prior, actual[["PLAYER_ID", "act_fpts_pg"]], pool_top_n=3)
    assert set(mm["PLAYER_ID"]) == {1, 2, 3}


# ------------------------------------------------------------- Step 2: selection floor

def test_selection_floor_matches_unbiased_forecaster_tail_bias():
    # A *perfect* conditional-mean forecaster: proj == mu, actual = mu + noise. All measured
    # tail bias is then selection effect, and the floor must reproduce it.
    rng = np.random.default_rng(3)
    n = 400
    mu = rng.normal(25, 8, size=n)
    noise = rng.normal(0, 5, size=n)
    pool = pd.DataFrame({
        "fpts_pg": mu, "act_fpts_pg": mu + noise, "prior_fpts_pg": mu,
    })
    pool["err"] = pool["fpts_pg"] - pool["act_fpts_pg"]
    pool["actual_delta"] = pool["act_fpts_pg"] - pool["prior_fpts_pg"]

    from fantasy_nba.models.eval_movers import _bucket
    measured = pool.groupby(_bucket(pool["actual_delta"]), observed=False)["err"].mean()
    floor = floor_sim.selection_floor(pool, n_draws=400, seed=0).set_index("bucket")

    for bucket in ("big faller", "faller", "riser", "big riser"):
        assert floor.loc[bucket, "floor_bias"] == pytest.approx(measured[bucket], abs=0.6)
    # Sign structure: floor is positive on fallers, negative on risers.
    assert floor.loc["big faller", "floor_bias"] > 1.0
    assert floor.loc["big riser", "floor_bias"] < -1.0


def test_floor_table_scales_and_reducible_gap():
    pool = pd.DataFrame({
        "fpts_pg": [20.0] * 50, "act_fpts_pg": np.linspace(10, 30, 50),
        "prior_fpts_pg": [20.0] * 50,
    })
    pool["err"] = pool["fpts_pg"] - pool["act_fpts_pg"]
    pool["actual_delta"] = pool["act_fpts_pg"] - pool["prior_fpts_pg"]
    ft = floor_sim.floor_table(pool, n_draws=50)
    assert set(ft["sigma_scale"]) == set(floor_sim.SIGMA_SCALES)

    measured = pd.DataFrame({"bucket": ["big riser"], "signed_bias": [-8.0]})
    gap = floor_sim.reducible_gap(measured, ft)
    got = gap.loc[0]
    assert got["reducible_gap"] == pytest.approx(-8.0 - got["floor_bias"])


# ------------------------------------------------------------- Step 3: oracle variants

def _proj_line(pid, mpg, pts_pg):
    row = {"rank": pid, "PLAYER_ID": pid, "PLAYER_NAME": f"p{pid}", "mpg": mpg,
           **{c: 0.0 for c in COUNTING}}
    row["pts"] = pts_pg
    return row


def test_oracle_minutes_identity_and_scaling():
    proj = pd.DataFrame([_proj_line(1, 30.0, 20.0), _proj_line(2, 20.0, 10.0)])
    proj["fpts_pg"] = proj["pts"]  # pts-only scoring
    lines = pd.DataFrame({
        "PLAYER_ID": [1, 2], "act_mpg": [30.0, 40.0],
        **{f"act_{c}": [0.0, 0.0] for c in COUNTING},
    })
    lines["act_pts"] = [22.0, 14.0]

    out = oracle_variant(proj, lines, PTS_ONLY, kind="minutes").set_index("PLAYER_ID")
    # Player 1: act_mpg == mpg -> unchanged. Player 2: minutes doubled -> stats double.
    assert out.loc[1, "fpts_pg"] == pytest.approx(20.0)
    assert out.loc[2, "fpts_pg"] == pytest.approx(20.0)
    assert out.loc[2, "pts"] == pytest.approx(20.0)

    rates = oracle_variant(proj, lines, PTS_ONLY, kind="rates").set_index("PLAYER_ID")
    # Player 2: actual 14 pts/g at 40 mpg -> at projected 20 mpg = 7.
    assert rates.loc[2, "fpts_pg"] == pytest.approx(7.0)
    # Ranks come from the base board (pool selection stays on the real model).
    assert list(out["rank"]) == [1, 2]

    with pytest.raises(ValueError):
        oracle_variant(proj, lines, PTS_ONLY, kind="nope")


# ------------------------------------------------------------- Step 4: recency de-confound

def _logs(pid, season, mins, start="2022-11-01", team="AAA"):
    dates = pd.date_range(start, periods=len(mins), freq="2D").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "SEASON": [season] * len(mins), "PLAYER_ID": [pid] * len(mins),
        "GAME_DATE": dates, "MIN": mins, "PTS": [m * 0.5 for m in mins],
        "TEAM_ABBREVIATION": [team] * len(mins) if isinstance(team, str) else team,
    })


def test_skip_last_trims_rest_contaminated_tail():
    # 20 games @20, then 15 @34 (real role), then 5 @10 (rest/tanking).
    logs = _logs(1, "2022-23", [20.0] * 20 + [34.0] * 15 + [10.0] * 5)

    raw = recency.season_recency_table(logs, window=20)
    feat = recency.recency_features(raw, "2023-24").set_index("PLAYER_ID")
    assert feat.loc[1, "recent_mpg"] == pytest.approx((15 * 34 + 5 * 10) / 20)  # 28.0, dragged down

    trimmed = recency.season_recency_table(logs, window=20, skip_last=5)
    feat5 = recency.recency_features(trimmed, "2023-24").set_index("PLAYER_ID")
    assert feat5.loc[1, "recent_mpg"] == pytest.approx((5 * 20 + 15 * 34) / 20)  # 30.5, clean
    # Season aggregates unchanged by the trim -> deltas shift purely from the window.
    assert feat5.loc[1, "recent_mpg_delta"] > feat.loc[1, "recent_mpg_delta"]


def test_trade_split_table_and_features():
    traded = _logs(1, "2022-23", [20.0] * 30 + [30.0] * 10,
                   team=["AAA"] * 30 + ["BBB"] * 10)
    stayed = _logs(2, "2022-23", [25.0] * 40)
    short = _logs(3, "2022-23", [20.0] * 37 + [36.0] * 3,
                  team=["AAA"] * 37 + ["BBB"] * 3)  # post-trade sample too small
    logs = pd.concat([traded, stayed, short], ignore_index=True)

    t = recency.trade_split_table(logs).set_index("PLAYER_ID")
    assert t.loc[1, "traded_flag"] == 1 and t.loc[1, "post_trade_games"] == 10
    assert t.loc[1, "post_trade_mpg_delta"] == pytest.approx(10.0)
    assert t.loc[2, "traded_flag"] == 0 and t.loc[2, "post_trade_mpg_delta"] == 0.0
    assert t.loc[3, "traded_flag"] == 1 and t.loc[3, "post_trade_mpg_delta"] == 0.0  # < 5 games

    table = recency.season_recency_table(logs)
    feat = recency.recency_features(table, "2023-24", trade_table=t.reset_index())
    assert set(recency.TRADE_FEATURES) <= set(feat.columns)
    # No-leakage: same-season ask stays empty even with a trade table.
    assert recency.recency_features(table, "2022-23", trade_table=t.reset_index()).empty

    with pytest.raises(ValueError):
        recency.trade_split_table(logs.drop(columns=["TEAM_ABBREVIATION"]))


# ------------------------------------------------------------- Step 5: objective modes

def test_learned_delta_and_weight_modes_run_and_are_deterministic():
    seasons = ["2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons)

    base = learned.project_learned(ss, bio, "2023-24", params=FAST)
    for kwargs in ({"target_mode": "delta"},
                   {"weight_mode": "mover"},
                   {"weight_mode": "relevance"},
                   {"target_mode": "delta", "weight_mode": "mover", "weight_alpha": 0.5}):
        out = learned.project_learned(ss, bio, "2023-24", params=FAST, **kwargs)
        out2 = learned.project_learned(ss, bio, "2023-24", params=FAST, **kwargs)
        assert out["gp"].between(1, 82).all() and out["mpg"].between(0, 48).all()
        assert (out[list(COUNTING)] >= 0).all().all()
        assert np.allclose(out["fpts_pg"], out2["fpts_pg"])  # seeded determinism
        # A different objective must actually change the projections vs the base model.
        assert not np.allclose(out["fpts_pg"].to_numpy(), base["fpts_pg"].to_numpy())

    with pytest.raises(ValueError):
        learned.project_learned(ss, bio, "2023-24", params=FAST, target_mode="nope")
    with pytest.raises(ValueError):
        learned.project_learned(ss, bio, "2023-24", params=FAST, weight_mode="nope")
    with pytest.raises(ValueError):  # trade split rides the recency tables
        learned.project_learned(ss, bio, "2023-24", params=FAST, use_trade_split=True)


# ------------------------------------------------------------- Step 5c: quantile heads

def test_quantiles_monotone_and_pinball():
    seasons = ["2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons)
    out = quantiles.project_fpts_quantiles(ss, bio, "2023-24", cfg=PTS_ONLY, params=FAST)

    cols = [quantiles.quantile_col(q) for q in quantiles.QUANTILES]
    assert set(cols) <= set(out.columns)
    vals = out[cols].to_numpy()
    assert (np.diff(vals, axis=1) >= 0).all()  # monotone across heads on every row
    assert (vals >= 0).all()

    # Pinball loss, hand-checked: y=[0,10] vs pred=[5,5].
    assert quantiles.pinball_loss([0, 10], [5, 5], 0.5) == pytest.approx(2.5)
    assert quantiles.pinball_loss([0, 10], [5, 5], 0.9) == pytest.approx(2.5)
    assert quantiles.pinball_loss([10], [10], 0.75) == 0.0


# ------------------------------------------------------------- Step 1/4/5 noise guard: CI

def test_bootstrap_ci_zero_for_identical_pools_and_detects_shift():
    rng = np.random.default_rng(0)
    pool = pd.DataFrame({
        "PLAYER_ID": range(120),
        "err": rng.normal(0, 2, 120),
        "actual_delta": rng.normal(0, 1, 120),  # all stable bucket
    })
    same = bootstrap_bias_delta_ci(pool, pool).set_index("bucket")
    assert same.loc["stable", "bias_delta"] == 0.0
    assert same.loc["stable", "ci_lo"] == 0.0 and same.loc["stable", "ci_hi"] == 0.0

    shifted = pool.copy()
    shifted["err"] = shifted["err"] - 1.0  # model B is 1 fpt/g less biased
    ci = bootstrap_bias_delta_ci(pool, shifted).set_index("bucket")
    assert ci.loc["stable", "bias_delta"] == pytest.approx(-1.0)
    assert ci.loc["stable", "ci_hi"] < 0  # resolved: CI excludes 0


def test_cluster_bootstrap_widens_ci_for_repeated_players():
    # Two "seasons" of the same 40 players with strongly player-correlated diffs: the row
    # bootstrap treats 80 rows as independent; clustering by player must not, so its CI
    # is at least as wide. Point estimate is identical either way.
    rng = np.random.default_rng(1)
    player_effect = rng.normal(0, 2.0, 40)
    rows = []
    for season in ("s1", "s2"):
        for pid in range(40):
            rows.append({"PLAYER_ID": pid, "season": season,
                         "err": player_effect[pid] + rng.normal(0, 0.1),
                         "actual_delta": 0.0})  # all stable bucket
    pool_a = pd.DataFrame(rows)
    pool_b = pool_a.copy()
    pool_b["err"] = 0.0  # diff == -err_a, perfectly player-clustered

    kw = dict(on=("PLAYER_ID", "season"), n_boot=800, seed=0)
    row_ci = bootstrap_bias_delta_ci(pool_a, pool_b, **kw).set_index("bucket")
    clu_ci = bootstrap_bias_delta_ci(pool_a, pool_b, cluster="PLAYER_ID", **kw).set_index("bucket")

    assert clu_ci.loc["stable", "bias_delta"] == pytest.approx(row_ci.loc["stable", "bias_delta"])
    row_w = row_ci.loc["stable", "ci_hi"] - row_ci.loc["stable", "ci_lo"]
    clu_w = clu_ci.loc["stable", "ci_hi"] - clu_ci.loc["stable", "ci_lo"]
    assert clu_w >= row_w * 1.2  # clustering must widen the interval here


# ------------------------------------------------------------- Step 6: allocation features

def test_allocation_features_depth_chart_math():
    # Prior season, team AAA: P1 guard 2000, P2 guard 1000, P3 big 1500, P4 big 500 (total 5000).
    prev = pd.DataFrame({
        "SEASON": ["2022-23"] * 4, "PLAYER_ID": [1, 2, 3, 4],
        "TEAM_ABBREVIATION": ["AAA"] * 4, "MIN": [2000.0, 1000.0, 1500.0, 500.0],
    })
    # Target rosters: AAA keeps P1, P4, adds rookie P5 (guard). P2 (guard) and P3 (big) -> BBB.
    roster = pd.DataFrame({
        "PLAYER_ID": [1, 4, 5, 2, 3],
        "team": ["AAA", "AAA", "AAA", "BBB", "BBB"],
        "pos_group": [0, 1, 0, 0, 1],
    })
    f = allocation.allocation_features(prev, roster, "2022-23").set_index("PLAYER_ID")

    assert f.loc[5, "own_prev_share"] == 0.0                                  # rookie
    assert f.loc[5, "same_pos_vacated_share"] == pytest.approx(1000 / 5000)   # P2 left
    assert f.loc[5, "same_pos_returning_share"] == pytest.approx(2000 / 5000) # P1 stayed
    assert f.loc[5, "depth_rank"] == 2 and f.loc[5, "n_same_pos"] == 2
    assert f.loc[1, "depth_rank"] == 1
    assert f.loc[1, "same_pos_returning_share"] == 0.0                        # excludes self
    assert f.loc[4, "same_pos_vacated_share"] == pytest.approx(1500 / 5000)   # P3 (big) left

    assert allocation.position_group("G-F") == 0 and allocation.position_group("F-C") == 1
    with pytest.raises(ValueError):
        allocation.position_group("X")


def test_rookie_reserve_and_share_normalization():
    ss = pd.DataFrame({
        "SEASON": ["2022-23", "2023-24", "2023-24"],
        "PLAYER_ID": [1, 1, 9],
        "TEAM_ABBREVIATION": ["AAA", "AAA", "AAA"],
        "MIN": [1000.0, 800.0, 200.0],  # P9 is new -> 200/1000 of AAA's minutes
    })
    assert allocation.rookie_reserve(ss) == pytest.approx(0.2)

    pred = pd.DataFrame({"PLAYER_ID": [1, 2], "team": ["AAA", "AAA"],
                         "share_pred": [0.5, 0.3]})
    norm = allocation.normalize_shares(pred, reserve=0.1)
    assert norm["share_norm"].sum() == pytest.approx(0.9)
    assert norm.loc[0, "share_norm"] == pytest.approx(0.5 * 0.9 / 0.8)


# ------------------------------------------------------- integration: the full eval path

def test_project_models_variants_and_seed_threading():
    seasons = ["2018-19", "2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons, n_players=30)
    out = project_models("2022-23", ss, bio, PTS_ONLY,
                         variants=["learned_delta", "learned_w_rel"], seed=1)
    assert {"baseline", "v2", "v2m", "learned", "learned_delta", "learned_w_rel"} <= set(out)
    for frame in out.values():
        assert {"PLAYER_ID", "fpts_pg", "rank"} <= set(frame.columns)
    # A recency variant without game logs must fail loudly.
    with pytest.raises(ValueError):
        project_models("2022-23", ss, bio, PTS_ONLY, variants=["learned_recency"])
    # Unknown variant name -> KeyError from the registry lookup.
    with pytest.raises(KeyError):
        project_models("2022-23", ss, bio, PTS_ONLY, variants=["nope"])
    assert "learned_recency_s5" in VARIANT_SPECS  # registry carries the Step-4 matrix
    # A params-carrying variant keeps its params under the seed override (the Step-5d
    # confirm path): seed must set random_state *inside* the spec's params, not clobber
    # them wholesale back to the defaults.
    import fantasy_nba.models.backtest as bt

    captured = {}
    real = bt.project_learned

    def spy(*a, **kw):
        if "params" in kw:
            captured.update(kw["params"])
        return real(*a, **kw)

    orig = bt.project_learned
    bt.project_learned = spy
    try:
        tuned = {"learned_tuned": {"params": {**bt.DEFAULT_LGBM_PARAMS, "n_estimators": 5}}}
        bt.project_models("2022-23", ss, bio, PTS_ONLY, variants=tuned, seed=1)
    finally:
        bt.project_learned = orig
    assert captured["n_estimators"] == 5      # the spec's tuned value survived
    assert captured["random_state"] == 1      # ...with the seed threaded inside it


def test_run_mover_eval_three_tables_oracles_and_pools():
    seasons = ["2018-19", "2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons, n_players=30)
    per_bucket, directional, per_pred, pools = run_mover_eval(
        "2022-23", ss, bio, cfg=PTS_ONLY, pool_top_n=25, min_prior_minutes=100.0,
        oracles=True, return_pools=True,
    )
    models = set(directional["model"])
    assert {"learned", "oracle_minutes(learned)", "oracle_rates(learned)"} <= models
    assert {"model", "bucket", "signed_bias"} <= set(per_bucket.columns)
    assert {"model", "bucket", "calib_gap"} <= set(per_pred.columns)
    # calib_gap arithmetic holds row-wise.
    ok = per_pred.dropna(subset=["calib_gap"])
    assert np.allclose(ok["calib_gap"], ok["mean_actual_delta"] - ok["mean_proj_delta"])
    # Pools carry what the floor sim and the CI need.
    for pool in pools.values():
        assert {"fpts_pg", "act_fpts_pg", "prior_fpts_pg", "err", "actual_delta"} <= set(pool.columns)
    # The minutes oracle can't be *worse* than the model it corrects (level MAE, same pool).
    d = directional.set_index("model")
    assert d.loc["oracle_minutes(learned)", "level_MAE"] <= d.loc["learned", "level_MAE"] + 1e-9


def test_run_mover_eval_actual_pool_recall_view():
    seasons = ["2018-19", "2019-20", "2020-21", "2021-22", "2022-23"]
    ss, bio = _synthetic_league(seasons, n_players=30)
    per_bucket, directional, per_pred, pools = run_mover_eval(
        "2022-23", ss, bio, cfg=PTS_ONLY, pool_top_n=20, min_prior_minutes=100.0,
        return_pools=True, pool="actual",
    )
    # Recall of the realized top-N is a real fraction in [0, 1] for every model.
    assert "recall" in directional.columns
    r = directional.set_index("model")["recall"]
    assert r.notna().all() and ((r >= 0.0) & (r <= 1.0)).all()
    # The three tables still have their headline columns on the realized pool.
    assert {"model", "bucket", "signed_bias"} <= set(per_bucket.columns)
