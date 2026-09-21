"""Export the current Board B as the read-only GitHub Pages snapshot.

The output intentionally contains no credentials, ESPN state, raw caches, or proposal
editing surface.  Commit ``static/data/board.json`` after running this script; the Pages
workflow deploys the static site whenever that commit reaches ``main``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fantasy_nba.config import ROOT


OUT = ROOT / "static" / "data" / "board.json"


def _clean(value):
    if pd.isna(value):
        return None
    if isinstance(value, float):
        return round(value, 2)
    return value.item() if hasattr(value, "item") else value


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export read-only Board B for GitHub Pages.")
    parser.add_argument("--board", default=None,
                        help="Board A parquet (default: data/processed/learned_2026-27.parquet).")
    args = parser.parse_args(argv)
    if args.board:
        board_path = Path(args.board).resolve()
        if not board_path.exists():
            raise SystemExit(f"Board parquet not found: {board_path}")
        # update_daily has already applied availability, redistribution, and the analyst
        # layer before it writes its ROS parquet. Do not apply anything a second time.
        board = pd.read_parquet(board_path)
        source_board = str(board_path.relative_to(ROOT)).replace("\\", "/")
        title = "Fantasy NBA 2026-27 — ROS Board"
    else:
        # Reuse the API's exact preseason board path: it adds the transaction-derived team
        # map and applies the effective analyst layer, keeping static and live boards aligned.
        from fantasy_nba.api import boards

        board = boards.ranked_board("2026-27", "learned", "safe", apply_analyst=True)
        source_board = "live API Board B (2026-27 learned/safe)"
        title = "Fantasy NBA 2026-27 — Board B"
    board = board.sort_values("rank").reset_index(drop=True)

    columns = [c for c in ("rank", "model_rank", "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION",
                            "gp", "mpg", "fpts_pg", "fpts_total", "fpts_p10", "fpts_median",
                            "fpts_p90", "risk", "analyst_action", "analyst_category", "analyst_date")
               if c in board.columns]
    rows = [{c: _clean(row[c]) for c in columns} for _, row in board[columns].iterrows()]
    payload = {
        "title": title,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source_board": source_board,
        "analyst_layer": True,
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Exported {len(rows)} Board B rows -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
