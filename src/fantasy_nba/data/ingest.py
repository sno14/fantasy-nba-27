"""Fetch NBA data from stats.nba.com via ``nba_api``.

Pulls the raw ingredients the projection pipeline needs:

* **player_season_stats** — per-season Base totals + Advanced metrics (usage, pace, minutes)
* **player_game_logs**    — one row per player per game (for game-by-game work later)
* **team_rosters**        — roster per team per season (positions for the depth-chart /
  allocation features; historical seasons supported — implementation-plan Step 6.1)

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


def fetch_preseason_game_logs(season: str) -> pd.DataFrame:
    """One row per player per **preseason** game (Step 9c / EXP-027: `ps_mpg`,
    `ps_start_share` — the latest-arriving pre-draft role signal). Covid quirk: the
    2019-20 frame also contains the July-2020 bubble scrimmages — consumers date-filter."""
    from nba_api.stats.endpoints import leaguegamelog

    def _logs() -> pd.DataFrame:
        return leaguegamelog.LeagueGameLog(
            season=season,
            season_type_all_star="Pre Season",
            player_or_team_abbreviation="P",
            timeout=REQUEST_TIMEOUT,
        ).get_data_frames()[0]

    df = _with_retry(_logs, f"preseason_game_logs {season}")
    df.insert(0, "SEASON", season)
    return df


def fetch_team_game_logs(season: str) -> pd.DataFrame:
    """One row per team per game (Step 10 amendment: game margins for blowout handling —
    margins are not derivable from the player logs)."""
    from nba_api.stats.endpoints import leaguegamelog

    def _logs() -> pd.DataFrame:
        return leaguegamelog.LeagueGameLog(
            season=season,
            season_type_all_star=SEASON_TYPE,
            player_or_team_abbreviation="T",
            timeout=REQUEST_TIMEOUT,
        ).get_data_frames()[0]

    df = _with_retry(_logs, f"team_game_logs {season}")
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


def fetch_draft_history() -> pd.DataFrame:
    """Full NBA draft history, one static pull (Step 9d / EXP-028).

    One row per drafted player: ``PERSON_ID, SEASON (draft year), ROUND_NUMBER,
    OVERALL_PICK, TEAM_ID, ORGANIZATION, …``. Season-independent — ``pull_seasons``
    special-cases it (fetched once, not per season). Undrafted players simply have no row;
    the rookie model maps them to the ``overall_pick = 61`` sentinel.
    """
    from nba_api.stats.endpoints import drafthistory

    def _draft() -> pd.DataFrame:
        return drafthistory.DraftHistory(timeout=REQUEST_TIMEOUT).get_data_frames()[0]

    return _with_retry(_draft, "draft_history")


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
    "preseason_game_logs": fetch_preseason_game_logs,
    "team_game_logs": fetch_team_game_logs,
    "team_rosters": fetch_team_rosters,
    "player_bio": fetch_player_bio,
}

# Season-independent datasets: fetched once per pull, not per season.
_STATIC_DATASETS = {
    "draft_history": fetch_draft_history,
}


def refresh_season(name: str, season: str) -> pd.DataFrame:
    """Re-fetch ONE season of a per-season dataset and replace it in the cache, keyed on
    SEASON — every other season's cached rows are preserved (the Step-12 nightly refresh;
    ``pull_seasons`` by contrast rewrites the file with only the seasons it was given).
    The endpoint returns the whole season, so this is simple and idempotent."""
    if name not in _DATASETS:
        raise ValueError(f"{name!r} is not a per-season dataset ({sorted(_DATASETS)}).")
    print(f"[{name}] refreshing {season} …")
    fresh = _DATASETS[name](season)
    if storage.exists(name):
        cached = storage.read(name)
        combined = pd.concat([cached[cached["SEASON"] != season], fresh], ignore_index=True)
    else:
        combined = fresh
    path = storage.write(combined, name)
    print(f"[{name}] {season}: {len(fresh):,} rows refreshed ({len(combined):,} total) -> {path}")
    return combined


def pull_seasons(
    seasons: Sequence[str],
    datasets: Sequence[str] = ("player_season_stats", "player_game_logs"),
    refresh: bool = True,
) -> dict[str, pd.DataFrame]:
    """Fetch the requested datasets across seasons, concatenate, and cache to Parquet.

    **Storage-discipline warning (Step 12):** this rewrites each dataset file with only
    the seasons requested — it is the bulk/backfill path. For a nightly single-season
    update use :func:`refresh_season`, which replaces in cache keyed on SEASON.

    Every dataset (including ``team_rosters`` — the endpoint accepts historical seasons;
    Step 6.1) is fetched per season and concatenated. A rosters pull is 30 requests per
    season, so a full-history refresh takes a few minutes under the throttle.

    Returns a mapping of dataset name -> combined DataFrame.
    """
    unknown = set(datasets) - set(_DATASETS) - set(_STATIC_DATASETS)
    if unknown:
        raise ValueError(f"Unknown datasets: {sorted(unknown)}. "
                         f"Valid: {sorted(_DATASETS) + sorted(_STATIC_DATASETS)}")

    results: dict[str, pd.DataFrame] = {}
    for name in datasets:
        if not refresh and storage.exists(name):
            print(f"[{name}] cache hit — skipping fetch")
            results[name] = storage.read(name)
            continue

        if name in _STATIC_DATASETS:
            print(f"[{name}] fetching (season-independent) …")
            combined = _STATIC_DATASETS[name]()
            path = storage.write(combined, name)
            print(f"[{name}] cached {len(combined):,} rows -> {path}")
            results[name] = combined
            continue

        frames = []
        for season in seasons:
            print(f"[{name}] fetching {season} …")
            frames.append(_DATASETS[name](season))
        combined = pd.concat(frames, ignore_index=True)

        path = storage.write(combined, name)
        print(f"[{name}] cached {len(combined):,} rows -> {path}")
        results[name] = combined

    return results
