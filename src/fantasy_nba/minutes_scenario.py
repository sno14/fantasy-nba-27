"""Read-only minutes sensitivity for an approved Board-B player row.

The current stat line is the approved minutes leg. Rescale that line with the
shared model helper, re-score it, then retain the separately applied analyst
rate residual. The scenario never changes ranks, games, ranges or saved boards.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

from .models._core import COUNTING, MPG_CAP, rescale_to_minutes
from .models.analyst import parse_fpts_delta
from .scoring import ScoringConfig, score_frame


def _number(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def minutes_scenario(row: Mapping, assumed_mpg: float | None, cfg: ScoringConfig) -> dict:
    """Return a verified decomposition, or an explicit unavailable reason."""
    name = str(row.get("PLAYER_NAME") or "Player")
    base = {"player_id": int(row["PLAYER_ID"]), "name": name, "enabled": False,
            "current_mpg": _number(row.get("mpg")), "approved_fpts_pg": _number(row.get("fpts_pg")),
            "min_mpg": 0.1, "max_mpg": MPG_CAP}
    old_mpg, approved = base["current_mpg"], base["approved_fpts_pg"]
    if old_mpg is None or old_mpg <= 0 or approved is None:
        return {**base, "reason": "This player has no positive projected minutes and approved FP/G to rescale."}
    required = {stat for stat, weight in cfg.weights.items() if weight != 0}
    if cfg.bonuses:
        required.update(cfg.double_double_categories)
    missing = sorted(stat for stat in required if _number(row.get(stat)) is None)
    if missing:
        return {**base, "reason": f"Projected stat-line inputs are missing: {', '.join(missing)}."}
    action = str(row.get("analyst_action") or "")
    if action and action != "none" and any(
        not part.startswith(("target_mpg:", "fpts_delta:", "rank_delta:")) for part in action.split("|")
    ):
        return {**base, "reason": "The approved analyst adjustment cannot be decomposed safely."}
    recorded_rate = parse_fpts_delta(action)
    if not math.isfinite(recorded_rate):
        return {**base, "reason": "The recorded analyst rate adjustment is invalid."}
    decay = _number(row.get("analyst_decay_factor"))
    if decay is None:
        decay = 1.0
    if decay < 0 or decay > 1:
        return {**base, "reason": "The analyst rate-decay factor is invalid."}
    scored_current = round(float(score_frame(pd.DataFrame([dict(row)]), cfg).iloc[0]), 2)
    retained_rate = approved - scored_current
    if abs(retained_rate - recorded_rate * decay) > 0.035:
        return {**base, "reason": "The approved FP/G does not reconcile with the scored stat line and recorded rate adjustment."}
    target = old_mpg if assumed_mpg is None else _number(assumed_mpg)
    if target is not None and assumed_mpg is not None:
        target = round(target, 1)
    if target is None or not 0 < target <= MPG_CAP:
        raise ValueError(f"Assumed MPG must be greater than 0 and at most {MPG_CAP:g}")
    frame = pd.DataFrame([dict(row)])
    for stat in COUNTING:
        if stat in frame.columns:
            frame[stat] = pd.to_numeric(frame[stat], errors="coerce")
    frame["mpg"] = pd.to_numeric(frame["mpg"], errors="coerce")
    rescale_to_minutes(frame, pd.Series([True], index=frame.index), target, cfg)
    scored_assumed = float(frame.loc[0, "fpts_pg"])
    contribution = round(scored_assumed - scored_current, 2)
    result = round(approved + contribution, 2)
    return {**base, "enabled": True, "reason": None, "assumed_mpg": round(target, 1),
            "scored_current_fpts_pg": scored_current, "scored_assumed_fpts_pg": scored_assumed,
            "minutes_contribution": contribution, "retained_rate_residual": round(retained_rate, 2),
            "recorded_rate_leg": round(recorded_rate * decay, 2),
            "assumed_fpts_pg": result, "fpts_pg_change": round(result - approved, 2),
            "rate_note": "Projected per-minute stat rates held; the shared scoring engine re-scores the scaled stat line.",
            "scope_note": "Exploration only. Games played, ranks, team minutes, usage and uncertainty ranges are unchanged."}
