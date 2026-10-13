"""Prepare the immutable, rationale-free EXP-029 preseason board pair.

The 2026-10-14 user hold removes this from the routine calendar. Even a preview
requires explicit final-review authorization in a separately requested session.
Writing also requires the local preflight and operator attestations for the ESPN
mock verification and analyst re-review. It never pulls data, edits overrides,
updates the live board, or stages/commits the frozen outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fantasy_nba.config import ROOT
from fantasy_nba.models.analyst import apply_overrides, load_overrides
from fantasy_nba.models.value import load_league
from fantasy_nba.scoring import load_scoring
from scripts.pre_draft_preflight import audit


REQUIRED = {"PLAYER_ID", "PLAYER_NAME", "rank", "gp", "mpg", "fpts_pg", "fpts_total"}
MODEL_COLUMNS = REQUIRED | {
    "TEAM_ABBREVIATION", "target_season", "target_age", "fgm", "fga", "fg3m",
    "ftm", "fta", "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pts",
    "returning_vet", "inj_chronic_flag", "fpts_p10", "fpts_p25", "fpts_p50",
    "fpts_p75", "fpts_p90", "fpts_median", "risk", "draft_value", "breakout_p",
    "ps_mpg", "ps_mpg_delta", "ps_start_share",
}
ANALYST_COLUMNS = {"model_rank", "analyst_action", "analyst_category",
                   "analyst_date", "analyst_base_fpts"}


def _validate_board(frame: pd.DataFrame, allowed: set[str], label: str) -> None:
    missing = REQUIRED - set(frame)
    unexpected = set(frame) - allowed
    if missing or unexpected:
        raise ValueError(f"{label} columns need review: missing {sorted(missing)}, unexpected {sorted(unexpected)}")
    if frame.empty or frame["PLAYER_ID"].isna().any() or frame["PLAYER_ID"].duplicated().any():
        raise ValueError(f"{label} needs nonempty, unique player IDs")
    if not frame["rank"].tolist() == list(range(1, len(frame) + 1)):
        raise ValueError(f"{label} ranks must be consecutive in row order")
    if not np.isfinite(pd.to_numeric(frame["fpts_pg"], errors="coerce").to_numpy(dtype=float)).all():
        raise ValueError(f"{label} contains nonfinite FP/G")


def build_freeze_pair(model: pd.DataFrame, entries: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use the approved arithmetic, then remove private rationale before publication."""
    _validate_board(model, MODEL_COLUMNS, "Model board A")
    analyst = apply_overrides(model, entries, cfg=load_scoring())
    if "analyst_rationale" not in analyst:
        raise ValueError("Analyst board B has no rationale field to redact")
    analyst = analyst.drop(columns=["analyst_rationale"])
    _validate_board(analyst, MODEL_COLUMNS | ANALYST_COLUMNS, "Analyst board B")
    if set(model["PLAYER_ID"]) != set(analyst["PLAYER_ID"]):
        raise ValueError("Board A/B player universes differ")
    source_rank = model.set_index("PLAYER_ID")["rank"]
    carried_rank = analyst.set_index("PLAYER_ID")["model_rank"]
    if not source_rank.sort_index().equals(carried_rank.sort_index()):
        raise ValueError("Board B does not preserve each player's model rank")
    return model.copy(), analyst


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_pair(model: pd.DataFrame, analyst: pd.DataFrame, model_out: Path,
               analyst_out: Path, manifest_out: Path, source: Path,
               overrides: Path, scoring: Path, as_of: date) -> dict:
    """Write once; never replace a prior freeze or leave partial staging files."""
    if "analyst_rationale" in analyst:
        raise ValueError("Private analyst rationale cannot be frozen for publication")
    _validate_board(model, MODEL_COLUMNS, "Model board A")
    _validate_board(analyst, MODEL_COLUMNS | ANALYST_COLUMNS, "Analyst board B")
    outputs = (model_out, analyst_out, manifest_out)
    if any(path.exists() for path in outputs):
        raise FileExistsError("A preseason freeze output already exists; never overwrite it")
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    staged = [path.with_name(path.name + ".staging") for path in outputs]
    if any(path.exists() for path in staged):
        raise FileExistsError("An earlier freeze staging file exists; inspect it before retrying")
    created = []
    try:
        model.to_parquet(staged[0], index=False)
        analyst.to_parquet(staged[1], index=False)
        manifest = {
            "schema": 1, "as_of": as_of.isoformat(), "model": "learned_ps",
            "player_count": len(model), "reviewed": True, "mock_verified": True,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "source_sha256": _sha(source), "overrides_sha256": _sha(overrides),
            "scoring_sha256": _sha(scoring),
            "frozen_model_sha256": _sha(staged[0]),
            "frozen_analyst_sha256": _sha(staged[1]),
        }
        staged[2].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        for temp, final in zip(staged, outputs):
            os.link(temp, final)  # Exclusive creation: never replace a freeze created meanwhile.
            created.append(final)
            temp.unlink()
        return manifest
    except Exception:
        for path in (*staged, *created):
            if path.exists():
                path.unlink()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--final-review-authorized", action="store_true",
                        help="Use only in the separate final-review session explicitly requested by the user.")
    parser.add_argument("--write", action="store_true", help="Write the immutable board pair after all gates pass.")
    parser.add_argument("--reviewed", action="store_true", help="Attest that every effective analyst entry was re-reviewed.")
    parser.add_argument("--mock-verified", action="store_true", help="Attest that ESPN mock latency and manual fallback were verified.")
    args = parser.parse_args()
    if not args.final_review_authorized:
        print("Projection freeze is paused by the 2026-10-14 user direction. "
              "Use --final-review-authorized only in a separately requested final-review session.")
        return 2
    as_of = date.fromisoformat(args.as_of)
    report = audit(ROOT, as_of, load_league())
    if not report["ready_for_human_review"]:
        print("Freeze blocked by pre-draft preflight:")
        for check in report["checks"]:
            if check["status"] != "ready":
                print(f"  {check['key']}: {check['detail']}")
        return 2
    if args.write and not (args.reviewed and args.mock_verified):
        parser.error("--write requires both --reviewed and --mock-verified")
    target = report["target"]
    source = ROOT / "data/processed" / f"learned_ps_{target}.parquet"
    overrides = ROOT / "config/analyst_overrides.yaml"
    scoring = ROOT / "config/scoring.yaml"
    model, analyst = build_freeze_pair(pd.read_parquet(source), load_overrides(overrides))
    print(f"Validated {len(model)} model/analyst players; private rationale removed from the freeze pair.")
    if not args.write:
        print("Preview only. In the authorized final-review session, complete human gates "
              "and use --write --reviewed --mock-verified to freeze.")
        return 0
    stem = ROOT / "data/processed" / f"frozen_{target}_preseason"
    model_out = stem.with_name(stem.name + "_model.parquet")
    analyst_out = stem.with_name(stem.name + "_analyst.parquet")
    manifest_out = stem.with_name(stem.name + "_manifest.json")
    write_pair(model, analyst, model_out, analyst_out, manifest_out,
               source, overrides, scoring, as_of)
    print(f"Wrote immutable freeze pair and manifest. Verify, append the dated EXP-029 ledger note, "
          f"then git add -f {model_out.relative_to(ROOT)} {analyst_out.relative_to(ROOT)} {manifest_out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
