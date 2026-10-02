"""Pre-score a public minutes grid with the local, canonical model/scoring path.

The static site only looks up these exported values. No private analyst rationale,
raw caches, roster ownership or scoring reimplementation is shipped to the browser.
"""

from __future__ import annotations

import pandas as pd

from fantasy_nba.minutes_scenario import minutes_scenario
from fantasy_nba.models._core import COUNTING, MPG_CAP, rescale_to_minutes
from fantasy_nba.scoring import ScoringConfig

MIN_MPG = 0.5
STEP_MPG = 0.5
GRID = [round(i * STEP_MPG, 1) for i in range(1, int(MPG_CAP / STEP_MPG) + 1)]


def build_public_minutes(board: pd.DataFrame, cfg: ScoringConfig,
                         *, generated_at: str, scoring_key: str) -> dict:
    rows = {}
    for row in board.to_dict("records"):
        baseline = minutes_scenario(row, None, cfg)
        if not baseline["enabled"]:
            continue
        frame = pd.DataFrame([row] * len(GRID))
        for stat in COUNTING:
            if stat in frame.columns:
                frame[stat] = pd.to_numeric(frame[stat], errors="coerce")
        frame["mpg"] = pd.to_numeric(frame["mpg"], errors="coerce")
        rescale_to_minutes(frame, pd.Series(True, index=frame.index),
                           pd.Series(GRID, index=frame.index), cfg)
        approved = baseline["approved_fpts_pg"]
        scored = baseline["scored_current_fpts_pg"]
        values = [round(approved + (float(value) - scored), 2)
                  for value in frame["fpts_pg"].tolist()]
        rows[str(row["PLAYER_ID"])] = {
            "current_mpg": baseline["current_mpg"], "approved_fpts_pg": approved,
            "scored_current_fpts_pg": scored,
            "retained_rate_residual": baseline["retained_rate_residual"],
            "values": values,
        }
    return {"schema": 1, "season": "2026-27", "generated_at": generated_at,
            "scoring_key": scoring_key, "board_rows": len(board),
            "min_mpg": MIN_MPG, "step_mpg": STEP_MPG, "max_mpg": MPG_CAP,
            "rows": rows}
