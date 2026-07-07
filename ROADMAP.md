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

### Stage 4 — Special cases
- [ ] Rookie model (draft position + college/international stats)
- [ ] Role-change / traded-player adjustment

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

### Stage 7 — Catching risers & fallers (the discontinuity frontier)  ← NEXT (the real value)

**The problem statement (user, 2026-07):** we project the stable core well but **miss the risers
and fallers** — and capitalising on those is the entire edge of a projection system. This stage
is the response. It is deliberately researched and sequenced *before* committing to any build;
see `EXPERIMENTS.md` for the trail of what's already been tested so we don't repeat it.

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

#### 7.0 — Riser/faller eval harness  ← **KEYSTONE, do first**
- [ ] Nothing below is measurable until we can *see* risers/fallers. Build a dedicated eval that
      scores the thing we actually care about — the **year-over-year change**, not the level:
  - Define riser/faller by large YoY change in actual fantasy value/rank among the draftable pool.
  - Metrics: directional accuracy on ΔY, error on Δ (not the level), recall/precision of our
      top-K "biggest movers" calls, and calibration of those calls. Segment eval by role-change vs
      stable, and by age band.
  - **Rationale:** top-100 Spearman (EXP-003) is availability-dominated and rewards ranking the
      stable core; it is blind to this stage's goal. Keep it, but 7.0 becomes the co-headline.
- [ ] Wire into `models/backtest.py` (no-leakage; refit any curves/allocations on training years).

#### 7.A — Opportunity / role-redistribution model  ← highest leverage
- [ ] Model the **team-context change** each player walks into, not just their own past.
      Depth-chart minutes allocation (team ≈ 240 min/game) + usage redistribution: when a player
      departs (trade/FA/retire), reallocate their vacated minutes & usage to returning players by
      position / trajectory; compress when a high-usage player arrives.
- [ ] **Data needed:** transactions/roster-turnover (nba_api transactions or prosportstransactions;
      rosters already pulled), which is the missing ingredient. Game logs (have) give the
      redistribution priors.
- [ ] **Test:** does modelling vacated minutes improve minutes MAE **and** 7.0 metrics *for the
      role-change subpopulation* specifically? (Aggregate metrics will hide it — segment.)

#### 7.B — Young-player trajectory / breakout layer  ← high, targeted
- [ ] For young players (age ≤ 24, ≥2 seasons) add a **trajectory/momentum term** instead of pure
      mean-reversion: extrapolate the improvement slope, gated by a breakout-probability model.
- [ ] **Features (from research):** age 22–24, prior-season gradual improvement, usage↑ with held
      TS%, minutes↑, low established level, draft pedigree.
- [ ] **Test:** historical breakout recall/precision; does shifting projections for high-P(breakout)
      players improve 7.0 metrics for the young cohort without hurting the rest? (EXP-000 warns
      population aging curves alone don't help young players — this is the targeted fix.)

#### 7.C — External availability / injury data  ← attacks the GP ceiling directly
- [ ] The only lever that can beat EXP-004's R²≈0.03 box-score GP ceiling. Ingest historical
      injury data (`nbainjuries` pkg / prosportstransactions; NBA official injury reports from
      2021-22). Build injury-history features (chronic vs acute, games-missed trend, injury type —
      Achilles/ACL/back/knee — age×injury interaction).
- [ ] **Two uses:** (a) a GP point-estimate model that finally beats box-score-only; (b) a
      **per-player** Monte-Carlo GP tail (Stage 6 currently uses an age-bucket pool, not player
      history) — sharpen the floor for chronically-injured stars.
- [ ] **Test:** does injury-featured GP beat the current GP model on next-season GP? Does the
      per-player tail improve range calibration and `safe`-ranking on injury-prone players?

#### 7.D — Within-season recency (game-log granularity)  ← medium
- [ ] We hold 16 seasons / 404k game-log rows but project off *season totals*. Weight the **last N
      games / post-All-Star / post-trade splits** more heavily to catch emerging roles a full-season
      average buries.
- [ ] **Test:** does a "last-25-games" weighting beat full-season weighting for next-season
      projection, especially for role-change and late-emerging players?

#### 7.E — Market / consensus integration  ← medium (also an eval tool)
- [ ] Pull ADP + ≥1 public projection (DARKO / Hashtag / FantasyPros consensus). Use three ways:
      (1) **benchmark** our accuracy vs the market; (2) **disagreement finder** — surface our
      biggest deltas vs ADP as the actionable riser/faller calls; (3) optional ensemble member.
- [ ] **Test:** where we systematically disagree with the market, who's right historically? Does a
      blend beat us on 7.0 metrics — and does it *wash out* our edge on the movers (the known
      ensemble trade-off)?

#### 7.F — Usage-coupled rate/efficiency  ← parked (revisit only via 7.A)
- [ ] Per-minute rates are already well-predicted (EXP-001); direct rate/efficiency modelling was
      parked. Only worth revisiting **coupled to 7.A** — a usage change from a role shift should
      propagate to rates. Low standalone priority.

**Sequencing:** 7.0 (keystone) → 7.A (highest leverage) & 7.C (GP ceiling) in parallel → 7.B →
7.D / 7.E → 7.F if warranted. Log every attempt in `EXPERIMENTS.md`, adopted **or** rejected.

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
