"""Export Board B and public draft metadata for the static GitHub Pages companion.

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

from fantasy_nba.config import PROCESSED_DIR, ROOT
from fantasy_nba.models.value import load_league


OUT = ROOT / "static" / "data" / "board.json"

PUBLIC_COLUMNS = (
    "rank", "source_rank", "model_source_rank", "tier", "source_tier", "PLAYER_ID", "PLAYER_NAME",
    "TEAM_ABBREVIATION", "target_age", "gp", "mpg", "fpts_pg", "fpts_total",
    "previous_fpts_pg", "fpts_pg_change",
    "draft_value", "vor", "vor_rank", "adp", "pts", "reb", "ast", "stl", "blk",
    "fg3m", "tov", "fpts_p10", "fpts_median", "fpts_p90", "risk", "market_priced",
    "seed_class", "positions", "analyst_action", "analyst_category", "analyst_date",
)


def _add_public_positions(board: pd.DataFrame, pmap: pd.DataFrame | None = None) -> pd.DataFrame:
    """Join ESPN position labels without publishing ESPN ids or private league state."""
    out = board.copy()
    path = PROCESSED_DIR / "espn_player_map.parquet"
    if "PLAYER_ID" not in out.columns or (pmap is None and not path.exists()):
        out["positions"] = None
        return out
    if pmap is None:
        pmap = pd.read_parquet(path, columns=["PLAYER_ID", "eligible"])
    eligible = (pmap.dropna(subset=["PLAYER_ID"]).drop_duplicates("PLAYER_ID")
                .set_index("PLAYER_ID")["eligible"])
    out["positions"] = out["PLAYER_ID"].map(eligible)
    return out


def _clean(value):
    if pd.isna(value):
        return None
    if isinstance(value, float):
        return round(value, 2)
    return value.item() if hasattr(value, "item") else value


def _latest_adp_vintage() -> tuple[str | None, str | None]:
    files = sorted((ROOT / "data" / "raw" / "market").glob("fantasypros_*.parquet"))
    if not files:
        return None, None
    path = files[-1]
    return path.stem.removeprefix("fantasypros_"), str(path.relative_to(ROOT)).replace("\\", "/")


def _rank_public_board(board: pd.DataFrame) -> pd.DataFrame:
    """Return a deterministic FP/G-ranked copy with FP/G tiers and source audit fields."""
    if "fpts_pg" not in board.columns:
        raise ValueError("Board must contain fpts_pg to produce the public rank")

    out = board.copy()
    if "rank" in out.columns:
        out["source_rank"] = out["rank"]
    if "model_rank" in out.columns:
        out["model_source_rank"] = out["model_rank"]
    if "tier" in out.columns:
        out["source_tier"] = out["tier"]

    sort_columns = ["fpts_pg"]
    ascending = [False]
    for column in ("source_rank", "PLAYER_ID", "PLAYER_NAME"):
        if column in out.columns:
            sort_columns.append(column)
            ascending.append(True)
    out = out.sort_values(sort_columns, ascending=ascending, na_position="last", kind="mergesort")
    out = out.reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)

    # The local board tiers are gaps in risk-adjusted season draft value. The public board
    # is explicitly an FP/G view, so derive its tiers from unusually large adjacent FP/G
    # gaps instead of mixing two rank semantics. Preserve the local tier above for audit.
    out["tier"] = float("nan")
    depth = min(160, len(out))
    if depth >= 3:
        gaps = out.loc[:depth - 1, "fpts_pg"].diff(-1).iloc[:-1]
        threshold = max(0.4, float(gaps.quantile(0.93)))
        tiers = [1]
        for gap in gaps:
            tiers.append(tiers[-1] + (1 if gap >= threshold else 0))
        out.loc[:depth - 1, "tier"] = tiers
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export Board B for the static GitHub Pages companion.")
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
    board = _add_public_positions(_rank_public_board(board))

    league = load_league()
    public_roster = {str(slot).upper(): int(count)
                     for slot, count in league.get("roster", {}).items()}

    columns = [c for c in PUBLIC_COLUMNS if c in board.columns]
    rows = [{c: _clean(row[c]) for c in columns} for _, row in board[columns].iterrows()]
    market_date, market_source = _latest_adp_vintage()
    payload = {
        "title": title,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source_board": source_board,
        "analyst_layer": True,
        "ranked_by": "fpts_pg",
        "market_date": market_date,
        "market_source": market_source,
        "capabilities": ["board", "player_detail", "compare", "tiers", "teams", "mock_draft"],
        "draft_config": {
            "teams": int(league.get("teams", 10)),
            "roster": public_roster,
        },
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Exported {len(rows)} Board B rows -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
