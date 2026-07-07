"""Team-context / vacated-minutes features (ROADMAP Stage 7.A / EXP-009).

The model so far projects each player almost entirely from his *own* history — structurally blind
to the **opportunity a player walks into**. The consensus #1 riser/faller mechanism is roster
turnover: when a teammate departs, his minutes and usage are **vacated** and redistributed to
those who remain; when a high-usage player arrives, returning players get **compressed**. This
module builds that team-context signal so the learned model (EXP-009 variant) can use it.

Computed per (player, target-season) from **prior-season minutes** + the **target-season team
assignment** (a preseason-known roster fact, not an outcome), so it is no-leakage:

  * ``team_vacated_min_norm``   — minutes on the player's target team vacated by players who did
    **not** return (left the team / league), as a fraction of an average team-season's minutes.
    High ⇒ opportunity opened up. The core riser signal.
  * ``team_returning_min_norm`` — minutes retained by returning players (the competition still there).
  * ``team_turnover_share``     — vacated / (vacated + returning): fraction of last year's rotation
    minutes that turned over. Season-length-robust by construction.
  * ``own_prev_min_share``      — the player's own share of his prior team's minutes (how big a role
    he's coming from — a newcomer with a big prior role competes harder for the vacated minutes).

Minutes are normalized by the prior season's league-average team minutes so shortened seasons
(2019-20, 2020-21) stay comparable.

**Known simplification:** team membership comes from ``player_season_stats`` (one row per
player-season, traded players attributed to their *last* team), so mid-season trades are
approximated and a player's target-season team is his actual season team, not a strict
preseason roster. A stricter version uses preseason rosters / transactions (the
prosportstransactions follow-up, EXP-009b). Documented in EXPERIMENTS.md.
"""

from __future__ import annotations

import pandas as pd

from ._core import _season_start

CONTEXT_FEATURES = [
    "team_vacated_min_norm",
    "team_returning_min_norm",
    "team_turnover_share",
    "own_prev_min_share",
]


def season_before(season: str) -> str:
    """'2024-25' -> '2023-24'."""
    start = _season_start(season) - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _primary_team_minutes(season_stats: pd.DataFrame, season: str) -> pd.DataFrame:
    """One row per player for ``season``: primary (last) team + minutes played."""
    s = season_stats[season_stats["SEASON"] == season]
    return (
        s.groupby("PLAYER_ID", as_index=False)
        .agg(team=("TEAM_ABBREVIATION", "last"), min=("MIN", "sum"))
    )


def team_context_features(
    prior_stats: pd.DataFrame,
    target_team_map: pd.DataFrame,
    prev_season: str,
) -> pd.DataFrame:
    """Vacated/returning team-minute features for the players in ``target_team_map``.

    ``prior_stats`` must contain ``prev_season`` (the season whose minutes are being reallocated).
    ``target_team_map`` is ``[PLAYER_ID, team]`` — each player's target-season team (from season
    stats in a backtest, or from rosters live). Returns ``[PLAYER_ID, *CONTEXT_FEATURES]``.
    """
    prev = _primary_team_minutes(prior_stats, prev_season)  # PLAYER_ID, team, min
    tgt = target_team_map.rename(columns={"team": "target_team"})[["PLAYER_ID", "target_team"]]

    league_team_min = prev["min"].sum() / max(prev["team"].nunique(), 1)  # avg team-season minutes

    # A prior-team player "returns" if his target team equals his prior team.
    prev = prev.merge(tgt, on="PLAYER_ID", how="left")
    prev["returning"] = prev["target_team"] == prev["team"]

    grp = prev.groupby("team")
    team_ctx = pd.DataFrame({
        "vacated_min": grp.apply(lambda g: g.loc[~g["returning"], "min"].sum(), include_groups=False),
        "returning_min": grp.apply(lambda g: g.loc[g["returning"], "min"].sum(), include_groups=False),
        "total_min": grp["min"].sum(),
    }).reset_index()
    denom = (team_ctx["vacated_min"] + team_ctx["returning_min"]).replace(0, pd.NA)
    team_ctx["team_turnover_share"] = (team_ctx["vacated_min"] / denom).fillna(0.0)
    team_ctx["team_vacated_min_norm"] = team_ctx["vacated_min"] / league_team_min
    team_ctx["team_returning_min_norm"] = team_ctx["returning_min"] / league_team_min

    # Each player's own prior-team minute share (role size he's coming from).
    prev = prev.merge(team_ctx[["team", "total_min"]], on="team", how="left")
    prev["own_prev_min_share"] = (prev["min"] / prev["total_min"]).fillna(0.0)

    out = tgt.merge(
        team_ctx[["team", "team_vacated_min_norm", "team_returning_min_norm", "team_turnover_share"]]
        .rename(columns={"team": "target_team"}),
        on="target_team", how="left",
    )
    out = out.merge(prev[["PLAYER_ID", "own_prev_min_share"]], on="PLAYER_ID", how="left")
    # Newcomers with no prior season, or teams with no prior roster (expansion), get neutral 0.
    for col in CONTEXT_FEATURES:
        out[col] = out[col].fillna(0.0)
    return out[["PLAYER_ID"] + CONTEXT_FEATURES]


def target_team_map(season_stats: pd.DataFrame, target_season: str) -> pd.DataFrame:
    """``[PLAYER_ID, team]`` for the target season — the preseason-known roster fact the context
    features key on. Extracted from season stats (backtest) or rosters (live), carrying no outcomes."""
    return _primary_team_minutes(season_stats, target_season)[["PLAYER_ID", "team"]]


def context_for_season(season_stats: pd.DataFrame, target_season: str) -> pd.DataFrame:
    """Convenience: build target-season context features when ``season_stats`` contains the target.

    Used by the training panel (each historical season is present) and to derive the inference-time
    team map. Requires both ``target_season`` and the season before it to be present.
    """
    prev_season = season_before(target_season)
    target_team_map = _primary_team_minutes(season_stats, target_season)[["PLAYER_ID", "team"]]
    return team_context_features(season_stats, target_team_map, prev_season)
