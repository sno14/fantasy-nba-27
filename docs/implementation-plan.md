# Implementation plan — the linear execution spec (Stage 7 → ship)

Status: **the execution source of truth** (2026-07). This turns
[`docs/breakthrough-plan.md`](breakthrough-plan.md) (the *why* and the phase logic) into a
**strictly linear sequence of steps** that can be followed mechanically. Work top to bottom.
Do not start a step before the previous step's **Done when** box is fully satisfied.

**Relationship to the other docs**
- `docs/breakthrough-plan.md` — the diagnosis and phase rationale. Read once; don't edit
  except to mark phases complete.
- `docs/design-critique.md` — the standing senior-review of the design (hidden assumptions,
  leakage risks, statistical issues, better decompositions). Its action items are folded
  into this plan as rules 10–11, per-step amendments, and Phase 1.5 (Steps R1–R3).
- `ROADMAP.md` — high-level stage tracking; each step here names the checkbox it closes.
- `EXPERIMENTS.md` — the append-only results ledger; each experiment step here contains the
  exact entry stub to fill in.
- **This file** — what to build, in what order, to what spec, with what accept/reject gate.

---

## 0. Rules of engagement (read before every session)

1. **One step at a time, in order.** Steps are sequenced so each produces either a decision
   input for the next or infrastructure the next requires. Skipping breaks the gates.
2. **Every experiment step ends in `adopted` / `rejected` / `parked`** in `EXPERIMENTS.md`
   using the entry stub given in the step. No experiment is "done" until logged.
3. **The gates are floor-adjusted.** After Step 2, every mover-bucket bias number is judged as
   `closed = (bias_old − bias_new) / (bias_old − floor)` — the fraction of the *reducible* gap
   closed — never against zero. Floors come from the Step 2 output table.
4. **Skeptic pass before `adopted`.** For each adopt candidate, explicitly check: (a) any
   feature computed from data dated on/after the projection cutpoint? (b) any filter that
   selects on the outcome? (c) is the win concentrated in one season? Write the answer into
   the ledger entry.
5. **Standard eval commands** (run from repo root, venv active, data pulled):
   ```bash
   # metric of record (mover buckets + directional):
   python scripts/eval_movers.py --seasons 2022-23 2023-24 2024-25 2025-26 --top-n 150
   # ranking sanity check (must not regress while chasing movers):
   python scripts/backtest.py --seasons 2022-23 2023-24 2024-25 2025-26
   # unit tests:
   python -m pytest tests/ -q
   ```
6. **Doc-sync checklist — run at the end of every step:**
   - [ ] `EXPERIMENTS.md` entry appended (experiment steps only).
   - [ ] Checkbox ticked in the **Progress tracker** below.
   - [ ] The ROADMAP checkbox named in the step ticked.
   - [ ] `README.md` updated **only if** a CLI flag, script, or data pull changed.
   - [ ] New/changed public functions have a unit test in `tests/test_models.py` (synthetic
         data, no network — follow the existing `_synthetic_league` pattern).
   - [ ] Commit with the step number in the message: `Step N: <what>`.
7. **Environment:** all steps that touch data run **locally** (`stats.nba.com` and scraping
   are blocked in the remote env). Remote sessions can still do pure-code steps if a data
   snapshot is committed (see Appendix C).
8. **Noise guards on every adopt decision (the optimization discipline).**
   - **Seed protocol:** any gate involving a learned model is judged on the **mean over
     LightGBM seeds {0, 1, 2}** (three eval runs with `--seed 0/1/2`); the claimed win must
     exceed the max spread across the three runs, or it's seed luck.
   - **Bootstrap CI:** run `--ci <control> <candidate>` (paired 90% CI on the per-bucket
     bias delta, pooled across seasons). If the CI on the decisive bucket straddles 0, the
     best available verdict is **adopted-tentative** — re-affirm after the next real season.
   - The floor (Step 2) is **recomputed whenever a new default model is adopted** — it
     scales with the current model's residual spread.
9. **Code-built ≠ done.** Much of Steps 1–6 was pre-built and unit-tested in a remote
   session (2026-07; `tests/test_stage7_infra.py` pins the mechanics — arithmetic,
   no-leakage, monotonicity, determinism). The tracker's **Code** column marks that. A step
   *completes* only when its gate is evaluated on real data and the ledger entry is written.
10. **Eval-reuse guard + prospective holdout** (design-critique §3.1). All verdicts share
   the same four eval seasons — a family-wise false-positive risk across ~15 experiments.
   Therefore: (a) **before the 2026-27 season starts**, freeze the board + per-player
   predictions to a committed file (`data/processed/frozen_2026-27_preseason.parquet` +
   a dated ledger note) and score it after the season — the program's only true
   out-of-sample test; (b) hyperparameter selection is **nested** — tune on folds
   ≤ 2021-22 only, confirm once on the eval window (Step 5d); (c) adopted-item ledger
   entries carry "eval-window-conditional until 2026-27 confirms."
