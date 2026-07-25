"""The analyst pass (Step D2 / EXP-029): auditable human overrides + the trigger list.

The gap-closer for what commercial systems' human staff do (camp reports, depth-chart
judgment, injury context) — replicated **auditable** and **scored**. Two-part discipline:

1. Every adjustment is written down in ``config/analyst_overrides.yaml`` with a dated
   rationale, including explicit ``none`` verdicts ("reviewed, no change" is
   information). Entries are append-only: a change of mind is a new, later-dated entry
   for the same player, never an edit. *(Workflow v2, 2026-07-12: entries land any time
   via the BBM-transcript triangulation → ``analyst_proposals.yaml`` → user approval; the
   mid-Oct pass re-reviews everything before the freeze.)*
2. Application is **deterministic, unit-tested arithmetic** (:func:`apply_overrides`):
   ``board A → board B`` preseason, and nightly on the in-season ROS board
   (``update_daily.py``). Board A's file is never touched — the D2.3 dual freeze commits
   both, and D2.4 grades them in April. *(2026-07-12 user decision: the grade
   **calibrates** the layer — magnitudes, per-source weighting — rather than deciding
   its existence; it is a standing supplement.)*

The trigger list (:func:`trigger_list`) generates *who to review* — within the top-200
union of our board and the expert consensus: large rank gaps, EXP-026 breakout flags,
severe-injury returnees (trailing 18 months), and rookies. Generated, not vibes: the
pass reviews a defined population, so "we never looked at him" is itself auditable.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..config import CONFIG_DIR
from ._core import MPG_CAP, rescale_to_minutes
from .breakout import DEFAULT_POLICY
from .darko import normalize_name as _normalize
from .injuries import ALIASES, SEVERE_RE

CATEGORIES = ("role", "injury", "hype", "rookie", "other")
ACTIONS = ("none", "rank_delta", "fpts_delta", "target_mpg")

# The two legs of a per-game belief, in application order. The model builds every
# projection as minutes x rate (`learned.py`: `out[canon] = rate * pred_mpg`), so the
# analyst layer — which owns per-game value — needs one verb per factor:
#   target_mpg  the MINUTES factor, absolute ("he plays 31"). Self-limiting: once the
#               model projects 31 itself the entry is a no-op, so it cannot double-count
#               and needs no Step-18 decay.
#   fpts_delta  the RATE residual, applied AFTER the minutes rescale.
# A minutes belief expressed as fpts_delta alone leaves `mpg` and the stat line stale and
# silently asserts a per-minute rate instead (Walker Kessler: 33.4 fpts at an unchanged
# 21.3 mpg = 1.568 fpts/min, 28% above his career best).
LEG_KEYS = ("target_mpg", "fpts_delta")

# Step 18 — the delta lifecycle. Role/hype deltas are *bridges*: they carry information
# the model can't see yet, and the in-season EWMA features learn the role as games
# accumulate — leaving a static delta stacked on a caught-up base = double-counting.
# injury/other deltas are exempt (availability lives in config/overrides.yaml anyway).
BRIDGE_CATEGORIES = ("role", "hype")
DECAY_FULL_GAMES = 10   # delta at full strength while the EWMA is still small-sample
DECAY_ZERO_GAMES = 30   # by here the role signal is reliable (EXP-018 half-lives: MPG=10g)

# D2.1 trigger thresholds.
TRIGGER_TOP_N = 200          # the union universe: our top-200 + consensus top-200
TRIGGER_RANK_GAP = 15        # |our rank − consensus rank| that flags a player
RETURNEE_WINDOW_DAYS = 548   # severe-injury spells ending in the trailing ~18 months


def name_key(name: str) -> str:
    """The shared normalizer + cross-source alias map (same key as ``pull_market``)."""
    key = _normalize(name)
    return ALIASES.get(key, key)


def load_overrides(path: str | Path | None = None) -> list[dict]:
    """Parse + validate ``config/analyst_overrides.yaml`` into a list of entry dicts.

    Each entry: ``name`` (str), ``date`` (ISO date), ``category`` (one of
    ``CATEGORIES``), ``action`` (the string ``"none"`` or a one-key mapping
    ``{rank_delta: int}`` / ``{fpts_delta: float}``), ``rationale`` (non-empty).
    Validation is loud — a malformed entry raises rather than silently skipping,
    because a dropped override would corrupt the April attribution.
    """
    path = Path(path) if path else CONFIG_DIR / "analyst_overrides.yaml"
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return parse_overrides(raw, source=str(path))


def parse_overrides(raw: list | None, source: str = "<overrides>") -> list[dict]:
    """Validate a raw YAML list of override mappings into internal entry dicts.

    Shared by :func:`load_overrides` and the proposals promoter
    (``scripts/apply_proposals.py``) so both enforce identical validation. Loud on any
    malformed entry — a silently dropped override corrupts the April attribution.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{source} must be a YAML list of override entries, got {type(raw).__name__}.")
    entries = []
    for i, e in enumerate(raw):
        where = f"{source} entry {i + 1}"
        if not isinstance(e, dict):
            raise ValueError(f"{where}: not a mapping.")
        missing = {"name", "date", "category", "action", "rationale"} - set(e)
        if missing:
            raise ValueError(f"{where} ({e.get('name', '?')}): missing {sorted(missing)}.")
        if e["category"] not in CATEGORIES:
            raise ValueError(f"{where} ({e['name']}): category {e['category']!r} not in {CATEGORIES}.")
        if not str(e["rationale"]).strip():
            raise ValueError(f"{where} ({e['name']}): rationale is empty.")
        date = pd.Timestamp(e["date"])  # raises on garbage
        action = e["action"]
        legs: dict[str, float] = {}
        if action == "none":
            kind, value = "none", 0.0
        elif isinstance(action, dict) and action:
            bad = set(action) - {"rank_delta", "fpts_delta", "target_mpg"}
            if bad:
                raise ValueError(f"{where} ({e['name']}): action key(s) {sorted(bad)} not in {ACTIONS[1:]}.")
            for k, v in action.items():
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise ValueError(f"{where} ({e['name']}): {k} value {v!r} is not numeric.")
                legs[k] = float(v)
            if "rank_delta" in legs and len(legs) > 1:
                raise ValueError(f"{where} ({e['name']}): rank_delta cannot combine with other legs.")
            if "target_mpg" in legs and not (0.0 < legs["target_mpg"] <= MPG_CAP):
                raise ValueError(f"{where} ({e['name']}): target_mpg {legs['target_mpg']} "
                                 f"must be in (0, {MPG_CAP}].")
            # `kind`/`value` stay for the single-leg legacy readers; a composite reports
            # its rate leg (or target_mpg when that is the only leg).
            kind = "fpts_delta" if "fpts_delta" in legs else next(iter(legs))
            value = legs[kind]
        else:
            raise ValueError(
                f"{where} ({e['name']}): action must be 'none' or a mapping of "
                f"{{target_mpg: M}} / {{fpts_delta: X}} / {{rank_delta: N}}, got {action!r}."
            )
        entries.append({
            "name": str(e["name"]), "name_key": name_key(e["name"]), "date": date,
            "category": e["category"], "kind": kind, "value": value,
            "target_mpg": legs.get("target_mpg"), "fpts_delta": legs.get("fpts_delta"),
            "rank_delta": legs.get("rank_delta"),
            "rationale": str(e["rationale"]).strip(), "_pos": i,
        })
    return entries


