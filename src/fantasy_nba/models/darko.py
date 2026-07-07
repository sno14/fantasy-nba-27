"""Consume DARKO as a **live** signal — minutes cross-check + disagreement finder (Stage 7.E).

DARKO's public export (``scripts/pull_darko.py``) is a *skill + minutes* board: DPM/ODPM/DDPM,
projected **MPG**, per-100 scoring, shooting %. It has **no full box line**, so we can't compute
DARKO fantasy points and a points-level ensemble isn't honest. What it gives us, with the right
expectations (from DARKO's own docs):

  * **DPM / per-100 skill** — DARKO's *strength*: it beats DFS sites on pts/reb/ast/blk/tov/3PM.
    But note the sober implication for us — per-minute **rates are already our strength too**
    (EXP-001), so DARKO's skill layer is largely *redundant* with what we do well; it's a prior and
    a disagreement signal, not a big new lever.
  * **MPG** — an independent estimate of our single largest error source (minutes, EXP-001) — but
    minutes is DARKO's **own self-admitted weakest output** (the one stat where it lost to DFS
    projections). So a minutes gap is a **mutual-uncertainty flag** ("both systems are guessing
    here"), *not* "DARKO is right and we're wrong." Treat it as a risk highlighter, not a correction.

**Two big caveats baked into DARKO (from its About page):**
  1. **Rookies/young players are placeholder-initialized** — DARKO has no NCAA/summer-league/preseason
     data, so preseason it starts rookies from a generic point and only learns once they play. In the
     offseason its young-player minutes/skill are largely priors, so the disagreement list is
     *dominated by young players for an artefactual reason* — down-weight those gaps.
  2. It's a daily box-score/skill engine, **blind to exogenous context** (roster turnover, news,
     depth charts) — the fantasy levers we're chasing. It complements, it doesn't replace, that work.

**Status: live-only, not backtested** — no historical as-of-date DARKO snapshots exist to validate
against (see EXPERIMENTS.md EXP-010 / memory ``darko-data-availability``). This module therefore
*informs* the board (cross-check + overlay); it does not silently move projections.

Join is by normalized name (DARKO has no player id; our board carries PLAYER_ID/PLAYER_NAME) with
team as a tiebreaker, after stripping accents and suffixes.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from ..config import RAW_DIR

DARKO_DIR = RAW_DIR / "darko"
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def normalize_name(name: str) -> str:
    """Accent/suffix/punctuation-insensitive key for joining DARKO to our board."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = re.sub(r"[.'`]", "", s.lower())
    s = _SUFFIX.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _to_float(series: pd.Series) -> pd.Series:
    """Parse DARKO's decorated numerics ('+7.4', '$94.1M') to plain floats."""
    cleaned = series.astype(str).str.replace(r"[+$,%]", "", regex=True).str.replace("M", "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce")


def load_latest_darko(darko_dir: Path = DARKO_DIR) -> pd.DataFrame:
    """Load the most recent date-stamped DARKO parquet with normalized/typed columns."""
    files = sorted(darko_dir.glob("darko_*.parquet"))
    if not files:
        raise FileNotFoundError(f"No DARKO pulls in {darko_dir}. Run scripts/pull_darko.py first.")
    latest = files[-1]
    d = pd.read_parquet(latest)
    out = pd.DataFrame({
        "darko_name": d["Player"],
        "name_key": d["Player"].map(normalize_name),
        "darko_team": d.get("Team"),
        "darko_rank": _to_float(d["#"]).astype("Int64"),
        "darko_mpg": _to_float(d["MPG"]),
        "darko_dpm": _to_float(d["DPM"]),
        "darko_value": _to_float(d.get("$ Value", pd.Series(index=d.index, dtype=object))),
    })
    out.attrs["source_file"] = latest.name
    return out


def join_board(board: pd.DataFrame, darko: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Left-join DARKO onto our projection ``board`` by normalized name.

    Returns ``(joined, stats)`` where ``stats`` reports the match rate so a low join quality is
    never silent. Duplicate normalized names in DARKO (rare) keep the highest-ranked row.
    """
    darko = darko if darko is not None else load_latest_darko()
    darko = darko.sort_values("darko_rank").drop_duplicates("name_key", keep="first")

    j = board.copy()
    j["name_key"] = j["PLAYER_NAME"].map(normalize_name)
    j = j.merge(
        darko[["name_key", "darko_name", "darko_rank", "darko_mpg", "darko_dpm", "darko_value"]],
        on="name_key", how="left",
    )
    matched = j["darko_mpg"].notna()
    stats = {"n_board": len(j), "n_matched": int(matched.sum()), "match_rate": float(matched.mean())}
    return j, stats


def minutes_disagreement(joined: pd.DataFrame, top_n: int = 150, min_gap: float = 4.0) -> pd.DataFrame:
    """Players (within our top-``top_n``) where our MPG most disagrees with DARKO's.

    A large gap flags our biggest minutes risk — the layer that drives most projection error.
    Positive ``mpg_gap`` = we project more minutes than DARKO (over-optimistic risk).
    """
    pool = joined.nsmallest(top_n, "rank") if "rank" in joined else joined.head(top_n)
    pool = pool[pool["darko_mpg"].notna()].copy()
    pool["mpg_gap"] = (pool["mpg"] - pool["darko_mpg"]).round(1)
    out = pool[pool["mpg_gap"].abs() >= min_gap]
    cols = ["PLAYER_NAME", "mpg", "darko_mpg", "mpg_gap"]
    if "rank" in out:
        cols = ["rank"] + cols
    return out[cols].sort_values("mpg_gap", key=lambda s: s.abs(), ascending=False)


def rank_disagreement(joined: pd.DataFrame, top_n: int = 150, min_gap: int = 25) -> pd.DataFrame:
    """Players where our rank most diverges from DARKO's DPM rank — the actionable calls.

    Negative ``rank_gap`` = we rank the player *higher* than DARKO (our sleeper vs the market);
    positive = we rank him lower (our fade). These are the disagreement-finder outputs of 7.E.
    """
    pool = joined.nsmallest(top_n, "rank") if "rank" in joined else joined.head(top_n)
    pool = pool[pool["darko_rank"].notna()].copy()
    pool["rank_gap"] = (pool["rank"] - pool["darko_rank"]).astype(int)
    out = pool[pool["rank_gap"].abs() >= min_gap]
    return out[["rank", "PLAYER_NAME", "darko_rank", "rank_gap", "mpg", "darko_mpg"]].sort_values(
        "rank_gap", key=lambda s: s.abs(), ascending=False
    )
