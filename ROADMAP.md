# Roadmap — Fantasy NBA Projections (2026-27)

This is the **source of truth for build progress** across sessions. Check items off as
they're completed. High-level "why" decisions live in the design notes below.

## Goal

Predict each NBA player's per-game stat line for the 2026-27 season, then convert those
stats into fantasy points under a configurable league scoring system.

## Core modeling philosophy

Don't predict fantasy points directly. **Decompose:**

```
stat_per_game = minutes_per_game × per_minute_rate × efficiency
FantasyPoints = Σ (scoring_weight × projected_stat)
```

Project minutes, per-minute skill rates, and efficiency as **separate** layers — they're
driven by different forces and have different stability/aging behavior. Minutes is the
highest-leverage and hardest driver. Rookies and traded/role-change players need
special-case handling.

## Key decisions

- **Scoring:** points league first, but scoring is a swappable **config** (`config/scoring.yaml`)
  so category/9-cat works later. Default weights are DraftKings-style placeholders — user to adjust.
- **League format (user, 2026-07):** weekly **H2H points** matchups with **daily lineup setting**;
  scoring numbers TBD (placeholders stand until locked — re-run the headline eval under the final
  scoring before draft day). The league **ends ~2–3 weeks before the NBA regular season** (exact gap
  TBD) to dodge late-season rest/tank noise — so ROS horizons, totals, and playoff-week logic key
  off `league_end`, not the NBA finale (`config/league.yaml`; implementation-plan Step D1).
- **Granularity:** season-long per-game first; game-by-game (opponent/rest-aware) later.
- **Data:** `nba_api` primary, Basketball Reference supplement, college/draft data for rookies. ~10-15 seasons.
- **Stack:** Python (pandas, scikit-learn, LightGBM/XGBoost, Parquet storage).

## Stages

### Stage 1 — Data foundation + baseline  ← DONE
- [x] Repo scaffold, tracking docs, packaging
- [x] Scoring config + scoring engine
- [x] Storage layer (Parquet)
- [x] Ingestion: player season stats, game logs, rosters, bio (age) via `nba_api`
- [x] Verify ingestion end-to-end (live pull — 2023-24…2025-26, 1,723 player-seasons)
- [x] Baseline model: **Marcel-style** — recency-weighted (5/4/3) per-minute rates, regressed
      to league mean by sample, age curve, projected minutes/games → stat line → fantasy pts
      (`models/baseline.py`, `scripts/project.py`)
- [x] Output: ranked 2026-27 projection table (582 players → `data/processed/baseline_2026-27.parquet`)

