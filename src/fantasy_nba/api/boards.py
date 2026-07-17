"""Board computation for the API — the same no-leakage recipe as scripts/explore.py,
with an in-process cache keyed on (target, model, analyst, overrides-file mtime).

Everything reads the local parquet cache; projections are computed live so they always
reflect the current scoring config and analyst overrides. Past seasons are re-projected
with **no leakage** (prior-only training data) and joined to actual results; the analyst
layer only ever touches the current target season (a July 2026 override must not adjust
a 2023-24 backtest board).
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from ..config import CONFIG_DIR, PROCESSED_DIR
from ..data import storage
from ..models._core import _season_start
from ..models.aging import build_aging_curves
from ..models.analyst import apply_overrides, load_overrides
from ..models.backtest import _actual
from ..models.baseline import project_baseline
from ..models.durability import build_gp_age_curve
from ..models.learned import project_learned
from ..models.minutes import build_minutes_age_curve
from ..models.projection import project_v2
from ..models.uncertainty import build_gp_pool, rank_board, simulate_ranges
from ..scoring import load_scoring

CURRENT_TARGET = "2026-27"
ANALYST_PATH = CONFIG_DIR / "analyst_overrides.yaml"
TARGET_SEASONS = ["2026-27", "2025-26", "2024-25", "2023-24", "2022-23"]
MODELS = {
    "learned": "LightGBM decompositional (EXP-007; the shipped default)",
    "v2m": "v2 + minutes aging",
    "v2": "empirical aging curves + durability",
    "baseline": "Marcel (recency-weighted rates)",
}
STANCES = {
    "safe": "median − ½·downside — as accurate as median but demotes injury-prone players",
    "median": "expected (median) season total",
    "floor": "10th-percentile total — maximise safety",
    "ceiling": "90th-percentile total — maximise upside",
}

# Tier detection (draft-day upgrade): a tier break is an unusually large draft_value gap
# between adjacent ranked players. The threshold is a high percentile of the adjacent
# gaps over the tiered depth (so ~TIER_DEPTH * (1 - TIER_GAP_Q) breaks), floored at
# TIER_MIN_GAP season points so near-uniform boards don't fragment. Only the draftable
# head of the board is tiered.
TIER_DEPTH = 160
TIER_MIN_GAP = 40.0
TIER_GAP_Q = 0.93


def overrides_mtime() -> float:
    return ANALYST_PATH.stat().st_mtime if ANALYST_PATH.exists() else 0.0


@lru_cache(maxsize=4)
def _raw(name: str) -> pd.DataFrame:
    try:
        return storage.read(name)
    except FileNotFoundError:
        return pd.DataFrame()


def raw(name: str) -> pd.DataFrame:
    return _raw(name)


def data_ready() -> bool:
    return not _raw("player_season_stats").empty


@lru_cache(maxsize=1)
def _injury_profile(_mtime_key: float):
    """(spells, chronic_flag_table) for the (age x chronic) GP pools; (None, None) when
    the injuries pull isn't cached."""
    if not storage.exists("injuries"):
        return None, None
    from ..models import injuries as inj

    ss = _raw("player_season_stats")
    spells, _ = inj.build_spells(storage.read("injuries"), ss)
    chronic = inj.chronic_flag_table(spells, sorted(ss["SEASON"].unique(), key=_season_start))
    return spells, chronic


