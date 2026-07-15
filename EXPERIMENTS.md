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

**Validation sequence for the 7.★ learned foundation (EXP-006…010 below — all run; the
follow-on sequence EXP-011+ is specified in [`docs/implementation-plan.md`](docs/implementation-plan.md)):**

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

### EXP-009 — + team-context / vacated-minutes features  ·  Status: **parked** (real but coarse; not adopted)
- **Date:** 2026-07-07  ·  **Commit:** uncommitted
- **Hypothesis:** modelling the opportunity a player walks into (vacated minutes/usage from roster
  turnover) is the decisive riser/faller lever — the largest single reduction in mover error.
- **Method:** `models/context.py` — per (player, target-season) team-context features from prior-season
  minutes + the target-season team assignment (a preseason roster fact): `team_vacated_min_norm`
  (minutes freed by non-returning teammates ÷ avg team-season minutes), `team_returning_min_norm`,
  `team_turnover_share`, `own_prev_min_share`. Wired into the learned model via `use_context=True`
  (`learned_ctx`), A/B'd vs `learned` in the mover eval, 2022-23…2025-26. **Discovery that reframed the
  data plan:** no transactions scrape was needed for a *first cut* — vacated minutes are computable from
  `player_season_stats` team membership alone (see memory `data-source-map`).
- **Result:** **net wash on the mover buckets, and inconsistent across seasons.** Pooled signed bias
  learned → learned_ctx: faller **+2.77 → +2.43** (better), but riser **−3.12 → −3.55** and big riser
  **−6.89 → −7.12** (worse); stable/big-faller ~flat. Per season it swings: context clearly *helped*
  2025-26 (level MAE 5.00 → 4.72, bias 1.24 → 0.39, sign-acc 0.63 → 0.67) but *hurt* 2023-24 (MAE
  4.28 → 4.62, Δ-corr 0.35 → 0.26). Since risers are the priority and the aggregate is a wash, not adopted.
