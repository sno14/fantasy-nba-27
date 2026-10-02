"""Read-only local player minutes scenario endpoint."""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Query

from ..minutes_scenario import minutes_scenario
from ..scoring import load_scoring
from . import boards

router = APIRouter(prefix="/api")


@router.get("/player/{player_id}/minutes-scenario")
def player_minutes_scenario(player_id: int, mpg: float | None = Query(default=None)) -> dict:
    if mpg is not None and (not math.isfinite(mpg) or mpg <= 0):
        raise HTTPException(422, "Assumed MPG must be a positive finite number")
    if not boards.data_ready():
        raise HTTPException(503, "No local projection data is cached")
    board = boards.ranked_board(boards.CURRENT_TARGET, "learned", "safe", True)
    hit = board[board["PLAYER_ID"] == player_id]
    if hit.empty:
        raise HTTPException(404, f"player {player_id} not on the current board")
    try:
        return minutes_scenario(hit.iloc[0].to_dict(), mpg, load_scoring())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