def effective_overrides(entries: list[dict]) -> list[dict]:
    """One entry per player: the latest-dated wins (file position breaks date ties) —
    the append-only correction rule. Output keeps the surviving entries in file order."""
    best: dict[str, dict] = {}
    for e in entries:
        cur = best.get(e["name_key"])
        if cur is None or (e["date"], e["_pos"]) >= (cur["date"], cur["_pos"]):
            best[e["name_key"]] = e
    return sorted(best.values(), key=lambda e: e["_pos"])


def _action_str(e: dict) -> str:
    """The audit string on the board: ``none``, ``fpts_delta:+4.5``, ``target_mpg:31``, or a
    pipe-joined composite ``target_mpg:31|fpts_delta:-4.3`` (legs in application order).

    ``target_mpg`` is absolute, so it is printed WITHOUT a sign — the ``+g`` used for the
    deltas would render it as ``+31`` and read like a delta. Anything parsing this string
    must handle the composite form; see :func:`parse_fpts_delta`.
    """
    if e["kind"] == "none":
        return "none"
    if e.get("rank_delta") is not None:
        return f"rank_delta:{e['rank_delta']:+g}"
    parts = []
    if e.get("target_mpg") is not None:
        parts.append(f"target_mpg:{e['target_mpg']:g}")
    if e.get("fpts_delta") is not None:
        parts.append(f"fpts_delta:{e['fpts_delta']:+g}")
    return "|".join(parts) if parts else "none"


