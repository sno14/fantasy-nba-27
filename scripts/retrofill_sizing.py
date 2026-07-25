"""One-shot: retro-fill `sizing:` blocks onto the analyst proposals already promoted.

Context (2026-07-25): the `sizing:` block became mandatory on non-`none` proposals so a
delta's decomposition is *checkable* rather than asserted in prose (see the transcripts
README and EXP-033). Entries written before that date have no block. This fills them.

**These are audit artifacts, not authored judgment.** A retro-filled block records only what
the standing delta ALREADY implies — every number is computed from the board plus the stats
cache, nothing is reconstructed from intent:

    base_mpg    = the board's mpg (unchanged by fpts_delta — that is the whole point)
    target_fpts = the board's post-analyst fpts_pg
    base_fpts   = target_fpts - delta
    target_mpg  = base_mpg      <- the honest record: the delta was applied at UNCHANGED minutes
    target_fpm  = target_fpts / base_mpg   <- the per-minute rate the board now asserts

so the reconciliation identities hold by construction, and `healthy_fpm` then exposes which
entries silently assert above-career per-minute value (the Trae Young defect). Every block is
stamped `retrofilled:` so a future pass can tell it from a real sized belief and replace it.

Only entries the board actually applies are filled (matched on name + `analyst_date`);
superseded entries are history and are left alone. Comments in the YAML are preserved by
inserting text before each entry's `status:` line rather than round-tripping the file.

    python scripts/retrofill_sizing.py [--write]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import yaml

from fantasy_nba.config import CONFIG_DIR, PROCESSED_DIR
from fantasy_nba.data import storage
from fantasy_nba.models._core import COUNTING, _season_start
from fantasy_nba.models.analyst import name_key
from fantasy_nba.scoring import load_scoring, score_frame

BASE_SEASON = "2025-26"
SMALL_SAMPLE_GP = 25     # the threshold the contract calls a small-sample base
MIN_HEALTHY_GP = 40
STAMP = "2026-07-25"


def season_rates() -> pd.DataFrame:
    """Per-game fpts / mpg / fpts-per-minute for every (PLAYER_ID, SEASON)."""
    ss = storage.read("player_season_stats")
    cfg = load_scoring(None)
    pg = ss.copy()
    for canon, src in COUNTING.items():
        pg[canon] = ss[src] / ss["GP"].clip(lower=1)
    pg["fpts_pg"] = score_frame(pg, cfg)
    pg["mpg"] = ss["MIN"] / ss["GP"].clip(lower=1)
    pg["fpm"] = pg["fpts_pg"] / pg["mpg"].replace(0, pd.NA)
    return pg[["PLAYER_ID", "PLAYER_NAME", "SEASON", "GP", "fpts_pg", "mpg", "fpm"]]


def build_blocks(proposals: list[dict], board: pd.DataFrame, rates: pd.DataFrame) -> dict:
    """(name_key, date) -> sizing dict, for the entries the board actually applies."""
    eff = board[board["analyst_action"].fillna("").str.startswith("fpts_delta")]
    by_key = {(name_key(r.PLAYER_NAME), str(r.analyst_date)): r for r in eff.itertuples()}
    out = {}
    for p in proposals:
        act = p.get("action")
        if not isinstance(act, dict) or "fpts_delta" not in act:
            continue
        key = (name_key(p["name"]), str(p["date"]))
        row = by_key.get(key)
        if row is None:
            continue  # superseded or never promoted — leave history alone
        delta = float(act["fpts_delta"])
        base_mpg, target_fpts = float(row.mpg), float(row.fpts_pg)
        if base_mpg <= 0:
            continue
        blk = {
            "base_fpts": round(target_fpts - delta, 2),
            "base_mpg": round(base_mpg, 1),
            "target_mpg": round(base_mpg, 1),
            "target_fpm": round(target_fpts / base_mpg, 3),
            "target_fpts": round(target_fpts, 2),
        }
        hist = rates[(rates.PLAYER_ID == row.PLAYER_ID)
                     & (rates.SEASON.map(_season_start) < _season_start(BASE_SEASON))
                     & (rates.GP >= MIN_HEALTHY_GP)]
        if not hist.empty:
            h = hist.sort_values("SEASON", key=lambda c: c.map(_season_start)).iloc[-1]
            blk["healthy_fpm"] = round(float(h.fpm), 3)
            blk["healthy_mpg"] = round(float(h.mpg), 1)
            blk["healthy_season"] = str(h.SEASON)
            cur = rates[(rates.PLAYER_ID == row.PLAYER_ID) & (rates.SEASON == BASE_SEASON)]
            if not cur.empty and int(cur.iloc[0].GP) < SMALL_SAMPLE_GP:
                blk["base_gp"] = int(cur.iloc[0].GP)
                blk["rate_held"] = round(float(cur.iloc[0].fpm) / float(h.fpm), 2)
        blk["retrofilled"] = STAMP
        out[key] = blk
    return out


def render(blk: dict) -> list[str]:
    lines = ["  sizing:"]
    for k, v in blk.items():
        lines.append(f"    {k}: {v}")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Retro-fill sizing blocks onto promoted proposals.")
    ap.add_argument("--proposals", default=str(CONFIG_DIR / "analyst_proposals.yaml"))
    ap.add_argument("--board", default=str(PROCESSED_DIR / "learned_2026-27_analyst.parquet"))
    ap.add_argument("--write", action="store_true", help="Edit the file (default: dry run).")
    args = ap.parse_args()

    path = Path(args.proposals)
    proposals = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    board = pd.read_parquet(args.board)
    blocks = build_blocks(proposals, board, season_rates())
    print(f"{len(blocks)} effective delta entries to fill "
          f"(of {sum(1 for p in proposals if isinstance(p.get('action'), dict))} non-none proposals)")

    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, l in enumerate(lines) if re.match(r"^- name: ", l)]
    bounds = starts + [len(lines)]
    inserts: dict[int, list[str]] = {}
    flagged = []
    for n, i in enumerate(starts):
        blockend = bounds[n + 1]
        seg = lines[i:blockend]
        if any(re.match(r"^  sizing:", s) for s in seg):
            continue
        name = lines[i][len("- name: "):].strip().strip("'\"")
        date = next((s.split(":", 1)[1].strip() for s in seg if re.match(r"^  date: ", s)), None)
        blk = blocks.get((name_key(name), str(date)))
        if blk is None:
            continue
        sidx = next(j for j in range(i, blockend) if re.match(r"^  status: ", lines[j]))
        inserts[sidx] = render(blk)
        if "healthy_fpm" in blk and blk["target_fpm"] > blk["healthy_fpm"] + 0.02:
            flagged.append((name, blk["target_fpm"], blk["healthy_fpm"],
                            blk.get("rate_held"), blk.get("base_gp")))

    out: list[str] = []
    for idx, l in enumerate(lines):
        if idx in inserts:
            out.extend(inserts[idx])
        out.append(l)

    print(f"inserting {len(inserts)} blocks")
    if flagged:
        print(f"\n{len(flagged)} assert per-minute value ABOVE the last healthy season "
              f"(implied vs healthy fpts/min):")
        for nm, tf, hf, rh, gp in sorted(flagged, key=lambda x: x[1] - x[2], reverse=True):
            extra = f"  [base {gp} gp, rate_held {rh}]" if gp else ""
            print(f"  {nm:<24} {tf:.3f} vs {hf:.3f}  (+{tf - hf:.3f}){extra}")

    if args.write:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        after = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert len(after) == len(proposals), "entry count changed — aborted state is on disk!"
        print(f"\nwrote {path} ({len(after)} entries intact)")
    else:
        print("\ndry run — pass --write to edit")


if __name__ == "__main__":
    main()
