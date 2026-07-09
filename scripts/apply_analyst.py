"""Apply the analyst overrides: board A -> board B (Step D2.2 / EXP-029).

Reads a saved board parquet (a projection board or the D1 draft sheet), applies
``config/analyst_overrides.yaml`` via deterministic, unit-tested arithmetic
(``models/analyst.py``), and writes **board B to a new file** — board A's file is
never touched (the D2.3 dual freeze commits both; D2.4 grades them in April).

Every override application is printed (name, action, model rank -> adjusted rank),
so the run itself is an audit record.

Example
-------
    python scripts/apply_analyst.py data/processed/draft_sheet_2026-27.parquet
    # -> data/processed/draft_sheet_2026-27_analyst.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from fantasy_nba.models.analyst import apply_overrides, effective_overrides, load_overrides


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyst overrides: board A -> board B.")
    parser.add_argument("board", help="Board parquet (board A). Never overwritten.")
    parser.add_argument("--overrides", default=None,
                        help="Overrides YAML (default: config/analyst_overrides.yaml).")
    parser.add_argument("--out", default=None,
                        help="Output parquet (default: <board>_analyst.parquet).")
    args = parser.parse_args()

    board_path = Path(args.board)
    out_path = Path(args.out) if args.out else board_path.with_name(
        board_path.stem + "_analyst.parquet")
    if out_path.resolve() == board_path.resolve():
        raise SystemExit("Refusing to overwrite board A — pick a different --out.")

    board = pd.read_parquet(board_path)
    entries = load_overrides(args.overrides)
    effective = effective_overrides(entries)
    print(f"[analyst] {len(entries)} entries ({len(effective)} effective after corrections) "
          f"from {args.overrides or 'config/analyst_overrides.yaml'}")

    board_b = apply_overrides(board, entries)

    applied = board_b[board_b["analyst_action"] != ""]
    if applied.empty:
        print("[analyst] no overrides — board B is board A + audit columns.")
    else:
        with pd.option_context("display.width", 200):
            print(applied[["PLAYER_NAME", "analyst_category", "analyst_action",
                           "analyst_date", "model_rank", "rank"]].to_string(index=False))
        n_moved = int((applied["model_rank"] != applied["rank"]).sum())
        print(f"[analyst] {len(applied)} reviewed, {n_moved} moved.")

    board_b.to_parquet(out_path, index=False)
    print(f"Saved board B -> {out_path}")


if __name__ == "__main__":
    main()
