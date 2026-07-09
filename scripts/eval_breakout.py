"""EXP-026 (b): the breakout **board policy**, judged on recall — never point error.

Per season × seed: project the ``learned`` board, score every player's breakout probability
(walk-forward classifier on the archetype features), apply the deterministic policy
(top-K scores outside the stable core move up ``boost`` ranks), then measure:

* **big-riser recall@150** — of the realized top-150 players whose fpts/g jumped > +6 vs
  their prior season, what fraction each board ranked into its own top-150. The draft-capture
  metric (EXP-011's verdict: recall is the real headroom, not bias).
* **above-market rate** — of those realized big risers, the fraction we ranked *above* the
  archived preseason expert consensus (Hashtag points-league; genuine snapshots exist for
  2022-23 and 2023-24 — the EXP-017b audit). Did we have him before the room did?
* **cost line** — pool level MAE (gate: ≤ +1%) and stable-bucket signed bias (within ±0.3):
  the option-value chase must not damage the core board.

Gate (plan Step 9b): recall +3pp pooled OR above-market +5pp, costs within bounds.

Usage
-----
    python scripts/eval_breakout.py --seasons 2022-23 2023-24 2024-25 2025-26 --seeds 0 1 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

from fantasy_nba.config import RAW_DIR
from fantasy_nba.data import storage
from fantasy_nba.models import breakout as brk
from fantasy_nba.models._core import _season_start
from fantasy_nba.models.backtest import _actual, project_models
from fantasy_nba.models.context import season_before
from fantasy_nba.scoring import load_scoring

BIG_RISER_DELTA = 6.0   # eval_movers' big-riser bucket edge
STABLE_DELTA = 2.0
MIN_PRIOR_MINUTES = 500.0

# Archived preseason consensus (vintage-verified in the EXP-017b audit).
CONSENSUS_FILES = {
    "2022-23": RAW_DIR / "market" / "hashtag_20221005.parquet",
    "2023-24": RAW_DIR / "market" / "hashtag_20231005.parquet",
}


def _big_risers(season_stats, season, cfg) -> pd.DataFrame:
    """Realized top-150 players whose fpts/g jumped > BIG_RISER_DELTA vs their prior season."""
    actual = _actual(season_stats, season, cfg, min_minutes=0.0)
    prior = _actual(season_stats, season_before(season), cfg, min_minutes=MIN_PRIOR_MINUTES)
    top = actual.nlargest(150, "act_fpts_total")
    m = top.merge(prior[["PLAYER_ID", "act_fpts_pg"]].rename(columns={"act_fpts_pg": "prior_pg"}),
                  on="PLAYER_ID")
    return m[m["act_fpts_pg"] - m["prior_pg"] > BIG_RISER_DELTA][["PLAYER_ID", "PLAYER_NAME"]]


def _board_metrics(board, season_stats, season, cfg, risers, consensus) -> dict:
    pool = board.nsmallest(150, "rank")
    actual = _actual(season_stats, season, cfg, min_minutes=0.0)
    prior = _actual(season_stats, season_before(season), cfg, min_minutes=MIN_PRIOR_MINUTES)

    riser_ids = set(risers["PLAYER_ID"])
    pooled_ids = set(pool["PLAYER_ID"])
    recall = len(riser_ids & pooled_ids) / max(len(riser_ids), 1)

    m = pool.merge(actual[["PLAYER_ID", "act_fpts_pg"]], on="PLAYER_ID")
    mae = (m["fpts_pg"] - m["act_fpts_pg"]).abs().mean()
    d = m.merge(prior[["PLAYER_ID", "act_fpts_pg"]].rename(columns={"act_fpts_pg": "prior_pg"}),
                on="PLAYER_ID")
    stable = d[(d["act_fpts_pg"] - d["prior_pg"]).abs() <= STABLE_DELTA]
    stable_bias = (stable["fpts_pg"] - stable["act_fpts_pg"]).mean()

    out = {"n_risers": len(riser_ids), "recall150": recall, "MAE": mae, "stable_bias": stable_bias}
    if consensus is not None:
        rank_of = board.set_index("PLAYER_ID")["rank"]
        cr = consensus.set_index("name_key")["consensus_rank"]
        above = 0
        for r in risers.itertuples(index=False):
            our = rank_of.get(r.PLAYER_ID, np.inf)
            from fantasy_nba.models.darko import normalize_name
            cons = cr.get(normalize_name(r.PLAYER_NAME), np.inf)
            if our <= 150 and our < cons:
                above += 1
        out["above_market"] = above / max(len(riser_ids), 1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-026b: breakout board-policy judgment.")
    parser.add_argument("--seasons", nargs="+", default=["2022-23", "2023-24", "2024-25", "2025-26"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    parser.add_argument("--k", type=int, default=brk.DEFAULT_POLICY["k"])
    parser.add_argument("--core", type=int, default=brk.DEFAULT_POLICY["core"])
    parser.add_argument("--boost", type=int, default=brk.DEFAULT_POLICY["boost"])
    parser.add_argument("--scoring", default=None)
    args = parser.parse_args()

    season_stats = storage.read("player_season_stats")
    bio = storage.read("player_bio")
    cfg = load_scoring(args.scoring)

    table = brk.breakout_feature_table(season_stats, bio, cfg)
    labels = brk.breakout_labels(season_stats, cfg)
    consensus = {s: pd.read_parquet(p) for s, p in CONSENSUS_FILES.items() if Path(p).exists()}
    print(f"[breakout] feature table {len(table):,} rows; labels {len(labels):,}; "
          f"archived consensus for {sorted(consensus)}")

    rows = []
    for seed in args.seeds:
        for season in args.seasons:
            models = project_models(season, season_stats, bio, cfg, seed=seed)
            board = models["learned"]
            clf_params = {**brk.DEFAULT_CLF_PARAMS, "random_state": seed}
            scores = brk.breakout_scores(table, labels, season, params=clf_params)
            policy = brk.apply_breakout_policy(board, scores, k=args.k, core=args.core,
                                               boost=args.boost)
            risers = _big_risers(season_stats, season, cfg)
            cons = consensus.get(season)
            for name, b in (("learned", board), ("policy", policy)):
                r = _board_metrics(b, season_stats, season, cfg, risers, cons)
                rows.append({"seed": seed, "season": season, "board": name, **r})
            # the flagged names — the auditable draft-sheet story
            fl = policy[policy["breakout_flag"] == 1]
            hits = set(fl["PLAYER_ID"]) & set(risers["PLAYER_ID"])
            print(f"seed {seed} {season}: flagged {len(fl)}, of which realized big risers: "
                  f"{sorted(fl.loc[fl['PLAYER_ID'].isin(hits), 'PLAYER_NAME'])}")

    df = pd.DataFrame(rows)
    with pd.option_context("display.width", 220, "display.max_columns", None):
        print("\n=== per (seed, season) ===")
        print(df.round(4).to_string(index=False))
        agg_cols = [c for c in ("recall150", "MAE", "stable_bias", "above_market") if c in df]
        pooled = df.groupby(["seed", "board"])[agg_cols].mean().round(4)
        print("\n=== pooled per seed (mean over seasons; above_market over archived seasons only) ===")
        print(pooled.to_string())
        delta = (pooled.xs("policy", level="board") - pooled.xs("learned", level="board")).round(4)
        print("\n=== policy − learned, per seed ===")
        print(delta.to_string())
        print("\nGATE (b): pooled recall150 +0.03 OR above_market +0.05, "
              "with ΔMAE ≤ +1% of control and stable_bias within ±0.3.")


if __name__ == "__main__":
    main()
