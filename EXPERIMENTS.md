# Experiment ledger — Fantasy NBA Projections

**Purpose:** a durable, append-only trail of *everything we've tested* — what the hypothesis
was, how we tested it, the result, and the verdict. This exists so we **never re-run a dead
end** and so every "we tried X, it didn't move the needle" is recoverable months later.

**Relationship to other docs:**
- `ROADMAP.md` — the forward-looking plan (what to build, in what order, and why).
- **This file** — the backward-looking record (what we ran and what happened).
- Claude memory — the terse "why" behind decisions.

## How to log an experiment

One entry per hypothesis tested. Append; don't rewrite history. Keep numbers with the
conditions they were measured under (seasons, pool, metric) — a bare "MAE 4.4" is useless
later. Template:

```
### EXP-NNN — <short title>
- **Date:** YYYY-MM-DD  ·  **Commit:** <sha or "uncommitted">  ·  **Status:** adopted | rejected | parked | superseded
- **Hypothesis:** what we expected to be true and why.
- **Method:** model/feature change, data used, backtest setup (seasons, pool, no-leakage notes).
- **Metric(s):** the exact eval + conditions (e.g. "top-100 Spearman, 2022-23..2025-26, no-leakage").
- **Result:** the numbers, deltas vs the relevant baseline.
- **Verdict:** what we did with it and the one-line reason.
- **Ledger note:** anything that stops us re-testing the same thing (e.g. "GP fit R²≈0.03 is the ceiling; don't retry box-score GP features").
```

Verdict vocabulary: **adopted** (in the shipped model), **rejected** (measured, doesn't help),
**parked** (promising but deferred), **superseded** (replaced by a later experiment).

---

## Backfilled findings (pre-ledger, reconstructed from ROADMAP + memory)

These predate the ledger. Numbers are as recorded in the roadmap's "key findings"; treat them
as the established baseline of what we already know.

### EXP-000 — Marcel baseline vs v2 aging curves (per-game accuracy)
- **Date:** ~Stage 2  ·  **Status:** adopted (both kept; backtest is arbiter)
- **Hypothesis:** empirical per-stat aging curves beat a single flat age multiplier.
- **Method:** no-leakage backtest, curves refit on training years; compare baseline vs v2.
- **Result:** per-game MAE ~4.4 **either way**. Aging helps old players, hurts young (survivor
  bias), nets to ~zero on aggregate.
- **Verdict:** both models kept; aging is ~neutral on aggregate. **Not** a lever for accuracy.
- **Ledger note:** don't expect population aging curves alone to move aggregate accuracy — the
  young-player miss (survivor bias) is a *known* cost, and is exactly the riser problem (Stage 7.B).

### EXP-001 — Minutes is the dominant error source (actual-minutes oracle)
- **Date:** ~Stage 2  ·  **Status:** adopted (motivated Stage 3)
- **Hypothesis:** minutes projection, not rates, drives per-game error.
- **Method:** feed *actual* minutes into the projection, hold rates as projected, re-measure MAE.
- **Result:** per-game MAE ~4.4 → ~2.0 (**~55% of error is minutes**). Per-minute rates are
  already well-predicted.
- **Verdict:** prioritize minutes/role over rate/efficiency modeling.
- **Ledger note:** per-minute *rate* and *efficiency* direct modeling are **parked** — measured
  low-leverage given rates are already good. Revisit only coupled to a usage/role model (7.F).

### EXP-002 — Minutes aging curve (v2m)
- **Date:** ~Stage 3  ·  **Status:** adopted (default model)
- **Hypothesis:** aging a player's own recency-weighted MPG (damped multiplicative trend)
  beats holding it flat.
- **Method:** empirical MPG-vs-age delta curve, `strength=0.5`; backtest 2022-23..2025-26.
- **Result:** beats v2 and baseline on minutes MAE in all 4 seasons (avg MPG MAE 4.07 → 3.93);
  beats v2 on per-game fpts MAE in all 4 (baseline in 3/4). Adds mild negative minutes bias
  (partly eval selection). `strength=0.5` tuned to keep ~all MAE gain at ~half the bias.
- **Verdict:** shipped as v2m, the default.
- **Ledger note:** first change to actually move the minutes needle — but it's still an
  *aging* trend on the player's own level, not a *role/opportunity* signal.

### EXP-003 — Draft-pool eval reframe (top-100 Spearman)
- **Date:** ~Stage 3  ·  **Status:** adopted (headline metric)
- **Hypothesis:** all-player MAE misleads for drafting; ranking the draftable pool is what matters.
- **Method:** score each model on its own top-100 by projected total; headline = Spearman rank corr.
- **Result:** on the top 100, baseline ≈ v2 ≈ v2m (Spearman ~0.51). Curve/minutes modeling is
  within noise **for drafting**.
- **Verdict:** top-100 Spearman is the headline metric.
- **Ledger note:** **this metric is availability-dominated and cannot see risers/fallers** — see
  Stage 7.0. It stays as the "did we rank the stable core right" metric; it is *not* sufficient.

### EXP-004 — Availability ceiling (the decisive finding)
- **Date:** ~Stage 3  ·  **Status:** adopted as a hard constraint
- **Hypothesis:** can we predict games-played (GP) well enough to rank draft totals?
- **Method:** oracle test (proj per-game × actual GP) vs current; fit GP on 3-yr GP + age + MPG.
- **Result:** oracle Spearman **0.89** vs current **0.51** vs per-game-only **0.49**. GP fit
  explains **R²≈0.03**; prior-GP→next-GP Spearman only 0.21. Era-window / own-GP-blend sweeps
  can't beat it; down-weighting own GP *hurts*. Stars are NOT load-managed down (36+ MPG has
  highest GP); modern rotation GP ~66-68.
