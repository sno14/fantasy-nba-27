"""Team-constrained minutes allocation — feature layer (EXP-014 / implementation-plan Step 6).

The structural bet of the breakthrough plan (§1b): minutes are a **team-constrained
allocation** — 240 per game, divided over a specific roster by position and pecking order —
not a per-player time series. Every prior minutes treatment (v2m's aging trend, EXP-009's
per-player context covariates) ignores both the 240-minute budget and *who specifically*
competes for the vacated minutes.

This module implements the **feature and normalization layer** of that model, fully
unit-testable without data. The LightGBM share model itself (target ``y_min_share`` = player
season MIN / team season MIN) and its wiring into ``project_learned(minutes_mode=
"allocation")`` are built in Step 6 proper, because they need the historical-rosters pull
(positions per player-season) that only runs locally — see the step spec for the target
definition, the A/B design, and the adopt gate.

Position groups are deliberately coarse (guard vs big): roster POSITION strings are hybrid
and inconsistent ("G-F", "F-C"), and finer buckets go sparse. Unmapped strings raise loudly
rather than silently polluting the depth chart.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._core import _season_start

ALLOC_FEATURES = [
    "own_prev_share",             # own share of prior team's minutes (role he's coming from)
    "pos_group",                  # 0 = guard, 1 = big
    "same_pos_returning_share",   # Σ prior-team shares of same-pos teammates also on the target roster
    "same_pos_vacated_share",     # Σ prior-team shares of same-pos players who left the roster
    "depth_rank",                 # rank of own prior minutes among same-pos players on the target roster
    "n_same_pos",                 # roster crowding in his position group
]

_GUARD = {"G", "G-F"}
_BIG = {"F", "F-C", "F-G", "C", "C-F"}


def position_group(position: str) -> int:
    """Map a roster POSITION string to 0 (guard) / 1 (big). Raises on anything unmapped so a
    new NBA-API position string is a loud failure, not a silent depth-chart corruption."""
    p = str(position).strip().upper()
    if p in _GUARD:
        return 0
    if p in _BIG:
        return 1
    raise ValueError(f"Unmapped roster POSITION {position!r} — extend _GUARD/_BIG in allocation.py")


def _prev_team_minutes(season_stats: pd.DataFrame, season: str) -> pd.DataFrame:
    """One row per player for ``season``: primary (last) team + minutes (context.py convention)."""
    s = season_stats[season_stats["SEASON"] == season]
    return (
        s.groupby("PLAYER_ID", as_index=False)
        .agg(prev_team=("TEAM_ABBREVIATION", "last"), prev_min=("MIN", "sum"))
    )


def allocation_features(
    season_stats: pd.DataFrame,
    roster_map: pd.DataFrame,
    prev_season: str,
) -> pd.DataFrame:
    """Depth-chart / opportunity features for every player on a target roster.

    ``roster_map`` is ``[PLAYER_ID, team, pos_group]`` — the target-season roster with the
    coarse position group (from historical ``team_rosters`` in backtests, live rosters in
    production; strict preseason rosters once EXP-016 lands). ``season_stats`` must contain
    ``prev_season`` (whose minutes are being re-allocated). Returns
    ``[PLAYER_ID] + ALLOC_FEATURES``; players with no prior season get share/rank neutrals
    (0 shares; depth_rank = n_same_pos, i.e. bottom of their positional stack).

    No-leakage contract: prior-season minutes + a target-season roster fact — nothing dated
    inside the target season (same contract as ``context.py``).
    """
    prev = _prev_team_minutes(season_stats, prev_season)
    team_total = prev.groupby("prev_team")["prev_min"].sum().rename("prev_team_total")

    r = roster_map[["PLAYER_ID", "team", "pos_group"]].copy()
    r = r.merge(prev, on="PLAYER_ID", how="left")
    r = r.merge(team_total, left_on="prev_team", right_index=True, how="left")
    r["own_prev_share"] = (r["prev_min"] / r["prev_team_total"]).fillna(0.0)
    r["prev_min"] = r["prev_min"].fillna(0.0)

    # Prior-season rotation of each *target* team, split into returning (on the target roster)
    # vs vacated (gone), by position group. A departed player's pos_group comes from the prior
    # roster in a full pipeline; until the historical-roster pull exists, callers may pass a
    # roster_map that also covers departed players — rows whose team is NaN in roster terms.
    prior_rot = prev.merge(team_total, left_on="prev_team", right_index=True, how="left")
    prior_rot["share"] = prior_rot["prev_min"] / prior_rot["prev_team_total"]
    pos_of = roster_map.set_index("PLAYER_ID")["pos_group"]
    prior_rot["pos_group"] = prior_rot["PLAYER_ID"].map(pos_of)
    roster_of = roster_map.set_index("PLAYER_ID")["team"]
    prior_rot["target_team"] = prior_rot["PLAYER_ID"].map(roster_of)
    prior_rot["returning"] = prior_rot["target_team"] == prior_rot["prev_team"]

    rows = []
    for (team, pos), grp in r.groupby(["team", "pos_group"]):
        # Same-pos prior-season rotation of this target team:
        rot = prior_rot[(prior_rot["prev_team"] == team) & (prior_rot["pos_group"] == pos)]
        returning_share = rot.loc[rot["returning"], "share"].sum()
        vacated_share = rot.loc[~rot["returning"], "share"].sum()
        # Depth rank among same-pos players on this roster, by prior-season minutes anywhere.
        order = grp["prev_min"].rank(ascending=False, method="min")
        for idx, row in grp.iterrows():
            own_returning = row["own_prev_share"] if row["prev_team"] == team else 0.0
            rows.append({
                "PLAYER_ID": row["PLAYER_ID"],
                "own_prev_share": row["own_prev_share"],
                "pos_group": pos,
                "same_pos_returning_share": max(returning_share - own_returning, 0.0),
                "same_pos_vacated_share": vacated_share,
                "depth_rank": int(order.loc[idx]),
                "n_same_pos": len(grp),
            })
    return pd.DataFrame(rows, columns=["PLAYER_ID"] + ALLOC_FEATURES)


def rookie_reserve(season_stats: pd.DataFrame) -> float:
    """League-average share of a team's season minutes played by players with **no
    prior-season row** (rookies / returnees the panel can't model). Used to leave headroom
    when normalizing predicted shares — measured, not guessed. Computed over every season
    with a predecessor in ``season_stats``."""
    seasons = sorted(season_stats["SEASON"].unique(), key=_season_start)
    shares = []
    for prev_s, s in zip(seasons, seasons[1:]):
        cur = season_stats[season_stats["SEASON"] == s]
        known = set(season_stats.loc[season_stats["SEASON"] == prev_s, "PLAYER_ID"])
        by_team = cur.groupby("TEAM_ABBREVIATION").apply(
            lambda g: g.loc[~g["PLAYER_ID"].isin(known), "MIN"].sum() / max(g["MIN"].sum(), 1e-9),
            include_groups=False,
        )
        shares.extend(by_team.tolist())
    if not shares:
        raise ValueError("rookie_reserve needs at least two consecutive seasons.")
    return float(np.mean(shares))


def normalize_shares(pred: pd.DataFrame, reserve: float) -> pd.DataFrame:
    """Enforce the budget: scale predicted raw shares so each team's modeled players sum to
    ``1 − reserve`` (the rest is the rookie/unmodeled headroom).

    ``pred`` is ``[PLAYER_ID, team, share_pred]``; returns it with ``share_norm`` added.
    Callers should also inspect the *pre*-normalization team sums (the Step-6 sanity print):
    a mean far from ``1 − reserve`` means the raw share model is mis-calibrated — investigate
    before trusting any A/B built on top.
    """
    out = pred.copy()
    team_sum = out.groupby("team")["share_pred"].transform("sum").replace(0, np.nan)
    out["share_norm"] = (out["share_pred"] * (1.0 - reserve) / team_sum).fillna(0.0)
    return out
