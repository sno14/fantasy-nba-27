"""Synthetic dev fixtures for the web UI — NOT real data, NOT for modeling work.

Remote/dev sessions can't reach stats.nba.com and never carry the local parquet caches
(`data/raw`, `data/processed` are gitignored, local-only). This script fabricates a small,
schema-faithful cache so the FastAPI + React app (`scripts/serve.py`) can run end-to-end:
draft board (the learned model genuinely trains on the synthetic panel), risk ranges,
ROS snapshots, draft-sheet decision columns, player pages, and the data browser.

Player names include the real names referenced by `config/analyst_overrides.yaml` /
`analyst_proposals.yaml` (the analyst engine fails loudly on an unmatched name), but every
number is generated. A `FIXTURE_DATA.marker` file is written next to the parquets and the
API reports `fixture: true` so the UI shows a "synthetic data" badge.

Usage:
    python scripts/dev_fixtures.py           # refuses to overwrite an existing cache
    python scripts/dev_fixtures.py --force   # replaces a previous fixture cache

Guard: refuses to write when `data/raw/player_season_stats.parquet` exists WITHOUT the
fixture marker (i.e. looks like a real cache) — --force does not override that.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fantasy_nba.config import PROCESSED_DIR, RAW_DIR, ensure_data_dirs  # noqa: E402
from fantasy_nba.scoring import load_scoring  # noqa: E402

MARKER = "FIXTURE_DATA.marker"
SEASONS = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
TEAMS = ["ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
         "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
         "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"]

# Names the analyst layer references — must exist on the 2026-27 board or apply_overrides
# raises. (name, tier, age_in_2026-27, team) — tiers: 0 superstar, 1 star, 2 starter,
# 3 rotation, 4 fringe.
ANALYST_PLAYERS = [
    ("Anthony Edwards", 0, 25, "MIN"), ("Brandon Ingram", 2, 29, "TOR"),
    ("Brandon Miller", 2, 24, "CHA"), ("Brook Lopez", 3, 38, "LAC"),
    ("Cade Cunningham", 1, 25, "DET"), ("Coby White", 2, 26, "CHI"),
    ("Darius Garland", 2, 27, "CLE"), ("Day'Ron Sharpe", 3, 25, "BKN"),
    ("Dyson Daniels", 2, 23, "ATL"), ("Giannis Antetokounmpo", 0, 32, "MIL"),
    ("Grayson Allen", 3, 31, "PHX"), ("Isaiah Stewart", 3, 25, "DET"),
    ("Ja Morant", 1, 27, "MEM"), ("Jaylen Brown", 1, 30, "BOS"),
    ("John Collins", 3, 29, "LAC"), ("Josh Giddey", 2, 24, "CHI"),
    ("Julius Randle", 2, 32, "MIN"), ("Jusuf Nurkić", 3, 32, "UTA"),
    ("Kawhi Leonard", 1, 35, "LAC"), ("Kon Knueppel", 3, 21, "CHA"),
    ("LaMelo Ball", 1, 25, "CHA"), ("LeBron James", 1, 42, "LAL"),
    ("Miles Bridges", 2, 28, "CHA"), ("Mitchell Robinson", 3, 28, "NYK"),
    ("Naz Reid", 2, 27, "MIN"), ("Nikola Vučević", 2, 36, "CHI"),
    ("Norman Powell", 2, 33, "MIA"), ("Paul George", 2, 36, "PHI"),
    ("Paul Reed", 4, 27, "DET"), ("Ryan Rollins", 3, 24, "MIL"),
    ("Santi Aldama", 3, 26, "MEM"), ("Trae Young", 1, 28, "ATL"),
    ("Ty Jerome", 3, 29, "MEM"), ("Tyler Herro", 2, 27, "MIA"),
    ("Tyrese Maxey", 0, 26, "PHI"), ("Walker Kessler", 2, 25, "UTA"),
]

# Familiar stars so screenshots read like a real board (numbers still synthetic).
STAR_PLAYERS = [
    ("Nikola Jokić", 0, 31, "DEN"), ("Luka Dončić", 0, 27, "LAL"),
    ("Shai Gilgeous-Alexander", 0, 28, "OKC"), ("Victor Wembanyama", 0, 23, "SAS"),
    ("Jayson Tatum", 1, 28, "BOS"), ("Stephen Curry", 1, 38, "GSW"),
    ("Kevin Durant", 1, 38, "HOU"), ("Joel Embiid", 1, 32, "PHI"),
    ("Domantas Sabonis", 1, 30, "SAC"), ("Karl-Anthony Towns", 1, 31, "NYK"),
    ("Devin Booker", 1, 30, "PHX"), ("Donovan Mitchell", 1, 30, "CLE"),
    ("De'Aaron Fox", 1, 29, "SAS"), ("Jalen Brunson", 1, 30, "NYK"),
    ("Alperen Şengün", 1, 24, "HOU"), ("Chet Holmgren", 1, 24, "OKC"),
    ("Paolo Banchero", 1, 24, "ORL"), ("Scottie Barnes", 1, 25, "TOR"),
    ("Evan Mobley", 1, 25, "CLE"), ("Franz Wagner", 1, 25, "ORL"),
    ("Anthony Davis", 1, 33, "DAL"), ("Damian Lillard", 2, 36, "POR"),
    ("Jimmy Butler", 2, 37, "GSW"), ("Zion Williamson", 1, 26, "NOP"),
    ("Bam Adebayo", 1, 29, "MIA"), ("Pascal Siakam", 1, 32, "IND"),
    ("Tyrese Haliburton", 1, 26, "IND"), ("Jaren Jackson Jr.", 1, 27, "MEM"),
    ("Jamal Murray", 2, 29, "DEN"), ("Zach LaVine", 2, 31, "SAC"),
]

FIRST = ["Marcus", "Jalen", "Devon", "Isaiah", "Malik", "Trey", "Jaden", "Keon", "Darius",
         "Cam", "Tyrese", "Jaylen", "Aaron", "Cole", "Grant", "Reed", "Miles", "Xavier",
         "Zeke", "Andre", "Luca", "Niko", "Dario", "Bogdan", "Jonas", "Kristaps", "Deni",
         "Ousmane", "Moussa", "Sekou", "Theo", "Hugo", "Mateo", "Santi", "Rui", "Yuta"]
LAST = ["Whitfield", "Calloway", "Brenner", "Okafor", "Delgado", "Marsh", "Vickers",
        "Holloway", "Trent", "McKinney", "Sloan", "Pryor", "Ashford", "Bellamy", "Croft",
        "Dunmore", "Ellery", "Fontaine", "Garrick", "Hale", "Ibarra", "Jessup", "Kessler",
        "Lachlan", "Merritt", "Nowak", "Oduya", "Petrov", "Quill", "Rowe", "Santos",
        "Thorne", "Ustinov", "Vance", "Wilkes", "Yarrow", "Zubac", "Alston", "Boyette",
        "Carmichael", "Draper", "Easley", "Fairbanks", "Goode", "Harmon", "Ingles"]

# Per-tier anchors: (mpg, gp_mean, usage-ish scoring rate multiplier).
TIER = {
    0: dict(mpg=35.0, gp=68, mult=1.55),
    1: dict(mpg=34.0, gp=64, mult=1.30),
    2: dict(mpg=31.0, gp=66, mult=1.05),
    3: dict(mpg=24.0, gp=62, mult=0.90),
    4: dict(mpg=16.0, gp=52, mult=0.78),
}

# League-average per-36 baselines for a rotation player.
PER36 = dict(pts=15.5, reb=6.5, ast=3.6, stl=1.1, blk=0.7, fg3m=1.7, tov=1.9,
             fga=12.5, fta=3.4, oreb=1.6)


def _age_factor(age: float) -> float:
    """Smooth rise-to-27, decline-after-30 production curve."""
    if age <= 27:
        return 1.0 - 0.035 * (27 - age)
    return max(0.55, 1.0 - 0.03 * (age - 27) ** 1.15)


def build_players(rng: np.random.Generator) -> pd.DataFrame:
    rows, pid = [], 20001
    seen = set()
    for name, tier, age27, team in ANALYST_PLAYERS + STAR_PLAYERS:
        rows.append((pid, name, tier, age27, team)); seen.add(name); pid += 1
    gen_needed = 300 - len(rows)
    combos = [(f, l) for f in FIRST for l in LAST]
    rng.shuffle(combos)
    for f, l in combos:
        if gen_needed == 0:
            break
        name = f"{f} {l}"
        if name in seen:
            continue
        tier = int(rng.choice([1, 2, 3, 4], p=[0.06, 0.24, 0.38, 0.32]))
        age27 = int(np.clip(rng.normal(26.5, 3.8), 19, 40))
        team = TEAMS[len(rows) % 30]
        rows.append((pid, name, tier, age27, team)); seen.add(name); pid += 1
        gen_needed -= 1
    df = pd.DataFrame(rows, columns=["PLAYER_ID", "PLAYER_NAME", "tier", "age_2026", "team"])
    # Per-player latent style: rebound/assist/defense/three-point lean.
    n = len(df)
    df["skill"] = rng.normal(1.0, 0.10, n) * df["tier"].map(lambda t: TIER[t]["mult"])
    df["reb_lean"] = rng.lognormal(0.0, 0.45, n)
    df["ast_lean"] = rng.lognormal(0.0, 0.55, n)
    df["stk_lean"] = rng.lognormal(0.0, 0.35, n)
    df["tre_lean"] = rng.lognormal(0.0, 0.50, n)
    df["frail"] = rng.beta(2.0, 5.0, n)  # injury propensity, 0 durable → 1 fragile
    df["career_start_age"] = rng.integers(19, 24, n)
    return df


def season_rows(players: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for p in players.itertuples(index=False):
        for si, season in enumerate(SEASONS):
            age = p.age_2026 - (len(SEASONS) - si)  # 2025-26 -> age_2026 - 1
            if age < p.career_start_age or age > 43:
                continue
            af = _age_factor(age)
            mpg = float(np.clip(TIER[p.tier]["mpg"] * (0.75 + 0.35 * af) + rng.normal(0, 2.2), 6, 38.5))
            gp_mu = TIER[p.tier]["gp"] * (1 - 0.35 * p.frail)
            gp = int(np.clip(rng.normal(gp_mu, 9 + 14 * p.frail), 5, 82))
            per36 = p.skill * af
            noise = rng.normal(1.0, 0.06, 10)
            pts36 = PER36["pts"] * per36 * noise[0]
            reb36 = PER36["reb"] * p.reb_lean * (0.7 + 0.3 * per36) * noise[1]
            ast36 = PER36["ast"] * p.ast_lean * (0.7 + 0.3 * per36) * noise[2]
            stl36 = PER36["stl"] * p.stk_lean * noise[3]
            blk36 = PER36["blk"] * p.stk_lean * (p.reb_lean ** 0.5) * noise[4]
            fg3m36 = PER36["fg3m"] * p.tre_lean * (0.6 + 0.4 * per36) * noise[5]
            tov36 = PER36["tov"] * (0.55 + 0.45 * (ast36 / PER36["ast"]) ** 0.7) * noise[6]
            fga36 = PER36["fga"] * per36 * noise[7]
            fta36 = PER36["fta"] * per36 * noise[8] * (1.25 if p.tier <= 1 else 1.0)
            oreb36 = PER36["oreb"] * p.reb_lean * noise[9]
            minutes = mpg * gp
            f = minutes / 36.0
            ftm = 0.78 * fta36 * f
            # Back out FGM from PTS = 2*(FGM-FG3M) + 3*FG3M + FTM.
            pts = pts36 * f
            fg3m = fg3m36 * f
            fgm = max(fg3m, (pts - ftm - fg3m) / 2.0)
            fga = max(fgm * 1.05, fga36 * f)
            rows.append({
                "SEASON": season, "PLAYER_ID": p.PLAYER_ID, "PLAYER_NAME": p.PLAYER_NAME,
                "TEAM_ABBREVIATION": p.team, "AGE": float(age), "GP": gp,
                "MIN": round(minutes, 1),
                "FGM": round(fgm), "FGA": round(fga), "FG3M": round(fg3m),
                "FTM": round(ftm), "FTA": round(fta36 * f),
                "OREB": round(oreb36 * f), "DREB": round((reb36 - oreb36) * f),
                "REB": round(reb36 * f), "AST": round(ast36 * f), "STL": round(stl36 * f),
                "BLK": round(blk36 * f), "TOV": round(tov36 * f), "PTS": round(pts),
                "USG_PCT": round(float(np.clip(14 + 9 * (per36 - 0.8) + rng.normal(0, 1.2), 8, 40)), 1),
            })
    return pd.DataFrame(rows)


def game_logs(ss: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Per-game logs for the last two seasons (enough for the Player page trends)."""
    rows = []
    for season in SEASONS[-2:]:
        start = pd.Timestamp(f"{season[:4]}-10-22")
        sub = ss[ss["SEASON"] == season]
        for r in sub.itertuples(index=False):
            gp = int(r.GP)
            mpg = r.MIN / max(gp, 1)
            days = np.sort(rng.choice(np.arange(0, 170), size=gp, replace=False))
            mins = np.clip(rng.normal(mpg, mpg * 0.18, gp), 4, 44)
            ppm = r.PTS / max(r.MIN, 1)
            pts = np.clip(rng.normal(ppm * mins, 4.5), 0, None)
            for d, m, pt in zip(days, mins, pts):
                rows.append({
                    "SEASON": season, "PLAYER_ID": r.PLAYER_ID, "PLAYER_NAME": r.PLAYER_NAME,
                    "TEAM_ABBREVIATION": r.TEAM_ABBREVIATION,
                    "GAME_DATE": (start + pd.Timedelta(days=int(d))).date().isoformat(),
                    "MIN": round(float(m), 1), "PTS": round(float(pt)),
                })
    return pd.DataFrame(rows)


