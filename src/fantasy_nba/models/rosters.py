"""Honest preseason roster maps from dated transactions (Step 8 / EXP-016, ROADMAP 7.A).

``context.target_team_map`` — the team map every backtest consumer has used so far — reads the
target season's stats, i.e. each player's **last** team of the season being predicted. That
flatters mid-season movers (the model "knows" February trades in October). This module replaces
it with what was actually knowable on draft day:

    prior-season primary team  +  player-movement transactions dated ≤ Oct 1 of the target season

Transactions come from the shared prosportstransactions scraper
(``scripts/pull_injuries.py --dataset transactions`` → ``data/raw/transactions.parquet``,
verbatim ``date, team, acquired, relinquished, notes`` rows). Name→PLAYER_ID resolution reuses
the Step-7 hardening (``injuries.resolve_players``: normalized names, team+season and
career-span disambiguation, dated aliases, hard-fail on new collisions).

Covid quirk: the 2019-20 season ended in the October-2020 bubble and 2020-21 free agency ran
in late November — an ``as_of_month_day="10-01"`` map for target 2020-21 is still no-leakage
but is effectively "prior teams, no offseason": pass a later ``as_of_month_day`` for that one
target if the offseason signal matters to the consumer.
"""

from __future__ import annotations

import pandas as pd

from ._core import _season_start
from .context import _primary_team_minutes, season_before
from .injuries import resolve_players

# PST team nickname -> TEAM_ABBREVIATION, era-resolved by transaction date where a nickname
# changed cities since 2009 (Hornets: New Orleans -> Charlotte 2014; Nets: NJN -> BKN 2012).
_STATIC_NICKNAMES = {
    "76ers": "PHI", "Blazers": "POR", "Trail Blazers": "POR", "Bucks": "MIL", "Bulls": "CHI",
    "Cavaliers": "CLE", "Celtics": "BOS", "Clippers": "LAC", "Grizzlies": "MEM", "Hawks": "ATL",
    "Heat": "MIA", "Jazz": "UTA", "Kings": "SAC", "Knicks": "NYK", "Lakers": "LAL",
    "Magic": "ORL", "Mavericks": "DAL", "Nuggets": "DEN", "Pacers": "IND", "Pelicans": "NOP",
    "Pistons": "DET", "Raptors": "TOR", "Rockets": "HOU", "Spurs": "SAS", "Suns": "PHX",
    "Thunder": "OKC", "Timberwolves": "MIN", "Warriors": "GSW", "Wizards": "WAS",
    "Bobcats": "CHA",
}


def team_abbreviation(nickname: str, date: pd.Timestamp) -> str | None:
    """PST nickname -> our TEAM_ABBREVIATION (era-resolved); None for unknown/defunct."""
    nickname = str(nickname).strip()
    if nickname == "Hornets":
        return "NOH" if date < pd.Timestamp("2013-08-01") else "CHA"
    if nickname == "Nets":
        return "NJN" if date < pd.Timestamp("2012-07-01") else "BKN"
    return _STATIC_NICKNAMES.get(nickname)


# The prior season's stats already encode every in-season move (primary team = last team of
# that season); the map only needs transactions the stats can't see — from just after the
# regular season (draft-night trades start late June; a small April buffer catches nothing
# but costs nothing) through the preseason cutoff.
OFFSEASON_FROM_MONTH_DAY = "04-20"


