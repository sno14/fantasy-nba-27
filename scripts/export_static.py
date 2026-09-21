"""Export the current Board B as the read-only GitHub Pages snapshot.

The output intentionally contains no credentials, ESPN state, raw caches, or proposal
editing surface.  Commit ``static/data/board.json`` after running this script; the Pages
workflow deploys the static site whenever that commit reaches ``main``. Public ``rank`` is
always the ordinal FP/G rank; the board's original ranks remain as audit-only metadata.
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


def _rank_public_board(board: pd.DataFrame) -> pd.DataFrame:
    """Return a deterministic FP/G-ranked copy while preserving source ranks."""
    if "fpts_pg" not in board.columns:
        raise ValueError("Board must contain fpts_pg to produce the public rank")

    out = board.copy()
    if "rank" in out.columns:
        out["source_rank"] = out["rank"]
    if "model_rank" in out.columns:
        out["model_source_rank"] = out["model_rank"]

    sort_columns = ["fpts_pg"]
    ascending = [False]
    for column in ("source_rank", "PLAYER_ID", "PLAYER_NAME"):
        if column in out.columns:
            sort_columns.append(column)
            ascending.append(True)
    out = out.sort_values(sort_columns, ascending=ascending, na_position="last", kind="mergesort")
    out = out.reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out


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
    board = _rank_public_board(board)

    columns = [c for c in ("rank", "source_rank", "model_source_rank", "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION",
                            "gp", "mpg", "fpts_pg", "fpts_total", "fpts_p10", "fpts_median",
                            "fpts_p90", "risk", "analyst_action", "analyst_category", "analyst_date")
               if c in board.columns]
    rows = [{c: _clean(row[c]) for c in columns} for _, row in board[columns].iterrows()]
    payload = {
        "title": title,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source_board": source_board,
        "analyst_layer": True,
        "ranked_by": "fpts_pg",
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Exported {len(rows)} Board B rows -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