def apply_overrides(board: pd.DataFrame, entries: list[dict],
                    decay_from: str | None = None, cfg=None) -> pd.DataFrame:
    """Board A + overrides → board B (a new frame; the input is not mutated).

    Deterministic arithmetic, applied in file order after the latest-dated-wins dedupe:

    * ``none``       — recorded only (``analyst_*`` columns), no movement.
    * ``rank_delta``  — the row moves to ``clip(current rank + delta, 1, n)`` (negative =
      up); everyone between shifts by one.
    * ``fpts_delta``  — ``fpts_pg += delta``; ``fpts_total`` recomputed from ``gp`` when
      present (else scaled proportionally); the row re-inserts where its adjusted
      ``fpts_total`` fits in the board order (stable — incumbents with equal totals stay
      ahead).

    ``rank`` is renumbered 1..n at the end; ``model_rank`` preserves board A's rank for
    the D2.4 per-adjustment attribution. VOR columns, when present, are board-A values
    (the analyst layer adjusts rank/fpts only — replacement level is not re-simulated).
    An override naming a player absent from the board, or matching two board rows,
    raises — a silently dropped or ambiguous override would corrupt the April scoring.

    ``decay_from`` (Step 18.2, in-season only — off by default): the name of a
    games-played-so-far column. When set, each :data:`BRIDGE_CATEGORIES` ``fpts_delta``
    is scaled by :func:`decay_factor` of that row's value before applying, and every
    adjusted row carries an ``analyst_decay_factor`` audit column (1.0 = undamped;
    injury/other/rookie deltas and the preseason board-B path are never scaled).
    ``analyst_action`` keeps the *entry's* delta — the factor column is the audit of
    what was actually applied.
    """
    out = board.copy().reset_index(drop=True)
    if "rank" not in out.columns:
        raise ValueError("board needs a 'rank' column.")
    if decay_from is not None and decay_from not in out.columns:
        raise ValueError(f"decay_from column {decay_from!r} not on the board.")
    out = out.sort_values("rank").reset_index(drop=True)
    out["model_rank"] = out["rank"].to_numpy()
    out["analyst_action"] = ""
    out["analyst_category"] = ""
    out["analyst_date"] = ""
    out["analyst_rationale"] = ""
    if decay_from is not None:
        out["analyst_decay_factor"] = np.nan
    keys = out["PLAYER_NAME"].map(name_key)

    for e in effective_overrides(entries):
        hits = np.flatnonzero((keys == e["name_key"]).to_numpy())
        if len(hits) == 0:
            raise ValueError(f"Override {e['name']!r} matches no board row — fix the name "
                             f"(or extend injuries.ALIASES) before applying.")
        if len(hits) > 1:
            raise ValueError(f"Override {e['name']!r} matches {len(hits)} board rows — "
                             f"colliding normalized names must be resolved explicitly.")
        i = int(hits[0])
        out.loc[i, "analyst_action"] = _action_str(e)
        out.loc[i, "analyst_category"] = e["category"]
        out.loc[i, "analyst_date"] = e["date"].date().isoformat()
        out.loc[i, "analyst_rationale"] = e["rationale"]

        if e["kind"] == "none":
            continue
        if e.get("rank_delta") is None:
            # The pre-analyst base, recorded rather than reconstructed. Step 18 used to
            # recover it by subtracting the delta from fpts_pg; that is unrecoverable once
            # a target_mpg rescale has MULTIPLIED the row, so store it here.
            if "analyst_base_fpts" not in out.columns:
                out["analyst_base_fpts"] = np.nan
            out.loc[i, "analyst_base_fpts"] = round(float(out.loc[i, "fpts_pg"]), 2)

            # Leg 1 — MINUTES. Absolute, and additive with EXP-030's in-season
            # redistribution (a role belief and a teammate's absence are separate causes).
            if e.get("target_mpg") is not None:
                if cfg is None:
                    from ..scoring import load_scoring
                    cfg = load_scoring(None)
                target = float(e["target_mpg"])
                if "redist_mpg" in out.columns and pd.notna(out.loc[i, "redist_mpg"]):
                    target += float(out.loc[i, "redist_mpg"])
                rescale_to_minutes(out, out.index == i, target, cfg)

        # Leg 2 — RATE residual, on top of the rescaled line.
        if e.get("fpts_delta") is not None:
            value = e["fpts_delta"]
            if decay_from is not None:
                factor = 1.0
                if e["category"] in BRIDGE_CATEGORIES:
                    g = out.loc[i, decay_from]
                    factor = decay_factor(g) if pd.notna(g) else 1.0
                out.loc[i, "analyst_decay_factor"] = factor
                value = value * factor
            old_pg = float(out.loc[i, "fpts_pg"])
            new_pg = old_pg + value
            out.loc[i, "fpts_pg"] = new_pg
            if "fpts_total" in out.columns:
                gp = out.loc[i, "gp"] if "gp" in out.columns else np.nan
                if pd.notna(gp):
                    out.loc[i, "fpts_total"] = new_pg * float(gp)
                elif old_pg != 0:
                    out.loc[i, "fpts_total"] = float(out.loc[i, "fpts_total"]) * new_pg / old_pg
                target_total = float(out.loc[i, "fpts_total"])
                others = out["fpts_total"].drop(index=i).to_numpy(dtype=float)
                j = int((others >= target_total).sum())  # stable: ties keep incumbents ahead
            else:
                others = out["fpts_pg"].drop(index=i).to_numpy(dtype=float)
                j = int((others >= new_pg).sum())
        elif e.get("rank_delta") is not None:
            j = int(np.clip(i + e["rank_delta"], 0, len(out) - 1))
        else:
            # target_mpg alone — rescale_to_minutes already recomputed fpts_pg/fpts_total;
            # the row re-inserts wherever its derived value now sits.
            if "fpts_total" in out.columns:
                others = out["fpts_total"].drop(index=i).to_numpy(dtype=float)
                j = int((others >= float(out.loc[i, "fpts_total"])).sum())
            else:
                others = out["fpts_pg"].drop(index=i).to_numpy(dtype=float)
                j = int((others >= float(out.loc[i, "fpts_pg"])).sum())
        row = out.iloc[[i]]
        rest = out.drop(index=i).reset_index(drop=True)
        out = pd.concat([rest.iloc[:j], row, rest.iloc[j:]], ignore_index=True)
        keys = out["PLAYER_NAME"].map(name_key)

    out["rank"] = range(1, len(out) + 1)
    return out


