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
   out-of-sample test; *(amended 2026-07-09: the freeze is **dual** — pure-model board A
   and analyst-adjusted board B, per Step D2 / EXP-029)*; (b) hyperparameter selection is **nested** — tune on folds
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
| 6 | 1 | Team-constrained minutes allocation | EXP-014 | ☑ | ☑ (rejected) |
| R1 | 1.5 | Composition-covariance check (direct vs composed) | EXP-022 | ☐ | ☐ deferred* |
| R2 | 1.5 | Per-season lags + era context | EXP-023 | ☐ | ☐ deferred* |
| R3 | 1.5 | Volume/efficiency split + pace normalization | EXP-024 | ☐ | ☐ deferred* |
| 7 | 2 | Injury/availability data | EXP-015 | ☑ | ☑ (split: GP rejected · MC tails adopted) |
| 8 | 2 | Dated transactions + preseason rosters + vacated usage | EXP-016/016b | ☑ | ☑ (016 adopted · 016b parked) |
| 9 | 2 | Market benchmark (expert consensus + ADP-for-availability) | EXP-017(+b) | ☑ | ☑ (017 adopted live · 017b waived — archives <4 seasons; re-pull Sept, re-arm 2027) |
| 9b | 2 | Breakout archetype layer, recall-gated | EXP-026 | ☑ | ☑ (both wirings rejected; breakout_p column ships) |
| 9c | 2 | Coach changes + preseason-October logs (+ win totals) | EXP-027 | ☑ | ☑ (a coach rejected · b `learned_ps` adopted-Oct, big-riser capture +9pp · c waived) |
| 9d | 2 | Rookie model (draft slot × landing spot) | EXP-028 | ☑ | ☑ (rejected — pick-order unbeaten; D1.5 market seed stands alone) |
| D1 | 2.5 | Decision layer: league config, VOR, schedule, rookie seed | — (product) | ◐ D1.1 ✅ · D1.2 VOR ✅ · D1.3 script ✅ (2026-27 schedule publishes ~mid-Aug) · D1.4 VOR+ADP ✅ (playoff cols await ESPN calendar) · D1.5 mechanism ✅ (extended 2026-07-17: returning-vet seed live — Kyrie/Haliburton/Beasley/Lillard, now MODEL-PROJECTED not just ADP-seeded per D1.6/EXP-032 2026-07-25; 2026 rookies hit the market pulls ~Sept) | ◐ (see D1 notes, 2026-07-10 + 2026-07-17) |
| D2 | 2.5 | Analyst pass + dual-board freeze | EXP-029 | ☑ (overrides schema + `apply_analyst.py` + trigger generator, tested 2026-07-10; **workflow v2 2026-07-12**: proposals flow + nightly in-season hook live; explorer board-B toggle 2026-07-13; **sizing contract corrected 2026-07-25** — EXP-033 withdrew "re-anchor a small-sample base on the last healthy season" (inflates +3.34/+5.56 fpts/g) and EXP-034 withdrew the ×0.85 per-36 fade (directionally wrong); magnitude is now decomposition with a machine-checked `sizing:` block, retro-filled onto 58 standing entries, Sabonis +4.0 → +1.0 promoted; **second VERB added same day** — `target_mpg` (absolute minutes, rescales the stat line at held rates and re-derives fpts, self-limiting so no Step-18 decay) alongside `fpts_delta` (rate residual), one per factor of the model's minutes × rate; 33 entries re-expressed, WAS team minutes 312.9 → 244 vs the 240 budget) | ◐ pending (living entries any time via proposals→approval; mid-Oct = re-review + dual freeze; Apr 2027 scoring now *calibrates* — amended gate, Appendix A) |
| 10 | 3 | As-of-date projection function | EXP-018 | ☑ | ☑ (foundation adopted; naive gate parked) |
| 11 | 3 | In-season eval + lead-time metric | EXP-019 | ☑ (`eval_asof.py --exp019`; half-lives frozen) | ☑ (adopted diagnostics: +30d reducible gap ≈ 0 · riser-recall 51.7% · lead 52d @ 99% detect vs naive 70% · league-horizon flips 2/12 → both views) |
| 12 | 3 | Nightly update pipeline + status overrides | — | ☑ (`update_daily.py` + `overrides.yaml` + `refresh_season`; naive line per addendum 5) | ☑ off-season dry-run clean 2026-07-10 (`--offline --asof 2026-03-01`); goes live opening night |
| 13 | 3 | External in-season benchmarks (DARKO/ADP archives) | EXP-020 | ☐ | ☐ |
| 14 | 4 | Distributional board (quantile ranges, GP tails, coverage) | EXP-021 | ☑ (piecewise-CDF path + `residual_pool` + `calibrate_resid_scale` + `range_coverage` scoreboard) | ☑ (rejected — SD_PG=9 stands; re-arm post-2026-27 per ledger note) |
| 15 | 4 | Ship: default model switch, explorer, final doc sweep | — | ☑ (`project.py` default `learned` + `--asof`; explorer: learned default, chronic GP pools, D1 columns, ROS tab) | ☑ 2026-07-10 (see as-built note under Step 15) |
| 16 | 5 | Vacated-minutes absorption + live OUT-redistribution | EXP-030 | ☑ (`absorption.py` + `--exp030` + nightly wiring) | ☑ 2026-07-11 (adopted-tentative — MAE-neutral, treated bias −0.15→−0.01, lead +5–8d; naive gate re-ran, stays parked; re-affirm Apr 2027 short-horizon) |
| 17 | 5 | Budget-reconciled minutes (allocation v2: depth features + soft reconciliation) | EXP-031 | ☑ (`eval_budget.py` + `learned_depth` + `reconcile_minutes`) | ☑ 2026-07-11 (both wirings rejected; 17.1 diagnostic ADOPTED — overshoot +0.18 supply, error-corr +0.38; re-run per adopted-model change) |
| D1.6 | 2.5 | Returning-vet projection (project from last healthy season) | EXP-032 | ☑ (`config/returning_vets.yaml` + predict-only `include_ids` in `_core`/`learned` + `overrides.yaml` `games_cap` + `eval_returning_vets.py`) | ☑ 2026-07-25 (adopted — n=50 cohort: MAE 5.15 vs naive 5.99, optimism bias halved +1.28 vs +3.42, ρ 0.75; zero blast radius; Haliburton/Kyrie/Lillard/Beasley live, VanVleet joins Sept) |
| 18 | 6 | Analyst-delta lifecycle: staleness flag + optional decay (the double-count guard) | — (product) | ☑ 2026-07-16 (18.1 staleness report + `analyst_stale` column in `update_daily.py`, base-then recovered from the snapshot archive/board A; 18.2 `--analyst-decay` behind its flag, OFF by default; unit + end-to-end tests) | ◐ (18.1 acceptance spot-checks + 18.2's validation gate need real in-season `--asof` dates — run them once the nightly cron has snapshots; ledger addendum then) |
| 19 | 7 | Live draft room: ESPN feed + dynamic VOR + composition views | — (product) | ☑ 19.1–19.3 + 19.7 (`draft/{feed,ids,live}.py` · `api/draft.py` · `views/DraftRoom.tsx`; 27 tests) | ☑ **shipped 2026-07-16** — verified on the real league + driven in a browser. **19.4–19.6 (the H2H simulator) descoped 2026-07-16, user decision** — see the note under Step 19 |

*\*Phase-0 verdict (EXP-011, Decision Row 1, 2026-07-08): the model-pool riser reducible gap
is +0.19 fpts/g (< 2) — preseason bias-chasing is near-done and the residual headroom is
sleeper recall. Per the decision row, Steps 4–6 ran as cheap A/Bs (all parked/rejected:
EXP-012/013/014) and **Step 10 is pulled forward next**; R1–R3 (preseason decomposition
refinements) are deferred behind it — they chase the same ≈0 preseason gap. Steps 7–9
(exogenous data) keep their place: they attack GP/availability and backtest correctness,
which the Phase-0 verdict does not touch.*

**Session addenda (2026-07-09, post-Step-10) — technical notes for the next session
(item 1's ordering is superseded by the draft-focus re-route below; items 2–5 stand):**

1. **Next step = Step 11 (EXP-019).** Run its diagnostics on the **EWMA configuration**
   (`use_ewma=True` — best pooled config in EXP-018, 3.763 vs naive 3.837); treat it as the
   recommended `project_asof` configuration until the re-gate says otherwise.
2. **Lead-time metric cost control (Step 11.3):** a literal implementation needs *daily*
   re-projection — expensive. Fit the fold's models once (`_fit_asof_models`) and call the
   cheap `predict_board` per date; evaluate on a **weekly grid**, or better, **event-anchored**:
   detect confirmed role changes from game logs first, then scan predictions only in a window
   around each event.
3. **`fit_half_lives` is the slow step** and is recomputed per fold although the fitted
   answer was identical in all four folds (**every rate → 40, MPG → 10**). Cheapest fix:
   freeze those as documented constants (with the fitting function kept for re-checks);
   otherwise cache per training-window.
4. **EXP-018 re-gate checklist** (what re-arms the parked naive gate): Step 7 OUT-tonight /
   live teammate-vacated minutes → asof features; D1 schedule → real `ros_gp_max` +
   schedule-aware ROS; blowout share / |margin|≥25 exclusion + return-from-absence ramp
   (`team_game_logs` pulled 17 seasons, **unwired**); EXP-013d tuner re-arm on the ~33k-row
   cutpoint panel (the ledger's named re-arm point).
5. **Step 12 note:** `update_daily` should emit the naive-updater line next to the asof board
   — it's the standing benchmark, and the daily disagreement between them is itself a signal.

**Re-route (2026-07-09, draft focus — supersedes addendum item 1 above):** the user's stated
priority is capturing risers/fallers **for the draft** (calendar-hard: draft ≈ Oct), then the
in-season loop. The riser signal is exogenous (EXP-011's verdict; the Maxey pattern: archetype
fit × vacated usage × market gap), so Phase 2 grows three additions — **Step 8.4 (EXP-016b
vacated-usage features)**, **Step 9b (EXP-026 breakout layer, recall-gated)**, **Step 9c
(EXP-027 coach changes + preseason-October logs)** — and Step 9's market sources are revised
(user 2026-07-09: expert consensus — Hashtag / Basketball Monster — is the quality benchmark;
platform ADP (Yahoo/ESPN) is too noisy for value and is kept **only** for the draft-day
availability column). **Recommended session order:** Step 7 (EXP-015) first — its scraper is
shared with Step 8, and its injury feed is both the EXP-018 re-gate dependency and the
in-season news channel — then 8 (+8.4) → 9 → 9b → 9c → 9d → D1 (**before draft day, with the
real scoring locked in `scoring.yaml`**) → D2 (**the last ~2 weeks before the draft**) → 11 →
12 (**before opening night**) → 13–15. Step 11 is data-independent and may interleave anywhere.

**Re-route addendum (2026-07-09, same day — gap-closers vs commercial systems):** the user
asked how to close the gap on what human-curated systems (Basketball Monster-class) do
better. Three additions, in return-on-effort order: **D1.5 rookie market-seed** (trivial
stopgap: rookies enter the draft sheet from the Step-9 consensus pull, flagged
`market_priced` — closes the "invisible rookies" hole immediately), **Step D2 (EXP-029)
analyst pass + dual-board freeze** (the human-judgment layer, replicated auditable and
*scored*: freeze the pure-model and analyst-adjusted boards separately before opening night,
grade both in April — the layer must earn its place or be deleted), and **Step 9d (EXP-028)
rookie model** (draft slot × landing spot; reuses Step-8.4 vacated-usage features; gate =
beat the draft-pick-order baseline). The long-run gap-closer is already structural: Step-9/13
archives turn every season into a labeled dataset of *where the commercial systems beat us
and on whom* — harvest it each spring.

**Status note (2026-07-10 evening, post D2-build/11/12 — commits dfb4793 · 6ce813f · a141c3e):**
every step buildable before the calendar gates is now done. What remains, in order:
**build-now** = Step 14 (EXP-021 distributional board) → Step 15 (ship) *(both ran
2026-07-10 later that session — Step 14 rejected, SD_PG=9 stands, see its as-completed
note; Step 15 shipped, see the as-built close-out under Step 15. **Nothing buildable
remains — every next action is on the standing calendar below.**)*;
**~mid-Aug** =
schedule pull + ESPN matchup calendar → `league.yaml`; **~Sept** = market re-pulls (D1.5
rookie seed goes live) **+ a first transaction/roster refresh** (`pull_injuries.py --dataset
transactions`, incremental — most of the summer's FA/trades have resolved by now, so the Sept
market board already reads the right teams); **mid-Oct** = re-pull `preseason_game_logs` +
`draft_history` **+ refresh transactions & injuries** (`pull_injuries.py --dataset transactions`
then `--dataset injuries`) → regenerate the sheet with `--model learned_ps` →
`analyst_triggers.py` → the analyst pass → `apply_analyst.py` → **dual freeze committed before
opening night** (D2.3 / rule 10a) **+ the Step-19 draft-room re-verification sweep (19.1b) —
league id / team ids / size / roster slots / pick order are all mutable until draft night and
every ESPN fact in Step 19 was measured 2026-07-15 on an undrafted league; a resize re-prices
the whole board via replacement level, so this runs BEFORE the freeze. Run the mock draft here
too — it is the only answer to the polling-latency question;** **opening night** = cron
`update_daily.py`; **April 2027** =
score EXP-029 A-vs-B + the rule-10a freeze, and EXP-020 arms when its archives reach ≥ 1 season.
Step 13 stays archive-gated — do not log it early.

> **Why the transaction refresh is load-bearing (note 2026-07-13):** `preseason_roster_map`
> (Step 8 / EXP-016) assigns every player to a team as *prior-season primary team + PST
> "player movement" transactions dated ≤ Oct 1*. So a player only lands on his **new** team
> once `data/raw/transactions.parquet` is re-pulled — and the 2026 off-season moved an unusual
> number of rotation players (per the BBM transcripts: Kawhi→TOR, Jaylen Brown→PHI, LaMelo→MIN,
> Kessler→LAL, Vučević→ORL, Naz Reid→CHA, Randle→BKN, Paul George→BOS, Ja Morant→POR, Ingram→LAC,
> Norman Powell→CHI, Collins→DET, Aldama→DAL, …). The roster map feeds **team assignments on the
> draft sheet, the EXP-030 vacated-minutes redistribution, and the depth/position features
> (`depth_rank`, `n_same_pos`, position scarcity)** — all of which run on *last* season's rosters
> until the refresh. Refresh transactions at the Sept gate and again at mid-Oct **before**
> regenerating the sheet and committing the freeze; the analyst layer (per-game deltas) is a
> separate axis and does **not** substitute for it. In-season this is automatic — `update_daily.py`
> pulls transactions/injuries incrementally each night.
>
> **Addendum (2026-07-17):** a transaction refresh ran early — cache now through
> 2026-07-13, covering the July FA wave (the BBM-claimed moves all confirmed in PST).
> The **live board's team display** now overlays `preseason_roster_map` directly
> (`api/boards.py`, current target only) so July movers read correctly today —
> display-only; the sheet's team assignments, EXP-030 redistribution and depth features
> still key off the cache vintage at regeneration time, so the Sept + mid-Oct refreshes
> above stand unchanged.

**Phase-5 note (2026-07-10 late, post-ship — user direction):** the minutes-economy pair
(Steps 16–17, EXP-030/031) is added as the new **build-now** work: the user's standing
conviction is that minutes are a 240-per-game constrained resource ("one ball"), and the
EXP-014 post-mortem supports a re-entry that never routes per-game through predicted GP.
Step 16 (OUT-redistribution) first — it is the EXP-018 re-gate's named "OUT-tonight /
live teammate-vacated minutes" item and the open in-season frontier; Step 17 is the
bounded-expectations preseason leg. Full specs in PHASE 5 below; the standing calendar
is unchanged and takes precedence at its dates.

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
> teammate's vacated share, depth ranks, normalization to 1 − reserve).
>
> **As completed (2026-07-08, local):** 6.1 — `pull_seasons` loops seasons for
> `team_rosters` (17 seasons cached; every POSITION string maps; the departed-player
> position limitation above is resolved by `pos_group_asof`'s past-preferred lookup).
> 6.2 — share-model layer in `allocation.py` (`share_labels`, `build_share_panel`,
> `fit_share_model`, `predict_shares`, `ALLOC_MODEL_FEATURES`), wired as
> `project_learned(minutes_mode="allocation")` / variant `learned_alloc`. The Σ-share
> sanity **did its job**: raw team sums were 1.21 vs the 0.89 target — two calibration
> flaws found and fixed (the 200-min label filter selected on the outcome; no-prior roster
> players double-counted the rookie reserve). After fixes: mean 0.946 vs 0.892. The share
> universe = players with a prior-season row (the learned board's universe by construction).

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
> **Amended 2026-08-02 (user decision) — missed-season carry-forward.** The seed is keyed on
> minutes *played*, so a player who missed the ENTIRE prior season had no row and dropped off
> every roster. Kyrie Irving was on no team at all despite ranking 30 on the live board (0 gp
> in 2025-26; same for Haliburton and Lillard). A player absent from the prior season is now
> seeded from the season **before** it — lookback deliberately **one** season, because a
> two-season gap is a retiree and carrying those forward would put dead names on rosters. The
> transaction pass still runs on top, so anyone who genuinely left is cleared by his own
> `relinquished` row. Recovers 4 board players on the live map (Irving→DAL, Haliburton→IND,
> Lillard→MIL, Beasley→DET); teamless 88 → 84. Dated addendum under EXP-016.
>
> **The shipped board does NOT consume this map** — `project.py --model learned` runs with
> `use_context=False` and `minutes_mode="regression"`, the two gates on `target_team_map`, and
> a post-fix re-run is bit-identical. The map drives team display, the BBM preview ledgers and
> their 240 budgets, EXP-030 redistribution, and backtest consumers only.
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

**8.4 — EXP-016b: vacated-usage features (the preseason opportunity signal, done honestly).**
EXP-009 tested team-level vacated *minutes* on end-of-season rosters (parked: net wash — and
the map flattered mid-season movers). With the honest preseason map + dated departures, build
the sharper version in `models/context.py`:
```python
VACATED_FEATURES = [
    "vac_min_share_pos",   # Σ departed same-pos-group teammates' prior share of team minutes
    "vac_usg_pos",         # Σ departed same-pos-group teammates' prior USG% × minutes share
    "vac_fga_pm",          # departed teammates' FGA per team minute (shot vacancy)
    "vac_ast_pm",          # departed teammates' AST per team minute (creation vacancy)
    "star_departed",       # any departure with prior USG% ≥ 24 and MPG ≥ 30 (holdouts count
                           #   only when the departure is dated ≤ Oct 1 — no hindsight)
    "arrivals_usg_pos",    # the mirror: usage arriving in his position group (role compression)
]
```
Position groups via `allocation.position_group` (`pos_group_asof` past-preferred lookup for
departed players). USG%: verify it survives the Advanced merge in cached `player_season_stats`
(same check pattern as Step R3's PACE); else derive `(FGA + 0.44·FTA + TOV)` per team
possession-proxy. A/B as `learned_vac` on the standard eval **plus the realized-pool recall
view** — this group's whole point is pulling context-driven risers *into* the pool, which the
model-pool bias tables understate (EXP-011's lesson).

**Gate (EXP-016b):** standard mover gate on the model-pool view, **or** realized-top-150
big-riser recall +2pp pooled with aggregate level MAE not worse. Rule-8/11 guarded. Separate
ledger verdict from the map-correctness fix (EXP-016 is unconditional; 016b is a feature bet).

**Done when:** validation ≥ 90%, consumers re-run, EXP-016 + EXP-016b logged, ROADMAP 7.A data
checkbox ticked.

## Step 9 — EXP-017: market benchmark (expert consensus first; ADP only for availability)

**Source hierarchy (user decision, 2026-07-09):** platform ADP (Yahoo/ESPN) is too noisy to
serve as the value benchmark. Two distinct market objects, never conflated:
- **Expert consensus rankings — the quality signal:** Hashtag Basketball season rankings
  (public HTML, points-mode where available); Basketball Monster projections if exportable
  (subscription — check before building). This is what "the market knows" means in every
  disagreement report and in EXP-017b/EXP-026 below. It also imports the human-intel layer
  (camp reports, coach quotes) without scraping news.
- **Consensus ADP (FantasyPros points-league) — the availability signal only:** kept solely
  for the draft-sheet "likely gone by pick N" column (D1.4), where actual draft position is
  what matters even when it's wrong about value.

**Build — `scripts/pull_market.py`:** both sources, date-stamped like the DARKO pull
(`data/raw/market/<source>_<date>.parquet`), name-joined with match-rate report (≥ 95% on the
draftable pool; Step-7 name-join hardening rules apply). New `scripts/market_report.py`
(mirror `darko_report.py`): board-vs-consensus top-20 disagreements each way (our rank −
consensus rank), flagged with the risk column so "we're low on X" reads with context.

**EXP-017b — market-rank-gap as a *feature* (the Basketball-Monster-in-a-column bet):**
`market_gap = our_rank − consensus_rank` (+ the raw consensus rank) fed to the learned model —
the hypothesis is the model learns *when* the market knows something we don't (young player,
new team) vs when it's chasing name value. **Requires historical preseason archives:** check
retrievability first (FantasyPros historical ADP pages go back years; Hashtag/BBM past-season
rankings may be recoverable) — if ≥ 4 backtest seasons are recoverable, run the A/B now
(standard mover gate + the recall view, rule-11 hygiene); if not, benchmark-only this season
(the EXP-010 waiver), archive from today, re-arm next season. Log which branch was taken.

**Done when:** pulls + report run end-to-end; EXP-017 logged (benchmark), EXP-017b logged
(run or explicitly waived-with-condition); ROADMAP 7.E checkbox ticked.

## Step 9b — EXP-026: breakout archetype layer, judged on recall (ROADMAP 7.B, done right)

**Why this gate:** EXP-011 proved the model-pool riser *bias* is ≈ irreducible preseason —
but the realized-pool view showed the actual cost: **recall 71%** (missed sleepers never enter
the pool; realized-pool gap −2.7). A breakout layer is therefore judged on **getting eventual
risers into/up the board and above their market price**, never on per-player point error —
you can't know which of ~20 archetype fits pops; ranking all of them higher *is* the edge
(the Maxey pattern: age-22–24 improvement streak × usage↑ at held TS% × vacated usage ×
market gap, all visible preseason).

**Build — `src/fantasy_nba/models/breakout.py`:**
```python
BREAKOUT_FEATURES = [
    "improve_streak_2y",   # consecutive prior seasons of rising fpts_pm (0/1/2)
    "usg_slope_held_ts",   # ΔUSG% (t−1 vs t−2) where ΔTS% ≥ −0.01, else 0
    "mpg_headroom",        # max(0, 36 − prev_mpg): room to grow
    "age_22_24",           # the research's breakout window
    "years_experience",
    "draft_pick",          # pedigree; verify DRAFT_NUMBER survives the player_bio pull,
                           #   else one draft-history endpoint pull
]

def breakout_score(panel, feature_cols) -> pd.Series:
    """P(actual next-season Δ ≥ +6 fpts/g) — LGBM binary classifier on the existing
    panel labels, walk-forward like every other fit."""
```
Two wirings, judged separately: **(a) features into the learned model** (standard A/B,
`learned_breakout`); **(b) a board policy** — top-K breakout scores get a flagged
`ceiling`-stance rank boost + a `breakout_p` column on the draft sheet (deterministic,
auditable — the "at least attempting every breakout" lever, sized so late-round picks chase
option value while the stable core is untouched).

**Metrics (per season + pooled):** realized big-riser **recall@150**; **above-market rate**
(of realized big risers, fraction we ranked above the expert consensus — needs Step 9; this
is the draft-capture number: did we have him before the room did); cost line = aggregate
level MAE + stable-bucket bias.

**Gate:** (a) standard rule-8/11. (b) policy adopts if big-riser recall@150 +3pp **or**
above-market rate +5pp, with aggregate MAE ≤ +1% and stable-bucket bias within ±0.3.
Log EXP-026 with both wirings' verdicts.

## Step 9c — EXP-027: coach changes + preseason-October logs (+ win totals rider)

Three cheap exogenous groups, judged separately (rule 11), rejected fast if they don't stick:

**(a) Coaching changes — hand-curated, one afternoon.** `data/manual/coach_changes.csv`
(`season, team, new_coach, interim`), 2009-10…2026-27 from Basketball-Reference coach pages
(~30 rows/season; commit the CSV — tiny, static, hand-checked; the repo's first manual-data
exception to the gitignore, note it in README). Features: `new_coach` **interacted** with
depth-rank/age (hypothesis: a new coach reshuffles the *rotation*, so the effect lives in
young/fringe players, not the main effect). A/B `learned_coach`, standard gate + recall view.

**(b) Preseason October game logs — the latest-arriving pre-draft signal.** nba_api
`LeagueGameLog` accepts `season_type_all_star="Pre Season"`; spot-check 3 historical seasons
for coverage, then add `preseason_game_logs` to the ingest datasets. Features (role only,
never rates — samples are tiny): `ps_mpg`, `ps_mpg_delta` (vs prior season), `ps_start_share`.
**Ship the columns to the draft sheet (D1) regardless of the A/B verdict** — "the coach played
him 34 minutes with the starters in October" is directly human-readable days before the draft.

**(c) Vegas win totals (optional rider):** historical preseason win totals (sportsoddshistory)
→ `team_expected_wins` (tanking → young-minutes runway; contender depth → minutes cap). Also
back-fills D1.4's `team_priors.yaml` (currently manual-entry). Include in the A/B only if the
scrape is trivial; otherwise D1 manual entry stands.

**Done when:** one EXP-027 ledger entry with a/b/c sub-verdicts; preseason-minutes columns
wired to the draft sheet; ROADMAP 7.A/7.B addenda boxes ticked.

> **As completed (2026-07-10, local):** split verdict — **(a) rejected** (`learned_coach`
> noise on every arm; the hand-curated CSV stays committed, `data/manual/coach_changes.csv`,
> the gitignore's first manual-data exception), **(b) adopted for the October window**
> (`learned_ps`: realized big-riser capture +9.2pp mean over seeds, aggregate MAE better all
> seeds — the first preseason recall movement in the program; `scripts/project.py --model
> learned_ps` + `--preseason` columns), **(c) waived** (sportsoddshistory now JS-rendered on
> covers.com; B-R 403s — D1.4 manual `team_priors.yaml` stands). Full numbers in EXP-027.
> **Calendar consequence:** the D1 sheet and the rule-10a dual freeze regenerate with
> `learned_ps` after preseason play in mid-October 2026 (`pull_data.py --datasets
> preseason_game_logs` then `project.py --model learned_ps --preseason`).

## Step 9d — EXP-028: rookie model (draft slot × landing spot) — Stage 4, first cut

**Why now:** rookies are the bluntest gap vs commercial systems — a player with no
prior-season row simply isn't on our board. The market-seed stopgap (D1.5) closes the
*visibility* hole; this step is the first attempt to beat the market's rookie rank with a
model. Research consensus: rookie fantasy value ≈ **draft slot + landing-spot opportunity**;
college-stat translation is a later refinement, not a prerequisite.

**9d.1 Data — draft history:** `nba_api` draft-history endpoint (one static pull, all years)
→ `data/raw/draft_history.parquet` (`PLAYER_ID, draft_year, overall_pick, round`). Add to the
ingest datasets. Undrafted rookies: `overall_pick = 61` sentinel + `undrafted` flag.

**9d.2 Build — `src/fantasy_nba/models/rookies.py`:**
- *Panel:* historical rookie seasons 2010-11…2025-26 = players whose first
  `player_season_stats` row is that season (~60/season × 16 ≈ 1,000 rows — small on purpose).
  Labels: realized rookie `y_mpg` and `y_fpts_pm` (fantasy points per minute under the
  scoring config). **Two targets only** — 13 rate targets on 1,000 rows would overfit;
  compose `fpts_pg = mpg × fpts_pm`. GP: rookie-cohort empirical mean by pick bucket (don't
  model — EXP-004 applies doubly to players with no history).
- *Features:* `overall_pick` (+ log), `undrafted`, `age_at_draft` (bio), `intl_flag` if
  derivable from bio country — plus the landing spot: the Step-8.4 vacated-usage group for
  his position group on the target roster, `n_same_pos` crowding, `depth_rank` treating his
  pick as pedigree, `team_expected_wins` if the 9c rider landed (tank → rookie runway).
  Position for rookies: draft-combine/bio listed position → the allocation groups.
- *Board integration:* rookie rows appended to the board flagged `rookie_model`; when the
  D1.5 market seed also exists, show both (`rookie_rank_model`, `rookie_rank_market`) — the
  disagreement between them is itself draft-day information.
- *Uncertainty:* rookies get the widest range bucket by construction (no history); flag,
  don't hide.

**9d.3 Run/Gate:** walk-forward on rookie cohorts (train < eval season). Baseline =
**draft-pick order** (rank rookies purely by pick — the naive strategy everyone can do).
Adopt if pooled rookie-cohort Spearman beats pick-order by ≥ 0.05 with MAE not worse
(rule 8 guarded); where market archives exist (EXP-017b branch), also report vs market rank
— informational this season, gate next. On reject: the D1.5 market seed stands alone;
ledger the numbers (a pick-order tie is a real finding — it means the market seed suffices).

**Done when:** EXP-028 logged; rookie rows appear on the draft sheet under whichever source
won; ROADMAP Stage-4 rookie checkbox updated; tests (synthetic rookie panel: pick-order
monotonicity, no-leakage on the first-season definition).

> **As completed (2026-07-10, local):** **rejected** — the model does not beat pick-order
> (pooled Spearman delta −0.02…0.00 over seeds vs the +0.05 gate; CI [−0.10, +0.05]; MAE
> slightly worse; on *totals* pick-order wins outright 0.62 vs 0.57). Landing-spot features
> verified real (96% non-zero) — the signal just doesn't generalize at ~60 rookies/cohort.
> The winning source is therefore the **D1.5 market seed** (build it in D1); informationally
> the archived market split 1-1 with pick-order (2022-23 +0.74 vs +0.64; 2023-24 +0.62 vs
> +0.69), so the sheet should show pick number alongside the market rank. Harness kept for
> re-arm: `models/rookies.py`, `scripts/eval_rookies.py`, the `draft_history` dataset
> (note: the 2026 draft class is not on the endpoint yet — re-pull before October; D1.5
> covers rookie visibility regardless). Full numbers in EXP-028.

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
> **D1.1 DONE (2026-07-10):** league confirmed — **ESPN default points, 10 teams, weekly
> H2H** — written to `league.yaml` (ESPN-default sub-settings marked as such).
> `scoring.yaml` was already the ESPN default points weights, so **every ledger verdict to
> date ran under the real scoring; no re-runs needed**. Still open in D1: schedule weeks
> (derive from ESPN's 2026-27 matchup calendar when published), D1.2 VOR (10 teams ×
> 13 slots), D1.3 schedule values, D1.4 sheet, D1.5 rookie market-seed.

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

**D1.5 Rookie market-seed (added 2026-07-09 — the stopgap for the Stage-4 gap):** rookies
have no prior-season row, so the model board silently omits them. Until/unless EXP-028
(Step 9d) beats the market: seed every rookie from the Step-9 expert-consensus pull onto the
draft sheet, flagged **`market_priced`** (no model behind the number — say so in the column).
Rank → value: interpolate `fpts_pg` from our own board at the consensus rank (so totals/VOR
compute consistently); ranges: the widest uncertainty bucket. **Sanity report:** count of
seeded rookies + eyeball the top 5 against the consensus source. If EXP-028 adopts, both
columns print (model + market) and the flag distinguishes them.

**Done when:** league.yaml filled; `add_vor` + schedule pull run end-to-end; draft sheet
prints rank / VOR / ADP-availability / playoff-week / rookie-seed columns; sanity reports
eyeballed and noted in the ledger as a dated D1 note (no EXP number — product, not hypothesis).

> **As built (2026-07-10, local) — D1 is code-complete; three cells wait on external
> publications:** D1.2 `models/value.py` (greedy 10-team × ESPN-starting-slot fill,
> guard/big groups; **sanity: VOR meaningfully reorders even a points league — 59 top-100
> rank moves ≥ 10**, position scarcity is real at 3 UTIL). D1.3 `scripts/pull_schedule.py`
> (ScheduleLeagueV2 — the cdn JSON 403s; regular-season filter handles Cup/Rivals/
> international labels, validated 1,230 games on 2025-26; prints per-week distribution,
> B2Bs, playoff-week counts, the D1.3b horizon cut) — **the feed serves 2026-27 ~mid-Aug;
> re-run then**, and derive `fantasy_playoff_weeks` + `league_end_offset_weeks` from the
> ESPN matchup calendar when published. D1.4+D1.5 `scripts/draft_sheet.py` (VOR + ADP
> availability + rookie market-seed; breakout_p/ps_*/risk pass through) — ADP matched
> 134/150 of our top-150; **the July FP pull carries no 2026 rookies yet** (seed guard:
> unmatched deep rows are stale stash names, capped at rank ≤ 160) — the seed goes live
> with the September market re-pull. Playoff-week board columns land after both
> publications.

> **D1.5 addendum (2026-07-17) — extended to returning vets (the Haliburton gap,
> user-found):** the seed keyed on presence in *season stats*, so vets with zero 2025-26
> games (no feature row → not on the board) but 2024-25 history fell through both nets.
> Now the seed keys on **board presence**: any market row missing from the board seeds at
> its consensus rank, split by `seed_class` (`rookie` / `returning-vet`); vets get real
> PLAYER_IDs + the market's team. Seeded 2026-07-17: Kyrie 124 · Haliburton 133 · Beasley
> 145 · Lillard 153. The API board (`api/boards.py`) **appends id-carrying seeded rows**
> and `rank_board` prices range-less rows at their ADP anchor under every stance
> (risk/p10/p90 stay NaN → UI "—"); id-less rookie rows stay sheet-only until the Oct id
> pass. Also fixed latent: the seed wrote string "rookie" into the numeric `risk` column —
> a draft-room-API crash waiting for the first seeded row. VanVleet: no FP top-260 ADP
> yet → still absent; the Sept re-pull is his path in. Ledger: D1 note addendum
> 2026-07-17.

## Step D2 — EXP-029: the analyst pass + dual-board freeze (the graded human layer)

*The gap-closer for what commercial systems' human staff do (camp reports, depth-chart
judgment, injury context) — replicated **auditable** and **scored**. Two-part discipline:
every adjustment is written down with a rationale before the season; the layer is graded
against the untouched model after the season and must earn its place or be deleted.
Timing: the last ~2 weeks before draft day (needs Step 9's market pull; benefits from 9c's
preseason-October minutes and Step 7's injury history).*

*(**Amended 2026-07-12, user decision — workflow v2, the living layer.** Three changes,
canonical contract in `data/manual/bbm_transcripts/README.md`: (1) entries may land any
time information arrives — BBM-transcript triangulation → `config/analyst_proposals.yaml`
(Claude drafts: model view × BBM view × own judgment; agreement = assurance → `none`
unless a new mechanism) → user approval → `analyst_overrides.yaml`; the mid-Oct pass
becomes a full **re-review** of every effective entry before the unchanged dual freeze;
(2) the layer also applies **nightly in-season** to the ROS board (`update_daily.py`,
audit columns, `--no-analyst`) — the in-season ROS adjustment the user named critical;
(3) D2.4's verdict **calibrates** the layer — magnitude rubric + per-source weighting,
with `BBM <date>:`-tagged entries scored as their own subset — instead of deciding its
existence: per the user, the layer is a standing supplement, "supplement, not beat".)*

**D2.1 Trigger list (generated, not vibes):** within the top-200 union of our board and the
expert consensus: (a) |our rank − consensus rank| ≥ 15; (b) every EXP-026 breakout-flag
player; (c) every major-injury returnee (Step-7 `inj_bodypart_severe` in trailing 18 months);
(d) every rookie (D1.5/9d). Expect ~30–50 players.

**D2.2 The pass:** one session, player by player: review the qualitative evidence a feature
can't hold (beat-writer reporting, depth chart, coach statements, rehab timelines — web
sources, local session). Output per player into `config/analyst_overrides.yaml`:
```yaml
- name: "Player Name"
  date: 2026-10-05
  category: role | injury | hype | rookie | other
  action: none | rank_delta: -8 | fpts_delta: +2.0
  rationale: >
    One paragraph. Written before the season; never edited after (append a dated
    correction instead).
```
`"none"` verdicts are logged too — "reviewed, no change" is information. *(Workflow-v2
policy note, 2026-07-12: new entries are **`fpts_delta` or `none` only — never
`rank_delta`** (transcripts-README hard rule 1; `apply_proposals.py --promote` refuses
it). The engine keeps `rank_delta` support for the as-built arithmetic tests only.)*
Application: `scripts/apply_analyst.py board.parquet` → board B (deterministic,
unit-tested arithmetic; never touches board A's file); interactively, the explorer's
Draft Board tab applies the same effective overrides via its **Analyst layer (B)**
toggle (2026-07-13).

**D2.3 The dual freeze (extends rule 10a):** commit **both** boards before opening night —
`data/processed/frozen_2026-27_preseason_model.parquet` (A: pure model) and
`…_analyst.parquet` (B: A + overrides) — plus a dated ledger note. Git timestamps are the
no-hindsight proof.

**D2.4 Scoring (April 2027, the other half of the experiment):** one eval run, both boards,
standard metrics (top-150 level MAE, mover buckets, big-riser recall, ranking Spearman) +
a **per-adjustment attribution table**: for each override — model rank, adjusted rank,
realized rank, which won. Verdicts: B > A → keep the pass, expand to in-season waivers;
A > B → delete the layer and ledger *which rationale categories* failed (that's tuition,
not just a loss); tie → keep as a documentation habit, not signal. *(Verdict semantics
superseded by the 2026-07-12 workflow-v2 amendment above: the table now calibrates
magnitudes + per-source weighting — incl. the `BBM <date>:` subset — the delete clause no
longer applies.)* **One-season sample:**
whatever the outcome, the ledger status is at most `adopted-tentative` / `parked` — an
unlucky injury on one heavily-adjusted player can swing it; say so in the entry.

**Done when:** overrides file populated with rationales; `apply_analyst.py` tested; both
frozen boards committed + ledger note dated before opening night; EXP-029 opened in the
ledger with status `pending (scores April 2027)`.

> **As built (2026-07-10, local — commit dfb4793; the buildable half only):**
> `models/analyst.py` + `scripts/apply_analyst.py` (board A → board B: deterministic,
> unit-tested, `model_rank`/`analyst_*` audit columns, board A's file never touched) +
> `scripts/analyst_triggers.py` (D2.1 generator) + `config/analyst_overrides.yaml`
> (schema documented, **empty — no overrides fabricated**; corrections are append-only,
> latest-dated wins). EXP-029 opened `pending`. July smoke run: 146 triggers — inflated by
> data vintage (July board vs July consensus); the real October run (learned_ps sheet +
> fresh market pulls) should land near the expected ~30–50. **Remaining (calendar-locked,
> mid-Oct):** the pass itself off the regenerated trigger list, then the D2.3 dual freeze
> before opening night, then D2.4 scoring in April 2027.
>
> **Workflow v2 (2026-07-12, commits 59beee2 · 724c42a):** the amendment above is live —
> `config/analyst_proposals.yaml` (draft → approve flow), the nightly in-season hook in
> `update_daily.py` (wiring verified end-to-end with a reverted test entry), and the
> transcript drop zone + triangulation rubric in `data/manual/bbm_transcripts/README.md`.
> "Remaining mid-Oct" now reads: **re-review** all effective entries off the regenerated
> trigger list + fresh videos, then the unchanged dual freeze.

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

> **Amendment (measured 2026-07-09):** the literal thresholds above are **below
> `project_learned`'s own seed-to-seed reproducibility** (two seeds of the identical model:
> Spearman 0.968–0.973, MAE 0.81–0.89 on this metric) — they are unreachable by construction.
> The operative criterion is **"within seed noise, and any residual gap explained."** Status:
> held (preseason-only asof = another-seed-indistinguishable; pooled model ~0.02 below the
> noise floor, documented as the cost of one model spanning six cutpoint regimes). The check
> did its job en route: it caught the garbage-time ROS-label bug (`MIN_ROS_MINUTES`).

**Gate (EXP-018):** at cutpoints +30/+60/+90: ROS level MAE on the top-150 pool beats both
(a) `project_learned` frozen at T₀ and (b) the naive updater
(`STD per-game line, shrunk: (games_so_far × std + 20 × T₀_proj) / (games_so_far + 20)`).
Beating (a) is table stakes; beating (b) is the evidence the *learned* shrinkage earns its
complexity. Adopt on 3/4 seasons at ≥ 2 of 3 cutpoints.

**Done when:** consistency check passes; gate evaluated + logged; ROADMAP 7.0 in-season
checkbox flips from parked to done-pending-Step-11.

> **As completed (2026-07-09, local):** core + two amendments built and measured
> (`models/asof.py`, `scripts/eval_asof.py`, `tests/test_asof.py` 6 green;
> `team_game_logs` dataset added + pulled for the blowout amendment). **Consistency:** the
> literal 10.2 thresholds are below `project_learned`'s own seed-to-seed noise floor
> (Spearman 0.968–0.973); preseason-only asof is within that noise (no leak, labels corr
> 1.0000); the pooled model pays a small documented pooling cost (0.947). **Gate:** frozen-T₀
> beaten 12/12 cells in every config; naive K=20 blend at parity (EWMA config −0.07 pooled
> MAE, cell tally 1/1/1/3 → **gate parked, engine adopted as the Phase-3 foundation**).
> EWMA half-lives fit to: every rate 40 games, MPG 10. Remaining amendments ride their data
> dependencies: teammate-vacated minutes → Step 7, schedule-aware ROS → D1, blowout/ramp →
> team logs (pulled, unwired), tuner re-arm (EXP-013d note) → this panel. See EXP-018.

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

> **As completed (2026-07-10, local — commit 6ce813f):** everything above prints from
> `eval_asof.py --exp019` (EWMA config; half-lives frozen as `asof.FROZEN_HALF_LIVES`,
> `--fit-half-lives` re-checks). Metric functions live in `eval_movers.py`
> (`role_change_events`, `lead_time_table`; unit-tested). Baselines (seed 0, pooled 22-23…25-26,
> full detail in EXP-019): +30d reducible gap ≈ 0 in every bucket; asof beats naive on
> big-riser bias at all cutpoints; **early-riser recall@150 = 51.7%**; **lead-time: asof 99%
> detection @ 52d median vs naive 70%** (medians condition on own detected subset — pair on
> the common set before gating on this); league-horizon truncation flips 2/12 cells ⇒ both
> views print. Both amendments handled: league-horizon ran (report-both verdict); the
> short-horizon next-7/14-day board rides Step 12's daily output and the D1 schedule —
> **still open, revisit when the 2026-27 schedule lands** (it needs real game dates).

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

> **As completed (2026-07-10, local — commit a141c3e):** built + off-season dry-run clean
> (`update_daily.py --offline --asof 2026-03-01`). Notes for the live run: pulls are
> fault-isolated (one flaky site never kills the night's board); the game-log refresh uses
> the new `ingest.refresh_season` (replace-in-cache keyed on SEASON — **`pull_seasons`
> rewrites the whole file and is now documented as the bulk/backfill path only**); the board
> write is append-only (`--force` to redo a date, never silent); the naive line (addendum 5)
> anchors on `data/processed/learned_<season>.parquet` — regenerate/freeze it preseason or
> pass `--t0-board`. Overrides applied inside `project_asof` (schedule-aware when the
> season's schedule pull exists, calendar-fraction fallback; loud name-match failure).
> The dry run itself demonstrated the need: Tatum (out for 2025-26) projected #1 with 65 ROS
> games — precisely the hole `config/overrides.yaml` plugs. **Cron it from opening night**;
> its date-stamped archives are Step 13's input. Storage-discipline check done (3): all
> writers append or replace-by-key; the one rewriting writer is documented.

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

> **As completed (2026-07-10, local):** all three build items shipped —
> `simulate_ranges(pg_quantiles=…)` piecewise-CDF sampler (normal path kept, per-row
> fallback for players missing from the frame), `residual_pool` (walk-forward out-of-sample
> residual CDF per the EXP-013c note, board-cached) + `pg_quantile_frame`, injury-profile GP
> pools already the default wherever ranges run, and the coverage-per-mover-bucket
> scoreboard (`eval_movers.range_coverage`, `scripts/eval_movers.py --ranges`, with the
> paired player-clustered coverage-delta CI). A third arm was added en route:
> `calibrate_resid_scale` — one width multiplier calibrated walk-forward to 0.83 total
> coverage on the pre-target seasons (the raw CDF is the honest per-game *marginal* and is
> structurally too narrow for *total* bands). **Gate failed on every clause across seeds
> {0,1,2}** (ALL 0.719 vs 0.805, big riser 0.598 vs 0.671, CIs exclude 0) → EXP-021
> **rejected as the default spread**; the ROADMAP note is "re-affirmed", not "superseded".
> Real finding: total-level dispersion rises era-over-era (walk-forward coverage at fixed
> scale declines 0.848 → 0.694 across targets), so a lagged honest calibration always
> trails; SD_PG=9's excess width absorbs that drift + the GP×PG covariance — but it broke
> the window itself in 2025-26 (0.719), where the calibrated arm already matched it.
> Re-arm named in the ledger (post-2026-27, calibration target raised toward 0.88).
> `--ranges` output columns unchanged; default board untouched.

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

> **As built vs as planned (Step 15 close-out, 2026-07-10).** Shipped: `scripts/project.py`
> defaults to **`learned`** (`learned_ps` is the documented mid-Oct switch once preseason
> games cache; Marcel/v2/v2m stay selectable fallbacks) and gained `--asof <date>` (the
> one-off `project_asof` ROS board on the adopted EWMA config with `overrides.yaml` caps;
> the cron path stays `update_daily.py`). Explorer: `learned` default model choice, risk
> ranges now on the adopted (age × chronic) GP pools, D1 decision columns (VOR/ADP) join
> from the target's draft-sheet parquet, and a new **ROS tab** reads the latest
> `ros_board/` nightly snapshot with the naive-disagreement table. Divergences from the
> Step-15 sketch, one line each: **"learned uncertainty"** shipped as *machinery, not
> default* — EXP-021 rejected learned ranges (SD_PG=9 re-affirmed; re-arm post-2026-27);
> **allocation-aware** means the EXP-009/016 team features, not the rejected EXP-014 share
> model; explorer **DARKO/ADP disagreement stays in the CLI reports** (`darko_report.py`,
> `market_report.py`) rather than a tab — the ROS tab points at them; `--asof`'s general
> `ros_gp_max` stays `= gp` until the 2026-27 schedule pull lands (mid-Aug; the
> overrides-based caps do use the schedule). Tracker honesty: rows 13 (archive-gated,
> ~Apr 2027) and the calendar halves of D1/D2 stay open by design — the standing calendar
> in the 2026-07-10 status note is the remaining work, none of it buildable today.

> **Delivery addendum (2026-09-21; expanded 2026-09-23).** The redacted `static/` snapshot is now deployed to
> GitHub Pages on every push to `main`; analyst promotion refreshes it automatically. The public
> projection hub includes board filtering/sorting, player drill-down and comparison, tiers, team
> summaries, and a browser-local manual mock draft without needing a backend. The mock room follows
> a 12-team snake by default, permits explicit team assignment, removes drafted players, persists
> picks in `localStorage`, and reports roster strength plus slot fit from a redacted positions-only
> export of the cached ESPN map. Live polling remains local. Public `rank` means ordinal projected FP/G. The local
> safe/season-value ranking remains available in the full app and is exported only as audit metadata
> (`source_rank` / `model_source_rank`); public tiers are FP/G-gap tiers and retain the local tier as
> `source_tier`. Live ESPN state, private analyst material, and writable workflows remain local-only.
>
> **2026-09-23 addendum:** the actual league is now confirmed at 12 teams, so `league.yaml`, VOR,
> replacement demand, manual mock clocks, and next-turn math all use 12. Draft Radar is a product
> overlay, not a model input: one-round ADP disagreements are target/fade candidates; a strong call
> needs a two-round gap plus an explicit projected-growth, analyst-role, or downside-risk mechanism.
> Personal priority targets, take-by picks, and notes remain browser-local.

---

# PHASE 5 — the minutes economy (Steps 16–17, added 2026-07-10 post-ship)

*Origin: user direction (2026-07-10 evening) — "there are only so many minutes and one
ball"; the 240-minute constraint is the right mental model even though EXP-014's
implementation of it failed. Two facts govern this phase:*

1. *The EXP-014 post-mortem exonerates the __structure__ and convicts the __conversion__:
   the share model was nearly competitive at season-total minutes (pool total-MIN MAE 496
   vs 447, −11%) — the damage was `MPG = share × team_total / pred_gp`, which routes the
   stable quantity through the near-unpredictable one (EXP-004: GP R²≈0.03), plus
   proportional normalization taxing stars. The ledger's do-not-retry is specific: never
   share-of-season-total ÷ predicted GP. Both steps below honor it — GP never appears as
   a divisor.*
2. *Where the constraint binds is __per game, over the active roster__ — which is the
   in-season/OUT-tonight situation, not the preseason board. Preseason reducible riser gap
   is ≈ 0 (EXP-011, Decision Row 1); the open frontier is in-season and exogenous (EXP-019:
   riser recall 51.7%, lead 52d; EXP-018 ledger: "the next in-season accuracy must come
   from new information — who is OUT tonight"). So the redistribution step goes first and
   carries the higher expectation; the preseason budget step is a bounded-expectations
   cheap A/B.*

*Outside practice (researched 2026-07-10): DARKO treats minutes as the hardest component
and wins via daily Bayesian updating (exponential decay + Kalman filter + a GBDT combiner)
— structurally our EWMA engine, no team constraint. DFS practice handles OUT-redistribution
with hand-set same-position tiers (backup +12–15 min, other same-pos +3–5, adjacent +2–3;
usage +4–6% to the next-highest-usage teammate) validated against with/without splits. Our
edge: we can __fit__ those tiers from 17 seasons of game logs instead of hand-setting them,
and score them walk-forward. Both steps run entirely on data already in the repo.*

## Step 16 — EXP-030: vacated-minutes absorption + live OUT-redistribution

**Goal:** when a player is OUT, move his minutes (and a shot-share bump) to the right
teammates **the day the news breaks**, instead of waiting for the reactive EWMA to see the
box scores. This is the "Step 7 OUT-tonight / live teammate-vacated minutes → asof
features" item on the EXP-018 re-gate checklist, built as a board layer rather than a
feature (features re-fit slowly; a layer applies instantly and is separately scoreable).

**16.1 Build — the historical absorption dataset (new `src/fantasy_nba/models/absorption.py`):**
- From `player_game_logs` (17 seasons; has `TEAM_ABBREVIATION, GAME_DATE, MIN, FGA`): per
  (team, game-date), the **active set** = players in the box; the **absent-rotation set** =
  players who appeared for that team within the trailing 14 days with trailing-10-game
  MPG ≥ 15 but are not in tonight's box. (No injury feed needed for *training* — absence is
  absence; the feed matters live, where it's forward-looking.)
- Per (absent player o, active teammate j, game): `absorb_minutes = MIN_j − baseline_j`
  (baseline = trailing-10 EWMA MPG, computed strictly before the game) and
  `absorb_fga_pm = FGA_j/MIN_j − baseline`. Attribute **jointly** when several players are
  out (regress the teammate delta on the vector of vacated MPG, never pairwise-naive) and
  **exclude |margin| ≥ 25 games** from fitting (`team_game_logs` is pulled and unwired —
  this is its named first use; blowout garbage time corrupts absorption weights).
- Fit absorption weights `w(same_pos_group, depth_rank_in_pos, baseline_mpg, vacated_mpg)`
  — start with a **constrained linear model** (weights ≥ 0, Σ_j w_j ≤ 1 per out-player;
  the un-absorbed remainder is real — teams also just play smaller rotations), positions
  via `allocation.pos_group_asof`. A GBM version only if the linear one leaves measurable
  signal (rule 8 seed protocol applies the moment it's a learned model).
- **Reality anchor (write into the ledger):** the fitted tiers should land near the DFS
  folk numbers (same-pos backup absorbs the plurality; spillover 2–5 min to adjacent) —
  wild divergence means a bug, not a discovery.

**16.2 Build — the live layer (`redistribute_board`):**
- `redistribute_board(board, out_events, team_map, pos_table, weights, horizon)` → a new
  board: for each OUT player, his projected MPG × absorption weights flows to same-team
  teammates, **prorated by overlap** — `mpg_j += w_j × mpg_o × (games_j_while_o_out /
  ros_games_j)`; per-game stats recomposed via each teammate's own rates (+ the fitted
  `absorb_fga_pm` bump as an optional second mode — minutes-only is mode 1, judged first);
  re-score, re-rank. The OUT player himself keeps his `apply_status_overrides` GP cap
  (that layer already works; this one is its missing other half).
- Board needs a **team column as of T** (most recent game-log `TEAM_ABBREVIATION`) — the
  as-of board currently has none (`asof.py` carries no roster context at all).
- OUT events live = `config/overrides.yaml` + open injury spells at T; OUT events
  backtest = spells overlapping T (`injuries.build_spells`), strictly as-of. Overlap
  horizon from `out_until` when present, else the spell-duration median by severe/normal
  notes class (fit on training spells; cap 120d like `UNCLOSED_SPELL_DAYS`).
- Wire as a fourth board `"asof_redist"` in `eval_asof.py`'s boards dict (both gate mode
  and `--exp019`) — the harness is model-agnostic past that dict; `naive_board` is the
  template for a board-transforming board.

**16.3 Run + gate:**
- Cutpoint eval per EXP-019's grid, but judged on the **treated segment** — players on a
  team with ≥ 1 OUT rotation player at T (redistribution is a no-op elsewhere; aggregates
  dilute). Report: treated-segment ROS MAE + signed bias vs `asof` and `naive`;
  **untouched-segment identity** (must be exactly 0 rows moved — a leak here is a bug);
  riser recall@150 and lead-time vs the standing EXP-019 seed-0 baselines (51.7% /
  52d @ 99%; pair on the common detected set before gating on a delta).
- **Gate (adopt):** treated-segment ROS MAE improves vs `asof` with a player-clustered CI
  excluding 0, untouched segment byte-identical, lead-time not worse. On adopt: the layer
  runs inside `update_daily.py` after `apply_status_overrides`, and **the parked EXP-018
  naive gate re-arms** (this is its named re-arm condition — run that re-gate in the same
  session). On reject: log the fitted absorption table anyway (it's the Embiid-question
  answer as a *report* even if the board wiring doesn't pay).
- **Skeptic pass specifics:** (leakage) baselines and weights strictly pre-game; OUT sets
  as-of T only; (selection) treated segment defined by teammate status, not outcome;
  (concentration) check the win isn't one season's (e.g. 2023-24 load-management era).

**Ledger stub:** EXP-030 with the fitted absorption tiers table (vs the DFS folk numbers),
treated-segment results, and the EXP-018 re-gate outcome if adopted.

**Done when:** EXP-030 logged; if adopted, `update_daily.py` applies it nightly and
README's nightly section mentions the redistribution line; tracker + ROADMAP frontier
updated.

> **As completed (2026-07-11).** Built exactly to spec (`models/absorption.py`,
> `eval_asof.py --exp030`, 7 unit tests). Verdict **adopted-tentative** (rule 8's codified
> category — the decisive treated-ΔMAE CI straddles 0 on all seeds): MAE-neutral at ROS
> horizons *structurally* (median non-severe absence = 6 days → mean prorated flow
> 0.14 MPG), but treated signed bias −0.15 → −0.01 and lead-time +5–8 days, consistent
> across all 4 seasons × 3 seeds; untouched rows byte-identical (0 mismatches ×3). Fitted
> tiers passed the reality anchor (same-pos 2× cross-pos, headroom ordering; ~17/30
> absorbed collectively). Nightly wiring live (fault-isolated, `--no-redist`, `redist_mpg`
> audit column, per-season weight cache); offline dry-run clean. **The EXP-018 naive gate
> re-ran and stays parked** (1/4 · 2/4 · 2/4 seasons at ≥2/3 cutpoints vs 3/4 needed;
> 2025-26 leans model — recheck post-2026-27). April 2027 re-affirm must score **short
> horizons** (next-14-day windows from the nightly archives), not ROS ΔMAE (settled
> neutral; ledger note bans re-litigating it).

## Step 17 — EXP-031: budget-reconciled minutes (allocation v2)

**Goal:** impose the 240-minute identity on the *preseason* board the honest way — MPG
stays the regression target (the stable quantity); the budget becomes a **diagnostic and a
soft correction**, with GP entering only as a bounded multiplicative weight, never a
divisor.

**17.1 The diagnostic first (cheap, decides everything):** on the honest Oct-1 rosters
(`preseason_roster_map`), per target team compute the model's implied budget
`B_team = Σ_i mpg_i × (gp_i/82) × 82 / (240 × 82)` over modeled players + the unmodeled
reserve (reuse `allocation.rookie_reserve`, train-slice only — critique §2.8). Publish the
distribution of `B_team` per season: the breakthrough plan claimed "teams silently sum to
260+"; **measure it**. If overshoot is small or uncorrelated with that team's players'
minutes errors, sub-step (b) is dead on arrival and the ledger says so for ~an hour's work.
- *Correlation check that matters:* per team, `B_team − 1` vs the mean signed minutes
  error of its players. No correlation ⇒ the constraint isn't where the error lives.

**17.2 (a) Depth-chart features into the MPG regression** — the ledger-sanctioned re-entry
(EXP-014 note: "a *feature* experiment, not a target change"). Add `ALLOC_FEATURES`
(`own_prev_share`, `same_pos_returning_share`, `same_pos_vacated_share`, `depth_rank`,
`n_same_pos`, `pf_per_min`) to the **y_mpg model only**, honest Oct-1 map, variant
`learned_depth`. Rule-11 hygiene (permutation importance, |ρ| sweep vs EXP-016b's group —
`same_pos_vacated_share` vs `vac_min_share_pos` will be near-duplicates; justify or drop).

**17.3 (b) Soft budget reconciliation** — post-hoc, on whichever of {control, (a)} wins:
`mpg_i ← mpg_i × f_team^λ` where `f_team = (1 − reserve) / B_team`, λ tuned on training
folds only (λ ∈ {0, 0.25, 0.5, 1}; λ=0 is the control), and the correction applied in
**headroom space** (scale `mpg` toward/away from a 40-min cap proportionally to
`40 − mpg`) so 36-minute stars move less than 18-minute fringe — the direct answer to
EXP-014's "proportional normalization taxes stars" failure.

**17.4 Gate:** minutes MAE ≤ control **and** the role-change segments (team-changers,
high-turnover teams — EXP-014's segment definitions) improve ≥ 10% with the rest ≤ 2%
worse, judged under rule 8 + clustered CI. **Expectations bounded and written down
up front:** the preseason reducible gap is ≈ 0 (EXP-011) and the selection-floor memory
stands — this step is judged on **minutes MAE and recall**, never on chasing preseason
riser bias. On reject: the diagnostic table still ships (it's the standing answer to "does
the budget bind?") and the constraint's live home remains Step 16, where the active roster
is known.

**Ledger stub:** EXP-031 with the 17.1 diagnostic distribution, (a)/(b) sub-results, and
the explicit EXP-014 contrast line (what changed vs what was banned).

**Done when:** EXP-031 logged adopt/reject; tracker + ROADMAP updated; any adopted mode
becomes a `project_models` default with a Step-2 floor recompute.

> **As completed (2026-07-11).** Built to spec (`allocation.depth_feature_table` /
> `budget_table` / `reconcile_minutes`, variant `learned_depth`, `scripts/eval_budget.py`;
> 3 unit tests). **The 17.1 diagnostic is the keeper**: overshoot confirmed (mean B_team
> 1.06–1.08× of full supply vs the 0.89 target; pooled +0.176, p90 +0.33) and error-linked
> (corr +0.24…+0.52 every season, pooled +0.381/120 team-seasons) — sub-step (b) survived
> its kill test. **Both cures rejected under rule 8** (seeds {0,1,2}): (a) minutes-MAE
> delta flips sign across seeds, moved −4.7% vs the −10% bar, rest degrades +3.5%, and the
> mover CI shows a uniform downward bias shift deepening the big-riser hole (−0.70, CI
> excludes 0 — the EXP-013d pathology); (b) λ*=0.25 stable and tuning-fold-real but
> eval-window MAE sub-noise (−0.011, spread 0.024), segments −0.5%; its one consistent
> effect is pool minutes bias +0.84→+0.30. **The Phase-5 lesson, seen twice:** constraint
> information centers minutes errors without shrinking them at season horizons. Re-arms in
> the ledger note (total-based decisions; re-run the diagnostic each adopted-model change;
> bias-sensitive consumers like the EXP-021 re-arm).

*Ordering note: 16 before 17 (higher expected return; its fitted absorption weights are
also 17's best prior on who inherits vacated minutes). Both are build-now and must not
displace the standing calendar (mid-Aug schedule pull → Sept market → mid-Oct analyst
pass/dual freeze → opening-night cron).*

---

# PHASE 6 — the analyst layer, operationalized (Step 18, added 2026-07-12)

*Context: the BBM-transcript analyst layer (workflow v2, EXP-029 amended) applies a **static**
`fpts_delta` on top of the nightly ROS board. Preseason and early-season that delta is pure
signal — the model can't see a role change from box scores it doesn't have yet. But
`update_daily.py` re-projects the model every night, and its EWMA form features **learn the
role** as games accumulate. Once the model's own base has risen to reflect (say) a player's
new starter minutes, the static commentary delta is still stacked on top → **double-counting**.
The role/hype deltas are "bridge the model until it can see for itself"; they must taper as the
model catches up. This step makes that lifecycle explicit instead of relying only on the manual
mid-Oct re-review. (Injury/availability facts are exempt — those are handled by
`config/overrides.yaml` availability caps + EXP-030 redistribution, not fpts_deltas, and don't
decay.)*

## Step 18 — analyst-delta staleness flag + optional decay

**Goal:** stop stale role/hype deltas from double-counting once the in-season model has
absorbed the role; surface it on the nightly board; optionally auto-taper.

**18.1 Staleness flag (diagnostic first — build this half, default-on as a *report*).**
In `update_daily.py` (or a helper `models/analyst.py::staleness`), for each moved player
compare the **model's current pre-analyst base `fpts_pg`** against the model's base **at the
override's `date`** (recover the latter from the frozen preseason board A, or the earliest
`ros_board/` snapshot on/after the entry date). If the base has risen by ≥ the delta's
magnitude (the model has "caught up"), set `analyst_stale=True` + a note on the board row and
print a "consider retiring" report line. No projection change — it's a nudge to post a
later-dated `none`/reduced entry. **Acceptance:** on a handful of in-season `--asof` dates,
the flag fires on players whose realized role the EWMA has clearly priced (spot-check the
named cases into a short ledger note; this is operational, not a backtest gate).

**18.2 Optional category-aware decay (build behind `--analyst-decay`, off by default).**
Scale each *role/hype* delta by `decay(games_so_far)` — full for the first
`DECAY_FULL_GAMES` (~10), linear taper to 0 by `DECAY_ZERO_GAMES` (~30, where the EWMA's role
signal is reliable); `other`/`injury` categories stay full-strength. Apply inside the analyst
layer before scoring; add a `analyst_decay_factor` audit column. **Validate before defaulting
it on:** the taper shape is a hyperparameter — show, on 2–3 in-season dates, that decayed
board B tracks realized ROS at least as well as the full-delta board B on the moved players
(reuse the `eval_asof` treated-segment machinery from EXP-030). Only then flip the default.

**18.3 Doc-sync:** README `update_daily`/`apply_proposals` lines; the transcripts README
lifecycle note ("role/hype deltas are bridges — retire or let them decay as the model learns");
this tracker + a one-line EXP-029 ledger addendum recording 18.1's spot-checks.

**Done when:** the staleness report ships in `update_daily.py` (and prints in the offline
dry-run); decay exists behind its flag with the validation note written; a fresh session can
run 18.1 end-to-end from this spec. *Ordering: 18.1 before 18.2 — the flag is cheap and
immediately useful; decay is only worth defaulting on if 18.1 shows staleness is common.*

---

# PHASE 7 — the draft room (Step 19, added 2026-07-15)

*Context (user, 2026-07-15): every artefact in this repo ends at "here is a board." Nothing
helps during the three hours that decide the season. The gap named: link the **live ESPN
draft** so picks remove players and re-order the remainder in real time; read **what all ten
teams have taken** to surface roster construction — at the base level positional spread, at
the useful level risk/volatility concentration and what to target next.*

*Calendar: the draft is ~Oct; the mid-Oct dual freeze (D2.3 / rule 10a) is the hard deadline.
This is a **product** step — no experiment gate, no ledger entry — with one exception: 19.4
builds a new variance layer and carries a real calibration gate, because it is the one place
this feature can be confidently wrong.*

> ### ⚠ SCOPE: 19.4–19.6 descoped 2026-07-16 (user decision) — read before building them
>
> The user's call, once the cost of an honest H2H simulator was clear: *"I don't think the
> insight layer is needed, maybe just a view of my current team composition and others."*
> **19.1–19.3 + 19.7 shipped; the variance layer (19.4), the week-win simulator (19.5) and the
> prescriptive shortlist (19.6) are NOT built.** Their specs stay below, unchanged, as the
> re-arm.
>
> This is the same shape as the "if 19.4's gate fails" fallback the step already specced — so
> it is a deliberate ship, not a shortcut. What the room does instead: reports **composition**
> (slot feasibility from real ESPN eligibility, chronic-injury counts, the board's own
> p10/median) and lets a human decide. It does **not** answer "should I take the lower-spread
> player" — that needs the simulator, and the honest answer is format-dependent anyway
> (variance helps an underdog, hurts a contender), so inventing a number would have been
> worse than the silence.
>
> **If 19.4 is ever re-armed, the two hard-won constraints still stand:** `SD_PG=9` is
> season-total-calibrated and must never be a per-game sigma; injuries must be sampled as
> contiguous spells. Nothing shipped depends on either.

*Scope decisions (user, 2026-07-15): (a) build the H2H week-win simulator now rather than
shipping descriptive risk columns first — **reversed 2026-07-16, see the scope box above**;
(b) ESPN access — **superseded the same day**: the
user supplied league 507458037 and cookies, and the probe (19.1) verified the endpoint, the
pick schema, the ID join, and `eligibleSlots` against three completed drafts. **The league is
already live at season 2027**, so `EspnPollFeed` is a real build, not a stub. The only ESPN
unknown left is live-draft polling latency (October mock draft).*

## Step 19 — live draft room

### 19.1 The feed adapter (isolate the unknown)

**Endpoint — VERIFIED 2026-07-15 against a real league (id 507458037), do not "correct" this
back:**
```
https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{id}?view=mDraftDetail
```
`season` is the season's **ending** year (2026-27 → `2027`). Private leagues need `espn_s2` +
`SWID` cookies.

⚠ **The old host `fantasy.espn.com/apis/v3/...` is dead and fails in the worst possible way:
it returns HTTP 200 with the SPA's HTML.** A client checking `status_code == 200` will think
it succeeded and then fail on the parse. **Therefore: never treat 200 as success — assert
`content-type` starts with `application/json` and raise a loud, named error otherwise.** The
live host returns well-formed JSON errors (verified: `401 {"messages":["You are not
authorized to view this League."]}` without cookies), so real failures are legible.

**Probe results — league 507458037, run 2026-07-15 with the user's cookies. These are
measured facts, not assumptions:**

| season | name | drafted | inProgress | picks | **real** picks | size | scoringType |
|---|---|---|---|---|---|---|---|
| 2027 | My 2025 League | False | False | 130 | **0** | 10 | H2H_POINTS |
| 2026 | My 2025 League | False | False | 130 | **0** | 10 | H2H_POINTS |
| 2025 | My 2025 League | True | False | 130 | 130 | 10 | H2H_POINTS |
| 2024 | My 2024 League | True | False | 130 | 130 | 10 | H2H_POINTS |
| 2023 | My 2023 League | True | False | 104 | 104 | 8 | H2H_POINTS |

**The league is LIVE at season 2027** — this *is* the 2026-27 league; it rolls forward and is
already provisioned (10 teams, H2H_POINTS, 130 picks = 10 × 13 rounds). So `EspnPollFeed` can
be developed against the real league now, and **2023/2024/2025 are three completed drafts** to
build fixtures from and test the ID join against. `size=10` + `scoringType=H2H_POINTS`
independently confirm `league.yaml`. 130 = 10 × 13 confirms 13 *drafted* slots (league.yaml's
14th is IR, which isn't drafted).

⚠ **TRAP — ESPN pre-allocates placeholder picks.** An undrafted season returns a **full
130-pick array** whose entries carry `playerId = -1`. A `poll()` that diffs on `len(picks)`
would conclude the draft is complete *before it starts*. **The feed MUST filter
`playerId > 0`**, and read draft state from the `drafted` / `inProgress` flags — never from
the pick count.

⚠ **TRAP — `teamId` is NOT a contiguous 1..N index.** In the 10-team 2025 draft, the team
making overall pick 1 has `teamId = 15`. Do **not** derive snake order or team position from
`league["teams"]`; read the actual order off the picks. `DraftState.picks_until_next()` must be
built from observed `teamId`s, not an assumed range.

**Verified pick schema** (`draftDetail.picks[]`): `overallPickNumber, roundId, roundPickNumber,
teamId, playerId, keeper, reservedForKeeper, lineupSlotId, autoDraftTypeId, bidAmount,
nominatingTeamId, tradeLocked`. (`bidAmount`/`nominatingTeamId` ⇒ auction leagues share this
schema; ours is a snake — ignore them.)

**Still unverified — the load-bearing one:** whether `mDraftDetail` updates with usable latency
*during* a live draft (ESPN's draft room uses its own real-time channel). The `inProgress` flag
existing is encouraging but proves nothing about refresh rate. Only an October mock draft
answers it. `ManualFeed` remains the shipped default until it does.

**2026-09-23 mock-room connection check:** a random mock draft URL's `leagueId=19350273`,
`seasonId=2027`, and `teamId=8` connected successfully through the same `mDraftDetail` league
endpoint (12 teams, real snake order, scheduled, 30-second clock). No room code or `memberId`
was needed. The mock league was deleted by ESPN shortly after the room closed, so these ids are
ephemeral; `/room` now accepts the full live URL and atomically connects, selects the user's team,
and starts polling. This verifies discovery/connection, **not live pick latency**; the mock-draft
latency rung remains open until picks are observed while a room is in progress.

Build a narrow adapter so the unknown stays in one file:
```python
# src/fantasy_nba/draft/feed.py
@dataclass(frozen=True)
class Pick:
    overall: int; team_id: int; espn_player_id: int; keeper: bool = False

class DraftFeed(Protocol):
    def poll(self) -> list[Pick]: ...   # full pick list to date; caller diffs. Idempotent.
```
Three implementations: `ManualFeed` (picks entered in the UI — **the default and the
draft-night fallback**; always works), `EspnPollFeed` (the poller — **credentials verified
2026-07-15, build it for real**), `FixtureFeed` (replays a recorded JSON payload — how the
tests run).

**Auth:** `espn_s2` + `SWID` read from `.env` (gitignored) or the environment — never from
`config/`, which is committed. Never log them; scrub them from any recorded fixture.

**Why manual is not a consolation prize:** it makes 19.3–19.6 testable with no live draft, and
it is what saves the draft night if the poller turns out to be laggy.

**Verification ladder:** (1) `FixtureFeed` + unit tests — *pending*; (2) **completed past draft
— ✅ DONE 2026-07-15**, see the probe table below: schema, ID join, and `eligibleSlots` all
validated against the 2025 league with no live-draft dependency; (3) an ESPN **mock draft in
early Oct** — *pending, and the only thing that can answer the latency question*. Record raw
payloads to `tests/fixtures/espn_draft_*.json` as you go (cookies scrubbed).

### 19.1b ⚠ The October re-verification sweep — **everything below is a snapshot that drifts**

*User, 2026-07-15: "the league id and draft order and teams likely will change as new people
are joining." Confirmed in the data the same day, so this is a standing instruction, not a
caveat.* Every ESPN fact in this step was measured on **2026-07-15** against a league that had
not yet drafted. **Nothing here may be trusted on draft day without re-reading it live.**

**What is known to drift, and the evidence:**

| Fact | Why it drifts | Detect it |
|---|---|---|
| **`pickOrder`** | ESPN seeds it with **sorted team ids** and randomizes shortly before the draft. Season 2027 reads `[1, 3, 8, 9, …, 15]` (sorted ⇒ **not yet drawn**); the played 2025 season reads `[15, 11, 13, 14, 8, 9, 1, 12, 3, 10]` (drawn). | `LeagueSettings.order_is_placeholder` |
| **league id** | A fresh league for new members ⇒ a new id; 507458037 is only *this* league rolled forward. | `ESPN_LEAGUE_ID` in `.env` — never hardcode |
| **team ids / count** | New members change both; ids are non-contiguous, so a resize is not a range change. | `EspnPollFeed.team_ids()` / `LeagueSettings.size` |
| **roster slots** | Settings are editable until the draft. | `LeagueSettings.slot_counts` |
| **draft date** | `None` until scheduled (2027 today) vs epoch-ms once set (2025). | `LeagueSettings.is_scheduled` |
| **cookies** | ESPN sessions expire. | a 401 ⇒ re-harvest, do **not** conclude the league is gone |

**The standing rule: ESPN is the authority, `config/league.yaml` is the fallback.** Read
`league_settings()` live and use `slot_counts` as `league["roster"]` and `size` as
`league["teams"]`. (They matched exactly on 2026-07-15, which is a *checkable* fact, not a
permanent one — `test_espn_settings_are_drop_in_for_league_yaml` fails loudly if they diverge,
which is the desired behaviour: it means the league changed and the config is stale.)

**Never cache `pick_order`.** A cached order is *worse than none*: `picks_until_next()` returns
`None` without one (honest — survival probability must not key off a fabricated number), but a
stale order returns confident nonsense all night.

**The mid-Oct sweep checklist (run in this order):**
1. Re-harvest `espn_s2` / `SWID`; confirm `ESPN_LEAGUE_ID` is *this season's* league.
2. `league_settings()` → assert `size` + `slot_counts` still match `league.yaml`; if not,
   **update `league.yaml`, then recompute VOR** — replacement level is a direct function of
   `teams × starting slots`, so a 10 → 12 team league re-prices the entire board.
3. `team_ids()` → confirm count == `size`.
4. Confirm `order_is_placeholder` is still `True`; if the draw has happened, capture the real
   order — **and re-read it again on draft day.**
5. Run an ESPN **mock draft** — the only thing that answers the polling-latency question
   (rung 3 of the ladder). Record payloads to `tests/fixtures/` (cookies scrubbed).

### 19.2 ID join + slot eligibility

ESPN player IDs ≠ NBA stats `PLAYER_ID`. Join on name via the existing alias-hardened path
(`models/injuries.py::ALIASES`, the `pull_market.py` pattern). Cache the resolved map to
`data/processed/espn_player_map.parquet`.

**Player universe endpoint — VERIFIED 2026-07-15.** Names + `eligibleSlots` come from
`?view=kona_player_info` **with an `X-Fantasy-Filter` JSON header** (NOT `mRoster`, which is
empty on an undrafted season):
```python
flt = {"players": {"limit": 400, "sortPercOwned": {"sortAsc": False, "sortPriority": 1}}}
requests.get(base, params={"view": "kona_player_info"},
             headers={"X-Fantasy-Filter": json.dumps(flt)}, cookies=ck)   # -> 400 players
```
**`eligibleSlots` confirmed real and genuinely multi-slot** — Edwards `[SG, SF]`, Harden
`[PG, SG]`, Giannis `[PF, C]`, Jokić `[C]`. Slot id map: `0 PG · 1 SG · 2 SF · 3 PF · 4 C ·
5 G · 6 F · 7 SG/SF · 8 G/F · 9 PF/C · 10 F/C · 11 UTIL · 12 BE · 13 IR` (filter to 0–4 for
the true position set). This closes the platform-eligibility hole
[`models/value.py`](../src/fantasy_nba/models/value.py) parks (§9.7) with ESPN's own answer;
fall back to the guard/big grouping only when a player is unmatched.

**Name normalization — measured, don't guess.** ESPN writes ASCII (`"Nikola Jokic"`); our
stats carry diacritics (`"Nikola Jokić"`). Normalize **NFKD → strip non-ASCII → lowercase →
drop `.`/`'` → drop Jr/Sr/II/III/IV suffixes**, then apply `ALIASES`. Measured on the 2025
league: **387/400 = 96.8%**, with Jokić → `203999` and Dončić → `1629029` correct.

**The 13 misses are correct behaviour, not join failures** — Bojan Bogdanović, Derrick Rose,
Blake Griffin, Andre Iguodala, Saddiq Bey, Nikola Topić, Tacko Fall … i.e. retirees and
players with **no season row at all** (Bey/Topić missed 2024-25 injured). ESPN's universe is
wider than our stats cache by construction.

⇒ **Refines the hard-fail rule:** hard-fail loudly on any name that is **on our board / has a
stats row** but doesn't resolve — never a silent guess. An ESPN player with no NBA season row
is a legitimate non-match: record it as `unmatched` and drop it, never fabricate an ID. A blunt
"hard-fail on any unmatched top-200 name" would fire constantly on retirees and be turned off
within a day — which is how a real guard rots.

### 19.3 Live board + dynamic replacement level

> **⚠ Verdict after building it (2026-07-16): this step's central premise is WRONG. The code
> ships with the claim retracted; keep the step, drop the premise.**
>
> The premise below: static VOR barely reorders, but *live* VOR will, because its unknowns
> collapse. Measured on the real league + the shipped board — `spearman(live_vor, fpts_pg)`:
>
> | picks made | 0 | 40 | 80 | 110 | 125 |
> |---|---|---|---|---|---|
> | spearman | 0.995 | 0.994 | 0.992 | 0.991 | **0.943** |
> | top-20 disagreements | 2 | 3 | 1 | 2 | **9** |
>
> Live VOR ranks ~identically to plain fpts/g for ~110 of 130 picks and only earns anything in
> the **endgame**. `value.py`'s standing caveat held; going live did not escape it.
>
> **Mechanism (surfaced by the user asking how a PF/C is handled): multi-eligibility.** 201 of
> 353 ESPN players fill 2+ slots, so a slot is almost never truly scarce — per-slot
> replacement spread ≈ **2.3 fpts/g**. Multi-eligibility *flattens* positional scarcity; an
> earlier claim here that it created a C-26.7/PF-34.9 spread was an artefact of the
> first-unseated bug (below), not a finding.
>
> Per `value.py`'s own instruction ("if it barely reorders the board, the sanity report says so
> and the column ships informational"), **`live_vor` ships informational.** What the room is
> actually worth: (1) drafted players leave the board; (2) **slot feasibility** — what you can
> no longer fill, orthogonal to value, and the honest form of "do I have too many guards";
> (3) live VOR in the last rounds.

Removing drafted players and re-ranking is trivial (the board is already ranked and tiered).
The original bet was that **replacement level recomputed after every pick** would be the part
that earns its keep — see the retraction above.

`value.replacement_level` today greedily fills a hypothetical league; the module's own
docstring concedes that in a one-dimension points league with 3 UTIL slots, VOR ends up
"close to a monotone transform of fpts/g." Live, both unknowns collapse: you know exactly who
is gone and exactly which slots each of the 10 teams still needs. Add:
```python
# src/fantasy_nba/draft/live.py
@dataclass
class DraftState:
    """The single source of truth the API and every 19.5/19.6 call read. Rebuildable from
    the pick list alone — so undo is just `picks.pop()` + rebuild, never mutation-in-place."""
    picks: list[Pick]                    # in overall order
    my_team_id: int
    league: dict                         # value.load_league()
    eligible_of: dict[int, set[str]]     # PLAYER_ID -> ESPN slots (19.2)

    @property
    def drafted(self) -> set[int]: ...           # PLAYER_IDs
    @property
    def rosters(self) -> dict[int, list[int]]: ...  # team_id -> [PLAYER_ID], all 10 teams
    def picks_until_next(self) -> int: ...        # snake order from league["teams"]

def live_replacement(state: DraftState, board: pd.DataFrame) -> dict[str, float]:
    """Replacement per slot from the ACTUAL remaining pool and the ACTUAL remaining
    starting-slot demand across all teams. Reuses value._slot_counts; the greedy fill
    starts from the real draft state, not an empty league."""
```
Recompute on each pick (cheap — a sort over ≤ ~500 rows). This is what stops VOR being a
restatement of fpts/g, and it is the backbone of 19.6.

### 19.4 The weekly variance layer ⚠ **the one place this can be confidently wrong**

**The trap (verified 2026-07-15):** `uncertainty.SD_PG = 9.0` is documented at its definition
as *"NOT just the ~5.6 per-game projection RMSE — it's tuned so the resulting season-total
p10–p90 band covers ~80%... it also absorbs... season-wide common health shocks that move a
whole cohort together."* It is deliberately ~60% wider than the honest per-game marginal
because it is doing a **season-total** job, and EXP-021 re-affirmed that excess width as
load-bearing *for that job*. **Passing `SD_PG` into a weekly sim as a per-game sigma would
inflate weekly variance, drive every matchup toward a coin flip, and produce a sim that says
roster construction doesn't matter.** Do not do it.

A weekly sim needs two variance components that `SD_PG` conflates, because they behave
completely differently across a season:

| Component | Source | Drawn | Behaviour |
|---|---|---|---|
| `σ_level` — uncertainty about the player's *true* fpts/g | walk-forward model residuals (~5.6) | **once per season**, persists every week | does **not** diversify — this is what actually decides your season |
| `σ_game` — game-to-game scatter around his own mean | **empirical, from `player_game_logs`** (16 seasons, 404k rows, cached) | **per game** | diversifies across ~35 player-games/week — mostly washes out |

**Reuse note (respects the ledger — this is not re-running a rejected experiment):** EXP-021
built exactly the honest per-game marginal we need here — `quantiles.pg_quantile_frame` /
`uncertainty.residual_pool` / `calibrate_resid_scale` — and it was rejected *because* it was
honest: too narrow for the season-total job `SD_PG` was doing. For `σ_level` the honest
marginal is precisely correct, because here the season-level covariance is modeled
**explicitly** (below) instead of being smuggled into a width. The rejected artefact has a
real home; the EXP-021 verdict stands untouched for the season board.

**Build — `src/fantasy_nba/draft/variance.py`. The three pieces bundle into one object the
sim takes, so the layer is swappable and the gate has something to hold:**
```python
@dataclass(frozen=True)
class VarianceLayer:
    sigma_game: pd.Series      # PLAYER_ID -> float, shrunk (piece 1)
    level_cdf: np.ndarray      # the EXP-021 empirical residual CDF grid (piece 2)
    spell_pools: dict          # (age_bucket, chronic_flag) -> empirical (count, length) (piece 3)

    def draw_levels(self, board, n_draws, rng) -> np.ndarray:   # (n_draws, n_players)
    def draw_availability(self, board, n_weeks, n_draws, rng) -> np.ndarray:  # (n_draws, n_players, n_weeks) mask

def build_variance_layer(game_logs, season_stats, bio, spells, cfg,
                         as_of: str) -> VarianceLayer:
    """as_of gates every input (Oct 1 of the target season preseason) — the same no-leakage
    contract as every other feature module here."""
```
1. `game_sd_table(game_logs, cfg)` — per (player, season) empirical SD of per-game fantasy
   points, shrunk toward a **minutes-conditional league curve** by sample size (a 12-game
   sample's raw SD is noise). Returns `σ_game` per PLAYER_ID.
2. `level_draw(...)` — `σ_level` from `residual_pool` (the EXP-021 CDF, empirical shape, no
   width inflation).
3. **Availability as contiguous spells, not random game-misses.** `injuries.build_spells`
   already yields `(start, end, days)` per absence. Sample spell **count and length** from
   the empirical distribution bucketed by (age × chronic) — the same pools EXP-015b adopted —
   and lay them on the calendar. This is the whole reason H2H differs from season totals: an
   injury takes out six *consecutive* weeks, it does not sprinkle absences uniformly. A sim
   that drops games at random would badly understate how injuries actually lose you matchups.

**Calibration gate (this sub-step is not "done" until this passes). Follow this protocol
exactly — it is the decision gate for the whole feature, so it must be reproducible:**

```python
# scripts/eval_draft_sim.py  (new; the 19.4 gate + the 19.5 sanity prints)
#   python scripts/eval_draft_sim.py --seasons 2024-25 2025-26 --n-rosters 200 --seed 0
```
1. **Roster construction (deterministic, seeded).** For each eval season, take the *board the
   model would have had* — `project_learned` trained on prior seasons only (the
   `backtest.project_models` no-leakage path; **never** the eval season's data). Draw
   `--n-rosters` (default 200) rosters of 13 from the top 150 by **snake-draft simulation**
   over 10 teams with `rng(seed)` jitter on board order (σ = 8 ranks) — not uniform random.
   Rationale: uniform-random rosters are not the population we advise on; a real roster is
   rank-correlated, which is exactly the regime the coverage claim has to hold in.
2. **Weeks.** Use `pull_schedule.py`'s per-team weekly counts for that season; score fantasy
   weeks 1..`league_end` (the `league.yaml` cut, **not** the NBA finale — the D1.3b rule).
3. **Predict.** Simulate each roster's weekly totals with the 19.4 layer (`n_draws=2000`),
   from prior-season-only projections. Emit p10/p50/p90 per (roster, week).
4. **Realize.** Compute each roster's **actual** weekly total from that season's
   `player_game_logs` scored through `load_scoring()`, applying the same v1 lineup
   simplification as 19.5 (start the best available by projected value each day) so predicted
   and realized are the same estimand. **This is the step to get right** — a coverage number
   comparing two different estimands is meaningless.
5. **Report.** Pooled coverage = fraction of realized weekly totals inside [p10, p90], plus a
   breakdown **by week-of-season** and **by roster strength tercile**. Also print p25–p75.

**Gate: pooled p10–p90 coverage ∈ [78, 88]%** — the same window EXP-015b/021 are judged in —
**and** no strength tercile outside [72, 92]% (a sim that only calibrates on average is not
safe to advise a specific roster). Judged under rule 8 (seeds {0,1,2}; the claim must survive
the spread). If it fails: 19.5–19.6 **do not ship**, 19.3 ships alone, and the risk layer
falls back to descriptive columns (chronic-flag / high-`risk` counts vs the league, no
fabricated team-variance number). Write the coverage table into a short note under this
step — operational, not a ledger entry.

**Skeptic pass (rule 4) — answer these in the note before claiming the gate passed:** (a) is
any input to `σ_game`, `σ_level`, or the spell pools dated on/after the eval season's Oct 1?
(b) does roster construction select on realized outcomes? (c) is the coverage carried by one
season or one tercile?

### 19.5 The H2H week-win simulator

Per sim draw of a season: draw each player's `σ_level` once → draw injury spells → per fantasy
week, per player, `games_that_week` (from `pull_schedule.py`'s per-team weekly counts) × draws
of `mu_i + N(0, σ_game_i)` → roster weekly total → compare vs opponent's → win/loss. Aggregate
over ~20 weeks × 9 opponents × N draws → **expected weeks won**, the headline number.

**Build — `src/fantasy_nba/draft/sim.py`:**
```python
N_DRAWS = 2000          # gate-validated default; the advice path (19.6) may drop to 500
@dataclass(frozen=True)
class SimResult:
    weeks_won: float            # expected, out of the scored weeks
    weeks_won_p10: float; weeks_won_p90: float
    weekly_p10: float; weekly_p50: float; weekly_p90: float
    playoff_odds: float         # P(top-N by weeks won); N from league.yaml when set, else 4

def simulate_season(rosters: dict[int, list[int]],   # team_id -> [PLAYER_ID]; all 10 teams
                    board: pd.DataFrame,             # needs PLAYER_ID, fpts_pg
                    schedule: pd.DataFrame,          # pull_schedule.py output, same season
                    league: dict,                    # value.load_league()
                    var: VarianceLayer,              # the 19.4 object
                    n_draws: int = N_DRAWS,
                    seed: int = 0) -> dict[int, SimResult]:
    """Expected weeks won per team. Vectorized over draws (n_draws x n_players), never a
    Python loop per draw — 19.6 re-runs this ~15x per pick and must stay interactive."""
```
**Performance budget (a hard requirement, not a nice-to-have):** one `simulate_season` at
`n_draws=500` must return in **< 300 ms** — 19.6 calls it per candidate while you are on the
clock. Draw arrays are `(n_draws, n_players)` float32; spells are pre-sampled once per draw
into a `(n_draws, n_players, n_weeks)` availability mask. If the budget is missed, cut
`n_draws` before cutting the spell model — spell structure is the thing that makes this
better than a season-total number.

**Two simplifications that must be stated in the UI, not buried:**
- *Daily lineups.* You start ~10 of 13 daily with no weekly games cap (`league.yaml`), so
  bench-loss is modest but not zero. v1 = start the best available by projected value each
  day; do **not** attempt full daily lineup optimization inside the sim.
- *Waivers.* An injured player is partially backfilled by a streamed replacement. Ignoring
  this overstates injury damage — v1 backfills at the 19.3 live replacement level, which is
  the right number and is already computed.

**Schedule vintage (corrected 2026-07-15):** the schedule is **not** a blocker.
`pull_schedule.py` is season-stamped and already derives per-team games-per-week; that
*structure* is stable year over year, so the 2025-26 vintage is a sound stand-in for
expected-weeks-won at draft altitude. Only **fantasy-playoff-week** planning is genuinely
vintage-sensitive (and `league.yaml`'s `fantasy_playoff_weeks` is already a flagged
placeholder). Re-run the pull mid-Aug and the numbers refresh — a re-run, not a rewrite.

**Opponents:** mid-draft this is a real strength — you know exactly what the other nine teams
have taken. Pre-draft, seed opponent rosters from ADP.

### 19.6 Slot feasibility + the recommendation

State the user's "too many guards" question correctly: not a **count**, a **feasibility**
question. With `eligibleSlots`, run a bipartite matching — can this roster legally fill all
10 starting slots? Which slot is closest to unfillable?

The recommendation combines three things that are all now real numbers: **live VOR** (19.3),
**survival** — `P(player lasts until my next pick)` from ADP and picks-to-next-turn — and
**Δ expected weeks won** from adding each candidate (19.5, re-simulated for the top ~15
candidates only; full-board re-sim per pick is too slow). Output is a ranked shortlist with
the reason attached, e.g. *"Center replacement falls 6 fpts/g in the next 14 picks and your
only C-eligible player is X"* — never a bare number.

**Build — `src/fantasy_nba/draft/advice.py`:**
```python
SHORTLIST_N = 15        # candidates re-simulated per pick (the interactivity budget)
ADVICE_DRAWS = 500      # n_draws for the per-candidate sims; the gate ran at 2000

def slot_feasibility(roster: list[int], eligible_of: dict[int, set[str]],
                     league: dict) -> dict:
    """Max bipartite matching (Hopcroft-Karp or nx.max_weight_matching) of roster players ->
    starting slots. Returns {filled: int, unfillable: list[str], binding: str | None} where
    `binding` = the slot that fails first if you add nobody eligible for it. This is the
    honest form of 'do I have too many guards'."""

def survival_prob(adp: float, picks_until_next: int, sigma: float = 6.0) -> float:
    """P(player is still there at my next pick) = 1 - Phi((picks_until_next - (adp - pick_now))
    / sigma). sigma is ADP noise; 6.0 is a starting value -- calibrate against the archived
    FantasyPros ADP vs realized draft slots once one real draft is recorded (a named re-arm,
    not a claim)."""

def recommend(state: DraftState, board: pd.DataFrame, var: VarianceLayer,
              n: int = SHORTLIST_N) -> list[Recommendation]:
    """Ranked shortlist. Each Recommendation carries `player_id, d_weeks_won, live_vor,
    survival, binding_slot, reason: str`. Candidates = top `n` by live VOR among undrafted;
    `d_weeks_won` = simulate_season(my roster + candidate) - simulate_season(my roster),
    SHARED RNG SEED across the two calls so the difference is signal and not draw noise."""
```
The shared-seed detail is load-bearing: with independent seeds, `d_weeks_won` for two similar
candidates is dominated by Monte-Carlo noise and the shortlist reorders randomly between
refreshes. Use common random numbers.

**Tests (rule 6 — `tests/test_draft.py`, synthetic, no network):** `slot_feasibility` on a
hand-built roster with a known unfillable slot; `survival_prob` monotone in
`picks_until_next`; `live_replacement` rises as the pool drains; `FixtureFeed` → pick diffing
is idempotent (polling twice yields no duplicate picks); `simulate_season` determinism under a
fixed seed; the ID join hard-fails on an unmatched top-200 name.

**Standing caveat to surface in the UI (user's framing needs this correction):** in weekly
H2H, roster variance is **not** simply bad — it is bad for a strong roster and *good* for a
weak one, which needs variance to steal weeks. "Get someone with a lower spread" is sound
advice for a contender and wrong for an underdog. The sim already knows which one you are;
let expected-weeks-won carry the recommendation rather than a variance rule of thumb.

### 19.7 API + frontend

- `src/fantasy_nba/api/draft.py`: `GET /api/draft/state`, `POST /api/draft/pick` (manual),
  `POST /api/draft/undo` (misclicks happen and the draft does not pause), `GET
  /api/draft/advice`. Poll from the client; no websockets in v1.
- `frontend/src/views/DraftRoom.tsx`: the live board (drafted struck out), my roster with slot
  feasibility, the shortlist with reasons, expected-weeks-won, and a league-wide picks feed.
  Register it in `frontend/src/App.tsx` alongside the existing views (DraftBoard / Ros /
  Player / Compare / Analyst / DataBrowser) and reuse `components/DataTable.tsx` +
  `lib/api.ts` rather than introducing a second table implementation.
  Draft-night UX rules: **large hit targets, undo always visible, never block on a network
  call** — if the ESPN poller stalls, the manual path must still take the pick instantly.

### 19.8 Doc sync

README (layout + a "Draft room" section under Web app), ROADMAP (a Stage-5 delivery line),
this tracker. No `EXPERIMENTS.md` entry — product step; 19.4's coverage table goes in a note
under this step.

**Done when:** a full mock draft can be run end-to-end through `ManualFeed` with the board
re-ordering, slot feasibility, and expected-weeks-won all live; 19.4's weekly coverage gate
passes and its table is written down; `EspnPollFeed` is either verified against a mock draft
or explicitly left stubbed with the manual path as the shipped default.

> **As built — 19.1–19.3 (2026-07-15).** `src/fantasy_nba/draft/` = `feed.py` (Pick /
> DraftFeed / Manual · Espn · Fixture, `_get_json` content-type assertion, `scrub_payload`),
> `ids.py` (`normalize_name` NFKD, `eligible_positions`, `build_player_map`), `live.py`
> (`DraftState`, `live_replacement`, `live_board`). 21 tests in `tests/test_draft.py`; full
> suite 119 green.
>
> **Verified end-to-end against the real league (507458037, season 2025), not just tests:**
> 130 real picks parsed · ID join 387/400 = 96.8% · all 10 rosters at exactly 13 · draft
> order recovered as `[15, 11, 13, 14, 8, 9, 1, 12, 3, 10]` · team ids
> `[1, 3, 8, 9, 10, 11, 12, 13, 14, 15]` — **no 2/4/5/6/7, confirming the non-contiguity trap
> is real and a `range(1, N+1)` assumption would have mispriced every pick.**
>
> **Bug found by the real-data run that the unit tests missed — worth remembering.**
> `remaining_slots()` iterated only teams that had *already picked*, so pre-draft it saw 1
> team / 10 open slots instead of 10 teams / 100, and replacement was priced against a tenth
> of real demand. **The test suite passed anyway**: `test_live_replacement_rises_as_pool_drains`
> asserted the right direction for the wrong reason — replacement moved because demand was
> *growing* as teams appeared, not because the pool was draining. Fix: `DraftState.team_ids`
> (+ `EspnPollFeed.team_ids()` via `mTeam`), demand computed over the whole league.
> **Standing lesson:** a monotonicity assertion on a quantity with two moving inputs can pass
> while the mechanism is inverted — pin the *invariant*, not the direction. The replacement
> test is now `test_replacement_is_flat_when_the_draft_follows_board_order` (pool and demand
> drain together ⇒ replacement is a statement about the wire, not about pick count), verified
> flat at ~29.1 fpts/g through pick 90 on the live board.
>
> *Caveat on that verification:* replaying the **2025 draft** against the **2026-27 board** is
> an anachronism (~30 of the 2026-27 top-100 went undrafted in 2025), so its replacement curve
> rises and is not evidence of anything. Coherent board-order drafts are the correct harness.

> **As built — 19.7 + the composition views (2026-07-16).** `src/fantasy_nba/api/draft.py`
> (one server-side session; state/connect/source/config/refresh/pick/undo/reset) +
> `frontend/src/views/DraftRoom.tsx` at `/room`. 27 tests; suite 127 green; tsc clean; driven
> in a real browser (Playwright) with zero console errors.
>
> **Two more bugs of the same family, both found by looking at the UI — not by tests.** Both
> were *demand under-counting*, the third and fourth instance of the bug fixed in 19.3:
>
> 1. **Replacement 56.6 fpts/g on an untouched board.** Pre-connect, `team_ids` is empty, so
>    zero demand was counted and replacement degenerated to "best player available". **The
>    insight: demand needs a team COUNT, not team ids** — `league.yaml` says ten teams compete
>    even when we cannot name one. Fix: `DraftState.n_teams` + `total_demand()`, where each
>    unnamed team contributes a full slate. Replacement pre-connect is now board #101 = 29.09,
>    exactly as it should be.
> 2. **Replacement 41.98 with no position data.** Applying "unknown position ⇒ UTIL-only"
>    (value.py's rule, correct per-player) to the *whole league* filled only the 30 UTIL slots.
>    Fix: `DraftState.no_positions` ⇒ `_fills` unconstrained — with zero information, degrade
>    to value.py's classic league-wide fill rather than invent a constraint.
>
> Also fixed from the screenshot: manual mode with no ESPN had no clock, so **every pick fell
> to my own roster** and the league panel showed one team — `_synthetic_teams` gives 1..N
> stand-ins and a plain snake, flagged in the UI as stand-ins (`synthetic_teams`).
>
> **The standing lesson, now seen four times in one step: this bug class does not surface in
> unit tests** — the synthetic leagues are small and fully-specified, so demand is never
> unknown. It surfaces the moment you *look at a number a human would read*. The
> tests-plus-real-data-plus-browser ladder caught what any one rung alone did not.
>
> **Fifth instance, and the worst — found by a user question, not by any rung (2026-07-16).**
> Asked whether a PF/C contributes to both PF and C replacement, the answer was yes (correct),
> but auditing it exposed that `live_replacement` walked the pool in `rank` order and recorded
> the **first** unseated player's `fpts_pg`. That silently assumes `rank == fpts_pg order`. The
> shipped board ranks by the risk-adjusted **`safe`** stance, where it does not hold, so the
> level was incoherent — a `safe` ordering priced in fpts/g — and stance-dependent: PF read
> **29.09 / 34.86 / 31.49** for fpts_pg / safe / median rankings of an *identical pool*.
> Replacement is a fact about the wire and must not move when we change our mind about
> ranking. Fixed: seat in draft order, then level each slot at the **max** fpts_pg among
> unseated eligibles. PF's cross-stance spread fell 5.8 → 0.98. Pinned by
> `test_replacement_does_not_depend_on_ranking_stance`.
>
> That fix is what revealed the premise was wrong (the retraction under 19.3): with the level
> computed honestly, per-slot spread collapses to ~2.3 fpts/g and `live_vor` ≈ `fpts_pg`.
> **The bug had been manufacturing the very positional scarcity the step was built to find.**
> Standing lesson: when a new signal looks impressively strong, suspect the instrument first —
> and prefer a *property* test (stance-invariance) over admiring the output.
>
> `PlayerMap.save/load` caches ESPN identity + eligibility to
> `data/processed/espn_player_map.parquet` — without it "manual needs no network" was false,
> since ESPN is the only source of slot eligibility. Connect once, ever.
>
> *Non-bugs chased, recorded so the next session doesn't repeat them:* `app.routes`
> introspection shows no routes under FastAPI 0.139 even though the endpoints serve fine (a
> control test proved the introspection wrong, not the code); and names look like mojibake
> through a Windows cp1252 pipe while the API emits correct UTF-8 (`b"Luka Don\xc4\x8di\xc4\x87"`).
> **The tooling lied twice; the code was right both times.**

*Ordering: 19.1 → 19.2 → 19.3 (a useful tool already exists at this point — live board +
dynamic VOR, no sim) → 19.4 **gate** → 19.5 → 19.6. If 19.4's gate fails, 19.3 still ships and
the risk layer falls back to descriptive columns. Step 19 precedes Step 18 — Step 18 serves the
nightly in-season loop which starts at opening night; the draft is ~6 weeks sooner.*

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
| 016b | standard mover gate OR realized-top-150 big-riser recall +2pp with aggregate MAE not worse |
| 017 | benchmark: expert consensus (Hashtag/BBM) = value signal, ADP = availability column only; 017b market-gap feature runs now if ≥4 historical seasons recoverable, else waived + archive |
| 026 | features: standard gate. Policy: big-riser recall@150 +3pp OR above-market +5pp, aggregate MAE ≤ +1%, stable bias ±0.3 |
| 027 | per-group standard mover gate + recall view; preseason-minutes columns ship to the draft sheet regardless of verdict |
| 028 | rookie-cohort Spearman beats draft-pick-order baseline by ≥ 0.05 pooled, MAE not worse (rule 8); on reject the D1.5 market seed stands |
| 029 | dual freeze before opening night is unconditional; layer verdict in April 2027 — B beats A on top-150 MAE + riser recall → keep; A beats B → delete + ledger failure categories; one-season sample ⇒ at most adopted-tentative. *(Amended 2026-07-12, user decision — workflow v2: the layer is a standing supplement fed by BBM-transcript triangulation (proposals → approval → living overrides, applied preseason AND nightly in-season via update_daily); the April scoring now **calibrates** magnitudes + per-source weighting (user vs `BBM <date>:`-tagged entries) instead of deciding existence. Freeze + scoring mechanics unchanged.)* |
| D1 | product step — no gate; ships with sanity reports (VOR reorder count, schedule spot-checks) |
| 19 | product step — no ledger entry, **except 19.4**: the weekly-total p10–p90 coverage of the H2H variance layer must land in [78, 88]% on synthetic rosters from real game logs (the EXP-015b/021 window), or 19.5–19.6 don't ship and the risk layer falls back to descriptive columns. Never pass `SD_PG=9` (a season-total-calibrated width) into a per-game weekly draw. |
| 022 | direct beats composed on riser bias ≥25% reducible-gap (rule-8), or bucketed covariance large+positive → adopt correction/blend |
| 023 | standard mover gate; watch age ≤ 24 cohort; rule-11 hygiene on the lag group |
| 024 | standard mover gate AND aggregate MAE not worse (consistency fix adoptable on a tie) |
| 025 | (reserved — rotation-survival hurdle; spec when Phase 0 says fallers matter) |
| 018 | beats frozen-T₀ AND naive-shrinkage updater at ≥2/3 cutpoints, 3/4 seasons — *ran 2026-07-09: frozen-T₀ beaten 12/12; naive at parity (gate parked; re-gate after Steps 7 + D1)* |
| 019 | diagnostic — baselines recall + lead time |
| 020 | standard riser gate + lead-time non-regression |
| 021 | coverage ∈ [78,88]% AND big-riser coverage improves AND rank Spearman not worse |
| 030 | treated-segment (teammate-OUT) ROS MAE improves vs asof, clustered CI excludes 0; untouched segment byte-identical; lead-time not worse. Adoption re-arms the EXP-018 naive gate |
| 031 | 17.1 diagnostic first (budget overshoot × error correlation — no correlation ⇒ reject (b) cheaply); minutes MAE ≤ control AND role-change segments −10% with rest ≤2% worse; judged on minutes MAE/recall, never preseason riser bias |

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
| `docs/ui-views-plan.md` | web-app view specs + their own tracker (product; added 2026-07-16) | model experiments, gates |

When any two disagree, the more specific doc wins and the less specific one gets a pointer,
in the same commit.

## Appendix C — data snapshot for remote sessions (optional)

To let remote (no-egress) sessions run Steps 1–5 code + evals: commit to a branch a trimmed
snapshot — `data/raw/player_season_stats.parquet`, `player_bio.parquet`, plus a *reduced*
game-log table (only the columns recency/trade/asof need: `SEASON, PLAYER_ID,
TEAM_ABBREVIATION, GAME_DATE, MIN, PTS`; parquet+zstd keeps 16 seasons ≈ a few MB). Add a
`data/README.md` stating the snapshot date and that `.gitignore` stays authoritative for
full raw pulls. Steps 6+ (rosters/injuries/ADP) still need local pulls.
