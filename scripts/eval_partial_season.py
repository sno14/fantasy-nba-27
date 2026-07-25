"""EXP-033 judgment: is the model's fade over-applied after a PARTIAL season?

EXP-032 settled the missed-FULL-season cohort (no S-1 row): there, naive last-healthy
carry-forward runs hot (+3.42 bias) and the model's aged-forward fade wins on MAE. This
asks the untested neighbouring question: what about players who *did* play S-1, but only
a handful of games (5..35)? The board projects them from that small sample, which fades
BOTH their minutes and their per-minute rate at once (the Trae Young / Walker Kessler
shape). When the small sample says the per-minute rate HELD, is that fade still right?

Four estimators, scored on per-game fpts in the return season S:

    model          the board's own projection (status quo)
    naive_healthy  last healthy season's fpts/g, carried forward unadjusted
    rate_anchor    healthy fpts/min  x  MODEL's projected mpg   (rate fade removed only)
    minutes_anchor model's fpts/min  x  healthy mpg             (minutes fade removed only)

The two anchors decompose the fade: whichever beats `model` tells us which leg the board
is getting wrong. Everything is additionally split on `rate_held` = (S-1 fpts/min) /
(healthy fpts/min) -- the hypothesis is that the fade is correctly sized when the rate
collapsed and over-applied when it held.

Example
-------
    python scripts/eval_partial_season.py --seeds 0 1 2
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

PARTIAL_GP_LO, PARTIAL_GP_HI = 5, 35   # a real but small S-1 sample
MIN_HEALTHY_GP = 40                    # a season we're willing to call the player's level
MIN_LABEL_MINUTES = 200.0              # a real return season, not a cameo

ESTIMATORS = ["model", "naive_healthy", "rate_anchor", "minutes_anchor"]


def per_game(ss: pd.DataFrame, cfg) -> pd.DataFrame:
    """Per-game fpts / mpg / fpts-per-minute for every (PLAYER_ID, SEASON)."""
    pg = ss.copy()
    for canon, src in COUNTING.items():
        pg[canon] = ss[src] / ss["GP"].clip(lower=1)
    pg["fpts_pg"] = score_frame(pg, cfg)
    pg["mpg"] = ss["MIN"] / ss["GP"].clip(lower=1)
    pg["fpm"] = pg["fpts_pg"] / pg["mpg"].replace(0, np.nan)
    return pg[["PLAYER_ID", "PLAYER_NAME", "SEASON", "GP", "fpts_pg", "mpg", "fpm"]]


def build_cohort(pg: pd.DataFrame) -> pd.DataFrame:
    """S-1 played but small (5..35 GP); a prior healthy season to anchor on; S is real."""
    seasons = sorted(pg["SEASON"].unique(), key=_season_start)
    by_ps = {(r.PLAYER_ID, r.SEASON): r for r in pg.itertuples()}
    rows = []
    for i in range(2, len(seasons)):
        S, prev = seasons[i], seasons[i - 1]
        for r in pg[(pg.SEASON == prev)
                    & pg.GP.between(PARTIAL_GP_LO, PARTIAL_GP_HI)].itertuples():
            lab = by_ps.get((r.PLAYER_ID, S))
            if lab is None or lab.mpg * lab.GP < MIN_LABEL_MINUTES:
                continue
            hist = pg[(pg.PLAYER_ID == r.PLAYER_ID)
                      & (pg.SEASON.map(_season_start) < _season_start(prev))
                      & (pg.GP >= MIN_HEALTHY_GP)]
            if hist.empty:
                continue
            h = hist.sort_values("SEASON", key=lambda c: c.map(_season_start)).iloc[-1]
            rows.append({
                "PLAYER_ID": r.PLAYER_ID, "player": r.PLAYER_NAME, "S": S,
                "prev_gp": r.GP, "prev_fpm": r.fpm,
                "h_season": h.SEASON, "h_fpts_pg": h.fpts_pg, "h_mpg": h.mpg, "h_fpm": h.fpm,
                "act_fpts_pg": lab.fpts_pg,
            })
    c = pd.DataFrame(rows)
    c["rate_held"] = c["prev_fpm"] / c["h_fpm"]
    return c


def score_block(r: pd.DataFrame, label: str) -> None:
    print(f"\n=== {label}  (n = {len(r)}) ===")
    print(f"{'':16}{'MAE':>8}{'bias':>8}{'Spearman':>10}")
    for e in ESTIMATORS:
        err = r[e] - r["act_fpts_pg"]
        rho = spearmanr(r[e], r["act_fpts_pg"]).correlation
        print(f"{e:16}{err.abs().mean():>8.2f}{err.mean():>+8.2f}{rho:>10.3f}")
    # paired bootstrap on each anchor's MAE improvement over the model
    rng = np.random.default_rng(0)
    base = (r["model"] - r["act_fpts_pg"]).abs().to_numpy()
    for e in ESTIMATORS[1:]:
        d = base - (r[e] - r["act_fpts_pg"]).abs().to_numpy()
        boot = [rng.choice(d, size=len(d), replace=True).mean() for _ in range(2000)]
        lo, hi = np.percentile(boot, [2.5, 97.5])
        print(f"  {e:14} MAE improvement over model: {d.mean():+.2f}  [95% CI {lo:+.2f}, {hi:+.2f}]")


def main() -> None:
    ap = argparse.ArgumentParser(description="EXP-033 partial-season re-anchoring backtest.")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--split", type=float, default=1.0, help="rate_held cut point")
    args = ap.parse_args()

    ss = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(None)
    pg = per_game(ss, cfg)

    c = build_cohort(pg)
    print(f"cohort: {len(c)} partial-season cases, return seasons "
          f"{c.S.min()}..{c.S.max()} ({c.S.nunique()} folds)")

    recs = []
    for S, grp in sorted(c.groupby("S"), key=lambda kv: _season_start(kv[0])):
        prior = ss[ss["SEASON"].map(_season_start) < _season_start(S)]
        prior_bio = bio[bio["SEASON"].map(_season_start) < _season_start(S)]
        if prior["SEASON"].nunique() < 3:
            continue
        preds = []
        for seed in args.seeds:
            proj = project_learned(prior, prior_bio, target_season=S, cfg=cfg,
                                   params={**DEFAULT_LGBM_PARAMS, "random_state": seed})
            preds.append(proj.set_index("PLAYER_ID")[["fpts_pg", "mpg"]])
        pred = sum(preds) / len(preds)  # seed-averaged
        for row in grp.itertuples():
            if row.PLAYER_ID not in pred.index:
                continue
            m_fpts, m_mpg = pred.loc[row.PLAYER_ID, "fpts_pg"], pred.loc[row.PLAYER_ID, "mpg"]
            recs.append({
                **row._asdict(),
                "model": float(m_fpts),
                "model_mpg": float(m_mpg),
                "naive_healthy": float(row.h_fpts_pg),
                "rate_anchor": float(row.h_fpm * m_mpg),
                "minutes_anchor": float((m_fpts / m_mpg) * row.h_mpg),
            })

    r = pd.DataFrame(recs)
    score_block(r, "ALL partial-season cases")
    score_block(r[r.rate_held >= args.split], f"rate HELD  (rate_held >= {args.split})")
    score_block(r[r.rate_held < args.split], f"rate FELL  (rate_held < {args.split})")

    print("\n--- skeptic pass ---")
    print("* leakage: each fold trains and predicts on seasons strictly < S; cohort features come")
    print("  from <= S-1. No return-season data reaches any estimator.")
    print("* selection: S is required to be a REAL season (>= 200 min). That filter selects")
    print("  players who came back healthy, which FAVOURS the anchors (they assume health). If an")
    print("  anchor still runs hot under a filter tilted its way, the finding is conservative.")
    print("* rate_held is measured on 5..35 games and is itself noisy; the split is a screen, not")
    print("  a clean instrument. Small-sample rate is upward-biased for players who only played")
    print("  when feeling good -- part of any 'held' signal is that survivorship, not true level.")
    print(f"* seeds {args.seeds} averaged; n per block printed above.")
    r.to_csv("data/processed/exp033_partial_season.csv", index=False)
    print("\nwrote data/processed/exp033_partial_season.csv")


if __name__ == "__main__":
    main()
