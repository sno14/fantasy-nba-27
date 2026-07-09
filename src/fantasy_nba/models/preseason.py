"""Preseason-October game-log features (Step 9c / EXP-027b, ROADMAP 7.B addendum).

The latest-arriving pre-draft signal: how the coach actually used players in October
exhibition games. **Role only, never rates** — preseason samples are 3-6 games, so minutes
and lineup usage carry signal while per-minute production is noise.

Source: the cached ``preseason_game_logs`` dataset (nba_api ``LeagueGameLog`` with
``season_type_all_star="Pre Season"``, 17 seasons). Two data quirks handled by the calendar
window below:
  * the 2019-20 frame contains the July/August-2020 bubble scrimmages/seeding warm-ups —
    excluded (they are not the *following* season's preseason and sit mid-frame);
  * 2020-21's preseason ran in December 2020 and 2011-12's (lockout) in mid-December 2011 —
    both inside the window.

Leakage note (the ledger's skeptic pass): preseason games of season S predate every regular-season
outcome of S. The cutpoint for these features is "day before the opener" — later than the
Oct-1 convention used for injuries/rosters, deliberately: the draft happens after preseason
ball, and this group exists to capture exactly that late information.

``ps_start_share`` is a **proxy**: ``LeagueGameLog`` carries no starter flag (that would need
~1,300 per-game boxscore pulls), so "started" = top-5 minutes on his team in that game.
"""

from __future__ import annotations

import pandas as pd

from ._core import _season_start
from .context import season_before

PRESEASON_FEATURES = [
    "ps_mpg",          # preseason minutes per game appeared
    "ps_mpg_delta",    # ps_mpg − prior-season regular-season MPG (NaN for no-prior players)
    "ps_start_share",  # share of his team's preseason games he "started" (top-5-MIN proxy)
]

# Preseason of season S = games in [Sep 1, Dec 31] of S's start year. Excludes the July-2020
# bubble rows in the 2019-20 frame; includes the Dec-2020 (covid) and Dec-2011 (lockout)
# preseasons.
WINDOW_FROM_MONTH_DAY = "09-01"
WINDOW_TO_MONTH_DAY = "12-31"


def preseason_feature_table(
    preseason_logs: pd.DataFrame,
    season_stats: pd.DataFrame,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """``[SEASON, PLAYER_ID, *PRESEASON_FEATURES]`` per season block.

    Fold-safe by construction: season S's block reads S's own **preseason** games (all dated
    before S's regular season) and S−1's regular-season MPG. Players with no preseason
    appearance get no rows — consumers keep them NaN (unknown role, *not* zero minutes;
    LightGBM handles NaN natively and the draft sheet shows a blank).
    """
    logs = preseason_logs.copy()
    logs["GAME_DATE"] = pd.to_datetime(logs["GAME_DATE"])

    if seasons is None:
        seasons = sorted(logs["SEASON"].unique(), key=_season_start)

    frames = []
    for s in seasons:
        ty = _season_start(s)
        lo = pd.Timestamp(f"{ty}-{WINDOW_FROM_MONTH_DAY}")
        hi = pd.Timestamp(f"{ty}-{WINDOW_TO_MONTH_DAY}")
        g = logs[(logs["SEASON"] == s) & logs["GAME_DATE"].between(lo, hi)]
        if g.empty:
            continue

        # Top-5 minutes within each (team, game) = the starter proxy.
        rk = g.groupby(["TEAM_ID", "GAME_ID"])["MIN"].rank(ascending=False, method="first")
        g = g.assign(started=(rk <= 5).astype(int))

        team_games = g.groupby("TEAM_ID")["GAME_ID"].nunique()
        # Primary preseason team = the one he appeared for most (trades during camp are rare).
        per_pt = g.groupby(["PLAYER_ID", "TEAM_ID"]).agg(
            g_appeared=("GAME_ID", "nunique"), min_sum=("MIN", "sum"), starts=("started", "sum")
        ).reset_index().sort_values(["PLAYER_ID", "g_appeared"])
        primary = per_pt.groupby("PLAYER_ID").tail(1)

        totals = per_pt.groupby("PLAYER_ID", as_index=False)[["g_appeared", "min_sum"]].sum()
        f = totals.merge(primary[["PLAYER_ID", "TEAM_ID", "starts"]], on="PLAYER_ID")
        f["ps_mpg"] = f["min_sum"] / f["g_appeared"]
        f["ps_start_share"] = f["starts"] / f["TEAM_ID"].map(team_games)

        prev = season_before(s)
        pm = season_stats[season_stats["SEASON"] == prev].groupby(
            "PLAYER_ID", as_index=False
        )[["MIN", "GP"]].sum()
        pm["prev_mpg"] = pm["MIN"] / pm["GP"].replace(0, pd.NA)
        f = f.merge(pm[["PLAYER_ID", "prev_mpg"]], on="PLAYER_ID", how="left")
        f["ps_mpg_delta"] = f["ps_mpg"] - pd.to_numeric(f["prev_mpg"], errors="coerce")

        f.insert(0, "SEASON", s)
        frames.append(f[["SEASON", "PLAYER_ID"] + PRESEASON_FEATURES])
    if not frames:
        raise ValueError("preseason_feature_table: no preseason games in the given seasons.")
    return pd.concat(frames, ignore_index=True)