- **Verdict:** **parked** — the signal is real (one strong season) but too **coarse and unstable** to ship.
  Kept in code (`use_context`, unwired from default eval like EXP-008's trajectory).
- **Ledger note / why it's coarse + the honest caveat:** (1) `team_turnover_share` is a **team-level**
  feature shared by every player on the team — a blunt instrument; it doesn't say *who* absorbs the
  vacated minutes (position/fit/trajectory). Roadmap 7.A always specified position-aware redistribution.
  (2) **The backtest mildly flatters it:** target-season team = *end-of-season* team (mid-season trades),
  so for the very mid-season movers the feature peeks slightly — true preseason value is likely a bit
  lower than measured. ⇒ **EXP-009b:** strict *preseason* rosters / dated transactions
  (prosportstransactions) + position-aware redistribution + couple to within-season recency (EXP-008b).
  Do not re-run coarse team-level turnover expecting a decisive win.
- **Addendum (2026-07-09, Step 8.3 / EXP-016):** the honest Oct-1 preseason map now exists
  (`rosters.preseason_roster_map`; validated 97–99% opening-team agreement on the draftable
  pool vs ~86% for the end-of-season map used here). The parked verdict **stands a fortiori**:
  EXP-009 was a net wash *with* the flattering map, and the honest map can only remove signal
  from the mid-season movers it flattered. `project_models(transactions=…)` now feeds
  `use_context` variants the honest map automatically; the position-aware successor built on
  the honest map is EXP-016b (`learned_vac`) — judged separately.

### EXP-008b — + within-season recency (last-N-games form)  ·  Status: **parked** (best add-on on aggregate; not the riser fix)
- **Date:** 2026-07-08  ·  **Commit:** uncommitted
- **Hypothesis:** the trajectory signal EXP-008 *should* have used — a player's **last-N-game form vs
  his full-season average** — catches late-emerging (and post-trade) roles that season totals bury,
  and shrinks the riser under-projection.
- **Method:** `models/recency.py` — from the last `window=20` games of a player's **most recent prior
  season**: `recent_mpg`, `recent_mpg_delta` (recent − season MPG, the core signal), `recent_ppm_delta`
  (points-per-min trend), `recent_games`. Heavy per-(player, season) aggregation done once
  (`season_recency_table`), sliced per fold; `recency_features` self-restricts to seasons `< target`
  (no-leakage, unit-tested). Wired via `use_recency=True`/`game_logs` → `learned_recency`, A/B'd vs
  `learned`, 2022-23…2025-26.
- **Result:** **best aggregate improvement of any add-on so far, but it does not crack the riser
  buckets.** Overall level MAE improves in **3/4** seasons (2025-26 5.00→4.70, 2023-24 4.28→4.12,
  2022-23 4.34→4.23; 2024-25 worse 4.08→4.20) and directional **sign-accuracy improves in 4/4**. BUT
  the pooled mover buckets (the metric of record) are a wash-to-worse: faller **+2.77→+2.63** (better),
  yet stable **−0.11→−0.64** and big riser **−6.89→−7.39** (worse). The tell: per-season level *bias*
  shifts **downward** everywhere (e.g. 2025-26 +1.24→+0.60).
- **Verdict:** **parked** — helps the overall board (a real, consistent MAE/directional gain) but fails
  the stated success criterion (riser buckets). Kept in code; **opt-in** in the eval (`--recency`), not
  a default model.
- **Ledger note / the confound:** the last-N-game window at **season's end is contaminated by rest /
  load-management / tanking** (bad teams rest players, contenders rest starters), so `recent_mpg_delta`
  skews **negative** — a downward pull that helps fallers + aggregate MAE but is noise for the riser
  signal and can't distinguish a *rested star* from a *faded player*. ⇒ **EXP-008b refinement:** trim
  the final rest-contaminated games (or use a mid-late window), and/or use an explicit **post-trade
  split** (games since last `TEAM_ABBREVIATION` change) — a cleaner role-change signal than raw last-N.
  Most promising when **coupled with team-context (EXP-009b)**: recency says a role changed, context
  says why/where the minutes came from.

### EXP-009b — recency **coupled with** team-context  ·  Status: **rejected** (coupling doesn't crack risers)
- **Date:** 2026-07-08  ·  **Commit:** uncommitted
- **Hypothesis:** recency (a role changed) + team-context (where the vacated minutes came from) *together*
  crack the riser buckets where neither did alone — the two signals are complementary.
- **Method:** `learned_rc` = `project_learned(use_recency=True, use_context=True, ...)`. A/B'd vs `learned`,
  `learned_recency`, `learned_ctx` in the mover eval (`--recency`), 2022-23…2025-26.
- **Result:** **no.** Pooled signed bias learned → learned_rc: riser **−3.12 → −3.40**, big riser
  **−6.89 → −7.41** (both *worse*, same downward-bias pattern as recency alone); fallers slightly better.
  Critically **`learned_rc` ≈ `learned_recency`** on every bucket — **team-context adds essentially nothing
  on top of recency.** Aggregate stays recency-like (2025-26 best-of-all: MAE 4.48, Δ-corr 0.394).
- **Verdict:** **rejected** — coupling inherits recency's aggregate gain and its riser miss; context is inert
  on top. Variants kept opt-in behind `--recency`.
- **Ledger note — the meta-finding (important):** **four feature experiments now** — EXP-008 trajectory,
  EXP-009 context, EXP-008b recency, EXP-009b recency+context — **all improve aggregate level MAE but none
  moves the riser buckets.** The riser under-projection is stubborn against every *own-history + season-level
  roster* feature we've built. This is consistent with `docs/model-foundation.md`'s honest caveat
  ("opportunity-driven moves are forecastable; pure skill leaps partly aren't") and the EXP-004 GP ceiling.
  The two remaining, *untried* levers are: (1) **de-confound recency** — trim the season-end
  rest/tanking games (`season_recency_table(skip_last=…)`) or use a **post-trade split**, the specific fix
  for EXP-008b's downward bias; (2) **exogenous injury/news data (7.C)** — genuinely new information, not
  derivable from what we hold. Recommend (1) as a cheap next test, then (2). Do **not** keep recombining the
  existing four feature groups expecting a riser win.

### EXP-010 — DARKO live integration (minutes cross-check + disagreement finder)  ·  Status: **adopted (live-only, unbacktested)**
- **Date:** 2026-07-07  ·  **Commit:** uncommitted
- **Hypothesis:** consuming DARKO (public daily skill/minutes projection) as a live overlay adds an
  independent signal for our weakest layer (minutes) and surfaces actionable market disagreements.
- **Method:** `scripts/pull_darko.py` (Playwright — darko.app renders client-side, exposes a
  "Download CSV" button, no API) → date-stamped `data/raw/darko/`. `models/darko.py` normalizes names
  (accent/suffix-insensitive) and joins to our board (no PLAYER_ID in DARKO → name join); reports
  minutes gaps + rank gaps. `scripts/darko_report.py`. **User decision: live-only, waive the backtest
  gate** — no historical as-of-date DARKO snapshots exist, so it can't be a *trained* GBM feature; it's
  an output-level overlay only.
- **Result:** works — **99% name match** (575/582). Minutes-gap list is topped by young/rising players
  (DARKO projects more minutes for Fears/Castle/Sheppard/Wembanyama; we project more for Sharpe/White).
- **Key reframing (from DARKO's own About page, user-supplied):** (1) **minutes is DARKO's
  self-admitted *weakest* output** — the one stat it lost to DFS on — so a minutes gap is a
  *mutual-uncertainty flag*, not a correction. (2) **Rookies/young players are placeholder-initialized**
  (no NCAA/preseason data) → the young-player-dominated disagreement list is partly artefactual;
  down-weight it. (3) DARKO's *strength is per-minute rates*, which per **EXP-001 is already our
  strength** → DARKO's skill layer is **largely redundant** with what we do well, and weakest exactly
  where we most need help (minutes). Net: **modest** marginal value — a disagreement/uncertainty
  highlighter and skill prior, **not** a fix for the minutes/role gap. Also: DARKO's `#` rank is a
  per-possession *skill* rank, not fantasy-volume, so rank-gap flags volume scorers (DeRozan) as false
  fades — minutes-gap is the cleaner signal.
- **Verdict:** adopted as a live overlay (informational; never silently moves projections). Every pull
  archived date-stamped, which *also* accumulates the as-of-date history we'd need to someday backtest it.
- **Ledger note:** do **not** treat DARKO MPG as ground truth (its weakest stat) and do **not** expect
  DARKO to solve risers/fallers — it's context-blind by construction. The real levers remain
  within-season recency (EXP-008b) and team-context/vacated-minutes (EXP-009). Requires a Playwright
  browser (`python -m playwright install chromium`).

### EXP-011a — selection floor of the mover buckets  ·  Status: **adopted (diagnostic)**
- **Date:** 2026-07-08  ·  **Commit:** uncommitted  ·  **Step:** implementation-plan Step 2
- **Hypothesis:** because the mover buckets are defined on *realized* YoY Δ, they select on the
  outcome — so a **perfect conditional-mean forecaster** would itself show a large signed bias at
  the tails. Part of the ~±8 fpts/g tail bias (EXP-006/007) is therefore irreducible, and every
  later gate must be judged against this floor, not against zero.
- **Method:** `models/floor_sim.selection_floor` — debiased `learned` projections treated as the
  true conditional mean, empirical residuals resampled (1000 draws, preserves skew/fat tails, no
  normality assumption), synthetic outcomes re-bucketed; `--floor` at sigma ∈ {0.75, 1.0, 1.25}.
  `learned` model, pool = its own top-150, 2022-23…2025-26 pooled. Pure-noise identity test in
  `tests/test_stage7_infra.py` confirms an unbiased forecaster's measured tail bias ≈ its floor.
- **Result (model pool, learned, @ sigma 1.0):**
  floor_bias per bucket = big faller **+6.807**, faller **+2.166**, stable **−0.524**,
  riser **−3.103**, big riser **−7.081**.
  Reducible gap (measured `learned` bias − floor) = big faller **+0.690**, faller **+0.600**,
  stable **+0.414**, riser **−0.013**, big riser **+0.192**. Sigma band (big riser): gap = −1.59
  @0.75, +0.19 @1.0, +1.72 @1.25 — **< 2 fpts/g across the entire band.**
- **Verdict:** adopted as the standing diagnostic. On the model's own pool the measured ~−6.9
  big-riser bias is **~97% selection floor** — the four failed feature experiments
  (EXP-008/009/008b/009b) were chasing ≈0.2 fpts/g of forecastable riser bias. See EXP-011b for
  the Phase-0 decision (recall view materially qualifies this on the *realized* pool).
- **Ledger note / caveat:** the floor assumes the current model's residual spread ≈ irreducible
  noise; a better model shrinks residuals and the floor with them — hence the sigma band and the
  rule-8 requirement to **recompute the floor whenever a new default model is adopted**. The floor
  is pool-conditional: it must be recomputed on any pool it is applied to (see EXP-011b's actual
  pool, where floors are very different).

### EXP-011b — per-bucket oracle decomposition + the Phase-0 verdict  ·  Status: **adopted (diagnostic) → Decision Row 1**
- **Date:** 2026-07-08  ·  **Commit:** uncommitted  ·  **Step:** implementation-plan Step 3 (closes Phase 0)
- **Hypothesis:** split the *reducible* mover gap into minutes-driven vs rate-driven to steer
  Phases 1–3 (minutes-heavy ⇒ Step 6 allocation is the headline bet; rate-heavy ⇒ add rate-focused
  Step 5 work).
- **Method:** `eval_movers.oracle_variant` — from the real `learned` board (pool stays `learned`'s
  own top-150 — pooling on oracle ranks would re-select on the outcome), swap in **actual minutes**
  (rates held, re-scored via `score_frame` — bonuses are non-linear) or **actual rates** (minutes
  held); `--oracles`. Shares vs the EXP-011a floor: `minutes_share = (bias_learned −
  bias_oracle_minutes)/(bias_learned − floor_bias)`, `rate_share` analogously. **Plus the
  design-critique §3.2 recall view** (`run_mover_eval(pool="actual")`, `--actual-pool`): the same
  tables on the **realized** top-150, since sleepers the model never ranked are invisible in the
  model pool and understate riser bias.
- **Result — model pool (actual-Δ buckets, pooled), signed bias:** learned big riser −6.889 →
  oracle_minutes **−4.611**, oracle_rates **−2.680**; riser −3.116 → −2.093 / −1.018. Because the
  reducible gap is ≈0 in the riser buckets, minutes/rate *shares* are undefined/explosive there
  (denominator ~0) — the decomposition is ill-posed precisely because there is nothing reducible to
  decompose. Descriptively, both oracles push bias *below* the forecaster floor (they use realized
  outcomes), and in the tail buckets **rates move it more than minutes** (big-riser Δ: rates 4.21
  vs minutes 2.28) — the opposite of EXP-001's aggregate "minutes dominate," specific to the tails.
- **Result — recall view (realized top-150):** model **recall = 71.3%** (misses ~29% of the true
  top-150). On the realized pool learned's bias is *larger* — riser **−4.066**, big riser
  **−8.214** — and, against the floor **recomputed on the realized pool** (big-riser floor −5.553),
  the reducible gap is **negative in every bucket** (big riser **−2.66**, riser **−3.00**): the
  model under-projects realized risers by ~2.7 fpts/g **beyond** the floor. That headroom lives
  entirely in the sleepers it never ranked.
- **Verdict — the Phase-0 decision (Decision Row 1): reducible gap (big riser) on the model pool =
  +0.19 < 2 ⇒ preseason bias-*chasing* is near-done.** Run Steps 4–5 as cheap one-pass A/Bs, do
  **no further preseason feature hunting**, and **pull Step 10 (the in-season engine) forward
  immediately after Step 6.** The recall view *sharpens* rather than overturns this: the residual
  headroom is a **sleeper-recall** problem (which currently-low-projected players break out), not a
  calibration problem — and (a) preseason box-score features demonstrably cannot crack it (the
  EXP-008/009/008b/009b meta-finding, now explained at the mechanism level), (b) the in-season
  engine addresses it structurally (a breakout surfaces in game logs within weeks). This *reinforces*
  the "pull Step 10 forward" prescription.
- **Skeptic pass:** (leakage) oracles use actual outcomes **by design** as a diagnostic, never as a
  feature; the pool stays the real model's top-150 so selection is not on the oracle. (per-36
  mirage, critique §2.1) `rate × actual_MPG` assumes bench rates hold at starter minutes, so the
  minutes oracle *overstates* minutes share — moot here since the gap is ≈0. (season concentration)
  numbers are 4-season pooled; the model-pool gap is < 2 across the whole sigma band.
- **Ledger note:** floors are **pool-conditional** — always recompute `floor_table` on whatever pool
  you apply the reducible-gap test to (the model pool and the realized pool have very different
  floors). Do **not** re-run coarse preseason own-history/roster features expecting a riser win; the
  next real levers are exogenous data (Steps 7–9) and the as-of-date engine (Step 10).

### EXP-012 — recency de-confound: skip-last + post-trade split  ·  Status: **parked** (aggregate keeper again; riser bar failed again)
- **Date:** 2026-07-08  ·  **Commit:** uncommitted  ·  **Step:** implementation-plan Step 4
- **Hypothesis:** EXP-008b's aggregate win survives while its season-end rest/tanking
  contamination is removed — trimming the final `skip_last` played games (or splitting on a
  mid-season trade) should stop the downward bias and finally let recency help the risers.
- **Method:** `recency.season_recency_table(skip_last=…)` + `trade_split_table`
  (`TRADE_FEATURES`, ≥5 post-trade games guard). Registry variants `learned_recency{,_s5,_s10,
  _trade,_s5_trade}` vs controls `learned` and `learned_recency`, mover eval, top-150,
  2022-23…2025-26. **Rule 8 in full:** all numbers below are means over LightGBM seeds
  {0,1,2}; the paired player-clustered bootstrap CI ran on s5 − recency.
- **Result (pooled signed bias, seed-mean · riser / big riser):**
  | variant | riser | big riser | agg MAE better vs learned |
  |---|---|---|---|
  | learned (control) | **−3.177** | **−6.907** | — |
  | learned_recency | −3.390 | −7.529 | 3/4 |
  | learned_recency_s5 | −3.396 | −7.749 | 3/4 |
  | learned_recency_s10 | −3.299 | −7.177 | 3/4 |
  | learned_recency_trade | −3.364 | −7.602 | 3/4 |
  | learned_recency_s5_trade | −3.355 | −7.827 | 3/4 |
  Riser bar: **failed.** No variant beats `learned_recency` beyond the seed spread (max 0.34;
  best candidate s10's big-riser +0.35 is exactly at it, its riser +0.09 inside it); the s5 CI
  straddles 0 (big riser [−0.60, +0.02]); and **every recency variant stays worse than plain
  `learned` on both riser buckets.** Aggregate bar: passed (3/4-season level-MAE win vs
  `learned` retained by all variants; 2024-25 the consistent miss; s5_trade best 2025-26 4.68).
- **Verdict:** **parked** — the plan's "clears the aggregate bar but not the riser bar" branch,
  verbatim. Keep opt-in (`--variants`), no default change, no floor recompute, don't iterate
  further; Step 10 revisits recency at true game-log granularity (EWMAs, fitted half-lives).
- **Skeptic pass:** (leakage) none — windows/trade features computed within prior seasons only,
  unit-tested (`tests/test_stage7_infra.py`); (selection) pool unchanged (model top-150);
  (season concentration) the aggregate win concentrates in 2025-26 + 2022-23 and *loses*
  2024-25 in every variant — real but uneven.
- **Ledger note:** this was **predicted by EXP-011a** — the model-pool riser reducible gap is
  ≈0 fpts/g, so there was nothing for de-confounding to close; the measured riser deltas are
  floor-level noise. The rest/tank contamination story (EXP-008b) is real but fixing it does
  not manufacture headroom that doesn't exist. **Five feature experiments now confirm the same
  meta-finding** (EXP-008, 009, 008b, 009b, 012): do not attempt further preseason riser-bias
  feature work; the open lever is sleeper *recall* (EXP-011b), which is exogenous-data
  (Steps 7–9) or in-season (Step 10) territory.

### EXP-013 — objective-side changes (Δ-targets, sample weights, quantile heads, tuning)  ·  Status: **rejected** (a, b, d) / **rejected as Step-14 input, with a replacement note** (c)
- **Date:** 2026-07-08  ·  **Commit:** uncommitted  ·  **Step:** implementation-plan Step 5
- **Hypothesis:** every prior experiment changed features under the same squared-error level
  objective; changing the objective (shrink toward "league-average change" instead of the
  pool-average player, re-weight movers, learn quantiles, tune the never-tuned params) is a
  different lever class.
- **Method:** mover eval, top-150, 2022-23…2025-26, **all sub-verdicts on seed {0,1,2} means**
  (rule 8). Controls: `learned` (bias riser **−3.177**, big riser **−6.907**, stable −0.134).
- **(a) Δ-targets (`learned_delta`) — rejected.** Riser −2.957 / big riser −6.746: nominal
  improvements (+0.22 / +0.16) are *inside* its own seed spread (0.25 / 0.39) — noise.
  Aggregate MAE a tie. The tree-regularization-geometry hypothesis produced nothing measurable.
- **(b) Sample weights — rejected.** `learned_w_mover` riser −2.770 / big riser −6.590 *looks*
  better but overshoots the EXP-011a floor (−3.103) by going bias-positive everywhere (stable
  +0.167) and pays a large, consistent aggregate cost: level MAE worse in **all 4 seasons**
  (+0.2…+0.35) — bias traded for variance, not signal. `_a05` same pattern, milder.
  `learned_w_rel` worse on both riser buckets *and* MAE. No candidate merited a CI.
- **(c) Quantile heads (`eval_quantiles.py`) — rejected as the Step-14 range source.** The
  direct fpts quantile heads **lose pinball** to the constant-σ normal baseline overall
  (seed-mean ≈1.78 vs ≈1.69) and decisively in the riser subset (≈2.35 vs ≈1.81; **0/4 riser
  seasons, 1/4 overall**), consistent across seeds (spread ~0.03 ≪ deficits). Coverage is
  badly outcome-dependent: big-riser cov_q90 = **0.29** vs 0.90 nominal (the heads can't see
  breakouts any better than the point model — same features, same ceiling). Baselines carried
  a deliberate in-sample σ advantage; the margins dwarf it. **Replacement note for Step 14:**
  `resid_quant` (empirical residual quantiles around the point estimate) beat `normal_sigma`
  overall on all 3 seeds (≈1.68 vs ≈1.69, and much better skew handling at q90) — the cheap
  upgrade to `SD_PG = 9` is an *empirical residual CDF*, not learned quantile heads.
- **(d) Hyperparameter tuning (`scripts/tune_learned.py`, built this step) — rejected;
  defaults stand.** Nested per rule 10b: 27-combo grid × 5 folds ≤ 2021-22, `n_estimators` by
  early stopping on each fold's last training season. Tuning-fold winner
  `{num_leaves 63, min_child_samples 30, lr 0.05, n_estimators 79}` (fold MAE 4.781 vs
  defaults 4.976) **did not transfer**: on the standard window (seeds {0,1,2}) pooled MAE
  ties (4.44 vs 4.44) and riser bias is clearly worse (riser −3.817 vs −3.177, big riser
  −7.555 vs −6.907; ~5× seed spread). The clustered CI shows a uniform ≈−0.7 bias shift in
  *every* bucket — deeper trees on this panel are just more mean-reverting, not smarter.
  Kept as registry variant `learned_tuned` (documented-rejected); the tuner script stays for
  re-tuning whenever the panel grows (Step 10's ~45k-row cutpoint panel is the natural
  re-arm point).
- **Verdict:** all four sub-experiments reject; `learned` with `DEFAULT_LGBM_PARAMS` remains
  the default. **Phase 1's cheap A/Bs are exhausted, exactly as Decision Row 1 predicted** —
  objective-side changes cannot manufacture headroom the floor says isn't there.
- **Skeptic pass:** (leakage) none — (a)/(b) touch training labels only; (c) trains prior-only;
  (d) grid never saw the verdict seasons (the script *refuses* tuning folds > 2021-22).
  (selection) pools unchanged. (season concentration) rejections are uniform, not
  season-driven; (d)'s MAE split 2/2.
- **Ledger note:** do **not** re-tune on the season-level panel expecting a transfer — the
  surface is flat (4.78–4.99 across 27 combos) and the tuning-fold ranking didn't survive the
  window switch. Re-arm (d) only on a structurally larger panel (Step 10). For ranges,
  Step 14's input is the empirical residual CDF (see (c) note), pending EXP-021 itself.
  Fixed en route: `project_models` seed override used to clobber a variant's own `params`
  (latent bug — any params-carrying variant silently tested defaults under `--seed`); now the
  seed threads *inside* spec params (unit-tested).

### EXP-014 — team-constrained minutes allocation  ·  Status: **rejected** (decisively; the structural bet fails at the share→MPG conversion)
- **Date:** 2026-07-08  ·  **Commit:** uncommitted  ·  **Step:** implementation-plan Step 6
- **Hypothesis:** modeling minutes as a **share of team minutes**, normalized within the target
  roster (240-minute budget + who competes for it, by position), beats the per-player MPG
  regression — the breakthrough plan's structural bet (§1b).
- **Method:** 6.1 historical `team_rosters` pull (17 seasons; all POSITION strings map to
  guard/big). 6.2 `y_min_share` LightGBM on `ALLOC_MODEL_FEATURES` (depth-chart features +
  role/durability/age + EXP-009 team pair + `pf_per_min`), budget-normalized to
  `1 − rookie_reserve` (measured 0.108), converted `share_norm × mean_team_total_min /
  pred_gp`, clip [0, 42]; wired as `learned_alloc` (swaps only the minutes layer). A/B vs
  `learned`, top-150, 2022-23…2025-26, seeds {0,1,2}, segment split + clustered CI.
- **Σ-share sanity (it did its job):** raw pre-norm team sums 1.21 vs the 0.89 target →
  found+fixed two real calibration flaws: (1) the 200-min label filter **selected on the
  outcome** (taught the model fringe players get real minutes) → share labels take
  `min_minutes=0`; (2) no-prior roster players in the modeled set **double-counted the rookie
  reserve** → the share universe = players with a prior-season row (the learned board's
  universe by construction). Post-fix: mean 0.946 vs 0.892 — acceptable.
- **Result (pooled, seed-mean; learned → learned_alloc):** fails everything, far beyond noise.
  Minutes MAE **2.81 → 4.59** (+63%); level MAE **4.43 → 5.78** (worse all 4 seasons); every
  bucket's signed bias shifted ≈ **−2.4** (clustered CI excludes 0 in *all five* buckets;
  pool minutes bias +0.8 → −0.8). Segments — the case it was built for — all worse: moved
  5.32 → 5.69, high-turnover 4.46 → 6.19, rest 3.92 → 5.50 level MAE.
- **Mechanism (the diagnostic that stops a re-run):** the share model itself is nearly
  competitive at **season-total minutes** (pool total-MIN MAE 496 vs 447, −11%) — the damage
  is the **share→MPG conversion**: `MPG = share × team_total / pred_gp` divides by predicted
  GP, which is near-unpredictable (EXP-004, R²≈0.03), so GP noise propagates
  *into* the per-game number the eval (and drafting) cares about. The regression predicts MPG
  — the stable quantity — directly. Compounding it, proportional normalization taxes every
  player for the fringe overshoot (stars included), hence the −0.8 MPG pool bias.
- **Verdict:** **rejected.** `minutes_mode="regression"` stays the default. Roster/position
  data, `pos_group_asof`, and the depth-chart features **stay** — Step 10 reuses them as
  in-season features (live teammate-vacated minutes), where allocation thinking belongs.
- **Skeptic pass:** (leakage) roster map = `context.target_team_map` (end-of-season teams) —
  the same *flattering* approximation EXP-009 carried, and it still lost badly, which
  strengthens the rejection; positions are static attributes (past-preferred lookup).
  (selection) pool = each model's own top-150, unchanged. (season concentration) worse in
  all 4 seasons.
- **Addendum (2026-07-09, Step 8.3 / EXP-016):** the rejection **stands a fortiori** under the
  honest Oct-1 map — EXP-014 lost decisively *with* the flattering end-of-season map (the
  skeptic pass already noted the flattery strengthened the rejection), and the failure
  mechanism (÷GP variance in the share→MPG conversion) is map-independent. Not re-run;
  `project_models(transactions=…)` supplies the honest map if allocation is ever revisited.
- **Ledger note:** do **not** re-run share-of-team-minutes → per-game via ÷GP. If allocation
  is ever revisited, it must predict **MPG directly with roster-relative features** (the
  depth-chart features as inputs to the existing regression — a *feature* experiment, not a
  target change) or allocate **season totals** for total-based decisions only. The EXP-004
  GP ceiling strikes again — any quantity routed through predicted GP inherits its noise.

### EXP-018 — `project_asof`: the as-of-date ROS engine  ·  Status: **adopted (foundation) / gate parked** (crushes frozen-T₀ 12/12; naive-parity, cell gate not met — re-gate after Step 7 + D1 signals land)
- **Date:** 2026-07-09  ·  **Commit:** uncommitted  ·  **Step:** implementation-plan Step 10 (pulled forward by Decision Row 1)
- **Hypothesis:** one model trained on in-season cutpoint snapshots learns the shrinkage
  ("6 hot games → move how far?") better than (a) never updating and (b) a hand-set K=20
  per-game blend.
- **Method:** `models/asof.py` — cutpoint grid (T₀−7d, +30…+150d), season-to-date block
  (STD gp/mpg/rates, last-10 form, days-since-game, `games_so_far`), ROS labels from game
  logs > T (≥5 games **and ≥200 min** — the minutes floor fixed a real bug: garbage-time
  rate labels distorted the fit), walk-forward panel (~33k rows/fold; within-season rows of
  the eval season never in train), cutpoint-balanced fits, union universe (STD-only rookies
  enter with NaN preseason features). Amendments built + measured: per-stat **EWMA half-lives**
  fitted on the training slice (grid {5,10,20,40}) and **naive-blend features** (the K=20
  blend as explicit columns; "start from naive, learn corrections").
  Gate harness: `scripts/eval_asof.py` — ROS level MAE, own top-150 pool, +30/+60/+90,
  2022-23…2025-26, seed 0.
- **10.2 consistency (T₀ vs `project_learned`):** the plan's literal bar (Spearman ≥ 0.98,
  MAE ≤ 0.3) is **below `learned`'s own seed-to-seed noise floor** (two seeds of the identical
  model: Spearman 0.968–0.973, MAE 0.81–0.89). Preseason-only asof = Spearman 0.965 / MAE 0.82
  — indistinguishable from another seed (**no leak**; shared-player labels corr 1.0000). Full
  pooled model = 0.947 / 1.14 — a small, documented pooling cost, not a bug.
