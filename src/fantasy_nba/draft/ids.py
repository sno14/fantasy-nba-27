"""ESPN <-> NBA player-id join + slot eligibility (implementation-plan Step 19.2).

ESPN's player ids are its own, so the draft feed's ``espn_player_id`` has to become our
``PLAYER_ID`` before it can touch a board. The join is by normalized name, reusing the
alias-hardened path the injuries/market pulls already use (``models.injuries.ALIASES``).

**Measured on league 507458037, season 2025 (2026-07-15) — not estimated:** 387/400 = 96.8%,
with Jokic -> 203999 and Doncic -> 1629029 correct.

Two findings from that run shape the code:

1. **ESPN writes ASCII, we store diacritics** — ESPN's ``"Nikola Jokic"`` vs our
   ``"Nikola Jokić"``. So normalization is NFKD -> strip non-ASCII -> lowercase -> drop
   ``.``/``'`` -> drop Jr/Sr/II/III/IV -> ``ALIASES``.
2. **The 13 non-matches were all correct** — Bojan Bogdanovic, Derrick Rose, Blake Griffin,
   Andre Iguodala, Saddiq Bey, Nikola Topic, Tacko Fall...: retirees and players with no
   season row at all. ESPN's universe is wider than our stats cache **by construction**.

Hence the guard is narrow on purpose: hard-fail only on a name that *has a stats row* but
doesn't resolve (a real join bug), never on ESPN carrying a retiree. A blunt "fail on any
unmatched name" would fire on Derrick Rose every run and be switched off within a day —
which is how a guard rots into noise.

The other half is ESPN's ``eligibleSlots``: real PG/SG/SF/PF/C eligibility, which
``models/value.py`` explicitly parks at guard/big (its §9.7). This is the only place in the
repo that knows a player is SG **and** SF.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..config import PROCESSED_DIR
from ..models.injuries import ALIASES
from .feed import POSITION_SLOTS, SLOT_NAMES

#: Cached ESPN identity + eligibility. Lets the manual feed run with no network at all.
MAP_PATH = PROCESSED_DIR / "espn_player_map.parquet"

_SUFFIX_RE = re.compile(r"\s+(jr|sr|ii|iii|iv|v)$")
_PUNCT_RE = re.compile(r"[.'`’]")


def normalize_name(name: str) -> str:
    """Name -> join key. NFKD-strips diacritics because ESPN serves ASCII and we don't.

    ``"Nikola Jokić"`` and ``"Nikola Jokic"`` must land on the same key or the join silently
    loses the best player in the league.
    """
    n = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    n = _PUNCT_RE.sub("", n.lower()).strip()
    n = _SUFFIX_RE.sub("", n)
    n = re.sub(r"\s+", " ", n).strip()
    return ALIASES.get(n, n)


def eligible_positions(eligible_slots: list[int] | None) -> set[str]:
    """ESPN slot ids -> the real position claims (PG/SG/SF/PF/C only).

    ESPN also lists composite slots (G, F, UTIL, BE, IR) that aren't position facts, so they
    are dropped: Edwards is ``{SG, SF}``, not ``{SG, SF, G, F, UTIL, BE}``.
    """
    return {SLOT_NAMES[s] for s in (eligible_slots or []) if s in POSITION_SLOTS}


@dataclass(frozen=True)
class PlayerMap:
    """Resolved ESPN -> NBA identity + eligibility.

    ``unmatched`` is expected to be non-empty and is not an error — see the module docstring.
    """

    to_nba: dict[int, int] = field(default_factory=dict)          # espn_id -> PLAYER_ID
    eligible_of: dict[int, set[str]] = field(default_factory=dict)  # PLAYER_ID -> {PG, SG...}
    names: dict[int, str] = field(default_factory=dict)            # PLAYER_ID -> ESPN name
    unmatched: list[str] = field(default_factory=list)             # ESPN names with no stats row

    def nba_id(self, espn_player_id: int) -> int | None:
        return self.to_nba.get(int(espn_player_id))

    @property
    def match_rate(self) -> float:
        total = len(self.to_nba) + len(self.unmatched)
        return len(self.to_nba) / total if total else 0.0

    def to_frame(self) -> pd.DataFrame:
        """Persistable form (``data/processed/espn_player_map.parquet``)."""
        return pd.DataFrame(
            [{"espn_player_id": e, "PLAYER_ID": n, "espn_name": self.names.get(n, ""),
              "eligible": "|".join(sorted(self.eligible_of.get(n, ())))}
             for e, n in sorted(self.to_nba.items())]
        )

    def save(self, path: Path | None = None) -> Path:
        path = Path(path) if path else MAP_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_frame().to_parquet(path, index=False)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "PlayerMap | None":
        """The cached map, or ``None``.

        This is what makes ``ManualFeed`` genuinely offline: ESPN is the only source of slot
        eligibility, so without a cache "manual mode needs no network" would be a lie — you
        would have no positions, hence no slot feasibility and a meaningless replacement
        level. Connect once (any time before the draft) and the map persists.
        """
        path = Path(path) if path else MAP_PATH
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        return cls(
            to_nba={int(r.espn_player_id): int(r.PLAYER_ID) for r in df.itertuples()},
            eligible_of={int(r.PLAYER_ID): set(str(r.eligible).split("|")) - {""}
                         for r in df.itertuples()},
            names={int(r.PLAYER_ID): str(r.espn_name) for r in df.itertuples()},
            unmatched=[],  # not persisted: it's a diagnostic of one pull, not identity
        )


def build_player_map(
    espn_players: list[dict],
    season_stats: pd.DataFrame,
    season: str | None = None,
    board_ids: set[int] | None = None,
) -> PlayerMap:
    """Join ESPN's player universe to our ``PLAYER_ID``s.

    ``espn_players``: raw rows from ``EspnPollFeed.player_universe()`` (need ``id``,
    ``fullName``, ``eligibleSlots``).
    ``season``: when supplied, restrict identity matching to that season. When omitted, use
    all historical rows so returning players who missed the latest season (for example an
    Achilles absence) still resolve when they reappear in ESPN's draft pool.
    ``board_ids``: when given, the guard is evaluated against *these* players — i.e. the ones
    we would actually draft. This is the honest scope: a miss inside the board is a bug, a
    miss outside it is ESPN carrying a retiree.

    Raises on a **collision** (two ESPN players resolving to one ``PLAYER_ID``) — that is a
    real ambiguity and must be fixed via ``ALIASES``, never silently resolved by pick-one.
    """
    ss = season_stats
    if season is not None:
        ss = ss[ss["SEASON"] == season]

    ours: dict[str, int] = {}
    for row in ss[["PLAYER_ID", "PLAYER_NAME"]].drop_duplicates().itertuples(index=False):
        ours[normalize_name(row.PLAYER_NAME)] = int(row.PLAYER_ID)

    to_nba: dict[int, int] = {}
    eligible_of: dict[int, set[str]] = {}
    names: dict[int, str] = {}
    unmatched: list[str] = []
    claimed: dict[int, str] = {}

    for p in espn_players:
        espn_id, full = p.get("id"), p.get("fullName")
        if espn_id is None or not full:
            continue
        nba_id = ours.get(normalize_name(full))
        if nba_id is None:
            unmatched.append(str(full))
            continue
        if nba_id in claimed and claimed[nba_id] != full:
            raise ValueError(
                f"ESPN name collision: {claimed[nba_id]!r} and {full!r} both resolve to "
                f"PLAYER_ID {nba_id}. Extend fantasy_nba.models.injuries.ALIASES (dated, "
                f"append-only) — never let the join pick one."
            )
        claimed[nba_id] = str(full)
        to_nba[int(espn_id)] = nba_id
        eligible_of[nba_id] = eligible_positions(p.get("eligibleSlots"))
        names[nba_id] = str(full)

    if board_ids:
        missed = board_ids - set(to_nba.values())
        if missed:
            raise ValueError(
                f"{len(missed)} board players did not resolve to an ESPN id: "
                f"{sorted(missed)[:10]}. These are players we would actually draft, so this "
                f"is a join bug — extend ALIASES. (ESPN players with no stats row are a "
                f"separate, expected case and are recorded in `unmatched`.)"
            )
    return PlayerMap(to_nba=to_nba, eligible_of=eligible_of, names=names, unmatched=unmatched)