**Known baseline limitations (fixed in later stages):**
- No injury/retirement awareness — e.g. it still projects a full-ish season for players
  coming off major injuries (Tatum's Achilles) and aging stars (LeBron at 42). → needs
  injury data + manual overrides.
- Minutes/games projection is naive (recency-weighted + durability regression). → Stage 3.
- Age curve is a single crude multiplier for all stats. → Stage 2 per-stat empirical curves.
- DD/TD bonus applied to average line (undercounts). → Stage 2 expected-DD-rate.
- Only projects players active in the most recent season (no return-from-injury, no rookies). → Stage 4.

### Stage 2 — Layered stat models + aging curves  ← DONE (with a key finding)
- [x] Empirical per-stat aging curves — era-detrended delta method (`models/aging.py`),
      fit on 16 seasons. Curves are basketball-sane: assists/rebounds age well, pts/FT/steals
      decline after 30, 3PM rises (role shift + survivor bias).
- [x] Games-played / durability model — age→expected-GP curve, blend recent availability
      toward it (`models/durability.py`).
- [x] Shared projection core (`models/_core.py`); v2 model (`models/projection.py`).
- [x] **Backtest harness** (`models/backtest.py`, `scripts/backtest.py`) — no-leakage,
      refits curves on training years, compares models vs actuals.
- [ ] Per-minute rate models beyond regression (usage-driven) — deferred; see finding below.
- [ ] Efficiency models (TS%/FG%/FT%/3P% direct) — deferred.

**🔑 KEY FINDING (backtested on 2023-24 & 2024-25):**
- The Marcel **baseline is already strong** and **v2's aging curves are ~neutral** on
  aggregate per-game accuracy (MAE ~4.4 either way). Aging helps old players, hurts young
  (survivor bias), nets to nothing. Both models are kept; backtest is the arbiter.
- **Minutes projection is THE error source.** Feeding *actual* minutes cuts per-game MAE
  from ~4.4 → ~2.0 (**~55% of the error**). Per-minute rates are already well-predicted.
- ⇒ **Stage 3 (minutes/role) is the highest-value work by far.** Prioritize it over further
  rate/efficiency modeling.

### Stage 3 — Minutes & team-context layer  ← IN PROGRESS (highest leverage)
- [x] **Minutes aging curve** (`models/minutes.py`) — empirical MPG-vs-age curve via the same
      delta method as the rate curves (no era de-trend needed). Applied as a *damped
      multiplicative trend* on the player's own recency-weighted MPG (`strength=0.5`), not a
      blend toward a population mean. Wired into `project_v2(age_minutes=True)` → the **v2m**
      model; it's the default in `scripts/project.py` and the `v2m_2026-27` output.
  - **Backtested 2022-23…2025-26:** v2m beats v2 **and** baseline on minutes MAE in all 4
    seasons (avg MPG MAE 4.07 → 3.93) and beats v2 on per-game fpts MAE in all 4 (beats
    baseline in 3/4). Correlation improves everywhere. First change to actually move the
    minutes needle. Trade-off: adds a mild negative minutes bias (partly an eval selection
    effect — the ≥500-actual-min filter selects players who out-earned their projection);
    `strength=0.5` was tuned to keep ~all the MAE gain at ~half the bias.
  - Backtest harness now reports a **minutes MAE** row per model (`models/backtest.py`).
- [x] **Draft-pool evaluation** — harness now scores each model on its own top-N (default 100)
      by projected total, headline metric **Spearman rank correlation** (`--top-n`). All-player
      MAE was misleading; on the top 100, baseline ≈ v2 ≈ v2m (Spearman ~0.51) — curve/minutes
      modeling is within noise for drafting.
- [x] **Pulled game logs (16 seasons, 404k rows) + current rosters** for availability/role work.
- [x] **🔑 AVAILABILITY-CEILING FINDING** (top-100 backtest) — the decisive result:
  - Games-played **dominates** draft ranking: oracle (proj per-game × *actual* GP) = Spearman
    **0.89** vs current **0.51** vs per-game-only **0.49**. Among elites, per-game is compressed
    and near-irrelevant; accumulation = who stays healthy.
  - Games-played is **~unpredictable** from box scores: prior-GP→next-GP Spearman 0.21; a fit on
    3-yr GP + age + MPG explains **R²≈0.03**. The current GP model is already at the data ceiling;
    era-window / own-GP-blend sweeps can't beat it (down-weighting own GP *hurts* ranking).
  - Aside: stars are NOT load-managed down (36+ MPG has the highest GP); modern rotation GP ~66-68.
  - ⇒ Point-estimate GP/rate/minutes modeling is **capped for ranking**. Next real levers are
    external availability data OR uncertainty ranges — see below. (`key-finding-availability-ceiling`.)
- [ ] Depth-chart / roster-turnover MPG redistribution — data now available (rosters + game logs);
      deferred because the top-100 lever is availability, not MPG-role (a smaller measured effect).
- [ ] Pace adjustment — deferred (low measured leverage).

### Stage 4 — Special cases  ← re-scoped 2026-07-09 into the Stage-7 execution plan
- [ ] Rookie model — now **EXP-028 (implementation-plan Step 9d)**: draft slot × landing spot
      (reuses the Step-8.4 vacated-usage features; gate = beat the draft-pick-order baseline).
      College/international stat translation stays a later refinement. **Stopgap ships first:**
      D1.5 seeds rookies from the expert-consensus pull, flagged `market_priced`, so the draft
      sheet has no invisible players even before the model exists.
- [ ] Role-change / traded-player adjustment — largely absorbed by Stage 7: preseason =
      the Step-8/8.4 dated-transactions + vacated-usage features; in-season = the as-of
      engine's post-trade features (EXP-018) + Step-7 live availability. Keep this box until
      those steps run, then tick with a pointer.

### Stage 5 — Scoring & delivery
- [ ] Category-league scoring mode (z-scores / rankings)
- [ ] Final ranked projections + export

### Stage 6 — Uncertainty / risk ranges  ← IN PROGRESS (the honest answer to the availability ceiling)
- [x] **Monte-Carlo risk ranges** (`models/uncertainty.py`) — simulate each player's season:
      games drawn from the empirical (no-leakage, modern-era, elite-tier ≥2000-min) GP
      distribution, additively re-centred on the player's projected GP (keeps the real
      left-skewed injury tail); per-game drawn normal around projected fpts_pg. Outputs
      `fpts_p10/p25/p50/p75/p90`, `fpts_median`, and a `risk` score. `scripts/project.py --ranges`.
  - **Calibrated on top-100 backtest** (2022-23..2025-26): p10–p90 coverage ~82%, p25–p75 ~48%,
    tails ~9%/10%. `SD_PG=9` is tuned to *total* coverage (absorbs breakout/role/model-bias and
    season-wide common health shocks the marginal GP pool misses), not literal per-game RMSE.
  - Sanity: Giannis flags highest-risk among top-20 (51-game history → low floor); durable
    Jokić/SGA lowest. `fpts_p10` is the draft-safety floor number.
