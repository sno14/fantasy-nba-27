"""Marcel-style baseline projection.

The honest benchmark every fancier model must beat. Adapted from Tom Tango's "Marcel the
Monkey" method (the standard simple baseline in baseball) to NBA per-minute rates:

1. **Recency-weight** the last N seasons (default 3, weights 5/4/3), weighted by minutes.
2. **Regress** each per-minute rate toward the league mean; the fewer minutes a player has
   logged, the harder his rate is pulled toward average (small-sample skepticism).
3. **Age curve** applied to production rates (rough single curve, peak ~27).
4. **Project minutes & games** from recency-weighted playing time. This is deliberately
   crude — a proper depth-chart-aware minutes model is Stage 3.

Reconstructs a per-game stat line and scores it with the league config. Everything here is
intentionally simple and transparent; the point is a defensible floor, not the final model.

Caveats:
* Only players who appeared in the most recent season are projected (assumed active).
* Double/triple-double bonuses are applied to the *average* line, which undercounts them
  (a 9.5-rpg player still records real double-doubles). An expected-DD-rate model is Stage 2.
"""

from __future__ import annotations

import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame

# Canonical (lowercase, matches scoring keys) -> source column in player_season_stats.
COUNTING = {
    "fgm": "FGM",
    "fga": "FGA",
    "fg3m": "FG3M",
    "ftm": "FTM",
    "fta": "FTA",
    "oreb": "OREB",
    "dreb": "DREB",
    "reb": "REB",
    "ast": "AST",
    "stl": "STL",
    "blk": "BLK",
    "tov": "TOV",
    "pts": "PTS",
}

DEFAULT_WEIGHTS = (5.0, 4.0, 3.0)  # most-recent season first
DEFAULT_REG_MINUTES = 750.0  # regression strength, in minutes of league-average play
AGE_PIVOT = 27.0
AGE_YOUNG_SLOPE = 0.010  # per year below pivot (improvement)
AGE_OLD_SLOPE = 0.008  # per year above pivot (decline)
AGE_FACTOR_BOUNDS = (0.80, 1.10)
DURABILITY_PRIOR = 66.0  # league-ish games-played anchor
DURABILITY_WEIGHT = 0.35  # how hard projected GP is pulled toward the prior


def _season_start(season: str) -> int:
    """'2025-26' -> 2025."""
    return int(season[:4])


def _age_factor(age: float) -> float:
    if pd.isna(age):
        return 1.0
    if age < AGE_PIVOT:
        f = 1.0 + (AGE_PIVOT - age) * AGE_YOUNG_SLOPE
    else:
        f = 1.0 - (age - AGE_PIVOT) * AGE_OLD_SLOPE
    lo, hi = AGE_FACTOR_BOUNDS
    return min(hi, max(lo, f))


def project_baseline(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    target_season: str,
    cfg: ScoringConfig | None = None,
    n_seasons: int = 3,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    reg_minutes: float = DEFAULT_REG_MINUTES,
) -> pd.DataFrame:
    """Project a per-game stat line + fantasy points for ``target_season``.

    Parameters
    ----------
    season_stats : combined player-season stats (needs SEASON, PLAYER_ID, GP, MIN, totals).
    bio          : combined player bio (needs SEASON, PLAYER_ID, AGE).
    target_season: season to project, e.g. ``"2026-27"``.

    Returns a ranked DataFrame (one row per player) with projected per-game stats,
    ``fpts_pg`` and ``fpts_total``.
    """
    cfg = cfg or load_scoring()

    seasons = sorted(season_stats["SEASON"].unique(), key=_season_start, reverse=True)[:n_seasons]
    most_recent = seasons[0]
    w_map = {s: (weights[i] if i < len(weights) else weights[-1]) for i, s in enumerate(seasons)}

    src_cols = ["MIN", "GP"] + list(COUNTING.values())
    df = season_stats[season_stats["SEASON"].isin(seasons)].copy()
    # Defensive: collapse any duplicate player-season rows (e.g. mid-season trades) to totals.
    df = df.groupby(["PLAYER_ID", "PLAYER_NAME", "SEASON"], as_index=False)[src_cols].sum()

    df["w"] = df["SEASON"].map(w_map).astype(float)
    df["wMIN"] = df["w"] * df["MIN"]
    df["wGP"] = df["w"] * df["GP"]
    for src in COUNTING.values():
        df[f"w_{src}"] = df["w"] * df[src]

    agg_spec = {"wMIN": ("wMIN", "sum"), "wGP": ("wGP", "sum"), "w": ("w", "sum")}
    agg_spec.update({f"w_{s}": (f"w_{s}", "sum") for s in COUNTING.values()})
    agg = df.groupby(["PLAYER_ID", "PLAYER_NAME"], as_index=False).agg(**agg_spec)

    # League minutes-weighted per-minute rate for each stat (from the full population).
    total_min = agg["wMIN"].sum()
    league_rate = {c: agg[f"w_{src}"].sum() / total_min for c, src in COUNTING.items()}

    # Keep only players active in the most recent season.
    recent_ids = set(season_stats.loc[season_stats["SEASON"] == most_recent, "PLAYER_ID"])
    agg = agg[agg["PLAYER_ID"].isin(recent_ids)].reset_index(drop=True)

    # Age at the target season (most-recent-season age + season gap).
    bio_recent = (
        bio.loc[bio["SEASON"] == most_recent, ["PLAYER_ID", "AGE"]]
        .drop_duplicates("PLAYER_ID")
    )
    agg = agg.merge(bio_recent, on="PLAYER_ID", how="left")
    gap = _season_start(target_season) - _season_start(most_recent)
    target_age = agg["AGE"] + gap
    target_age = target_age.fillna(target_age.median())
    age_factor = target_age.map(_age_factor)

    # Projected playing time (deliberately simple).
    proj_mpg = agg["wMIN"] / agg["wGP"]
    weighted_gp = agg["wGP"] / agg["w"]
    proj_gp = (DURABILITY_WEIGHT * DURABILITY_PRIOR + (1 - DURABILITY_WEIGHT) * weighted_gp)
    proj_gp = proj_gp.clip(1, 82).round()

    out = pd.DataFrame(
        {
            "PLAYER_ID": agg["PLAYER_ID"],
            "PLAYER_NAME": agg["PLAYER_NAME"],
            "target_season": target_season,
            "target_age": target_age.round(1),
            "gp": proj_gp,
            "mpg": proj_mpg.round(1),
        }
    )

    # Regressed per-minute rate -> per-game stat = mpg * rate * age_factor.
    for c, src in COUNTING.items():
        rate = (agg[f"w_{src}"] + reg_minutes * league_rate[c]) / (agg["wMIN"] + reg_minutes)
        out[c] = (proj_mpg * rate * age_factor).round(2)

    out["fpts_pg"] = score_frame(out, cfg).round(2)
    out["fpts_total"] = (out["fpts_pg"] * out["gp"]).round(1)

    out = out.sort_values("fpts_total", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out
