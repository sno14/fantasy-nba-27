"""The draft room (implementation-plan Step 19 / Phase 7).

Everything else in this repo ends at "here is a board". This package is what runs *during*
the draft: it ingests picks as they happen, keeps a live board, and re-prices the pool after
every pick.

Layers (each its own module, in dependency order):

* :mod:`.feed` — where picks come from. A narrow ``DraftFeed`` protocol with three
  implementations: ``ManualFeed`` (the shipped default and the draft-night fallback),
  ``EspnPollFeed`` (the real ESPN league), ``FixtureFeed`` (recorded payloads, for tests).
* :mod:`.ids` — the ESPN <-> NBA player-id join, plus ESPN's ``eligibleSlots`` (the real
  PG/SG/SF/PF/C eligibility that ``models/value.py`` parks at guard/big).
* :mod:`.live` — ``DraftState`` (rebuildable from the pick list alone) and
  ``live_replacement``: replacement level recomputed from the *actual* remaining pool and the
  *actual* remaining slot demand, which is what stops VOR being a restatement of fpts/g.

Later sub-steps (19.4-19.6: the weekly variance layer, the H2H week-win simulator, and the
recommendation) land in ``variance.py`` / ``sim.py`` / ``advice.py``. 19.5-19.6 are gated on
19.4's coverage check — see the step spec.
"""

from __future__ import annotations

from .feed import EspnPollFeed, FixtureFeed, ManualFeed, Pick
from .ids import PlayerMap, build_player_map
from .live import DraftState, live_replacement

__all__ = [
    "Pick",
    "ManualFeed",
    "EspnPollFeed",
    "FixtureFeed",
    "PlayerMap",
    "build_player_map",
    "DraftState",
    "live_replacement",
]
