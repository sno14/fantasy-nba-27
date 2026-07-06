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
- [ ] Risk-adjusted ranking mode (rank by floor / expected value) in the delivery layer.
- [ ] (Optional, higher effort) source external availability data — injury history/reports — the
      only way to beat the R²≈0.03 box-score ceiling on games-played.

## How we track progress
- **This file** — durable checklist, the source of truth.
- **Claude memory** — decisions and rationale (the "why").
- **In-session todos** — the active working list for the current sitting.
