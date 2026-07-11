"""EXP-031 (implementation-plan Step 17): the budget diagnostic + the two sub-A/Bs.

**17.1 diagnostic (always printed — it decides sub-step (b) cheaply):** per eval season,
the walk-forward `learned` board joined to the honest Oct-1 roster map: each team's implied
budget share ``B_team = Σ mpg_i × gp_i / (240 × 82)`` vs the target ``1 − rookie_reserve``
(train-slice reserve), and the across-teams correlation of the overshoot with the team's
mean signed minutes error. **No correlation ⇒ the budget isn't where the error lives** and
sub-step (b) is dead for ~an hour's work.

**(a) ``--depth``:** the ledger-sanctioned allocation re-entry — ``learned_depth``
(ALLOC_FEATURES + pf_per_min into the y_mpg model only). This script reports its minutes
MAE + segments; run the standard mover/recall tables via
``eval_movers.py --variants learned_depth``.

**(b) ``--reconcile``:** soft headroom-space budget reconciliation
(``allocation.reconcile_minutes``). λ is selected on TUNING folds (targets ≤ 2021-22 only —
rule 10b nested; the script refuses later tuning folds) by pooled minutes MAE, then the
winner is confirmed once on the eval window.

Segments (the EXP-014 definitions): (i) team-changers (prior primary team ≠ Oct-1 team),
(ii) high-turnover target teams (``team_turnover_share`` > pooled median), (iii) rest.
Judged on **minutes MAE and level MAE** — never preseason riser bias (EXP-011's floor).

Usage:
    python scripts/eval_budget.py --seasons 2022-23 2023-24 2024-25 2025-26 --seed 0
    python scripts/eval_budget.py --depth --reconcile --seed 0   # full Step-17 judgment
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models import allocation as alloc
from fantasy_nba.models import context as ctx
from fantasy_nba.models._core import _season_start
from fantasy_nba.models.backtest import _actual
from fantasy_nba.models.learned import DEFAULT_LGBM_PARAMS, project_learned
from fantasy_nba.models.rosters import preseason_roster_map
from fantasy_nba.scoring import load_scoring

LAM_GRID = (0.25, 0.5, 1.0)
MAX_TUNE_START = 2021          # rule 10b: tuning folds target seasons <= 2021-22 only
DEFAULT_TUNE_SEASONS = ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22"]


def season_inputs(season, season_stats, bio, transactions, cfg, params, depth_table=None):
    """One season's walk-forward pieces: learned board(s), honest Oct-1 map, train-slice
    reserve, actual minutes."""
    ty = _season_start(season)
    train_ss = season_stats[season_stats["SEASON"].map(_season_start) < ty]
    train_bio = bio[bio["SEASON"].map(_season_start) < ty]
    boards = {"learned": project_learned(train_ss, train_bio, season, cfg=cfg, params=params)}
    if depth_table is not None:
        boards["learned_depth"] = project_learned(
            train_ss, train_bio, season, cfg=cfg, params=params,
            use_depth=True, depth_table=depth_table)
    rmap = preseason_roster_map(season_stats, transactions, season)
    reserve = alloc.rookie_reserve(train_ss)
    actual = _actual(season_stats, season, cfg, min_minutes=0.0)
    return boards, rmap, reserve, actual


def segments_for(pool: pd.DataFrame, season: str, season_stats, rmap) -> pd.Series:
    """Segment label per pool row: 'moved' (team-changer), 'turnover' (high-turnover
    target team), 'rest' — the EXP-014 splits, on the honest map."""
    prev_s = ctx.season_before(season)
    prev_team = alloc._prev_team_minutes(season_stats, prev_s).set_index("PLAYER_ID")["prev_team"]
    team_feats = ctx.team_context_features(season_stats, rmap, prev_s)
    turnover = team_feats.set_index("PLAYER_ID")["team_turnover_share"]
    map_team = rmap.set_index("PLAYER_ID")["team"]

    pid = pool["PLAYER_ID"]
    moved = (pid.map(map_team).notna() & pid.map(prev_team).notna()
             & (pid.map(map_team) != pid.map(prev_team)))
    to = pid.map(turnover)
    high = to > to.median()
    return pd.Series(np.where(moved, "moved", np.where(high.fillna(False), "turnover", "rest")),
                     index=pool.index)


def minutes_pool(board: pd.DataFrame, actual: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Board top-N joined to actual MPG (+ per-game level for the level-MAE clause)."""
    pool = board.nsmallest(top_n, "rank")[["PLAYER_ID", "mpg", "fpts_pg"]]
    return pool.merge(actual[["PLAYER_ID", "act_mpg", "act_fpts_pg"]], on="PLAYER_ID", how="inner")


