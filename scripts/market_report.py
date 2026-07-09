"""Board-vs-market disagreement report (Step 9 / EXP-017 — the live benchmark).

Joins the latest market pulls (``scripts/pull_market.py``) to one of our projection boards:

* vs **Hashtag points-league consensus** (the value signal): top disagreements each way —
  ``rank_gap = our_rank − consensus_rank`` (negative = our sleeper vs the market, positive =
  our fade). The risk column rides along when the board carries ranges, so "we're low on X"
  reads with availability context.
* vs **FantasyPros ADP** (the availability signal only): the "likely gone by pick N" column
  for the draft sheet (D1.4) — printed here as the ADP next to our rank; never a value input.

Informational overlay; it does not modify projections (EXP-017b — market-gap as a *feature* —
is waived-with-condition until the archive we start accumulating today covers ≥4 seasons).

Example
-------
    python scripts/pull_market.py          # refresh the pulls first
    python scripts/market_report.py --board data/processed/learned_2026-27.parquet
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

# pull_market lives beside this script (it owns the market dirs/parsers/normalizer).
_spec = importlib.util.spec_from_file_location("pull_market", Path(__file__).parent / "pull_market.py")
pull_market = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pull_market)


def _join(board: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    b = board.copy()
    b["name_key"] = b["PLAYER_NAME"].map(pull_market.normalize_name)
    m = market.drop_duplicates("name_key", keep="first")
    return b.merge(m, on="name_key", how="left", suffixes=("", "_mkt"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Market consensus + ADP disagreement report.")
    parser.add_argument("--board", default="data/processed/learned_2026-27.parquet")
    parser.add_argument("--top-n", type=int, default=150)
    parser.add_argument("--min-gap", type=int, default=20)
    args = parser.parse_args()

    board = pd.read_parquet(args.board)
    ht = pull_market.load_latest("hashtag")
    fp = pull_market.load_latest("fantasypros")
    risk_cols = [c for c in ("risk",) if c in board.columns]

    j = _join(board, ht)
    pool = j.nsmallest(args.top_n, "rank")
    matched = pool["consensus_rank"].notna()
    print(f"Board: {args.board}")
    print(f"Consensus: {ht.attrs.get('source_file')} ({len(ht)} rows) — matched "
          f"{matched.sum()}/{len(pool)} of our top-{args.top_n}")
    print(f"ADP:       {fp.attrs.get('source_file')} ({len(fp)} rows)")
    print("NOTE: check the consensus source's vintage before drafting off this — Hashtag "
          "flips to next-season preseason boards in late summer.\n")

    pool = pool[matched].copy()
    pool["rank_gap"] = (pool["rank"] - pool["consensus_rank"]).astype(int)
    cols = ["rank", "PLAYER_NAME", "consensus_rank", "rank_gap"] + risk_cols
    big = pool[pool["rank_gap"].abs() >= args.min_gap].sort_values("rank_gap")
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(f"=== Our SLEEPERS vs consensus (we rank ≥{args.min_gap} higher) ===")
        print(big[big["rank_gap"] < 0].head(20)[cols].to_string(index=False))
        print(f"\n=== Our FADES vs consensus (we rank ≥{args.min_gap} lower) ===")
        print(big[big["rank_gap"] > 0].tail(20).sort_values("rank_gap", ascending=False)[cols].to_string(index=False))

        # Availability column (D1.4): ADP is what the draft room does, even when wrong on value.
        ja = _join(board, fp).nsmallest(args.top_n, "rank")
        ja = ja[ja["adp"].notna()].copy()
        ja["adp_vs_us"] = (ja["adp"] - ja["rank"]).round(1)
        print(f"\n=== Draft-day availability: our top-30 with consensus ADP (likely gone by pick) ===")
        print(ja.head(30)[["rank", "PLAYER_NAME", "adp", "adp_vs_us"] + risk_cols].to_string(index=False))


if __name__ == "__main__":
    main()