# --------------------------------------------------------------- Step 18: delta lifecycle
def parse_fpts_delta(action_str: str) -> float:
    """The fpts_delta encoded in an ``analyst_action`` audit string, 0.0 when there is none.

    Handles every form the string takes: ``fpts_delta:+3.5``, the composite
    ``target_mpg:31|fpts_delta:-4.3``, and ``none`` / ``rank_delta:…`` / empty.

    **LEGACY USE ONLY.** This recovers a pre-analyst base by subtraction
    (``base = fpts_pg − delta``), which is only valid when the entry had no ``target_mpg``
    leg — a minutes rescale MULTIPLIES the row, so subtracting the rate leg leaves
    ``base x ratio``. Live boards carry an ``analyst_base_fpts`` column; prefer it and fall
    back here only for archived snapshots written before that column existed.
    """
    for part in (action_str or "").strip().split("|"):
        if part.startswith("fpts_delta:"):
            try:
                return float(part.split(":", 1)[1])
            except ValueError:
                return 0.0
    return 0.0


def parse_target_mpg(action_str: str) -> float | None:
    """The absolute ``target_mpg`` in an ``analyst_action`` audit string, else ``None``.

    Its presence is also the signal that :func:`parse_fpts_delta` CANNOT recover that row's
    pre-analyst base by subtraction.
    """
    for part in (action_str or "").strip().split("|"):
        if part.startswith("target_mpg:"):
            try:
                return float(part.split(":", 1)[1])
            except ValueError:
                return None
    return None