def preseason_roster_map(
    season_stats: pd.DataFrame,
    transactions: pd.DataFrame,
    target_season: str,
    as_of_month_day: str = "10-01",
) -> pd.DataFrame:
    """``[PLAYER_ID, team]`` as knowable on ``as_of_month_day`` of the target season.

    Prior-season primary team, then player-movement transactions dated in
    ``(Apr 20 of the target year, the cutoff]`` applied chronologically: an *acquired* row
    puts the player on that team; a *relinquished* row (waive/release/trade-out) clears him
    if he was on it. Players left teamless (unsigned free agents) drop out of the map —
    honest: on draft day they had no team. The honest replacement for
    ``context.target_team_map`` in backtests (Step 8.3 re-runs its consumers).

    **Missed-season carry-forward (2026-08-02).** The seed is keyed on minutes *played*, so a
    player who missed the ENTIRE prior season through injury had no row and silently vanished
    from every team — not because he was a free agent but because he never checked in. That is
    a data artifact, not a fact: Kyrie Irving (0 gp 2025-26, ACL) was under contract with Dallas
    the whole time, as were Tyrese Haliburton and Damian Lillard with their teams. So a player
    absent from the prior season is seeded from the season **before** it instead. The lookback
    is deliberately ONE season: a two-season gap is a player who is realistically out of the
    league, and carrying those forward would resurrect retirees onto rosters. Leakage-safe by
    construction (an older season is strictly less information than the prior one), and the
    transaction pass still runs on top — so a carried player who did leave in free agency is
    cleared by his own ``relinquished`` row exactly as before.
    """
    ty = _season_start(target_season)
    lo = pd.Timestamp(f"{ty}-{OFFSEASON_FROM_MONTH_DAY}")
    hi = pd.Timestamp(f"{ty}-{as_of_month_day}")

    prev_season = season_before(target_season)
    base = _primary_team_minutes(season_stats, prev_season)
    team_of: dict[int, str | None] = dict(zip(base["PLAYER_ID"], base["team"]))

    carried = _primary_team_minutes(season_stats, season_before(prev_season))
    for pid, team in zip(carried["PLAYER_ID"], carried["team"]):
        team_of.setdefault(pid, team)

    tx = transactions.copy()
    tx["date"] = pd.to_datetime(tx["date"])
    tx = tx[(tx["date"] > lo) & (tx["date"] <= hi)]
    if not tx.empty:
        from .injuries import explode_events

        events = explode_events(tx)
        # Prior-only stats keep resolution leakage-safe in spirit; identity resolution itself
        # may use the full frame (a player's name/id mapping is not an outcome).
        resolved, _ = resolve_players(events, season_stats, strict=False)
        resolved = resolved.sort_values("date")
        for r in resolved.itertuples(index=False):
            abbr = team_abbreviation(r.team, r.date)
            if abbr is None:
                continue
            pid = int(r.PLAYER_ID)
            if r.direction == "in":       # signed / traded in / claimed
                team_of[pid] = abbr
            elif team_of.get(pid) == abbr:  # waived / released / traded out
                team_of[pid] = None

    rows = [(pid, t) for pid, t in team_of.items() if t is not None]
    return pd.DataFrame(rows, columns=["PLAYER_ID", "team"])


def vacated_feature_table(
    season_stats: pd.DataFrame,
    transactions: pd.DataFrame,
    team_rosters: pd.DataFrame,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """EXP-016b: ``[SEASON, PLAYER_ID, *VACATED_FEATURES]`` over every season with a predecessor.

    Each season's row block uses the **honest Oct-1 map** (this module) + prior-season stats +
    as-of positions (``allocation.pos_group_asof``) — leakage-safe per block regardless of the
    backtest fold, so the table is computed once and sliced per season (the
    ``season_recency_table`` pattern). ``seasons`` defaults to every cached season after the
    first; a target season absent from ``season_stats`` (live use) works too — only its prior
    season's stats and its transactions are read.
    """
    from .allocation import pos_group_asof
    from .context import vacated_features

    from .allocation import position_table

    if seasons is None:
        all_s = sorted(season_stats["SEASON"].unique(), key=_season_start)
        seasons = all_s[1:]
    pos_table = position_table(team_rosters)
    frames = []
    for s in seasons:
        prev = season_before(s)
        if prev not in set(season_stats["SEASON"]):
            continue
        team_map = preseason_roster_map(season_stats, transactions, s)
        pos_of = pos_group_asof(pos_table, s)
        f = vacated_features(season_stats, team_map, prev, pos_of)
        f.insert(0, "SEASON", s)
        frames.append(f)
    if not frames:
        raise ValueError("vacated_feature_table needs at least two consecutive seasons.")
    return pd.concat(frames, ignore_index=True)


def validate_roster_map(
    roster_map: pd.DataFrame,
    game_logs: pd.DataFrame,
    target_season: str,
    pool_ids: set[int] | None = None,
    min_first_games: int = 3,
) -> dict:
    """Step-8.2 validation: agreement with the team each player actually opened the season on.

    Ground truth = the team of a player's first ``min_first_games`` played games of the target
    season (majority team of that window). Restricted to ``pool_ids`` (the draftable pool) when
    given. Returns agreement stats + the disagreeing rows for inspection (mid-Oct trades are
    legitimate misses; name-join failures are not). Gate: >= 90% agreement on the pool.
    """
    gl = game_logs[(game_logs["SEASON"] == target_season) & (game_logs["MIN"] > 0)].copy()
    gl = gl.sort_values(["PLAYER_ID", "GAME_DATE"])
    first = gl.groupby("PLAYER_ID").head(min_first_games)
    opener = first.groupby("PLAYER_ID")["TEAM_ABBREVIATION"].agg(
        lambda s: s.mode().iloc[0]).rename("opening_team").reset_index()

    m = roster_map.merge(opener, on="PLAYER_ID", how="inner")
    if pool_ids is not None:
        m = m[m["PLAYER_ID"].isin(pool_ids)]
    m["agree"] = m["team"] == m["opening_team"]
    return {
        "season": target_season,
        "n": len(m),
        "agreement": float(m["agree"].mean()) if len(m) else float("nan"),
        "misses": m[~m["agree"]].reset_index(drop=True),
    }
