"""Season schedule pull + weekly-value derivations (Step D1.3).

Fetches the league schedule (nba_api ``ScheduleLeagueV2`` — the cdn.nba.com static JSON
403s plain requests) → ``data/raw/schedule_<season>.parquet`` with one row per game:
``season, game_date, week, week_name, home, away`` (regular season = week >= 1; the feed's
week 0 is preseason).

Derived and printed (the D1.3/D1.4 inputs):
* per-team games per NBA week (weekly-H2H matchup value),
* back-to-back counts per team,
* game counts in the league's fantasy-playoff weeks (``league.yaml``; the current
  ``fantasy_playoff_weeks`` is a placeholder until ESPN's matchup calendar is published),
* the ``league_end_offset_weeks`` cut date (D1.3b: ROS horizons stop there, not at the
  NBA finale).

**Vintage:** the endpoint serves the most recent published schedule. The 2026-27 schedule
is typically published mid-August — until then this pull returns 2025-26 and says so.
Re-run in August; the parquet is season-stamped so nothing is overwritten.

Example
-------
    python scripts/pull_schedule.py --expect 2026-27
"""

from __future__ import annotations

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

from fantasy_nba.data import storage
from fantasy_nba.models.value import load_league

REQUEST_TIMEOUT = 60


# Anything matching these is not a regular-season standings game. The Emirates NBA Cup
# *is* regular season except its Championship game (gameSubLabel).
_NON_REGULAR = ("Preseason", "All-Star", "Rising Stars", "Play-In", "First Round",
                "Semifinals", "Conf. Finals", "NBA Finals")


def fetch_schedule() -> pd.DataFrame:
    from nba_api.stats.endpoints import scheduleleaguev2

    raw = scheduleleaguev2.ScheduleLeagueV2(timeout=REQUEST_TIMEOUT).get_data_frames()[0]
    label = raw["gameLabel"].fillna("")
    sub = raw["gameSubLabel"].fillna("")
    regular = (
        ~label.str.contains("|".join(_NON_REGULAR), regex=True)
        & ~(label.str.contains("Cup") & (sub == "Championship"))
        & (pd.to_numeric(raw["weekNumber"], errors="coerce").fillna(0) >= 1)
    )
    df = pd.DataFrame({
        "season": raw["seasonYear"],
        "game_date": pd.to_datetime(raw["gameDateEst"].str[:10]),
        "week": pd.to_numeric(raw["weekNumber"], errors="coerce").fillna(0).astype(int),
        "week_name": raw["weekName"],
        "label": label,
        "home": raw["homeTeam_teamTricode"],
        "away": raw["awayTeam_teamTricode"],
        "regular_season": regular,
    })
    return df


def _per_team_long(reg: pd.DataFrame) -> pd.DataFrame:
    home = reg[["game_date", "week", "home"]].rename(columns={"home": "team"})
    away = reg[["game_date", "week", "away"]].rename(columns={"away": "team"})
    return pd.concat([home, away], ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull the NBA schedule + weekly derivations.")
    parser.add_argument("--expect", default="2026-27",
                        help="Season you want; a mismatch prints the vintage warning.")
    args = parser.parse_args()

    df = fetch_schedule()
    season = df["season"].iloc[0]
    reg = df[df["regular_season"]]
    path = storage.write(df, f"schedule_{season}")
    print(f"[schedule] {season}: {len(df):,} games ({len(reg):,} regular season) -> {path}")
    if season != args.expect:
        print(f"[schedule] VINTAGE WARNING: wanted {args.expect}, the feed serves {season} — "
              "the next season's schedule is typically published mid-August; re-run then.")

    long = _per_team_long(reg)
    per_week = long.groupby(["team", "week"]).size().unstack(fill_value=0)
    print(f"\n=== Games per team per week ({season}; weeks {per_week.columns.min()}–"
          f"{per_week.columns.max()}) — distribution ===")
    counts = per_week.stack()
    print(counts.value_counts().sort_index().rename("team-weeks").to_string())

    b2b = (
        long.sort_values(["team", "game_date"])
        .groupby("team")["game_date"]
        .apply(lambda s: int((s.diff().dt.days == 1).sum()))
        .sort_values(ascending=False)
    )
    print(f"\n=== Back-to-backs per team ===\nmax {b2b.iloc[0]} ({b2b.index[0]}), "
          f"min {b2b.iloc[-1]} ({b2b.index[-1]}), median {b2b.median():.0f}")

    league = load_league()
    pw = league.get("fantasy_playoff_weeks") or []
    in_pw = long[long["week"].isin(pw)]
    if not in_pw.empty:
        tbl = in_pw.groupby("team").size().sort_values()
        print(f"\n=== Games in fantasy-playoff weeks {pw} (league.yaml placeholder until the "
              f"ESPN calendar is published) ===")
        print(f"min {tbl.iloc[0]} ({tbl.index[0]}), max {tbl.iloc[-1]} ({tbl.index[-1]})")

    offset = int(league.get("league_end_offset_weeks") or 0)
    finale = reg["game_date"].max()
    cut = finale - pd.Timedelta(weeks=offset)
    print(f"\n[horizon] NBA finale {finale.date()} — league_end_offset_weeks={offset} ⇒ "
          f"ROS horizons cut at ~{cut.date()} (D1.3b; concrete once the ESPN calendar lands).")


if __name__ == "__main__":
    main()
