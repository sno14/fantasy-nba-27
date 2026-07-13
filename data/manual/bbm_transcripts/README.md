# BBM video transcripts — the analyst-signal source (feeds the living analyst layer)

Drop one file per video here. Transcripts are the raw material for the
transcript→override workflow; they are **committed** (data/manual is the gitignore's
committed exception) so every derived override has checkable provenance.

## File naming

    YYYY-MM-DD_short-slug.txt        # date = video publish date

## File header (paste above the transcript text)

    Title: <video title>
    URL:   <video url>
    Date:  <YYYY-MM-DD>
    ---
    <full transcript below>

## Workflow v2 (user decisions 2026-07-12: a LIVING layer for THIS season)

The repeatable per-transcript pass (steps 1–3 are Claude, 4 is Steven, 5–7 are standing):

1. **Drop transcripts** — backlog and, going forward, each new video.
2. **Extract (Claude):** every player-specific *fact* → append `data/manual/bbm_notes.csv`
   (`date, player, team, claim_type (injury|role|depth|rank|hype), direction, quote,
   source_file`). Facts only: role / minutes / usage / depth chart / injury / transaction.
3. **Triangulate (Claude):** per flagged player, three angles — (i) our model board's
   fpts/g + mpg, (ii) BBM's basketball mechanism, (iii) Claude's own judgment — into
   **proposals** in `config/analyst_proposals.yaml` (entry schema + `status`, `preview`,
   `triangulation`). Rookies not on the learned board are deferred (noted in the ledger).
4. **Review (Steven):** set each `status` to `approved` / `rejected`, then
       python scripts/apply_proposals.py            # preview the fpts→rank impact
       python scripts/apply_proposals.py --promote  # approved -> analyst_overrides.yaml
   Promotion is idempotent, strips the proposal-only fields, and appends (never edits) —
   a change of mind is a NEW later-dated entry (latest wins), which is how the layer stays
   current as information arrives between now and October.
5. **The visible adjusted board (any time):**
       python scripts/apply_analyst.py data/processed/learned_2026-27.parquet
   or interactively: the explorer's Draft Board tab applies the effective overrides via
   its **Analyst layer (B)** toggle (default on; edits/promotes refresh on the next
   interaction), and its Player tab reflects board B.
6. **In-season (critical feature):** `update_daily.py` applies the effective overrides to
   the nightly ROS board automatically (audit columns; `--no-analyst`). Concrete
   out-timelines still go to `config/overrides.yaml` (availability caps + EXP-030
   redistribution to teammates).
7. **Mid-Oct pass:** full re-review of every effective entry vs fresh videos +
   `analyst_triggers.py`, then the dual freeze (boards A and B).

## The two hard rules (user decisions 2026-07-12)

1. **`fpts_delta` or `none` ONLY — never `rank_delta`.** A projection is a belief about a
   player's *per-game value*; the board ranking is the byproduct of re-sorting everyone on
   fpts. A `rank_delta` shoves a player past others who have nothing to do with the news —
   incoherent from our POV. Change fpts; let rank fall out. (`apply_proposals.py --promote`
   refuses `rank_delta`.)
2. **Ignore BBM's ranking/tier claims.** "Top 50", "top 100", "top 20 in 9-cat" are his
   league settings, not ours — misleading for a points league. Extract only the basketball
   *mechanism*; Claude sizes the fpts_delta from that mechanism.

## Triangulation rubric (sizing the fpts_delta from the mechanism)

**The sizing frame (amended 2026-07-13, user decision — magnitude matters): size the
TARGET, not a bump.** Every proposal is a triangulated belief about the player's ROS
fpts/g *level*; the delta is just the arithmetic remainder:

    fpts_delta = (triangulated ROS fpts/g target) − (model's current base fpts/g)

This one rule captures magnitude AND prevents stacking, because the model's base already
contains whatever part of the story the model has priced:

- **Assurance (`none`) is the case where the triangulated target ≈ the model's base** —
  not merely "same direction". BBM agreeing with our *number* and adding no new mechanism
  is recorded confidence, never an addition (stacking agreement double-counts one fact).
- **Directional agreement with a magnitude gap IS actionable — in both directions.** The
  model already projects a rise worth ~+2 and BBM's mechanism honestly supports ~+5 → the
  entry is the *unpriced remainder* (+3), not +5 on top. Conversely, if the model's
  stats-momentum implies a bigger jump than BBM's mechanism supports (role capped, crowded
  depth chart), a NEGATIVE delta on a player everyone is "positive" about is legitimate —
  write it, with the mechanism.
