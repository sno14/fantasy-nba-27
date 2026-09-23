"""Explainable draft targets and fades from board value, growth, role, and risk.

ADP remains an availability signal, never a projection input.  The radar only compares
where the market drafts a player with an already-produced board and names the independent
reason(s) that make a large disagreement more or less convincing.
"""

from __future__ import annotations

import re

import pandas as pd


GROWTH_FPTS = 4.0
HIGH_RISK = 1.0


def _role_direction(action: object, rank: float, model_rank: object) -> int:
    text = str(action or "")
    if not text or text == "none":
        return 0
    values = [float(v) for v in re.findall(r"fpts_delta:([+-]?\d+(?:\.\d+)?)", text)]
    if "target_mpg:" in text and pd.notna(model_rank):
        before = float(model_rank)
        if before > rank:
            return 1
        if before < rank:
            return -1
    if any(v > 0 for v in values):
        return 1
    if any(v < 0 for v in values):
        return -1
    return 0


def add_draft_radar(
    board: pd.DataFrame,
    *,
    teams: int,
    rank_column: str = "rank",
) -> pd.DataFrame:
    """Add an explainable target/fade label using round-scaled market disagreement.

    ``strong_target`` / ``strong_fade`` require a two-round price gap plus a supporting
    mechanism. A one-round gap is a plain target/fade. Neutral rows remain blank so the UI
    stays quiet. The function does not reorder the board or alter any projection.
    """
    out = board.copy()
    out["radar_label"] = ""
    out["radar_round_gap"] = float("nan")
    out["radar_reasons"] = ""
    if teams <= 0 or rank_column not in out.columns or "adp" not in out.columns:
        return out

    for idx, row in out.iterrows():
        rank, adp = row.get(rank_column), row.get("adp")
        if pd.isna(rank) or pd.isna(adp):
            continue
        gap = float(adp) - float(rank)
        rounds = gap / teams
        growth = row.get("fpts_pg_change")
        growth = float(growth) if pd.notna(growth) else None
        risk = row.get("risk")
        risk = float(risk) if pd.notna(risk) else None
        role = _role_direction(row.get("analyst_action"), float(rank), row.get("model_rank"))
        reasons: list[str] = []

        if gap >= teams:
            reasons.append(f"ADP {abs(rounds):.1f} rounds later")
            if growth is not None and growth >= GROWTH_FPTS:
                reasons.append(f"+{growth:.1f} FP/G projection")
            if role > 0:
                reasons.append("positive role adjustment")
            support = (growth is not None and growth >= GROWTH_FPTS) or role > 0
            label = "strong_target" if gap >= 2 * teams and support else "target"
        elif gap <= -teams:
            reasons.append(f"ADP {abs(rounds):.1f} rounds earlier")
            if growth is not None and growth <= -GROWTH_FPTS:
                reasons.append(f"{growth:.1f} FP/G projection")
            if role < 0:
                reasons.append("negative role adjustment")
            if risk is not None and risk >= HIGH_RISK:
                reasons.append("wide downside range")
            support = ((growth is not None and growth <= -GROWTH_FPTS)
                       or role < 0 or (risk is not None and risk >= HIGH_RISK))
            label = "strong_fade" if gap <= -2 * teams and support else "fade"
        else:
            continue

        out.at[idx, "radar_label"] = label
        out.at[idx, "radar_round_gap"] = round(rounds, 2)
        out.at[idx, "radar_reasons"] = " | ".join(reasons)
    return out
