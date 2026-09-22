"""Compare a dated full external projection with model A and the effective analyst board.

The output is a top-200 review sheet, not an automatic model mutation.  Material matched
disagreements (strictly more than ``--threshold`` FP/G) receive a proposed target and a
player-specific decomposition.  Source-only players are reported separately because a
missing model value is not a numeric disagreement.

By default, rate-only disagreements are shrunk one-third toward the current board: the
learned model is strongest on rates, while current-role minutes are the external source's
highest-value information.  Named fresh analyst judgments are retained explicitly.
Use ``--append-proposals`` to append actionable entries to the normal review queue; nothing
is approved or promoted by that operation. After the normal approval/promotion workflow,
``--sync-decisions`` records the queue decisions in the preserved review snapshot without
recomputing its comparison against the now-updated Board B.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import yaml

from fantasy_nba.config import CONFIG_DIR, PROCESSED_DIR, RAW_DIR
from fantasy_nba.models.analyst import name_key
from fantasy_nba.scoring import load_scoring, score_frame


STAT_COLS = ("pts", "fg3m", "fgm", "fga", "ftm", "fta", "reb", "ast", "stl", "blk", "tov")

# These values were deliberately set from newer evidence or direct user judgment.  A full
# sweep must surface their disagreement without erasing the evidence that produced Board B.
RETAIN_CURRENT = {
    "victor wembanyama": "the current 62.0 is an explicit user-set top-four judgment",
    "jalen johnson": "today's BBM pass already discounts the external line for CJ McCollum's effect",
    "stephen curry": "today's BBM pass already applies the specific persistent-knee concern",
    "josh giddey": "the 33.5-MPG target is backed by BBM's explicit 33-34 minute range",
    "matas buzelis": "the current line includes BBM's explicit 32 MPG and higher post-departure usage",
    "ayo dosunmu": "the 29.5-MPG target is backed by BBM's explicit 29-30 minute role",
}


def _pg_rank(values: pd.Series) -> pd.Series:
    return values.rank(method="first", ascending=False, na_option="bottom").astype("Int64")


def _fmt_action(target_mpg: float, delta: float) -> str:
    return f"target_mpg:{target_mpg:.1f}|fpts_delta:{delta:+.2f}"


def _top_stat_drivers(row: pd.Series, weights: dict[str, float], n: int = 3) -> str:
    parts: list[tuple[float, str]] = []
    labels = {"fg3m": "3PM", "tov": "TO", "reb": "REB", "ast": "AST",
              "stl": "STL", "blk": "BLK", "pts": "PTS", "fgm": "FGM",
              "fga": "FGA", "ftm": "FTM", "fta": "FTA"}
    for stat in STAT_COLS:
        ext, cur = row.get(f"{stat}_external"), row.get(f"{stat}_current")
        if pd.isna(ext) or pd.isna(cur):
            continue
        contribution = (float(ext) - float(cur)) * weights.get(stat, 0.0)
        if abs(contribution) >= 0.15:
            parts.append((abs(contribution), f"{labels[stat]} {contribution:+.1f} FP"))
    return ", ".join(text for _, text in sorted(parts, reverse=True)[:n]) or "no large single-stat gap"


def build_review(external: pd.DataFrame, model: pd.DataFrame, current: pd.DataFrame,
                 threshold: float = 1.5, top_n: int = 200) -> pd.DataFrame:
    """Return one auditable review row for each source player in the requested pool."""
    cfg = load_scoring()
    weights = dict(cfg.weights)
    ext = external.nsmallest(top_n, "external_rank").copy()
    ext = ext.rename(columns={"mpg": "external_mpg", "gp": "external_gp",
                              **{s: f"{s}_external" for s in STAT_COLS}})
    a = model.copy()
    b = current.copy()
    for frame in (a, b):
        frame["name_key"] = frame["PLAYER_NAME"].map(name_key)
    a["model_pg_rank"] = _pg_rank(a["fpts_pg"])
    b["current_pg_rank"] = _pg_rank(b["fpts_pg"])

    model_cols = ["name_key", "PLAYER_ID", "PLAYER_NAME", "fpts_pg", "mpg", "gp",
                  "model_pg_rank", *[c for c in STAT_COLS if c in a.columns]]
    current_cols = ["name_key", "fpts_pg", "mpg", "gp", "current_pg_rank",
                    "analyst_action", "analyst_category", "analyst_date", "analyst_rationale",
                    *[c for c in STAT_COLS if c in b.columns]]
    joined = ext.merge(a[model_cols], on="name_key", how="left", suffixes=("_external", "_model"))
    joined = joined.merge(b[current_cols], on="name_key", how="left", suffixes=("", "_current"))

    # The second merge leaves model columns with their suffix and current columns with the
    # explicit _current suffix only when names overlap; normalize the scalar labels here.
    rename = {
        "fpts_pg": "current_fpts_pg", "mpg": "current_mpg", "gp": "current_gp",
        "fpts_pg_model": "model_fpts_pg", "mpg_model": "model_mpg", "gp_model": "model_gp",
    }
    joined = joined.rename(columns=rename)
    for stat in STAT_COLS:
        if f"{stat}_model" not in joined and stat in joined:
            joined = joined.rename(columns={stat: f"{stat}_model"})
        if f"{stat}_current" not in joined and f"{stat}_external" in joined:
            # pandas only suffixes the external/model merge first, then the current merge.
            candidate = f"{stat}"
            if candidate in joined:
                joined = joined.rename(columns={candidate: f"{stat}_current"})

    # Be explicit rather than relying on pandas' suffix behavior for the fields used below.
    current_lookup = b.set_index("name_key")
    model_lookup = a.set_index("name_key")
    for prefix, lookup in (("current", current_lookup), ("model", model_lookup)):
        for col in ("fpts_pg", "mpg", "gp", *STAT_COLS):
            if col in lookup:
                joined[f"{prefix}_{col}" if col in {"fpts_pg", "mpg", "gp"}
                       else f"{col}_{prefix}"] = joined["name_key"].map(lookup[col])

    joined["match_status"] = np.where(joined["model_fpts_pg"].notna(), "matched", "source_only")
    joined["fpts_gap_external_minus_current"] = (
        joined["external_fpts_pg"] - joined["current_fpts_pg"]
    )
    joined["abs_fpts_gap"] = joined["fpts_gap_external_minus_current"].abs()
    joined["flag_gt_threshold"] = (
        joined["match_status"].eq("matched") & joined["abs_fpts_gap"].gt(threshold)
    )
    joined["model_gap_external_minus_model"] = joined["external_fpts_pg"] - joined["model_fpts_pg"]
    joined["mpg_gap_external_minus_current"] = joined["external_mpg"] - joined["current_mpg"]
    joined["gp_gap_external_minus_current"] = joined["external_gp"] - joined["current_gp"]

    rows: list[dict] = []
    for _, r in joined.iterrows():
        out = r.to_dict()
        if r["match_status"] == "source_only":
            out.update({
                "lean": "source seed (no model comparison)",
                "proposal_target_fpts": float(r["external_fpts_pg"]),
                "proposal_target_mpg": float(r["external_mpg"]),
                "proposal_action_vs_model": "external-projection seed",
                "proposal_status": "source_only",
                "quick_justification": "No learned-model row; use only as a clearly labeled external seed.",
                "analysis": (
                    f"No learned-model row exists, so the 1.5 FP/G test is undefined. "
                    f"Keep the clearly flagged external seed at {r['external_fpts_pg']:.1f} "
                    f"FP/G and {r['external_mpg']:.1f} MPG pending the normal rookie/returning-player review."
                ),
            })
            rows.append(out)
            continue
        if not bool(r["flag_gt_threshold"]):
            out.update({"lean": "within threshold", "proposal_target_fpts": np.nan,
                        "proposal_target_mpg": np.nan, "proposal_action_vs_model": "",
                        "proposal_status": "not_flagged", "quick_justification": "",
                        "analysis": ""})
            rows.append(out)
            continue

        gap = float(r["fpts_gap_external_minus_current"])
        current_mpg = float(r["current_mpg"])
        external_mpg = float(r["external_mpg"])
        minutes_component = (external_mpg - current_mpg) * float(r["current_fpts_pg"]) / current_mpg
        rate_component = gap - minutes_component
        out["minutes_component"] = round(minutes_component, 2)
        out["rate_component"] = round(rate_component, 2)
        drivers = _top_stat_drivers(r, weights)

        retained_reason = RETAIN_CURRENT.get(str(r["name_key"]))
        if retained_reason:
            target_fpts = float(r["current_fpts_pg"])
            target_mpg = current_mpg
            lean = "current closer"
            proposal_status = "retain_current"
            action = "retain current effective override"
            quick = retained_reason[0].upper() + retained_reason[1:] + "."
            verdict = f"Current closer: {retained_reason}. No superseding entry is proposed."
        elif abs(external_mpg - current_mpg) >= 1.5:
            target_fpts = float(r["external_fpts_pg"])
            target_mpg = external_mpg
            lean = "external closer"
            proposal_status = "proposed"
            quick = (
                f"Role gap: external {external_mpg:.1f} vs current {current_mpg:.1f} MPG "
                f"({minutes_component:+.1f} FP); minutes are the model's weak layer."
            )
            verdict = (
                "External closer: the material minutes disagreement is the model's known weak "
                "layer, and the source supplies a complete current-role line."
            )
            action = ""
        else:
            # Rate projections are the learned model's stronger layer.  Move two-thirds of
            # the way to the trusted current source rather than copying one rounded line.
            target_fpts = round(float(r["current_fpts_pg"]) + (2 / 3) * gap, 1)
            target_mpg = round(current_mpg + (2 / 3) * (external_mpg - current_mpg), 1)
            lean = "external closer (blended)"
            proposal_status = "proposed"
            first_driver = drivers.split(",", 1)[0]
            quick = (
                f"Minutes are close; rate remainder is {rate_component:+.1f} FP, led by "
                f"{first_driver}; move two-thirds toward the source."
            )
            verdict = (
                "External closer, but the minutes anchors differ by less than 1.5 MPG, so this "
                "is not a clear role reset; retain one-third of the learned/analyst estimate "
                "because historical rates are the model's strongest layer."
            )

        if proposal_status == "proposed":
            base_fpts = float(r["model_fpts_pg"])
            base_mpg = float(r["model_mpg"])
            residual = target_fpts - base_fpts * target_mpg / base_mpg
            action = _fmt_action(target_mpg, residual)
            out["proposal_fpts_delta_vs_model"] = round(residual, 2)
        out.update({
            "lean": lean,
            "proposal_target_fpts": round(target_fpts, 2),
            "proposal_target_mpg": round(target_mpg, 1),
            "proposal_action_vs_model": action,
            "proposal_status": proposal_status,
            "quick_justification": quick,
            "analysis": (
                f"External is {gap:+.2f} FP/G versus current. Its {external_mpg:.1f} versus "
                f"{current_mpg:.1f} MPG explains {minutes_component:+.2f}; the remaining "
                f"{rate_component:+.2f} is rate. Largest line drivers: {drivers}. {verdict} "
                f"Proposed level: {target_fpts:.1f} FP/G at {target_mpg:.1f} MPG."
            ),
        })
        rows.append(out)

    result = pd.DataFrame(rows)
    lead = [
        "match_status", "flag_gt_threshold", "external_rank", "player", "team", "pos",
        "external_fpts_pg", "current_fpts_pg", "model_fpts_pg",
        "fpts_gap_external_minus_current", "abs_fpts_gap", "external_mpg", "current_mpg", "model_mpg",
        "lean", "proposal_target_fpts", "proposal_target_mpg", "proposal_action_vs_model",
        "proposal_status", "quick_justification", "analysis",
    ]
    return result[[c for c in lead if c in result] + [c for c in result if c not in lead]]


def proposal_entries(review: pd.DataFrame, stamp: str) -> list[dict]:
    entries = []
    for r in review[review["proposal_status"].eq("proposed")].itertuples(index=False):
        base_fpts, base_mpg = float(r.model_fpts_pg), float(r.model_mpg)
        target_fpts, target_mpg = float(r.proposal_target_fpts), float(r.proposal_target_mpg)
        delta = round(target_fpts - base_fpts * target_mpg / base_mpg, 2)
        entries.append({
            "name": r.player,
            "date": stamp,
            "category": "role" if abs(float(r.external_mpg) - float(r.current_mpg)) >= 1.5 else "other",
            "action": {"target_mpg": target_mpg, "fpts_delta": delta},
            "preview": (
                f"current {float(r.current_fpts_pg):.2f} fpts/g -> proposal "
                f"{target_fpts:.2f} at {target_mpg:.1f} mpg"
            ),
            "rationale": (
                f"Trusted external projection {stamp} full-line reconciliation: source "
                f"{float(r.external_fpts_pg):.1f} fpts/g at {float(r.external_mpg):.1f} mpg versus "
                f"current Board B {float(r.current_fpts_pg):.2f} at {float(r.current_mpg):.1f}."
            ),
            "sizing": {
                "base_fpts": round(base_fpts, 2),
                "base_mpg": round(base_mpg, 1),
                "target_mpg": target_mpg,
                "target_fpm": round(target_fpts / target_mpg, 4),
                "target_fpts": target_fpts,
            },
            "status": "proposed",
            "triangulation": r.analysis,
        })
    return entries


def load_external_batch(path: Path, stamp: str) -> list[dict]:
    """Load one dated external-sweep batch from the append-only proposal queue."""
    marker = f"# ============ External projection full sweep {stamp} ============"
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        raise ValueError(f"external proposal batch {stamp} not found in {path}")
    entries = yaml.safe_load(text.split(marker, 1)[1]) or []
    if not isinstance(entries, list):
        raise ValueError(f"external proposal batch {stamp} is not a YAML list")
    if any(str(entry.get("date")) != stamp for entry in entries):
        raise ValueError(f"external proposal batch {stamp} contains a different date")
    return entries


def sync_final_decisions(review: pd.DataFrame, entries: list[dict]) -> pd.DataFrame:
    """Attach reviewed queue decisions to the original, pre-promotion comparison."""
    result = review.copy()
    by_name = {name_key(str(entry["name"])): entry for entry in entries}
    result["final_decision"] = ""
    result["final_fpts_pg"] = np.nan
    result["final_mpg"] = np.nan
    result["final_action"] = ""
    result["decision_note"] = ""

    missing: list[str] = []
    for idx, row in result.iterrows():
        if row["match_status"] == "source_only":
            result.at[idx, "final_decision"] = "pending seed review"
            result.at[idx, "decision_note"] = "No learned-model row; external seed was not promoted."
            continue
        if not bool(row["flag_gt_threshold"]):
            continue

        entry = by_name.get(str(row["name_key"]))
        if entry is None:
            if row["proposal_status"] == "retain_current":
                result.at[idx, "final_decision"] = "retain current"
                result.at[idx, "final_fpts_pg"] = float(row["current_fpts_pg"])
                result.at[idx, "final_mpg"] = float(row["current_mpg"])
                result.at[idx, "final_action"] = "retain current effective override"
                result.at[idx, "decision_note"] = str(row["quick_justification"])
                continue
            missing.append(str(row["player"]))
            continue

        status = str(entry.get("status", "proposed"))
        if status == "approved":
            sizing = entry["sizing"]
            action = entry["action"]
            target_fpts = float(sizing["target_fpts"])
            target_mpg = float(sizing["target_mpg"])
            delta = float(action["fpts_delta"])
            formatted_action = _fmt_action(target_mpg, delta)
            result.at[idx, "proposal_target_fpts"] = target_fpts
            result.at[idx, "proposal_target_mpg"] = target_mpg
            result.at[idx, "proposal_action_vs_model"] = formatted_action
            result.at[idx, "proposal_status"] = "approved"
            result.at[idx, "final_decision"] = "approved change"
            result.at[idx, "final_fpts_pg"] = target_fpts
            result.at[idx, "final_mpg"] = target_mpg
            result.at[idx, "final_action"] = formatted_action
            result.at[idx, "decision_note"] = str(entry.get("rationale", ""))
            result.at[idx, "analysis"] = str(entry.get("triangulation", row["analysis"]))
            result.at[idx, "quick_justification"] = (
                f"Final review approved {target_fpts:.1f} FP/G at {target_mpg:.1f} MPG."
            )
        elif status == "rejected":
            current_fpts = float(row["current_fpts_pg"])
            current_mpg = float(row["current_mpg"])
            result.at[idx, "proposal_status"] = "rejected"
            result.at[idx, "final_decision"] = "retain current"
            result.at[idx, "final_fpts_pg"] = current_fpts
            result.at[idx, "final_mpg"] = current_mpg
            result.at[idx, "final_action"] = "retain current effective override"
            result.at[idx, "decision_note"] = (
                f"Reviewed and rejected the external change; retained the existing effective "
                f"override at {current_fpts:.2f} FP/G and {current_mpg:.1f} MPG."
            )
            result.at[idx, "quick_justification"] = str(result.at[idx, "decision_note"])
            result.at[idx, "analysis"] = (
                f"{row['analysis']} Final decision: retain the current effective override."
            )
        else:
            raise ValueError(f"proposal for {entry['name']} is still {status!r}")

    if missing:
        raise ValueError("flagged proposals missing from decision batch: " + ", ".join(missing))
    return result


def write_markdown(review: pd.DataFrame, path: Path, threshold: float, stamp: str) -> None:
    flagged = review[review["flag_gt_threshold"]].copy()
    source_only = review[review["match_status"].eq("source_only")]
    finalized = "final_decision" in review and bool(flagged["final_decision"].ne("").all())
    lines = [
        f"# External projection review — {stamp}", "",
        f"Scope: source top {len(review)}; strict flag threshold `abs(external - current) > {threshold:g}` FP/G.",
        f"Matched: {(review.match_status == 'matched').sum()} · flagged: {len(flagged)} · source-only: {len(source_only)}.",
        "Current means effective Board B; the pure learned-model value remains in the CSV.", "",
        "## Final decisions" if finalized else "## Decision checklist", "",
    ]
    if finalized:
        approved = int(flagged["final_decision"].eq("approved change").sum())
        retained = int(flagged["final_decision"].eq("retain current").sum())
        lines.extend([
            f"Finalized: {approved} changes approved and {retained} current values retained. "
            "Source-only seeds remain pending.", "",
            "| Rank | Player | Current | External | Reviewed proposal | Final FP/G | Final MPG | Decision | Quick justification |",
            "|---:|---|---:|---:|---:|---:|---:|---|---|",
        ])
    else:
        lines.extend([
            "Check exactly one box per player. For proposed changes, **Yes** accepts the proposed level and **No** keeps the current value. For a `keep current` recommendation, **Yes** agrees and **No** flags it for reconsideration. Nothing is promoted merely by editing this file.", "",
            "| Rank | Player | Current | External | Proposed | Recommendation | Quick justification | Yes | No |",
            "|---:|---|---:|---:|---:|---|---|:---:|:---:|",
        ])
    for r in flagged.itertuples(index=False):
        recommendation = "keep current" if r.proposal_status == "retain_current" else r.lean
        quick = str(r.quick_justification).replace("|", "\\|")
        if finalized:
            lines.append(
                f"| {int(r.external_rank)} | {r.player} | {float(r.current_fpts_pg):.2f} | "
                f"{float(r.external_fpts_pg):.2f} | {float(r.proposal_target_fpts):.2f} | "
                f"{float(r.final_fpts_pg):.2f} | {float(r.final_mpg):.1f} | "
                f"{r.final_decision} | {quick} |"
            )
        else:
            lines.append(
                f"| {int(r.external_rank)} | {r.player} | {float(r.current_fpts_pg):.2f} | "
                f"{float(r.external_fpts_pg):.2f} | {float(r.proposal_target_fpts):.2f} | "
                f"{recommendation} | {quick} | [ ] | [ ] |"
            )
    lines.extend([
        "", "## Source-only seed checklist", "",
        "These players have no learned-model value, so Yes accepts the external seed and No leaves them without a projection seed.", "",
        "| Rank | Player | Seed FP/G | Seed MPG | Yes | No |",
        "|---:|---|---:|---:|:---:|:---:|",
    ])
    for r in source_only.itertuples(index=False):
        lines.append(
            f"| {int(r.external_rank)} | {r.player} | {float(r.external_fpts_pg):.2f} | "
            f"{float(r.external_mpg):.1f} | [ ] | [ ] |"
        )
    lines.extend(["", "## Detailed analysis", ""])
    for r in flagged.itertuples(index=False):
        lines.extend([
            f"### {int(r.external_rank)}. {r.player} — {r.lean}", "",
            r.analysis, "",
            (f"Final: **{r.final_decision}**, {float(r.final_fpts_pg):.2f} FP/G at "
             f"{float(r.final_mpg):.1f} MPG · `{r.final_action}`."
             if finalized else
             f"Review action: `{r.proposal_action_vs_model}` · status `{r.proposal_status}`."), "",
        ])
    lines.extend(["## Source-only player notes", ""])
    for r in source_only.itertuples(index=False):
        lines.extend([f"- **{r.player}** — {r.analysis}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_html(review: pd.DataFrame, path: Path, threshold: float, stamp: str) -> None:
    """Write a clickable, self-contained version of the Markdown review table.

    Decisions persist in browser localStorage and can be exported as JSON.  The HTML never
    mutates proposals itself; promotion remains behind the normal review gate.
    """
    flagged = review[review["flag_gt_threshold"]].copy()
    source_only = review[review["match_status"].eq("source_only")].copy()
    finalized = "final_decision" in review and bool(flagged["final_decision"].ne("").all())
    rows = []
    decisions_meta = []
    for r in flagged.itertuples(index=False):
        key = f"matched:{r.name_key}"
        recommendation = "keep current" if r.proposal_status == "retain_current" else r.lean
        no_text = "Reconsider" if r.proposal_status == "retain_current" else "Keep current"
        if finalized:
            rows.append(
                f'<tr data-final="true" data-player="{html.escape(str(r.player).lower())}">'
                f'<td class="num">{int(r.external_rank)}</td><td class="player">{html.escape(str(r.player))}</td>'
                f'<td class="num">{float(r.current_fpts_pg):.2f}</td>'
                f'<td class="num">{float(r.external_fpts_pg):.2f}</td>'
                f'<td class="num proposed">{float(r.proposal_target_fpts):.2f}</td>'
                f'<td class="num proposed">{float(r.final_fpts_pg):.2f}</td>'
                f'<td class="num">{float(r.final_mpg):.1f}</td>'
                f'<td><span class="tag">{html.escape(str(r.final_decision))}</span></td>'
                f'<td class="quick">{html.escape(str(r.quick_justification))}</td>'
                f'<td><details><summary>View</summary><div class="analysis">{html.escape(str(r.analysis))}'
                f'<p><code>{html.escape(str(r.final_action))}</code></p></div></details></td></tr>'
            )
        else:
            rows.append(
                f'<tr data-key="{html.escape(key)}" data-player="{html.escape(str(r.player).lower())}">'
                f'<td class="num">{int(r.external_rank)}</td><td class="player">{html.escape(str(r.player))}</td>'
                f'<td class="num">{float(r.current_fpts_pg):.2f}</td>'
                f'<td class="num">{float(r.external_fpts_pg):.2f}</td>'
                f'<td class="num proposed">{float(r.proposal_target_fpts):.2f}</td>'
                f'<td><span class="tag">{html.escape(str(recommendation))}</span></td>'
                f'<td class="quick">{html.escape(str(r.quick_justification))}</td>'
                f'<td class="choice yes"><label><input type="radio" name="{html.escape(key)}" value="yes"> Yes</label></td>'
                f'<td class="choice no"><label><input type="radio" name="{html.escape(key)}" value="no"> {no_text}</label></td>'
                f'<td><details><summary>View</summary><div class="analysis">{html.escape(str(r.analysis))}'
                f'<p><code>{html.escape(str(r.proposal_action_vs_model))}</code></p></div></details></td></tr>'
            )
            decisions_meta.append({"key": key, "player": r.player, "external_rank": int(r.external_rank),
                                   "kind": "matched", "proposal_status": r.proposal_status,
                                   "current_fpts": round(float(r.current_fpts_pg), 2),
                                   "external_fpts": round(float(r.external_fpts_pg), 2),
                                   "proposed_fpts": round(float(r.proposal_target_fpts), 2)})
    source_rows = []
    for r in source_only.itertuples(index=False):
        key = f"source_only:{r.name_key}"
        source_rows.append(
            f'<tr data-key="{html.escape(key)}" data-player="{html.escape(str(r.player).lower())}">'
            f'<td class="num">{int(r.external_rank)}</td><td class="player">{html.escape(str(r.player))}</td>'
            f'<td class="num">{float(r.external_fpts_pg):.2f}</td><td class="num">{float(r.external_mpg):.1f}</td>'
            f'<td class="choice yes"><label><input type="radio" name="{html.escape(key)}" value="yes"> Yes</label></td>'
            f'<td class="choice no"><label><input type="radio" name="{html.escape(key)}" value="no"> No</label></td>'
            f'<td><details><summary>View</summary><div class="analysis">{html.escape(str(r.analysis))}</div></details></td></tr>'
        )
        decisions_meta.append({"key": key, "player": r.player, "external_rank": int(r.external_rank),
                               "kind": "source_only", "external_fpts": round(float(r.external_fpts_pg), 2),
                               "external_mpg": round(float(r.external_mpg), 1)})

    metadata_json = json.dumps(decisions_meta, ensure_ascii=False).replace("</", "<\\/")
    storage_key = f"fantasy-nba-external-review:{stamp}"
    if finalized:
        approved = int(flagged["final_decision"].eq("approved change").sum())
        retained = int(flagged["final_decision"].eq("retain current").sum())
        notice = (
            f"Finalized: {approved} changes approved and {retained} current values retained. "
            "The source-only seed checklist remains open."
        )
        flagged_header = (
            "<th>Rank</th><th>Player</th><th>Current</th><th>External</th>"
            "<th>Reviewed proposal</th><th>Final FP/G</th><th>Final MPG</th>"
            "<th>Decision</th><th>Quick justification</th><th>Analysis</th>"
        )
    else:
        notice = (
            "For proposed changes, <strong>Yes</strong> accepts the proposed value and "
            "<strong>Keep current</strong> rejects it. For “keep current” recommendations, "
            "<strong>Yes</strong> agrees and <strong>Reconsider</strong> flags it for another pass. "
            "Choices save in this browser only until you export them."
        )
        flagged_header = (
            "<th>Rank</th><th>Player</th><th>Current</th><th>External</th><th>Proposed</th>"
            "<th>Recommendation</th><th>Quick justification</th><th>Yes</th><th>No</th><th>Analysis</th>"
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>External projection review — {html.escape(stamp)}</title>
<style>
:root{{--bg:#fff;--panel:#f6f8fa;--text:#1f2328;--muted:#59636e;--line:#d0d7de;--blue:#0969da;--green:#1a7f37;--red:#cf222e}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1500px;margin:auto;padding:24px}} h1{{margin:0 0 6px;font-size:28px}} h2{{margin-top:34px}} .muted{{color:var(--muted)}}
.toolbar{{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:20px 0;padding:12px;background:rgba(246,248,250,.97);border:1px solid var(--line);border-radius:8px}}
input[type=search]{{min-width:260px;padding:7px 10px;border:1px solid var(--line);border-radius:6px}} button,select{{padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}} button.primary{{background:var(--blue);color:#fff;border-color:var(--blue)}}
.progress{{font-weight:600;margin-left:auto}} .bar{{width:150px;height:8px;background:#d8dee4;border-radius:9px;overflow:hidden}} .bar>span{{display:block;height:100%;width:0;background:var(--green)}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:8px}} table{{width:100%;border-collapse:collapse;white-space:nowrap}} th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{position:sticky;top:0;background:var(--panel);z-index:2}} tr:last-child td{{border-bottom:0}} tr.decided-yes{{background:#dafbe1}} tr.decided-no{{background:#ffebe9}} tr.hidden{{display:none}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .player{{font-weight:600}} .proposed{{font-weight:700;color:var(--blue)}} .tag{{display:inline-block;padding:2px 7px;border-radius:999px;background:#ddf4ff;color:#0550ae;font-size:12px}} .quick{{min-width:310px;max-width:430px;white-space:normal;color:var(--muted)}}
.choice label{{display:block;cursor:pointer;font-weight:600}} .yes{{color:var(--green)}} .no{{color:var(--red)}} details{{max-width:460px;white-space:normal}} summary{{color:var(--blue);cursor:pointer}} .analysis{{padding:8px 0;color:var(--muted)}} code{{white-space:normal}}
.notice{{padding:10px 12px;border-left:4px solid var(--blue);background:var(--panel)}} @media(max-width:800px){{main{{padding:12px}}.progress{{margin-left:0}}}}
</style></head><body><main>
<h1>External projection review — {html.escape(stamp)}</h1>
<p class="muted">Source top {len(review)} · {len(flagged)} matched flags above {threshold:g} FP/G · {len(source_only)} source-only seeds.</p>
<p class="notice">{notice}</p>
<div class="toolbar"><input id="search" type="search" placeholder="Search player…"><select id="filter"><option value="all">All</option><option value="pending">Pending</option><option value="yes">Yes</option><option value="no">No / reconsider</option></select><button id="export" class="primary">Export decisions JSON</button><button id="clear">Clear all</button><div class="progress"><span id="count">0 / {len(decisions_meta)}</span><div class="bar"><span id="bar"></span></div></div></div>
<h2>Flagged players</h2><div class="table-wrap"><table><thead><tr>{flagged_header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Source-only seed checklist</h2><p class="muted">Yes accepts the external seed; No leaves the player without a projection seed.</p><div class="table-wrap"><table><thead><tr><th>Rank</th><th>Player</th><th>Seed FP/G</th><th>Seed MPG</th><th>Yes</th><th>No</th><th>Analysis</th></tr></thead><tbody>{''.join(source_rows)}</tbody></table></div>
<script>
const META={metadata_json}; const STORE={json.dumps(storage_key)}; let decisions=JSON.parse(localStorage.getItem(STORE)||'{{}}');
function paint(){{document.querySelectorAll('tr[data-key]').forEach(tr=>{{const v=decisions[tr.dataset.key];tr.classList.toggle('decided-yes',v==='yes');tr.classList.toggle('decided-no',v==='no');const input=v&&tr.querySelector(`input[value="${{v}}"]`);if(input)input.checked=true;}});const n=Object.keys(decisions).length;document.getElementById('count').textContent=`${{n}} / ${{META.length}}`;document.getElementById('bar').style.width=`${{META.length?100*n/META.length:0}}%`;applyFilter();}}
document.querySelectorAll('input[type=radio]').forEach(el=>el.addEventListener('change',e=>{{decisions[e.target.name]=e.target.value;localStorage.setItem(STORE,JSON.stringify(decisions));paint();}}));
function applyFilter(){{const q=document.getElementById('search').value.toLowerCase();const f=document.getElementById('filter').value;document.querySelectorAll('tr[data-player]').forEach(tr=>{{const v=tr.dataset.key&&decisions[tr.dataset.key];const okText=tr.dataset.player.includes(q);const okFilter=f==='all'||(tr.dataset.key&&((f==='pending'&&!v)||v===f));tr.classList.toggle('hidden',!(okText&&okFilter));}});}}
document.getElementById('search').addEventListener('input',applyFilter);document.getElementById('filter').addEventListener('change',applyFilter);
document.getElementById('clear').addEventListener('click',()=>{{if(confirm('Clear every saved decision for this review?')){{decisions={{}};localStorage.removeItem(STORE);document.querySelectorAll('input[type=radio]').forEach(x=>x.checked=false);paint();}}}});
document.getElementById('export').addEventListener('click',()=>{{const rows=META.map(x=>({{...x,decision:decisions[x.key]||'pending'}}));const payload={{review_date:{json.dumps(stamp)},exported_at:new Date().toISOString(),complete:Object.keys(decisions).length===META.length,decisions:rows}};const blob=new Blob([JSON.stringify(payload,null,2)],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='external_projection_decisions_{stamp}.json';a.click();URL.revokeObjectURL(a.href);}});paint();
</script></main></body></html>"""
    path.write_text(document, encoding="utf-8")


