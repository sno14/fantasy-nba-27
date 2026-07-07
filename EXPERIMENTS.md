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

### EXP-006 — as-of-date eval harness + current-model mover bias  ·  Status: **adopted** (preseason form) / in-season cutpoints **parked**
- **Date:** 2026-07-07  ·  **Commit:** uncommitted  ·
- **Hypothesis:** the current v2m model is accurate on stable players but **biased on movers**
  (under-projects risers, over-projects fallers) — the structural cost of mean-reversion.
- **Method:** built `models/eval_movers.py` + `scripts/eval_movers.py` — mover-segmented,
  draftable-pool eval on the shared no-leakage projection path (`backtest.project_models`, refactored
  out of `run_backtest`). Pool = each model's own top-150 by projected total, restricted to players
  with a prior-season actual (≥500 min) so "mover" is defined. Bucket by **actual** YoY per-game Δ
  (fixed fpts/g edges ±2, ±6, stable across seasons); report per-bucket level MAE/RMSE + **signed
  bias** `mean(proj_pg − act_pg)`, plus directional Δ capture (corr, sign accuracy). Seasons
  2022-23…2025-26, points scoring.
- **Result (pooled across 4 seasons, v2m default):** the structural bias is exactly as predicted and
  large — signed bias by bucket: **big faller +6.8, faller +1.6, stable −1.7, riser −4.8, big riser
  −8.9** fpts/g. i.e. we **over-project fallers and under-project risers** monotonically. The cause is
  visible: `mean_proj_delta` is compressed to ~[−2.8, +0.1] in *every* bucket while `mean_actual_delta`
  spans −9.6…+9.0 — the models essentially predict "same as last year" and barely move a player off
  his prior level. Directional Δ corr is weak (0.07–0.42; best for v2m) and sign accuracy ~0.52–0.68.
  baseline/v2/v2m all show the pattern; v2m's negative minutes bias helps the big-faller bucket
  (+6.8 vs +8.0) but worsens the stable bucket (−1.7 vs −0.9).
- **Verdict:** adopted as the Stage-7 headline diagnostic — this is the number every 7.★/7.A–E
  experiment is judged against. "The disease" is now quantified: **~±8 fpts/g bias at the tails.**
- **Ledger note:** the mover buckets, not aggregate MAE/Spearman, are the metric of record for Stage 7
  (aggregate level MAE is a flat ~4.1–4.9 across models and hides all of this). In-season as-of-date
  cutpoints (the waiver case) are **parked** — they need game-log-date-granular as-of-date projection
  (project off `game_logs.date ≤ T`), which the current season-total projection path doesn't yet do;
  tracked for a follow-up once the learned as-of-date model (EXP-007) lands.

### EXP-007 — learned decompositional model, Marcel-equivalent features  ·  Status: **adopted** (signal-safe; modest win)
- **Date:** 2026-07-07  ·  **Commit:** uncommitted
- **Hypothesis:** a LightGBM decompositional model given only Marcel-equivalent inputs ≈ ties v2m
  (proves the framework loses no signal and is a safe swap; Marcel stays the fallback).
- **Method:** `models/learned.py` — one `LGBMRegressor` per decomposition target (MPG, GP, per-minute
  rate ×13 stats) trained on the historical as-of-date panel (`build_panel`: for each season S with
  ≥2 prior seasons, Marcel aggregates from `<S` as features, realized outcomes in S as labels, MIN≥200).
  Features = **only** Marcel-equivalent: own recency-weighted rates, weighted MPG/GP, recent GP, from/
  target age. Compose `stat_pg = rate × MPG`, score via config. Wired into `backtest.project_models`,
  so it refits per fold on strictly prior seasons (no leakage). Params: 300 trees, lr .05, 31 leaves,
  subsample/colsample .8, seed 0. Eval: EXP-006 mover eval + EXP-003 ranking backtest, 2022-23…2025-26.