def stale_entries(entries: list[dict], base_now: dict[str, float],
                  base_then: dict[str, float]) -> list[dict]:
    """18.1 — which effective bridge deltas has the model already absorbed?

    For each effective ``fpts_delta`` entry in a :data:`BRIDGE_CATEGORIES` category,
    compare the model's current pre-analyst base against its base when the entry was
    written (both keyed by ``name_key``; players missing either base are skipped —
    never guessed). The entry is **stale** when the base has moved *in the delta's
    direction* by at least the delta's magnitude — the spec's "risen by ≥ the delta"
    for upgrades, mirrored for downgrades. Stale ≠ auto-removed: the flag is a nudge
    to post a later-dated ``none``/reduced entry (append-only rule unchanged).

    Returns one dict per checkable entry: ``name, name_key, category, delta,
    base_then, base_now, caught_up`` (signed base move) ``, stale``.
    """
    out = []
    for e in effective_overrides(entries):
        if e.get("fpts_delta") is None or e["category"] not in BRIDGE_CATEGORIES:
            continue
        now, then = base_now.get(e["name_key"]), base_then.get(e["name_key"])
        if now is None or then is None:
            continue
        caught, delta = float(now) - float(then), float(e["fpts_delta"])
        stale = (caught * delta > 0) and abs(caught) >= abs(delta)
        out.append({"name": e["name"], "name_key": e["name_key"],
                    "category": e["category"], "delta": delta,
                    "base_then": round(float(then), 1), "base_now": round(float(now), 1),
                    "caught_up": round(caught, 1), "stale": stale})
    return out


def decay_factor(games_so_far: float) -> float:
    """18.2 — how much of a bridge delta survives after ``games_so_far`` games: full
    strength through :data:`DECAY_FULL_GAMES`, linear taper to 0 by
    :data:`DECAY_ZERO_GAMES` (where the EWMA role signal is reliable)."""
    g = float(games_so_far)
    if g <= DECAY_FULL_GAMES:
        return 1.0
    if g >= DECAY_ZERO_GAMES:
        return 0.0
    return 1.0 - (g - DECAY_FULL_GAMES) / (DECAY_ZERO_GAMES - DECAY_FULL_GAMES)


def _breakout_flags(board: pd.DataFrame) -> pd.Series:
    """EXP-026 breakout flags per board row: the shipped ``breakout_flag`` column when
    present, else derived from ``breakout_p`` with the DEFAULT_POLICY (the k highest
    scores ranked below the core)."""
    if "breakout_flag" in board.columns:
        return board["breakout_flag"].fillna(0).astype(int)
    if "breakout_p" not in board.columns:
        return pd.Series(0, index=board.index)
    eligible = board[board["rank"] > DEFAULT_POLICY["core"]]
    flagged = set(eligible.nlargest(DEFAULT_POLICY["k"], "breakout_p").index)
    return pd.Series([int(i in flagged) for i in board.index], index=board.index)


def severe_returnees(spells: pd.DataFrame, as_of: str,
                     window_days: int = RETURNEE_WINDOW_DAYS) -> set[int]:
    """PLAYER_IDs with a severe-bodypart spell (Step-7 regex) *ending* in the trailing
    ``window_days`` before ``as_of`` — the D2.1(c) returnee trigger."""
    cut = pd.Timestamp(as_of)
    s = spells[(spells["end"] > cut - pd.Timedelta(days=window_days)) & (spells["start"] < cut)]
    hit = s["notes"].astype(str).str.contains(SEVERE_RE)
    return set(s.loc[hit, "PLAYER_ID"].astype(int))


