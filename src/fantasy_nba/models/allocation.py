"""Team-constrained minutes allocation (EXP-014 / implementation-plan Step 6).

The structural bet of the breakthrough plan (§1b): minutes are a **team-constrained
allocation** — 240 per game, divided over a specific roster by position and pecking order —
not a per-player time series. Every prior minutes treatment (v2m's aging trend, EXP-009's
per-player context covariates) ignores both the 240-minute budget and *who specifically*
competes for the vacated minutes.

Layers in this module:

* **Feature / normalization layer** (unit-testable without data): ``position_group``,
  ``allocation_features`` (depth-chart math), ``rookie_reserve``, ``normalize_shares``.
* **Share model layer** (Step 6.2, needs the historical rosters pull): target
  ``y_min_share`` = player season MIN / his primary team's season total MIN
  (season-length-robust by construction); ``build_share_panel`` / ``fit_share_model`` /
  ``predict_shares``. Wired into ``project_learned(minutes_mode="allocation")``, which swaps
  **only** the minutes layer — rates and GP stay on the regression path.

Position groups are deliberately coarse (guard vs big): roster POSITION strings are hybrid
and inconsistent ("G-F", "F-C"), and finer buckets go sparse. Unmapped strings raise loudly
rather than silently polluting the depth chart. Positions are looked up as-of the target
season (most recent roster season ≤ target), falling back to the earliest later roster for
players first seen afterwards — a static-attribute lookup, not an outcome.

Known honesty caveat (carried from the step spec): the backtest team map is
``context.target_team_map`` (end-of-season teams) until EXP-016 supplies true preseason
rosters, so mid-season movers flatter the features slightly — same caveat as EXP-009.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ._core import _season_start
from .context import season_before, target_team_map, team_context_features

ALLOC_FEATURES = [
    "own_prev_share",             # own share of prior team's minutes (role he's coming from)
    "pos_group",                  # 0 = guard, 1 = big
    "same_pos_returning_share",   # Σ prior-team shares of same-pos teammates also on the target roster
    "same_pos_vacated_share",     # Σ prior-team shares of same-pos players who left the roster
    "depth_rank",                 # rank of own prior minutes among same-pos players on the target roster
    "n_same_pos",                 # roster crowding in his position group
]

_GUARD = {"G", "G-F"}
_BIG = {"F", "F-C", "F-G", "C", "C-F"}


def position_group(position: str) -> int:
    """Map a roster POSITION string to 0 (guard) / 1 (big). Raises on anything unmapped so a
    new NBA-API position string is a loud failure, not a silent depth-chart corruption."""
    p = str(position).strip().upper()
    if p in _GUARD:
        return 0
    if p in _BIG:
        return 1
    raise ValueError(f"Unmapped roster POSITION {position!r} — extend _GUARD/_BIG in allocation.py")


def _prev_team_minutes(season_stats: pd.DataFrame, season: str) -> pd.DataFrame:
    """One row per player for ``season``: primary (last) team + minutes (context.py convention)."""
    s = season_stats[season_stats["SEASON"] == season]
    return (
        s.groupby("PLAYER_ID", as_index=False)
        .agg(prev_team=("TEAM_ABBREVIATION", "last"), prev_min=("MIN", "sum"))
    )


def allocation_features(
    season_stats: pd.DataFrame,
    roster_map: pd.DataFrame,
    prev_season: str,
) -> pd.DataFrame:
    """Depth-chart / opportunity features for every player on a target roster.

    ``roster_map`` is ``[PLAYER_ID, team, pos_group]`` — the target-season roster with the
    coarse position group (from historical ``team_rosters`` in backtests, live rosters in
    production; strict preseason rosters once EXP-016 lands). ``season_stats`` must contain
    ``prev_season`` (whose minutes are being re-allocated). Returns
    ``[PLAYER_ID] + ALLOC_FEATURES``; players with no prior season get share/rank neutrals
    (0 shares; depth_rank = n_same_pos, i.e. bottom of their positional stack).

    No-leakage contract: prior-season minutes + a target-season roster fact — nothing dated
    inside the target season (same contract as ``context.py``).
    """
    prev = _prev_team_minutes(season_stats, prev_season)
    team_total = prev.groupby("prev_team")["prev_min"].sum().rename("prev_team_total")

    r = roster_map[["PLAYER_ID", "team", "pos_group"]].copy()
    r = r.merge(prev, on="PLAYER_ID", how="left")
    r = r.merge(team_total, left_on="prev_team", right_index=True, how="left")
    r["own_prev_share"] = (r["prev_min"] / r["prev_team_total"]).fillna(0.0)
    r["prev_min"] = r["prev_min"].fillna(0.0)

    # Prior-season rotation of each *target* team, split into returning (on the target roster)
    # vs vacated (gone), by position group. A departed player's pos_group comes from the prior
    # roster in a full pipeline; until the historical-roster pull exists, callers may pass a
    # roster_map that also covers departed players — rows whose team is NaN in roster terms.
    prior_rot = prev.merge(team_total, left_on="prev_team", right_index=True, how="left")
    prior_rot["share"] = prior_rot["prev_min"] / prior_rot["prev_team_total"]
    pos_of = roster_map.set_index("PLAYER_ID")["pos_group"]
    prior_rot["pos_group"] = prior_rot["PLAYER_ID"].map(pos_of)
    roster_of = roster_map.set_index("PLAYER_ID")["team"]
    prior_rot["target_team"] = prior_rot["PLAYER_ID"].map(roster_of)
    prior_rot["returning"] = prior_rot["target_team"] == prior_rot["prev_team"]

    rows = []
    for (team, pos), grp in r.groupby(["team", "pos_group"]):
        # Same-pos prior-season rotation of this target team:
        rot = prior_rot[(prior_rot["prev_team"] == team) & (prior_rot["pos_group"] == pos)]
        returning_share = rot.loc[rot["returning"], "share"].sum()
        vacated_share = rot.loc[~rot["returning"], "share"].sum()
        # Depth rank among same-pos players on this roster, by prior-season minutes anywhere.
        order = grp["prev_min"].rank(ascending=False, method="min")
        for idx, row in grp.iterrows():
            own_returning = row["own_prev_share"] if row["prev_team"] == team else 0.0
            rows.append({
                "PLAYER_ID": row["PLAYER_ID"],
                "own_prev_share": row["own_prev_share"],
                "pos_group": pos,
                "same_pos_returning_share": max(returning_share - own_returning, 0.0),
                "same_pos_vacated_share": vacated_share,
                "depth_rank": int(order.loc[idx]),
                "n_same_pos": len(grp),
            })
    return pd.DataFrame(rows, columns=["PLAYER_ID"] + ALLOC_FEATURES)


def rookie_reserve(season_stats: pd.DataFrame) -> float:
    """League-average share of a team's season minutes played by players with **no
    prior-season row** (rookies / returnees the panel can't model). Used to leave headroom
    when normalizing predicted shares — measured, not guessed. Computed over every season
    with a predecessor in ``season_stats``."""
    seasons = sorted(season_stats["SEASON"].unique(), key=_season_start)
    shares = []
    for prev_s, s in zip(seasons, seasons[1:]):
        cur = season_stats[season_stats["SEASON"] == s]
        known = set(season_stats.loc[season_stats["SEASON"] == prev_s, "PLAYER_ID"])
        by_team = cur.groupby("TEAM_ABBREVIATION").apply(
            lambda g: g.loc[~g["PLAYER_ID"].isin(known), "MIN"].sum() / max(g["MIN"].sum(), 1e-9),
            include_groups=False,
        )
        shares.extend(by_team.tolist())
    if not shares:
        raise ValueError("rookie_reserve needs at least two consecutive seasons.")
    return float(np.mean(shares))


def normalize_shares(pred: pd.DataFrame, reserve: float) -> pd.DataFrame:
    """Enforce the budget: scale predicted raw shares so each team's modeled players sum to
    ``1 − reserve`` (the rest is the rookie/unmodeled headroom).

    ``pred`` is ``[PLAYER_ID, team, share_pred]``; returns it with ``share_norm`` added.
    Callers should also inspect the *pre*-normalization team sums (the Step-6 sanity print):
    a mean far from ``1 − reserve`` means the raw share model is mis-calibrated — investigate
    before trusting any A/B built on top.
    """
    out = pred.copy()
    team_sum = out.groupby("team")["share_pred"].transform("sum").replace(0, np.nan)
    out["share_norm"] = (out["share_pred"] * (1.0 - reserve) / team_sum).fillna(0.0)
    return out


# ------------------------------------------------------------------ share model (Step 6.2)

# The full share-model feature set: depth-chart features + role size / durability / age +
# the EXP-009 team-level pair (kept per the step spec) + foul rate (critique §5.3 — a
# stable mechanical minutes cap; foul-prone players cannot hold heavy minutes).
ALLOC_MODEL_FEATURES = ALLOC_FEATURES + [
    "prev_mpg", "prev_gp", "target_age",
    "team_vacated_min_norm", "team_turnover_share",
    "pf_per_min",
]


def position_table(team_rosters: pd.DataFrame) -> pd.DataFrame:
    """``[PLAYER_ID, SEASON, pos_group]`` from the historical rosters pull (Step 6.1).

    Blank/NaN POSITION rows are dropped (rare administrative rows); any *non-blank* unmapped
    string still raises via ``position_group``.
    """
    t = team_rosters[["PLAYER_ID", "SEASON", "POSITION"]].copy()
    pos = t["POSITION"].astype(str).str.strip().str.upper()
    t = t[~pos.isin(["", "NAN", "NONE"])]
    t["pos_group"] = t["POSITION"].map(position_group)
    return t[["PLAYER_ID", "SEASON", "pos_group"]].drop_duplicates(["PLAYER_ID", "SEASON"])


def pos_group_asof(pos_table: pd.DataFrame, season: str) -> pd.Series:
    """PLAYER_ID → pos_group as of ``season``: most recent roster season ≤ ``season``,
    falling back to the earliest later roster (positions are near-static; using a later
    roster for a player's static attribute is noted, not hidden)."""
    y = _season_start(season)
    pt = pos_table.assign(_y=pos_table["SEASON"].map(_season_start)).sort_values("_y")
    past = pt[pt["_y"] <= y].groupby("PLAYER_ID")["pos_group"].last()
    later = pt[pt["_y"] > y].groupby("PLAYER_ID")["pos_group"].first()
    return past.combine_first(later)


def share_labels(season_stats: pd.DataFrame, season: str, min_minutes: float = 0.0) -> pd.DataFrame:
    """``[PLAYER_ID, y_min_share]`` for ``season``: the player's total season minutes over his
    primary team's season total minutes (``_primary_team_minutes`` convention).

    Default ``min_minutes=0``: unlike the rate targets, a tiny-minutes share is a perfectly
    valid label, and filtering small labels *selects on the outcome* — it taught the model
    that fringe players get real minutes (measured: pre-norm team sums 1.21 vs 0.89 with the
    200-min filter, 1.05 without)."""
    s = season_stats[season_stats["SEASON"] == season]
    team_total = s.groupby("TEAM_ABBREVIATION")["MIN"].sum()
    p = _prev_team_minutes(season_stats, season).rename(
        columns={"prev_team": "team", "prev_min": "min"}
    )
    p = p[p["min"] >= min_minutes].copy()
    p["y_min_share"] = p["min"] / p["team"].map(team_total)
    return p[["PLAYER_ID", "y_min_share"]]


def _prev_player_stats(season_stats: pd.DataFrame, prev_season: str) -> pd.DataFrame:
    """Per player for ``prev_season``: MPG, GP, PF per minute (the non-depth-chart share
    features), plus age for the target-age derivation."""
    s = season_stats[season_stats["SEASON"] == prev_season]
    g = s.groupby("PLAYER_ID", as_index=False).agg(
        prev_min=("MIN", "sum"), prev_gp_raw=("GP", "sum"), prev_pf=("PF", "sum"),
        prev_age=("AGE", "max"),
    )
    g["prev_mpg"] = g["prev_min"] / g["prev_gp_raw"].replace(0, np.nan)
    g["prev_gp"] = g["prev_gp_raw"]
    g["pf_per_min"] = g["prev_pf"] / g["prev_min"].replace(0, np.nan)
    g["target_age"] = g["prev_age"] + 1.0
    return g[["PLAYER_ID", "prev_mpg", "prev_gp", "pf_per_min", "target_age"]]


def share_features_for(
    season_stats: pd.DataFrame,
    team_map: pd.DataFrame,
    pos_table: pd.DataFrame,
    target_season: str,
) -> pd.DataFrame:
    """The full share-model feature frame for one target season.

    ``season_stats`` needs only seasons ≤ the season before ``target_season`` (the features
    read ``season_before(target_season)``); ``team_map`` is ``[PLAYER_ID, team]`` — the
    target-season assignment (a preseason roster fact). Players without a known position
    drop out (callers fall back to the regression minutes for them). Returns
    ``[PLAYER_ID, team] + ALLOC_MODEL_FEATURES``.
    """
    prev_season = season_before(target_season)
    pos = pos_group_asof(pos_table, target_season)
    roster_map = team_map[["PLAYER_ID", "team"]].copy()
    roster_map["pos_group"] = roster_map["PLAYER_ID"].map(pos)
    roster_map = roster_map.dropna(subset=["pos_group"]).astype({"pos_group": int})
    # The modeled universe = players with a prior-season row — exactly the learned board's
    # universe (Marcel aggregates can't project rookies either). Everyone else IS the
    # ``rookie_reserve`` headroom; keeping them here would double-count it (measured: the
    # pre-norm team sums only center on 1 − reserve once this filter is in).
    prev_ids = set(season_stats.loc[season_stats["SEASON"] == prev_season, "PLAYER_ID"])
    roster_map = roster_map[roster_map["PLAYER_ID"].isin(prev_ids)]

    feats = allocation_features(season_stats, roster_map, prev_season)
    ctx = team_context_features(season_stats, roster_map[["PLAYER_ID", "team"]], prev_season)
    prev = _prev_player_stats(season_stats, prev_season)

    out = roster_map[["PLAYER_ID", "team"]].merge(
        feats, on="PLAYER_ID", how="inner"
    ).merge(
        ctx[["PLAYER_ID", "team_vacated_min_norm", "team_turnover_share"]],
        on="PLAYER_ID", how="left",
    ).merge(prev, on="PLAYER_ID", how="left")
    # Neutral fills: no prior season -> rookie-ish newcomer (features say "bottom of stack").
    fills = {"team_vacated_min_norm": 0.0, "team_turnover_share": 0.0,
             "prev_mpg": 0.0, "prev_gp": 0.0, "pf_per_min": 0.0}
    for col, v in fills.items():
        out[col] = out[col].fillna(v)
    out["target_age"] = out["target_age"].fillna(out["target_age"].median())
    return out


def build_share_panel(
    season_stats: pd.DataFrame,
    pos_table: pd.DataFrame,
    min_prior_seasons: int = 2,
    min_label_minutes: float = 0.0,
) -> pd.DataFrame:
    """Stack (share features as-of-S, ``y_min_share`` in S) over every eligible season S —
    the same eligibility rule as ``learned.build_panel``. The team map per training season
    is ``context.target_team_map`` (end-of-season approximation; see module docstring)."""
    seasons = sorted(season_stats["SEASON"].unique(), key=_season_start)
    frames = []
    for s in seasons:
        prior = season_stats[season_stats["SEASON"].map(_season_start) < _season_start(s)]
        if prior["SEASON"].nunique() < min_prior_seasons:
            continue
        team_map = target_team_map(season_stats, s)
        feats = share_features_for(season_stats, team_map, pos_table, s)
        labels = share_labels(season_stats, s, min_minutes=min_label_minutes)
        merged = feats.merge(labels, on="PLAYER_ID", how="inner")
        if not merged.empty:
            merged["label_season"] = s
            frames.append(merged)
    if not frames:
        raise ValueError("Empty share panel — need at least a few seasons of history.")
    return pd.concat(frames, ignore_index=True)


def fit_share_model(panel: pd.DataFrame, params: dict):
    """One LightGBM regressor on the raw share target (the step amendment says try raw
    first; switch to logit only if raw mis-calibrates — judged by the Σ-share sanity)."""
    from lightgbm import LGBMRegressor

    model = LGBMRegressor(**params)
    model.fit(panel[ALLOC_MODEL_FEATURES], panel["y_min_share"])
    return model


def predict_shares(model, feats: pd.DataFrame, reserve: float) -> pd.DataFrame:
    """Predict + budget-normalize shares for one target season's feature frame.

    Returns ``[PLAYER_ID, team, share_pred, share_norm]`` — ``share_pred`` is the raw model
    output (clipped ≥ 0; the Σ-share sanity reads it), ``share_norm`` sums to ``1 − reserve``
    per team.
    """
    out = feats[["PLAYER_ID", "team"]].copy()
    out["share_pred"] = np.clip(model.predict(feats[ALLOC_MODEL_FEATURES]), 0.0, None)
    return normalize_shares(out, reserve)


# ------------------------------------------------- Step 17 (EXP-031): the budget layer
#
# The honest re-entry after EXP-014: MPG stays the regression target (the stable quantity);
# the 240-minute identity returns as (a) depth-chart *features* into the y_mpg model — the
# ledger-sanctioned path — and (b) a soft post-hoc reconciliation in HEADROOM space, where
# predicted GP enters only as a bounded multiplicative weight, never a divisor.

TEAM_BUDGET_MIN = 240.0 * 82          # a team-season's player-minutes supply
MPG_HEADROOM_CAP = 40.0               # headroom anchor: stars near it barely move
DEPTH_FEATURES = ALLOC_FEATURES + ["pf_per_min"]


def depth_feature_table(
    season_stats: pd.DataFrame,
    transactions: pd.DataFrame,
    team_rosters: pd.DataFrame,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """SEASON-keyed ``[SEASON, PLAYER_ID] + DEPTH_FEATURES`` — the EXP-031(a) feature group.

    Per season: the honest Oct-1 roster map (``rosters.preseason_roster_map``) + as-of
    position groups + prior-season minutes → ``allocation_features`` depth-chart math, plus
    ``pf_per_min`` (critique §5.3's mechanical minutes cap) from the prior season. Same
    SEASON-keyed contract as ``rosters.vacated_feature_table`` (build once, slice per fold);
    players off the Oct-1 map get no row — unsigned on draft day is honest missingness.
    """
    from .rosters import preseason_roster_map

    pos_table = position_table(team_rosters)
    all_seasons = sorted(season_stats["SEASON"].unique(), key=_season_start)
    seasons = list(seasons) if seasons is not None else all_seasons[1:]
    frames = []
    for s in seasons:
        prev_s = season_before(s)
        if prev_s not in all_seasons:
            continue
        rmap = preseason_roster_map(season_stats, transactions, s)[["PLAYER_ID", "team"]].copy()
        rmap["pos_group"] = rmap["PLAYER_ID"].map(pos_group_asof(pos_table, s))
        rmap = rmap.dropna(subset=["pos_group"])
        feats = allocation_features(season_stats, rmap, prev_s)
        prev = season_stats[season_stats["SEASON"] == prev_s].groupby("PLAYER_ID", as_index=False).agg(
            _pf=("PF", "sum"), _min=("MIN", "sum"))
        prev["pf_per_min"] = prev["_pf"] / prev["_min"].replace(0, np.nan)
        feats = feats.merge(prev[["PLAYER_ID", "pf_per_min"]], on="PLAYER_ID", how="left")
        feats["pf_per_min"] = feats["pf_per_min"].fillna(0.0)  # no prior season = no foul rate
        feats.insert(0, "SEASON", s)
        frames.append(feats)
    if not frames:
        raise ValueError("depth_feature_table: no season with a predecessor in season_stats.")
    return pd.concat(frames, ignore_index=True)


def budget_table(board: pd.DataFrame, roster_map: pd.DataFrame, reserve: float) -> pd.DataFrame:
    """The 17.1 diagnostic: each target team's implied share of its minutes supply.

    ``B_team = Σ_i mpg_i × gp_i / (240 × 82)`` over the board's players mapped to the team —
    predicted GP enters multiplicatively (bounded 0–1 as a fraction of 82), never as a
    divisor. ``target = 1 − reserve`` (the unmodeled/rookie headroom is real supply we don't
    project). Returns ``[team, n, B_team, target, overshoot]`` — the breakthrough plan's
    "teams silently sum to 260+" claim, finally measured.
    """
    m = board.merge(roster_map[["PLAYER_ID", "team"]], on="PLAYER_ID", how="inner")
    g = m.groupby("team").apply(
        lambda x: pd.Series({"n": len(x), "B_team": float((x["mpg"] * x["gp"]).sum()) / TEAM_BUDGET_MIN}),
        include_groups=False,
    ).reset_index()
    g["n"] = g["n"].astype(int)
    g["target"] = 1.0 - reserve
    g["overshoot"] = g["B_team"] - g["target"]
    return g


def reconcile_minutes(
    board: pd.DataFrame,
    roster_map: pd.DataFrame,
    reserve: float,
    lam: float,
    cfg=None,
) -> pd.DataFrame:
    """EXP-031(b): soft budget reconciliation of a projection board, in headroom space.

    Per team, the expected budget gap ``G = (1 − reserve) × 240 × 82 − Σ mpg_i × gp_i`` is
    distributed as ``Δmpg_i = λ × G × h_i / Σ_j h_j × gp_j`` with headroom
    ``h_i = max(MPG_HEADROOM_CAP − mpg_i, 0)`` — fringe minutes flex, 36-minute stars barely
    move (the direct answer to EXP-014's proportional-normalization star tax), and GP is
    only ever a multiplicative weight. ``λ = 0`` is the identity (the A/B control); off-map
    players are untouched. Per-game stats rescale with the minutes ratio and ``fpts_pg``
    re-scores through ``cfg`` when given (bonuses are non-linear); MPG clips to [0, 42].
    Adds a ``recon_mpg`` audit column (the applied Δ, 0 elsewhere).
    """
    from ..scoring import score_frame

    out = board.copy()
    out["recon_mpg"] = 0.0
    if lam == 0.0:
        return out
    team_of = roster_map.set_index("PLAYER_ID")["team"]
    teams = out["PLAYER_ID"].map(team_of)
    mpg = out["mpg"].to_numpy(dtype=float)
    gp = out["gp"].to_numpy(dtype=float)
    h = np.maximum(MPG_HEADROOM_CAP - mpg, 0.0)
    delta = np.zeros(len(out))
    for team, idx in out.groupby(teams).groups.items():
        loc = out.index.get_indexer(idx)
        denom = float((h[loc] * gp[loc]).sum())
        if denom <= 0:
            continue
        gap = (1.0 - reserve) * TEAM_BUDGET_MIN - float((mpg[loc] * gp[loc]).sum())
        delta[loc] = lam * gap * h[loc] / denom
    new_mpg = np.clip(mpg + delta, 0.0, 42.0)
    touched = ~np.isclose(new_mpg, mpg)
    if touched.any():
        ratio = np.where(mpg > 0, new_mpg / np.where(mpg > 0, mpg, 1.0), 1.0)
        from ._core import COUNTING
        for canon in COUNTING:
            out.loc[touched, canon] = (out.loc[touched, canon].astype(float)
                                       * ratio[touched]).round(2)
        out.loc[touched, "recon_mpg"] = np.round(new_mpg[touched] - mpg[touched], 2)
        out.loc[touched, "mpg"] = np.round(new_mpg[touched], 1)
        if cfg is not None:
            out.loc[touched, "fpts_pg"] = score_frame(out.loc[touched], cfg).round(2)
            out.loc[touched, "fpts_total"] = (out.loc[touched, "fpts_pg"]
                                              * out.loc[touched, "gp"]).round(1)
            out = out.sort_values("fpts_total", ascending=False).reset_index(drop=True)
            out["rank"] = range(1, len(out) + 1)
    return out


def mean_team_total_minutes(season_stats: pd.DataFrame) -> float:
    """Average team-season total minutes over the given (training) seasons — the scale that
    converts a normalized share into projected season minutes."""
    per_team = season_stats.groupby(["SEASON", "TEAM_ABBREVIATION"])["MIN"].sum()
    return float(per_team.mean())