- **Verdict:** point-estimate GP from box scores is at the data ceiling. Next levers are
  **external availability data** (7.C) or **uncertainty ranges** (Stage 6).
- **Ledger note:** **DO NOT** retry GP prediction from box-score features — it is capped at
  R²≈0.03. Only *new data* (injury history/reports, 7.C) can move it.

### EXP-005 — Monte-Carlo risk ranges + risk-adjusted ranking
- **Date:** ~Stage 6  ·  **Status:** adopted (`--ranges`, `--rank-by`)
- **Hypothesis:** since GP is unpredictable, model the *distribution* instead of a point total.
- **Method:** GP drawn from empirical modern-era elite pool, additively re-centred on proj GP;
  per-game normal(sd=9). Calibrated on top-100 backtest.
- **Result:** p10–p90 coverage ~82%, p25–p75 ~48%, tails ~9%/10%. `safe` ranking backtests as
  accurate as median (Spearman ~0.57) while demoting injury-prone players (Giannis out of top-20).
  Projected top-100 ↔ actual top-100 overlap ~79%; only ~60% at top-24.
- **Verdict:** shipped. The honest answer to the availability ceiling.
- **Ledger note:** the GP pool is age-bucketed, not player-specific — a per-player injury-history
  tail (7.C) is the natural next sharpening.

---

## Active experiments (Stage 7 — risers & fallers)

**Data-access note (2026-07):** the remote/web environment **cannot pull NBA data** —
`stats.nba.com` is blocked by egress policy (403 CONNECT) and `data/` is gitignored, so there is no
cache to run against here. Until resolved, Stage-7 experiments run **locally** (where `nba_api`
works) or against a **committed data snapshot** on the branch. Decision pending.

**Planned (not yet run) — validation sequence for the 7.★ learned foundation:**

### EXP-006 — as-of-date eval harness + current-model mover bias  ·  Status: planned
- **Hypothesis:** the current v2m model is accurate on stable players but **biased on movers**
  (under-projects risers, over-projects fallers) — the structural cost of mean-reversion.
- **Method:** build the mover-segmented, draftable-pool **as-of-date** eval (per-game level MAE/RMSE
  + signed bias per YoY-change bucket; directional Δ capture). Score both **preseason→season** and
  **in-season cutpoints** (given games ≤ T, ROS projection vs actual remainder — especially early
  season, the waiver case). Walk-forward, no-leakage.
- **Success = the harness exists and quantifies the per-bucket bias** preseason *and* in-season
  (baselines "the disease" for both the draft and waiver use cases).
- **Note:** in-season eval needs game-log-date granularity (have) and eventually the daily news/status
  feed (new — `nbainjuries` / official injury report / prosportstransactions).

### EXP-007 — learned decompositional model, Marcel-equivalent features  ·  Status: planned
- **Hypothesis:** a LightGBM decompositional model given only Marcel-equivalent inputs ≈ ties v2m
  (proves the framework loses no signal and is a safe swap; Marcel stays the fallback).
- **Success = within-noise parity on the 7.0 metrics.** A loss means the framework is dropping
  signal and must be fixed before adding features.

### EXP-008 — + trajectory / slope features  ·  Status: planned
- **Hypothesis:** own multi-year trends/slopes reduce the riser under-projection bias for the young
  (age ≤ 24) cohort without hurting the stable core.
- **Success = lower signed bias in the riser buckets, no regression elsewhere.**

### EXP-009 — + team-context / vacated-minutes features  ·  Status: planned  ·  needs transactions data
- **Hypothesis:** modelling the opportunity a player walks into (vacated minutes/usage from roster
  turnover) is the decisive riser/faller lever — the largest single reduction in mover error.
- **Success = material mover-bucket error reduction for the role-change subpopulation.**

_EXP-010+ — injury data (7.C), market/ADP (7.E), hyper-parameter tuning — after the above._