def trigger_list(
    board: pd.DataFrame,
    consensus: pd.DataFrame,
    known_keys: set[str] | None = None,
    returnee_ids: set[int] | None = None,
    top_n: int = TRIGGER_TOP_N,
    rank_gap: int = TRIGGER_RANK_GAP,
) -> pd.DataFrame:
    """The D2.1 trigger list: who the analyst pass must review (generated, not vibes).

    Universe = union of our board's top-``top_n`` (by ``rank``) and the consensus
    top-``top_n`` (by ``consensus_rank``). Triggers, comma-joined per player:

    * ``rank_gap``       — both ranks known and ``|our − consensus| >= rank_gap``.
    * ``not_on_board``   — consensus top-``top_n`` player absent from our board entirely
      (an implicit infinite gap — the consensus sees someone we cannot).
    * ``breakout``       — EXP-026 flag (shipped column or DEFAULT_POLICY-derived).
    * ``injury_returnee``— PLAYER_ID in ``returnee_ids`` (see :func:`severe_returnees`).
    * ``rookie``         — ``market_priced == 1`` board rows, or consensus rows whose
      name key is absent from ``known_keys`` (no NBA stats history).

    Only triggered players return, sorted by their best rank on either list.
    """
    b = board.copy()
    b["name_key"] = b["PLAYER_NAME"].map(name_key)
    b["breakout_hit"] = _breakout_flags(b)
    b_top = b[b["rank"] <= top_n]

    c = consensus.drop_duplicates("name_key", keep="first").copy()
    c["consensus_rank"] = pd.to_numeric(c["consensus_rank"], errors="coerce")
    c_top = c[c["consensus_rank"].between(1, top_n)]

    # itertuples renames underscore-prefixed columns, so keep the merge indicator plain.
    m = b_top.merge(c_top[["name_key", "consensus_rank"]], on="name_key", how="outer",
                    indicator="merge_src")
    # Consensus-only rows carry the consensus name for display.
    con_names = c_top.set_index("name_key")["player"]
    m["PLAYER_NAME"] = m["PLAYER_NAME"].fillna(m["name_key"].map(con_names))

    returnee_ids = returnee_ids or set()
    rows = []
    for r in m.itertuples(index=False):
        triggers = []
        our = getattr(r, "rank", np.nan)
        con = getattr(r, "consensus_rank", np.nan)
        if pd.notna(our) and pd.notna(con) and abs(our - con) >= rank_gap:
            triggers.append("rank_gap")
        if r.merge_src == "right_only":
            triggers.append("not_on_board")
        if pd.notna(our) and getattr(r, "breakout_hit", 0) == 1:
            triggers.append("breakout")
        pid = getattr(r, "PLAYER_ID", np.nan)
        if pd.notna(pid) and int(pid) in returnee_ids:
            triggers.append("injury_returnee")
        is_rookie = (getattr(r, "market_priced", 0) == 1) or (
            known_keys is not None and r.name_key not in known_keys)
        if is_rookie:
            triggers.append("rookie")
        if triggers:
            rows.append({
                "PLAYER_NAME": r.PLAYER_NAME,
                "our_rank": our, "consensus_rank": con,
                "rank_gap": (our - con) if pd.notna(our) and pd.notna(con) else np.nan,
                "triggers": ",".join(triggers),
                "breakout_p": getattr(r, "breakout_p", np.nan),
            })
    out = pd.DataFrame(rows, columns=["PLAYER_NAME", "our_rank", "consensus_rank",
                                      "rank_gap", "triggers", "breakout_p"])
    if out.empty:
        return out
    out["_best"] = out[["our_rank", "consensus_rank"]].min(axis=1)
    return out.sort_values("_best").drop(columns="_best").reset_index(drop=True)