- [x] **Risk-adjusted ranking** (`uncertainty.rank_board`, `scripts/project.py --rank-by`) —
      safe / median / floor / ceiling stances. Default **safe** = `median - 0.5·(median-floor)`:
      backtests as accurate as median (Spearman ~0.57, all indicators within noise) but demotes
      injury-prone players (e.g. Giannis falls out of the top-20). Reliability context: projected
      top-100 has ~79% overlap with actual top-100, but only ~60% at top-24 (fine-grained order is
      injury-limited — the availability ceiling).
- [ ] (Optional, higher effort) source external availability data — injury history/reports — the
      only way to beat the R²≈0.03 box-score ceiling on games-played. **→ now tracked as Stage 7.C**
      (same data serves both a GP point-estimate and a per-player Monte-Carlo injury tail).

### Stage 7 — Catching risers & fallers (the discontinuity frontier)  ← IN PROGRESS (Phases 0–1 complete: preseason riser bias measured ≈ irreducible, EXP-011; in-season engine built + gated, EXP-018; execution order lives in docs/implementation-plan.md)

**The problem statement (user, 2026-07):** we project the stable core well but **miss the risers
and fallers** — and capitalising on those is the entire edge of a projection system. This stage
is the response. It is deliberately researched and sequenced *before* committing to any build;
see `EXPERIMENTS.md` for the trail of what's already been tested so we don't repeat it.

**Season-long, daily-updating use (user, 2026-07 clarification).** This is not a one-shot draft
tool. It runs **all season**: the preseason draft board **and** a **rest-of-season (ROS)
projection refreshed daily** as box scores + news arrive — the waiver-wire and trade-value engine.
Highest-value in-season job: catch a riser **early**, from a small sample, before the market does.
Design consequence: the projection is a **pure as-of-date function** — `project(data ≤ T) → ROS
line`, runnable at any T (T₀ = draft, every day after = the updated ROS number). This reshapes the
eval (in-season as-of-date walk-forward, not just season boundaries) and adds a **daily news/status
feed** as a data requirement. Full weighing in `docs/model-foundation.md`.

