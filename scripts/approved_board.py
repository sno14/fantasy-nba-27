"""Refresh an explicitly approved analyst snapshot from saved inputs, without a fit.

Used only by proposal promotion. Ordinary reads and exports retain the accepted
snapshot. External-only rows keep their source provenance and missing ranges.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from fantasy_nba.models.analyst import apply_overrides, name_key
from fantasy_nba.models.uncertainty import rank_board, simulate_ranges


def proposal_base(model: pd.DataFrame, accepted: pd.DataFrame,
                  external: pd.DataFrame) -> pd.DataFrame:
    """Restore pure model values and original external seeds, never adjusted B."""
    if model.PLAYER_ID.duplicated().any() or accepted.PLAYER_ID.duplicated().any():
        raise ValueError("Snapshot player identities must be unique")
    if not set(model.PLAYER_ID) <= set(accepted.PLAYER_ID):
        raise ValueError("Accepted snapshot is missing model players")
    base = accepted.copy().set_index("PLAYER_ID")
    original = model.set_index("PLAYER_ID")
    for column in original:
        if column != "rank":
            base.loc[original.index, column] = original[column]
    source = external.assign(name_key=external.player.map(name_key)).set_index("name_key")
    for pid in base.index.difference(original.index):
        key = name_key(base.at[pid, "PLAYER_NAME"])
        if key not in source.index:
            raise ValueError(f"No original source for external-only player {key}")
        row = source.loc[key]
        for column, field in (("fpts_pg", "external_fpts_pg"), ("gp", "gp"), ("mpg", "mpg")):
            base.at[pid, column] = float(row[field])
        base.at[pid, "fpts_total"] = base.at[pid, "fpts_pg"] * base.at[pid, "gp"]
    # apply_overrides recreates audit columns. No earlier analyst residual enters base.
    return base.reset_index()


def refresh_board(model: pd.DataFrame, accepted: pd.DataFrame, external: pd.DataFrame,
                  entries: list[dict], gp_pool: pd.DataFrame) -> pd.DataFrame:
    base = proposal_base(model, accepted, external)
    updated = apply_overrides(base, entries).set_index("PLAYER_ID")
    before = accepted.set_index("PLAYER_ID")
    if not np.allclose(updated.gp, before.loc[updated.index, "gp"], equal_nan=True):
        raise ValueError("Analyst approval must preserve GP")
    changed = ~np.isclose(updated.fpts_pg, before.loc[updated.index, "fpts_pg"], atol=1e-8)
    # Use the existing simulator and fixed ID order, so proposal ordering cannot
    # change random draws. Recompute only changed model players' dependent ranges.
    simulated = simulate_ranges(updated.loc[sorted(model.PLAYER_ID)].reset_index(), gp_pool).set_index("PLAYER_ID")
    range_columns = [c for c in simulated if
                     (c.startswith("fpts_p") and c[6:].isdigit()) or c in ("fpts_median", "risk")]
    changed_ids = updated.index[changed].intersection(simulated.index)
    for column in range_columns:
        if column in before:
            updated[column] = before.loc[updated.index, column]
        if column in updated:
            updated.loc[changed_ids, column] = simulated.loc[changed_ids, column]
    updated["model_rank"] = updated.index.map(model.set_index("PLAYER_ID")["rank"])
    if "previous_fpts_pg" in updated:
        updated["fpts_pg_change"] = (updated.fpts_pg - updated.previous_fpts_pg).round(2)
    # Public ranks will be derived separately from FP/G by export_static.
    return rank_board(updated.reset_index().sort_values("PLAYER_ID"), method="safe")


def refresh_approved_snapshot() -> pd.DataFrame:
    from fantasy_nba.api import boards
    from fantasy_nba.models.analyst import load_overrides
    from fantasy_nba.models.external_projection import load_latest
    from fantasy_nba.models.uncertainty import build_gp_pool
    from fantasy_nba.config import PROCESSED_DIR

    accepted = boards.accepted_board(True)
    model = pd.read_parquet(PROCESSED_DIR / "learned_2026-27.parquet")
    _, chronic = boards._injury_profile(boards._spells_key())
    pool = build_gp_pool(boards.raw("player_season_stats"), boards.raw("player_bio"),
                         max_start_year=2026, injury_profile=chronic)
    updated = refresh_board(model, accepted, load_latest(), load_overrides(), pool)
    updated = boards.add_tiers(updated)
    path = PROCESSED_DIR / "learned_2026-27_analyst.parquet"
    pending = path.with_suffix(".pending.parquet")
    updated.to_parquet(pending, index=False)
    pending.replace(path)
    return updated
