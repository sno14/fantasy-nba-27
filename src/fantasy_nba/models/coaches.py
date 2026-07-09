"""Coaching-change features (Step 9c / EXP-027a, ROADMAP 7.B addendum).

Hypothesis: a new head coach reshuffles the *rotation*, so the fantasy-relevant effect lives
in young/fringe players, not in a main effect — hence the explicit interactions with
depth-rank and age rather than a lone team-level flag.

Source: ``data/manual/coach_changes.csv`` — the repo's first committed manual dataset
(gitignore exception). One row per (season, team) whose **opening-night** head coach differs
from the previous season's opening-night head coach, 2009-10…2026-27, hand-curated from
Basketball-Reference season coach pages (2026-27 from the league's 2026 offseason trackers).
``interim`` = 1 when the new coach already ran the team mid-prior-season (interim or
mid-season hire retained) or opens the season on an interim basis — the reshuffle partially
happened before this preseason, so the flag separates "new voice" from "continuity promotion".

The season-keyed feature table follows the EXP-016b pattern: each block reads the honest
Oct-1 roster map + prior-season stats only, so it is computed once and sliced per fold.
"""

from __future__ import annotations

import pandas as pd

from ..config import MANUAL_DIR
from ._core import _season_start
from .context import season_before
from .rosters import preseason_roster_map

COACH_FEATURES = [
    "new_coach",           # target team's opening-night HC differs from last season's (0/1)
    "new_coach_interim",   # …and he is an interim / retained mid-prior-season takeover
    "new_coach_x_depth",   # new_coach × depth_rank (1 = prior-minutes leader on the Oct-1 roster)
    "new_coach_x_young",   # new_coach × (target-season age ≤ 24)
]

YOUNG_AGE_MAX = 24  # matches the breakout research's window upper edge

# Franchise renames within the panel era: the coach CSV uses each season's own abbreviation,
# the Oct-1 map inherits the *prior* season's — normalize both sides before joining.
FRANCHISE_MOVES = {"NOH": "NOP", "NJN": "BKN"}


def _franchise(team: pd.Series) -> pd.Series:
    return team.replace(FRANCHISE_MOVES)


def load_coach_changes(path=None) -> pd.DataFrame:
    """Read + validate the hand-curated CSV: required columns, no duplicate (season, team)."""
    path = path or MANUAL_DIR / "coach_changes.csv"
    df = pd.read_csv(path)
    required = {"season", "team", "new_coach", "interim"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"coach_changes.csv missing columns: {sorted(missing)}")
    dupes = df[df.duplicated(["season", "team"], keep=False)]
    if not dupes.empty:
        raise ValueError(f"coach_changes.csv has duplicate (season, team) rows:\n{dupes}")
    df["interim"] = df["interim"].astype(int)
    return df


def coach_feature_table(
    season_stats: pd.DataFrame,
    transactions: pd.DataFrame,
    bio: pd.DataFrame,
    coach_changes: pd.DataFrame | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """``[SEASON, PLAYER_ID, *COACH_FEATURES]`` per season block (fold-safe by construction).

    Per season S: the honest Oct-1 map assigns each player a team; ``new_coach`` fires when
    that team appears in the CSV for S. ``depth_rank`` = rank of the player's prior-season
    total minutes among his mapped teammates (1 = most minutes → fringe players get high
    ranks, so the interaction grows toward the end of the bench). Age = prior-season bio age
    + 1 (the breakout-table convention). Players off the Oct-1 map get no rows — consumers
    fill 0 (no team ⇒ no new-coach effect).
    """
    coach_changes = coach_changes if coach_changes is not None else load_coach_changes()
    cc = coach_changes.copy()
    cc["team"] = _franchise(cc["team"])

    if seasons is None:
        all_s = sorted(season_stats["SEASON"].unique(), key=_season_start)
        seasons = all_s[1:]

    ages = bio[["PLAYER_ID", "SEASON", "AGE"]].drop_duplicates(["PLAYER_ID", "SEASON"]).copy()
    ages["yr"] = ages["SEASON"].map(_season_start)
    age_of = ages.set_index(["PLAYER_ID", "yr"])["AGE"]

    frames = []
    for s in seasons:
        prev = season_before(s)
        if prev not in set(season_stats["SEASON"]):
            continue
        ty = _season_start(s)
        team_map = preseason_roster_map(season_stats, transactions, s)
        team_map = team_map.assign(team=_franchise(team_map["team"]))

        prior_min = (
            season_stats[season_stats["SEASON"] == prev]
            .groupby("PLAYER_ID", as_index=False)["MIN"].sum()
        )
        f = team_map.merge(prior_min, on="PLAYER_ID", how="left")
        f["MIN"] = f["MIN"].fillna(0.0)
        f["depth_rank"] = f.groupby("team")["MIN"].rank(ascending=False, method="first")

        changed = cc[cc["season"] == s].set_index("team")["interim"]
        f["new_coach"] = f["team"].isin(changed.index).astype(int)
        f["new_coach_interim"] = (f["new_coach"] * f["team"].map(changed).fillna(0)).astype(int)

        age_prev = pd.Series(
            [age_of.get((pid, ty - 1), pd.NA) for pid in f["PLAYER_ID"]], index=f.index
        )
        target_age = pd.to_numeric(age_prev, errors="coerce") + 1
        young = (target_age <= YOUNG_AGE_MAX).fillna(False).astype(int)

        f["new_coach_x_depth"] = f["new_coach"] * f["depth_rank"]
        f["new_coach_x_young"] = f["new_coach"] * young
        f.insert(0, "SEASON", s)
        frames.append(f[["SEASON", "PLAYER_ID"] + COACH_FEATURES])
    if not frames:
        raise ValueError("coach_feature_table needs at least two consecutive seasons.")
    return pd.concat(frames, ignore_index=True)