**Why every model so far misses them (structural, not a bug).** Baseline → v2 → v2m all project
each player **almost entirely from their own recent history**, recency-weighted and regressed to
the mean. That is an excellent *central-tendency* engine and a structurally *blind*
*discontinuity* engine: it treats an upward trajectory as noise around a mean, and it has **no
information about next season's context**. Real risers/fallers are driven by signals absent from a
player's own box scores:
1. **Opportunity / role change** — vacated minutes & usage when a teammate leaves, role
   compression from an arrival, coaching change. (Consensus #1 mechanism in the research.)
2. **Skill trajectory** — breakouts cluster at **age 22–24**, in players *already* gradually
   improving, with rising usage at held efficiency (TS%). Our 5/4/3 weighting damps this signal.
3. **External availability** — injury history/reports; the only thing that can beat the R²≈0.03
   box-score games-played ceiling (EXP-004).
4. **Within-season recency** — late-season / post-trade role changes wash out of season totals.
5. **The market** — ADP + public systems (DARKO/EPM) locate *where we disagree*, which is where
   the value is.

**Research basis (2026-07 survey):** DARKO (Bayesian/Kalman, per-possession, daily-updated) and
the RAPM-family (EPM, LEBRON) all beat static box-score models mainly by *weighting recency
intelligently and updating on new information* — not by a magic feature. Breakout literature
converges on age 22–24 + prior gradual improvement + usage↑ at held TS% + minutes↑ + low
established level (room to grow). Trade/roster research names the vacancy → redistribution →
market-lag chain explicitly. Consensus/ensemble reduces variance but can wash out a real edge —
so we use the market as a **benchmark and disagreement-finder**, not a crutch. (Sources logged in
the session; key ones: darko.app, Bruin/Dartmouth breakout studies, Athlon trade-effect pieces,
`nbainjuries` / prosportstransactions for injury data.)

#### 7.0 — Draftable-pool accuracy eval, mover-segmented  ← **KEYSTONE (preseason form DONE; in-season engine DONE — its eval metrics are Step 11)**
Universe: the **top ~100–150** (draftable) pool — players outside it won't be drafted, so we
don't care about them. Goal (user, 2026-07): get each player's projected **production level**
right, *especially the movers* — if a player goes 35→40, we want the projection to say ~40 so he's
drafted there. This is **not** a big-mover *classifier* and it's **not** about % move size; it's
level accuracy that doesn't fall apart on players whose level changed.
- [x] Primary metric: per-game fantasy-points **error** (MAE/RMSE + signed bias) over the pool.
      (`models/eval_movers.py`; ranking/Spearman stays in `backtest.py` as the EXP-003 component.)
- [x] **Mover segmentation (the new diagnostic):** bucket players by *actual* YoY change in value
      (big fallers … stable … big risers); report error **and signed bias per bucket**. EXP-006
      confirmed the structural flaw and sized it: **signed bias runs +6.8 (big fallers) → −8.9 (big
      risers) fpts/g** — we over-project fallers and under-project risers monotonically, because
      projected Δ is compressed to ~0 in every bucket. Shrinking this per-bucket bias is the deliverable.
- [x] **Directional capture:** projected Δ vs actual Δ (correlation + sign accuracy). Baselined weak
      (Δ-corr 0.07–0.42, sign acc ~0.52–0.68).
- [x] Score **per-game level** separately (done); **totals** (GP-capped — availability ceiling) left to
      the ranking backtest. The 35→40 case is a per-game-level case.
- [x] **In-season as-of-date engine + gate (EXP-018, Step 10):** `models/asof.py` — `project_asof(T)`
      trained on cutpoint snapshots (T₀−7d…+150d, ~33k rows/fold, walk-forward). **Beats frozen-T₀
      12/12 (season × cutpoint) by 0.6–1.7 ROS MAE — in-season updating is the largest accuracy lever
      measured.** vs the naive K=20 blend: parity (best config −0.07 pooled; per-season cell gate met
      only by 2025-26 → gate parked). Fitted EWMA half-lives: all rates → 40 games, MPG → 10 (EXP-001
      restated in-season). Re-gate after Step 7 (live OUT-tonight/vacated minutes) + D1 (schedule).
      Done-pending-Step-11 (the in-season mover eval + lead-time metric itself).
- [x] First run doubles as measuring the *current* model's mover bias — baseline the disease (EXP-006). ✔
- [x] Wire into `models/backtest.py` (no-leakage; shared `project_models` path). Across-season
      walk-forward done; within-season folds come with the in-season eval above.
- [x] **Predicted-Δ calibration + actual-pool recall view** (impl-plan Step 1): a selection-free
      calibration table and a second view scored on the *realized* top-150 (recall metric) — the
      model-pool view understates riser bias because missed sleepers are invisible.
- [x] **Ceiling diagnostics (EXP-011):** selection floor (011a) + per-bucket minutes/rate oracle
      decomposition (011b). **Phase-0 verdict — Decision Row 1:** on the model's own pool the
      big-riser reducible gap is **+0.19 fpts/g (< 2)** — preseason bias-*chasing* is near-done;
      the residual headroom is a **sleeper-recall** problem (recall 71%, realized-pool gap −2.7),
      which box-score preseason features can't crack ⇒ run Steps 4–5 as cheap A/Bs and **pull the
      in-season engine (Step 10) forward after Step 6.**

#### 7.★ — Foundational refactor: a learned, decompositional panel model  ← DONE (EXP-007 adopted; the as-of-date interface below delivered by Step 10 / EXP-018)
**Full weighing of alternatives (GBM panel vs DARKO-style state-space vs hierarchical Bayes vs
neural vs Marcel-incremental), the research mapping, and the honest "is it worthwhile" analysis:
see [`docs/model-foundation.md`](docs/model-foundation.md).** Summary below.

**Proposed decision (2026-07).** Keep the decomposition (proven right — minutes is the error
driver, EXP-001) but replace the hand-set Marcel layers (fixed 5/4/3 weights, fixed regression
constants, population curves) with **learned, feature-based models over the historical
player-season panel**. This is the base that lets 7.A–7.E become *features in one place* rather than
bolt-on adjustments — the scalable foundation the user asked for.
- **Interface: an as-of-date function** `project(data ≤ T) → ROS line`, run daily (T₀ = draft,
  every day after = updated ROS). Trained on as-of-date snapshots across seasons **and in-season
  cutpoints** so it learns small-sample shrinkage ("6 hot games" → how far to move).
- **Targets (kept separate — different drivers, different stability):** (1) per-minute rate per stat;
  (2) MPG / role — the dominant lever and most **news-sensitive** layer; (3) remaining games —
  in-season **news-driven** ("out 2 weeks"), preseason via durability + injury history (7.C).
  Compose `stat_pg = MPG × rate`; fantasy points via the swappable scoring config; uncertainty via
  the Monte-Carlo layer (Stage 6).
- **Model class:** gradient-boosted trees (LightGBM — already a dep). Chosen because it **subsumes
  Marcel**: given only "own recency-weighted rate + age" it can rediscover recency-weighting,
  mean-reversion and aging, so it's a strict generalization — can't do worse on the same inputs, and
  it can *use* the context features Marcel structurally cannot. Handles age × usage × trajectory ×
  role interactions natively; fast to iterate; feature importances give interpretability.
- **Feature families (where risers/fallers actually get captured):** own multi-year levels **and
  trends/slopes** · **recent-window (last-N-games) vs season splits** (in-season riser detection) ·
  age/experience · role & usage · **team-context / vacated minutes (7.A)** · efficiency/TS% ·
  **injury/lineup news status** (in-season) · optional **public daily skill feed (DARKO/DPM) and
  market/ADP (7.E)** · per-stat recency summaries. **7.A–7.E stop being separate models and become
  feature groups feeding this one.**
- **Don't rebuild DARKO — consider consuming it.** DARKO is already an excellent daily-updating
  *box-score skill* engine but is blind to context/news. Rather than rebuild a Kalman, we can
  **consume a public daily skill feed as a feature** and spend our effort on the minutes / role /
  news / availability layer where our fantasy-specific edge is. A home-grown online skill estimator
  stays an eval-gated future upgrade, not the base.
- **Honest framing of the test:** EXP-000/003 already showed a learned model on *Marcel-equivalent
  inputs* will roughly **tie** (rates are already well-predicted). The architecture swap is the
  *enabler*; the win must come from the *new context features*. We validate in that order and do
  **not** judge the refactor on the expected tie.

**Validation sequence (each → an `EXPERIMENTS.md` entry, adopt or reject):**
- [x] EXP-006 — build the 7.0 eval; quantify the current model's mover bias (baseline the disease). ✔
- [x] EXP-007 — learned decompositional model on Marcel-equivalent features (`models/learned.py`,
  LightGBM per target, wired into `project_models`). Expected a tie; **beat it** — signal-safe *and*
  modestly less mean-reverting (riser bias −4.8→−3.1, big-riser −8.9→−6.9), even before context
  features. Adopted as the foundation; Marcel kept as fallback. Caveats logged (small +bias; fallers
  not improved). ✔
- [x] EXP-008 — + season-level trajectory/slope features → **rejected**: no lift, slightly worse
  riser buckets (−3.12→−3.49) and directional capture. Season-granularity slopes are too noisy and
  redundant with what the GBM already learns. Code kept, unwired. Next trajectory test is
  **within-season recency (last-N games)**, not season slopes. → **EXP-008b**.
- [x] EXP-008b — + within-season recency (last-N-games form, `models/recency.py`) → **parked**: best
  add-on on *aggregate* (level MAE better 3/4 seasons, directional sign-acc 4/4) but **not the riser
  fix** — mover buckets a wash-to-worse because the season-end window is confounded by rest/tanking
  (biases projections down). Kept, opt-in (`--recency`). Refinement: trim rest games / post-trade split,
  couple with EXP-009b.
- [x] EXP-009 — + team-context / vacated-minutes features (`models/context.py`) → **parked**: a *net
  wash* on the buckets (better fallers, worse risers) and inconsistent across seasons (helped 2025-26,
  hurt 2023-24). Real but coarse — team-level turnover is blunt and the backtest mildly flatters it
  (end-of-season team assignment). **No transactions scrape was needed for the first cut** (computable
  from season-stats team membership). Code kept, unwired. → **EXP-009b** (below).
- [x] EXP-009b — recency **coupled with** team-context (`learned_rc`) → **rejected**: coupling doesn't
  crack risers (riser −3.12→−3.40) and context is **inert on top of recency** (`learned_rc` ≈
  `learned_recency`). **META-FINDING: four feature experiments now (008/009/008b/009b) all improve
  aggregate MAE but none moves the riser buckets** — the riser bias is stubborn against every
  own-history + season-roster feature. Remaining untried levers: **(1) de-confound recency** (trim
  season-end rest/tanking games — `skip_last` — or post-trade split); **(2) exogenous injury/news (7.C)**.
- [x] EXP-010 — DARKO live overlay (adopted live-only; see 7.E). Injury data (7.C), market/ADP remain.

**Shipped board:** `learned` (EXP-007) is now selectable in `scripts/project.py --model learned`
(→ `data/processed/learned_2026-27.parquet`, `--ranges` supported). The parked add-on variants are
eval-only (opt-in `--recency`); the shipped board uses the plain `learned` foundation.

#### 7.A — Opportunity / role-redistribution model  ← measured to its end preseason (EXP-009 parked, EXP-014 rejected); lives on as in-season features (Step 10+)
- [x] **First cut (EXP-009, `models/context.py`):** team-level vacated/returning minutes + turnover
      share as learned-model features. **Parked** — net wash on the mover buckets, coarse. **Key
      correction to the old plan:** transactions were **not** the missing ingredient for a first pass —
      vacated minutes are computable from `player_season_stats` team membership alone.
- [x] **Refinement (EXP-014, rejected):** position-aware, team-constrained share-of-minutes model
      (`models/allocation.py`, historical rosters pulled 2009-10…2025-26). **Fails decisively** —
      minutes MAE +63%, level MAE worse all 4 seasons, all segments (incl. moved/high-turnover)
      worse. Mechanism: the share model is ~competitive on season-*total* minutes, but converting
      share → MPG divides by predicted GP (R²≈0.03, EXP-004) — GP noise propagates into the
      per-game number. **Do not re-run share-of-minutes → MPG via ÷GP.** Depth-chart features +
      roster data stay (Step 10 reuses them as in-season features).
- [x] **Data (EXP-016, adopted 2026-07-09):** dated transactions pulled (25,771 rows, shared
      Step-7 scraper) → `rosters.preseason_roster_map`, the honest Oct-1 backtest team map —
      validated **97–99%** opening-team agreement on the draftable pool vs ~86% for the old
      end-of-season map (more accurate *and* leakage-free). Wired into `project_models`;
      EXP-009/EXP-014 verdicts stand a fortiori (dated addenda in the ledger).
      **EXP-016b (parked 2026-07-09):** the sharper honest-map opportunity features — vacated
      **usage**, position-weighted, star-departure flag, arrivals mirror (`learned_vac`,
      `context.vacated_features`). Orthogonal to everything held (max |ρ| 0.08; 7.1% y_mpg
      gain share) and aggregate level MAE improves in 9/12 season-seed cells (−0.09 mean),
      but the mover buckets don't move (bias deltas within seed spread, CIs straddle 0) and
      realized big-riser recall doesn't gain — the EXP-009 profile, sharpened and still short
      of its gate. Features stay: **EXP-026 (breakout layer) and EXP-028 (rookie model)
      consume them** — that's where vacated usage was always expected to pay (the Maxey
      pattern is archetype × vacancy, not a marginal bias fix).
