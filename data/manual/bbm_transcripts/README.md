# BBM video transcripts — the analyst-signal source (feeds the living analyst layer)

Drop one file per video here. Transcripts are the raw material for the
transcript→override workflow; they are **committed** (data/manual is the gitignore's
committed exception) so every derived override has checkable provenance.

## File naming

    YYYY-MM-DD-short-slug.md         # date = video publish date
                                     # (contract aligned to practice 2026-07-17: every
                                     # drop so far is hyphenated .md — was "_slug.txt")

## File header (optional — paste above the transcript text if handy)

    Title: <video title>
    URL:   <video url>
    Date:  <YYYY-MM-DD>
    ---
    <full transcript below>

    In practice drops arrive headerless and that's fine: the date comes from the
    filename, which is what `bbm_notes.csv` cites as source_file. The URL line is the
    only thing lost — add it when provenance matters.

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
- **BBM's minutes AND usage numbers get priority weight (amended 2026-07-17, user
  decision — the Trae Young miss; usage added same day).** His gauge on both has earned
  trust, and minutes × usage are the biggest correlates of fantasy points — our own
  backtests say minutes error dominates. So both comparisons must be EXPLICIT, never
  impressionistic:
  - Whenever BBM states a minutes number or range ("33 to 35", "he should play 32",
    "20-plus"), write BOTH numbers into the `triangulation` field: his claim vs the
    model's mpg base. A gap of **~2+ mpg is presumptively actionable** in either
    direction — price it with the standard Δmpg formula; overriding the presumption takes
    a NAMED offsetting mechanism (crowding, efficiency regression, his own hedge), stated
    in the entry. "The model is already close" hand-waving is what buried the Trae gap
    (31.8 vs "almost certainly 33 to 35") under two consecutive `none` verdicts.
  - **Usage claims get the same treatment.** The board carries no usage column, but the
    base is computable from the cache and verified accurate (Brown 36.2 vs BBM's "36",
    Randle 26.5 vs "27", George 23.3 vs "23"):
        USG% = 100 · (FGA + 0.44·FTA + TOV) · (TmMIN/5) / (MIN · (TmFGA + 0.44·TmFTA + TmTOV))
    from `player_season_stats` + `team_game_logs` (sum team logs by season). When BBM
    states a usage number or shift ("36 comes down to 28-30", "could the 23 become 25"),
    write his claim vs the player's computed last-season USG%; a **~2+ usage-point gap is
    presumptively actionable**, sized at **~0.5-0.8 fpts/g per usage point at starter
    minutes** (efficiency partially cannibalizes; less at bench minutes) — consistent
    with the standing ±1-2 usage-only anchor. Compare like-for-like: BBM often cites a
    post-deadline WINDOW figure (Flagg "31", Buzelis "25"), which sits above the season
    number the formula gives — note which window his claim describes.
  - **Audit the base before trusting it:** check the gp behind the model's rate/minutes.
    A base season under ~25 games is a small-sample-artifact candidate (Kessler's 5-game
    base → +7.5; Trae's 15-game base faded his rate AND minutes at once) — re-anchor on
    the last healthy season's level, not on the artifact.
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

## Delta lifecycle — role/hype deltas are BRIDGES (Step 18, built 2026-07-16)

A role/hype `fpts_delta` bridges the model until it can see the role for itself. In-season,
`update_daily.py` re-projects the model nightly and its EWMA **learns the role** from games —
so once the model's own base has caught up, a static delta double-counts and should be
retired (a later-dated `none`/reduced entry) or auto-decayed. Injury/availability facts don't
decay (they live in `config/overrides.yaml`, not here).

**Step 18 shipped (2026-07-16):** every nightly run now prints the **staleness report** —
per bridge entry, the model's pre-analyst base *now* vs *when the entry was written*
(recovered from the snapshot archive / frozen board A); a caught-up delta flags
`analyst_stale` on the board and prints "consider retiring". Retirement stays **manual and
append-only** — the flag is a nudge, never an auto-edit. `--analyst-decay` (18.2) can
auto-taper bridge deltas by games played (full ≤ ~10, gone by ~30) but is **off by default**
until its validation gate runs on real in-season dates (implementation-plan 18.2).

## Scoring = calibration (amended 2026-07-12)

The layer is a **standing supplement** by user decision — it does not have to beat the
model to exist. April 2027's A-vs-B scoring (with the BBM-tagged subset split out)
**calibrates** it instead: are the magnitude translations running hot or cold, and which
source (user vs BBM-derived) earns bigger weights next season. The dual freeze and the
scoring itself are unchanged.
