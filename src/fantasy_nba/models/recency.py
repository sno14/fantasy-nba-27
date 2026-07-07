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

**EXP-012 de-confound (Step 4 of docs/implementation-plan.md):** the raw last-N window at
season's end is contaminated by rest / load-management / tanking (the EXP-008b ledger note) —
it biases ``recent_mpg_delta`` downward. Two remedies live here:

* ``skip_last`` — drop each player-season's final ``skip_last`` *played* games before taking
  the window, so the window ends before the rest-contaminated stretch.
* ``trade_split_table`` — an explicit post-trade split (games since the last
  ``TEAM_ABBREVIATION`` change): a cleaner role-change signal than raw last-N, because a
  traded player's new-team minutes are a *fact about his new role*, not late-season noise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._core import _season_start

RECENCY_FEATURES = ["recent_mpg", "recent_mpg_delta", "recent_ppm_delta", "recent_games"]
# Post-trade split features (EXP-012). post_trade_mpg_delta is 0.0 when the post-trade sample
# is < MIN_POST_TRADE_GAMES (too noisy to trust) or the player wasn't traded.
TRADE_FEATURES = ["traded_flag", "post_trade_games", "post_trade_mpg_delta"]

DEFAULT_WINDOW = 20
MIN_POST_TRADE_GAMES = 5


def season_recency_table(
    game_logs: pd.DataFrame, window: int = DEFAULT_WINDOW, skip_last: int = 0
) -> pd.DataFrame:
    """Per (player, season) full-season and last-``window``-game aggregates (computed once).

    Only games actually played (``MIN > 0``) count. ``GAME_DATE`` is ISO ``YYYY-MM-DD`` so a plain
    string sort is chronological. ``skip_last`` drops each player-season's final ``skip_last``
    played games before taking the window (rest/tanking de-confound, EXP-012); the full-season
    aggregates are always computed on all played games.
    """
    gl = game_logs[game_logs["MIN"] > 0].copy()
    gl["yr"] = gl["SEASON"].map(_season_start)
    gl = gl.sort_values(["PLAYER_ID", "yr", "GAME_DATE"])

    grp = gl.groupby(["PLAYER_ID", "yr"])
    season = grp.agg(s_min=("MIN", "sum"), s_g=("MIN", "size"), s_pts=("PTS", "sum"))
    trimmed = grp.head(-skip_last) if skip_last > 0 else gl
    tail = trimmed.groupby(["PLAYER_ID", "yr"]).tail(window).groupby(["PLAYER_ID", "yr"])
    win = tail.agg(w_min=("MIN", "sum"), w_g=("MIN", "size"), w_pts=("PTS", "sum"))

    t = season.join(win).reset_index()
    t["season_mpg"] = t["s_min"] / t["s_g"]
    t["season_ppm"] = t["s_pts"] / t["s_min"]
    t["recent_mpg"] = t["w_min"] / t["w_g"]
    t["recent_ppm"] = t["w_pts"] / t["w_min"]
    t["recent_games"] = t["w_g"]
    return t


def trade_split_table(game_logs: pd.DataFrame) -> pd.DataFrame:
    """Per (player, season) post-trade split (computed once, sliced per fold like the recency table).

    Requires a ``TEAM_ABBREVIATION`` column on the game logs. For each player-season:
      * ``traded_flag``          — 1 if the player logged games for more than one team.
      * ``post_trade_games``     — played games in the trailing run with the *final* team
                                   (0 when never traded).
      * ``post_trade_mpg_delta`` — mean MIN with the final team minus mean MIN before the last
                                   change; 0.0 when not traded or when the post-trade sample is
                                   < ``MIN_POST_TRADE_GAMES`` (too small to read a role from).
    """
    if "TEAM_ABBREVIATION" not in game_logs.columns:
        raise ValueError("trade_split_table needs TEAM_ABBREVIATION on the game logs.")
    gl = game_logs[game_logs["MIN"] > 0].copy()
    gl["yr"] = gl["SEASON"].map(_season_start)
    gl = gl.sort_values(["PLAYER_ID", "yr", "GAME_DATE"])

    def _split(g: pd.DataFrame) -> pd.Series:
        teams = g["TEAM_ABBREVIATION"].to_numpy()
        traded = int((teams != teams[-1]).any())
        if not traded:
            return pd.Series({"traded_flag": 0, "post_trade_games": 0, "post_trade_mpg_delta": 0.0})
        # Trailing run of the final team = the post-trade block.
        cut = len(teams) - 1
        while cut > 0 and teams[cut - 1] == teams[-1]:
            cut -= 1
        post, pre = g.iloc[cut:], g.iloc[:cut]
        delta = 0.0
        if len(post) >= MIN_POST_TRADE_GAMES and len(pre) > 0:
            delta = float(post["MIN"].mean() - pre["MIN"].mean())
        return pd.Series({
            "traded_flag": 1, "post_trade_games": int(len(post)), "post_trade_mpg_delta": delta,
        })

    out = gl.groupby(["PLAYER_ID", "yr"]).apply(_split, include_groups=False).reset_index()
    for col, typ in (("traded_flag", int), ("post_trade_games", int)):
        out[col] = out[col].astype(typ)
    return out


def recency_features(
    table: pd.DataFrame, target_season: str, trade_table: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Last-season recency features for ``target_season`` from the precomputed ``table``.

    Picks each player's **most recent season strictly before** the target and returns the
    ``RECENCY_FEATURES``. Players with no prior game logs are simply absent (callers fill neutral).
    When ``trade_table`` (from :func:`trade_split_table`) is given, the ``TRADE_FEATURES`` for the
    same most-recent prior season are joined on (players untraded that season get 0/0/0.0).
    """
    ty = _season_start(target_season)
    prior = table[table["yr"] < ty]
    cols = RECENCY_FEATURES + (TRADE_FEATURES if trade_table is not None else [])
    if prior.empty:
        return pd.DataFrame(columns=["PLAYER_ID"] + cols)

    latest = prior.loc[prior.groupby("PLAYER_ID")["yr"].idxmax()].copy()
    latest["recent_mpg_delta"] = latest["recent_mpg"] - latest["season_mpg"]
    latest["recent_ppm_delta"] = (
        (latest["recent_ppm"] - latest["season_ppm"]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    )
    if trade_table is not None:
        latest = latest.merge(trade_table, on=["PLAYER_ID", "yr"], how="left")
        latest["traded_flag"] = latest["traded_flag"].fillna(0).astype(int)
        latest["post_trade_games"] = latest["post_trade_games"].fillna(0).astype(int)
        latest["post_trade_mpg_delta"] = latest["post_trade_mpg_delta"].fillna(0.0)
    return latest[["PLAYER_ID"] + cols].reset_index(drop=True)
