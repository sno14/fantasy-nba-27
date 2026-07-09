"""Injury / availability history features (Step 7 / EXP-015, ROADMAP 7.C).

Consumes the prosportstransactions scrape (``scripts/pull_injuries.py`` →
``data/raw/injuries.parquet``: verbatim ``date, team, acquired, relinquished, notes``
rows for the *injury* and *il* categories) and turns it into the first exogenous
availability signal the models see:

1. **Events** — each row's bullet-lists are exploded into per-player events
   (``out`` = relinquished, ``in`` = acquired), then resolved to ``PLAYER_ID`` by
   normalized name (``darko.normalize_name``) with the Step-7 name-join hardening:
   team + season disambiguation for colliding names, a dated append-only alias map,
   and a **hard fail** (never a silent guess) when a name stays ambiguous.
2. **Spells** — relinquish→acquire pairs per player (the injury absences). Unclosed
   spells (waived while out, season-ending) are capped at ``UNCLOSED_SPELL_DAYS``.
3. **Features** — ``INJURY_FEATURES`` as-of any date (preseason use passes Oct 1 of
   the target season), computed **only from spells strictly before** that date —
   the same no-leakage contract as every other feature module here.

The chronic-flag table for the Monte-Carlo GP pool (7.3b) also lives here
(:func:`chronic_flag_table`) so ``uncertainty.build_gp_pool`` can bucket its
empirical GP outcomes by (age × chronic) instead of age alone.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ._core import _season_start
from .darko import normalize_name

INJURY_FEATURES = [
    "inj_events_1y", "inj_events_3y",   # distinct injury spells overlapping the trailing window
    "inj_days_1y", "inj_days_3y",       # summed spell days inside the trailing window
    "inj_recency_days",                 # days since the last spell ended (cap 1500)
    "inj_chronic_flag",                 # >= 3 spells starting in the trailing 2y
    "inj_bodypart_severe",              # severe-injury regex hit in trailing-3y spell notes
]

UNCLOSED_SPELL_DAYS = 120   # season-ending absence with no "acquired" row
MAX_CLOSE_GAP_DAYS = 365    # an "acquired" further out than this can't close the spell (player
                            # left the league in between) — treat the spell as unclosed instead
RECENCY_CAP_DAYS = 1500
CHRONIC_MIN_SPELLS = 3
SEVERE_RE = re.compile(r"achilles|acl|mcl|meniscus|back surgery|stress fracture", re.IGNORECASE)

# PST team nicknames -> plausible TEAM_ABBREVIATIONs in our stats cache (2009-10 onward).
# Only used to *disambiguate* colliding player names, so era-ambiguous nicknames simply map
# to every abbreviation they've meant since 2009 (Hornets: New Orleans through 2012-13, then
# Charlotte; Nets: NJN through 2011-12, then BKN).
TEAM_NICKNAMES: dict[str, set[str]] = {
    "76ers": {"PHI"}, "Blazers": {"POR"}, "Trail Blazers": {"POR"}, "Bucks": {"MIL"},
    "Bulls": {"CHI"}, "Cavaliers": {"CLE"}, "Celtics": {"BOS"}, "Clippers": {"LAC"},
    "Grizzlies": {"MEM"}, "Hawks": {"ATL"}, "Heat": {"MIA"}, "Hornets": {"NOH", "NOK", "CHA"},
    "Jazz": {"UTA"}, "Kings": {"SAC"}, "Knicks": {"NYK"}, "Lakers": {"LAL"}, "Magic": {"ORL"},
    "Mavericks": {"DAL"}, "Nets": {"NJN", "BKN"}, "Nuggets": {"DEN"}, "Pacers": {"IND"},
    "Pelicans": {"NOP"}, "Pistons": {"DET"}, "Raptors": {"TOR"}, "Rockets": {"HOU"},
    "Spurs": {"SAS"}, "Suns": {"PHX"}, "Thunder": {"OKC"}, "Timberwolves": {"MIN"},
    "Warriors": {"GSW"}, "Wizards": {"WAS"}, "Bobcats": {"CHA"},
}

# Append-only, dated alias map (Step-7 name-join hardening rule c): PST normalized name key
# -> our normalized name key (as it appears in player_season_stats.PLAYER_NAME).
ALIASES: dict[str, str] = {
    # 2026-07-09 — initial map from the first full-history match report:
    "dj augustine": "dj augustin",        # PST misspelling (35 events)
    "roy devyn marble": "devyn marble",   # PST uses the full given name
    # 2026-07-09 — market sources (Step 9): full given names vs our stats' short forms
    "alexandre sarr": "alex sarr",
    "nicolas claxton": "nic claxton",
}

# Append-only, dated list of *known-unresolvable* collisions: (name_key, team, season-start yr)
# events where two same-named players both plausibly fit and neither ever logged stats for the
# event's team. Dropping them is explicit and bounded — any NEW collision still hard-fails.
AMBIGUOUS_DROPS: set[tuple[str, str, int]] = {
    # 2026-07-09 — two Chris Wrights (GSW-F / DAL-G) both active around the Clippers' Dec-2011
    # IL moves; neither has an LAC stats row. 4 events, both fringe players.
    ("chris wright", "Clippers", 2011),
    # 2026-07-09 — two 2013-14 Tony Mitchells (DET / MIL); the Suns Dec-2014 waiver fits both.
    ("tony mitchell", "Suns", 2014),
}


def _pst_names(cell: str) -> list[str]:
    """Names from a PST bullet cell. Each entry may carry ' / '-separated alternates."""
    if not cell or not str(cell).strip():
        return []
    return [part.strip() for part in str(cell).split("•") if part.strip()]


def _event_season(date: pd.Timestamp) -> int:
    """Season-start year a transaction date belongs to (Jul-Jun season calendar)."""
    return date.year if date.month >= 7 else date.year - 1


def explode_events(raw: pd.DataFrame) -> pd.DataFrame:
    """Verbatim scrape rows -> one row per (player-name, direction) event.

    ``direction``: ``"out"`` (relinquished — the injury/IL placement) or ``"in"``
    (acquired — activated/returned). Duplicate signals for the same (name, date,
    direction) across the *injury* and *il* categories collapse to one event.
    """
    rows = []
    for r in raw.itertuples(index=False):
        for direction, cell in (("out", r.relinquished), ("in", r.acquired)):
            for name in _pst_names(cell):
                rows.append({
                    "date": r.date, "team": str(r.team).strip(), "pst_name": name,
                    "direction": direction, "notes": r.notes,
                })
    ev = pd.DataFrame(rows, columns=["date", "team", "pst_name", "direction", "notes"])
    ev["date"] = pd.to_datetime(ev["date"])
    # Cross-category duplicates: keep one, preferring a row with notes (the injury category's).
    ev["_has_notes"] = ev["notes"].astype(str).str.len()
    ev = (ev.sort_values("_has_notes", ascending=False)
            .drop_duplicates(["date", "pst_name", "direction"])
            .drop(columns="_has_notes")
            .sort_values(["pst_name", "date"])
            .reset_index(drop=True))
    return ev


def _player_key_table(season_stats: pd.DataFrame) -> pd.DataFrame:
    """(name_key, PLAYER_ID, yr, TEAM_ABBREVIATION) rows from our stats cache."""
    cols = ["PLAYER_ID", "PLAYER_NAME", "SEASON"]
    has_team = "TEAM_ABBREVIATION" in season_stats.columns
    if has_team:
        cols.append("TEAM_ABBREVIATION")
    k = season_stats[cols].drop_duplicates().copy()
    k["name_key"] = k["PLAYER_NAME"].map(normalize_name)
    k["yr"] = k["SEASON"].map(_season_start)
    if not has_team:
        k["TEAM_ABBREVIATION"] = ""
    return k[["name_key", "PLAYER_ID", "yr", "TEAM_ABBREVIATION"]]


def resolve_players(
    events: pd.DataFrame,
    season_stats: pd.DataFrame,
    aliases: dict[str, str] | None = None,
    strict: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """Attach ``PLAYER_ID`` to exploded events by normalized name (+ team/season tiebreak).

    Returns ``(resolved_events, stats)`` where ``stats`` reports the match rate (never
    silent — implementation-plan 7.1 requires >= 95% on players in our season stats).
    Names colliding on the normalized key are disambiguated by (event season ±1, PST team
    nickname); a collision that survives disambiguation **raises** under ``strict`` (rule:
    hard-fail rather than silently keep one row — extend ``ALIASES`` instead). Names with
    no key match at all are dropped (report lists the most frequent — G-League/overseas
    names are expected there).
    """
    aliases = ALIASES if aliases is None else aliases
    keys = _player_key_table(season_stats)
    ev = events.copy()
    # Alternates ("Nene / Nene Hilario"): try each ' / ' part until one matches a known key.
    known = set(keys["name_key"])

    def _key(pst_name: str) -> str:
        # "(Christian) Johnny Davis"-style parenthesized alternate first names, and
        # " / "-separated full alternates ("Nene / Nene Hilario"): try each in turn.
        bare = re.sub(r"\([^)]*\)", " ", pst_name)
        parts = [p.strip() for p in bare.split(" / ") if p.strip()] or [pst_name]
        cand = [normalize_name(p) for p in parts]
        for c in cand:
            c = aliases.get(c, c)
            if c in known:
                return c
        return aliases.get(cand[0], cand[0])

    ev["name_key"] = ev["pst_name"].map(_key)
    ev["yr"] = ev["date"].map(_event_season)

    # Unique-key fast path: name keys mapping to exactly one PLAYER_ID anywhere in our data.
    n_ids = keys.groupby("name_key")["PLAYER_ID"].nunique()
    unique_keys = n_ids[n_ids == 1].index
    id_of = keys[keys["name_key"].isin(unique_keys)].drop_duplicates("name_key").set_index("name_key")["PLAYER_ID"]
    ev["PLAYER_ID"] = ev["name_key"].map(id_of)

    # Colliding keys: disambiguate by (season ±1, team nickname).
    ambiguous_rows = ev["PLAYER_ID"].isna() & ev["name_key"].isin(n_ids[n_ids > 1].index)
    unresolved: list[str] = []
    if ambiguous_rows.any():
        multi = keys[keys["name_key"].isin(n_ids[n_ids > 1].index)]
        by_key = {k: g for k, g in multi.groupby("name_key")}
        for idx in ev.index[ambiguous_rows]:
            row = ev.loc[idx]
            cand = by_key[row["name_key"]]
            # 1st: same-season (±1) team match.
            near = cand[cand["yr"].sub(row["yr"]).abs() <= 1]
            abbrs = TEAM_NICKNAMES.get(row["team"], set())
            hit = near[near["TEAM_ABBREVIATION"].isin(abbrs)]["PLAYER_ID"].unique()
            if len(hit) != 1:
                # 2nd: career plausibility — exactly one candidate's stats span (±2y, for
                # IL-only stints at the career edges) contains the event season.
                spans = cand.groupby("PLAYER_ID")["yr"].agg(["min", "max"])
                fits = spans[(spans["min"] - 2 <= row["yr"]) & (row["yr"] <= spans["max"] + 2)]
                hit = fits.index.to_numpy() if len(fits) == 1 else hit
            if len(hit) == 1:
                ev.loc[idx, "PLAYER_ID"] = hit[0]
            elif (row["name_key"], row["team"], row["yr"]) in AMBIGUOUS_DROPS:
                continue  # documented unresolvable — dropped, counted unmatched below
            else:
                unresolved.append(f"{row['pst_name']} ({row['team']} {row['date'].date()})")
    if unresolved and strict:
        sample = "; ".join(sorted(set(unresolved))[:20])
        raise ValueError(
            f"{len(unresolved)} events with colliding player names could not be disambiguated "
            f"by team+season — extend injuries.ALIASES (dated, append-only). Sample: {sample}"
        )

    matched = ev["PLAYER_ID"].notna()
    unmatched_names = ev.loc[~matched, "pst_name"].value_counts()
    stats = {
        "n_events": len(ev),
        "n_matched": int(matched.sum()),
        "match_rate": float(matched.mean()),
        "n_unmatched_names": int(unmatched_names.size),
        "top_unmatched": unmatched_names.head(15).to_dict(),
        "n_ambiguous_unresolved": len(unresolved),
    }
    out = ev[matched].copy()
    out["PLAYER_ID"] = out["PLAYER_ID"].astype(int)
    return out.reset_index(drop=True), stats


def injury_spells(events: pd.DataFrame) -> pd.DataFrame:
    """Pair each ``out`` event with the player's next ``in`` event -> one row per spell.

    Chronological per player: an ``out`` opens a spell (further ``out``s while open are the
    same absence and are ignored); the next ``in`` closes it. A spell with no ``in`` within
    ``MAX_CLOSE_GAP_DAYS`` (waived / season-ending) is capped at ``UNCLOSED_SPELL_DAYS``.
    ``in`` events with nothing open are ignored (e.g. activation after a pull-window edge).
    Columns: ``PLAYER_ID, start, end, days, notes`` (notes from the opening event).
    """
    rows = []
    for pid, g in events.sort_values(["PLAYER_ID", "date"]).groupby("PLAYER_ID"):
        open_start = None
        open_notes = ""
        for r in g.itertuples(index=False):
            if r.direction == "out":
                if open_start is None:
                    open_start, open_notes = r.date, r.notes
            elif open_start is not None:  # "in" closing an open spell
                gap = (r.date - open_start).days
                if gap > MAX_CLOSE_GAP_DAYS:
                    end = open_start + pd.Timedelta(days=UNCLOSED_SPELL_DAYS)
                else:
                    end = r.date
                rows.append({"PLAYER_ID": pid, "start": open_start, "end": end,
                             "days": max((end - open_start).days, 1), "notes": open_notes})
                open_start = None
        if open_start is not None:  # unclosed at the data edge
            end = open_start + pd.Timedelta(days=UNCLOSED_SPELL_DAYS)
            rows.append({"PLAYER_ID": pid, "start": open_start, "end": end,
                         "days": UNCLOSED_SPELL_DAYS, "notes": open_notes})
    return pd.DataFrame(rows, columns=["PLAYER_ID", "start", "end", "days", "notes"])


def _window_stats(spells: pd.DataFrame, as_of: pd.Timestamp, days: int) -> pd.DataFrame:
    """Per-player (n_spells, overlap_days) for spells overlapping [as_of - days, as_of)."""
    lo = as_of - pd.Timedelta(days=days)
    s = spells[(spells["end_eff"] > lo) & (spells["start"] < as_of)]
    if s.empty:
        return pd.DataFrame(columns=["n", "d"])
    overlap = (s["end_eff"].clip(upper=as_of) - s["start"].clip(lower=lo)).dt.days.clip(lower=1)
    return pd.DataFrame({"n": s.groupby("PLAYER_ID").size(), "d": overlap.groupby(s["PLAYER_ID"]).sum()})


def injury_features(spells: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """Per-PLAYER_ID ``INJURY_FEATURES`` from spells strictly before ``as_of`` (ISO date).

    Preseason use passes Oct 1 of the target season. Ongoing spells count only the days
    elapsed before ``as_of``. Players with no prior spells are absent — consumers fill
    events/days/flags with 0 and ``inj_recency_days`` with the ``RECENCY_CAP_DAYS`` cap.
    """
    cut = pd.Timestamp(as_of)
    s = spells[spells["start"] < cut].copy()
    if s.empty:
        return pd.DataFrame(columns=["PLAYER_ID"] + INJURY_FEATURES)
    s["end_eff"] = s["end"].clip(upper=cut)

    w1, w3 = _window_stats(s, cut, 365), _window_stats(s, cut, 3 * 365)
    out = pd.DataFrame(index=s["PLAYER_ID"].unique())
    out.index.name = "PLAYER_ID"
    out["inj_events_1y"] = w1["n"]
    out["inj_events_3y"] = w3["n"]
    out["inj_days_1y"] = w1["d"]
    out["inj_days_3y"] = w3["d"]
    last_end = s.groupby("PLAYER_ID")["end_eff"].max()
    out["inj_recency_days"] = (cut - last_end).dt.days.clip(0, RECENCY_CAP_DAYS)
    starts_2y = s[s["start"] >= cut - pd.Timedelta(days=2 * 365)]
    out["inj_chronic_flag"] = (starts_2y.groupby("PLAYER_ID").size() >= CHRONIC_MIN_SPELLS).astype(int)
    lo3 = cut - pd.Timedelta(days=3 * 365)
    recent3 = s[s["end_eff"] > lo3]
    severe = recent3.groupby("PLAYER_ID")["notes"].apply(
        lambda n: int(n.astype(str).str.contains(SEVERE_RE).any())
    )
    out["inj_bodypart_severe"] = severe
    for col in ["inj_events_1y", "inj_events_3y", "inj_days_1y", "inj_days_3y",
                "inj_chronic_flag", "inj_bodypart_severe"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["inj_recency_days"] = (
        pd.to_numeric(out["inj_recency_days"], errors="coerce").fillna(RECENCY_CAP_DAYS).astype(int)
    )
    return out.reset_index()


def chronic_flag_table(spells: pd.DataFrame, seasons: list[str]) -> pd.DataFrame:
    """Per (SEASON, PLAYER_ID) chronic flag as-of Oct 1 of each season (for the 7.3b GP pool)."""
    frames = []
    for season in seasons:
        f = injury_features(spells, f"{_season_start(season)}-10-01")
        if f.empty:
            continue
        frames.append(pd.DataFrame({
            "SEASON": season, "PLAYER_ID": f["PLAYER_ID"],
            "inj_chronic_flag": f["inj_chronic_flag"],
        }))
    if not frames:
        return pd.DataFrame(columns=["SEASON", "PLAYER_ID", "inj_chronic_flag"])
    return pd.concat(frames, ignore_index=True)


def build_spells(raw: pd.DataFrame, season_stats: pd.DataFrame, strict: bool = True) -> tuple[pd.DataFrame, dict]:
    """Scrape parquet -> resolved spells table (the one-call entry point for scripts/backtest)."""
    events = explode_events(raw)
    resolved, stats = resolve_players(events, season_stats, strict=strict)
    return injury_spells(resolved), stats