- [ ] **Cheap exogenous pair (2026-07-09, EXP-027, Step 9c):** hand-curated coach-change table
      (the effect lives in new-coach × depth/age interactions) + **preseason-October game logs**
      (`ps_mpg`, `ps_start_share` — the latest-arriving pre-draft role signal; ships to the
      draft sheet regardless of the A/B verdict) + optional Vegas win-totals rider.
- [x] **Test:** ran with segments per the spec — the answer is no (see EXP-014).

#### 7.B — Young-player trajectory / breakout layer  ← re-scoped 2026-07-09: a **recall-gated** breakout layer (EXP-026, implementation-plan Step 9b) — per EXP-011, never judged on per-player error (you can't know which of ~20 archetype fits pops; ranking them all above their market price *is* the edge)
- [x] **Built + judged (EXP-026, 2026-07-09): both wirings rejected; the flag column ships.**
      Classifier (`models/breakout.py`, walk-forward) genuinely works as a classifier — AUC
      0.63–0.73, top-20 flag zone hits 2–3× base rate, preseason flags included Sheppard /
      Walker / Daniels / Avdija. But (a) features into the learned model make the mover buckets
      *worse* all seeds (aggregate MAE better — the familiar trade); (b) the rank-boost policy
      moves recall@150 by exactly 0.000 all seeds, and the diagnostic bound kills all sizings:
      missed risers score high (74th–100th pctile) yet sit at board ranks 150–350 with a
      crowded flag zone — max gain ≈ +3pp before displacement. Vacated-usage extension:
      neutral. The missing Maxey-triad leg is the **market gap** (re-arms with the EXP-017
      archive).
