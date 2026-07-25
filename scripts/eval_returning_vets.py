"""EXP-032 judgment: projecting returning vets from their last healthy season.

Players with prior NBA history but ZERO games in the intervening season fall off the learned
board (it projects from last-season logs). ``project_learned(..., returning_vet_ids=...)`` now
includes them, projecting a CLEAN per-game value from their last healthy season aged forward.
This validates that mechanism on the historical missed-full-season-return cohort: for every
player who played season S-2, has NO row in S-1, and returned in S (>= MIN_LABEL_MINUTES),
project S from data strictly before S (the vet included via returning_vet_ids) and score the
per-game fpts prediction vs what they actually did.

Baseline = last-healthy fpts/g carried forward UNADJUSTED (does the model's regression + aging
beat "just reuse their old number?"). Skeptic pass printed at the end: leakage, selection
(survivors-who-returned only), small-sample / seed stability.

Example
-------
    python scripts/eval_returning_vets.py
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from fantasy_nba.data import storage
from fantasy_nba.models._core import COUNTING, _season_start
from fantasy_nba.models.learned import DEFAULT_LGBM_PARAMS, project_learned
from fantasy_nba.scoring import load_scoring, score_frame

MIN_LABEL_MINUTES = 200.0   # a real return season, not a 5-game cameo
MIN_HEALTHY_MINUTES = 200.0  # a real last-healthy season to project from


def build_cohort(ss: pd.DataFrame) -> list[dict]:
    """Gap-return cases: played S-2 (>= MIN_HEALTHY_MINUTES), NO row in S-1, played S."""
    seasons = sorted(ss["SEASON"].unique(), key=_season_start)
    min_by = ss.groupby(["PLAYER_ID", "SEASON"])["MIN"].sum()
    rows = {s: set(ss.loc[ss.SEASON == s, "PLAYER_ID"]) for s in seasons}
    cohort = []
    for i in range(2, len(seasons)):
        S, prev, prev2 = seasons[i], seasons[i - 1], seasons[i - 2]
        for pid in rows[S] & rows[prev2]:
            if pid in rows[prev]:
                continue  # played the intervening season -> not a gap
            if min_by.get((pid, prev2), 0) < MIN_HEALTHY_MINUTES:
                continue
            if min_by.get((pid, S), 0) < MIN_LABEL_MINUTES:
                continue
            cohort.append({"PLAYER_ID": pid, "return_season": S, "healthy_season": prev2})
    return cohort


def actual_fpts_pg(ss: pd.DataFrame, cfg) -> pd.Series:
    """Per-game fantasy points a player actually scored in each (PLAYER_ID, SEASON)."""
    g = ss.groupby(["PLAYER_ID", "SEASON"], as_index=False)[["GP"] + list(COUNTING.values())].sum()
    pg = g.copy()
    for canon, src in COUNTING.items():
        pg[canon] = g[src] / g["GP"].clip(lower=1)
    pg["act_fpts_pg"] = score_frame(pg, cfg)
    return pg.set_index(["PLAYER_ID", "SEASON"])["act_fpts_pg"]


def main() -> None:
    ap = argparse.ArgumentParser(description="EXP-032 returning-vet projection backtest.")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    args = ap.parse_args()

    ss = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(None)
    act = actual_fpts_pg(ss, cfg)

    cohort = build_cohort(ss)
    names = ss.drop_duplicates("PLAYER_ID").set_index("PLAYER_ID")["PLAYER_NAME"]
    by_season: dict[str, list[int]] = {}
    for c in cohort:
        by_season.setdefault(c["return_season"], []).append(c["PLAYER_ID"])
    print(f"cohort: {len(cohort)} gap-return cases across {len(by_season)} return seasons "
          f"({min(by_season)}..{max(by_season)})\n")

    recs = []
    for S, pids in sorted(by_season.items(), key=lambda kv: _season_start(kv[0])):
        prior = ss[ss["SEASON"].map(_season_start) < _season_start(S)]
        prior_bio = bio[bio["SEASON"].map(_season_start) < _season_start(S)]
        if prior["SEASON"].nunique() < 3:
            continue  # too little history to train the adopted config comparably
        preds = []
        for seed in args.seeds:
            proj = project_learned(prior, prior_bio, target_season=S, cfg=cfg,
                                   returning_vet_ids=set(pids),
                                   params={**DEFAULT_LGBM_PARAMS, "random_state": seed})
            preds.append(proj[proj["returning_vet"]].set_index("PLAYER_ID")["fpts_pg"])
        pred = pd.concat(preds, axis=1).mean(axis=1)  # seed-averaged
        for pid in pids:
            if pid not in pred.index or (pid, S) not in act.index:
                continue
            recs.append({
                "player": names.get(pid, pid), "return_season": S,
                "pred_fpts_pg": float(pred[pid]),
                "naive_fpts_pg": float(act.get((pid, [c["healthy_season"] for c in cohort
                                       if c["PLAYER_ID"] == pid and c["return_season"] == S][0]))),
                "act_fpts_pg": float(act[(pid, S)]),
            })

    r = pd.DataFrame(recs)
    r["model_err"] = r["pred_fpts_pg"] - r["act_fpts_pg"]
    r["naive_err"] = r["naive_fpts_pg"] - r["act_fpts_pg"]
    n = len(r)
    model_mae, naive_mae = r["model_err"].abs().mean(), r["naive_err"].abs().mean()
    model_bias, naive_bias = r["model_err"].mean(), r["naive_err"].mean()
    rho = spearmanr(r["pred_fpts_pg"], r["act_fpts_pg"]).correlation
    rho_naive = spearmanr(r["naive_fpts_pg"], r["act_fpts_pg"]).correlation

    # paired bootstrap CI on the MAE improvement (naive - model)
    rng = np.random.default_rng(0)
    diffs = r["naive_err"].abs().to_numpy() - r["model_err"].abs().to_numpy()
    boot = [rng.choice(diffs, size=n, replace=True).mean() for _ in range(2000)]
    lo, hi = np.percentile(boot, [2.5, 97.5])

    print(f"scored n = {n}\n")
    print(f"{'':18}{'MAE':>8}{'bias':>8}{'Spearman':>10}")
    print(f"{'model (aged)':18}{model_mae:>8.2f}{model_bias:>8.2f}{rho:>10.3f}")
    print(f"{'naive carry-fwd':18}{naive_mae:>8.2f}{naive_bias:>8.2f}{rho_naive:>10.3f}")
    print(f"\nMAE improvement (naive - model): {naive_mae - model_mae:+.2f} "
          f"fpts/g  [95% CI {lo:+.2f}, {hi:+.2f}]")
    print("\nworst model misses:")
    print(r.reindex(r["model_err"].abs().sort_values(ascending=False).index)
          [["player", "return_season", "naive_fpts_pg", "pred_fpts_pg", "act_fpts_pg", "model_err"]]
          .head(8).to_string(index=False))

    print("\n--- skeptic pass ---")
    print("* leakage: each fold trains/predicts on seasons strictly < S; the vet's features come")
    print("  from <= S-2 (last healthy). No return-season data leaks into the projection.")
    print("* selection: cohort = players who RETURNED and played >= 200 min (survivors). The")
    print("  projection is validated on returners only; matches the use case (we list players we")
    print("  BELIEVE will play). It says nothing about players who never came back.")
    print(f"* sample: n={n}; the paired bootstrap CI above is the honest width. Seed-averaged over")
    print(f"  {args.seeds} for stability. Re-run as more seasons cache.")


if __name__ == "__main__":
    main()