def draft_sheet(ss: pd.DataFrame, cfg, rng: np.random.Generator) -> pd.DataFrame:
    """Decision columns keyed off last-season production + noise (synthetic ADP/VOR)."""
    last = ss[ss["SEASON"] == SEASONS[-1]].copy()
    per_g = {k: last[v] / last["GP"] for k, v in
             [("pts", "PTS"), ("fg3m", "FG3M"), ("fgm", "FGM"), ("fga", "FGA"),
              ("ftm", "FTM"), ("fta", "FTA"), ("reb", "REB"), ("ast", "AST"),
              ("stl", "STL"), ("blk", "BLK"), ("tov", "TOV")]}
    fpts = sum(cfg.weights.get(k, 0.0) * v for k, v in per_g.items())
    last["fpts_pg"] = fpts
    last = last.sort_values("fpts_pg", ascending=False).reset_index(drop=True)
    repl = last["fpts_pg"].iloc[129]  # 10 teams x 13 slots ≈ replacement at 130
    last["vor"] = (last["fpts_pg"] - repl).round(1)
    last["vor_rank"] = np.arange(1, len(last) + 1)
    noisy = last["vor_rank"] + rng.normal(0, 9, len(last))
    last["adp"] = pd.Series(noisy).rank().clip(1, 250).round()
    last.loc[last["adp"] > 200, "adp"] = np.nan  # undrafted tail, like real ADP feeds
    last["market_priced"] = 0
    return last[["PLAYER_ID", "vor", "vor_rank", "adp", "market_priced"]]