def append_proposals(path: Path, entries: list[dict], stamp: str) -> None:
    marker = f"# ============ External projection full sweep {stamp}"
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"[review] proposal batch already present in {path.name}; not appended")
        return
    block = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(text.rstrip() + "\n\n" + marker + " ============\n" + block, encoding="utf-8")
    print(f"[review] appended {len(entries)} proposed entries -> {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Full top-200 external projection reconciliation")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--threshold", type=float, default=1.5)
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--external", type=Path, default=None)
    ap.add_argument("--model", type=Path,
                    default=PROCESSED_DIR / "learned_2026-27.parquet")
    ap.add_argument("--current", type=Path,
                    default=PROCESSED_DIR / "learned_2026-27_analyst.parquet")
    ap.add_argument("--append-proposals", action="store_true")
    ap.add_argument(
        "--sync-decisions",
        action="store_true",
        help="finalize the preserved review CSV from this date's proposal-queue decisions",
    )
    args = ap.parse_args()

    csv_path = PROCESSED_DIR / f"external_projection_review_{args.date}.csv"
    md_path = PROCESSED_DIR / f"external_projection_review_{args.date}.md"
    html_path = PROCESSED_DIR / f"external_projection_review_{args.date}.html"
    proposal_path = PROCESSED_DIR / f"external_projection_proposals_{args.date}.yaml"

    if args.sync_decisions:
        if args.append_proposals:
            ap.error("--sync-decisions cannot be combined with --append-proposals")
        entries = load_external_batch(CONFIG_DIR / "analyst_proposals.yaml", args.date)
        review = sync_final_decisions(pd.read_csv(csv_path), entries)
        review.to_csv(csv_path, index=False, float_format="%.3f", encoding="utf-8")
        write_markdown(review, md_path, args.threshold, args.date)
        write_html(review, html_path, args.threshold, args.date)
        proposal_path.write_text(
            yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        approved = sum(entry.get("status") == "approved" for entry in entries)
        rejected = sum(entry.get("status") == "rejected" for entry in entries)
        retained = int(review["final_decision"].eq("retain current").sum())
        print(
            f"[review] finalized {approved} approved and {rejected} rejected queue entries; "
            f"{retained} total current values retained"
        )
        print(f"[review] CSV -> {csv_path}")
        print(f"[review] narrative -> {md_path}")
        print(f"[review] clickable review -> {html_path}")
        print(f"[review] proposal batch -> {proposal_path}")
        return

    external_path = args.external or RAW_DIR / "market" / f"external_projection_{args.date}.parquet"
    review = build_review(pd.read_parquet(external_path), pd.read_parquet(args.model),
                          pd.read_parquet(args.current), args.threshold, args.top)
    review.to_csv(csv_path, index=False, float_format="%.3f", encoding="utf-8")
    write_markdown(review, md_path, args.threshold, args.date)
    write_html(review, html_path, args.threshold, args.date)
    entries = proposal_entries(review, args.date)
    proposal_path.write_text(yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=100),
                             encoding="utf-8")
    if args.append_proposals:
        append_proposals(CONFIG_DIR / "analyst_proposals.yaml", entries, args.date)

    flagged = int(review["flag_gt_threshold"].sum())
    source_only = int(review["match_status"].eq("source_only").sum())
    retained = int(review["proposal_status"].eq("retain_current").sum())
    print(f"[review] {len(review)} source rows; {flagged} flagged; {source_only} source-only; "
          f"{len(entries)} proposed; {retained} retain-current")
    print(f"[review] CSV -> {csv_path}")
    print(f"[review] narrative -> {md_path}")
    print(f"[review] clickable review -> {html_path}")
    print(f"[review] proposal batch -> {proposal_path}")


if __name__ == "__main__":
    main()
