"""Fetch NBA data from stats.nba.com via ``nba_api``.

Pulls the raw ingredients the projection pipeline needs:

* **player_season_stats** — per-season Base totals + Advanced metrics (usage, pace, minutes)
* **player_game_logs**    — one row per player per game (for game-by-game work later)
* **team_rosters**        — current roster per team (depth-chart / minutes context)

stats.nba.com is rate-limited and occasionally flaky, so every call goes through a small
retry+delay wrapper. Data is cached to Parquet via :mod:`fantasy_nba.data.storage`; pass
``refresh=False`` to reuse an existing cache.
"""

from __future__ import annotations

import time
from typing import Callable, Sequence

import pandas as pd

from . import storage

# Politeness / robustness knobs for stats.nba.com.
REQUEST_TIMEOUT = 60
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 2.0  # seconds, multiplied by attempt number
THROTTLE = 0.6  # seconds between successive requests

SEASON_TYPE = "Regular Season"


def _with_retry(fn: Callable[[], pd.DataFrame], label: str) -> pd.DataFrame:
    """Call ``fn`` with retries + exponential-ish backoff; raise on final failure."""
    last_err: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            df = fn()
            time.sleep(THROTTLE)
            return df
        except Exception as err:  # nba_api raises requests/JSON errors of varied types
            last_err = err
            wait = RETRY_BACKOFF * attempt
            print(f"  [{label}] attempt {attempt}/{RETRY_ATTEMPTS} failed: {err} — retrying in {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {label} after {RETRY_ATTEMPTS} attempts") from last_err


# --- Individual fetchers ---------------------------------------------------------------


def fetch_player_season_stats(season: str) -> pd.DataFrame:
    """Per-player season stats for one season: Base totals joined with Advanced metrics.

    ``season`` is in nba_api form, e.g. ``"2024-25"``.
    """
    from nba_api.stats.endpoints import leaguedashplayerstats

    def _base() -> pd.DataFrame:
        return leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            season_type_all_star=SEASON_TYPE,
            measure_type_detailed_defense="Base",
            per_mode_detailed="Totals",
            timeout=REQUEST_TIMEOUT,
        ).get_data_frames()[0]

    def _adv() -> pd.DataFrame:
        return leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            season_type_all_star=SEASON_TYPE,
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="Totals",
            timeout=REQUEST_TIMEOUT,
        ).get_data_frames()[0]

    base = _with_retry(_base, f"season_stats base {season}")
    adv = _with_retry(_adv, f"season_stats advanced {season}")

    # Advanced-only columns (usage, pace, ratings, etc.) to merge onto Base.
    adv_only = [c for c in adv.columns if c not in base.columns] + ["PLAYER_ID"]
    merged = base.merge(adv[adv_only], on="PLAYER_ID", how="left")
    merged.insert(0, "SEASON", season)
    return merged


def fetch_player_game_logs(season: str) -> pd.DataFrame:
    """One row per player per game for a season (basic box score)."""
    from nba_api.stats.endpoints import leaguegamelog

    def _logs() -> pd.DataFrame:
        return leaguegamelog.LeagueGameLog(
            season=season,
            season_type_all_star=SEASON_TYPE,
            player_or_team_abbreviation="P",
            timeout=REQUEST_TIMEOUT,
        ).get_data_frames()[0]

    df = _with_retry(_logs, f"game_logs {season}")
    df.insert(0, "SEASON", season)
    return df


def fetch_team_rosters(season: str) -> pd.DataFrame:
    """Current roster for every team in a season, stacked into one DataFrame."""
    from nba_api.stats.endpoints import commonteamroster
    from nba_api.stats.static import teams as static_teams

    frames: list[pd.DataFrame] = []
    for team in static_teams.get_teams():
        team_id = team["id"]

        def _roster(_tid: int = team_id) -> pd.DataFrame:
            return commonteamroster.CommonTeamRoster(
                team_id=_tid,
                season=season,
                timeout=REQUEST_TIMEOUT,
            ).get_data_frames()[0]

        df = _with_retry(_roster, f"roster {team['abbreviation']} {season}")
        frames.append(df)

    out = pd.concat(frames, ignore_index=True)
    # CommonTeamRoster already returns its own SEASON column (year form, e.g. "2025"); drop it
    # and stamp our canonical "2025-26" form so it joins with the rest of the pipeline.
    out = out.drop(columns=[c for c in out.columns if c.upper() == "SEASON"])
    out.insert(0, "SEASON", season)
    return out


def fetch_player_bio(season: str) -> pd.DataFrame:
    """Per-player bio for a season: age, height, weight, draft info.

    One league-wide call per season. AGE is the player's age during that season, which is
    what the projection's aging curve needs.
    """
    from nba_api.stats.endpoints import leaguedashplayerbiostats

    def _bio() -> pd.DataFrame:
        return leaguedashplayerbiostats.LeagueDashPlayerBioStats(
            season=season,
            season_type_all_star=SEASON_TYPE,
            per_mode_simple="Totals",
            timeout=REQUEST_TIMEOUT,
        ).get_data_frames()[0]

    df = _with_retry(_bio, f"player_bio {season}")
    df.insert(0, "SEASON", season)
    return df


# --- Orchestration ---------------------------------------------------------------------

_DATASETS = {
    "player_season_stats": fetch_player_season_stats,
    "player_game_logs": fetch_player_game_logs,
    "team_rosters": fetch_team_rosters,
    "player_bio": fetch_player_bio,
}


def pull_seasons(
    seasons: Sequence[str],
    datasets: Sequence[str] = ("player_season_stats", "player_game_logs"),
    refresh: bool = True,
) -> dict[str, pd.DataFrame]:
    """Fetch the requested datasets across seasons, concatenate, and cache to Parquet.

    Rosters are current-only (not seasonal history), so ``team_rosters`` ignores the
    ``seasons`` list beyond using the most recent one for the API call.

    Returns a mapping of dataset name -> combined DataFrame.
    """
    unknown = set(datasets) - set(_DATASETS)
    if unknown:
        raise ValueError(f"Unknown datasets: {sorted(unknown)}. Valid: {sorted(_DATASETS)}")

    results: dict[str, pd.DataFrame] = {}
    for name in datasets:
        if not refresh and storage.exists(name):
            print(f"[{name}] cache hit — skipping fetch")
            results[name] = storage.read(name)
            continue

        if name == "team_rosters":
            print(f"[{name}] fetching current rosters …")
            combined = _DATASETS[name](seasons[-1])
        else:
            frames = []
            for season in seasons:
                print(f"[{name}] fetching {season} …")
                frames.append(_DATASETS[name](season))
            combined = pd.concat(frames, ignore_index=True)

        path = storage.write(combined, name)
        print(f"[{name}] cached {len(combined):,} rows -> {path}")
        results[name] = combined

    return results
