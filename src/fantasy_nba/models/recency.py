"""Within-season recency features — last-N-games form (ROADMAP Stage 7.D / EXP-008b).

The model projects off **season totals**, which bury a role that emerged late: a player who
averaged 24 MPG across a season but 34 MPG over his last 20 games is walking into next season as
a ~34-MPG player, and the season average mean-reverts him down. EXP-008 tried to catch this with
*season-to-season* slopes and failed (too noisy, redundant). This is the signal it should have
used: **within the player's most recent season, how does his last-N-game form differ from his
full-season average** — the emerging-role / late-surge (and post-trade) signal that lives only at
game-log granularity.

Features per player, from the last ``window`` games of his **most recent prior season**:
  * ``recent_mpg``        — minutes over the window (the level he's trending toward).
  * ``recent_mpg_delta``  — ``recent_mpg − season_mpg``. The core signal: minutes rising (+) or
    fading (−) late. This is exactly what a full-season average erases.
  * ``recent_ppm_delta``  — recent points-per-minute minus season points-per-minute (production
    trend, using PTS as a scoring-agnostic density proxy).
  * ``recent_games``      — window size actually available (< ``window`` if he missed time).

No-leakage: only game logs from seasons **strictly before** the target are used; the last-N games
of a prior season are fully known before the target season starts. The heavy per-(player, season)
aggregation is computed **once** (``season_recency_table``) and sliced per fold, so refitting many
folds stays cheap.

**Known simplification:** "recent" = last N games of the latest season; a dedicated *post-trade*
split (games since the last ``TEAM_ABBREVIATION`` change) is a natural refinement but the last-N
window already captures a recent trade if it happened late. Documented in EXPERIMENTS.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._core import _season_start

RECENCY_FEATURES = ["recent_mpg", "recent_mpg_delta", "recent_ppm_delta", "recent_games"]

DEFAULT_WINDOW = 20


def season_recency_table(game_logs: pd.DataFrame, window: int = DEFAULT_WINDOW) -> pd.DataFrame:
    """Per (player, season) full-season and last-``window``-game aggregates (computed once).

    Only games actually played (``MIN > 0``) count. ``GAME_DATE`` is ISO ``YYYY-MM-DD`` so a plain
    string sort is chronological.
    """
    gl = game_logs[game_logs["MIN"] > 0].copy()
    gl["yr"] = gl["SEASON"].map(_season_start)
    gl = gl.sort_values(["PLAYER_ID", "yr", "GAME_DATE"])

    grp = gl.groupby(["PLAYER_ID", "yr"])
    season = grp.agg(s_min=("MIN", "sum"), s_g=("MIN", "size"), s_pts=("PTS", "sum"))
    tail = grp.tail(window).groupby(["PLAYER_ID", "yr"])
    win = tail.agg(w_min=("MIN", "sum"), w_g=("MIN", "size"), w_pts=("PTS", "sum"))

    t = season.join(win).reset_index()
    t["season_mpg"] = t["s_min"] / t["s_g"]
    t["season_ppm"] = t["s_pts"] / t["s_min"]
    t["recent_mpg"] = t["w_min"] / t["w_g"]
    t["recent_ppm"] = t["w_pts"] / t["w_min"]
    t["recent_games"] = t["w_g"]
    return t


def recency_features(table: pd.DataFrame, target_season: str) -> pd.DataFrame:
    """Last-season recency features for ``target_season`` from the precomputed ``table``.

    Picks each player's **most recent season strictly before** the target and returns the
    ``RECENCY_FEATURES``. Players with no prior game logs are simply absent (callers fill neutral).
    """
    ty = _season_start(target_season)
    prior = table[table["yr"] < ty]
    if prior.empty:
        return pd.DataFrame(columns=["PLAYER_ID"] + RECENCY_FEATURES)

    latest = prior.loc[prior.groupby("PLAYER_ID")["yr"].idxmax()].copy()
    latest["recent_mpg_delta"] = latest["recent_mpg"] - latest["season_mpg"]
    latest["recent_ppm_delta"] = (
        (latest["recent_ppm"] - latest["season_ppm"]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    )
    return latest[["PLAYER_ID"] + RECENCY_FEATURES].reset_index(drop=True)
