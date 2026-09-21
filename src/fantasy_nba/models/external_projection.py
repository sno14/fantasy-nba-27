"""Board overlay for a dated, trusted external projection snapshot.

The learned model remains the source for players it can project.  This module only
refreshes display teams and supplies explicitly flagged projection rows for players
missing from that model (typically incoming rookies and returning veterans).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import RAW_DIR
from .analyst import name_key


ARCHIVE_DIR = RAW_DIR / "market"
ARCHIVE_GLOB = "external_projection_*.parquet"
SEED_CLASS = "external-projection"

# The copied export uses common broadcast abbreviations for four teams.  Internally the
# project uses NBA Stats' three-letter abbreviations everywhere else.
TEAM_ALIASES = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "PHO": "PHX",
    "SA": "SAS",
}


def latest_path() -> Path | None:
    """Return the newest dated snapshot, if one is cached locally."""
    paths = sorted(ARCHIVE_DIR.glob(ARCHIVE_GLOB))
    return paths[-1] if paths else None


def latest_mtime() -> float:
    path = latest_path()
    return path.stat().st_mtime if path else 0.0


def load_latest() -> pd.DataFrame:
    path = latest_path()
    return pd.read_parquet(path) if path else pd.DataFrame()


def canonical_team(team: object) -> object:
    if pd.isna(team):
        return np.nan
    value = str(team).strip().upper()
    if not value or value == "FA":
        return np.nan
    return TEAM_ALIASES.get(value, value)


def _board_only_id(key: str) -> int:
    """Stable negative UI identifier; deliberately outside the NBA PLAYER_ID domain."""
    digest = hashlib.sha256(f"external-projection:{key}".encode()).digest()
    return -(int.from_bytes(digest[:8], "big") % 2_000_000_000 + 1)


def overlay_external_projection(
    board: pd.DataFrame,
    external: pd.DataFrame,
    season_stats: pd.DataFrame,
) -> pd.DataFrame:
    """Apply source teams and append source-projected rows missing from ``board``.

    Existing projection values are never replaced here.  Missing players receive the
    external FP/G, GP, MPG and ADP values and remain visibly marked as market priced.
    Known veterans reuse their NBA id; players not yet in NBA Stats get a deterministic
    negative board-only id so the static UI can still address them safely.
    """
    if external.empty:
        return board.copy()

    required = {"player", "team", "external_fpts_pg", "adp", "gp", "mpg", "name_key"}
    missing = required - set(external.columns)
    if missing:
        raise ValueError(f"External projection is missing required columns: {sorted(missing)}")

    out = board.copy()
    ext = external.drop_duplicates("name_key", keep="first").copy()
    ext["team"] = ext["team"].map(canonical_team)
    ext_by_key = ext.set_index("name_key")
    board_keys = out["PLAYER_NAME"].map(name_key)

    # The dated external team field is the user's chosen current-team authority.  This is
    # display reconciliation only; it does not mutate the model's roster/allocation inputs.
    source_teams = board_keys.map(ext_by_key["team"])
    team_mask = source_teams.notna()
    out.loc[team_mask, "TEAM_ABBREVIATION"] = source_teams[team_mask].to_numpy()

    missing_ext = ext[~ext["name_key"].isin(set(board_keys))].copy()
    if missing_ext.empty:
        return out

    stats = season_stats.sort_values("SEASON").copy()
    stats["name_key"] = stats["PLAYER_NAME"].map(name_key)
    id_map = stats.drop_duplicates("name_key", keep="last").set_index("name_key")["PLAYER_ID"]

    extras = pd.DataFrame(index=missing_ext.index)
    extras["PLAYER_ID"] = missing_ext["name_key"].map(id_map)
    no_nba_id = extras["PLAYER_ID"].isna()
    extras.loc[no_nba_id, "PLAYER_ID"] = missing_ext.loc[no_nba_id, "name_key"].map(_board_only_id)
    extras["PLAYER_ID"] = extras["PLAYER_ID"].astype("int64")
    extras["PLAYER_NAME"] = missing_ext["player"]
    extras["TEAM_ABBREVIATION"] = missing_ext["team"]
    extras["gp"] = pd.to_numeric(missing_ext["gp"], errors="raise")
    extras["mpg"] = pd.to_numeric(missing_ext["mpg"], errors="raise")
    extras["fpts_pg"] = pd.to_numeric(missing_ext["external_fpts_pg"], errors="raise")
    extras["fpts_total"] = extras["fpts_pg"] * extras["gp"]
    extras["adp"] = pd.to_numeric(missing_ext["adp"], errors="coerce")
    extras["market_priced"] = 1
    extras["seed_class"] = SEED_CLASS
    extras["analyst_action"] = ""
    extras["analyst_category"] = ""
    extras["analyst_date"] = ""

    collisions = set(extras["PLAYER_ID"]) & set(out["PLAYER_ID"])
    if collisions:
        raise ValueError(f"Board-only id collision while adding external rows: {sorted(collisions)}")
    return pd.concat([out, extras], ignore_index=True, sort=False)
