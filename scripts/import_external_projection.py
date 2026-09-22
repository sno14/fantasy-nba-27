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

LEGACY_HEADER = ["R#", "ADP", "PLAYER", "AVG", "POS", "TEAM", "GP", "MPG"]
STAT_HEADER = [
    "R#", "PLAYER", "AVG", "POS", "TEAM", "GP", "MPG", "FGM", "FGA", "FTM",
    "FTA", "3PM", "PTS", "TREB", "AST", "STL", "BLK", "TO",
]
STAT_RENAMES = {
    "FGM": "fgm", "FGA": "fga", "FTM": "ftm", "FTA": "fta", "3PM": "fg3m",
    "PTS": "pts", "TREB": "reb", "AST": "ast", "STL": "stl", "BLK": "blk",
    "TO": "tov",
}

# Some browser copies replace non-ASCII letters with U+FFFD before the file reaches us.
# These are source-text repairs, not player aliases: the canonical spelling is retained in
# the normalized archive while name_key still owns cross-source matching.
TEXT_REPAIRS = {
    "Alperen Seng\ufffdn": "Alperen Sengün",
    "Moussa Diabat\ufffd": "Moussa Diabaté",
    "Dennis Schr\ufffdder": "Dennis Schröder",
}


def parse_projection_export(path: str | Path) -> pd.DataFrame:
    """Repair multiline position cells and return the canonical projection columns."""
    source_path = Path(path)
    lines = source_path.read_text(encoding="utf-8-sig").splitlines()
    header = lines[0].split("\t") if lines else []
    if header not in (LEGACY_HEADER, STAT_HEADER):
        got = lines[0].split("\t") if lines else []
        raise ValueError(
            f"Unexpected external projection header: {got}; expected {LEGACY_HEADER} "
            f"or {STAT_HEADER}"
        )

    has_adp = header == LEGACY_HEADER
    tail_columns = header[header.index("TEAM"):]
    lead_width = header.index("TEAM")

    records: list[dict] = []
    i = 1
    while i < len(lines):
        lead = lines[i].split("\t")
        line_no = i + 1
        if len(lead) != lead_width or not lead[0].strip().isdigit():
            raise ValueError(f"Malformed player lead line {line_no}: {lines[i]!r}")
        if has_adp:
            rank, adp, player, avg, blank_pos = lead
        else:
            rank, player, avg, blank_pos = lead
            adp = None
        if blank_pos.strip():
            raise ValueError(f"Expected split POS cell on line {line_no}: {lines[i]!r}")
        i += 1

        positions: list[str] = []
        while i < len(lines):
            tail = lines[i].split("\t")
            if len(tail) == len(tail_columns):
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
        tail_values = dict(zip(tail_columns, tail))
        record = {
            "external_rank": int(rank),
            "player": TEXT_REPAIRS.get(player.strip(), player.strip()),
            "team": tail_values["TEAM"].strip(),
            "pos": "/".join(positions),
            "external_fpts_pg": pd.to_numeric(avg, errors="raise"),
            "adp": pd.to_numeric(adp, errors="coerce"),
            "gp": int(tail_values["GP"]),
            "mpg": pd.to_numeric(tail_values["MPG"], errors="raise"),
        }
        for source_name, canonical in STAT_RENAMES.items():
            if source_name in tail_values:
                record[canonical] = pd.to_numeric(tail_values[source_name], errors="raise")
        records.append(record)

    df = pd.DataFrame(records)
    if df["external_rank"].tolist() != list(range(1, len(df) + 1)):
        raise ValueError("External projection ranks must be unique, ordered, and contiguous from 1")
    if df["player"].duplicated().any():
        dupes = df.loc[df["player"].duplicated(False), "player"].tolist()
        raise ValueError(f"Duplicate players in external projection export: {dupes}")
    if not df["gp"].between(0, 82).all() or not df["mpg"].between(0, 48).all():
        raise ValueError("External GP/MPG values fall outside basketball bounds")
    if set(STAT_RENAMES.values()).issubset(df.columns):
        # ESPN default scoring, deliberately expanded rather than calling score_line row by
        # row so the import check stays vectorized and reports the source's rounded-line drift.
        scored = (
            df["pts"] + df["fg3m"] + 2 * df["fgm"] - df["fga"] + df["ftm"]
            - df["fta"] + df["reb"] + 2 * df["ast"] + 4 * df["stl"]
            + 4 * df["blk"] - 2 * df["tov"]
        )
        df["scored_fpts_pg"] = scored.round(2)
        df["source_fpts_rounding_gap"] = (df["external_fpts_pg"] - scored).round(2)
        if df["source_fpts_rounding_gap"].abs().max() > 0.65:
            bad = df.loc[df["source_fpts_rounding_gap"].abs() > 0.65,
                         ["player", "external_fpts_pg", "scored_fpts_pg"]]
            raise ValueError(f"External AVG does not reconcile with the stat line:\n{bad}")
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
    stem = ARCHIVE_DIR / f"external_projection_{stamp}"
    destination = stem.with_suffix(".parquet")
    normalized_csv = ARCHIVE_DIR / f"{stem.name}.normalized.csv"
    source_copy = ARCHIVE_DIR / f"{stem.name}.source.tsv"
    if destination.exists() or normalized_csv.exists() or source_copy.exists():
        if not destination.exists() or not normalized_csv.exists():
            raise FileExistsError(f"Incomplete dated archive exists for {stamp}; refusing to overwrite")
        existing = pd.read_parquet(destination)
        if existing.equals(df):
            print(f"[external projection] identical archive already exists -> {destination}")
            return df
        raise FileExistsError(f"Refusing to overwrite existing dated archive: {destination}")
    source_copy.write_bytes(Path(path).read_bytes())
    df.to_csv(normalized_csv, index=False, float_format="%.2f", encoding="utf-8")
    df.to_parquet(destination, index=False)
    print(f"[external projection] normalized CSV -> {normalized_csv}")
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
