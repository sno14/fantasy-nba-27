"""Pull market boards (Step 9 / EXP-017): expert consensus + consensus ADP, date-stamped.

Two market objects, never conflated (user decision 2026-07-09):

* ``hashtag``     — Hashtag Basketball **points-league rankings** (public HTML; the expert
                    consensus / value signal). Plain requests, no Cloudflare, ~200 rows.
* ``fantasypros`` — FantasyPros **consensus ADP** (Yahoo/ESPN average; the availability
                    signal only — "likely gone by pick N", D1.4). ~260 rows.

Every pull is stored **append-only, date-stamped** (``data/raw/market/<source>_<date>.parquet``)
— the DARKO-archive pattern: accumulating these from today is what makes EXP-017b (market-gap
as a feature) backtestable next season, because genuine historical preseason snapshots proved
unrecoverable for ≥4 seasons (see the EXP-017b retrievability audit in EXPERIMENTS.md).

Name-join: normalized-name match against our season stats with a printed match-rate report
(Step-7 hardening; gate ≥95% on the draftable pool). Unmatched market rows are *kept* in the
parquet (rookies with no NBA stats are expected misses preseason — the D1.5 market-seed reads
them), only reported.

Usage
-----
    python scripts/pull_market.py                 # both sources
    python scripts/pull_market.py --source hashtag
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import requests
from bs4 import BeautifulSoup

from fantasy_nba.config import RAW_DIR
from fantasy_nba.data import storage
from fantasy_nba.models.darko import normalize_name as _normalize
from fantasy_nba.models.injuries import ALIASES


def normalize_name(name: str) -> str:
    """Shared normalizer + the dated cross-source alias map (Step-7 hardening rule c)."""
    key = _normalize(name)
    return ALIASES.get(key, key)

MARKET_DIR = RAW_DIR / "market"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
TIMEOUT = 60

HASHTAG_URL = "https://hashtagbasketball.com/fantasy-basketball-points-league-rankings"
FANTASYPROS_URL = "https://www.fantasypros.com/nba/adp/overall.php"

_FP_PLAYER = re.compile(r"^(?P<name>.*?)\s*\((?P<team>[A-Z]{2,4})\s*-\s*(?P<pos>[^)]*)\)")


def _largest_table(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        raise RuntimeError("No <table> found — page layout changed?")
    best = max(tables, key=lambda t: len(t.find_all("tr")))
    return [[td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
            for tr in best.find_all("tr")]


def parse_hashtag(html: str) -> pd.DataFrame:
    """Hashtag rankings table -> [consensus_rank, player, team, pos, consensus_value].

    Handles both layouts: the points-league page uses NAME/TOTAL (projected total points);
    the category pages use PLAYER (+ optional ADP). Repeated in-table header rows (the page
    re-inserts them every 25 players) are skipped.
    """
    rows = _largest_table(html)
    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}
    name_col = "NAME" if "NAME" in idx else "PLAYER"
    for req in ("R#", name_col, "TEAM"):
        if req not in idx:
            raise RuntimeError(f"Hashtag table missing column {req!r}; header={header}")
    out = []
    for r in rows[1:]:
        if len(r) < len(header) or r[idx["R#"]] == "R#":  # repeated in-table header
            continue
        try:
            rank = int(r[idx["R#"]])
        except ValueError:
            continue
        out.append({
            "consensus_rank": rank,
            "player": r[idx[name_col]],
            "team": r[idx["TEAM"]],
            "pos": r[idx["POS"]] if "POS" in idx else "",
            "consensus_value": (pd.to_numeric(r[idx["TOTAL"]], errors="coerce")
                                if "TOTAL" in idx else None),
            "adp": pd.to_numeric(r[idx["ADP"]], errors="coerce") if "ADP" in idx else None,
        })
    return pd.DataFrame(out)


def parse_fantasypros(html: str) -> pd.DataFrame:
    """FantasyPros ADP table -> [adp_rank, player, team, pos, adp] (site columns vary by
    year — Yahoo/ESPN/CBS come and go; only Rank/Player/AVG are relied on)."""
    rows = _largest_table(html)
    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}
    for req in ("Rank", "Player", "AVG"):
        if req not in idx:
            raise RuntimeError(f"FantasyPros table missing column {req!r}; header={header}")
    out = []
    for r in rows[1:]:
        if len(r) < 3:
            continue
        m = _FP_PLAYER.match(r[idx["Player"]])
        name = m.group("name") if m else r[idx["Player"]]
        out.append({
            "adp_rank": pd.to_numeric(r[idx["Rank"]], errors="coerce"),
            "player": name.strip(),
            "team": m.group("team") if m else "",
            "pos": m.group("pos") if m else "",
            "adp": pd.to_numeric(r[idx["AVG"]], errors="coerce"),
        })
    df = pd.DataFrame(out).dropna(subset=["adp_rank"])
    df["adp_rank"] = df["adp_rank"].astype(int)
    return df


SOURCES = {
    "hashtag": (HASHTAG_URL, parse_hashtag),
    "fantasypros": (FANTASYPROS_URL, parse_fantasypros),
}


def match_report(market: pd.DataFrame, season_stats: pd.DataFrame, top_n: int = 150) -> dict:
    """Name-key match rate vs our stats cache, overall and within the market's top ``top_n``
    (the draftable pool — where the ≥95% gate applies; deep-list misses are mostly rookies)."""
    known = set(season_stats["PLAYER_NAME"].map(normalize_name))
    matched = market["name_key"].isin(known)
    rank_col = "consensus_rank" if "consensus_rank" in market else "adp_rank"
    top = market[market[rank_col] <= top_n]
    top_matched = top["name_key"].isin(known)
    return {
        "n": len(market), "match_rate": float(matched.mean()),
        f"top{top_n}_match_rate": float(top_matched.mean()) if len(top) else float("nan"),
        "top_unmatched": top.loc[~top_matched, "player"].tolist()[:12],
    }


def pull(source: str, wayback: str | None = None) -> pd.DataFrame:
    url, parser = SOURCES[source]
    if wayback:
        url = f"http://web.archive.org/web/{wayback}/{url}"
    html = requests.get(url, headers=HEADERS, timeout=TIMEOUT).text
    df = parser(html)
    if df.empty:
        raise RuntimeError(f"[{source}] parsed 0 rows — layout changed?")
    df["name_key"] = df["player"].map(normalize_name)
    df.insert(0, "source", source)
    df.insert(1, "pulled", dt.date.today().isoformat())
    if wayback:
        df.insert(2, "wayback", wayback)

    season_stats = storage.read("player_season_stats")
    rep = match_report(df, season_stats)
    print(f"[{source}] {rep['n']} rows; match {rep['match_rate']:.3f} overall, "
          f"{rep['top150_match_rate']:.3f} in top-150")
    if rep["top_unmatched"]:
        print(f"[{source}] top-150 unmatched (rookies expected preseason): {rep['top_unmatched']}")

    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    stamp = wayback[:8] if wayback else dt.date.today().isoformat()
    path = MARKET_DIR / f"{source}_{stamp}.parquet"
    df.to_parquet(path, index=False)
    print(f"[{source}] saved -> {path}")
    return df


def load_latest(source: str) -> pd.DataFrame:
    files = sorted(MARKET_DIR.glob(f"{source}_*.parquet"))
    if not files:
        raise FileNotFoundError(f"No {source} pulls in {MARKET_DIR}. Run scripts/pull_market.py.")
    df = pd.read_parquet(files[-1])
    df.attrs["source_file"] = files[-1].name
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull market boards (expert consensus + ADP).")
    parser.add_argument("--source", choices=sorted(SOURCES), default=None,
                        help="One source only (default: all).")
    parser.add_argument("--wayback", default=None, metavar="TIMESTAMP",
                        help="Pull an archived snapshot (YYYYMMDD[hhmmss]) instead of live — "
                             "used by the EXP-017b retrievability audit.")
    args = parser.parse_args()
    for source in ([args.source] if args.source else sorted(SOURCES)):
        pull(source, wayback=args.wayback)


if __name__ == "__main__":
    main()
