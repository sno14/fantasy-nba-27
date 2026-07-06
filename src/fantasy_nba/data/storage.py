"""Parquet-based local cache for pulled and processed data.

Thin helpers so the rest of the codebase never hard-codes paths or file formats. Datasets
are addressed by a short name (e.g. ``"player_season_stats"``) within a layer
(``"raw"`` or ``"processed"``).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import PROCESSED_DIR, RAW_DIR, ensure_data_dirs

_LAYERS = {"raw": RAW_DIR, "processed": PROCESSED_DIR}


def _path(name: str, layer: str) -> Path:
    if layer not in _LAYERS:
        raise ValueError(f"layer must be one of {sorted(_LAYERS)}, got {layer!r}")
    return _LAYERS[layer] / f"{name}.parquet"


def write(df: pd.DataFrame, name: str, layer: str = "raw") -> Path:
    """Write a DataFrame to ``<layer>/<name>.parquet`` and return the path."""
    ensure_data_dirs()
    path = _path(name, layer)
    df.to_parquet(path, index=False)
    return path


def read(name: str, layer: str = "raw") -> pd.DataFrame:
    """Read ``<layer>/<name>.parquet`` into a DataFrame."""
    path = _path(name, layer)
    if not path.exists():
        raise FileNotFoundError(f"No cached dataset at {path}. Pull it first.")
    return pd.read_parquet(path)


def exists(name: str, layer: str = "raw") -> bool:
    """Whether a cached dataset exists."""
    return _path(name, layer).exists()