def _mae_rows(pools: dict[str, list[pd.DataFrame]]) -> pd.DataFrame:
    rows = []
    for name, frames in pools.items():
        m = pd.concat(frames, ignore_index=True)
        for seg, g in [("ALL", m)] + list(m.groupby("segment")):
            rows.append({
                "variant": name, "segment": seg, "n": len(g),
                "min_MAE": (g["mpg"] - g["act_mpg"]).abs().mean(),
                "min_bias": (g["mpg"] - g["act_mpg"]).mean(),
                "level_MAE": (g["fpts_pg"] - g["act_fpts_pg"]).abs().mean(),
            })
    return pd.DataFrame(rows)


def _clustered_ci(pool_a: pd.DataFrame, pool_b: pd.DataFrame, col: str = "mpg",
                  act: str = "act_mpg", n_boot: int = 2000, seed: int = 0,
                  alpha: float = 0.10) -> dict:
    """Player-clustered paired bootstrap CI on Δ|err| (b − a) — rule 8's noise guard."""
    a = pool_a[["PLAYER_ID", "season", col, act]].rename(columns={col: "a"})
    b = pool_b[["PLAYER_ID", "season", col]].rename(columns={col: "b"})
    m = a.merge(b, on=["PLAYER_ID", "season"])
    m["_d"] = (m["b"] - m[act]).abs() - (m["a"] - m[act]).abs()
    g = m.groupby("PLAYER_ID")["_d"].agg(["sum", "count"])
    sums, counts = g["sum"].to_numpy(float), g["count"].to_numpy(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n_boot, len(g)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return {"n": len(m), "delta": float(m["_d"].mean()),
            "ci_lo": float(np.quantile(boots, alpha / 2)),
            "ci_hi": float(np.quantile(boots, 1 - alpha / 2))}


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-031 budget diagnostic + sub-A/Bs.")
    parser.add_argument("--seasons", nargs="+", default=["2022-23", "2023-24", "2024-25", "2025-26"])
    parser.add_argument("--top-n", type=int, default=150)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--scoring", default=None)
    parser.add_argument("--depth", action="store_true",
                        help="(a) add learned_depth (ALLOC_FEATURES+pf_per_min into y_mpg only).")
    parser.add_argument("--reconcile", action="store_true",
                        help="(b) tune λ on folds <= 2021-22, confirm the winner on --seasons.")
    parser.add_argument("--reconcile-base", default="learned",
                        choices=["learned", "learned_depth"],
                        help="Which board (b) reconciles (spec: whichever of control/(a) wins).")
    parser.add_argument("--tune-seasons", nargs="+", default=DEFAULT_TUNE_SEASONS)
    args = parser.parse_args()

    for s in args.tune_seasons:
        if _season_start(s) > MAX_TUNE_START:
            raise SystemExit(f"tuning fold {s} is later than 2021-22 — rule 10b forbids "
                             "selecting hyperparameters on the verdict window.")

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    transactions = storage.read("transactions")
    cfg = load_scoring(args.scoring)
    params = {**DEFAULT_LGBM_PARAMS, "random_state": args.seed}

    depth_table = None
    if args.depth or args.reconcile_base == "learned_depth":
        depth_table = alloc.depth_feature_table(
            season_stats, transactions, storage.read("team_rosters"))
        print(f"[depth] table rows={len(depth_table):,} over "
              f"{depth_table['SEASON'].nunique()} seasons (honest Oct-1 maps)", flush=True)

    # ---- (b) nested λ selection on the tuning folds (control base only — cheap) ----
    lam_star = None
    if args.reconcile:
        tune_mae = {lam: [] for lam in LAM_GRID + (0.0,)}
        for season in args.tune_seasons:
            boards, rmap, reserve, actual = season_inputs(
                season, season_stats, bio, transactions, cfg, params,
                depth_table if args.reconcile_base == "learned_depth" else None)
            base = boards[args.reconcile_base if args.reconcile_base in boards else "learned"]
            for lam in (0.0,) + LAM_GRID:
                b = alloc.reconcile_minutes(base, rmap, reserve, lam, cfg) if lam else base
                p = minutes_pool(b, actual, args.top_n)
                tune_mae[lam].append((p["mpg"] - p["act_mpg"]).abs().mean())
            print(f"[tune {season}] done", flush=True)
        t = pd.DataFrame({lam: [float(np.mean(v))] for lam, v in tune_mae.items()},
                         index=["min_MAE"]).T
        print("\n=== (b) λ grid on tuning folds (targets <= 2021-22; pooled minutes MAE) ===")
        print(t.round(4).to_string())
        candidates = {lam: v.iloc[0] for lam, v in t.iterrows() if lam > 0}
        lam_star = min(candidates, key=candidates.get)
        print(f"λ* = {lam_star} (control λ=0: {t.loc[0.0, 'min_MAE']:.4f})")

    # ---- eval window: diagnostic + variant pools ----
    budget_rows, corr_rows, corr_pairs = [], [], []
    pools: dict[str, list[pd.DataFrame]] = {}
    for season in args.seasons:
        boards, rmap, reserve, actual = season_inputs(
            season, season_stats, bio, transactions, cfg, params, depth_table)
        if args.reconcile and lam_star is not None:
            base = boards[args.reconcile_base]
            boards[f"recon_l{lam_star}"] = alloc.reconcile_minutes(
                base, rmap, reserve, lam_star, cfg)

        # 17.1 diagnostic on the control board.
        bt = alloc.budget_table(boards["learned"], rmap, reserve)
        bt.insert(0, "season", season)
        budget_rows.append(bt)
        merged = (boards["learned"].merge(rmap[["PLAYER_ID", "team"]], on="PLAYER_ID")
                  .merge(actual[["PLAYER_ID", "act_mpg"]], on="PLAYER_ID", how="inner"))
        team_err = merged.groupby("team").apply(
            lambda g: (g["mpg"] - g["act_mpg"]).mean(), include_groups=False).rename("team_min_err")
        j = bt.set_index("team").join(team_err)
        corr = float(j["overshoot"].corr(j["team_min_err"]))
        corr_pairs.append(j[["overshoot", "team_min_err"]].assign(season=season))
        corr_rows.append({"season": season, "corr_overshoot_err": corr,
                          "mean_B": float(bt["B_team"].mean()),
                          "p10_B": float(bt["B_team"].quantile(0.10)),
                          "p90_B": float(bt["B_team"].quantile(0.90)),
                          "target": float(bt["target"].iloc[0])})

        for name, b in boards.items():
            p = minutes_pool(b, actual, args.top_n)
            p["segment"] = segments_for(p, season, season_stats, rmap)
            p["season"] = season
            pools.setdefault(name, []).append(p)
        print(f"[{season}] B_team mean {bt['B_team'].mean():.3f} vs target "
              f"{bt['target'].iloc[0]:.3f}; corr(overshoot, team min err) = {corr:+.3f}", flush=True)

    with pd.option_context("display.width", 220, "display.max_columns", None):
        print("\n=== 17.1 budget diagnostic (learned board, honest Oct-1 maps) ===")
        C = pd.DataFrame(corr_rows)
        print(C.round(3).to_string(index=False))
        B = pd.concat(budget_rows, ignore_index=True)
        P = pd.concat(corr_pairs, ignore_index=True)
        pooled_corr = float(P["overshoot"].corr(P["team_min_err"]))
        print(f"pooled overshoot distribution: mean {B['overshoot'].mean():+.3f}, "
              f"p10 {B['overshoot'].quantile(0.1):+.3f}, p90 {B['overshoot'].quantile(0.9):+.3f} "
              f"(in fractions of the 240×82 supply; +0.1 ≈ +24 mpg-equivalent per game)")
        print(f"pooled corr(overshoot, team mean minutes err) over "
              f"{len(P)} team-seasons: {pooled_corr:+.3f}")
        print("DECISION RULE: |corr| small and unstable across seasons ⇒ (b) is dead — the "
              "budget isn't where the minutes error lives.")

        print(f"\n=== Minutes/level MAE by segment (top-{args.top_n} pools, pooled) ===")
        print(_mae_rows(pools).round(3).to_string(index=False))

        control = pd.concat(pools["learned"], ignore_index=True)
        for name in pools:
            if name == "learned":
                continue
            cand = pd.concat(pools[name], ignore_index=True)
            ci = _clustered_ci(control, cand, seed=args.seed)
            print(f"\npaired player-clustered 90% CI on Δ|minutes err| ({name} − learned): "
                  f"{ci['delta']:+.4f} [{ci['ci_lo']:+.4f}, {ci['ci_hi']:+.4f}] (n={ci['n']})")

        print("\nGATE (EXP-031): minutes MAE <= control AND moved/turnover segments -10% "
              "with rest <= +2%, rule 8 (seeds {0,1,2}) + clustered CI. Judged on minutes/"
              "level MAE and recall — never preseason riser bias (EXP-011 floor).")


if __name__ == "__main__":
    main()
