"""Rookie model: draft slot × landing spot (Step 9d / EXP-028, Stage-4 first cut).

Why: a player with no prior-season row simply isn't on the learned board — the bluntest gap
vs commercial systems. The D1.5 market seed closes the *visibility* hole; this module is the
first attempt to beat the market's naive ordering with a model. Research consensus: rookie
fantasy value ≈ **draft slot + landing-spot opportunity**; college-stat translation is a
later refinement, not a prerequisite.

Design choices (all from the implementation-plan spec):
  * **Cohort** = players whose first ``player_season_stats`` row is that season (the cache's
    own first season is excluded — everyone is "new" there). International/stash debuts count
    as rookies (they are, for fantasy purposes).
  * **Two targets only** — ``y_mpg`` and ``y_fpts_pm`` (fantasy points per minute under the
    scoring config), composed ``fpts_pg = mpg × fpts_pm``. Thirteen rate targets on ~1,000
    rows would overfit. **GP is never modeled** (EXP-004 applies doubly to players with no
    history): it is the empirical rookie-cohort mean by pick bucket, walk-forward.
  * **Landing spot** reuses the tested EXP-016b machinery: rookies are *injected into* the
    honest Oct-1 team map (their rookie-season primary team — a preseason fact for the vast
    majority; documented approximation) so ``context.vacated_features`` yields each rookie
    his team's position-group vacancy line. Positions come from the rookie-season roster
    listing (``allocation.pos_group_asof`` — a preseason fact, not an outcome).
  * **Baseline** (the gate's opponent) = pick order, given a point estimate via the
    walk-forward pick-bucket empirical mean — "rank rookies purely by pick" with the fairest
    possible value curve attached.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, load_scoring
from ._core import _season_start
from .breakout import _season_lines
from .context import season_before, vacated_features, VACATED_FEATURES

ROOKIE_FEATURES = [
    "overall_pick",        # 61 = undrafted sentinel
    "log_pick",
    "undrafted",
    "rookie_age",          # bio AGE in the rookie season
    "years_since_draft",   # 0 = drafted last June; >0 = draft-and-stash arrival
    "intl_flag",           # bio COUNTRY != USA
    "n_same_pos",          # roster crowding in his position group (Oct-1 map)
] + VACATED_FEATURES       # the team's same-pos vacancy line (EXP-016b machinery)

TARGETS = ["y_mpg", "y_fpts_pm"]

UNDRAFTED_PICK = 61
MIN_LABEL_MINUTES = 200.0   # same convention as the learned panel

# Pick buckets for the empirical GP curve and the baseline value curve.
PICK_BUCKETS = [(1, 5), (6, 14), (15, 30), (31, 60), (61, 61)]

DEFAULT_ROOKIE_PARAMS = dict(
    n_estimators=150, learning_rate=0.05, num_leaves=7, min_child_samples=20,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
    random_state=0, n_jobs=-1, verbosity=-1,
)


def pick_bucket(pick: float) -> str:
    for lo, hi in PICK_BUCKETS:
        if lo <= pick <= hi:
            return f"{lo}-{hi}"
    return f"{PICK_BUCKETS[-1][0]}-{PICK_BUCKETS[-1][1]}"


def rookie_cohorts(season_stats: pd.DataFrame) -> pd.DataFrame:
    """``[SEASON, PLAYER_ID]`` — each player's first cached season, excluding the cache's own
    first season (where "first row" means nothing)."""
    first = (
        season_stats.assign(yr=season_stats["SEASON"].map(_season_start))
        .groupby("PLAYER_ID")["yr"].min()
    )
    cache_first = int(first.min())
    rows = first[first > cache_first]
    return pd.DataFrame({
        "SEASON": [f"{y}-{str(y + 1)[-2:]}" for y in rows.to_numpy()],
        "PLAYER_ID": rows.index.to_numpy(),
    })


def _draft_facts(draft_history: pd.DataFrame) -> pd.DataFrame:
    """Per PERSON_ID: latest draft row (players are drafted once; keep last defensively)."""
    d = draft_history.drop_duplicates("PERSON_ID", keep="last")
    return pd.DataFrame({
        "PLAYER_ID": d["PERSON_ID"].astype(int).to_numpy(),
        "draft_year": pd.to_numeric(d["SEASON"], errors="coerce").to_numpy(),
        "overall_pick": pd.to_numeric(d["OVERALL_PICK"], errors="coerce").to_numpy(),
    })


def build_rookie_panel(
    season_stats: pd.DataFrame,
    bio: pd.DataFrame,
    draft_history: pd.DataFrame,
    transactions: pd.DataFrame,
    team_rosters: pd.DataFrame,
    cfg: ScoringConfig | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """``[SEASON, PLAYER_ID, PLAYER_NAME, *ROOKIE_FEATURES, y_mpg, y_fpts_pm, y_gp, min]``
    per rookie cohort. Labels are the rookie season's realized values (NaN below
    ``MIN_LABEL_MINUTES`` — kept in the frame so live/target cohorts still get features).

    Fold-safe: features read the draft fact sheet (static), bio age/country of the rookie
    season (preseason facts), and the S−1 stats + Oct-1 map (the EXP-016b contract). The
    only approximation is the rookie's team = his rookie-season primary team (mid-season
    rookie trades are rare; documented).
    """
    from .allocation import pos_group_asof, position_table
    from .rosters import preseason_roster_map

    cfg = cfg or load_scoring()
    cohorts = rookie_cohorts(season_stats)
    if seasons is not None:
        cohorts = cohorts[cohorts["SEASON"].isin(seasons)]

    lines = _season_lines(season_stats, cfg).set_index(["PLAYER_ID", "SEASON"])
    gp_of = season_stats.groupby(["PLAYER_ID", "SEASON"])["GP"].sum()
    names = season_stats.drop_duplicates("PLAYER_ID", keep="last").set_index("PLAYER_ID")["PLAYER_NAME"]
    facts = _draft_facts(draft_history).set_index("PLAYER_ID")
    b = bio.drop_duplicates(["PLAYER_ID", "SEASON"]).set_index(["PLAYER_ID", "SEASON"])
    pos_table = position_table(team_rosters)

    frames = []
    for s, grp in cohorts.groupby("SEASON", sort=True):
        prev = season_before(s)
        if prev not in set(season_stats["SEASON"]):
            continue
        ty = _season_start(s)
        pids = grp["PLAYER_ID"].to_numpy()

        # Rookie landing team = rookie-season primary team (preseason-fact approximation).
        rook_team = (
            season_stats[(season_stats["SEASON"] == s) & season_stats["PLAYER_ID"].isin(pids)]
            .groupby("PLAYER_ID")["TEAM_ABBREVIATION"].last()
        )
        team_map = preseason_roster_map(season_stats, transactions, s)
        team_map = pd.concat([
            team_map[~team_map["PLAYER_ID"].isin(pids)],
            pd.DataFrame({"PLAYER_ID": rook_team.index, "team": rook_team.to_numpy()}),
        ], ignore_index=True)
        pos_of = pos_group_asof(pos_table, s)
        vac = vacated_features(season_stats, team_map, prev, pos_of).set_index("PLAYER_ID")

        # Crowding: same-pos players on the mapped roster.
        tm = team_map.assign(pos=team_map["PLAYER_ID"].map(pos_of))
        crowd = tm.groupby(["team", "pos"])["PLAYER_ID"].size()

        rows = []
        for pid in pids:
            fact = facts.loc[pid] if pid in facts.index else None
            pick = float(fact["overall_pick"]) if fact is not None and pd.notna(fact["overall_pick"]) \
                else float(UNDRAFTED_PICK)
            dyear = float(fact["draft_year"]) if fact is not None and pd.notna(fact["draft_year"]) else ty
            age = b.loc[(pid, s), "AGE"] if (pid, s) in b.index else np.nan
            country = b.loc[(pid, s), "COUNTRY"] if (pid, s) in b.index else "USA"
            team = rook_team.get(pid)
            pos = pos_of.get(pid)
            line = lines.loc[(pid, s)] if (pid, s) in lines.index else None
            enough = line is not None and line["MIN"] >= MIN_LABEL_MINUTES
            row = {
                "SEASON": s, "PLAYER_ID": pid, "PLAYER_NAME": names.get(pid, ""),
                "overall_pick": pick, "log_pick": float(np.log(pick)),
                "undrafted": int(pick >= UNDRAFTED_PICK),
                "rookie_age": float(age) if pd.notna(age) else np.nan,
                "years_since_draft": max(0.0, ty - dyear),
                "intl_flag": int(str(country) not in ("USA", "")),
                "n_same_pos": float(crowd.get((team, pos), 0)) if team is not None else 0.0,
                "y_mpg": float(line["mpg"]) if enough else np.nan,
                "y_fpts_pm": float(line["fpts_pm"]) if enough else np.nan,
                "y_gp": float(gp_of.get((pid, s), np.nan)),
                "min": float(line["MIN"]) if line is not None else 0.0,
            }
            v = vac.loc[pid] if pid in vac.index else None
            for c in VACATED_FEATURES:
                row[c] = float(v[c]) if v is not None else 0.0
            rows.append(row)
        frames.append(pd.DataFrame(rows))
    if not frames:
        raise ValueError("build_rookie_panel: no rookie cohorts in range.")
    return pd.concat(frames, ignore_index=True)


def gp_by_pick_bucket(train: pd.DataFrame) -> pd.Series:
    """Empirical mean rookie GP per pick bucket from the training cohorts (never modeled)."""
    t = train.dropna(subset=["y_gp"]).copy()
    t["bucket"] = t["overall_pick"].map(pick_bucket)
    return t.groupby("bucket")["y_gp"].mean()


def project_rookies(
    panel: pd.DataFrame,
    target_season: str,
    params: dict | None = None,
) -> pd.DataFrame:
    """Walk-forward rookie board for ``target_season``: LGBM y_mpg × y_fpts_pm on cohorts
    strictly before the target, composed ``fpts_pg``; GP = training pick-bucket mean;
    ``fpts_total = fpts_pg × gp``. Returns the target cohort with predictions attached."""
    from lightgbm import LGBMRegressor

    params = params or DEFAULT_ROOKIE_PARAMS
    ty = _season_start(target_season)
    yrs = panel["SEASON"].map(_season_start)
    train = panel[(yrs < ty)].dropna(subset=TARGETS)
    test = panel[panel["SEASON"] == target_season].copy()
    if train.empty or test.empty:
        raise ValueError(f"project_rookies: no train/test cohorts around {target_season!r}.")

    preds = {}
    for tgt in TARGETS:
        m = LGBMRegressor(**params)
        m.fit(train[ROOKIE_FEATURES], train[tgt])
        preds[tgt] = m.predict(test[ROOKIE_FEATURES])
    test["mpg"] = np.clip(preds["y_mpg"], 0.0, 40.0)
    test["fpts_pm"] = np.clip(preds["y_fpts_pm"], 0.0, None)
    test["fpts_pg"] = test["mpg"] * test["fpts_pm"]

    gp_curve = gp_by_pick_bucket(train)
    test["gp"] = test["overall_pick"].map(lambda p: gp_curve.get(pick_bucket(p), gp_curve.mean()))
    test["fpts_total"] = test["fpts_pg"] * test["gp"]
    return test.sort_values("fpts_total", ascending=False).reset_index(drop=True)


def pick_order_baseline(panel: pd.DataFrame, target_season: str) -> pd.DataFrame:
    """The gate's opponent: rank purely by pick, valued at the walk-forward pick-bucket
    empirical mean fpts_pg/total (ties within a bucket broken by pick)."""
    ty = _season_start(target_season)
    yrs = panel["SEASON"].map(_season_start)
    train = panel[(yrs < ty)].dropna(subset=["y_mpg", "y_fpts_pm"]).copy()
    test = panel[panel["SEASON"] == target_season].copy()
    if train.empty or test.empty:
        raise ValueError(f"pick_order_baseline: no train/test cohorts around {target_season!r}.")
    train["bucket"] = train["overall_pick"].map(pick_bucket)
    train["fpts_pg"] = train["y_mpg"] * train["y_fpts_pm"]
    curve = train.groupby("bucket")["fpts_pg"].mean()
    gp_curve = gp_by_pick_bucket(train)

    test["fpts_pg"] = test["overall_pick"].map(lambda p: curve.get(pick_bucket(p), curve.mean()))
    test["gp"] = test["overall_pick"].map(lambda p: gp_curve.get(pick_bucket(p), gp_curve.mean()))
    test["fpts_total"] = test["fpts_pg"] * test["gp"]
    return test.sort_values("overall_pick").reset_index(drop=True)