@lru_cache(maxsize=8)
def compute_board(target: str, model: str, apply_analyst: bool, ovr_mtime: float) -> pd.DataFrame:
    """No-leakage board for ``target`` + risk ranges (+ actuals for past seasons).

    ``ovr_mtime`` is a cache key only: editing config/analyst_overrides.yaml (or promoting
    proposals) busts the cache on the next request.
    """
    ss, bio = _raw("player_season_stats"), _raw("player_bio")
    cfg = load_scoring()
    ty = _season_start(target)
    max_year = int(ss["SEASON"].map(_season_start).max())

    tr_ss = ss[ss["SEASON"].map(_season_start) < ty]
    tr_bio = bio[bio["SEASON"].map(_season_start) < ty]

    if model == "learned":
        proj = project_learned(tr_ss, tr_bio, target_season=target, cfg=cfg)
    elif model == "baseline":
        proj = project_baseline(tr_ss, tr_bio, target_season=target, cfg=cfg)
    else:
        curves = build_aging_curves(tr_ss, tr_bio, save=False)
        gpc = build_gp_age_curve(tr_ss, tr_bio, save=False)
        mc = build_minutes_age_curve(tr_ss, tr_bio, save=False) if model == "v2m" else None
        proj = project_v2(tr_ss, tr_bio, target_season=target, cfg=cfg, curves=curves,
                          gp_curve=gpc, mpg_curve=mc, age_minutes=(model == "v2m"))

    # Analyst layer (board B) — current season only, before the ranges are simulated so
    # floor/median/ceiling move with the fpts_delta.
    if apply_analyst and target == CURRENT_TARGET and ANALYST_PATH.exists():
        entries = load_overrides(ANALYST_PATH)
        if entries:
            proj = apply_overrides(proj, entries)

    spells, chronic = _injury_profile(_spells_key())
    if spells is not None:
        from ..models.injuries import injury_features

        flags = injury_features(spells, f"{ty}-10-01")[["PLAYER_ID", "inj_chronic_flag"]]
        proj = proj.merge(flags, on="PLAYER_ID", how="left")
        proj["inj_chronic_flag"] = proj["inj_chronic_flag"].fillna(0).astype(int)
    pool = build_gp_pool(tr_ss, tr_bio, max_start_year=ty, injury_profile=chronic)
    proj = simulate_ranges(proj, pool)
    recent = tr_ss.sort_values("SEASON").drop_duplicates("PLAYER_ID", keep="last")
    proj = proj.merge(recent[["PLAYER_ID", "TEAM_ABBREVIATION"]], on="PLAYER_ID", how="left")

    sheet_path = PROCESSED_DIR / f"draft_sheet_{target}.parquet"
    if sheet_path.exists():
        sheet = pd.read_parquet(sheet_path)
        d1 = [c for c in ("vor", "vor_rank", "adp", "market_priced", "seed_class")
              if c in sheet.columns]
        proj = proj.merge(sheet[["PLAYER_ID"] + d1].drop_duplicates("PLAYER_ID"),
                          on="PLAYER_ID", how="left")
        # D1.5 market-priced rows (rookies + returning vets with zero 2025-26 games — the
        # Haliburton gap, found 2026-07-17) have no prior-season feature row, so the live
        # projection above cannot produce them. Append the ones with a real PLAYER_ID as
        # flagged market prices: no simulated ranges (risk/p10/p90 stay NaN; the UI shows
        # "—"), and rank_board prices them at their ADP anchor. Id-less rows (rookies
        # before the October id pass) stay sheet-only — the API's int(PLAYER_ID) contract
        # excludes them.
        if "market_priced" in sheet.columns and "PLAYER_ID" in sheet.columns:
            extra = sheet[(sheet["market_priced"] == 1) & sheet["PLAYER_ID"].notna()
                          & ~sheet["PLAYER_ID"].isin(proj["PLAYER_ID"])].copy()
            if not extra.empty:
                keep = [c for c in ("PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION",
                                    "fpts_pg", "fpts_total", *d1) if c in extra.columns]
                extra = extra[keep]
                extra["PLAYER_ID"] = extra["PLAYER_ID"].astype(proj["PLAYER_ID"].dtype)
                if "TEAM_ABBREVIATION" not in extra.columns:
                    # older sheets predate the market-team column: fall back to last stats team
                    extra["TEAM_ABBREVIATION"] = extra["PLAYER_ID"].map(
                        recent.set_index("PLAYER_ID")["TEAM_ABBREVIATION"])
                proj = pd.concat([proj, extra], ignore_index=True)

    # Current-season team display: the last-stats-row team above predates the offseason,
    # so overlay the transaction-derived roster map (prior-season primary team + player
    # movement through the cache; the same map the mid-Oct pass freezes at Oct 1). Players
    # absent from the map — seeded returning vets, unsigned FAs — keep what they have.
    if target == CURRENT_TARGET:
        tx = _raw("transactions")
        if not tx.empty:
            from ..models.rosters import preseason_roster_map

            tmap = preseason_roster_map(ss, tx, target)
            proj["TEAM_ABBREVIATION"] = (
                proj["PLAYER_ID"].map(dict(zip(tmap["PLAYER_ID"], tmap["team"])))
                .fillna(proj["TEAM_ABBREVIATION"]))

    if ty <= max_year:  # season already played — join actual outcomes
        act = _actual(ss, target, cfg, 0.0).copy()
        act["actual_rank"] = act["act_fpts_total"].rank(ascending=False, method="min").astype(int)
        proj = proj.merge(
            act[["PLAYER_ID", "act_fpts_pg", "act_fpts_total", "act_gp", "actual_rank"]],
            on="PLAYER_ID", how="left")
    return proj


def _spells_key() -> float:
    from ..config import RAW_DIR

    p = RAW_DIR / "injuries.parquet"
    return p.stat().st_mtime if p.exists() else 0.0


def add_tiers(board: pd.DataFrame) -> pd.DataFrame:
    """Tier numbers from draft_value gaps on an already-ranked board (1 = top tier).

    A break lands where the gap to the previous player is unusually large for this
    board — above the TIER_GAP_Q percentile of adjacent gaps over the tiered depth
    (and at least TIER_MIN_GAP season points). Rows past TIER_DEPTH get no tier.
    """
    out = board.copy()
    out["tier"] = np.nan
    head = out.head(TIER_DEPTH)
    vals = head["draft_value"].to_numpy(dtype=float)
    if len(vals) < 3:
        return out
    gaps = -np.diff(vals)
    thresh = max(TIER_MIN_GAP, float(np.quantile(gaps, TIER_GAP_Q)))
    tier, tiers = 1, [1]
    for g in gaps:
        if g >= thresh:
            tier += 1
        tiers.append(tier)
    out.loc[head.index, "tier"] = tiers
    return out


def ranked_board(target: str, model: str, stance: str, apply_analyst: bool) -> pd.DataFrame:
    board = compute_board(target, model, apply_analyst, overrides_mtime())
    return add_tiers(rank_board(board, method=stance))


# ------------------------------------------------------------------------------- schedule
def load_schedule(target: str) -> pd.DataFrame:
    """The target season's schedule pull (regular-season games only), or an empty frame
    when `scripts/pull_schedule.py` hasn't cached one yet (published ~mid-August)."""
    name = f"schedule_{target}"
    if not storage.exists(name):
        return pd.DataFrame()
    df = storage.read(name)
    if "regular_season" in df.columns:
        df = df[df["regular_season"] == True].copy()  # noqa: E712
    else:
        df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df


def team_week_games(target: str) -> pd.DataFrame:
    """Schedule in long form: one row per (team, week, game_date) so per-team weekly game
    counts fall straight out of a groupby. Empty when no schedule is cached."""
    sch = load_schedule(target)
    if sch.empty:
        return sch
    cols = ["game_date", "week", "week_name"]
    home = sch[cols + ["home"]].rename(columns={"home": "team"})
    away = sch[cols + ["away"]].rename(columns={"away": "team"})
    return pd.concat([home, away], ignore_index=True)
