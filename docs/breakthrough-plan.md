# Breakthrough plan — where the accuracy actually is (Stage 7, rev. 3)

Status: **proposal for review** (2026-07). Companion to `docs/model-foundation.md` and
`EXPERIMENTS.md`. Written after EXP-006…EXP-010 — i.e. after the meta-finding that **four
feature experiments (trajectory, team-context, recency, recency+context) all improved
aggregate MAE and none moved the riser buckets**.

This note answers: *why* has no experiment produced a breakthrough, what is the honest
accuracy ceiling of the current problem formulation, and what plan actually gets to "the
most accurate fantasy prediction model."

> **Execution:** this doc is the *diagnosis and rationale*. The step-by-step build spec —
> exact files, function signatures, commands, and adopt/reject gates, in a strictly linear
> order — is [`docs/implementation-plan.md`](implementation-plan.md). Work from that file.

---

## 1. Why nothing has cracked the riser buckets — a structural diagnosis

Three separate causes, in increasing order of how much they change the plan:

### 1a. The features tried so far are all *derived from what we already hold*

Trajectory slopes, season-end recency, and team-level turnover are all transformations of
`player_season_stats` + `game_logs`. LightGBM over raw rates + age already recovers most
of what those transformations express (EXP-008's ledger note said exactly this). The two
levers repeatedly named and never tried — **exogenous injury/news data** and **dated
preseason transactions/depth charts** — are the only *new information* on the table.

### 1b. Minutes drives the error, but no experiment modelled minutes as what it is

EXP-001: ~55% of per-game error is minutes. Yet every minutes treatment so far is
**per-player** — v2m ages a player's own MPG; EXP-009's context features are per-player
covariates. Real NBA minutes are a **team-constrained allocation**: exactly 240 per game,
divided over a specific roster, by position and pecking order. A riser's minutes rise
*because specific teammates' minutes fell or left* — that is an allocation constraint, not
a player feature. No model in the repo enforces (or even sees) the 240-minute budget, and
projected team totals can silently sum to 260+. This is the biggest **untried in-repo**
structural change.

### 1c. ⚠️ The metric of record has a built-in selection effect — part of the ±8 bias is irreducible

The mover buckets condition on **realized** YoY change. A player lands in "big riser"
partly because of forecastable causes (opportunity, age-22–24 leap) and partly because of
**positive realized shocks** (teammate injuries during the season, luck, health). By
selecting on the outcome, the big-riser bucket is *guaranteed* to contain players whose
realized level exceeds any honest conditional-mean forecast — so **even the Bayes-optimal
point projection shows negative signed bias in that bucket**. The mirror holds for
fallers.

This single fact explains the meta-finding cleanly: each feature experiment improved the
conditional mean (hence aggregate MAE fell, 3–4 seasons out of 4), but the buckets kept
re-selecting on the residual shock, so the tail bias barely moved. **We have been chasing
a number that cannot reach zero, without knowing its floor.** Sizing that floor is the
first action item (EXP-011) — everything else is prioritized by what it says.

Two complementary metrics don't have this defect and should join the scoreboard:
- **Bias bucketed on *predicted* Δ** (a pure calibration question: "when we say a player
  rises 5, does he rise 5 on average?") — fully reducible in principle.
- **Distributional calibration per bucket** (did the realized outcome land inside our
  p10–p90?) — the honest formulation when part of the move is genuinely stochastic.

---

## 2. The reframe: what "most accurate" can honestly mean

Split by information regime:

| Regime | What's knowable | Ceiling | Our status |
|---|---|---|---|
| **Preseason, own-history features** | central tendency + mild shrinkage tuning | ~exhausted (EXP-007 took the win; 008/008b/009/009b confirmed the wall) | done |
| **Preseason, exogenous data** (injury history, dated transactions, depth charts, market) | opportunity-driven moves, availability tails | real headroom, un-attempted | **the preseason lever** |
| **In-season, as-of-date** | the role change is *observed* after a handful of games; news makes availability directly knowable (EXP-004's R²≈0.03 ceiling does not bind) | largest headroom in the whole project | **not built yet** |

The uncomfortable-but-freeing conclusion: **the preseason riser problem is partly
irreducible, and the in-season riser problem is mostly an engineering problem** (the
as-of-date engine `project(data ≤ T)` at game-log granularity, which `docs/model-foundation.md`
already specifies but which no experiment has exercised). The "huge breakthrough" the
project is looking for lives in:

1. **Phase 0** — measure the preseason floor so we stop judging experiments against zero;
2. **team-constrained minutes allocation** — the one big untried structure on data we hold;
3. **exogenous data** — the only new preseason information;
4. **the in-season engine** — where accuracy gains are structurally available and where
   the stated highest-value use (waivers, catching risers early) lives anyway;
5. **a distributional board** — because for the irreducible remainder, being *calibrated
   about the tail* (who has a fat right tail) is itself draft/waiver edge.

---

## 3. The plan

Each item is one `EXPERIMENTS.md` entry, adopt-or-reject, judged on the (upgraded)
Stage-7 scoreboard. Phases are ordered by information-per-effort; 0 and 1 need no new data.

### Phase 0 — size the ceiling (EXP-011, days, existing data) ← ✅ COMPLETE (2026-07-08, EXP-011: riser reducible gap ≈ 0 on the model pool — Decision Row 1; headroom = sleeper recall)

Two cheap diagnostics that tell us what every later experiment can possibly earn:

- **Selection-floor simulation.** Treat the learned model's predictions as truth, add
  noise calibrated to observed residual variance, generate synthetic "actuals," bucket on
  synthetic realized Δ, measure the signed bias a *perfect* forecaster shows. That number
  (per bucket) is the floor. Report every future experiment as
  `(measured bias − floor) / (current bias − floor)` — fraction of the *reducible* gap closed.
- **Per-bucket oracle decomposition** (EXP-001 extended to the mover buckets): re-run the
  mover eval feeding **actual minutes** (rates as projected), then actual GP. How much of
  the −8.9 big-riser bias is minutes-driven? Expected answer: most of it — which would
  confirm minutes/role as the reducible target and promote Phase 1c.
- Add the two selection-free metrics (predicted-Δ-bucket calibration, distribution
  coverage per bucket) to `eval_movers.py` as standing columns.

**Decision gate:** if (bias − floor) is small in the tails, stop optimizing preseason
point bias entirely and shift weight to Phases 3–4. If minutes-oracle closes most of the
gap, Phase 1c (allocation) is the headline preseason bet.

### Phase 1 — the untried levers on data we already hold ← ✅ COMPLETE (2026-07-08, EXP-012 parked, EXP-013 all rejected, EXP-014 rejected — exactly as Phase 0 predicted; see EXPERIMENTS.md)

- **EXP-012 — de-confound recency** (named in the 009b ledger note; cheapest test):
  `season_recency_table(skip_last=…)` to trim rest/tanking-contaminated season-end games;
  mid-late window variant; explicit **post-trade split** (games since last
  `TEAM_ABBREVIATION` change) as a clean role-change signal. Success = recency's 3/4-season
  aggregate win *without* the downward bias that worsened the riser buckets.
- **EXP-013 — objective-side changes** (all four failed experiments changed *features*,
  never the *loss*; this is cheap and orthogonal):
  - train the MPG/rate models on **Δ-from-own-baseline** targets instead of levels
    (forces the model to explain change rather than restate level);
  - **sample-weight** the panel toward draftable + mover rows (the GBM currently
    optimizes the stable majority — ~5k rows, movers are rare);
  - **quantile heads** (LightGBM `objective="quantile"`, p25/p50/p75/p90 per target) —
    feeds Phase 4 and replaces the hand-set `SD_PG=9`.
- **EXP-014 — team-constrained minutes allocation** (the big structural bet, per §1b):
  model each player's **share of his team's minutes** rather than raw MPG; features =
  own prior share, position, depth-chart rank among same-position teammates, teammates'
  vacated share (who *specifically* left above/below him); normalize projected shares to
  the 240-minute budget per team. This is ROADMAP 7.A's "position-aware redistribution"
  done as a structure, not a feature. Success = minutes MAE **and** riser-bucket bias for
  the role-change subpopulation (segment it — aggregate hides it).

### Phase 2 — new exogenous data (the only new preseason information)

- **EXP-015 — injury/availability history (7.C):** `nbainjuries` / prosportstransactions
  → (a) GP features that finally attack the R²≈0.03 ceiling, (b) **per-player**
  Monte-Carlo GP tails (Stage 6 currently uses an age-bucket pool). Judged on GP MAE,
  range calibration, and `safe`-ranking of injury-prone stars.
- **EXP-016 — dated preseason transactions + depth charts:** strict preseason rosters
  (fixes EXP-009's end-of-season-team leak, which flattered the backtest) feeding the
  Phase-1c allocation model with *true* as-of-draft rosters.
- **EXP-017 — market/ADP:** pull ADP + one consensus source. Primary use = benchmark and
  disagreement-finder (the actionable calls are where we differ and are right); secondary,
  eval-gated use = a market-prior feature — with the explicit check that it doesn't wash
  out our mover edge (the known ensemble failure mode).

### Phase 3 — the in-season as-of-date engine (the actual breakthrough) ← ◐ ENGINE BUILT + GATED (2026-07-09, EXP-018: beats frozen-T₀ 12/12 — the largest lever measured; naive-parity gate parked pending Phase-2 signals; Steps 11–13 remain)

The system `docs/model-foundation.md` §4 specifies, now built and evaluated:

- **`project(data ≤ T)` at game-log granularity** — features computed from
  `game_logs.date ≤ T` (season-to-date splits, last-N form, days-rest, post-trade
  windows), panel trained on **in-season cutpoint snapshots** (not just season
  boundaries) so the model *learns* small-sample shrinkage — "6 hot games → move this
  far." This also multiplies the training panel (~5k season rows → tens of thousands of
  cutpoint rows), directly attacking the small-data constraint.
- **The parked in-season eval (EXP-006's other half):** at cutpoints (10/20/40/60 games),
  score ROS projection vs actual remainder, mover-segmented, plus a **lead-time metric**:
  how many games after a real role change does our projection move (vs a naive last-N
  baseline, and vs archived DARKO once enough snapshots accumulate)?
- **Nightly pipeline + news/status feed** (`model-foundation.md` §7): injury report,
  lineups, transactions. In-season, availability is *news*, not inference — the whole
  EXP-004 ceiling stops binding.
- DARKO date-stamped archives (EXP-010) start earning their keep here as an in-season
  benchmark/feature with real history.

### Phase 4 — the distributional board (edge from the irreducible remainder)

- Quantile-learned ranges (EXP-013) replace the generic `SD_PG=9` Monte-Carlo spread;
  per-player GP tails (EXP-015) replace the age-bucket pool.
- Rank stances get sharper: `safe` for early rounds, **`ceiling` for late rounds /
  waivers** — a calibrated fat right tail on a cheap pick *is* the riser edge, expressed
  honestly instead of as a point estimate we know is capped.
- Eval: coverage per mover bucket (are big risers inside their p90? currently the tails
  are exactly where ranges should earn their keep).

---

## 4. Scoreboard changes (so "breakthrough" is measurable)

1. Keep the mover-bucket signed bias, but report it **against the EXP-011 floor**, not
   against zero.
2. Add predicted-Δ-bucket calibration (selection-free, fully reducible).
3. Add per-bucket range coverage (the distributional formulation).
4. Add the in-season lead-time metric once Phase 3 lands (games-to-detection of real
   role changes).

## 5. Practicalities

- **Data access:** this remote env cannot reach `stats.nba.com` (egress-blocked) and
  `data/` is gitignored. Phases 0–1 need only the existing cache → run locally, **or
  commit a trimmed parquet snapshot** (season stats + bio + the per-(player,season)
  recency table; game logs only if Phase 3 work happens remotely) to unblock remote
  experimentation. Recommended: snapshot on a branch, keep raw pulls local.
- **Order of operations if time is scarce:** EXP-011 (days, changes how everything else
  is judged) → EXP-012 (cheapest named test) → EXP-014 (biggest in-repo bet) → Phase 3
  (biggest overall payoff) with Phase 2 data pulls proceeding in parallel.
- **Guardrails unchanged:** strict as-of-date no-leakage, refit per fold, the
  backtest-skeptic pass before any `adopted`, Marcel kept as the "did we lose signal?"
  fallback, every attempt logged in `EXPERIMENTS.md` adopted **or** rejected.
