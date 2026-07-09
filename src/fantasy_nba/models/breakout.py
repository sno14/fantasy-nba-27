"""Breakout archetype layer, judged on recall (Step 9b / EXP-026, ROADMAP 7.B done right).

Why this exists: EXP-011 proved the model-pool riser *bias* is ≈ irreducible preseason, but
the realized-pool view showed the real cost — recall ~71%: eventual big risers the board never
ranked top-150. You can't know which of ~20 archetype fits pops; ranking all of them higher
*is* the edge (the Maxey pattern: age-22-24 improvement streak × usage↑ at held TS% × room to
grow — all visible preseason). So this layer is judged on **getting eventual risers into/up
the board**, never on per-player point error.

Two wirings, judged separately (EXP-026):
  (a) ``BREAKOUT_FEATURES`` into the learned model (variant ``learned_breakout``) — the
      season-keyed ``breakout_feature_table`` follows the EXP-016b pattern: each block uses
      prior seasons only, so it is computed once and sliced per fold.
  (b) a **board policy** (:func:`apply_breakout_policy`) — deterministic, auditable: the
      top-K breakout scores outside the stable core get a bounded rank boost + a
      ``breakout_p`` column on the draft sheet, sized so late-round picks chase option value
      while the core is untouched.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring, score_frame
from ._core import COUNTING, _season_start

BREAKOUT_FEATURES = [
    "improve_streak_2y",   # consecutive prior seasons of rising fpts/min (0/1/2)
    "usg_slope_held_ts",   # ΔUSG% (t−1 vs t−2) where ΔTS% ≥ −0.01, else 0
    "mpg_headroom",        # max(0, 36 − prev_mpg): room to grow
    "age_22_24",           # the research's breakout window (target-season age)
    "years_experience",    # prior seasons with an NBA stats row
    "draft_pick",          # pedigree; 61 = undrafted sentinel (bio DRAFT_NUMBER)
]

BREAKOUT_DELTA = 6.0        # fpts/g jump that defines a breakout (the eval's big-riser edge)
MIN_PRIOR_MINUTES = 500.0   # the label needs a meaningful prior-season baseline
UNDRAFTED_PICK = 61

DEFAULT_CLF_PARAMS = dict(
    n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=30,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
    random_state=0, n_jobs=-1, verbosity=-1,
)


def _season_lines(season_stats: pd.DataFrame, cfg: ScoringConfig) -> pd.DataFrame:
    """Per (PLAYER_ID, yr): MIN, MPG, fpts_pg, fpts_pm, USG, TS — the per-season summary the
    archetype features read."""
    cols = ["GP", "MIN"] + list(COUNTING.values())
    s = season_stats.groupby(["PLAYER_ID", "SEASON"], as_index=False)[cols].sum()
    per_game = pd.DataFrame({c: s[src] / s["GP"] for c, src in COUNTING.items()})
    s["fpts_pg"] = score_frame(per_game, cfg)
    s["mpg"] = s["MIN"] / s["GP"]
    s["fpts_pm"] = s["fpts_pg"] / s["mpg"].replace(0, np.nan)
    w = season_stats.assign(wUSG=season_stats["USG_PCT"] * season_stats["MIN"],
                            wTS=season_stats["TS_PCT"] * season_stats["MIN"])
    ww = w.groupby(["PLAYER_ID", "SEASON"], as_index=False)[["wUSG", "wTS"]].sum()
    s = s.merge(ww, on=["PLAYER_ID", "SEASON"])
    s["USG"] = s["wUSG"] / s["MIN"].replace(0, np.nan)
    s["TS"] = s["wTS"] / s["MIN"].replace(0, np.nan)
    s["yr"] = s["SEASON"].map(_season_start)
    return s[["PLAYER_ID", "SEASON", "yr", "MIN", "mpg", "fpts_pg", "fpts_pm", "USG", "TS"]]


def _draft_pick(bio: pd.DataFrame) -> pd.Series:
    """PLAYER_ID → overall pick (61 = undrafted / unknown)."""
    b = bio.drop_duplicates("PLAYER_ID", keep="last")
    pick = pd.to_numeric(b["DRAFT_NUMBER"], errors="coerce").fillna(UNDRAFTED_PICK)
    return pd.Series(pick.to_numpy(), index=b["PLAYER_ID"].to_numpy())


def breakout_feature_table(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    cfg: ScoringConfig | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """``[SEASON, PLAYER_ID, *BREAKOUT_FEATURES]`` per season block.

    Row block for season S reads seasons < S only (plus static bio facts), so the table is
    fold-safe by construction and sliced per season by consumers (the EXP-016b pattern).
    Players covered: everyone with an S−1 stats row (the board's own universe).
    ``seasons`` defaults to every cached season with a predecessor; pass extra upcoming
    seasons (live use: the projection target) — each just needs its S−1 stats cached.
    """
    cfg = cfg or load_scoring()
    lines = _season_lines(season_stats, cfg)
    by_py = lines.set_index(["PLAYER_ID", "yr"])
    ages = bio[["PLAYER_ID", "SEASON", "AGE"]].drop_duplicates(["PLAYER_ID", "SEASON"]).copy()
    ages["yr"] = ages["SEASON"].map(_season_start)
    age_of = ages.set_index(["PLAYER_ID", "yr"])["AGE"]
    picks = _draft_pick(bio)
    n_prior = lines.groupby("PLAYER_ID")["yr"].apply(lambda s: sorted(s.unique()))

    if seasons is None:
        seasons = sorted(lines["SEASON"].unique(), key=_season_start)[1:]
    frames = []
    for s in seasons:
        ty = _season_start(s)
        prev = lines[lines["yr"] == ty - 1]
        if prev.empty:
            raise ValueError(f"breakout_feature_table: no stats for the season before {s!r}.")
        rows = []
        for r in prev.itertuples(index=False):
            pid = r.PLAYER_ID

            def _line(offset: int):
                try:
                    return by_py.loc[(pid, ty - offset)]
                except KeyError:
                    return None

            l1, l2, l3 = r, _line(2), _line(3)
            streak = 0
            if l2 is not None and pd.notna(l1.fpts_pm) and pd.notna(l2["fpts_pm"]) \
                    and l1.fpts_pm > l2["fpts_pm"]:
                streak = 1
                if l3 is not None and pd.notna(l3["fpts_pm"]) and l2["fpts_pm"] > l3["fpts_pm"]:
                    streak = 2
            usg_held = 0.0
            if l2 is not None and pd.notna(l1.USG) and pd.notna(l2["USG"]) \
                    and pd.notna(l1.TS) and pd.notna(l2["TS"]) and (l1.TS - l2["TS"]) >= -0.01:
                usg_held = float(l1.USG - l2["USG"])
            age_prev = age_of.get((pid, ty - 1), np.nan)
            target_age = float(age_prev) + 1 if pd.notna(age_prev) else np.nan
            rows.append({
                "PLAYER_ID": pid,
                "improve_streak_2y": streak,
                "usg_slope_held_ts": usg_held,
                "mpg_headroom": max(0.0, 36.0 - float(r.mpg)),
                "age_22_24": int(22 <= target_age <= 24) if pd.notna(target_age) else 0,
                "years_experience": sum(1 for y in n_prior.get(pid, []) if y < ty),
                "draft_pick": float(picks.get(pid, UNDRAFTED_PICK)),
            })
        f = pd.DataFrame(rows)
        f.insert(0, "SEASON", s)
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def breakout_labels(season_stats: pd.DataFrame, cfg: ScoringConfig | None = None) -> pd.DataFrame:
    """``[SEASON, PLAYER_ID, y_breakout]``: did realized fpts/g jump ≥ BREAKOUT_DELTA vs the
    prior season (prior season ≥ MIN_PRIOR_MINUTES — same convention as the mover eval)."""
    cfg = cfg or load_scoring()
    lines = _season_lines(season_stats, cfg)
    prev = lines[["PLAYER_ID", "yr", "fpts_pg", "MIN"]].copy()
    prev["yr"] += 1
    m = lines.merge(prev.rename(columns={"fpts_pg": "prior_fpts_pg", "MIN": "prior_min"}),
                    on=["PLAYER_ID", "yr"])
    m = m[m["prior_min"] >= MIN_PRIOR_MINUTES]
    m["y_breakout"] = ((m["fpts_pg"] - m["prior_fpts_pg"]) >= BREAKOUT_DELTA).astype(int)
    return m[["SEASON", "PLAYER_ID", "y_breakout"]]


def breakout_scores(
    feature_table: pd.DataFrame,
    labels: pd.DataFrame,
    target_season: str,
    params: dict | None = None,
) -> pd.DataFrame:
    """Walk-forward P(breakout in ``target_season``) per player: the classifier trains on
    (features, labels) from seasons strictly before the target, predicts on the target's
    feature block. Returns ``[PLAYER_ID, breakout_p]``."""
    from lightgbm import LGBMClassifier

    params = params or DEFAULT_CLF_PARAMS
    ty = _season_start(target_season)
    train = feature_table[feature_table["SEASON"].map(_season_start) < ty].merge(
        labels, on=["SEASON", "PLAYER_ID"])
    test = feature_table[feature_table["SEASON"] == target_season]
    if train.empty or test.empty:
        raise ValueError(f"breakout_scores: no train/test rows around {target_season!r}.")
    clf = LGBMClassifier(**params)
    clf.fit(train[BREAKOUT_FEATURES], train["y_breakout"])
    return pd.DataFrame({
        "PLAYER_ID": test["PLAYER_ID"].to_numpy(),
        "breakout_p": clf.predict_proba(test[BREAKOUT_FEATURES])[:, 1],
    })


DEFAULT_POLICY = dict(k=20, core=50, boost=40)


def apply_breakout_policy(
    board: pd.DataFrame,
    scores: pd.DataFrame,
    k: int = DEFAULT_POLICY["k"],
    core: int = DEFAULT_POLICY["core"],
    boost: int = DEFAULT_POLICY["boost"],
) -> pd.DataFrame:
    """Deterministic ceiling-stance re-rank: the ``k`` highest ``breakout_p`` players ranked
    below ``core`` move up ``boost`` ranks (never into the core). Adds ``breakout_p`` and
    ``breakout_flag`` columns; returns a re-sorted, re-numbered copy. The stable core
    (ranks 1..core) is untouched by construction — late-round picks chase option value."""
    out = board.merge(scores, on="PLAYER_ID", how="left")
    out["breakout_p"] = out["breakout_p"].fillna(0.0)
    eligible = out[out["rank"] > core]
    flagged = set(eligible.nlargest(k, "breakout_p")["PLAYER_ID"])
    out["breakout_flag"] = out["PLAYER_ID"].isin(flagged).astype(int)
    out["_key"] = np.where(out["breakout_flag"] == 1,
                           np.maximum(out["rank"] - boost, core + 0.5), out["rank"])
    out = out.sort_values(["_key", "rank"]).drop(columns="_key").reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out
