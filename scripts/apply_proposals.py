"""Preview and promote analyst proposals — the review→apply half of workflow v2.

`config/analyst_proposals.yaml` is where Claude drafts triangulated BBM-transcript
proposals (model × BBM basketball reasoning × Claude judgment). Steven sets each entry's
``status`` to ``approved`` / ``rejected``; this script promotes the approved ones into
`config/analyst_overrides.yaml` — the living layer `apply_analyst.py` and `update_daily.py`
read. Idempotent: an entry already present (same name + date) is skipped, so re-running is
safe and un-approving just means flipping the status back before the next promote.

**Workflow policy (user decision 2026-07-12):**
  * Overrides are ``fpts_delta`` or ``none`` ONLY — never ``rank_delta``. A projection is a
    belief about a player's per-game value; ranking is the *byproduct* of re-sorting the
    whole board. A rank shove is incoherent — it moves a player past others who have
    nothing to do with the news. This script refuses to promote a ``rank_delta`` entry.
  * BBM's own ranking/tier claims ("top 50", "top 100") are ignored at extraction time —
    he plays different league settings; only the basketball mechanism transfers. (Enforced
    by the drafting rubric in data/manual/bbm_transcripts/README.md, not by code.)

Usage:
    python scripts/apply_proposals.py                    # preview all proposals' board impact
    python scripts/apply_proposals.py --status approved  # filter the preview
    python scripts/apply_proposals.py --promote          # approved -> analyst_overrides.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import yaml

from fantasy_nba.config import CONFIG_DIR, PROCESSED_DIR
from fantasy_nba.models.analyst import apply_overrides, name_key, parse_overrides

PROPOSAL_ONLY_FIELDS = ("status", "triangulation", "preview")
ENTRY_FIELDS = ("name", "date", "category", "action", "rationale")
_DATA_LINE = re.compile(r"^\s*(\[\]|-\s)")


def load_proposals(path: Path) -> list[dict]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw or []


def strip_to_entry(p: dict) -> dict:
    """A proposal → the analyst_overrides entry (drops the proposal-only fields)."""
    missing = [f for f in ENTRY_FIELDS if f not in p]
    if missing:
        raise SystemExit(f"proposal {p.get('name', '?')!r} missing {missing}")
    return {k: p[k] for k in ENTRY_FIELDS}


def _split_header(path: Path) -> str:
    """The leading comment block of an overrides file (everything before the YAML data),
    preserved verbatim across rewrites so the schema notes survive promotion."""
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    header: list[str] = []
    for ln in lines:
        if _DATA_LINE.match(ln):
            break
        header.append(ln)
    return "".join(header)


def preview(proposals: list[dict], status: str | None, board_path: Path) -> None:
    sel = [p for p in proposals if status is None or p.get("status") == status]
    counts: dict[str, int] = {}
    for p in proposals:
        counts[p.get("status", "?")] = counts.get(p.get("status", "?"), 0) + 1
    print(f"proposals: {len(proposals)} total ({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))})")
    if not sel:
        print(f"none with status={status!r}." if status else "none.")
        return
    if not board_path.exists():
        raise SystemExit(f"board {board_path} not found — pass --board or generate it first.")
    board = pd.read_parquet(board_path)

    entries = parse_overrides([strip_to_entry(p) for p in sel], source="proposals")
    after = apply_overrides(board, entries).set_index("PLAYER_ID")
    before = board.set_index("PLAYER_ID")[["PLAYER_NAME", "fpts_pg"]]
    key_to_pid = {name_key(n): pid for pid, n in board.set_index("PLAYER_ID")["PLAYER_NAME"].items()}

    rows = []
    for p, e in zip(sel, entries):
        pid = key_to_pid.get(e["name_key"])
        if pid is None:
            rows.append({"player": p["name"], "status": p.get("status"), "on_board": "NO",
                         "action": _action_str(p["action"])})
            continue
        rows.append({
            "player": before.loc[pid, "PLAYER_NAME"], "status": p.get("status"),
            "action": _action_str(p["action"]),
            "fpts_old": round(float(before.loc[pid, "fpts_pg"]), 2),
            "fpts_new": round(float(after.loc[pid, "fpts_pg"]), 2),
            "rank_old": int(after.loc[pid, "model_rank"]),
            "rank_new": int(after.loc[pid, "rank"]),
        })
    with pd.option_context("display.width", 200):
        print(pd.DataFrame(rows).to_string(index=False))
    print("\n(rank_new is the byproduct of re-sorting on fpts — never set directly.)")


def _action_str(action) -> str:
    if action == "none":
        return "none"
    (k, v), = action.items()
    return f"{k}:{float(v):+g}"


def promote(proposals: list[dict], overrides_path: Path) -> None:
    approved = [p for p in proposals if p.get("status") == "approved"]
    if not approved:
        print("no proposals with status=approved — nothing to promote.")
        return

    entries = [strip_to_entry(p) for p in approved]
    parse_overrides(entries, source="approved proposals")  # validate before touching the file
    bad = [e["name"] for e in entries if isinstance(e["action"], dict) and "rank_delta" in e["action"]]
    if bad:
        raise SystemExit(f"rank_delta is not allowed in this workflow (use fpts_delta): {bad}")

    existing = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or []
    have = {(name_key(e["name"]), str(pd.Timestamp(e["date"]).date())) for e in existing}
    promoted, skipped = [], []
    for e in entries:
        key = (name_key(e["name"]), str(pd.Timestamp(e["date"]).date()))
        (skipped if key in have else promoted).append(e)
        have.add(key)

    merged = existing + promoted
    body = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True, default_flow_style=False)
    overrides_path.write_text(_split_header(overrides_path) + body, encoding="utf-8")

    from fantasy_nba.models.analyst import load_overrides
    load_overrides(overrides_path)  # re-validate the written file
    print(f"promoted {len(promoted)} → {overrides_path.name}"
          + (f"; skipped {len(skipped)} already present" if skipped else ""))
    for e in promoted:
        print(f"  + {e['name']:<20} {_action_str(e['action'])}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Preview / promote analyst proposals (workflow v2).")
    ap.add_argument("--proposals", default=str(CONFIG_DIR / "analyst_proposals.yaml"))
    ap.add_argument("--overrides", default=str(CONFIG_DIR / "analyst_overrides.yaml"))
    ap.add_argument("--board", default=str(PROCESSED_DIR / "learned_2026-27.parquet"),
                    help="Board for the preview's fpts→rank impact.")
    ap.add_argument("--status", default=None, help="Filter the preview by status.")
    ap.add_argument("--promote", action="store_true",
                    help="Copy status=approved proposals into the overrides file (idempotent).")
    args = ap.parse_args()

    proposals = load_proposals(Path(args.proposals))
    if args.promote:
        promote(proposals, Path(args.overrides))
    else:
        preview(proposals, args.status, Path(args.board))


if __name__ == "__main__":
    main()