- **Disagreement** → same arithmetic, sized by his mechanism's strength vs the model's
  evidence.
- **Magnitude, reasoned in fpts/g (never from his rank):**
  - *Minutes-driven:* `Δfpts ≈ Δmpg × (fpts_pg / mpg) × ~0.85` (the per-36 fade — bench
    rates dip at starter minutes), then discounted for conviction/hedging.
  - *Usage-only* (minutes already high): smaller, ±1 to ±2.
  - **No hard cap** (user decision 2026-07-13, superseding the same-day ±3.0/±5.0 caps):
    the tiers mild ≈1 / moderate ≈2 / strong ≈3 are calibration *anchors*, not limits —
    judgment sizes the number. An unusually large delta needs unusually concrete
    mechanisms and a sentence acknowledging its size; April 2027 calibrates whether the
    magnitudes ran hot.
- Concrete role/depth/injury/usage claims move numbers; generic praise/hype → `none`.
- Every transcript-derived rationale starts with ``BBM <video-date>:`` + the quote.
- The `triangulation` field records the model base the sizing used — the number Step 18's
  staleness check (and the mid-Oct re-review) compares against later.

## Multiple mechanisms on one player (amended 2026-07-13, user decision)

The engine keeps **one effective entry per player** (`effective_overrides`: latest-dated
wins — entries never sum mechanically), so compounding is a judgment made *inside* one
entry, never an emergent stack:

- **A new mechanism lands on an already-adjusted player → re-triangulate the WHOLE
  player** from the model's *current* base and write one superseding entry. Never
  `old delta + new delta`: the joint effect of "enters the starting lineup" + "becomes
  the lead ball-handler" is a judgment about what the combination *means* — usually more
  than either alone, but bounded by the real constraints (48 minutes, one ball; usage
  gains partially cannibalize efficiency; the minutes leg may already contain half the
  usage leg's value). Weigh the mechanisms' meaning, never count their number.
- In-season the base moves nightly (the EWMA learns the role), so re-triangulating from
  the current base automatically sheds whatever the model has since absorbed — the same
  no-double-count logic as Step 18's staleness flag, applied at write time.
- **No numeric cap here either** (user decision 2026-07-13) — compounding cases are
  sized by judgment like everything else, with each mechanism enumerated in the
  rationale plus a sentence on why the joint effect exceeds the largest single one.
  Expect big joint deltas to be rare; April 2027's calibration judges whether they
  ran hot.

## Delta lifecycle — role/hype deltas are BRIDGES (Step 18, next build)

A role/hype `fpts_delta` bridges the model until it can see the role for itself. In-season,
`update_daily.py` re-projects the model nightly and its EWMA **learns the role** from games —
so once the model's own base has caught up, a static delta double-counts and should be
retired (a later-dated `none`/reduced entry) or auto-decayed. Injury/availability facts don't
decay (they live in `config/overrides.yaml`, not here). Step 18 (implementation-plan Phase 6)
adds the staleness flag + optional decay; until then, retirement is manual (the mid-Oct
re-review and ad-hoc as roles crystallize).

## Scoring = calibration (amended 2026-07-12)

The layer is a **standing supplement** by user decision — it does not have to beat the
model to exist. April 2027's A-vs-B scoring (with the BBM-tagged subset split out)
**calibrates** it instead: are the magnitude translations running hot or cold, and which
source (user vs BBM-derived) earns bigger weights next season. The dual freeze and the
scoring itself are unchanged.
