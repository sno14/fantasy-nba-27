"""Shared projection machinery used by both the baseline and v2 models.

The common work — recency-weighting seasons, aggregating per-player totals, regressing
per-minute rates toward league average, and deriving age / minutes / games metadata — lives
here. Models differ only in how they apply *aging* and project *games played*.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MPG_CAP = 42.0  # mirrors the learned model's own clip; the ceiling for any minutes edit

# Canonical (lowercase, matches scoring keys) -> source column in player_season_stats.
COUNTING = {
    "fgm": "FGM",
    "fga": "FGA",
    "fg3m": "FG3M",
    "ftm": "FTM",
    "fta": "FTA",
    "oreb": "OREB",
    "dreb": "DREB",
    "reb": "REB",
    "ast": "AST",
    "stl": "STL",
    "blk": "BLK",
    "tov": "TOV",
    "pts": "PTS",
}

DEFAULT_WEIGHTS = (5.0, 4.0, 3.0)  # most-recent season first
DEFAULT_REG_MINUTES = 750.0  # regression strength, in minutes of league-average play


def rescale_to_minutes(board, mask, new_mpg, cfg):
    """Move masked rows to ``new_mpg`` **holding per-minute rates**, in place.

    The one place minutes are edited on a projected board, shared by EXP-030's
    OUT-redistribution (``absorption.redistribute_board``) and the analyst layer's
    ``target_mpg`` (``analyst.apply_overrides``). Per-game counting stats scale by the
    minutes ratio and ``fpts_pg`` / ``fpts_total`` are recomputed from the scaled line.

    Two invariants worth stating, because both have been got wrong before:

    * **Rates are held flat — no per-36 "fade" in either direction.** EXP-034 measured that
      coefficient across 2428 consecutive-season pairs with a >= 2 mpg move: realised/naive
      is 1.05-1.10 on increases (even age-30+ veterans sit at 1.022), so the ~0.85 haircut
      the sizing rubric used to prescribe was directionally wrong. 1.0 is the honest default
      — the measured excess is mostly selection we cannot identify ex ante.
    * **fpts is RE-SCORED, never scaled.** It is exactly linear in the counting stats under
      today's empty ``bonuses``, so scaling would agree to the cent — but a future
      double-double bonus would make that silently wrong.

    ``new_mpg`` is clipped to ``[0, MPG_CAP]``. Rows where the old mpg is 0 (nothing to hold
    a rate constant against) are left untouched. Does NOT re-sort or renumber ``rank`` — the
    caller owns ordering, since it may apply several edits before re-ranking.
    """
    from ..scoring import score_frame  # local: keeps module import order simple

    if not mask.any():
        return board
    old = board.loc[mask, "mpg"].astype(float)
    new = np.clip(new_mpg, 0.0, MPG_CAP)
    if not isinstance(new, pd.Series):  # a scalar target applies to every masked row
        new = pd.Series(float(new), index=old.index)
    ratio = (new / old.replace(0.0, np.nan)).fillna(1.0)
    for canon in COUNTING:
        if canon in board.columns:
            board.loc[mask, canon] = (board.loc[mask, canon].astype(float) * ratio).round(2)
    board.loc[mask, "mpg"] = new.round(1)
    board.loc[mask, "fpts_pg"] = score_frame(board.loc[mask], cfg).round(2)
    if "fpts_total" in board.columns and "gp" in board.columns:
        board.loc[mask, "fpts_total"] = (
            board.loc[mask, "fpts_pg"] * board.loc[mask, "gp"]).round(1)
    return board


def _season_start(season: str) -> int:
    """'2025-26' -> 2025."""
    return int(season[:4])


def weighted_aggregates(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    target_season: str,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
    include_ids: set | None = None,
) -> pd.DataFrame:
    """Per-player recency-weighted aggregates + regressed per-minute rates.

    Returns one row per player active in the most recent season (plus any PLAYER_ID in
    ``include_ids`` — returning vets with prior history but zero most-recent games, projected
    from their last healthy season; ``target_age`` for those uses their own last-played
    season so the aging is correct), with:
      * ``from_age``    minutes-weighted mean age across the seasons used (the age the rate
                        was effectively measured at — the 'from' point for aging)
      * ``recent_age``  age in the most recent season
      * ``target_age``  projected age in ``target_season``
      * ``proj_mpg``    recency-weighted minutes per game
      * ``weighted_gp`` recency-weighted games played
      * ``recent_gp``   games played in the most recent season
      * ``rate_<stat>`` regressed per-minute rate for each counting stat
    """
    seasons = sorted(season_stats["SEASON"].unique(), key=_season_start, reverse=True)[:n_seasons]
    most_recent = seasons[0]
    w_map = {s: (weights[i] if i < len(weights) else weights[-1]) for i, s in enumerate(seasons)}

    src_cols = ["MIN", "GP"] + list(COUNTING.values())
    df = season_stats[season_stats["SEASON"].isin(seasons)].copy()
    df = df.groupby(["PLAYER_ID", "PLAYER_NAME", "SEASON"], as_index=False)[src_cols].sum()

    ages = bio[["PLAYER_ID", "SEASON", "AGE"]].drop_duplicates(["PLAYER_ID", "SEASON"])
    df = df.merge(ages, on=["PLAYER_ID", "SEASON"], how="left")

    df["w"] = df["SEASON"].map(w_map).astype(float)
    df["wMIN"] = df["w"] * df["MIN"]
    df["wGP"] = df["w"] * df["GP"]
    df["wMINAGE"] = df["wMIN"] * df["AGE"]
    for src in COUNTING.values():
        df[f"w_{src}"] = df["w"] * df[src]

    spec = {
        "wMIN": ("wMIN", "sum"),
        "wGP": ("wGP", "sum"),
        "w": ("w", "sum"),
        "wMINAGE": ("wMINAGE", "sum"),
    }
    spec.update({f"w_{s}": (f"w_{s}", "sum") for s in COUNTING.values()})
    agg = df.groupby(["PLAYER_ID", "PLAYER_NAME"], as_index=False).agg(**spec)

    # League minutes-weighted per-minute rate (full population, before filtering to active).
    total_min = agg["wMIN"].sum()
    league_rate = {c: agg[f"w_{src}"].sum() / total_min for c, src in COUNTING.items()}

    # Keep players active in the most recent season, plus any explicitly included returning
    # vets (prior history, zero most-recent games — projected from their last healthy season).
    recent = season_stats[season_stats["SEASON"] == most_recent]
    keep_ids = set(recent["PLAYER_ID"])
    if include_ids:
        keep_ids |= set(include_ids)
    agg = agg[agg["PLAYER_ID"].isin(keep_ids)].reset_index(drop=True)

    recent_age = (
        bio.loc[bio["SEASON"] == most_recent, ["PLAYER_ID", "AGE"]]
        .drop_duplicates("PLAYER_ID")
        .rename(columns={"AGE": "recent_age"})
    )
    recent_gp = (
        recent.groupby("PLAYER_ID", as_index=False)["GP"].sum().rename(columns={"GP": "recent_gp"})
    )
    agg = agg.merge(recent_age, on="PLAYER_ID", how="left").merge(recent_gp, on="PLAYER_ID", how="left")

    gap = _season_start(target_season) - _season_start(most_recent)
    agg["from_age"] = (agg["wMINAGE"] / agg["wMIN"]).fillna(agg["recent_age"])
    agg["from_age"] = agg["from_age"].fillna(agg["from_age"].median())
    agg["target_age"] = (agg["recent_age"] + gap).fillna((agg["from_age"] + gap))
    if include_ids:
        # Returning vets are absent from the most recent season, so recent_age+gap under-ages
        # them. Use their OWN last-played season age + years-to-target (exact); leaves every
        # active player untouched.
        latest = bio.dropna(subset=["AGE"]).sort_values("SEASON").groupby("PLAYER_ID").tail(1)
        own_target_age = dict(
            zip(latest["PLAYER_ID"],
                latest["AGE"] + (_season_start(target_season)
                                 - latest["SEASON"].map(_season_start)))
        )
        mask = agg["PLAYER_ID"].isin(include_ids)
        agg.loc[mask, "target_age"] = (
            agg.loc[mask, "PLAYER_ID"].map(own_target_age).fillna(agg.loc[mask, "target_age"])
        )
    agg["target_age"] = agg["target_age"].fillna(agg["target_age"].median())
    agg["proj_mpg"] = agg["wMIN"] / agg["wGP"]
    agg["weighted_gp"] = agg["wGP"] / agg["w"]

    for canon, src in COUNTING.items():
        agg[f"rate_{canon}"] = (agg[f"w_{src}"] + reg_minutes * league_rate[canon]) / (
            agg["wMIN"] + reg_minutes
        )

    return agg