def ros_snapshots(ss: pd.DataFrame, cfg, rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    """Two fake nightly ROS boards (mid-January 2027)."""
    base = draft_sheet(ss, cfg, rng)  # reuse the fpts ordering via vor_rank
    last = ss[ss["SEASON"] == SEASONS[-1]][["PLAYER_ID", "PLAYER_NAME", "GP", "MIN"]].copy()
    m = last.merge(base, on="PLAYER_ID")
    out = {}
    for i, date in enumerate(["2027-01-14", "2027-01-15"]):
        d = m.copy()
        d["fpts_pg"] = (34 - 0.16 * d["vor_rank"] + rng.normal(0, 1.5, len(d))).clip(lower=4).round(1)
        d["games_so_far"] = rng.integers(28, 44, len(d))
        d["gp"] = rng.integers(20, 38, len(d))
        d["mpg"] = (d["MIN"] / d["GP"]).round(1)
        d["fpts_total"] = (d["fpts_pg"] * d["gp"]).round()
        d = d.sort_values("fpts_pg", ascending=False).reset_index(drop=True)
        d["rank"] = np.arange(1, len(d) + 1)
        d["naive_fpts_pg"] = (d["fpts_pg"] + rng.normal(0, 2.0, len(d))).round(1)
        d["naive_rank"] = d["naive_fpts_pg"].rank(ascending=False).astype(int)
        d["status_override"] = ""
        d.loc[d.sample(6, random_state=7 + i).index, "status_override"] = "out_until_2027-02-01"
        out[date] = d[["rank", "PLAYER_ID", "PLAYER_NAME", "games_so_far", "gp", "mpg",
                       "fpts_pg", "fpts_total", "naive_fpts_pg", "naive_rank", "status_override"]]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Write synthetic dev fixtures for the web UI.")
    ap.add_argument("--force", action="store_true", help="Replace an existing FIXTURE cache.")
    args = ap.parse_args()

    marker = RAW_DIR / MARKER
    existing = RAW_DIR / "player_season_stats.parquet"
    if existing.exists() and not marker.exists():
        raise SystemExit("data/raw looks like a REAL cache (no fixture marker) — refusing to touch it.")
    if existing.exists() and not args.force:
        raise SystemExit("Fixture cache already present. Re-run with --force to regenerate.")

    rng = np.random.default_rng(0)
    ensure_data_dirs()
    players = build_players(rng)
    ss = season_rows(players, rng)
    cfg = load_scoring()

    ss.to_parquet(RAW_DIR / "player_season_stats.parquet", index=False)
    bio = ss[["PLAYER_ID", "SEASON", "AGE"]].copy()
    bio["HEIGHT_INCHES"] = np.round(rng.normal(79, 3.2, len(bio))).clip(69, 91)
    bio.to_parquet(RAW_DIR / "player_bio.parquet", index=False)
    gl = game_logs(ss, rng)
    gl.to_parquet(RAW_DIR / "player_game_logs.parquet", index=False)
    rosters = ss[ss["SEASON"] == SEASONS[-1]][
        ["SEASON", "TEAM_ABBREVIATION", "PLAYER_ID", "PLAYER_NAME", "AGE"]]
    rosters.to_parquet(RAW_DIR / "team_rosters.parquet", index=False)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    draft_sheet(ss, cfg, rng).to_parquet(PROCESSED_DIR / "draft_sheet_2026-27.parquet", index=False)
    ros_dir = PROCESSED_DIR / "ros_board"
    ros_dir.mkdir(exist_ok=True)
    for date, df in ros_snapshots(ss, cfg, rng).items():
        df.to_parquet(ros_dir / f"{date}.parquet", index=False)

    marker.write_text("Synthetic dev fixtures — generated by scripts/dev_fixtures.py. "
                      "Delete data/raw + data/processed before pulling real data.\n")
    print(f"fixtures written: {len(players)} players, {len(ss)} player-seasons, "
          f"{len(gl)} game-log rows → {RAW_DIR}")


if __name__ == "__main__":
    main()
