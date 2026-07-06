"""Convert projected stat lines into fantasy points.

The projection models produce stat lines (points, rebounds, assists, ...). This module is
the *only* place scoring rules live, so swapping league formats never touches projections.

Works on both a single stat line (``dict``) and a vectorized ``pandas.DataFrame``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import pandas as pd
import yaml

from .config import SCORING_CONFIG

# Canonical stat column names understood by the scoring engine and projection outputs.
STAT_KEYS = (
    "pts",
    "reb",
    "oreb",
    "dreb",
    "ast",
    "stl",
    "blk",
    "tov",
    "fgm",
    "fga",
    "fg3m",
    "ftm",
    "fta",
)


@dataclass(frozen=True)
class ScoringConfig:
    """A league's scoring rules."""

    name: str
    weights: Mapping[str, float]
    bonuses: Mapping[str, float] = field(default_factory=dict)
    double_double_categories: tuple[str, ...] = ("pts", "reb", "ast", "stl", "blk")
    double_double_threshold: int = 10
    description: str = ""

    def __post_init__(self) -> None:
        unknown = set(self.weights) - set(STAT_KEYS)
        if unknown:
            raise ValueError(
                f"Unknown stat keys in scoring weights: {sorted(unknown)}. "
                f"Valid keys: {STAT_KEYS}"
            )


def load_scoring(path: str | Path | None = None) -> ScoringConfig:
    """Load a :class:`ScoringConfig` from YAML (defaults to ``config/scoring.yaml``)."""
    path = Path(path) if path is not None else SCORING_CONFIG
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return ScoringConfig(
        name=raw.get("name", "unnamed"),
        weights={k: float(v) for k, v in raw.get("weights", {}).items()},
        bonuses={k: float(v) for k, v in raw.get("bonuses", {}).items()},
        double_double_categories=tuple(
            raw.get("double_double_categories", ("pts", "reb", "ast", "stl", "blk"))
        ),
        double_double_threshold=int(raw.get("double_double_threshold", 10)),
        description=raw.get("description", ""),
    )


def _bonus_points(dd_count: pd.Series | int, cfg: ScoringConfig) -> pd.Series | float:
    """Highest-applicable bonus only (triple-double supersedes double-double)."""
    dd_bonus = cfg.bonuses.get("double_double", 0.0)
    td_bonus = cfg.bonuses.get("triple_double", 0.0)

    if isinstance(dd_count, pd.Series):
        out = pd.Series(0.0, index=dd_count.index)
        out = out.mask(dd_count >= 2, dd_bonus)
        out = out.mask(dd_count >= 3, td_bonus)
        return out

    if dd_count >= 3:
        return td_bonus
    if dd_count >= 2:
        return dd_bonus
    return 0.0


def score_frame(df: pd.DataFrame, cfg: ScoringConfig | None = None) -> pd.Series:
    """Fantasy points for each row of a stat-line DataFrame.

    Missing stat columns are treated as 0, so a frame need only contain the stats the
    scoring config actually references (plus the double-double categories).
    """
    cfg = cfg or load_scoring()

    total = pd.Series(0.0, index=df.index)
    for stat, weight in cfg.weights.items():
        if stat in df.columns:
            total = total + df[stat].fillna(0) * weight

    if cfg.bonuses:
        dd_count = pd.Series(0, index=df.index)
        for stat in cfg.double_double_categories:
            if stat in df.columns:
                dd_count = dd_count + (df[stat].fillna(0) >= cfg.double_double_threshold).astype(int)
        total = total + _bonus_points(dd_count, cfg)

    return total


def score_line(stats: Mapping[str, float], cfg: ScoringConfig | None = None) -> float:
    """Fantasy points for a single stat line given as a mapping of stat -> value."""
    cfg = cfg or load_scoring()

    total = sum(float(stats.get(stat, 0.0)) * weight for stat, weight in cfg.weights.items())

    if cfg.bonuses:
        dd_count = sum(
            1
            for stat in cfg.double_double_categories
            if float(stats.get(stat, 0.0)) >= cfg.double_double_threshold
        )
        total += _bonus_points(dd_count, cfg)

    return float(total)