- **Result (ROS level MAE, pooled over 12 season×cutpoint cells, seed 0):**
  | config | asof | frozen_t0 | naive | beats frozen | beats naive (cells) | gate tally |
  |---|---|---|---|---|---|---|
  | core | 3.791 | 4.835 | 3.837 | 12/12 | 6/12 | 1/1/1/3 |
  | +EWMA | **3.763** | 4.835 | 3.837 | 12/12 | 6/12 | 1/1/1/3 |
  | +EWMA+blend | 3.806 | 4.835 | 3.837 | 12/12 | 7/12 | 2/1/1/3 |
  **(a) frozen-T₀ is crushed everywhere** — margins 0.6–1.7 MAE/cell; in-season updating is
  the single largest accuracy lever measured in this program. **(b) the naive K=20 blend is
  at parity**: best config −0.07 pooled MAE but only 2025-26 clears the per-season cell
  criterion (adopt needed 3/4). Naive's wins concentrate at +90d (3/4 seasons, every config).
  Fitted half-lives are themselves a finding: **every rate → 40 games (grid max, "use
  everything"); MPG → 10 games** — rates are stable, minutes volatile, EXP-001 restated
  in-season. Fail verdict logged on seed 0 (a pass would have required seeds {0,1,2}; the
  cell pattern is far from flipping on seed wiggle).
- **Verdict:** **engine adopted as the Phase-3 foundation** (Steps 11–13 are built on it —
  in-season eval, nightly pipeline, benchmarks); the *learned-shrinkage-beats-naive* gate is
  **parked, not passed**. Re-gate when the plan's remaining in-season signals exist: live
  teammate-vacated minutes (needs Step 7 injuries — "the single biggest waiver signal"),
  schedule-aware ROS (needs D1), blowout/ramp cleanups (team logs pulled, 17 seasons), and
  the EXP-013d tuner re-arm on this ~9× panel.
- **Skeptic pass:** (leakage) labels strictly > T, features strictly ≤ T, panel seasons
  strictly < eval season, half-lives fitted on training slice only — unit-tested
  (`tests/test_asof.py`, 6 green). (selection) pool = each comparator's own top-150 by its own
  ROS ranking. (season concentration) frozen-T₀ win is uniform; the naive-parity result is
  also uniform (asof wins 2025-26, naive wins +90d cells — not one-season luck).
- **Ledger note:** do **not** re-run STD/EWMA-style form features expecting to beat the naive
  blend at +90d — measured three configs, the deficit sits where rest/tank noise lives (late
  cutpoints) and where the naive blend's directness wins. The next in-season accuracy must
  come from **new information** (who is OUT tonight, schedule, margins), not from re-weighting
  the same game logs. Deployment note until then: the asof engine is still the right daily
  board (it ties naive overall, beats it early-season, and handles rookies/preseason in one
  path).

### EXP-015 — injury / availability history (prosportstransactions)  ·  Status: **split — (a) GP point estimate rejected · (b) Monte-Carlo chronic tails adopted**
- **Date:** 2026-07-09  ·  **Commit:** this commit  ·  **Step:** implementation-plan Step 7
- **Hypothesis:** 17 seasons of injury/IL transactions — the first exogenous availability
  data — (a) finally beat the box-score-only GP model (EXP-004 ceiling: prior-GP→GP Spearman
  0.21, fit R²≈0.03), and (b) give chronically-injured players their own fatter Monte-Carlo
  GP tail instead of an age-bucket pool.
- **Data:** `scripts/pull_injuries.py` — general PST scraper (categories injury+il →
  `injuries.parquet` 47,015 verbatim rows 2009-07…2026-06; category movement →
  `transactions.parquet` for Step 8). Cloudflare blocks requests/curl-impersonation *and
  headless* browsers; the machine's real **Edge driven headed via Playwright** passes
  (~5 s challenge, then plain pagination at 1 page/s). Incremental by date after the first pull.
- **Name-join (hardening per plan 7.1):** `injuries.resolve_players` — normalized name
  (+ alternates + parenthesized given names), team+season disambiguation, career-span
  fallback, dated `ALIASES` (2 entries) + documented `AMBIGUOUS_DROPS` (2 collisions, 20
  events, both fringe); any **new** collision hard-fails. Match rate **99.0%** of 46,828
  events (gate ≥95%); the 103 unmatched names are pre-2009-10 careers (Foyle, Bender,
  Atkins…) legitimately absent from our stats window.
- **Spells:** relinquish→acquire pairing (`injuries.injury_spells`, unit-tested on the plan's
  synthetic 3-transaction sequence + ongoing-spell no-leakage) → 17,977 spells / 1,652
  players (median 6 d; unclosed capped 120 d; an acquire >365 d out can't close a spell).
  `INJURY_FEATURES` as-of Oct 1 per season: events/days 1y/3y, recency (cap 1500), chronic
  (≥3 spells in 2y), severe-bodypart regex.
- **(a) GP point estimate — `learned_inj` (INJURY_FEATURES into y_gp only) vs `learned`,
  control-pool top-150, 4 seasons, seeds {0,1,2}:** pooled GP Spearman ctrl → inj:
  0.204→0.224 (s0), 0.236→0.220 (s1), 0.217→0.194 (s2) — **mean Δ −0.006 vs the +0.05 gate**,
  seed spread 0.043 swamps it; pooled GP MAE **worse +0.20**; player-clustered paired 90% CI
  Δspearman **(−0.029, +0.067) straddles 0**. The exogenous data does *not* rescue the GP
  point estimate — availability stays ~unpredictable at season horizon (EXP-004 stands).
  **Rejected** — `learned_inj` stays registered for re-tests; default board unchanged.
- **(b) Monte-Carlo tails — `build_gp_pool(injury_profile=…)` buckets the empirical GP pool
  by (age × chronic), guard <30 rows → age-only; board carries `inj_chronic_flag`:** pooled
  p10–p90 coverage base → inj: 0.820→0.817 (s0), 0.799→0.791 (s1), 0.807→0.815 (s2) — **all
  within the [0.78, 0.88] gate**; `safe`-rank Spearman **improves in all 3 seeds**
  (0.506→0.514, 0.495→0.502, 0.501→0.505; mean +0.006 — a tie-or-better, within noise).
  **Named chronic-vs-durable cases (seed 0):** Joel Embiid 2024-25 p10 1481→**1189** while
  equal-median durable Paolo Banchero holds 1788; Giannis 2024-25 p10 1991→**1855** vs
  Sabonis 2062; Zion 2025-26 p10 1284→**1173** vs Banchero 1322. **Adopted** — wired into
  `scripts/project.py --ranges` (auto when `injuries.parquet` exists); adopted for the
  *calibration structure* (chronic stars finally carry their own downside), not for a
  ranking-accuracy claim.
- **Skeptic pass:** (leakage) features/flags built from spells **strictly before Oct 1** of
  each panel/target season (unit-tested, incl. ongoing-spell clipping); pool seasons < target
  via `max_start_year`; the scrape itself is dated rows. (selection) (a) control-model pool
  for both arms — identical players; (b) same `learned` board top-100 both arms. (season
  concentration) (a) sign flips by seed/season — noise, and rejected anyway; (b) coverage and
  safe-Spearman moves are uniform across seasons (2025-26 coverage is low ~0.75 in **both**
  arms — a base-model issue, pooled stays in band). Eval-window-conditional until 2026-27
  confirms (rule 10).
- **Ledger note:** the injury feed's real value is **forward-looking** (Step 12 OUT-tonight
  overrides + the EXP-018 re-gate's live vacated-minutes) and the **chronic tail**; do not
  re-try season-horizon GP point regression from history alone. 2020-21's Oct-1 as-of predates
  that covid offseason (bubble ended Oct 2020) — irrelevant here (eval seasons 2022-23+), but
  any consumer touching 2020-21 must pass a later as-of. Judgment harness: `scripts/eval_gp.py`.

### EXP-016 — dated transactions → honest preseason roster maps  ·  Status: **adopted** (unconditional backtest-correctness fix)
- **Date:** 2026-07-09  ·  **Commit:** this commit  ·  **Step:** implementation-plan Step 8.1–8.3
- **What:** every backtest team map so far was `context.target_team_map` — the target season's
  *end-of-season* team, which lets features "know" mid-season trades months early (the EXP-009
  flattery caveat). Replacement: `rosters.preseason_roster_map` = prior-season primary team +
  player-movement transactions dated ≤ Oct 1 of the target season (`transactions.parquet`,
  25,771 rows 2009-07…2026-06 from the shared Step-7 scraper; name resolution reuses the
  Step-7 hardening; PST nicknames era-resolved — Hornets NOH→CHA 2014, Nets NJN→BKN 2012).
- **Validation (8.2, gate ≥90% opening-team agreement on the draftable pool):** pool
  (≥1500 prior-season min) agreement **99.4% / 98.4% / 97.3% / 98.8%** (2022-23…2025-26);
  all-mapped-players agreement 94–95%. Every pool miss inspected: all are genuine post-cutoff
  moves (Harden→LAC Oct 30 2023; the KAT/Randle trade Oct 2 2024; Crowder holdout-traded
  Nov 2022), none are name-join failures. **Bonus finding:** the end-of-season map agrees with
  opening-day teams only **~85–86%** — the honest map is not just leakage-free, it is the
  *more accurate* preseason roster estimate by ~12pp.
- **Adoption:** `project_models(transactions=…)` now derives the honest map for any
  `use_context` / allocation variant; EXP-016b's feature table is built on it per season.
  EXP-009 (parked) and EXP-014 (rejected) carry dated addenda: both verdicts stand a fortiori
  (each failed *with* the flattering map; see their entries).
- **Skeptic pass:** (leakage) map inputs = prior-season stats + transactions dated ≤ Oct 1 —
  nothing from inside the target season; identity resolution may read the full stats frame
  (a name↔id mapping is a static fact, not an outcome). (selection) validation universe =
  prior-minutes threshold, not an outcome. (season concentration) agreement uniform 97–99%.
- **Covid caveat:** target 2020-21's Oct-1 cutoff predates that November's offseason — the
  map degrades to "prior teams" for that one season (documented in `rosters.py`; panel-only,
  eval seasons unaffected).

### EXP-016b — honest-map vacated-usage features  ·  Status: **parked** (aggregate gain, movers unmoved — the EXP-009 profile, done right and still short)
- **Date:** 2026-07-09  ·  **Commit:** this commit  ·  **Step:** implementation-plan Step 8.4
- **Hypothesis:** position-aware vacated **usage** (not just minutes) on the honest Oct-1 map —
  the preseason opportunity signal behind the Maxey pattern — pulls context-driven risers up
  the board and into the pool.
- **Method:** `context.vacated_features` — `VACATED_FEATURES` = vac_min_share_pos /
  vac_usg_pos / vac_fga_pm / vac_ast_pm / star_departed (USG ≥ .24 & MPG ≥ 30, map-dated) /
  arrivals_usg_pos (self-excluded) — per season from the honest map + prior stats + as-of
  positions (`rosters.vacated_feature_table`, 8,563 rows / 15 seasons); variant `learned_vac`.
  A/B vs `learned`, top-150, 4 seasons, seeds {0,1,2}, model-pool + realized-pool views,
  player-clustered CI. Spot-checked real cases (POR 2023-24: bigs' vacancy 0.37 of team
  minutes from Nurkić/Eubanks/Watford departures, Lillard star flag set; WAS: Beal).
- **Rule-11 hygiene:** orthogonal to every existing feature (max |ρ| = 0.083) — genuinely new
  information; y_mpg gain share 7.1% (each vacancy feature ≈ a rate feature's weight;
  `star_departed` unused, 0.1%). Within-group: vac_min_share_pos ↔ vac_usg_pos ρ = 0.97 and
  vac_fga_pm ↔ vac_ast_pm ρ = 0.92 — a slimmer 3-feature version exists if ever revisited.
- **Result (learned → learned_vac, pooled):** mover buckets **unmoved** — signed-bias deltas
  riser +0.003 / big-riser +0.073 mean over seeds, seed spread (0.163) exceeds the win, CI
  straddles 0 in **all five buckets**. Realized-top-150 big-riser capture 62→61 / 62→62 /
  65→59 (mean **−2.3 players** — the recall arm needed +2pp). But **aggregate level MAE
  improves in 9/12 season-seed cells** (pooled −0.004 / −0.125 / −0.151; 2025-26 better all
  three seeds, up to −0.30) — though that spread too exceeds its mean (rule 8: not adoptable
  on aggregate either).
- **Verdict:** **parked.** Neither gate arm (mover gate; big-riser recall +2pp with MAE not
  worse) is met. The features are real (orthogonal, used by the trees, aggregate-friendly) but
  preseason mover bias stays irreducible — EXP-011's floor verdict survives its sharpest
  challenger yet. Kept as `learned_vac` + `vacated_table` plumbing.
- **Skeptic pass:** (leakage) per-season blocks built from the honest Oct-1 map + prior-season
  stats only (unit-tested incl. the target-season-missing hard-fail); no outcome touches the
  map. (selection) pool = each model's own top-150, unchanged; recall judged on the realized
  pool. (season concentration) the aggregate win concentrates in 2025-26; the mover null is
  uniform.
- **Ledger note:** this is where the *feature-into-the-point-estimate* road ends for vacated
  usage. Its remaining path is **EXP-026** (breakout classifier — vacancy × archetype ×
  market gap, judged on recall/above-market rate) and **EXP-028** (rookie model: draft slot ×
  landing-spot vacancy), both of which take `VACATED_FEATURES`/`vacated_feature_table` as
  inputs. Do not re-A/B vacancy variants against the standard mover gate.

### EXP-017 — market benchmark: expert consensus + ADP  ·  Status: **adopted (live overlay)** · EXP-017b **waived-with-condition** (archives < 4 seasons; archiving from today)
- **Date:** 2026-07-09  ·  **Commit:** this commit  ·  **Step:** implementation-plan Step 9
- **What (EXP-017):** the market boards as benchmark + disagreement-finder, per the 2026-07-09
  source hierarchy. `scripts/pull_market.py`: **Hashtag Basketball points-league rankings**
  (the expert-consensus *value* signal — 579 rows, public HTML, plain requests, no Cloudflare)
  and **FantasyPros consensus ADP** (Yahoo/ESPN average — the *availability* signal only, 260
  rows; already showing genuine 2026-27 draft data in July). Date-stamped append-only
  (`data/raw/market/<source>_<date>.parquet`, the DARKO-archive pattern). Name join =
  shared normalizer + the dated cross-source alias map (`injuries.ALIASES` — 2 market aliases
  added); match **100% of our top-150** (99.5% of all 579). `scripts/market_report.py`:
  sleepers/fades vs consensus (`rank_gap = our_rank − consensus_rank`, risk column attached)
  + the D1.4 "likely gone by pick" ADP column. Verified end-to-end against the saved
  `learned_2026-27` board.
- **Vintage caveat (prints on every report):** in July, Hashtag's board is still last season's
  — the consensus benchmark for the 2026-27 draft arrives when they publish preseason
  rankings (~Sept). FantasyPros ADP is already 2026-27. Re-pull both in September; pulls are
  ~seconds each.
- **EXP-017b (market-gap as a feature) — the retrievability audit and the branch taken:**
  Wayback Machine holds *genuine* preseason snapshots — rookie/trade-marker verified — for:
  **2022-23** (FP ADP Oct-02-2022, Banchero ADP 66 ✓; Hashtag Oct-05-2022, ~125 rows ✓),
  **2023-24** (FP Oct-17-2023, Wemby 20 ✓; Hashtag Oct-05-2023, ~180 rows ✓), **2025-26**
  (FP Oct-05-2025, Flagg 36 ✓; Hashtag snapshot only ~25 rows — too thin). **2024-25 is
  unrecoverable:** the only captures (FP Aug-03-2024, Hashtag Aug-17-2024, Basketball Monster
  Oct-02-2024) all still displayed **2023-24 boards** (FP: Wemby ADP 19 ≈ his rookie-year
  ADP, zero 2024 rookies in 257 rows; HT: Embiid #1; BBM: Embiid #1 with g=39 — trailing
  player-rater values, and BBM's projection views are subscriber-side). 3 of 4 eval seasons
  < the spec's ≥4 gate ⇒ **benchmark-only this season, archive from today, re-arm next
  offseason** (`pull_market.py --wayback TIMESTAMP` can replay the audit / ingest archives
  later — the parsers handle the 2022–2025 schema drift).
- **Skeptic pass:** n/a for the live benchmark (no model change). For the audit: vintage was
  established from *content* (rookie presence, known ranks), never from snapshot dates —
  exactly the check that caught three stale-page traps that would have poisoned a backtest
  with lagged-actuals ranks masquerading as preseason consensus.
- **Ledger note:** the standing question (where we disagree, who's right) starts being
  answerable in April 2027 from today's archive. EXP-026's `above-market rate` metric
  consumes the September Hashtag pull; D1.5's rookie market-seed consumes the FantasyPros
  pull (rookies are its expected top-150 unmatched rows — they're kept in the parquet).

### EXP-026 — breakout archetype layer, recall-gated  ·  Status: **both wirings rejected; `breakout_p` ships as an informational draft-sheet column**
- **Date:** 2026-07-09  ·  **Commit:** this commit  ·  **Step:** implementation-plan Step 9b
- **Hypothesis:** an archetype classifier (P(next-season fpts/g jump ≥ +6): improvement
  streak × usage↑ at held TS% × minutes headroom × age 22-24 × experience × pedigree) pulls
  eventual big risers **into/up** the board — judged on recall and above-market rate, never
  per-player error (EXP-011's lesson; the realized-pool recall ~53-70% is the real headroom).
- **Build:** `models/breakout.py` — SEASON-keyed `breakout_feature_table` (fold-safe, the
  EXP-016b pattern), walk-forward `breakout_scores` (LGBM classifier, base rate 12.2%),
  deterministic `apply_breakout_policy` (top-K scores outside the stable core get a bounded
  rank boost; core untouched by construction). Judgment harness `scripts/eval_breakout.py`;
  above-market rate uses the vintage-verified archived Hashtag consensus (2022-23, 2023-24).
- **Classifier reality check (it works as a *classifier*):** walk-forward AUC 0.63-0.73;
  top-20 flag zone hits 3-8 realized breakouts/season (~2-3× the base rate). Preseason flags
  included Reed Sheppard, Jarace Walker, Anthony Black, Stephon Castle (2025-26), Dyson
  Daniels (2024-25), Deni Avdija (2023-24) — real names, before the season.
- **(a) features into the learned model (`learned_breakout`), 4 seasons × seeds {0,1,2}:**
  **rejected.** Mover buckets consistently *worse*: pooled big-riser bias −6.89→−7.73 /
  −7.02→−7.38 / (worse s2), riser bias worse all seeds; realized-pool recall flat
  (Δ −0.003 mean). Aggregate level MAE improves −0.12 (10/12 cells) — the familiar
  aggregate-vs-mover trade, not the gate. Hygiene flag: `mpg_headroom` is |ρ|=0.936 with
  `proj_mpg` — in the regression the group largely re-expresses minutes level.
- **(b) board policy (K=20, core=50, boost=40):** **rejected at the gate.** Recall@150 delta
  **exactly 0.000 on all three seeds**; above-market delta 0. **The decisive diagnostic (what
  stops a sizing grid):** the risers the board misses DO score high (74th-100th percentile —
  Sheppard 100th, Walker 99th, Daniels 98th, Murphy 97th) but only 0/0/1/3 per season crack
  the top-20 flag zone (crowded by same-profile non-risers), and their board ranks are
  150-350 — so even an infinite boost at K=20 caps the gain at ≈ +3pp *before* displacement
  losses. No sizing clears +3pp net. Extension checked: adding the EXP-016b vacated-usage
  group to the classifier is neutral (AUC ±0.05 mixed, flag-zone hits net −1) — the
  Maxey-triad leg that's actually missing is the **market gap** (waived until the EXP-017
  archive accumulates).
- **Ships:** `scripts/project.py --breakout` adds a walk-forward `breakout_p` column to the
  draft sheet — informational only, never re-ranks. The D2 analyst pass (EXP-029) reads it as
  the option-value flag; it's the "at least attempting every breakout" lever in human-decision
  form, where the measured ~2-3× flag lift is genuinely useful.
- **Skeptic pass:** (leakage) features strictly prior-season (unit-tested); labels realized
  next-season deltas; classifier walk-forward; consensus snapshots content-vintage-verified.
  (selection) recall judged on the *realized* top-150 — the anti-selection view by design.
  (season concentration) the (a) mover worsening and the (b) recall null are uniform.
- **Ledger note:** preseason recall does not move by re-ranking what the board already knows —
  the missed risers are *deep* (ranks 150-350) because their projected level is honestly low
  pre-breakout. The remaining recall levers are **new information**: EXP-027 preseason-October
  role signals, EXP-028 rookies, and the market-gap re-arm. Do not re-run flag-zone sizing
  grids on these features.

### EXP-027 — coach changes + preseason-October logs (+ win-totals rider)  ·  Status: **split — (a) coach rejected · (b) preseason roles adopted (October window) · (c) win totals waived**
- **Date:** 2026-07-10  ·  **Commit:** this commit  ·  **Step:** implementation-plan Step 9c
- **Hypothesis (per EXP-026's standing lesson):** the remaining preseason recall levers are
  **new information**, not re-ranking. Two cheap exogenous groups: (a) coaching changes
  (effect hypothesized in new-coach × depth/age interactions — a new coach reshuffles the
  *rotation*); (b) preseason-October game logs (`ps_mpg` / `ps_mpg_delta` / `ps_start_share`,
  role only, never rates — the latest-arriving pre-draft signal).
- **Build:** `data/manual/coach_changes.csv` — the repo's first committed manual dataset
  (143 rows, 2009-10…2026-27; opening-night-coach-differs rule, `interim` = mid-prior-season
  takeover retained; curated from the B-R/Wikipedia coach records, 2013-14 + 2016-17 verified
  row-for-row, 2026-27 = the six completed 2026 hires per the June-23 tracker: CHI Splitter /
  DAL May / MIL Jenkins / NOP Mosley / ORL Sweeney / POR Nori). `models/coaches.py`
  (SEASON-keyed table on the honest Oct-1 map; depth_rank = prior-minutes rank on the mapped
  roster) and `models/preseason.py` (Sep-1→Dec-31 window per season start-year — excludes the
  July-2020 bubble rows, keeps the Dec-2011/Dec-2020 late preseasons; `ps_start_share` =
  top-5-team-minutes proxy, LeagueGameLog has no starter flag; no-preseason-appearance stays
  NaN — "role unknown", never 0). Variants `learned_coach` / `learned_ps`; A/B 4 seasons ×
  seeds {0,1,2}, model-pool + realized-pool views, player-clustered CIs (`--ci` now repeatable).
- **Rule-11 hygiene:** all features pass (worst |ρ| = 0.753, ps_mpg_delta vs proj_mpg — vets
  rest in October, so the delta anti-correlates with prior MPG; coach interactions ≤ 0.31).
  Gain shares tell the story early: preseason group **25-29%** of y_mpg/y_gp gain; coach
  group ~1%.
- **(a) `learned_coach` — rejected.** Realized-top-150 recall Δ mean **−0.2pp** (0/−2.0/+1.3);
  big-riser capture 62→63 / 62→64 / 65→66 (**+1.2pp**, under the +2pp arm); pooled aggregate
  MAE Δ +0.005 with seed spread 0.13 (noise); paired CIs flip sign across seeds (big-riser
  delta +0.34*/+0.15/−0.09 — seed luck by rule 8). The hypothesized interaction effect is too
  diffuse at season granularity. The CSV stays committed — EXP-028's `team_expected_wins`
  slot and the D2 analyst pass can still read it as context.
- **(b) `learned_ps` — adopted (October window).** The recall-arm gate (EXP-016b form:
  realized big-riser recall +2pp with aggregate MAE not worse) passes **on every seed**:
  big-riser capture 62→74 / 62→75 / 65→71 = **+9.2pp mean** (min seed +5.4pp; mean > seed
  spread 6.2pp); realized-top-150 recall 71.3→74.7 / 74.0→74.0 / 72.0→74.7 (**+2.0pp mean** —
  the first preseason recall movement in the program); pooled aggregate MAE **better all
  three seeds** (−0.131/−0.130/−0.167, spread 0.037; 9/12 season-seed cells; 2025-26 the
  largest, −0.46…−0.56, with delta_corr 0.32→0.49 and sign-acc 0.61→0.70). Trade-off, stated
  honestly: paired big-riser *bias* on shared players is slightly more negative
  (−0.28…−0.42/seed, CI excludes 0 in 1 of 3) — the new pool members are deep sleepers whose
  point estimates stay low; recall was the gate, per EXP-011/026.
- **(c) Vegas win totals — waived (non-trivial scrape).** sportsoddshistory.com now 301s to
  covers.com with JS-rendered content; Basketball-Reference preseason-odds pages 403
  automated fetches. Fails the "include only if trivial" bar ⇒ D1.4 `team_priors.yaml`
  manual entry stands.
- **Ships:** ps columns on the draft sheet regardless of verdict (`scripts/project.py
  --preseason`); **`--model learned_ps` = the adopted pre-draft board configuration** once
  the target's October games are cached (July boards keep `--model learned`; the rule-10a
  freeze + D1 sheet should regenerate with it days before the draft). Until then it no-ops
  with a pointer (`re-pull preseason_game_logs` in October).
- **Skeptic pass:** (leakage) preseason games of S predate every regular-season outcome of S —
  the cutpoint for this group is "day before the opener", deliberately later than the Oct-1
  injury/roster convention because the draft actually happens then (stated as a design fact,
  not an accident); coach rows are opening-night facts knowable at the draft; both tables
  SEASON-keyed and unit-tested (bubble filter, NaN semantics, interaction math, empty-target
  hard-fail). (selection) pool = each model's own top-150 unchanged; the decisive metric is
  judged on the *realized* pool. (season concentration) the (a) null is uniform; the (b)
  recall gain is positive in 3-4 of 4 seasons on every seed (largest 2025-26, never
  negative); the MAE win is largest in 2025-26 but positive-mean on all seeds.
  Eval-window-conditional until 2026-27 confirms (rule 10c).
- **Ledger note:** this is the program's proof that the missing riser signal is **new
  information arriving late**: three role-only columns from ~4 October games move recall more
  than every feature engineered from prior-season box scores combined (EXP-008/009/012/016b/
  026 all null on recall). Consequence for the calendar: the board that matters is built
  **after preseason play, days before the draft** — wire the D1 sheet and the dual freeze to
  `learned_ps`, and re-pull `preseason_game_logs` in mid-October 2026.

### EXP-028 — rookie model: draft slot × landing spot  ·  Status: **rejected (pick-order unbeaten; the D1.5 market seed stands alone)**
- **Date:** 2026-07-10  ·  **Commit:** this commit  ·  **Step:** implementation-plan Step 9d
- **Hypothesis:** rookie fantasy value ≈ draft slot + landing-spot opportunity — a small
  walk-forward model (two targets only: `y_mpg`, `y_fpts_pm`; GP never modeled, EXP-004
  applies doubly) beats ranking rookies purely by pick.
- **Build:** `draft_history` dataset (nba_api drafthistory, one static pull, 8,374 rows —
  season-independent ingest path added; **the 2026 class is not on the endpoint yet — re-pull
  before October**). `models/rookies.py`: cohorts = first cached stats row (15 cohorts,
  1,463 rookies, 835 with ≥200-min labels); features = pick(+log) / undrafted-61 sentinel /
  rookie age / years-since-draft (stash) / intl flag / `n_same_pos` + the EXP-016b
  vacancy line, obtained by **injecting rookies into the honest Oct-1 map** so
  `context.vacated_features` serves them directly (96% non-zero — verified, not silently
  empty; Wemby's row sanity-checked). Baseline = pick order valued at the walk-forward
  pick-bucket empirical mean (the fairest version of "everyone can rank by pick").
  Judgment: `scripts/eval_rookies.py`, 4 eval cohorts × seeds {0,1,2}, paired bootstrap CI.
- **Result (pooled, n-weighted; labeled rookies n=213):** Spearman vs realized fpts/g:
  model 0.306/0.311/0.326 vs pick-order 0.331 — delta **−0.025/−0.020/−0.004** (gate:
  ≥ +0.05); CI **[−0.100, +0.051]**; MAE 5.52 vs 5.41 (worse). On season *totals*
  pick-order wins outright (0.623 vs 0.570-0.584). Season detail: the model wins 2022-23
  (+0.08/+0.06/+0.04) and 2025-26 (+0.10/+0.10/+0.13) but collapses on 2023-24
  (−0.30 — the Wemby/Chet cohort, where pick order was nearly perfect at the top).
- **Market comparison (informational, vintage-verified archives):** 2022-23 n=33 — market
  +0.738 / pick +0.641 / model +0.623; 2023-24 n=30 — market +0.615 / pick +0.685 / model
  +0.462. The market itself only splits 1-1 with pick-order on rookies.
- **Verdict:** **rejected** — the spec's anticipated "real finding": pick-order is the
  operative rookie prior, so **D1.5 seeds rookies from the consensus pull (market rank) with
  the pick number shown alongside**; no model column ships. Harness + dataset stay for
  re-arm (college-stat translation, or 2-3 more archived market seasons).
- **Skeptic pass:** (leakage) features are static draft facts + rookie-season bio age/roster
  position + S−1 stats through the honest map; the one approximation — rookie team = his
  rookie-season primary team — is a preseason fact for the overwhelming majority (draft-night
  signings) and is documented in the module. (selection) eval universe = rookies with ≥200
  min, applied identically to model and baseline (a no-show has no rank to score either way).
  (season concentration) the rejection is *not* season-concentrated: the model loses pooled
  with two season wins and one big loss — the instability is itself the finding at n≈50/cohort.

### D1 note (dated, no EXP number — product, not hypothesis)  ·  2026-07-10
- **Built + verified end-to-end:** D1.2 VOR (`models/value.py`, greedy 10-team ×
  ESPN-starting-slot fill, guard/big; unit-tested greedy math). **Sanity finding worth
  keeping: VOR meaningfully reorders even this points league** — 59 of the top-100 move
  ≥ 10 ranks (3 UTIL slots don't wash out guard/big scarcity; e.g. Wemby vor_rank 4 at raw
  rank 13, Sengun 11 at 5). D1.3 `scripts/pull_schedule.py` (regular-season filter validated
  to exactly 1,230 games on 2025-26; per-week/B2B/playoff-week/horizon derivations print).
  D1.4 sheet `scripts/draft_sheet.py`: rank/pos_group/fpts/VOR/ADP/market_priced +
  breakout_p/ps_*/risk pass-through → `draft_sheet_2026-27.parquet`; ADP matched 134/150.
  D1.5 rookie market-seed: mechanism live with a rank ≤ 160 guard (the July FP pull's only
  unmatched names are stale stash players, **not** the 2026 class — seeded 0, correctly).
- **Standing calendar (all one-command re-runs):** ~mid-Aug `pull_schedule.py --expect
  2026-27` (schedule publishes) + derive `fantasy_playoff_weeks`/`league_end_offset_weeks`
  from ESPN's matchup calendar into `league.yaml`; ~Sept `pull_market.py` (Hashtag flips to
  2026-27, FP adds the rookie class → the D1.5 seed goes live); mid-Oct re-pull
  `preseason_game_logs` + `draft_history`, regenerate the sheet from `--model learned_ps`.

### EXP-029 — analyst pass + dual-board freeze (the graded human layer)  ·  Status: **pending (machinery built 2026-07-10 · workflow-v2 amendment 2026-07-12 below: living entries any time, nightly in-season application, scoring = calibration · scores April 2027)**
- **Date:** 2026-07-10 (build) ·  **Commit:** this commit  ·  **Step:** implementation-plan Step D2
- **Hypothesis:** an auditable, written-down analyst pass (the human-judgment layer commercial
  systems keep opaque) adds value over the pure model board — testable only by freezing both
  boards before opening night and grading them against each other in April.
- **Build (the buildable half — done):** `config/analyst_overrides.yaml` (schema per D2.2:
  name/date/category/action/rationale; `none` verdicts logged too; append-only — corrections
  are new later-dated entries, latest wins). `models/analyst.py` + `scripts/apply_analyst.py`:
  deterministic board A → board B (rank_delta repositions with edge clipping; fpts_delta
  adjusts fpts/g, recomputes the total from gp, re-inserts stably with ties keeping incumbents
  ahead; `model_rank` + `analyst_*` audit columns carry the D2.4 attribution; board A's file
  is never touched — enforced in the script). Unmatched/ambiguous override names hard-fail.
  D2.1 trigger generator `scripts/analyst_triggers.py`: top-200 union of our board and the
  Hashtag consensus — |rank gap| ≥ 15 (+ consensus-only `not_on_board`), EXP-026 breakout
  flags, severe-injury returnees (Step-7 spell notes ending in trailing 18 months), rookies
  (`market_priced` / no stats history). 9 unit tests (validation, arithmetic, tie-stability,
  purity, trigger categories).
- **Smoke run (July data, machinery only — no overrides written):** empty overrides →
  board B = board A + audit columns; trigger list = 146 players (101 rank-gap, 14 returnee,
  38 not-on-board, 3 breakout) — **inflated by data vintage** (July board vs July consensus;
  Derik Queen gap −102 is a consensus-staleness artifact, not signal). The real October run
  (learned_ps sheet + Sept/Oct market pulls) is expected to land near the spec's ~30–50.
- **Remaining (calendar-locked, do NOT do early):** the analyst pass itself (last ~2 weeks
  before the draft, off the regenerated trigger list; overrides written with rationales
  before the season) and the D2.3 dual freeze (`frozen_2026-27_preseason_model.parquet` +
  `…_analyst.parquet`, committed before opening night, dated ledger note). D2.4 scoring
  April 2027: standard metrics on both boards + per-adjustment attribution; verdict capped
  at adopted-tentative/parked on a one-season sample.
- **Skeptic pass (build-time):** no leakage possible yet (no overrides exist); the freeze's
  git timestamp is the no-hindsight proof; application arithmetic is unit-tested and pure.
- **Workflow-v2 addendum (2026-07-12, user decision — commits 59beee2 · 724c42a):** the
  layer becomes a **living, this-season supplement** fed by BBM video transcripts:
  drop zone `data/manual/bbm_transcripts/` (rubric + contract in its README) → Claude
  triangulates (model × BBM × own judgment; **agreement = assurance → `none`** unless a
  new mechanism) into `config/analyst_proposals.yaml` → user approves → entries copy into
  `analyst_overrides.yaml` (append-only, latest-dated wins keeps it current July→Oct) →
  applied preseason (`apply_analyst.py`) **and nightly in-season** (`update_daily.py`
  hook, audit columns, `--no-analyst`; wiring verified with a reverted test entry —
  Tatum 1→4, audited). Mid-Oct = re-review of all effective entries + the **unchanged**
  dual freeze. **Gate semantics amended (user: "supplement, not beat"):** D2.4's April
  scoring — including the `BBM <date>:`-tagged subset scored separately — now
  **calibrates** the magnitude rubric and per-source weighting instead of deciding the
  layer's existence. Freeze + scoring mechanics untouched, so the April table is produced
  either way.
- **Rubric v2.1 addendum (2026-07-13, user decision):** sizing is **target-level** —
  `fpts_delta = triangulated ROS fpts/g − model's current base` — so a magnitude gap under
  directional agreement is actionable in both directions (`none` is reserved for target ≈
  base, not merely same-direction agreement), and multiple mechanisms on one player are
  re-triangulated **jointly** into one superseding entry from the current base (the
  engine's latest-dated-wins dedupe already guarantees entries never sum mechanically —
  judged on what the combination means, not the mechanism count). Caps removed by the
  same-day follow-up decision: **no numeric limits** — the mild ≈1 / moderate ≈2 /
  strong ≈3 tiers stay as calibration anchors, judgment dictates magnitude, and large
  deltas require concrete enumerated mechanisms; April 2027 calibrates. Canonical text:
  `data/manual/bbm_transcripts/README.md`.

### EXP-019 — in-season mover eval + lead-time metric  ·  Status: **adopted (diagnostics; seed-0 baselines recorded)**
- **Date:** 2026-07-10  ·  **Commit:** this commit  ·  **Step:** implementation-plan Step 11
- **What:** the metrics that judge the Phase-3 engine on the question it exists for — catch a
  riser early — printed from one command: `python scripts/eval_asof.py --seasons 2022-23
  2023-24 2024-25 2025-26 --cutpoints 30 60 90 --exp019`. Runs the EWMA configuration (the
  EXP-018 pooled winner) with half-lives **frozen as documented constants**
  (`asof.FROZEN_HALF_LIVES`: every rate → 40 games, MPG → 10 — identical in all four folds;
  addendum item 3; `--fit-half-lives` re-checks). Comparators: the naive K=20 updater and
  frozen-T₀. Pool = each model's own top-150 by projected ROS total;
  `actual_delta_ros = act_ros_pg − prior_full_season_pg`, standard bucket edges; floors
  recomputed **per cutpoint** on ROS residuals (`floor_sim` on the pooled asof pool).
- **19.1 In-season mover eval (pooled 4 seasons):** asof's reducible gap is ≈ 0 at +30d
  (big faller +0.17 · riser +0.10 · **big riser −0.02**) and ≤ 0.6 at +60/+90d — *in-season,
  against per-cutpoint floors, the engine's bucket bias is nearly all selection artifact*
  (the EXP-011 preseason verdict restated in-season, now with the machinery to keep it
  honest). asof beats naive on big-riser signed bias at every cutpoint (−4.25/−4.27/−4.54
  vs −6.09/−5.56/−5.79) and on delta_corr (0.67/0.70/0.68 vs 0.61/0.68/0.68); frozen-T₀ is
  far behind everywhere (delta_corr 0.33–0.36). Level MAE: asof ≤ naive at all three
  cutpoints pooled (3.65/3.56/3.94 vs 3.74/3.65/4.04) — consistent with EXP-018's parked
  cell-gate (parity-ish on MAE) while the mover/directional views show where the learned
  engine earns its keep.
- **19.2 Early-riser recall @ +30d (the waiver question):** pooled **51.7%** of the 174
  realized in-season big risers (`act_ros_pg ≥ prior + 6`, ≥ 20 ROS games) are inside the
  asof top-150 ROS board at +30d (by season: 56.8/48.8/56.2/45.7). Captured risers are
  projected at ~half their realized move (mean proj Δ +5.0 vs realized +9.6) — the standing
  baseline for every later in-season improvement.
- **19.3 Lead-time (event-anchored, weekly grid — addendum item 2; never daily refit):**
  193 confirmed role changes (trailing-10 MPG ≥ +6 over baseline, sustained 15 games).
  asof moves ≥ 50% of the realized MPG change before confirmation on **99%** of events,
  median lead **52 days**; naive detects only **70%**. Caveat logged: the per-model median
  lead conditions on that model's own detected subset (naive's 67-day median is computed on
  the 70% it catches, and both models' leads are inflated by events whose T₀ projection
  already sat above the threshold) — when this metric later gates a tuning decision, pair
  it on the common detected set. Standing target: detection ≥ naive, median lead ≥ naive.
- **19.4 League-horizon sensitivity (amendment D1.3b):** with ROS labels truncated at the
  league-end analogue (NBA finale − 3 weeks, `league.yaml` placeholder), 2 of 12
  asof-beats-naive MAE cells flip ⇒ **verdicts move — both views print going forward**
  (the `--exp019` runner computes both unconditionally).
- **Verdict:** adopted as diagnostics (the EXP-006 pattern). Numbers are **seed-0
  baselines**; nothing was tuned against them — re-run under rule 8 (seeds {0,1,2} + CI)
  before any adopt/reject decision leans on a delta between models.
- **Skeptic pass:** (leakage) fold models train on strictly-prior seasons; the weekly-grid
  projections use logs ≤ each grid date; frozen half-lives were fitted on training slices
  in EXP-018 and are constants here. (selection) pools are each model's own top-150 —
  identical construction across models; floors are computed per cutpoint on the same pools;
  the 19.3 conditioning caveat is written above. (season concentration) 19.1/19.3 verdicts
  hold in every season; 19.2 recall ranges 46–57% with no outlier season.

### EXP-021 — distributional board: learned ranges (empirical residual CDF) vs the hand-set SD_PG=9  ·  Status: **rejected as the default spread** (machinery ships; re-arm named below)
- **Date:** 2026-07-10  ·  **Commit:** (Step 14 commit)  ·  **Step:** implementation-plan Step 14
- **Hypothesis:** per the EXP-013c replacement note, drawing per-game values from the
  **empirical walk-forward residual CDF** (piecewise-linear through q25/50/75/90, tails
  extended with the adjacent segment's slope, floor 0) should fix the big-riser escape rate
  (the CDF carries the right-tail skew a normal can't) while keeping overall [p10, p90]
  season-total coverage in [78%, 88%] — replacing the hand-set `SD_PG = 9`.
- **Method:** `uncertainty.simulate_ranges(pg_quantiles=…)` (piecewise-CDF sampler; normal
  path kept as fallback); `residual_pool` = out-of-sample residuals of the learned model on
  its own top-150 pools over the 4 seasons before each target (each board trains strictly
  before its season; boards cached across targets); **both arms share the adopted
  (age × chronic) GP pools** (EXP-015/7.3b) so only the per-game spread differs. Scoreboard:
  `eval_movers.range_coverage` per actual-Δ bucket (`scripts/eval_movers.py --ranges`),
  2022-23…2025-26, seeds {0,1,2}, player-clustered paired 90% CI on the coverage delta.
  Third arm `resid_cdf_cal`: one width multiplier from {1.0…2.0} calibrated **walk-forward**
  (target 0.83 total coverage on the pre-target seasons; zero target-season data).
- **Result (seed means; mover-pool coverage):** `sd_pg9` ALL **0.805** / big riser **0.671**;
  raw `resid_cdf` ALL **0.668** / big riser **0.529**; calibrated `resid_cdf_cal` ALL
  **0.719** / big riser **0.598** (seed spreads ≤ 0.010 / 0.034 — far below the deficits).
  CI (cal − sd_pg9): ALL ≈ −0.086 [−0.107, −0.067], big riser ≈ −0.074, CIs exclude 0 in all
  seeds. Top-100: coverage 0.807 vs 0.741; safe-Spearman 0.517 vs 0.499 (slightly worse);
  ceiling-Spearman 0.503 vs 0.512 (slightly better). **Gate failed on every clause.**
- **Why (the real finding):** `SD_PG = 9`'s excess width over the honest per-game marginal
  (residual σ ≈ 5.6, q25/q90 ≈ −4.3/+7.5) is **load-bearing** — it absorbs the GP × per-game
  covariance the independent Monte Carlo drops, model-level bias, and **era drift**:
  total-level dispersion is *rising*, so walk-forward coverage at scale 1.0 declines
  monotonically across targets (0.848 → 0.822 → 0.761 → 0.694), and any honestly-lagged
  calibration trails realized dispersion by ~9–13pp of coverage. The skew premise also
  fails: big-riser escapes are a *width* phenomenon, not shape — the CDF's +7.5 right tail
  is still narrower than the normal's inflated +11.5.
- **Verdict:** rejected — `SD_PG = 9` + (age × chronic) GP pools remain the default board
  spread. The piecewise-CDF path, `residual_pool`, and `calibrate_resid_scale` ship as
  opt-in infrastructure (`pg_quantiles=`), documented-rejected as the default.
- **Skeptic pass:** (leakage) none in the candidate — residuals, calibration, and GP pools
  are all strictly pre-target; the calibration CDF's in-window caveat (each calibration
  season contributes ~¼ of the residual pool it is scored against) *favours* the candidate,
  which still lost. The **incumbent** carries an in-sample advantage — SD_PG was hand-tuned
  historically to ~80% coverage on an overlapping window — but the rejection stands on the
  baseline-free absolute clause (ALL 0.719 < 0.78) as well. (selection) pooling is the
  model's own top-150; buckets are outcome-conditioned by design, same as every scoreboard
  metric. (season concentration) none — the candidate trails in all four seasons.
- **Ledger note / re-arm:** the incumbent is decaying too — `sd_pg9` itself broke the window
  in 2025-26 (top-100 coverage 0.719), and there the calibrated arm already **matched/beat
  it** (0.729): the adaptive instrument catches up as the stale constant falls behind.
  Re-arm EXP-021 after the 2026-27 rule-10a freeze scores (one true out-of-sample season),
  judging `resid_cdf_cal` with the calibration target raised toward the window's top (~0.88)
  to hedge the measured drift; the Step-12 nightly archives eventually enable rolling
  in-season recalibration. Do **not** revisit raw (uncalibrated) residual CDFs or the
  EXP-013c quantile heads as the range source.

### EXP-030 — vacated-minutes absorption + live OUT-redistribution  ·  Status: **adopted-tentative** (rule 8: the decisive CI straddles 0; harm excluded, auxiliary wins consistent — re-affirm April 2027 from the nightly archives)
- **Date:** 2026-07-11  ·  **Commit:** (this commit)  ·  **Step:** implementation-plan Step 16 (Phase 5)
- **Hypothesis:** when a rotation player is OUT, flowing his projected minutes to teammates
  by **fitted** absorption weights (instead of waiting for the EWMA to see the box scores)
  improves treated-segment ROS accuracy and moves the board earlier on role changes — the
  EXP-018 re-gate's named "OUT-tonight / live teammate-vacated minutes" item, built as a
  board layer (`models/absorption.py` → `eval_asof.py --exp030` → `update_daily.py`).
- **Method:** joint-attribution dataset from prior-season game logs per fold (171k–221k
  teammate rows / 17k–22k team-games; absence = appeared for the team ≤ 14d prior, form
  ≥ 15 MPG, not in tonight's box; strictly-pre-game trailing-10 baselines; |margin| ≥ 25
  blowouts excluded via `team_game_logs` — its first wiring). Bounded LSQ (θ ∈ [0,1],
  free intercept) over 6 cells {same/cross-pos} × {starter/rotation/fringe}; a parallel
  head fits per-game FGA absorption. Backtest OUT-sets = spells open at T with
  **median-estimated** return (severe ≈ 37–40d, normal = 6d, fit on training spells; the
  recorded spell end is an oracle reserved for live use where news supplies `out_until`).
  Eval: 4 seasons × cutpoints {+30/60/90} × seeds {0,1,2}; treated segment = touched rows
  in the asof top-200 with ≥ 5 ROS games (n ≈ 1,450/seed).
- **Fitted tiers (reality anchor — vs the DFS folk numbers, per 30 vacated MPG):** same-pos
  fringe **3.2** / rotation **2.2** / starter **1.2**; cross-pos 1.5 / 0.8 / 0.6. Both
  monotonicities right (same-pos ≈ 2× cross-pos; headroom ordering within relation); a
  realistic roster absorbs ~17 of 30 collectively (teams also shorten rotations) — the
  folk "backup +12–15" concentrates on one man, the cell model spreads it over the cell.
  FGA head shows the same ordering. Tiers deterministic across seeds.
- **Result (treated segment, pooled):** ΔMAE (redist − asof) seed-mean **+0.002** (spread
  0.005), clustered 90% CIs all straddle 0 ([−.011,+.008] / [−.006,+.014] / [−.007,+.013])
  — the layer is MAE-neutral at ROS horizons, and structurally so: the median non-severe
  absence is 6 days, so honest proration averages only **0.14 MPG** of flow. But: treated
  **signed bias −0.15 → −0.01** (the systematic under-projection of players with an OUT
  teammate essentially removed; better at all 3 cutpoints, all seeds), **lead-time median
  52.4→60.0 / 56.0→57.6 / 52.4→59.1 days** with detection 0.98–0.99 → 0.99–1.00 (better or
  equal in every season, all seeds), and **untouched-row identity = 0 mismatches** (×3
  seeds) — provably a no-op away from OUT events.
- **Verdict:** **adopted-tentative** — exactly rule 8's category: the decisive CI straddles
  0 (upper bound ≤ +0.014, ≈ 0.4% of MAE — harm excluded), the auxiliary wins are
  season-consistent, and the cost is zero. Wired into `update_daily.py` (fault-isolated;
  `--no-redist` opt-out; `redist_mpg` audit column; weights fit once per season and cached).
  Offline dry-run 2026-07-11 clean (91 OUT, 386 teammates adjusted). Re-affirm April 2027
  by scoring the season's nightly `ros_board/` archives — at **short horizons** (e.g.
  next-14-day windows), where the layer's flow isn't prorated away; ROS-horizon ΔMAE is
  settled (neutral), don't re-litigate it.
- **EXP-018 naive re-gate (its named re-arm condition, run herewith):** asof+redist beats
  the naive updater at ≥ 2/3 cutpoints in **1/4 · 2/4 · 2/4 seasons** (seeds 0/1/2; gate
  needs 3/4) → **the naive gate stays parked**. Trend worth recording: 2025-26 favors the
  model at 3/3 cutpoints (seed 0) and recent seasons lean model — recheck after 2026-27.
- **Skeptic pass:** (leakage) absorption weights, spell-duration medians, pre-game
  baselines, OUT-sets, and team maps are all strictly ≤ T or prior-season; backtests never
  see a spell's recorded end. (selection) the treated segment conditions on **teammate
  status** (treatment), never on outcomes; the untouched-identity check is the no-leak
  proof on everyone else. (season concentration) bias and lead-time improvements appear in
  all four seasons; MAE-neutrality is uniform.
- **Ledger note:** the ROS horizon structurally dilutes this layer — don't retry variants
  hoping for ROS-MAE wins (short absences prorate to ~0.1 MPG by construction). The value
  is same-day: bias removal on treated players and ~a week of extra lead. The usage
  (FGA-bump) second mode is fitted but **unjudged** — arm it only after the April 2027
  short-horizon scoring says the minutes mode holds.

### EXP-031 — budget-reconciled minutes (allocation v2)  ·  Status: **rejected (both wirings) · the 17.1 budget diagnostic adopted** (the budget violation is real and error-linked — but correcting it centers errors without shrinking them)
- **Date:** 2026-07-11  ·  **Commit:** (this commit)  ·  **Step:** implementation-plan Step 17 (Phase 5)
- **Hypothesis:** the 240-minute identity, re-entered per the EXP-014 ledger note (GP never
  a divisor): (a) depth-chart features into the **y_mpg model only** (`learned_depth` =
  `ALLOC_FEATURES` + `pf_per_min`, honest Oct-1 maps); (b) soft post-hoc reconciliation in
  **headroom space** (`allocation.reconcile_minutes`: team budget gap distributed
  ∝ (40 − mpg), so stars barely move — the answer to EXP-014's star tax), λ nested-tuned
  on folds ≤ 2021-22 (rule 10b; the script refuses later folds).
- **17.1 diagnostic (adopted — `scripts/eval_budget.py`, run before either A/B):** the
  breakthrough-plan's "teams silently sum to 260+" is **confirmed and quantified**: on
  honest Oct-1 rosters the learned board's modeled players consume mean **B_team =
  1.06–1.08× of the full 240×82 supply** vs the honest target 0.89 (1 − rookie_reserve) —
  pooled overshoot **+0.176** of supply (p10 +0.05, p90 +0.33), i.e. ~+42 phantom
  MPG-equivalents per team-game. And it is error-linked: **corr(overshoot, team mean
  minutes error) = +0.52 / +0.45 / +0.24 / +0.37** per season, pooled **+0.381** over 120
  team-seasons. Sub-step (b) survived its kill test — the failure below is in the *cure*,
  not the diagnosis.
- **(a) `learned_depth` — rejected.** Pooled top-150 minutes MAE delta **flips sign across
  seeds** (−0.052 / +0.045 / +0.027; mean +0.007, spread 0.097 — seed noise); moved-segment
  improvement mean **−4.7%** (gate: −10%); the rest segment **degrades +3.5%** in 2/3 seeds
  (gate: ≤ +2%); clustered CIs straddle 0. The mover view shows the EXP-013d pathology:
  a **uniform downward bias shift in every bucket** — big riser **−0.70 [−0.94, −0.47]**
  (CI excludes 0, the wrong way: the under-projected bucket gets more under-projected).
  Depth features mostly re-price the level, not the person.
- **(b) `recon λ=0.25` — rejected.** λ* = 0.25 in **all three seeds** (stable; λ=1
  overcorrects badly, +9% MAE) with a real tuning-fold win (~−1%). On the eval window:
  minutes MAE ≤ control in 3/3 seeds but **sub-noise** (mean −0.011, spread 0.024, CIs all
  straddle); moved+turnover segments −0.5% vs the −10% bar; level MAE −0.02 (flat). The one
  consistent effect: **pool minutes bias +0.84 → +0.30 (−65%)** — the overshoot removal
  works exactly as designed, but *centering* errors without *shrinking* them does not
  reorder a ranking.
- **Verdict:** both wirings rejected; `learned` regression minutes stand unchanged. The
  diagnostic is the keeper — `eval_budget.py` is the standing instrument for "does the
  budget bind?", re-runnable in one command. Machinery stays (registry variant
  `learned_depth` documented-rejected; `reconcile_minutes`/`budget_table` importable).
- **Skeptic pass:** (leakage) honest Oct-1 maps throughout; `rookie_reserve` train-slice
  only; λ selected on folds ≤ 2021-22 (enforced by the script); depth features =
  prior-season minutes + roster facts. (selection) segments defined by roster facts
  (moved / team turnover), never outcomes; pools are each model's own top-150. (season
  concentration) (a)'s rest-segment degradation appears in 2/3 seeds — the rejection is
  not one season's; (b)'s effects are uniform.
- **Ledger note — the Phase-5 shape, now seen twice (EXP-030/031):** budget/OUT
  information **centers** minutes errors (bias −65% here; treated bias −85% in EXP-030)
  but does not **shrink** them at season horizons — per-player minutes noise dominates the
  systematic component the constraint removes. Do not re-run (a)/(b) hoping for MAE wins
  at this horizon. Legitimate re-arm points only: (i) the EXP-014 note's other sanctioned
  path — allocate **season totals for total-based decisions** (VOR replacement levels,
  GP-weighted totals); (ii) a future default model whose overshoot-error correlation
  strengthens materially (re-run the diagnostic each adopted-model change); (iii) bias-
  sensitive consumers (calibrated ranges, EXP-021's re-arm) that benefit from centered
  minutes even without MAE gains.

_Next experiments — numbering reserved by [`docs/implementation-plan.md`](docs/implementation-plan.md)
(the execution spec; run in its Step order, as re-routed by the dated notes in its tracker — latest:
the **2026-07-09 draft-focus re-route + gap-closer addendum**). Done: EXP-011…014 (Phase 0+1),
EXP-018 (engine; naive gate parked), **EXP-015** injuries (Step 7, split verdict above — scraper +
spells now serve Step 8 and the Step-12 live feed), **EXP-016** honest preseason maps (adopted;
backtest-correctness fix) + **EXP-016b** vacated usage (parked; feeds EXP-026/028),
**EXP-017** market benchmark (adopted live; 017b waived — 2024-25 preseason archives proved
unrecoverable, archiving from today, re-arm next offseason), **EXP-026** breakout layer (both
wirings rejected; breakout_p ships as a draft-sheet column), **EXP-027** coach + October logs
(split above — `learned_ps` is the adopted October board; re-pull preseason logs mid-Oct),
**EXP-028** rookie model (rejected above — pick-order unbeaten; D1.5 market seed is the rookie
source, pick number shown alongside; re-pull `draft_history` before October for the 2026 class).
**Draft-facing, calendar-critical, in order: D1** decision layer incl. the D1.5 rookie market-seed
(product; **scoring + league confirmed 2026-07-10: ESPN default points, 10 teams, weekly H2H —
scoring.yaml already matched, no re-runs**) → **EXP-029** analyst pass + dual-board freeze (Step D2 —
**machinery built + tested 2026-07-10; workflow v2 live 2026-07-12** — living entries any
time via `analyst_proposals.yaml` → approval, applied nightly in-season too; mid-Oct =
re-review + dual freeze; both freeze boards regenerate with
`learned_ps` after preseason tips; April 2027 scoring now *calibrates* per the amended
gate). **In-season: EXP-019** (Step 11) done above
(adopted diagnostics — riser-recall 51.7% / lead 52d @ 99% are the standing baselines) ·
**Step 12** nightly pipeline built + dry-run clean 2026-07-10 (`update_daily.py`; cron it from
opening night — the archives it accumulates are EXP-020's input). **EXP-021** learned ranges
done above (rejected as the default spread — SD_PG=9 stands; re-arm with the raised
calibration target after 2026-27 scores). Remaining, all calendar/archive-gated: **EXP-020**
benchmarks (re-arm when ≥ 1 season of date-stamped DARKO/ADP archives exists) · **EXP-029**
scores April 2027 · EXP-021 re-arm per its note. Deferred: **EXP-022/023/024**
(they chase the ≈0 preseason gap) · **EXP-025** (reserved) rotation-survival hurdle.
Post-ship frontier (Step 15): rookies beyond the market seed, category scoring, an official
injury feed, the home-grown online skill layer (model-foundation §3C). **Phase 5 (added
2026-07-10, user direction — "minutes economy") is COMPLETE 2026-07-11: EXP-030**
OUT-redistribution adopted-tentative (nightly layer live in `update_daily.py`; naive gate
re-ran, stays parked; re-affirm at short horizons April 2027) · **EXP-031** rejected (both
wirings) with the **17.1 budget diagnostic adopted** (`eval_budget.py` — overshoot +0.18 of
supply, error-corr +0.38; re-run at every adopted-model change). **Next build: Step 19**
(implementation-plan **Phase 7**, added 2026-07-15) — the **live draft room**; product step,
no EXP number. 19.1–19.3 (ESPN feed + ID join + dynamic replacement) shipped 2026-07-15,
verified end-to-end on the real league. **19.4 is next and is the one sub-step with a real
gate:** the H2H weekly variance layer must hit weekly-total p10–p90 coverage ∈ [78,88]% or
19.5–19.6 don't ship. Note for that build — `SD_PG=9` is **season-total**-calibrated (~60%
wider than the honest per-game marginal *on purpose*; EXP-021 re-affirmed that width as
load-bearing for season ranges) and must **never** be used as a per-game sigma in a weekly
sim; `σ_level` there comes from EXP-021's *rejected* residual-CDF artefact, which is the
honest marginal and is exactly right for this different job (the EXP-021 verdict for the
season board stands untouched). Step 18 (Phase 6, analyst-delta staleness) follows 19 — it
serves the nightly loop, which can't pay off before opening night, whereas the draft is ~Oct.
Otherwise everything waits on the standing calendar
(mid-Aug schedule → Sept market → mid-Oct analyst re-review + dual freeze →
opening-night cron → April 2027 scoring + re-arms)._
