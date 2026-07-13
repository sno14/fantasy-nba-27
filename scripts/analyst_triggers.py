"""Generate the D2.1 analyst trigger list: who the pre-draft analyst pass must review.

Within the top-200 union of our board (the D1 draft sheet) and the expert consensus
(latest Hashtag pull): (a) |our rank − consensus rank| >= 15 (plus consensus players
missing from our board entirely), (b) EXP-026 breakout flags, (c) severe-injury
returnees (Step-7 spell notes, trailing ~18 months), (d) rookies (D1.5 market-priced
rows / no NBA history). Expect ~30-50 players. Generated, not vibes — the pass reviews
a defined population, and every reviewed player gets an ``analyst_overrides.yaml``
entry, including explicit ``none`` verdicts.

Run any time as workflow v2's review frame (2026-07-12: entries land whenever information
arrives — BBM-transcript proposals → approval); the canonical run is the mid-Oct
**re-review** of every effective entry, after the draft-sheet regeneration:

    python scripts/analyst_triggers.py --board data/processed/draft_sheet_2026-27.parquet
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import importlib.util
from pathlib import Path

import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models.analyst import name_key, severe_returnees, trigger_list
from fantasy_nba.models.injuries import build_spells

_spec = importlib.util.spec_from_file_location("pull_market", Path(__file__).parent / "pull_market.py")
pull_market = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pull_market)


def main() -> None:
    parser = argparse.ArgumentParser(description="D2.1 analyst trigger list.")
    parser.add_argument("--board", default="data/processed/draft_sheet_2026-27.parquet")
    parser.add_argument("--consensus", default="hashtag",
                        help="Market source for consensus ranks (default: hashtag).")
    parser.add_argument("--as-of", default=None,
                        help="Returnee-window anchor, ISO date (default: today).")
    parser.add_argument("--target", default="2026-27",
                        help="Names the saved output parquet.")
    args = parser.parse_args()
    as_of = args.as_of or dt.date.today().isoformat()

    board = pd.read_parquet(args.board)
    consensus = pull_market.load_latest(args.consensus)
    season_stats = storage.read("player_season_stats")
    known = set(season_stats["PLAYER_NAME"].map(name_key))

    spells, stats = build_spells(storage.read("injuries"), season_stats)
    returnees = severe_returnees(spells, as_of)
    print(f"[triggers] consensus: {consensus.attrs.get('source_file')}; "
          f"injury events matched {stats['match_rate']:.3f}; "
          f"{len(returnees)} severe returnees in trailing 18m of {as_of}")

    trig = trigger_list(board, consensus, known_keys=known, returnee_ids=returnees)
    counts = trig["triggers"].str.get_dummies(sep=",").sum() if not trig.empty else pd.Series(dtype=int)
    print(f"[triggers] {len(trig)} players to review "
          f"({', '.join(f'{k}: {v}' for k, v in counts.items())})")

    path = storage.write(trig, f"analyst_triggers_{args.target}", layer="processed")
    print(f"Saved -> {path}\n")
    with pd.option_context("display.width", 200, "display.max_rows", None):
        print(trig.to_string(index=False))


if __name__ == "__main__":
    main()
