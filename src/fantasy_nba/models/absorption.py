"""Vacated-minutes absorption + live OUT-redistribution (EXP-030 / implementation-plan Step 16).

Why this exists
---------------
When a rotation player is ruled OUT, the as-of board reacts only through the EWMA form
features — i.e. *after* his teammates' elevated minutes show up in box scores, a ~1–2 week
lag. This module makes the response predictive: it **fits, from history, who absorbs an
absent player's minutes** and applies that flow to the board the day the news breaks. It is
the EXP-018 re-gate checklist's "OUT-tonight / live teammate-vacated minutes" item, built as
a board *layer* (applies instantly, separately scoreable) rather than a model feature.

Model
-----
Training rows come straight from the game logs (no injury feed needed — absence is absence):
for every (team, game) with ≥ 1 **absent rotation player** (appeared for that team within the
trailing ``RECENT_DAYS``, trailing-form MPG ≥ ``MIN_ROTATION_MPG``, not in tonight's box),
each active teammate with an established baseline contributes one row:

    delta_min_j = MIN_j(tonight) − base_mpg_j(strictly pre-game)
                = Σ_o  θ[same_pos(o,j), tier(j)] × vacated_mpg_o  + intercept + ε

Attribution is **joint** (all simultaneous absentees enter one regression row — never
pairwise-naive), blowout games (|margin| ≥ ``BLOWOUT_MARGIN``, from ``team_game_logs``) are
excluded, and θ ≥ 0 is fit by bounded least squares over 6 cells: {same-position,
cross-position} × {starter, rotation, fringe} teammate tiers. A parallel head fits the
per-game FGA (shot-share) absorption on the same cells. Reality anchor: the fitted tiers
should land near the DFS folk numbers (same-pos backup absorbs the plurality; 2–5 min
spillover elsewhere) — wild divergence is a bug, not a discovery.

Application (:func:`redistribute_board`): for each OUT player, his projected ROS MPG flows
to same-team teammates by the fitted weights, **prorated** by the fraction of the remaining
season he is expected to miss; per-game stats recompose via each teammate's own rates
(re-scored through the scoring config); everyone untouched keeps byte-identical values. The
OUT player himself is handled by ``asof.apply_status_overrides`` (GP cap) — this layer is
that one's missing other half.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring import ScoringConfig, score_frame
from ._core import COUNTING
from .asof import _with_dates
from .injuries import SEVERE_RE

# Absence/rotation thresholds (dataset construction and application share them).
MIN_ROTATION_MPG = 15.0   # an absent sub-rotation player vacates no signal worth modeling
RECENT_DAYS = 14          # "on the roster tonight" = appeared for the team this recently
BASELINE_GAMES = 10       # trailing window for pre-game baselines / absent-player form
MIN_BASELINE_GAMES = 3    # teammate rows need an established baseline
BLOWOUT_MARGIN = 25.0     # |final margin| >= this -> garbage time corrupts absorption
MPG_CAP = 42.0            # post-redistribution cap (mirrors the learned model's clip)
MIN_REMAINING_DAYS = 7    # an open spell is never projected to end tomorrow

# Teammate tiers by pre-game baseline MPG: fringe < 15 <= rotation < 25 <= starter.
TIER_EDGES = (15.0, 25.0)
TIERS = ("fringe", "rotation", "starter")
CELL_COLS = [f"vac_sp{sp}_{t}" for sp in (1, 0) for t in TIERS]


def _tier(mpg: float | np.ndarray) -> np.ndarray:
    return np.digitize(mpg, TIER_EDGES)


def _cell(same_pos: int, tier: int) -> str:
    return f"vac_sp{int(same_pos)}_{TIERS[int(tier)]}"


def absorption_dataset(
    game_logs: pd.DataFrame,
    team_logs: pd.DataFrame | None = None,
    pos_map: dict | pd.Series | None = None,
    min_rotation_mpg: float = MIN_ROTATION_MPG,
    recent_days: int = RECENT_DAYS,
    blowout_margin: float = BLOWOUT_MARGIN,
) -> pd.DataFrame:
    """One row per (active teammate, team-game-with-absence): the joint-attribution frame.

    Columns: identity (``season, GAME_ID, team, PLAYER_ID``), targets ``delta_min`` /
    ``delta_fga`` (tonight minus strictly-pre-game trailing baseline), and the 6 ``CELL_COLS``
    regressors (Σ of absent players' trailing-form MPG landing in that cell) plus their
    ``_fga`` twins (Σ of absent players' trailing-form FGA/game). ``pos_map`` maps
    PLAYER_ID → position group (0=guard, 1=big); pairs with an unknown position count as
    cross-position (conservative). ``team_logs`` supplies final margins for the blowout
    exclusion; games without a margin row are kept.
    """
    gl = _with_dates(game_logs)
    if pos_map is None:
        pos_map = {}
    elif isinstance(pos_map, pd.Series):
        pos_map = pos_map.to_dict()

    margins: dict = {}
    if team_logs is not None:
        for gid, team, pm in team_logs[["GAME_ID", "TEAM_ABBREVIATION", "PLUS_MINUS"]].itertuples(index=False):
            margins[(gid, team)] = abs(float(pm))

    rows: list[dict] = []
    for season, gl_s in gl.groupby("SEASON"):
        h = gl_s.sort_values("_date").copy()
        grp = h.groupby("PLAYER_ID")
        h["games_prior"] = grp.cumcount()
        def _roll(col: str, shift: bool) -> pd.Series:
            r = grp[col].transform(lambda s: s.rolling(BASELINE_GAMES, min_periods=1).mean())
            return r.groupby(h["PLAYER_ID"]).shift(1) if shift else r

        h["form_mpg"] = _roll("MIN", shift=False)       # trailing form incl. tonight
        h["form_fga_pg"] = _roll("FGA", shift=False)
        h["base_mpg"] = _roll("MIN", shift=True)        # strictly pre-game baseline
        h["base_fga_pg"] = _roll("FGA", shift=True)

        for team, th in h.groupby("TEAM_ABBREVIATION"):
            last_seen: dict = {}  # pid -> (date, form_mpg, form_fga_pg)
            for gid in th.drop_duplicates("GAME_ID")["GAME_ID"]:
                box = th[th["GAME_ID"] == gid]
                d = box["_date"].iloc[0]
                tonight = set(box["PLAYER_ID"])
                absent = [
                    (pid, fmpg, ffga)
                    for pid, (dt, fmpg, ffga) in last_seen.items()
                    if pid not in tonight
                    and (d - dt).days <= recent_days
                    and fmpg >= min_rotation_mpg
                ]
                margin = margins.get((gid, team))
                if absent and (margin is None or margin < blowout_margin):
                    for r in box.itertuples(index=False):
                        if r.games_prior < MIN_BASELINE_GAMES or pd.isna(r.base_mpg):
                            continue
                        row = {
                            "season": season, "GAME_ID": gid, "team": team,
                            "PLAYER_ID": r.PLAYER_ID,
                            "delta_min": float(r.MIN) - float(r.base_mpg),
                            "delta_fga": float(r.FGA) - float(r.base_fga_pg),
                            "n_out": len(absent),
                        }
                        for c in CELL_COLS:
                            row[c] = 0.0
                            row[f"{c}_fga"] = 0.0
                        pos_j = pos_map.get(r.PLAYER_ID)
                        tier_j = int(_tier(float(r.base_mpg)))
                        for pid_o, fmpg_o, ffga_o in absent:
                            pos_o = pos_map.get(pid_o)
                            sp = int(pos_o is not None and pos_j is not None
                                     and not pd.isna(pos_o) and not pd.isna(pos_j)
                                     and pos_o == pos_j)
                            c = _cell(sp, tier_j)
                            row[c] += fmpg_o
                            row[f"{c}_fga"] += ffga_o
                        rows.append(row)
                for r in box.itertuples(index=False):
                    last_seen[r.PLAYER_ID] = (d, float(r.form_mpg), float(r.form_fga_pg))
    cols = (["season", "GAME_ID", "team", "PLAYER_ID", "delta_min", "delta_fga", "n_out"]
            + [c for cc in CELL_COLS for c in (cc, f"{cc}_fga")])
    return pd.DataFrame(rows, columns=cols)


def fit_absorption(dataset: pd.DataFrame) -> dict:
    """Bounded least squares (θ ∈ [0, 1] per cell, free intercept) on the joint-attribution
    frame — the minutes head on ``delta_min`` vs the ``CELL_COLS``, the shot head on
    ``delta_fga`` vs their ``_fga`` twins. Returns the weights dict
    ``{"theta", "intercept", "theta_fga", "intercept_fga", "n_rows", "n_team_games"}``.
    """
    from scipy.optimize import lsq_linear

    if dataset.empty:
        raise ValueError("empty absorption dataset — nothing to fit")

    def _fit(target: str, cols: list[str]) -> tuple[dict, float]:
        A = np.column_stack([dataset[cols].to_numpy(dtype=float),
                             np.ones(len(dataset))])
        y = dataset[target].to_numpy(dtype=float)
        res = lsq_linear(A, y, bounds=([0.0] * len(cols) + [-np.inf],
                                       [1.0] * len(cols) + [np.inf]))
        return dict(zip(CELL_COLS, res.x[:len(cols)])), float(res.x[-1])

    theta, intercept = _fit("delta_min", CELL_COLS)
    theta_fga, intercept_fga = _fit("delta_fga", [f"{c}_fga" for c in CELL_COLS])
    return {
        "theta": theta, "intercept": intercept,
        "theta_fga": theta_fga, "intercept_fga": intercept_fga,
        "n_rows": int(len(dataset)),
        "n_team_games": int(dataset.groupby(["season", "GAME_ID", "team"]).ngroups),
    }


def absorption_table(weights: dict) -> pd.DataFrame:
    """The fitted tiers as a printable table (the ledger's reality-anchor vs the DFS folk
    numbers: same-pos backup absorbs the plurality, 2–5 min spillover elsewhere)."""
    rows = []
    for sp in (1, 0):
        for t, tier in enumerate(TIERS):
            c = _cell(sp, t)
            rows.append({
                "relation": "same_pos" if sp else "cross_pos", "teammate_tier": tier,
                "theta_min": weights["theta"][c],
                "mpg_if_30_vacated": 30.0 * weights["theta"][c],
                "theta_fga": weights["theta_fga"][c],
            })
    return pd.DataFrame(rows)


# --- application-side inputs -------------------------------------------------------------

def team_map_asof(gl_season: pd.DataFrame, T: pd.Timestamp) -> pd.Series:
    """PLAYER_ID → team from each player's most recent game on/before ``T`` (the board
    carries no team column — this is the honest as-of source; players yet to appear are
    absent from the map and excluded from redistribution)."""
    sub = gl_season[gl_season["_date"] <= T]
    return sub.sort_values("_date").groupby("PLAYER_ID")["TEAM_ABBREVIATION"].last()


def spell_duration_medians(spells: pd.DataFrame) -> dict:
    """Median historical spell length by severity class (Step-7 ``SEVERE_RE`` on the notes)
    — fit on **training** spells only; the backtest's honest stand-in for "no timetable"."""
    sev = spells["notes"].astype(str).str.contains(SEVERE_RE)
    return {
        "severe": float(spells.loc[sev, "days"].median()) if sev.any() else 60.0,
        "normal": float(spells.loc[~sev, "days"].median()) if (~sev).any() else 14.0,
    }


def out_events_asof(spells: pd.DataFrame, T: pd.Timestamp, medians: dict | None = None) -> pd.DataFrame:
    """Players OUT at ``T`` (open spells) with an estimated return date.

    With ``medians`` (the honest mode — always in backtests): expected remaining absence =
    ``max(median_by_class − elapsed, MIN_REMAINING_DAYS)``; at T we know a spell is open but
    never its true end. Without ``medians`` the spell's recorded end is used — an **oracle**
    acceptable only live (where ``out_until`` comes from actual news via overrides.yaml).
    Returns ``[PLAYER_ID, out_until]``, one row per player (longest estimate wins).
    """
    T = pd.Timestamp(T)
    open_ = spells[(spells["start"] <= T) & (spells["end"] > T)].copy()
    if open_.empty:
        return pd.DataFrame(columns=["PLAYER_ID", "out_until"])
    if medians is None:
        open_["out_until"] = open_["end"]
    else:
        sev = open_["notes"].astype(str).str.contains(SEVERE_RE)
        expected = np.where(sev, medians["severe"], medians["normal"])
        elapsed = (T - open_["start"]).dt.days.to_numpy(dtype=float)
        remaining = np.maximum(expected - elapsed, MIN_REMAINING_DAYS)
        open_["out_until"] = T + pd.to_timedelta(remaining, unit="D")
    return (open_.sort_values("out_until").groupby("PLAYER_ID", as_index=False)["out_until"].last())


def mpg_additions(
    mpg: pd.Series,
    out_events: pd.DataFrame,
    team_map: pd.Series | dict,
    pos_map: pd.Series | dict,
    weights: dict,
    T: pd.Timestamp,
    season_end: pd.Timestamp,
) -> pd.Series:
    """Per-player MPG additions from every OUT teammate — the arithmetic core shared by the
    board layer and the lead-time grid. ``mpg`` is indexed by PLAYER_ID (the projection to
    redistribute). Flow per OUT player o: ``vac = mpg_o × overlap_fraction``, split over
    active same-team teammates by ``θ[same_pos, tier]``, tier from the teammate's own
    projected MPG; if the cell weights sum past 1 they are scaled back (a team cannot absorb
    more than what vacated)."""
    T, season_end = pd.Timestamp(T), pd.Timestamp(season_end)
    team_map = team_map.to_dict() if isinstance(team_map, pd.Series) else dict(team_map)
    pos_map = pos_map.to_dict() if isinstance(pos_map, pd.Series) else dict(pos_map)
    theta = weights["theta"]

    add = pd.Series(0.0, index=mpg.index)
    denom = max((season_end - T).days, 1)
    out_ids = set(out_events["PLAYER_ID"])
    by_team: dict = {}
    for pid in mpg.index:
        t = team_map.get(pid)
        if t is not None and not pd.isna(t):
            by_team.setdefault(t, []).append(pid)

    for e in out_events.itertuples(index=False):
        pid = e.PLAYER_ID
        if pid not in mpg.index:
            continue
        vac_mpg = float(mpg[pid])
        if vac_mpg < MIN_ROTATION_MPG:
            continue
        team = team_map.get(pid)
        if team is None or pd.isna(team):
            continue
        f = np.clip((min(pd.Timestamp(e.out_until), season_end) - T).days / denom, 0.0, 1.0)
        if f <= 0:
            continue
        pos_o = pos_map.get(pid)
        ws = {}
        for j in by_team.get(team, []):
            if j == pid or j in out_ids:
                continue
            pos_j = pos_map.get(j)
            sp = int(pos_o is not None and pos_j is not None
                     and not pd.isna(pos_o) and not pd.isna(pos_j) and pos_o == pos_j)
            w = theta.get(_cell(sp, int(_tier(float(mpg[j])))), 0.0)
            if w > 0:
                ws[j] = w
        tot = sum(ws.values())
        scale = 1.0 / tot if tot > 1.0 else 1.0
        for j, w in ws.items():
            add[j] += w * scale * vac_mpg * f
    return add


def redistribute_board(
    board: pd.DataFrame,
    out_events: pd.DataFrame,
    team_map: pd.Series | dict,
    pos_map: pd.Series | dict,
    weights: dict,
    T: pd.Timestamp,
    season_end: pd.Timestamp,
    cfg: ScoringConfig,
) -> pd.DataFrame:
    """Board → board with OUT players' minutes flowed to their teammates (EXP-030's live
    layer; runs after ``asof.apply_status_overrides``, which owns the OUT player's own GP).

    Touched teammates: ``mpg += additions`` (capped at ``MPG_CAP``), per-game counting stats
    scaled by the minutes ratio (rates held — the board's own rates), ``fpts_pg`` re-scored
    through ``cfg`` (bonuses are non-linear — never scale fpts directly), totals and ranks
    recomputed. Untouched rows keep byte-identical values (only ``rank`` may renumber).
    Adds ``redist_mpg`` (the addition, 0 elsewhere) as the audit column.
    """
    out = board.copy()
    mpg = pd.Series(out["mpg"].to_numpy(dtype=float), index=out["PLAYER_ID"])
    add = mpg_additions(mpg, out_events, team_map, pos_map, weights, T, season_end)
    out["redist_mpg"] = out["PLAYER_ID"].map(add).fillna(0.0).round(2)
    touched = out["redist_mpg"] > 0
    if touched.any():
        old_mpg = out.loc[touched, "mpg"].astype(float)
        new_mpg = np.clip(old_mpg + out.loc[touched, "redist_mpg"], 0.0, MPG_CAP)
        ratio = (new_mpg / old_mpg.replace(0.0, np.nan)).fillna(1.0)
        for canon in COUNTING:
            out.loc[touched, canon] = (out.loc[touched, canon].astype(float) * ratio).round(2)
        out.loc[touched, "mpg"] = new_mpg.round(1)
        out.loc[touched, "fpts_pg"] = score_frame(out.loc[touched], cfg).round(2)
        out.loc[touched, "fpts_total"] = (
            out.loc[touched, "fpts_pg"] * out.loc[touched, "gp"]).round(1)
    out = out.sort_values("fpts_total", ascending=False).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out


def redistribute_mpg_grid(
    grid: pd.DataFrame,
    spells: pd.DataFrame,
    medians: dict,
    gl_season: pd.DataFrame,
    pos_map: pd.Series | dict,
    weights: dict,
    season_end: pd.Timestamp,
) -> pd.DataFrame:
    """The lead-time comparator: apply :func:`mpg_additions` to a ``[date, PLAYER_ID, mpg]``
    weekly grid (``eval_asof._grid_mpg_asof`` output), with OUT sets and team maps rebuilt
    honestly at each grid date."""
    frames = []
    for T, sub in grid.groupby("date"):
        mpg = pd.Series(sub["mpg"].to_numpy(dtype=float), index=sub["PLAYER_ID"])
        tm = team_map_asof(gl_season, T)
        ev = out_events_asof(spells, T, medians)
        add = mpg_additions(mpg, ev, tm, pos_map, weights, T, season_end)
        frames.append(pd.DataFrame({
            "date": T, "PLAYER_ID": mpg.index,
            "mpg": np.clip(mpg.to_numpy() + add.to_numpy(), 0.0, MPG_CAP),
        }))
    return pd.concat(frames, ignore_index=True)
