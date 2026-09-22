from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "scripts" / "reconcile_external_projection.py"
SPEC = importlib.util.spec_from_file_location("reconcile_external_projection", SCRIPT)
RECONCILE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RECONCILE)


def _line(name: str, fpts: float, mpg: float, rank: int = 1) -> dict:
    return {
        "rank": rank, "PLAYER_ID": rank, "PLAYER_NAME": name, "fpts_pg": fpts,
        "mpg": mpg, "gp": 70, "pts": 20.0, "fg3m": 2.0, "fgm": 7.0, "fga": 15.0,
        "ftm": 4.0, "fta": 5.0, "reb": 6.0, "ast": 5.0, "stl": 1.0, "blk": 0.5,
        "tov": 2.0,
    }


def test_build_review_flags_strict_threshold_and_separates_source_only() -> None:
    model = pd.DataFrame([_line("Role Player", 25.0, 25.0), _line("Rate Player", 30.0, 30.0, 2)])
    current = model.copy()
    current["analyst_action"] = ""
    current["analyst_category"] = ""
    current["analyst_date"] = ""
    current["analyst_rationale"] = ""
    external = pd.DataFrame([
        {"external_rank": 1, "player": "Role Player", "team": "AAA", "pos": "G",
         "external_fpts_pg": 29.0, "gp": 70, "mpg": 29.0, "name_key": "role player",
         "pts": 22.0, "fg3m": 2.0, "fgm": 8.0, "fga": 16.0, "ftm": 4.0,
         "fta": 5.0, "reb": 6.0, "ast": 5.0, "stl": 1.0, "blk": 0.5, "tov": 2.0},
        {"external_rank": 2, "player": "Rate Player", "team": "BBB", "pos": "F",
         "external_fpts_pg": 31.5, "gp": 70, "mpg": 30.0, "name_key": "rate player",
         "pts": 21.5, "fg3m": 2.0, "fgm": 7.0, "fga": 15.0, "ftm": 4.0,
         "fta": 5.0, "reb": 6.0, "ast": 5.0, "stl": 1.0, "blk": 0.5, "tov": 2.0},
        {"external_rank": 3, "player": "Rookie Only", "team": "CCC", "pos": "C",
         "external_fpts_pg": 24.0, "gp": 70, "mpg": 22.0, "name_key": "rookie only",
         "pts": 10.0, "fg3m": 0.0, "fgm": 4.0, "fga": 7.0, "ftm": 2.0,
         "fta": 3.0, "reb": 8.0, "ast": 2.0, "stl": 0.5, "blk": 1.0, "tov": 1.0},
    ])

    got = RECONCILE.build_review(external, model, current, threshold=1.5, top_n=200)
    rows = got.set_index("player")

    assert bool(rows.loc["Role Player", "flag_gt_threshold"])
    assert rows.loc["Role Player", "proposal_target_fpts"] == 29.0
    assert rows.loc["Role Player", "lean"] == "external closer"
    assert not bool(rows.loc["Rate Player", "flag_gt_threshold"])  # strict > 1.5
    assert rows.loc["Rookie Only", "match_status"] == "source_only"
    assert rows.loc["Rookie Only", "proposal_status"] == "source_only"

    output = Path.cwd() / "data" / "processed" / "test-review-checklist.md"
    try:
        RECONCILE.write_markdown(got, output, threshold=1.5, stamp="2026-09-22")
        text = output.read_text(encoding="utf-8")
        assert "## Decision checklist" in text
        assert "| 1 | Role Player | 25.00 | 29.00 | 29.00 | external closer | Role gap:" in text
        assert "## Source-only seed checklist" in text
        assert "| 3 | Rookie Only | 24.00 | 22.0 | [ ] | [ ] |" in text
    finally:
        output.unlink(missing_ok=True)

    html_output = Path.cwd() / "data" / "processed" / "test-review-clickable.html"
    try:
        RECONCILE.write_html(got, html_output, threshold=1.5, stamp="2026-09-22")
        page = html_output.read_text(encoding="utf-8")
        assert "Current</th><th>External</th><th>Proposed" in page
        assert "Quick justification</th>" in page
        assert 'name="matched:role player" value="yes"' in page
        assert 'name="matched:role player" value="no"' in page
        assert "Export decisions JSON" in page
        assert "source_only:rookie only" in page
    finally:
        html_output.unlink(missing_ok=True)


def test_sync_final_decisions_records_approved_rejected_and_retained() -> None:
    review = pd.DataFrame([
        {
            "player": "Approved Player", "name_key": "approved player", "match_status": "matched",
            "flag_gt_threshold": True, "proposal_status": "proposed", "current_fpts_pg": 30.0,
            "current_mpg": 30.0, "proposal_target_fpts": 34.0, "proposal_target_mpg": 32.0,
            "proposal_action_vs_model": "old", "quick_justification": "old", "analysis": "old",
        },
        {
            "player": "Rejected Player", "name_key": "rejected player", "match_status": "matched",
            "flag_gt_threshold": True, "proposal_status": "proposed", "current_fpts_pg": 31.0,
            "current_mpg": 31.0, "proposal_target_fpts": 28.0, "proposal_target_mpg": 29.0,
            "proposal_action_vs_model": "old", "quick_justification": "old", "analysis": "old",
        },
        {
            "player": "Retained Player", "name_key": "retained player", "match_status": "matched",
            "flag_gt_threshold": True, "proposal_status": "retain_current", "current_fpts_pg": 32.0,
            "current_mpg": 32.0, "proposal_target_fpts": 32.0, "proposal_target_mpg": 32.0,
            "proposal_action_vs_model": "retain", "quick_justification": "Fresh evidence.",
            "analysis": "retained",
        },
        {
            "player": "Seed Player", "name_key": "seed player", "match_status": "source_only",
            "flag_gt_threshold": False, "proposal_status": "source_only", "current_fpts_pg": float("nan"),
            "current_mpg": float("nan"), "proposal_target_fpts": 20.0, "proposal_target_mpg": 20.0,
            "proposal_action_vs_model": "seed", "quick_justification": "seed", "analysis": "seed",
        },
    ])
    entries = [
        {
            "name": "Approved Player", "status": "approved",
            "action": {"target_mpg": 33.0, "fpts_delta": 0.25},
            "sizing": {"target_fpts": 35.5, "target_mpg": 33.0},
            "rationale": "Approved rationale.", "triangulation": "Approved analysis.",
        },
        {
            "name": "Rejected Player", "status": "rejected",
            "action": {"target_mpg": 29.0, "fpts_delta": -1.0},
            "sizing": {"target_fpts": 28.0, "target_mpg": 29.0},
        },
    ]

    got = RECONCILE.sync_final_decisions(review, entries).set_index("player")

    assert got.loc["Approved Player", "final_decision"] == "approved change"
    assert got.loc["Approved Player", "final_fpts_pg"] == 35.5
    assert got.loc["Approved Player", "proposal_action_vs_model"] == "target_mpg:33.0|fpts_delta:+0.25"
    assert got.loc["Approved Player", "analysis"] == "Approved analysis."
    assert got.loc["Rejected Player", "final_decision"] == "retain current"
    assert got.loc["Rejected Player", "final_fpts_pg"] == 31.0
    assert got.loc["Retained Player", "final_decision"] == "retain current"
    assert got.loc["Retained Player", "decision_note"] == "Fresh evidence."
    assert got.loc["Seed Player", "final_decision"] == "pending seed review"
