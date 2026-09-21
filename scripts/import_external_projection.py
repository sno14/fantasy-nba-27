"""Normalize a copied private-league projection export into a dated local archive.

The browser copy is TSV-like rather than valid CSV: each position in the POS cell is
written on its own physical line. The normalized archive remains a local raw-data cache;
tracked analyst rationales refer only to a trusted external projection set.

Usage:
    python scripts/import_external_projection.py projections.csv --date 2026-09-21
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from fantasy_nba.config import RAW_DIR
from fantasy_nba.data import storage
from fantasy_nba.models.analyst import name_key


ARCHIVE_DIR = RAW_DIR / "market"


def parse_projection_export(path: str | Path) -> pd.DataFrame:
    """Repair multiline position cells and return the canonical projection columns."""
    source_path = Path(path)
    lines = source_path.read_text(encoding="utf-8-sig").splitlines()
    expected = ["R#", "ADP", "PLAYER", "AVG", "POS", "TEAM", "GP", "MPG"]
    if not lines or lines[0].split("\t") != expected:
        got = lines[0].split("\t") if lines else []
        raise ValueError(f"Unexpected external projection header: {got}; expected {expected}")

    records: list[dict] = []
    i = 1
    while i < len(lines):
        lead = lines[i].split("\t")
        line_no = i + 1
        if len(lead) != 5 or not lead[0].strip().isdigit():
            raise ValueError(f"Malformed player lead line {line_no}: {lines[i]!r}")
        rank, adp, player, avg, blank_pos = lead
        if blank_pos.strip():
            raise ValueError(f"Expected split POS cell on line {line_no}: {lines[i]!r}")
        i += 1

        positions: list[str] = []
        while i < len(lines):
            tail = lines[i].split("\t")
            if len(tail) == 3:
                team, gp, mpg = tail
                i += 1
                break
            if len(tail) != 1 or not tail[0].strip():
                raise ValueError(f"Malformed POS line {i + 1}: {lines[i]!r}")
            positions.append(tail[0].strip())
            i += 1
        else:
            raise ValueError(f"Missing TEAM/GP/MPG tail for rank {rank} ({player})")

        if not positions:
            raise ValueError(f"Missing position for rank {rank} ({player})")
        records.append({
            "external_rank": int(rank),
            "player": player.strip(),
            "team": team.strip(),
            "pos": "/".join(positions),
            "external_fpts_pg": pd.to_numeric(avg, errors="raise"),
            "adp": pd.to_numeric(adp, errors="coerce"),
            "gp": int(gp),
            "mpg": pd.to_numeric(mpg, errors="raise"),
        })

    df = pd.DataFrame(records)
    if df["external_rank"].tolist() != list(range(1, len(df) + 1)):
        raise ValueError("External projection ranks must be unique, ordered, and contiguous from 1")
    if df["player"].duplicated().any():
        dupes = df.loc[df["player"].duplicated(False), "player"].tolist()
        raise ValueError(f"Duplicate players in external projection export: {dupes}")
    if not df["gp"].between(0, 82).all() or not df["mpg"].between(0, 48).all():
        raise ValueError("External GP/MPG values fall outside basketball bounds")
    return df


def archive_projection_export(path: str | Path, pulled: str | None = None) -> pd.DataFrame:
    """Normalize, name-key, validate, and archive one private projection snapshot."""
    stamp = pulled or dt.date.today().isoformat()
    try:
        dt.date.fromisoformat(stamp)
    except ValueError as exc:
        raise ValueError(f"--date must be YYYY-MM-DD, got {stamp!r}") from exc

    df = parse_projection_export(path)
    df["name_key"] = df["player"].map(name_key)
    df.insert(0, "source", "trusted_external_projection")
    df.insert(1, "pulled", stamp)

    known = set(storage.read("player_season_stats")["PLAYER_NAME"].map(name_key))
    matched = df["name_key"].isin(known)
    top = df["external_rank"] <= 150
    print(f"[external projection] {len(df)} rows; match {matched.mean():.3f} overall, "
          f"{matched[top].mean():.3f} in top-150")
    misses = df.loc[top & ~matched, "player"].tolist()
    if misses:
        print(f"[external projection] top-150 unmatched (rookies expected): {misses[:12]}")

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    destination = ARCHIVE_DIR / f"external_projection_{stamp}.parquet"
    if destination.exists():
        existing = pd.read_parquet(destination)
        if existing.equals(df):
            print(f"[external projection] identical archive already exists -> {destination}")
            return df
        raise FileExistsError(f"Refusing to overwrite existing dated archive: {destination}")
    df.to_parquet(destination, index=False)
    print(f"[external projection] saved -> {destination}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize a private projection export.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--date", default=None, metavar="YYYY-MM-DD")
    args = parser.parse_args()
    archive_projection_export(args.input, pulled=args.date)


if __name__ == "__main__":
    main()
