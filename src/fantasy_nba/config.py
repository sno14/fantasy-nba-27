"""Project paths and configuration loading."""

from __future__ import annotations

from pathlib import Path

# Repo root = two levels up from this file (src/fantasy_nba/config.py -> repo root).
ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

SCORING_CONFIG = CONFIG_DIR / "scoring.yaml"


def ensure_data_dirs() -> None:
    """Create the local data cache directories if they don't exist."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
