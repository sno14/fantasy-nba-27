---
name: bbm
description: Run the BBM transcript → analyst-layer pass — detect unprocessed transcripts, extract player facts to bbm_notes.csv, triangulate proposals into analyst_proposals.yaml, preview the board impact, then STOP for Steven's review. Use when new transcripts land in data/manual/bbm_transcripts/ or the user shares fantasy-relevant commentary.
---

# /bbm — the BBM transcript pass (workflow v2)

This skill is the **session mechanics**. The **judgment rubric is NOT here** — it lives in
`data/manual/bbm_transcripts/README.md` (the canonical contract: the two hard rules, the
target-level sizing frame, the minutes & usage priority rule, multiple-mechanisms
re-triangulation, the delta lifecycle). **Read that file in full before drafting
anything.** If this skill and that README ever disagree, the README wins.

## 1 — Detect state (do this before reading transcripts)

```bash
ls data/manual/bbm_transcripts/*.md                       # the drop zone (skip README.md)
cut -d, -f7 data/manual/bbm_notes.csv | sort -u           # source_file = processed episodes
md5sum data/manual/bbm_transcripts/*.md | sort            # catch duplicate-paste files
```

- Unprocessed = files not appearing in the notes CSV's `source_file` column.
- **Duplicate hashes mean a paste error** (it has happened: a file named for one episode
  containing another's text). Flag it to Steven and process the content once, attributed
  to the episode it actually is; ask for a re-drop of the missing one.
- Check `config/analyst_overrides.yaml` for players that already have effective entries —
  any new mechanism on them means a whole-player re-triangulation from the CURRENT base
  (one superseding entry, never a stacked delta).

## 1b — If it's a team preview (whole-roster, closed-minutes mode)

A `*-season-preview.md` file (or any transcript that walks ONE team's full roster: outlook →
moves → starting five → per-player → usage hierarchy → win prediction) runs the same pipeline
with a ledger front-end. **Full contract: the "Team-preview mode" section of the transcripts
README** — read it; this is just the checklist.

1. **Build + persist the minutes+usage ledger FIRST** →
   `data/manual/bbm_team_previews/<date>-<team>.yaml` (schema in that dir's README). One row
   per rotation player: model `mpg`/`fpts_pg` + computed last-season `USG%` vs BBM's stated
   minutes/usage. Current-team assignment via `preseason_roster_map` (the live board's source).
2. **Budget cross-check:** `sum(bbm_mpg) ≈ 240`. Over ~245 / under ~235 → rebalance before
   sizing. Every +Δmpg must come out of a nameable teammate whose −delta is itself a proposal.
3. **Coverage = full rotation; output = movers only.** Give every rotation player a ledger
   verdict; only target ≠ base becomes a proposal. A compact coverage table (player | verdict)
   + a pointer to the ledger file goes in the proposals batch header.
4. **Route the preview-only signals:** rookies → `defer(rookie)`, ledger+notes, no proposal
   (feeds the Oct sheet); team availability/tanking/rest → `config/overrides.yaml` candidate
   flagged to Steven; scheme/pace/wins → conviction context, not a standalone delta.

Then rejoin the normal flow at step 3 (triangulate the movers) → 4 (validate) → **STOP**.

## 2 — Extract → append `data/manual/bbm_notes.csv`

One row per player-specific fact: `date,player,team,claim_type,direction,quote,source_file`
(claim_type ∈ injury|role|depth|rank|hype|usage; date = episode date; source_file = the
transcript filename). Facts only — role / minutes / usage / depth / injury / transaction.

- Transcripts are auto-transcribed and names arrive mangled ("Iodumu" = Ayo Dosunmu,
  "Nerkage" = Nurkić, "Bzalis" = Buzelis). Resolve from roster context; when a reading is
  a judgment call, note it in the row ("[transcription: 'X'] read as Y"); leave a garbled
  row unresolved rather than guessing a wrong player.
- Availability facts (out-timelines, "misses half the season") get a CSV row flagged as a
  **config/overrides.yaml candidate for Steven** — they are NEVER analyst-layer material.

## 3 — Triangulate → append a batch to `config/analyst_proposals.yaml`

Every entry: `name / date (today) / category / action / preview / rationale / status:
proposed / triangulation`, under a dated batch header comment naming the source episodes.
Schema and precedent: read the existing batches in that file — match their style exactly.

Pull the model bases before sizing anything:

```python
import pandas as pd
b = pd.read_parquet('data/processed/learned_2026-27.parquet')
b[b.PLAYER_NAME.isin(names)][['rank','PLAYER_NAME','mpg','fpts_pg','gp','ast','stl','blk','pts']]
```

Mechanics the rubric requires (full text in the contract README):

- **Minutes & usage rule:** write BBM's stated minutes vs the model's `mpg`, and stated
  usage vs last-season USG% (formula in the README; computable from
  `player_season_stats` + `team_game_logs`) into every triangulation. ~2+ mpg or ~2+
  usage-point gaps are presumptively actionable — overriding takes a NAMED mechanism.
- **Audit the base — do NOT re-anchor on it (EXP-033, 2026-07-25).** A base season under
  ~25 gp is a flag to check, never a licence to adopt the last healthy season's number:
  that was backtested and **inflates +3.34 fpts/g** (+5.56 when the per-minute rate really
  fell). Compute **`rate_held` = small-sample fpts/min ÷ healthy fpts/min** and write it in.
  Below ~1.0 → the fade is correct, no upward delta. At/above ~1.0 → healthy level is the
  *ceiling* of a range, and the delta needs a **named minutes mechanism**, because the fade
  lives in minutes (the model already prices rate ~1.05× healthy for these players).
- **Size by DECOMPOSITION, not adjustment** (rewritten 2026-07-25 — "reflect the truth, not
  aggressive or conservative"). Four steps, symmetric in both directions:
  1. **Name** each component precisely enough to be mechanically reversible ("3PT .185 → .396
     on 1.42 attempts", "+4 mpg starting"). Vague = conviction = no number.
  2. **Price** each in fpts/g at the model's own minutes (made 3 = +6, made 2 = +4, ast = 2,
     stl/blk = 4). Minutes: `Δmpg × fpts-per-min`, **×1.0 — no fade**. The old ×0.85 was
     measured in EXP-034 and is directionally wrong (realised/naive 1.05-1.10 on increases).
  3. **Subtract what the model already prices** — the step that is usually skipped and where
     the biggest errors live: `already = (model fpts/min − last-actual fpts/min) × model mpg`.
     The delta is the **unpriced remainder**. (Sabonis: +3.15 of real shooting recovery, but
     +2.23 already in the base → the truth was +0.9, not the +4.0 that was written.)
  4. **No second trim** for conviction/hedging on top of the components — that stacking is what
     buried Trae. Hedge *inside* one component, once, and name it.
- **TWO VERBS, one per factor (2026-07-25).** The model builds value as minutes × rate, and
  this layer owns both. `action` may carry either or both legs:
  `{target_mpg: 31.0}` · `{fpts_delta: -2.0}` · `{target_mpg: 31.0, fpts_delta: -4.3}`.
  - `target_mpg` is **absolute** (write the number BBM states), self-limiting, and rescales
    the whole stat line at held per-minute rates with fpts **re-derived** — no ×0.85 fade.
  - `fpts_delta` is the **rate residual applied after** that rescale (so with a minutes leg
    it is measured off the *rescaled* base, never the raw one).
  - **A minutes belief MUST use `target_mpg`** — as an `fpts_delta` it leaves mpg and the
    stat line stale and becomes a silent efficiency claim. `apply_proposals.py` rejects a
    batch whose `sizing:` moves minutes without the leg.
  - **Team previews:** set `target_mpg` for every rotation player BBM numbers, not just the
    movers — that is what makes the ~240 budget checkable.
- **`sizing:` block is mandatory on every non-`none` entry** — `base_fpts / base_mpg /
  target_mpg / target_fpm / target_fpts` (+ `rate_held` when the base is under ~25 gp), where
  `target_fpts` must equal `target_mpg × target_fpm` and the delta is the remainder.
  `apply_proposals.py` rejects a batch whose arithmetic doesn't reconcile. Remember
  `fpts_delta` moves **only** `fpts_pg` — never `mpg`, never the stat line — so an unstated
  minutes thesis silently becomes an efficiency claim. Full rationale: the contract README.
- Scoring context for sizing: ESPN points — stl/blk 4x, ast/fgm 2x, pts/reb/3pm/ftm 1x,
  fga/fta −1, tov −2. Assists and defensive stats move fpts twice as hard as they look.
- Rookies not on the learned board: defer with a note (unmatched names fail loudly);
  they enter via the market seed / October sheet.
- Ignore every rank/tier claim of BBM's; `fpts_delta` or `none` only.

## 4 — Validate, then STOP

```bash
python scripts/apply_proposals.py --status proposed    # read-only; unmatched names fail loudly
```

Report to Steven: the batch table, the large deltas with their size justifications, any
duplicate/garbled-transcript issues, and the availability items routed to him. **Do not
approve or promote anything.** The review gate is his.

## 5 — Only on Steven's explicit approval

```bash
# flip the statuses he approves, then:
python scripts/apply_proposals.py --promote
python scripts/apply_analyst.py data/processed/learned_2026-27.parquet   # regenerate board B
```

The running web server picks up promotions automatically (board cache keys on the
overrides file's mtime — no restart needed). Finish by updating the batch-status line in
the auto-memory (`project-direction-news-signal.md`) so the next session knows where
things stand.
