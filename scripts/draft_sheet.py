"""The draft sheet (Step D1.4 + D1.5): board + VOR + ADP availability + rookie market-seed.

Assembles the decision-ready table from a saved projection board:

* **VOR** (D1.2, ``models/value.py``): fpts/g above the greedy replacement level for the
  league in ``config/league.yaml`` (10 teams × ESPN default starting slots). Sanity report:
  how much VOR actually reorders a points league is printed, not assumed.
* **ADP availability** (D1.4): FantasyPros consensus ADP — "likely gone by pick" — never a
  value input (the Step-9 source hierarchy).
* **Market-seed for board-missing players** (D1.5): rookies have no prior-season row, and
  returning vets (zero 2025-26 games: Haliburton/Kyrie/Lillard) have no feature row either,
  so the model board silently omits both (EXP-028's model lost to pick-order, so the market
  seed stands alone). Every market row that matches no player ON THE BOARD is seeded at its
  consensus rank, flagged ``market_priced`` + ``seed_class`` — value = our own board's
  fpts/g interpolated at that rank, so
  totals/VOR compute consistently; no model behind the number, and the column says so.

Pass-through: optional board columns (risk, breakout_p, ps_*) ride along when present —
generate the input board with ``project.py --rank-by safe --breakout --preseason``
(``--model learned_ps`` once the target's October games are cached).

Example
-------
    python scripts/project.py --target 2026-27 --model learned --rank-by safe --breakout
    python scripts/draft_sheet.py --board data/processed/learned_2026-27.parquet --target 2026-27
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models.allocation import pos_group_asof, position_table
from fantasy_nba.models.value import add_vor, load_league

_spec = importlib.util.spec_from_file_location("pull_market", Path(__file__).parent / "pull_market.py")
pull_market = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pull_market)

# Market-seeded rows carry no model projection: `risk` stays NaN (the column is numeric —
# the UI meters and the draft API float() it; the old string label was a latent crash) and
# `seed_class` records WHY the learned board misses the player.
SEED_ROOKIE = "rookie"            # no stats history at all (this year's class)
SEED_RETURNING = "returning-vet"  # has history but zero 2025-26 games (the Haliburton gap)


def seed_missing(board: pd.DataFrame, market: pd.DataFrame, board_keys: set[str],
                 stats_keys: set[str], id_map: dict[str, int] | None = None,
                 max_rank: int = 160) -> pd.DataFrame:
    """D1.5: market rows matching no player ON THE BOARD -> rows at their consensus rank.

    Two classes fall through the learned board (it projects from 2025-26 logs): rookies
    (no stats history at all) and returning vets (2024-25 stats, zero 2025-26 games —
    the Haliburton/Kyrie/Lillard gap, found 2026-07-17; the old seed keyed on season-stats
    presence, so known-but-missing vets fell through both nets). Value = our board's
    fpts/g (and total) interpolated at the consensus rank — a market *price* expressed in
    our units, not a projection (``market_priced = 1`` + ``seed_class`` say so).
    ``max_rank`` keeps the seed inside the draftable range: unmatched rows deep on a market
    list are stale draft-and-stash names, not misses — real rookies chart high once the
    market source lists them (the July FP pull has none yet; re-pull in September).
    """
    m = market.drop_duplicates("name_key", keep="first")
    rank_col = ("consensus_rank"
                if "consensus_rank" in m.columns and m["consensus_rank"].notna().any()
                else "adp")
    m[rank_col] = pd.to_numeric(m[rank_col], errors="coerce")
    miss = m[~m["name_key"].isin(board_keys) & m[rank_col].between(1, max_rank)].copy()
    if miss.empty:
        return board.assign(market_priced=board.get("market_priced", 0),
                            seed_class=board.get("seed_class", ""))

    xs = board["rank"].to_numpy(dtype=float)
    seeded = pd.DataFrame({
        # Returning vets get their real nba PLAYER_ID (they have stats history) so the API
        # board can append them and the draft room can match their picks; rookies stay
        # id-less (NaN) until the October pass — the API skips id-less rows by contract.
        "PLAYER_ID": miss["name_key"].map(id_map or {}),
        "PLAYER_NAME": miss["player"],
        # The market's team is fresher than any stats row for these players (a returning
        # vet's last stats team predates his current one); explicit FA -> no team (honest).
        "TEAM_ABBREVIATION": miss["team"].where(
            miss["team"].astype(str).str.upper() != "FA") if "team" in miss.columns else None,
        "rank": miss[rank_col].astype(float),
        "adp": miss[rank_col].astype(float),  # the market rank IS the seed's anchor
        "fpts_pg": np.interp(miss[rank_col].astype(float), xs, board["fpts_pg"].to_numpy(dtype=float)),
        "fpts_total": np.interp(miss[rank_col].astype(float), xs, board["fpts_total"].to_numpy(dtype=float)),
        "market_priced": 1,
        "seed_class": [SEED_ROOKIE if k not in stats_keys else SEED_RETURNING
                       for k in miss["name_key"]],
    })
    out = pd.concat([board.assign(market_priced=0, seed_class=""), seeded], ignore_index=True)
    out = out.sort_values(["rank", "market_priced"]).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Decision-ready draft sheet (D1).")
    parser.add_argument("--board", default="data/processed/learned_2026-27.parquet")
    parser.add_argument("--target", default="2026-27")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--no-rookies", action="store_true",
                        help="Skip the D1.5 market seed (e.g. when the market pull is stale).")
    args = parser.parse_args()

    board = pd.read_parquet(args.board)
    league = load_league()
    season_stats = storage.read("player_season_stats")

    # D1.2 — VOR against the league's replacement level.
    pos_of = pos_group_asof(position_table(storage.read("team_rosters")), args.target)
    board = add_vor(board, pos_of, league)
    moved = (board["vor_rank"] - board["rank"]).abs()
    top100 = board.nsmallest(100, "rank")
    n_moved = int(((top100["vor_rank"] - top100["rank"]).abs() >= 10).sum())
    print(f"[vor] replacement fill: {league['teams']} teams x ESPN starting slots; "
          f"top-100 rank moves >= 10: {n_moved} "
          f"({'VOR meaningfully reorders' if n_moved >= 10 else 'points-league VOR is nearly monotone — informational column'})")

    # D1.4 — ADP availability (never a value input).
    fp = pull_market.load_latest("fantasypros")
    board["name_key"] = board["PLAYER_NAME"].map(pull_market.normalize_name)
    adp = fp.drop_duplicates("name_key", keep="first").set_index("name_key")["adp"]
    board["adp"] = pd.to_numeric(board["name_key"].map(adp), errors="coerce")
    print(f"[adp] {fp.attrs.get('source_file')} — matched "
          f"{board.nsmallest(150, 'rank')['adp'].notna().sum()}/150 of our top-150")

    # D1.5 — market seed for players the model board can't project: rookies AND returning
    # vets with no 2025-26 row (FantasyPros is the 2026-27-vintage source in July; Hashtag
    # flips to preseason boards ~Sept — re-pull then).
    if not args.no_rookies:
        stats_keys = set(season_stats["PLAYER_NAME"].map(pull_market.normalize_name))
        id_map = (season_stats.sort_values("SEASON")
                  .assign(nk=season_stats["PLAYER_NAME"].map(pull_market.normalize_name))
                  .drop_duplicates("nk", keep="last").set_index("nk")["PLAYER_ID"].to_dict())
        n_before = len(board)
        board = seed_missing(board, fp, set(board["name_key"]), stats_keys, id_map)
        seeded = board[board["market_priced"] == 1]
        n_rk = int((seeded["seed_class"] == SEED_ROOKIE).sum())
        print(f"[seed] {len(board) - n_before} market-priced rows ({n_rk} rookies, "
              f"{len(seeded) - n_rk} returning vets with no 2025-26 games); top by rank:")
        print(seeded.nsmallest(8, "rank")[["rank", "PLAYER_NAME", "fpts_pg", "seed_class"]]
              .to_string(index=False))

    show = ["rank", "PLAYER_NAME", "pos_group", "fpts_pg", "fpts_total", "vor", "vor_rank", "adp",
            "market_priced", "seed_class"]
    show += [c for c in ("risk", "breakout_p", "ps_mpg", "ps_mpg_delta", "ps_start_share")
             if c in board.columns]
    board = board.drop(columns=["name_key"], errors="ignore")

    path = storage.write(board, f"draft_sheet_{args.target}", layer="processed")
    print(f"\nSaved -> {path}")
    with pd.option_context("display.width", 220, "display.max_columns", None):
        print(board[[c for c in show if c in board.columns]].head(args.top).to_string(index=False))


if __name__ == "__main__":
    main()