- **Result:** **beat the "tie" bar** — even with no new features it is *less mean-reverting* than
  hand-set Marcel. Pooled signed bias by bucket (learned vs baseline vs v2m):
  - stable **−0.11** vs −0.90 vs −1.70 · riser **−3.12** vs −4.27 vs −4.81 · big riser **−6.89** vs
    −8.37 vs −8.89. It is the only model that projects risers *upward* (big-riser mean proj Δ **+2.28**
    vs ~0). Directional Δ-corr 0.30–0.43 (≥ every hand-set model). Per-game fpts MAE also lower
    (3.71 vs v2m 4.16 in 2024-25; 4.71 vs 5.11 in 2025-26); ranking Spearman ~ even-to-better.
  - **Honest caveats (skeptic pass):** (1) small **positive overall level bias** (+0.15…+1.24 fpts/g;
    worst in 2025-26) — it slightly over-projects on average, the mirror of v2m's negative bias.
    (2) **Faller buckets did not improve** (learned faller +2.77 vs v2m +1.57): v2m's downward minutes
    bias *accidentally* helps fallers; learned trades that for much better stable/riser calibration.
    (3) The riser gains come from Marcel's fixed 5/4/3 + fixed regression constant being *too*
    shrink-happy; a learned shrinkage is simply better — this is a real but *modest* structural win,
    **not** the context-feature win (that's EXP-008/009).
- **Verdict:** adopted as the Stage-7 foundation model. The swap is signal-safe **and** nets a small
  mover-bias reduction; Marcel (baseline/v2/v2m) kept as fallback + "did we lose signal?" baseline.
- **Ledger note:** the big-faller/faller over-projection and the ~R²≈0.03 GP ceiling (EXP-004) are
  **untouched** — expected, since no availability/context feature was added. The next real levers are
  trajectory/slope (EXP-008) and vacated-minutes/context (EXP-009). Do **not** read EXP-007's win as
  evidence features aren't needed — it only re-fit the shrinkage Marcel hand-set.

### EXP-008 — + trajectory / slope features  ·  Status: **rejected** (no lift; slightly regressed risers)
- **Date:** 2026-07-07  ·  **Commit:** uncommitted
- **Hypothesis:** own multi-year trends/slopes reduce the riser under-projection bias for the young
  (age ≤ 24) cohort without hurting the stable core.
- **Method:** added 8 season-over-season trajectory features to the EXP-007 learned model
  (`learned.trajectory_features`, gated by `use_trajectory=True`): OLS slopes of MPG / USG / and
  deltas over the last 3 seasons, most-recent USG, TS level + TS stability (std), n seasons observed.
  Multi-team seasons collapsed with minutes-weighted USG/TS; single-season players get neutral 0 fills.
  A/B'd `learned_traj` vs `learned` in the EXP-006 mover eval, 2022-23…2025-26.
- **Result:** trajectory **did not help and slightly hurt the movers**. Pooled signed bias
  learned → learned_traj: riser **−3.12 → −3.49**, big riser **−6.89 → −7.33**, stable −0.11 → −0.38;
  fallers ~unchanged. Directional Δ-corr also fell (e.g. 2023-24 0.352 → 0.304; 2025-26 0.318 → 0.267).
  Per-game MAE mixed (better 2024-25 4.08→3.96, worse 2023-24/2025-26). All differences small (~0.3–0.4
  fpts/g) — the honest read is "no signal, mild variance cost," not a large regression.
- **Verdict:** **rejected** as a standalone feature group. Kept as fallback baseline: plain EXP-007
  `learned` stays the foundation. Code + `use_trajectory` flag retained (not wired into
  `project_models`) for later recombination.
- **Ledger note:** a 2–3-point OLS slope is a **noisy** trend estimator, and LightGBM already recovers
  the usable trajectory from raw rates + age — the explicit slopes are largely redundant noise on a
  ~5k-row panel. This matches EXP-000's warning (season-level aging/trend alone doesn't fix the young
  cohort). **Do not re-run season-granularity slope features expecting a mover win.** The untested,
  more-promising trajectory signal is **within-season recency (last-N games from the 404k game-log
  rows)** — a different experiment (call it EXP-008b) — and **team-context / vacated minutes**
  (EXP-009). Trajectory may still matter *coupled* to those, not standalone.

### EXP-009 — + team-context / vacated-minutes features  ·  Status: planned  ·  needs transactions data
- **Hypothesis:** modelling the opportunity a player walks into (vacated minutes/usage from roster
  turnover) is the decisive riser/faller lever — the largest single reduction in mover error.
- **Success = material mover-bucket error reduction for the role-change subpopulation.**

_EXP-010+ — injury data (7.C), market/ADP (7.E), hyper-parameter tuning — after the above._