- [x] **Ships:** `scripts/project.py --breakout` → `breakout_p` on the draft sheet
      (informational, never re-ranks); the D2 analyst pass reads it as the option-value flag.
- [x] **Standing lesson (test ran as specced):** preseason recall doesn't move by re-ranking
      what the board already knows — missed risers are deep because their projected level is
      honestly low pre-breakout. Remaining recall levers are new information: EXP-027
      preseason-October roles, EXP-028 rookies, market-gap re-arm.

#### 7.C — External availability / injury data  ← DONE (EXP-015, 2026-07-09: split verdict)
- [x] Ingested: prosportstransactions injury+IL history 2009→today (`scripts/pull_injuries.py`,
      47k rows; Cloudflare needs the real Edge driven headed via Playwright). Name-join hardened
      (99.0% of events matched; dated aliases; new collisions hard-fail). Spell pairing +
      `INJURY_FEATURES` (chronic/recency/severity, as-of Oct 1) in `models/injuries.py`.
- [x] **Two uses, judged separately (EXP-015):** (a) GP point-estimate — **rejected**: pooled GP
      Spearman Δ −0.006 vs the +0.05 gate, CI straddles 0; EXP-004's season-horizon GP ceiling
      stands even with exogenous history. (b) **per-player Monte-Carlo tail — adopted**: the GP
      pool buckets by (age × chronic), coverage stays in [78,88]% all seeds, `safe`-rank ties or
      improves all seeds, and chronic stars finally carry their own downside (Embiid 2024-25 p10
      1481→1189 while equal-median durable Banchero holds 1788). Wired into
      `scripts/project.py --ranges` automatically when the injuries pull exists.
