"""DARKO cross-check + disagreement report against our projection board (Stage 7.E, live-only).

Joins the latest DARKO pull to one of our projection boards and surfaces (1) the minutes
disagreements — our biggest projection risk — and (2) the rank disagreements — the actionable
sleeper/fade calls where we differ from the market. Informational overlay; it does not modify
projections (DARKO is adopted live-only, unbacktested — see EXPERIMENTS.md EXP-010).

Example
-------
    python scripts/pull_darko.py            # refresh the DARKO pull first
    python scripts/darko_report.py          # against data/processed/v2m_2026-27.parquet
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

from fantasy_nba.models import darko as darko_mod


def main() -> None:
    parser = argparse.ArgumentParser(description="DARKO minutes + rank disagreement report.")
    parser.add_argument("--board", default="data/processed/v2m_2026-27.parquet")
    parser.add_argument("--top-n", type=int, default=150)
    args = parser.parse_args()

    board = pd.read_parquet(args.board)
    darko = darko_mod.load_latest_darko()
    joined, stats = darko_mod.join_board(board, darko)

    print(f"Board: {args.board}  ·  DARKO: {darko.attrs.get('source_file')}")
    print(f"Matched {stats['n_matched']}/{stats['n_board']} names ({stats['match_rate']:.0%}).\n")

    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(f"=== Biggest MINUTES disagreements (top-{args.top_n}; +gap = we project more) ===")
        print(darko_mod.minutes_disagreement(joined, top_n=args.top_n).head(15).to_string(index=False))

        print(f"\n=== Biggest RANK disagreements (top-{args.top_n}; -gap = our sleeper vs DARKO) ===")
        print(darko_mod.rank_disagreement(joined, top_n=args.top_n).head(15).to_string(index=False))


if __name__ == "__main__":
    main()