11. **Feature-hygiene protocol** (design-critique §5.1). Every new feature *group* ships
   with: permutation importance on the validation fold; a correlation sweep (|ρ| > 0.95
   vs an existing feature ⇒ justify or drop); and a group-level A/B (never judge single
   features — EXP-008's lesson). Prefer cluster bootstrap (`cluster="PLAYER_ID"`) for
   pooled multi-season CIs — rows repeat players and are not independent.

## Progress tracker

| Step | Phase | What | Experiment | Code | Run + logged |
|---|---|---|---|---|---|
| 0 | — | Docs alignment + data refresh | — | ☑ docs | ☑ data |
| 1 | 0 | Eval refactor + predicted-Δ calibration + bootstrap CI | — | ☑ (+actual-pool recall) | ☑ |
| 2 | 0 | Selection-floor simulation | EXP-011a | ☑ | ☑ |
| 3 | 0 | Per-bucket oracle decomposition + Phase-0 verdict | EXP-011b | ☑ | ☑ (Decision Row 1) |
| 4 | 1 | Recency de-confound (skip-last + post-trade) | EXP-012 | ☑ | ☑ (parked) |
| 5 | 1 | Objective-side changes (Δ-targets, weights, quantiles, tuning) | EXP-013a/b/c/d | ☑ | ☑ (all rejected) |
| 6 | 1 | Team-constrained minutes allocation | EXP-014 | ◐ feature layer | ☐ |
| R1 | 1.5 | Composition-covariance check (direct vs composed) | EXP-022 | ☐ | ☐ |
| R2 | 1.5 | Per-season lags + era context | EXP-023 | ☐ | ☐ |
| R3 | 1.5 | Volume/efficiency split + pace normalization | EXP-024 | ☐ | ☐ |
| 7 | 2 | Injury/availability data | EXP-015 | ☐ | ☐ |
| 8 | 2 | Dated transactions + preseason rosters | EXP-016 | ☐ | ☐ |
| 9 | 2 | ADP / market benchmark | EXP-017 | ☐ | ☐ |
| D1 | 2.5 | Decision layer: league config, VOR, schedule | — (product) | ◐ league.yaml | ☐ |
| 10 | 3 | As-of-date projection function | EXP-018 | ☐ | ☐ |
| 11 | 3 | In-season eval + lead-time metric | EXP-019 | ☐ | ☐ |
| 12 | 3 | Nightly update pipeline + status overrides | — | ☐ | ☐ |
| 13 | 3 | External in-season benchmarks (DARKO/ADP archives) | EXP-020 | ☐ | ☐ |
| 14 | 4 | Distributional board (quantile ranges, GP tails, coverage) | EXP-021 | ☐ | ☐ |
| 15 | 4 | Ship: default model switch, explorer, final doc sweep | — | ☐ | ☐ |

---

## Step 0 — Docs alignment + data refresh

**Goal:** nothing stale; a full local data cache so Steps 1–6 run without network work.

**0.1 Docs (done in the commit that adds this file — verify, don't redo):**
- `ROADMAP.md` Stage-7 sequencing points to `breakthrough-plan.md` and this file.
- `EXPERIMENTS.md` trailing "next experiments" line matches the numbering in this plan
  (EXP-011…021 as reserved in the tracker above).
- `docs/model-foundation.md` §8 ("concrete run order") carries a superseded banner pointing
  here (its EXP-006…009 run order is complete).
- `README.md` has a Documentation section listing the four docs and reading order.

**0.2 Data (local):**
```bash
pip install -e . && pip install -r requirements.txt
python scripts/pull_data.py --seasons 2009-10 2010-11 2011-12 2012-13 2013-14 2014-15 \
  2015-16 2016-17 2017-18 2018-19 2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26 \
  --datasets player_season_stats player_game_logs player_bio team_rosters
python -m pytest tests/ -q                      # all green
python scripts/eval_movers.py --seasons 2022-23 2023-24 2024-25 2025-26   # reproduces EXP-006/007 numbers
```

**Done when:** tests green; the eval reproduces the ledger's pooled bias table for
`learned` (stable −0.11, riser −3.12, big riser −6.89 ± small refit noise); optional
snapshot committed per Appendix C if remote work is planned.

---

# PHASE 0 — size the ceiling (Steps 1–3)

## Step 1 — Eval refactor + predicted-Δ calibration table

**Goal:** (a) extract the per-model pool-building logic in `run_mover_eval` so Steps 2–3
reuse it instead of copy-pasting; (b) add the first selection-free metric — bias bucketed on
**predicted** Δ.

**Build — `src/fantasy_nba/models/eval_movers.py`:**
1. Extract a helper (module-level, testable):
   ```python
   def pool_frame(proj: pd.DataFrame, prior: pd.DataFrame, actual: pd.DataFrame,
                  pool_top_n: int) -> pd.DataFrame:
       """Top-N pool joined to prior + actual, with actual_delta / proj_delta / err /
       bucket columns — the shared per-model frame behind every Stage-7 metric."""
   ```
   Body = the current lines building `m` inside `run_mover_eval` (pool → inner-join `prior`,
   `actual` → deltas → `err` → `bucket`). `run_mover_eval` calls it per model.
2. Add the calibration table: bucket the same frame by `_bucket(m["proj_delta"])`
   (same edges ±2/±6) and report per (model, predicted-bucket):
   `n, mean_proj_delta, mean_actual_delta, calib_gap = mean_actual_delta − mean_proj_delta,
   level_MAE`. Interpretation: when we *say* a player rises ~5, does he? `calib_gap` is fully
   reducible (no outcome selection) — a second headline alongside the actual-Δ buckets.
3. `run_mover_eval` returns `(per_bucket, directional, per_pred_bucket)` — plus a
   `{model: pool_frame}` dict when `return_pools=True` (feeds Steps 2–3 and the CI). Update
   `scripts/eval_movers.py` to print the third table (same pooled-weighted-mean pattern as
   `per_bucket`).
4. The rule-8 noise guard: `bootstrap_bias_delta_ci(pool_a, pool_b, on=("PLAYER_ID","season"))`
   — paired bootstrap 90% CI on the per-bucket bias delta between two models, exposed as
   `--ci MODEL_A MODEL_B` in the script.

**Tests:** synthetic 3-player frame through `pool_frame` asserting deltas/buckets; a
`per_pred_bucket` row-shape + `calib_gap` arithmetic check; CI = exactly 0 on identical
pools, excludes 0 on a shifted pool.

> **As built (2026-07, remote):** all of the above is implemented — `pool_frame`,
> `oracle_variant`, `bootstrap_bias_delta_ci`, the three-table return + `return_pools` in
> `src/fantasy_nba/models/eval_movers.py`; script flags in `scripts/eval_movers.py`; tests
> in `tests/test_stage7_infra.py`. **Remaining (local):** run on real data, confirm the
> pooled `learned` bias table still reproduces the EXP-007 ledger numbers, tick ROADMAP.

**Amendment (design review 2026-07, critique §3.2–3.3):**
- **Actual-pool recall view:** the model-pool eval is blind to sleepers the model never
  ranked top-150 (their miss is invisible, so riser bias is *understated*). Add a second
  view computing the same three tables on the **realized** top-150 (by actual total), plus
  one recall line per model: "% of the actual top-150 the model pooled." Print both views,
  always. (`run_mover_eval(pool="model"|"actual")` or a `--actual-pool` flag.)
- **Cluster bootstrap** is built: pass `cluster="PLAYER_ID"` to `bootstrap_bias_delta_ci`
  for pooled multi-season CIs (rule 11).
- **Bucket-edge sensitivity:** once per adopted model, re-run the headline table with
  edges shifted ±1 fpt/g; a verdict that flips was never real (critique §2.4).

**Done when:** eval script prints three tables **in both pool views**; old numbers
unchanged (pure refactor for tables 1–2); tests green. *(Closes ROADMAP 7.0 "predicted-Δ
calibration" — add the checkbox under 7.0 when ticking.)*

## Step 2 — EXP-011a: selection-floor simulation

**Goal:** the per-bucket signed bias a **perfect conditional-mean forecaster** would show,
because the buckets select on realized outcomes (breakthrough-plan §1c). Output = the floor
table every later gate divides by.

**Build — new `src/fantasy_nba/models/floor_sim.py`:**
```python
def selection_floor(pool: pd.DataFrame, n_draws: int = 1000, seed: int = 0,
                    sigma_scale: float = 1.0) -> pd.DataFrame:
    """Per-bucket signed bias of an oracle forecaster under outcome-conditioned bucketing.

    pool: the Step-1 ``pool_frame`` output for one (model, season).
    Method: treat debiased projections as the true conditional mean;
    resample residuals empirically; re-bucket on synthetic outcomes.
    Returns one row per bucket: floor_bias, floor_MAE, n_mean.
    """
```
Algorithm (exactly this, so it's reproducible):
1. `mu = pool.fpts_pg − pool.err.mean()` (remove the model's overall level bias so the
   synthetic truth is centred).
2. `resid = pool.act_fpts_pg − mu`; center it (`resid −= resid.mean()`).
3. For each of `n_draws`: `synth_act = mu + sigma_scale * rng.choice(resid, size=len(pool))`
   (empirical residual resampling — preserves skew/fat tails; do **not** assume normal).
4. `synth_delta = synth_act − pool.prior_fpts_pg`; bucket with `_bucket(synth_delta)`;
   per-bucket `floor_bias = mean(mu − synth_act)`, `floor_MAE = mean(|mu − synth_act|)`.
5. Average across draws.

**Build — script flag:** `scripts/eval_movers.py --floor` → after the standard tables, for
the `learned` model per season and pooled, print floors at `sigma_scale ∈ {0.75, 1.0, 1.25}`
(sensitivity band — the floor depends on residual spread, so show the range) and the derived
**reducible gap**: `measured signed_bias − floor_bias(1.0)` per bucket.

**Honest caveat to write into the ledger:** the floor assumes the current model's residual
spread ≈ irreducible noise; if a *better* model shrinks residuals, the floor shrinks with
it. That's why the sensitivity band is reported and why the floor gets **recomputed whenever
a new model is adopted** (add this to the doc-sync checklist mentally for Steps 4/6/10).

**Tests:** pure-noise synthetic pool (mu = truth + N(0,σ)) → measured bias per bucket ≈
floor per bucket (an *unbiased* forecaster's tail bias is entirely selection), tolerance
±0.6.

> **As built (2026-07, remote):** `src/fantasy_nba/models/floor_sim.py` —
> `selection_floor`, `floor_table` (sigma band), `reducible_gap`; `--floor` prints the band
> + gap for `learned`, pooled. The pure-noise identity test passes. **Remaining (local):**
> run on real data, fill the EXP-011a ledger rows.

**Ledger stub:**
```
### EXP-011a — selection floor of the mover buckets
- Status: adopted (diagnostic) · Method: floor_sim.selection_floor, resampled residuals,
  1000 draws, sigma ∈ {0.75,1.0,1.25}, learned model, 2022-23…2025-26 pooled.
- Result: floor per bucket = [numbers]; reducible gap per bucket = [numbers].
- Verdict/decision: [see Step 3 decision rule — filled in after Step 3.]
```

**Done when:** floor table produced for all 4 seasons + pooled; ledger entry (result rows
filled, verdict pending Step 3); tracker + ROADMAP 7.0 ticked.

## Step 3 — EXP-011b: per-bucket oracle decomposition + the Phase-0 verdict

**Goal:** split the *reducible* gap into minutes-driven vs rate-driven, then make the
explicit go/no-go decisions that shape Phases 1–3.

**Build — in `eval_movers.py`:**
```python
def oracle_variant(proj: pd.DataFrame, season_stats: pd.DataFrame, season: str,
                   cfg: ScoringConfig, kind: str) -> pd.DataFrame:
    """kind='minutes': rescale each COUNTING stat column by act_mpg/mpg and re-score via
    score_frame (bonuses are non-linear — never scale fpts_pg directly).
    kind='rates': replace each stat_pg with act_stat_pg × (mpg/act_mpg) and re-score.
    Returns a projection-schema frame; players with no actuals dropped."""
```
Wire into the script behind `--oracles`: adds rows `oracle_minutes(learned)` and
`oracle_rates(learned)` to all three tables. **The pool must stay the real model's top-150**
(pool on `learned`'s ranks, then swap the oracle columns) — pooling on oracle ranks would
select on the outcome.

> **As built (2026-07, remote):** `oracle_variant` + `--oracles` implemented and tested
> (identity when `act_mpg == mpg`; scaling; re-scored via `score_frame`, never scaled fpts).
> **Remaining (local):** the runs, the share arithmetic, and the Phase-0 verdict below.

**Read-out arithmetic (write it in the ledger):**
- `minutes_share = (bias_learned − bias_oracle_minutes) / (bias_learned − floor_bias)` per
  bucket (expect large in riser buckets per EXP-001; this makes it exact).
- `rate_share` analogously. They needn't sum to 1 (interaction term); report the residual.
- **Caveat on the readout (critique §2.1):** `rate × actual_MPG` assumes per-minute rates
  hold at a role the player never had (the "per-36 mirage" — bench rates fall somewhat at
  starter minutes). The minutes oracle therefore **overstates** the minutes-driven share;
  treat it as an upper bound and say so in the ledger entry.

**Decision rules (the Phase-0 verdict — record in the ledger under EXP-011):**
| Finding | Consequence |
|---|---|
| reducible gap (big riser) < 2 fpts/g | Preseason bias-chasing is near-done: run Steps 4–5 as cheap A/Bs, **skip any further preseason feature hunting**, pull Step 10 (in-season engine) forward immediately after Step 6. |
| reducible gap ≥ 2 and minutes_share ≥ 60% | Phase 1 proceeds with **Step 6 (allocation) as the headline bet**; Step 5 stays a quick pass. |
| reducible gap ≥ 2 and minutes_share < 60% | Rates matter more than assumed: add a rate-focused variant to Step 5 (per-stat sample weights), and reconsider 7.F (usage-coupled rates) after Step 6. |

**Done when:** oracle rows print; EXP-011 ledger entry completed with the verdict row filled
and one of the three decision rows circled; ROADMAP 7.0 gets a `[x] ceiling diagnostics
(EXP-011)` line.

---

# PHASE 1 — untried levers on data we hold (Steps 4–6)

## Step 4 — EXP-012: de-confound within-season recency

**Goal:** keep EXP-008b's aggregate win (level MAE better 3/4 seasons, sign-acc 4/4) while
removing the season-end rest/tanking contamination that biased it downward and worsened the
riser buckets.

**Build — `src/fantasy_nba/models/recency.py`:**
1. `season_recency_table(game_logs, window=20, skip_last=0)` — per (player, season), drop
   the final `skip_last` **played** games before taking the `window`-game tail. Season
   aggregates (`s_min/s_g/s_pts`) unchanged; only the window moves. Cache key: the table is
   computed per (window, skip_last) combination — compute once per setting in the eval run.
2. Post-trade split — new function in the same module:
   ```python
   TRADE_FEATURES = ["traded_flag", "post_trade_games", "post_trade_mpg_delta"]

   def trade_split_table(game_logs: pd.DataFrame) -> pd.DataFrame:
       """Per (player, season): did TEAM_ABBREVIATION change; games with the final team;
       post-trade MPG − pre-trade MPG (0.0 when no trade or <5 post-trade games)."""
   ```
   `recency_features` gains `trade_table=None` param; when given, joins the three features
   for each player's most recent prior season (same `< target` self-restriction — reuse the
   existing leakage unit-test pattern).
3. Requires `TEAM_ABBREVIATION` in the game-log columns the eval loads — it is in the raw
   `leaguegamelog` pull; verify it survived `storage.read("player_game_logs")` and add it to
   the recency module docstring's required-columns list.

**Run — the A/B matrix. As built, variants are selected by registry name
(`backtest.VARIANT_SPECS` → `--variants` on the eval script); one run covers the matrix:**

```bash
python scripts/eval_movers.py --seasons 2022-23 2023-24 2024-25 2025-26 \
  --variants learned_recency learned_recency_s5 learned_recency_s10 \
  --ci learned_recency learned_recency_s5 --seed 0   # repeat --seed 1, 2 (rule 8)
# then, with the winning skip: learned_recency_trade / learned_recency_s5_trade
```

| Variant (registry name) | Setting |
|---|---|
| learned | control |
| learned_recency | window 20, skip 0 (EXP-008b baseline) |
| learned_recency_s5 | window 20, skip 5 |
| learned_recency_s10 | window 20, skip 10 (≡ a "mid window ending 10 early" — do not test twice) |
| learned_recency_trade | skip 0 + TRADE_FEATURES |
| learned_recency_s5_trade | skip 5 + TRADE_FEATURES |

> **As built (2026-07, remote):** `season_recency_table(skip_last=…)`,
> `trade_split_table` (+`TRADE_FEATURES`, `MIN_POST_TRADE_GAMES=5` noise guard),
> `recency_features(trade_table=…)`, the `project_learned` kwargs, and all six registry
> variants — tested incl. the no-leakage same-season case and the rest-tail trim
> arithmetic. **Remaining (local):** the runs and the verdict.

**Gate (adopt):** vs `learned_recency`: pooled riser + big-riser signed bias improve by
≥ 25% of their reducible gap **and** the aggregate win vs `learned` is retained (level MAE
better in ≥ 3/4 seasons). If adopted → wire the winning setting into
`backtest.project_models` as the **default `learned`** (recency becomes non-optional), keep
plain-learned available as `learned_plain` for A/Bs, update `scripts/project.py --model
learned` to pass game logs, and **recompute the Step-2 floor for the new default**.
If it clears the aggregate bar but not the riser bar again → `parked`, keep opt-in, move on
(don't iterate further — Step 10 revisits recency at true game-log granularity anyway).

**Ledger stub:** EXP-012 with the variant table, both bars, floor-adjusted riser numbers,
skeptic answers (leakage: none — all windows within prior seasons; selection: pool unchanged).

**Done when:** matrix run, ledger logged, adopt-path wiring (if any) + floor recompute done,
ROADMAP 7.D refinement checkbox ticked.

## Step 5 — EXP-013: objective-side changes (three cheap sub-experiments)

**Goal:** every prior experiment changed features under the same squared-error level
objective. Change the objective. Run a → b → c; each is independent; (c) is required
infrastructure for Step 14 even if (a)/(b) reject.

**Build — `src/fantasy_nba/models/learned.py`:**

**(a) Δ-targets.** `project_learned(..., target_mode="level"|"delta")`:
- In `build_panel`, add delta labels: `y_mpg_delta = y_mpg − proj_mpg`,
  `y_rate_delta_<s> = y_rate_<s> − rate_<s>` (label minus the model's own Marcel-aggregate
  feature; both already in the panel row). `y_gp` stays level (no meaningful anchor).
- In `_fit_models`/prediction: when `delta`, train on delta labels, predict, add the anchor
  back, then apply the existing clips.
- Hypothesis (honest): trees regularize toward the *target mean*; for levels that mean is
  the pool-average player (pulls stars down / scrubs up — plausibly EXP-007's +bias);
  for deltas it is "league-average change". Different geometry, unknown sign — that's why
  it's an A/B and not an assumption.

**(b) Sample weights.** `project_learned(..., weight_mode=None|"mover"|"relevance",
weight_alpha=…)`:
- `"mover"`: per target, `w = 1 + alpha × |y − anchor| / scale` with `alpha ∈ {0.5, 1.0}`,
  `scale` = the target's panel-wide MAD (so alpha is unitless); anchor as in (a) —
  `WEIGHT_ANCHORS` includes `y_gp → weighted_gp` for weighting even though gp is excluded
  from delta mode. Weights computed from **labels**, which is legitimate at train time
  (never at eval).
- `"relevance"`: `w = clip(avg_season_min / 2000, 0.25, 2.0)` where `avg_season_min` is the
  recency-weighted average season minutes already in the panel (`wMIN / w`) — draftable
  players count more; bench noise counts less.

**(c) Quantile heads (infrastructure + experiment).** New
`src/fantasy_nba/models/quantiles.py`:
```python
QUANTILES = (0.25, 0.50, 0.75, 0.90)

def fit_fpts_quantiles(panel, feature_cols, cfg, params) -> dict[float, LGBMRegressor]:
    """Direct per-game-fpts quantile models: label y_fpts_pg = score_frame(composed y_rate_*
    × y_mpg stat line, cfg). objective='quantile', alpha=q; other params shared."""

def predict_quantiles(models, X) -> pd.DataFrame:  # fpts_pg_q25/q50/q75/q90, sorted per row
```
Direct-on-fpts (not per-target) because quantiles don't compose across rate × minutes.
Point estimates remain decompositional; this frame is used **only** for ranges (Step 14).

**(d) Hyperparameter tuning (the never-done pass).** `DEFAULT_LGBM_PARAMS` were set once in
EXP-007 and never tuned — cheap potential accuracy left on the table. Build a small
walk-forward tuner (new `scripts/tune_learned.py`): grid over
`num_leaves ∈ {15, 31, 63}`, `min_child_samples ∈ {10, 30, 60}`,
`learning_rate ∈ {0.03, 0.05, 0.10}`, with `n_estimators` chosen by early stopping
(validation fold = the **last training season** of each backtest fold — never the eval
season). **Nested selection (rule 10b, critique §3.1): the grid is scored only on folds
targeting seasons ≤ 2021-22; the winning combo is then confirmed *once* on the standard
4-season eval** — never grid-search directly on the verdict seasons, or every later
"win" is partly in-sample. Optional extras if the grid winner is unstable:
`reg_lambda ∈ {0.5, 1, 5}`, monotone constraint on `proj_mpg → y_mpg`. Tune **once, after
(a)/(b) settle** — tuning before the objective is chosen wastes the grid.

**Run:**
- (a)/(b): one eval invocation covers the matrix —
  `--variants learned_delta learned_w_mover learned_w_mover_a05 learned_w_rel`, with
  `--ci learned <candidate>` on the front-runner and seeds {0,1,2} (rule 8).
- (c): per season, **pinball loss** at each q vs two baselines (constant-spread normal
  around `learned`'s point estimate with σ = pooled residual std — the SD_PG analogue — and
  the empirical pool quantiles), plus **coverage**: fraction of pool actuals ≤ each
  predicted quantile, target within ±5pp of nominal, overall and per actual-Δ bucket.
- (d): `python scripts/tune_learned.py` → winning params; re-run the standard eval with
  them; only then update `DEFAULT_LGBM_PARAMS`.

**Gates:** (a)/(b) adopt if pooled riser+big-riser floor-adjusted bias improves ≥ 25% with
stable bucket bias within ±0.5 of control and ranking Spearman within noise. (c) adopt (as
Step-14 input) if it beats the constant-σ baseline on pinball loss overall **and** in the
riser bucket. (d) adopt if pooled level MAE improves with riser bias not worse — judged
under rule 8 like everything else. Combinations: if both (a) and (b) pass individually, run
the combination once; adopt the best single-or-combo by riser bias.

**Ledger stub:** one EXP-013 entry with a/b/c/d sub-results (mirrors EXP-008's style).

> **As built (2026-07, remote):** (a)/(b) — `target_mode` / `weight_mode` / `weight_alpha`
> in `learned.py` (`DELTA_ANCHORS`/`WEIGHT_ANCHORS`, `_sample_weight`, `_predict_target`),
> registry variants `learned_delta`, `learned_w_mover`, `learned_w_mover_a05`,
> `learned_w_rel`; (c) — `src/fantasy_nba/models/quantiles.py` complete
> (`fit_fpts_quantiles`, `predict_quantiles` with monotone enforcement, `pinball_loss`,
> `project_fpts_quantiles` wrapper). All tested. **As completed (2026-07-08, local):** runs
> done — all four sub-experiments rejected (EXP-013); (c)'s glue is
> `scripts/eval_quantiles.py`, (d)'s tuner is `scripts/tune_learned.py` (nested; refuses
> tuning folds > 2021-22). Defaults stand; `learned_tuned` registered documented-rejected.

**Done when:** all four sub-A/Bs logged; any adopted mode/params become the default in
`project_models` (+ floor recompute).

## Step 6 — EXP-014: team-constrained minutes allocation (the structural bet)

**Goal:** replace the per-player `y_mpg` regression with a model of **share of team
minutes**, normalized within the target roster — the first model in the repo that knows
minutes are a 240-per-game constrained resource and *who* competes for them.

**6.1 Data prerequisite — historical rosters (positions).**
`fetch_team_rosters` currently pulls the latest season only. Extend `pull_seasons` to loop
seasons for `team_rosters` (the endpoint accepts historical seasons; keep the same output
schema — `SEASON, TeamID, PLAYER_ID, POSITION, …`). Re-pull 2009-10…2025-26 locally.
Positions normalize to two groups for depth-chart purposes:
`GUARD = {G, G-F}`, `BIG = {F, F-C, C, C-F, F-G}` (map exact `POSITION` strings; log any
unmapped string loudly). Coarse on purpose — finer buckets (PG/SG/…) are sparse and rosters
list hybrid positions inconsistently.

**6.2 Build — new `src/fantasy_nba/models/allocation.py`:**

*Target:* `y_min_share = player season MIN / team season total MIN` (his primary team,
`context._primary_team_minutes` convention). Season-length-robust by construction.

*Features (per player × target season; all computed from prior-season minutes + the
target-season roster map — the same no-leakage contract as `context.py`):*
```python
ALLOC_FEATURES = [
    "own_prev_share",        # own share of prior team's minutes (have: context.py)
    "prev_mpg", "prev_gp", "target_age",            # from the existing aggregates
    "pos_group",             # 0=guard 1=big (categorical)
    "same_pos_returning_share",  # Σ prior shares of returning teammates in his pos_group
    "same_pos_vacated_share",    # Σ prior shares of departed teammates in his pos_group
    "depth_rank",            # rank of own_prev_share among target-roster same-pos players
    "n_same_pos",            # roster crowding in his position group
    "team_vacated_min_norm", "team_turnover_share",  # the EXP-009 team-level pair, kept
    "pf_per_min",            # foul rate (critique §5.3): a stable, mechanical minutes cap —
                             # foul-prone players cannot hold heavy minutes. PF is in the
                             # Base pull; lag it like the other rates.
]
```
*Amendments (design review 2026-07):* (a) consider training the share model on
`logit(share)` (bounded target; back-transform + clip) — try raw first, logit if raw
mis-calibrates; (b) **`rookie_reserve` must be computed on the training slice only** in
backtest folds (critique §2.8) — the helper takes whatever frame it's handed, so the
caller owns this.
*Normalization (the constraint):* per target team,
`share_norm_i = share_pred_i × (1 − rookie_reserve) / Σ_j share_pred_j` over modeled players
`j` on the roster, where `rookie_reserve` = league-average share of team minutes taken by
players with **no prior-season row** (rookies/returnees we can't model), measured on the
training seasons (one scalar; expect ~0.08–0.12; compute, don't guess). Convert:
`pred_min_total = share_norm × mean_team_total_min(training seasons)`;
`mpg = pred_min_total / pred_gp` with `pred_gp` from the existing `y_gp` model; clip MPG to
[0, 42].

*Wiring:* `project_learned(..., minutes_mode="regression"|"allocation")` — allocation mode
swaps only the minutes layer; rates/GP untouched. Backtest team map = `context.target_team_map`
(until Step 8 replaces it with true preseason rosters); live team map = `team_rosters`.

**6.3 Run:**
- Eval matrix: `learned` (current best default after Steps 4–5) vs `learned_alloc`.
- Report **three segments** in addition to the standard tables (aggregate hides this —
  ledger note of EXP-009): (i) players whose target team's `team_turnover_share` > pooled
  median; (ii) players who changed teams; (iii) everyone else. Per segment: minutes MAE,
  level MAE, signed bias.
- Sanity print: distribution of per-team Σ share_pred *before* normalization (how far from
  1 − rookie_reserve? a mean far from it means the raw model is mis-calibrated — investigate
  before trusting the A/B).

**Gate (adopt):** pooled minutes MAE ≤ control **and** floor-adjusted riser+big-riser bias
improves ≥ 25%, **or** segment (i)+(ii) level MAE improves ≥ 15% with segment (iii) flat
(≤ 3% worse). On adopt: `minutes_mode="allocation"` becomes the default, floor recompute,
`scripts/project.py` passes rosters. On reject: park with the measured numbers — but the
roster/position data and depth features stay (Step 10 reuses them as in-season features).

**Ledger stub:** EXP-014, with the segment table and the Σ-share sanity distribution.

> **As built (2026-07, remote):** the **feature layer** —
> `src/fantasy_nba/models/allocation.py` (`ALLOC_FEATURES`, `position_group` with loud
> unmapped-string failure, `allocation_features` depth-chart math, `rookie_reserve`,
> `normalize_shares`) — implemented and tested (synthetic 2-team league: departed same-pos
> teammate's vacated share, depth ranks, normalization to 1 − reserve). **Remaining
> (local):** 6.1 historical-rosters pull, the `y_min_share` LightGBM model, the
> `minutes_mode="allocation"` wiring in `project_learned`, and the A/B. One known
> limitation to carry into the run: a departed player's position comes from his *new*
> roster — players who left the league entirely drop out of the vacated-share sums until
> the historical-roster pull supplies prior-season positions.

**Done when:** logged adopt/park/reject; ROADMAP 7.A refinement checkbox ticked; tests
(synthetic 2-team league: departed star → his same-pos teammate's `same_pos_vacated_share`
correct; normalization sums to 1 − reserve per team).

---

# PHASE 1.5 — decomposition refinements (Steps R1–R3, from the design review)

*Source: `docs/design-critique.md` §§2, 4, 5. All three run on data already held. Ordered
cheapest-first; R1's answer partially reprioritizes R2/R3 (a large covariance term says
"fix the composition before adding features").*

## Step R1 — EXP-022: composition-covariance check (direct vs composed)

**The hypothesis (critique §4.1):** `E[rate×MPG] = E[rate]·E[MPG] + cov(rate, MPG)`, and
the residual covariance is *positive* (one latent role shock lifts minutes and rates
together) — so composing the two conditional means **structurally under-projects risers**.
Part of the stubborn riser bias may be arithmetic, not missing features.

**Build (small):**
1. A **direct per-game-fpts L2 model** — reuse the quantile plumbing
   (`quantiles.panel_fpts_label` as the target, `BASE_FEATURES`, default params; ~20 lines,
   registry name `learned_direct`).
2. A panel diagnostic: per season, compute `cov(resid_mpg, resid_fpts_rate)` where the
   residuals come from the fitted y_mpg model and a per-game-fpts-per-minute rate model;
   report by actual-Δ bucket.

**Run:** standard eval, `learned` vs `learned_direct`; the covariance table.

**Read-out / gate:** if `learned_direct` beats `learned` on riser/big-riser signed bias by
≥ 25% of the reducible gap (rule-8 guarded) **or** the bucketed covariance is large and
positive → adopt a correction: either (a) additive covariance term
`stat_pg += cov_hat(features)` (a small model on the residual product), or (b) a
blend `α·direct + (1−α)·composed` tuned on training folds. If neither shows → the
composition is fine; log and move on (that's a real result too — it kills §4.1 as an
explanation).

**Ledger stub:** EXP-022 with the covariance-by-bucket table and the A/B.

## Step R2 — EXP-023: per-season lags + era context

**The hypothesis (critique §2.5 + §2.2):** the GBM can't learn recency weighting it never
sees (only the pre-blended 5/4/3 aggregate is fed), and has no era awareness across a
2009→2026 panel. Lags + era context let the trees learn age- and era-conditional weighting.
EXP-008's failed *slopes* are not evidence against lags — a slope is a lossy transform; raw
lags let the model choose.

**Build — feature group `LAG_FEATURES` in `learned.py` (gated `use_lags=True`, registry
`learned_lags`):**
- Per season t−1, t−2, t−3: `mpg_lag{k}`, `gp_lag{k}`, `usg_lag{k}`, `ts_lag{k}`,
  `fpts_pm_lag{k}` (fantasy points per minute under the scoring config — one compact
  production summary instead of 13 rate lags), plus `min_lag{k}` (sample size for that
  lag). Missing lags → NaN (LightGBM handles natively; do *not* zero-fill — 0 is a real
  MPG). 18 columns.
- Era context: `season_year` (integer), `league_mean_fpts_pm` and `league_pace_proxy`
  (league-average of the season's per-minute fpts and possessions-proxy) computed **per
  training season** from that season's stats — all as-of-known facts.
- **Era-relative targets (second half of the experiment, separate flag
  `era_relative=True`):** train rate targets as `rate / league_mean_rate(season)`;
  multiply back by the *most recent training season's* league mean at inference (the
  honest preseason estimate of the target season's context).

**Run:** `learned` vs `learned_lags` vs `learned_lags`+`era_relative`, rule-8 guarded,
rule-11 hygiene (permutation importances; expect `*_lag1` to dominate and aggregates to
cede importance — that's the point, not a bug).

**Gate:** standard — ≥ 25% reducible riser-gap closure, stable within ±0.5, ranking
Spearman within noise. Special attention to the **age ≤ 24 cohort** (segment it): lags ×
age interactions are where "young player still improving" lives (ROADMAP 7.B's targeted
fix, done properly).

**Ledger stub:** EXP-023; log the importance shift aggregates→lags.

## Step R3 — EXP-024: volume/efficiency split + pace normalization

**The hypothesis (critique §4.1–4.2):** 13 independent raw-rate targets confound sticky
volume with noisy efficiency, allow internally inconsistent lines (REB ≠ OREB+DREB, PTS
free-floating), and bake team pace into "skill." Re-target the rate layer.

**Build — `rate_mode="split"` in `learned.py`:**
- **Volume targets (per minute, later per 100 poss):** `fga2`, `fga3`, `fta`, `oreb`,
  `dreb`, `ast`, `stl`, `blk`, `tov`.
- **Efficiency targets (ratios, heavier shrinkage — their own `reg_minutes`-style priors):**
  `fg2_pct`, `fg3_pct`, `ft_pct`.
- **Identities at composition (never modeled):** `fgm = fg2_pct·fga2 + fg3_pct·fga3`;
  `fg3m = fg3_pct·fga3`; `ftm = ft_pct·fta`; `fga = fga2 + fga3`; `reb = oreb + dreb`;
  `pts = 2·fg2_pct·fga2 + 3·fg3_pct·fga3 + ft_pct·fta`. Lines are consistent by
  construction; 13 targets → 12 with the right noise structure.
- **Pace normalization:** verify `PACE` survives in the cached `player_season_stats`
  (Advanced merge); if absent, one `leaguedashteamstats` pull per season supplies team
  pace. Normalize volume features/targets per-100-possessions; compose back with the
  **target team's prior-season pace** (preseason-known; a real feature for team-switchers).

**Run:** `learned` vs `learned_split` vs `learned_split+pace`; rule-8 guarded. Also check
internal-consistency violations of the *current* model (how often FGM > FGA etc.) as the
motivating stat for the ledger.

**Gate:** standard mover gate, **plus** it must not lose on aggregate level MAE (a
refactor that's mover-neutral but consistency-fixing is still adoptable if MAE ties —
consistency is a correctness property; say so in the verdict).

**Ledger stub:** EXP-024.

---

# PHASE 2 — new exogenous data (Steps 7–9)

*Order note: Steps 7–8 share one scraper. Build it once in Step 7.*

## Step 7 — EXP-015: injury / availability history

**7.1 Build — `scripts/pull_injuries.py`:** scrape prosportstransactions.com
(Basketball → "Missed games due to injury/illness" + "Movement to/from injured/inactive
list" categories), paginated HTML tables → `data/raw/injuries.parquet` with columns
`date, team, acquired, relinquished, notes` (verbatim strings, ISO dates). Politeness:
one page/sec, retry×3 (reuse the `_with_retry` pattern from `ingest.py`). Pull 2009→today
once; afterwards incremental by date. Name-join via the existing normalizer
(`darko.normalize_name`) — report unmatched-% like `darko.join_board` does; require ≥ 95%
on players in our season stats, else extend the alias map before proceeding.

**Name-join hardening (applies to Steps 7, 8, 9 — critique §2.7):** names are not
identities — the league has real collisions (Jalen Williams and Jaylin Williams shared the
OKC roster). Every external join must: (a) join on **name + team** whenever the source has
a team column; (b) **hard-fail on duplicate normalized keys within a source** rather than
silently keeping one row; (c) keep the alias map append-only and dated.

**7.2 Build — `src/fantasy_nba/models/injuries.py`:**
```python
INJURY_FEATURES = [
    "inj_events_1y", "inj_events_3y",      # distinct injury spells (relinquish→acquire pairs)
    "inj_days_1y", "inj_days_3y",          # summed spell durations, days
    "inj_recency_days",                    # days since last spell ended (cap 1500)
    "inj_chronic_flag",                    # ≥3 spells in trailing 2y
    "inj_bodypart_severe",                 # notes regex: achilles|acl|mcl|meniscus|back surgery|stress fracture
]

def injury_features(injuries: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """Per PLAYER_ID from spells strictly before ``as_of`` (ISO date). Preseason use passes
    Oct 1 of the target season."""
```
Spell construction: pair each `relinquished` row with the player's next `acquired` row
(cap spell length at 120 days when unclosed — season-ending). Unit-test the pairing on a
synthetic 3-transaction sequence.

**7.3 Run — two separate judgments:**
- **(a) GP point estimate:** add `INJURY_FEATURES` to the `y_gp` model only. Metric:
  next-season GP MAE + Spearman on the draftable pool, 4 seasons pooled, vs current `y_gp`.
  Gate: Spearman +0.05 absolute (EXP-004 baseline: prior-GP→GP 0.21, fit R²≈0.03 — this is
  the first data with a right to beat it).
- **(b) Per-player Monte-Carlo tail:** `build_gp_pool(..., injury_profile=...)` — bucket
  the empirical pool by (age bucket × chronic flag) instead of age alone; guard buckets
  < 30 rows by falling back to age-only (same pattern as `_age_bucket` guard). Gate:
  top-100 backtest p10–p90 coverage stays in [78%, 88%] **and** `safe`-ranking Spearman
  improves or ties while Giannis-class (chronic) players' p10 drops vs durable peers —
  check 3 named cases in the ledger.

**Done when:** both judged + logged (they can split adopt/reject); ROADMAP 7.C ticked
accordingly; injury pull documented in README data section.

## Step 8 — EXP-016: dated transactions → true preseason rosters

**8.1 Build:** same scraper, "player movement" category → `data/raw/transactions.parquet`
(`date, team_from, team_to, player, type`). New `src/fantasy_nba/models/rosters.py`:
```python
def preseason_roster_map(season_stats, transactions, target_season,
                         as_of_month_day="10-01") -> pd.DataFrame:
    """[PLAYER_ID, team]: prior-season primary team + transactions dated ≤ Oct 1 of the
    target season. The honest replacement for context.target_team_map in backtests."""
```
**8.2 Validate before using:** against each backtest season, compare to the team each
player actually logged his first ≥ 3 games for (from game logs). Report agreement; require
≥ 90% on the draftable pool. Investigate the misses (mid-Oct trades are legitimate misses;
name-join failures are not).

**8.3 Run:** re-run the two consumers with the honest map — the Step-6 allocation A/B and
(if it was parked, one re-check) the EXP-009 context features. Expect the measured value to
**drop** for mid-season movers (the flattery EXP-009's ledger note predicted); what remains
is deployable preseason signal.

**Gate:** keep the honest map unconditionally for all *backtests* (correctness fix, not a
performance question). The feature adoption decisions from Step 6 get re-affirmed or
reversed on the honest numbers — update their ledger entries with a dated addendum.

**Done when:** validation ≥ 90%, consumers re-run, EXP-016 logged, ROADMAP 7.A data
checkbox ticked.

## Step 9 — EXP-017: ADP / market

**Build — `scripts/pull_adp.py`:** one consensus ADP source (FantasyPros points-league ADP
preferred; HashtagBasketball fallback), date-stamped like the DARKO pull
(`data/raw/adp/adp_<date>.parquet`), name-joined with match-rate report. New
`scripts/adp_report.py` (mirror `darko_report.py`): board-vs-ADP top-20 disagreements each
way (our rank − ADP rank), flagged with the risk column so "we're low on X" reads with
context.

**Run/Gate:** benchmark-only at first — **no feature use** until ≥ 2 seasons of dated ADP
archives exist (same waiver as DARKO/EXP-010; log that condition in the ledger). The
deliverable is the disagreement report wired into the draft-day workflow and the archives
accumulating.

**Done when:** pull + report run end-to-end; EXP-017 logged (`adopted (benchmark-only)`);
ROADMAP 7.E ADP checkbox ticked.

---

# PHASE 2.5 — the decision layer (Step D1, from the specialist review)

*Source: `docs/design-critique.md` §9. Accuracy work optimizes the projection; leagues are
won by decisions. This step turns boards into decisions-ready values. It is a **product
step, not an experiment** — no mover gate; each piece ships with a sanity report instead.
Calendar-critical: everything here must exist **before draft day**.*

## Step D1 — league config, replacement value, schedule

**D1.1 League config — `config/league.yaml`** (skeleton committed; fill with the real
league's settings): teams, roster slots, lineup frequency (daily/weekly), format
(h2h/season points), games cap, fantasy-playoff weeks, waiver system + FAAB budget,
keeper flag. Scoring stays in `config/scoring.yaml` — **verify it matches the real league
before draft day** (critique §2.4: every verdict is scoring-conditional).

**D1.2 Replacement value — new `src/fantasy_nba/models/value.py`:**
```python
def replacement_level(board, league) -> dict[str, float]:
    """Per roster-slot replacement fpts/g: the level of the best player left after every
    team fills that slot (greedy fill by board order, league.teams × slots)."""

def add_vor(board, league) -> pd.DataFrame:   # adds `vor` and `vor_rank` columns
```
Position source: roster POSITION → the allocation position groups (guard/big) at minimum;
platform eligibility is parked (§9.7). **Sanity report (no gate):** print top-100 by raw
total vs by VOR — count rank moves ≥ 10; eyeball that centers/guards move the expected
direction. If VOR barely reorders a points league, *log that honestly* and keep the column
informational.

**D1.3 Schedule ingestion — `scripts/pull_schedule.py`:** one static pull per season
(nba_api schedule endpoint or data.nba.com JSON) → `data/raw/schedule.parquet`
(`game_date, home, away`). Derived per team: games per NBA week, back-to-back counts,
**fantasy-playoff-weeks game counts** (weeks from `league.yaml`). Feeds: D1.4, Step 10's
schedule-aware ROS, Step 11's streaming values.

**D1.3b The league horizon (user decision 2026-07):** the league ends
`league_end_offset_weeks` (~2–3, TBD) before the NBA regular-season finale. Derive
`league_end_date` from the schedule + offset, and thread it everywhere a horizon appears:
**ROS projections/totals cut at `league_end_date`, never the NBA finale** (a star's
remaining value excludes weeks the league doesn't play); fantasy playoff weeks =
the last league weeks, derived, replacing the yaml placeholder. Payoff: the worst
rest/tank regime falls out of the *decision* horizon by design — it remains a
*training-label* issue only (EXP-012's territory), since historical seasons still
contain those weeks.

**D1.4 Board columns:** `playoff_wk_games` (games in the league's playoff weeks),
`playoff_weeks_risk` flag (aging star × likely-bad team — team prior from optional manual
`config/team_priors.yaml`, e.g. Vegas win totals entered once preseason), and the
ADP-availability column on the draft sheet ("likely gone by pick N" via ADP ± σ from the
Step-9 pull).

**Done when:** league.yaml filled; `add_vor` + schedule pull run end-to-end; draft sheet
prints rank / VOR / ADP-availability / playoff-week columns; sanity reports eyeballed and
noted in the ledger as a dated D1 note (no EXP number — product, not hypothesis).

---

# PHASE 3 — the in-season as-of-date engine (Steps 10–13)

## Step 10 — EXP-018: `project_asof` — the as-of-date foundation

**Goal:** the model `docs/model-foundation.md` §4 specifies: one function usable at any
date, trained on in-season cutpoint snapshots so shrinkage ("6 hot games → move how far?")
is learned, not hand-set. This is the largest step; it is deliberately sequenced after the
preseason work so every adopted feature group carries over.

**10.1 Build — new `src/fantasy_nba/models/asof.py`:**

*Interface:*
```python
def project_asof(T: str, season_stats, game_logs, bio, cfg=None, rosters=None,
                 injuries=None, params=None) -> pd.DataFrame:
    """ROS per-game projection as of ISO date T. Uses season_stats for seasons fully
    ended before T's season; game_logs strictly ≤ T; rosters/injuries as-of T.
    Output schema = project_learned's + [games_so_far, ros_gp_max]."""
```
*Cutpoint grid (training and eval share it):* per historical season, `T ∈ {season_start − 7d
(≡ preseason), +30d, +60d, +90d, +120d, +150d}` where `season_start = min(GAME_DATE)` of
that season. 16 usable seasons × 6 cutpoints × ~500 players ≈ **45k panel rows** (~9× the
season-only panel — the small-data constraint materially relaxes).

*Feature groups (concatenation of everything adopted so far + the in-season block):*
- All preseason features as of the season (Marcel aggregates from prior seasons, adopted
  Step 4/5/6/7 groups).
- **Season-to-date (STD) block, from `game_logs ≤ T`:** `std_gp, std_mpg, std_rate_<s>`
  (13), `last10_mpg, last10_mpg_delta` (vs STD), `last10_ppm_delta`, `days_since_last_game`,
  `post_trade_games` (within current season), `games_so_far` — the shrinkage handle the
  model interacts everything with. Preseason cutpoint rows get STD = 0/NaN-filled-neutral
  and `games_so_far = 0`, so **one model serves T₀ and every later date**.
- **Amendments (design review 2026-07, critique §5.2/5.4/5.5):**
  - **Per-stat EWMAs with fitted half-lives** replace/augment the hard last-10 window:
    steals stabilize in a handful of games, 3P% barely stabilizes in a season — one window
    for all stats is wrong. Fit half-lives per stat on the cutpoint panel (grid
    {5, 10, 20, 40 games}).
  - **Live teammate-vacated minutes:** minutes/usage of currently-OUT teammates (injury
    feed), same-position-weighted — the single biggest waiver signal.
  - **Return-from-absence ramp:** games since return from a ≥5-game absence + a
    minutes-restriction flag (recent MPG ≪ pre-absence MPG) — so rust isn't read as
    decline.
  - **Blowout handling:** pull **team game logs** (`LeagueGameLog`, team mode — margins
    aren't derivable from player logs; add to the Step-0 data list) → per-game margin;
    (a) team blowout-share as a context feature, (b) option to exclude |margin| ≥ 25 games
    from recency/EWMA windows.
  - **Schedule-aware ROS:** remaining totals use the player's team's **actual remaining
    schedule count** as of T (never `82 − games_so_far`), plus back-to-back density —
    from the Step D1 schedule pull.
  - **Late-season rest/tank risk (critique §9.4):** in-season, team proximity to
    elimination / seed-lock is a rest-risk feature for veterans in the fantasy-playoff
    weeks; preseason it's only a flag (D1.4).
- *Labels:* ROS realized from `game_logs > T` of the same season: `y_ros_mpg`,
  `y_ros_rate_<s>`, `y_ros_gp`; rows require ≥ 5 ROS games to be labeled (tail cutpoints
  with < 5 remaining drop out).

*Training:* one LGBM per target over the pooled cutpoint panel (fit once per backtest fold:
train seasons strictly before the eval season — **within-season rows of the eval season are
never in train**, even at earlier cutpoints; that's the walk-forward discipline
`model-foundation.md` §4 requires).

**10.2 Consistency check (before any metric):** at the preseason cutpoint, `project_asof`
vs `project_learned` on the same fold must agree closely (Spearman ≥ 0.98 on top-150,
level MAE gap ≤ 0.3) — same features, bigger panel; a large gap means a leak or a feature
mismatch. Debug until it holds.

**Gate (EXP-018):** at cutpoints +30/+60/+90: ROS level MAE on the top-150 pool beats both
(a) `project_learned` frozen at T₀ and (b) the naive updater
(`STD per-game line, shrunk: (games_so_far × std + 20 × T₀_proj) / (games_so_far + 20)`).
Beating (a) is table stakes; beating (b) is the evidence the *learned* shrinkage earns its
complexity. Adopt on 3/4 seasons at ≥ 2 of 3 cutpoints.

**Done when:** consistency check passes; gate evaluated + logged; ROADMAP 7.0 in-season
checkbox flips from parked to done-pending-Step-11.

## Step 11 — EXP-019: the in-season mover eval + lead-time metric

**Build — extend `eval_movers.py` / new `scripts/eval_asof.py`:**
1. **In-season mover eval:** at each cutpoint, pool = top-150 by projected ROS total;
   `actual_delta_ros = act_ros_pg − prior_full_season_pg`; same buckets/edges; same three
   tables + floor (Step-2 floor recomputed on ROS residuals — spreads shrink as
   games_so_far grows, so floors are per-cutpoint).
2. **Early-riser recall (the waiver question):** define realized in-season risers as
   players with `act_ros_pg ≥ prior_full_season_pg + 6` at the +30d cutpoint (the "big
   riser" edge, ROS form). Report: of these, the fraction inside our top-150 ROS board at
   +30d, and their mean projected Δ vs realized Δ.
3. **Lead-time:** for each player-season where trailing-10-game MPG rises ≥ +6 over his
   season baseline and *stays* ≥ +6 for ≥ 15 further games (a confirmed role change; compute
   from game logs), find the first date our daily ROS MPG projection moves ≥ 50% of the
   eventual realized change. `lead_time_days = confirm_date − first_move_date` (positive =
   early). Baseline comparator: the naive last-10 updater from Step 10's gate. Report the
   distribution (median, IQR) per season.

**Gate:** this step *defines* the metrics and baselines them — adopted as diagnostics
(like EXP-006). The standing target for later tuning: median lead time ≥ naive baseline,
early-riser recall reported every run.

**Amendment (specialist review, critique §9.6):** the daily output must include a
**short-horizon board** next to ROS — next-7/14-day schedule-weighted totals (per-game
line × that team's games in the window, from the D1 schedule) — this, not ROS, is the
streaming/last-roster-spot decision number. Plus value-vs-droppable context: ROS Δ against
the current roster's worst player (roster read from `league.yaml` manually or entered ad
hoc).

**Amendment (league horizon, D1.3b):** since the league ends before the NBA season,
(a) deployed ROS numbers cut at `league_end_date`; (b) optionally add a **league-horizon
eval view** — score cutpoint projections against actuals *through the league end date
analogue* (e.g. "through NBA week 22") rather than full-season actuals. Run it once as a
sensitivity: if verdicts don't move, keep full-season actuals for comparability with the
existing ledger and note that; if they do move (plausible — truncation drops the
rest-noise weeks from the *labels* too), report both views going forward.

**Done when:** all three metrics print from one command
(`python scripts/eval_asof.py --seasons … --cutpoints 30 60 90`); EXP-019 logged with the
baseline numbers; ROADMAP 7.0 in-season checkbox fully ticked.

## Step 12 — nightly pipeline + manual status overrides

**Build:**
1. `scripts/update_daily.py`: (a) re-pull current season's `player_game_logs` (full-season
   refetch, replace-in-cache keyed on SEASON — endpoint returns the whole season; simple and
   idempotent), (b) incremental injuries/transactions pulls (Step 7/8 scrapers, since-date),
   (c) `project_asof(today)` → append-only
   `data/processed/ros_board/<YYYY-MM-DD>.parquet`, (d) DARKO + ADP pulls (existing
   scripts) so their archives accumulate. One command, safe to cron.
2. `config/overrides.yaml` + application in `project_asof`:
   ```yaml
   # player status the box scores can't know yet; applied to availability only
   overrides:
     - name: "Jayson Tatum"        # matched via normalize_name
       out_until: 2027-01-15       # or: out_for_season: true
   ```
   Effect: `y_ros_gp_pred = min(pred, games_remaining_after(out_until))`. Deterministic,
   auditable, never touches rates/minutes. (A scraped official injury-report feed is a
   later upgrade; overrides give the news channel *now* with zero scraping risk.)
3. Storage discipline check: everything date-stamped/append-only per
   `model-foundation.md` §7 — verify no writer overwrites history.

**Done when:** `update_daily.py` runs end-to-end locally on the live season (or dry-runs
clean off-season with cached data); overrides unit-tested (capped GP, name matching);
README gains the nightly-run section.

## Step 13 — EXP-020: external benchmarks go live-comparable

**When ≥ 1 season of date-stamped DARKO/ADP archives exists (they accumulate from
Steps 9/12 automatically):** join archived snapshots at each cutpoint; add `darko_dpm` /
ADP-rank as **eval comparators** in `eval_asof` (who called the riser first — us, DARKO,
ADP?) and A/B `darko_dpm` as a *feature* in `project_asof` (the EXP-010 ledger's condition
is now met). Gate: standard — floor-adjusted riser improvement, lead-time non-regression.

**Done when:** EXP-020 logged (even if the verdict is "archives still too short — re-arm
next season"); ROADMAP 7.E test checkbox resolved.

---

# PHASE 4 — the distributional board (Steps 14–15)

## Step 14 — EXP-021: learned ranges replace the hand-set spread

**Build — `src/fantasy_nba/models/uncertainty.py`:**
1. `simulate_ranges(..., pg_quantiles=None)`: when given the Step-5c quantile frame
   (`fpts_pg_q25/50/75/90` per player), draw per-game values from the piecewise-linear CDF
   through those quantiles (tails: extend linearly with the q25–q50 / q75–q90 slopes,
   floor 0) instead of `normal(fpts_pg, SD_PG)`. Keep the normal path as fallback when the
   frame is absent.
2. GP draws: per-player injury-profile pools from Step 7b (already built) — wire as the
   default when injury data exists.
3. **Coverage per mover bucket** joins the standing scoreboard (the deferred Step-1 column):
   in `eval_movers`, when ranges are available, report per actual-Δ bucket the fraction of
   realized season totals inside [p10, p90]. Target: ≥ 70% in the big-riser bucket (they are
   currently the systematic escapees) with overall in [78%, 88%].

**Gate (adopt):** overall coverage within [78%, 88%] **and** big-riser coverage improves vs
the SD_PG=9 baseline **and** `safe`/`ceiling` ranking Spearman not worse. On adopt: delete
the `SD_PG` constant path? **No** — keep as fallback, but the default board uses learned
ranges; update the `uncertainty.py` module docstring (its "Model" section) to describe both.

**Done when:** EXP-021 logged; Stage-6 ROADMAP items get a "superseded by learned ranges"
note; `--ranges` output columns unchanged (downstream compatibility).

## Step 15 — Ship + final sweep

1. **Default model switch:** `scripts/project.py --model` default flips from `v2m` to the
   best adopted configuration (expected: `learned` + adopted Step 4/5/6 modes); `--asof
   <date>` flag added (routes to `project_asof`; default = today in-season, T₀ preseason).
   Marcel models stay selectable (the permanent "did we lose signal?" fallback).
2. **Explorer:** `scripts/explore.py` gains (a) model choices for the adopted variants,
   (b) an ROS tab reading the latest `data/processed/ros_board/` snapshot with the
   disagreement tables (DARKO, ADP), (c) range columns on the board tab, (d) the D1
   decision columns (VOR, playoff-week games, short-horizon totals) on both tabs.
3. **Final documentation sweep (the whole-repo staleness pass):**
   - [ ] `README.md`: quick start reflects the new defaults, nightly run, all scripts.
   - [ ] `ROADMAP.md`: Stages 4–7 checkboxes reconciled; anything superseded says so and by
         what. (Stage 4 rookies + Stage 5 category scoring remain honestly-open items —
         list them under "next frontiers", don't silently drop them.)
   - [ ] `EXPERIMENTS.md`: every EXP-011…021 present with final status; "next experiments"
         line updated to the post-ship frontier (rookies, category scoring, official injury
         feed, home-grown online skill layer per model-foundation §3C).
   - [ ] `docs/model-foundation.md` + `docs/breakthrough-plan.md`: mark delivered; divergences
         between plan and what actually shipped noted inline (dated, one line each).
   - [ ] This file: tracker all ☑; add a final "as-built vs as-planned" paragraph.
   - [ ] Claude memory updated with the final architecture + the "do not retry" list
         (EXP-004 GP ceiling, EXP-008 season slopes, plus whatever Steps 2–14 added).
4. **Verification:** full test suite; one end-to-end draft-board run and one `--asof` run;
   numbers spot-checked against the ledger.

**Done when:** all boxes above ticked. The system is: a learned, decompositional,
as-of-date, allocation-aware, injury-aware projection with learned uncertainty, evaluated
floor-adjusted on movers, updating nightly, benchmarked against the market — the
"most accurate model" target expressed as the sum of every adopted, measured step.

---

## Appendix A — gate summary (one screen)

| Exp | Adopt when (all floor-adjusted where applicable) |
|---|---|
| 011 | diagnostic — produces the floor table + Phase-0 verdict |
| 012 | riser+big-riser ≥25% reducible-gap closed vs learned_recency AND aggregate win kept (3/4 seasons) |
| 013a/b | riser+big-riser ≥25% closed, stable-bucket bias within ±0.5, ranking Spearman within noise |
| 013c | beats constant-σ baseline on pinball loss overall AND in riser bucket |
| 013d | tuned params: pooled level MAE improves AND riser bias not worse (rule-8 guarded) |
| 014 | minutes MAE ≤ control AND riser ≥25% closed; OR role-change segments −15% level MAE, others ≤3% worse |
| 015a | GP Spearman +0.05 vs current | 015b: coverage ∈ [78,88]% AND safe-Spearman ties/wins |
| 016 | unconditional for backtests (correctness); re-affirm Step-6 verdicts on honest rosters |
| 017 | benchmark-only until 2 seasons of ADP archives |
| D1 | product step — no gate; ships with sanity reports (VOR reorder count, schedule spot-checks) |
| 022 | direct beats composed on riser bias ≥25% reducible-gap (rule-8), or bucketed covariance large+positive → adopt correction/blend |
| 023 | standard mover gate; watch age ≤ 24 cohort; rule-11 hygiene on the lag group |
| 024 | standard mover gate AND aggregate MAE not worse (consistency fix adoptable on a tie) |
| 025 | (reserved — rotation-survival hurdle; spec when Phase 0 says fallers matter) |
| 018 | beats frozen-T₀ AND naive-shrinkage updater at ≥2/3 cutpoints, 3/4 seasons |
| 019 | diagnostic — baselines recall + lead time |
| 020 | standard riser gate + lead-time non-regression |
| 021 | coverage ∈ [78,88]% AND big-riser coverage improves AND rank Spearman not worse |

## Appendix B — documentation consistency matrix

| Doc | Owns | Must never contain |
|---|---|---|
| `README.md` | setup, layout, commands, data pulls | experiment results, plans |
| `ROADMAP.md` | stage checkboxes, key findings, links | step-level specs (live here) |
| `EXPERIMENTS.md` | results ledger, append-only | forward plans beyond the "next" line |
| `docs/model-foundation.md` | architecture decision record (historical) | current run orders (superseded → here) |
| `docs/breakthrough-plan.md` | diagnosis + phase rationale | step-level specs (live here) |
| `docs/design-critique.md` | standing review: assumptions, leakage, statistics, decompositions | run order (its actions are folded here) |
| `docs/implementation-plan.md` | step specs, gates, tracker | results (those go to the ledger) |

When any two disagree, the more specific doc wins and the less specific one gets a pointer,
in the same commit.

## Appendix C — data snapshot for remote sessions (optional)

To let remote (no-egress) sessions run Steps 1–5 code + evals: commit to a branch a trimmed
snapshot — `data/raw/player_season_stats.parquet`, `player_bio.parquet`, plus a *reduced*
game-log table (only the columns recency/trade/asof need: `SEASON, PLAYER_ID,
TEAM_ABBREVIATION, GAME_DATE, MIN, PTS`; parquet+zstd keeps 16 seasons ≈ a few MB). Add a
`data/README.md` stating the snapshot date and that `.gitignore` stays authoritative for
full raw pulls. Steps 6+ (rosters/injuries/ADP) still need local pulls.