- [x] **Standing value:** the feed is the Step-12 OUT-tonight / live vacated-minutes channel and
      the EXP-018 re-gate dependency; do not re-try season-horizon GP point regression from
      history alone (ledger note).

#### 7.D — Within-season recency (game-log granularity)  ← preseason use exhausted (EXP-008b + EXP-012 both parked); true game-log granularity now lives in the as-of engine (EXP-018 EWMAs)
- [x] **Last-N-games form** as learned-model features (`models/recency.py`, EXP-008b): recent MPG /
      production vs the player's own season average. **Result:** best *aggregate* add-on (level MAE
      better 3/4 seasons, directional sign-acc 4/4) but **doesn't crack the riser buckets** — the
      season-end window is confounded by **rest / load-management / tanking**, which biases it *down*.
- [x] **Refinement (EXP-012, parked):** skip-last {5,10} trims + post-trade split, seeds {0,1,2} +
      clustered CI. Aggregate MAE win retained (3/4 seasons) but **no variant beats plain `learned`
      on the riser buckets** — as EXP-011a predicted (model-pool riser reducible gap ≈ 0, nothing to
      close). Kept opt-in; Step 10 revisits recency at game-log granularity (EWMAs, fitted half-lives).
- [x] **Couple with EXP-009b (rejected):** recency+context coupling inherits recency's aggregate
      gain and its riser miss; context is inert on top (see EXP-009b).

#### 7.E — Market / consensus integration  ← medium (also an eval tool)
- [x] **DARKO consumed as a live overlay** (`scripts/pull_darko.py` + `models/darko.py` +
      `scripts/darko_report.py`, EXP-010). Playwright pull (no API), name-join (99% match), archived
      date-stamped. Disagreement finder = minutes gaps + rank gaps vs our board. **Live-only /
      unbacktested** (no historical DARKO snapshots) and, honestly, **modest value**: DARKO's strength
      is rates (already ours, EXP-001), its minutes is its *weakest* stat (our need), and rookies are
      placeholder-initialized — so it's a risk/disagreement highlighter, not a mover fix.
- [x] **Market benchmark pulled + reporting (EXP-017, adopted live, 2026-07-09):**
      `scripts/pull_market.py` — Hashtag **points-league** rankings (the expert-consensus value
      signal, 579 rows, plain requests) + FantasyPros consensus ADP (availability only, 260
      rows), date-stamped append-only like DARKO, alias-hardened name join (100% of our
      top-150). `scripts/market_report.py` — sleepers/fades vs consensus (rank_gap + risk
      column) and the D1.4 "likely gone by pick" ADP column. Re-pull in Sept when both
      sources flip to 2026-27 preseason boards (a vintage note prints on every report).
