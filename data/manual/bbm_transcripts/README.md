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
- **Magnitude = decomposition, not adjustment (rewritten 2026-07-25, user direction: "I don't
  want aggressive or conservative evaluation, I want one that reflects the truth").** Both
  failure modes we have actually committed came from sizing a *narrative* — Trae Young was
  deflated by three compounding haircuts, Sabonis inflated by anchoring on a healthy season.
  The cure for both is the same four steps, and they are symmetric: run honestly, they produce
  negatives as readily as positives.

  1. **Name the components.** Each must be a specific, mechanically-reversible thing —
     "3PT .185 → .396 on 1.42 attempts", "+4 mpg as the starting five", "usage 23 → 26". A
     component you cannot state that precisely is conviction, not a component; it does not
     get a number.
  2. **Price each in fpts/g at the model's own minutes**, using the scoring weights (a made
     three = +6: 3PM 1 + FGM 2 + PTS 3; a made 2 = +4; an assist = 2; stl/blk = 4).
     Minutes-driven: `Δfpts ≈ Δmpg × fpts-per-min`, **no multiplier** — the old ×0.85 "per-36
     fade" was measured in EXP-034 across 2428 season pairs and is *directionally wrong*
     (realised/naive is 1.05-1.10 for minutes increases; even age-30+ veterans sit at 1.02).
     Use **×1.0**: adopting the measured 1.05 would import a selection effect we cannot
     identify ex ante, and 0.85 was a 15% haircut nobody had ever checked.
  3. **Subtract what the model already prices — this is the step that is usually skipped and
     it is where the biggest errors live.** The base is a *projection*, not last season: it
     has already moved off the actual. Compute
     `already_priced = (model fpts/min − last-actual fpts/min) × model mpg`
     and the delta is the **unpriced remainder**. Sabonis's 2026-07-20 entry priced +3.15 of
     real shooting normalisation while the model had already recovered +2.23 of it — a +4.0
     where the truth was +0.9. Adding a component the base already contains is double-counting,
     the same error as stacking two entries on one fact.
  4. **State it as a line and let the delta fall out** — fill the `sizing:` block below;
     `target_fpts = target_mpg × target_fpm` and `fpts_delta = target_fpts − base_fpts`. If
     the line does not reconcile, the reasoning is wrong, not the arithmetic.

  **No hard cap** (user decision 2026-07-13, superseding the same-day ±3.0/±5.0 caps) — and
  equally **no reflexive trim**. Mild ≈1 / moderate ≈2 / strong ≈3 are descriptions of what
  decompositions usually total, never targets to steer toward. A large number that survives
  step 3 is the honest answer and gets written with a sentence acknowledging its size; a small
  number on a loud story is equally honest. **Do not apply a second discount for
  conviction/hedging on top of the components** — that was the Trae error: a ×0.85 fade, a rate
  ceiling set below every season he had played, and a "joint bounding" trim, each defensible
  alone, together landing him beneath his own worst healthy year. Hedging belongs *inside* a
  component (BBM says 33-35 and hedges → price 33, not 35), applied once, and named.
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
  - **Audit the base before trusting it — but do NOT re-anchor on it (amended 2026-07-25,
    EXP-033).** A base season under ~25 games is still a flag to *stop and check*. What it
    is NOT is a licence to adopt the last healthy season's number: EXP-033 backtested that
    instruction on 315 partial-season cases and it **inflates by +3.34 fpts/g** (and by
    **+5.56** when the player's per-minute rate genuinely collapsed) — EXP-032 found the
    same +3.42 on the missed-full-season cohort. Two cohorts, one verdict. The model's fade
    beats every anchor on MAE. So the check is:
    1. Compute **`rate_held` = (small-sample fpts/min) ÷ (last healthy fpts/min)** and write
       it into the triangulation. Below ~1.0 the rate really did fall — the model's fade is
       right and re-anchoring is pure optimism (Embiid 0.87, Morant 0.89 on the live board).
    2. At/above ~1.0 the model carries a mild pessimism (~1 fpts/g) — real but small, and
       correcting it does **not** improve MAE. Treat the healthy level as the *ceiling* of a
       defensible range, never the target.
    3. **The fade lives in MINUTES, not rate.** For rate-held players the model already
       prices per-minute value *above* the healthy norm (median 1.05×) while fading minutes
       ~2.5 mpg. So an upward delta needs a **named minutes mechanism** — "the model faded
       his rate off a small sample" is false for the typical player and is not a rationale.
       (Trae's 0.93 rate ratio is 5th-percentile rare; his +4.5 stands, a blanket anchor
       would have said +7.4.)

- **Show the arithmetic: every non-`none` proposal carries a `sizing:` block (added
  2026-07-25).** The Trae miss was not a bad judgment call — it was prose asserting a
  decomposition the arithmetic never delivered ("minutes leg +2.7, rate leg +2.0, jointly
  bounded → +4.5"), which nothing in the workflow could check. Because `fpts_delta` moves
  **only** `fpts_pg` — never `mpg`, never the stat line (`models/analyst.py`) — a minutes
  thesis silently becomes a per-minute-efficiency claim. Trae's +4.5 implies 1.334 fpts/min
  at an unchanged 31.8 mpg: above every healthy season he has played, and the exact opposite
  of what his own triangulation text claimed. So state the belief as a line that reconciles:

      sizing:
        base_fpts: 37.92        # from the board
        base_mpg: 31.8          # from the board
        target_mpg: 34.5        # the minutes belief + its source (BBM's claim, healthy norm…)
        target_fpm: 1.28        # the per-minute belief + its source
        target_fpts: 44.2       # MUST equal target_mpg x target_fpm
        rate_held: 1.05         # required when the base season is under ~25 gp

  `fpts_delta = target_fpts − base_fpts`, and `apply_proposals.py` recomputes both products
  and rejects the batch if they disagree. If you cannot fill `target_mpg` and `target_fpm`
  from named evidence, you do not have a sized belief yet — write `none` or ask. Retro-filled
  blocks on pre-2026-07-25 entries are marked `retrofilled:` and record only what the standing
  delta *implies*; they are audit artifacts, not authored judgment, and any new pass on that
  player replaces them.
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

## Team-preview mode (added 2026-07-24) — the whole-roster, closed-minutes variant

**Trigger:** a transcript that walks ONE team's full roster — filename `*-season-preview.md`,
chapter skeleton `franchise outlook -> offseason moves -> projected starting five ->
per-player deep dives -> usage hierarchy -> rotation depth -> win prediction`. Locked On's
team-by-team previews (a Locked On <team> beat guest joins Josh) are the archetype.

**Why they earn their own front-end:** a team is a **closed ~240-minute system**. Unlike a
topic episode that names a riser in isolation, a preview discusses the WHOLE rotation — so
every minutes bump can be checked against a *nameable* loser, the depth chart is stated
outright, and usage is given as a ranked list. This is the depth-chart redistribution the
model can't derive from box scores (role-change-lever / EXP-030), handed to us by a beat
analyst. **Everything in the rules above still governs the sizing — only the extraction
structure changes.**

**The minutes+usage ledger is the spine (persisted, user decision 2026-07-24).** Before
writing a single proposal, build a per-team ledger — one row per rotation player — and persist
it to `data/manual/bbm_team_previews/<date>-<team>.yaml` (schema + contract in that
directory's README). It is a **dated snapshot** (like `bbm_notes.csv`), not a live table:

1. Pull every rotation player's model base (`mpg`, `fpts_pg`, `gp`) and compute last-season
   `USG%` (the formula above) — the `model_*` columns. Current-team assignment via
   `preseason_roster_map` (the live board's source).
2. Record BBM's stated minutes and usage per player, verbatim/normalized — the `bbm_*` columns
   (blank when he gives none). His projected starting five + rotation-depth comments are the
   source.
3. **Cross-check the budget:** `sum(bbm_mpg) ~= 240` (5x48). A sum materially over ~245 or
   under ~235 means the implied minutes don't fit — re-read and rebalance before sizing. This
   is the check topic episodes can't offer: a riser's +Δmpg must come out of a nameable
   teammate's row, and **that teammate's negative delta is itself a legitimate proposal**.
4. Size each row's `verdict` with the standard target-level rule + the minutes/usage priority
   rule; the ledger makes both comparisons explicit for the whole team at once.

**Coverage = the full projected rotation (user decision 2026-07-24); output = movers only.**
Triangulate every rotation player (~10-12) so the systematic sweep is visible and auditable —
but only players whose triangulated target ≠ base become entries in `analyst_proposals.yaml`.
The rest are recorded as ledger rows (verdict `none` / `defer(rookie)` / `note-only`) and,
where they carry a fact, `bbm_notes.csv` rows. The proposals **batch header** carries a compact
coverage table (player | verdict) and cites the ledger file, so review shows nothing was
silently skipped.

**Routing the preview-only signals:**

- **Rookies** (previews are dense with them — a #1 pick is often the centerpiece): capture
  role/minutes context in the ledger row + notes, verdict `defer(rookie)`, **no proposal** —
  there's no learned base to size against. This context feeds the mid-Oct market seed / sheet.
- **Team-level availability / tanking / rest signals** (e.g. Wizards 2026-07-23: "the
  fake-injury, load-management era is over — they'll actually play their guys"): an
  availability-ceiling shift → **`config/overrides.yaml` candidate for Steven**, NEVER the
  analyst layer (the same hard rule as any out-timeline). Record it in the ledger's
  `availability_note` and flag it in the batch report.
- **Scheme / pace / competitiveness** (win-total jump, new defensive identity): context that
  supports minute *stability* and reduces blowout benchings — informs conviction on the
  minutes deltas, not a standalone delta. Note it; don't price it alone.

Provenance, hard rules, and the review gate are unchanged: the ledger and proposals are
committed; `fpts_delta` / `none` only; ignore his ranks; STOP for Steven.

## Scoring = calibration (amended 2026-07-12)

The layer is a **standing supplement** by user decision — it does not have to beat the
model to exist. April 2027's A-vs-B scoring (with the BBM-tagged subset split out)
**calibrates** it instead: are the magnitude translations running hot or cold, and which
source (user vs BBM-derived) earns bigger weights next season. The dual freeze and the
scoring itself are unchanged.
