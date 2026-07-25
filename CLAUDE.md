# fantasy-nba-27 — session orientation

Fantasy NBA projection system for the 2026-27 season (ESPN 10-team weekly-H2H points
league). Read in this order before changing anything:

1. **README.md** — setup, layout, commands; its documentation map is the canonical
   reading order for everything else.
2. **ROADMAP.md** — build progress + key findings. **docs/implementation-plan.md** — the
   execution spec; active work runs from its tracker, step specs, and standing calendar.
3. **EXPERIMENTS.md** — the append-only ledger of everything tested. **Never re-run
   anything it records as rejected / do-not-retry; never edit a past entry** (corrections
   are dated addenda).

## Standing workflows — follow the named doc exactly, don't improvise

- **BBM commentary → analyst layer.** Trigger: a new transcript lands in
  `data/manual/bbm_transcripts/` or the user shares fantasy-relevant commentary/news —
  **run the `/bbm` skill** (`.claude/skills/bbm/`: state detection, extraction/triangulation
  mechanics, the review gate).
  Contract: **`data/manual/bbm_transcripts/README.md`** (workflow steps, triangulation
  rubric, hard rules — read it in full before drafting; it outranks the skill on judgment). Shape: extract player facts →
  append `data/manual/bbm_notes.csv` → triangulate each flagged player (our board's
  numbers × BBM's basketball mechanism × your own judgment) into
  `config/analyst_proposals.yaml` as `status: proposed`. Sizing is **target-level**:
  `fpts_delta = triangulated ROS fpts/g − model's current base` (`none` when target ≈
  base); `fpts_delta`/`none` only, never `rank_delta`; ignore BBM's rank/tier claims;
  one joint superseding entry per player (never sum deltas); no numeric caps — judgment
  dictates magnitude. **BBM's stated minutes and usage numbers carry priority weight**
  (user decision 2026-07-17): a ~2+ mpg gap vs the model's mpg, or a ~2+ usage-point gap
  vs cache-computed last-season USG%, is presumptively actionable. A sub-~25-game base is a
  flag to CHECK, **never to re-anchor on the last healthy season** — that rule was withdrawn
  2026-07-25 (EXP-033: anchoring inflates +3.34 fpts/g, +5.56 when the per-minute rate fell;
  compute `rate_held` instead, and note the fade lives in minutes, not rate). Magnitude is
  **decomposition, not adjustment**: name each component, price it (minutes ×1.0 — the old
  ×0.85 "per-36 fade" is directionally wrong, EXP-034), **subtract what the model already
  prices**, and let the delta fall out of a `sizing:` block that must reconcile
  (`apply_proposals.py` rejects batches that don't) — full rules in the transcripts README.
  The user reviews; `apply_proposals.py --promote` moves approved
  entries. **Never write into `config/analyst_overrides.yaml` directly** — every entry
  traces to an approved proposal or the mid-Oct calendar pass.
- **In-season nightly:** `scripts/update_daily.py` (cron from opening night); concrete
  out-timelines go to `config/overrides.yaml` (availability caps), not the analyst layer.
- **The standing calendar** (implementation-plan status notes) takes precedence at its
  dates: mid-Aug schedule pull → Sept market re-pulls (+ first transaction/roster refresh)
  → mid-Oct preseason re-pull (logs + `draft_history` + **transactions & injuries** —
  `preseason_roster_map` only puts players on their new teams once transactions ≤ Oct 1 are
  cached; drives sheet team assignments, EXP-030 redistribution, depth features) + analyst
  re-review + **the Step-19 draft-room sweep (impl-plan 19.1b: re-read league id / teams /
  size / roster slots / pick order live — all drift as members join, and a resize re-prices
  the board; + the mock draft, the only test of ESPN polling latency)** + dual board freeze →
  opening-night cron → April 2027 scoring.

## Hard constraints

- `data/raw` + `data/processed` are local-only caches; **stats.nba.com is blocked from
  remote sessions** — don't attempt live pulls remotely (see EXPERIMENTS "Active
  experiments" note).
- Boards and overrides are never fabricated or hand-edited; overrides are append-only,
  latest-dated entry per player wins.
- Every experiment gets an EXPERIMENTS.md entry — adopted **or** rejected — with a
  skeptic pass (leakage / selection / seed-stability), per the ledger's house style.