- [x] **Test (EXP-017b): waived-with-condition (the EXP-010 waiver), 2026-07-09.** Archive
      audit: Wayback has genuine preseason snapshots for 2022-23 and 2023-24 (both sources,
      rookie-verified) and 2025-26 (ADP only; Hashtag snapshot is 25 rows deep), but
      **2024-25 preseason is unrecoverable** — the Aug-2024 FP/Hashtag and Oct-2024
      Basketball Monster captures all still showed 2023-24 boards (verified: Wemby ADP 19,
      no 2024 rookies, Embiid #1 g=39). 3/4 seasons < the ≥4 gate ⇒ benchmark-only this
      season, **archive from today**, re-arm the A/B next offseason on the accumulated pulls.
- [ ] **Analyst pass (EXP-029, Step D2, 2026-07-09):** the graded human-judgment layer —
      pre-draft review of every big board-vs-consensus disagreement, breakout flag, injury
      returnee, and rookie; adjustments + written rationales committed to
      `config/analyst_overrides.yaml`; **dual-board freeze** (pure model A vs analyst-adjusted
      B, both committed before opening night) scored against each other in April 2027. The
      layer must earn its place or be deleted — the discipline commercial systems' human
      layers never face. Long-run: each season's archives are a labeled map of *where the
      market beats us and on whom* — harvest every spring.

#### 7.F — Usage-coupled rate/efficiency  ← parked (revisit only via 7.A)
- [ ] Per-minute rates are already well-predicted (EXP-001); direct rate/efficiency modelling was
      parked. Only worth revisiting **coupled to 7.A** — a usage change from a role shift should
      propagate to rates. Low standalone priority.

**Sequencing (superseded 2026-07 — see [`docs/breakthrough-plan.md`](docs/breakthrough-plan.md)):**
after EXP-006…010, the plan is re-phased: **EXP-011 ceiling diagnostics** (the mover buckets
select on realized outcomes, so part of the tail bias is irreducible — size the floor first) →
untried in-repo levers (recency de-confound, loss-side changes, **team-constrained minutes
allocation**) → exogenous data (7.C injury, dated transactions, ADP) → the **in-season as-of-date
engine** (largest headroom) → distributional board. Original sequencing kept below for history.
**The step-by-step execution spec (files, signatures, commands, adopt/reject gates, progress
tracker) is [`docs/implementation-plan.md`](docs/implementation-plan.md) — work from that file;
it names the ROADMAP checkbox each step closes.**

**Sequencing (original):** 7.0 eval (keystone) → 7.★ learned foundation → then 7.A–7.E enter as **feature
families** into that model, in leverage order (7.A team-context & 7.B trajectory first, then 7.C
injury / 7.E market), 7.F only if warranted. Log every attempt in `EXPERIMENTS.md`, adopted **or**
rejected. **Note (2026-07): experiments need the NBA data cache, which this remote environment
cannot pull (`stats.nba.com` is blocked by egress policy). Runs happen locally or off a committed
data snapshot — see EXPERIMENTS.md "Active experiments".**

**Agent personas (user asked whether they'd add value):** recommendation — **one clear win, one
optional.**
- **Backtest/eval skeptic (recommended):** a reviewer persona whose only job is to hunt
  data-leakage, selection effects, and p-hacking in every 7.x experiment before it's logged
  `adopted`. High ROU given the ledger's whole point is trustworthy findings, and this stage adds
  new data sources (prime leakage territory).
- **Fantasy-basketball domain expert (optional):** a hypothesis-generator / sanity-checker for
  role-change and injury priors and for eyeballing the "biggest movers" list. Genuine value as a
  *prior*, but must be grounded against data — risk of confident-but-wrong specifics.
- Not recommended: a zoo of personas. The work is one coherent modelling effort; two lightweight
  definitions cover the real gaps.

## How we track progress
- **`ROADMAP.md`** (this file) — durable forward-looking checklist, the source of truth for *plan*.
- **`EXPERIMENTS.md`** — the backward-looking trail of what we've tested (so dead ends aren't
  re-run). Every 7.x experiment gets an entry, adopted or rejected.
- **Claude memory** — decisions and rationale (the "why").
- **In-session todos** — the active working list for the current sitting.
