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

- **Scoring:** set to **ESPN Fantasy default points** (`config/scoring.yaml`, `espn_points`:
  PTS 1, 3PM 1, FGM 2, FGA −1, FTM 1, FTA −1, REB 1, AST 2, STL 4, BLK 4, TOV −2; no DD/TD).
  Swappable config layer (category/9-cat later); box-score projections are league-independent, so
  changing scoring is a pure re-weight (only re-check `SD_PG` if the fpts *scale* shifts a lot).
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
- [x] **🔑 ROLE-CHANGE INVESTIGATION** (2026-07-07) — "why doesn't it catch busts/sleepers?"
  - Diagnosis: busts/sleepers are **~85% minutes/role changes** (corr per-game-miss vs minutes-miss
    0.84–0.89). The momentum model can't see them: it projects minutes from a player's *own* history,
    not their *team's* context (Braun rising because KCP left, etc.).
  - **Automated depth-chart / roster-turnover redistribution FAILED** — 4 formulations (team-wide,
    within-position, youth/room-weighted, targeted "next man up"), all lost the backtest (hurt the
    majority; surgical version made confident wrong bets). Causes: height→position only 67% accurate
    (no historical positions), and "who slots up" is a coaching/breakout call not in box scores.
    **Do not re-attempt from box-score data.** (`key-finding-role-change-lever`.)
- [ ] **Recent-form minutes blend** — CANDIDATE, validated, NOT yet implemented. Blend `w≈0.4–0.5`
      of a player's last-~25-game MPG (from game logs) into the momentum MPG. Improves minutes MAE
      for all players *and* movers every season, no new data; ~neutral on draft *outcome* (totals
      still availability-bound). Low-risk free win — fold into `models/minutes.py`.
- [ ] Pace adjustment — deferred (low measured leverage).

### Stage 4 — Special cases
- [ ] Rookie model (draft position + college/international stats) — also a natural fit for the
      Stage 7 news layer (rookies like Dybantsa/Boozer show up in preseason role news).
- [ ] Role-change / traded-player adjustment — the box-score route failed (Stage 3); the real
      path is the Stage 7 editorial/news signal.

### Stage 5 — Scoring & delivery  ← PARTLY DONE
- [x] **ESPN default points scoring** wired in (`config/scoring.yaml`); `fpts_pg` (avg FP/G) shown
      on the board; `--rank-by` CLI board.
- [x] **Interactive explorer** (`scripts/explore.py`, Streamlit) — Draft Board (season selector incl.
      no-leakage past seasons vs actuals + hit-rate; model selector; rank stance; search/filter),
      Player drill-down (career + minutes trend/volatility), raw Data browser.
      Run: `python -m streamlit run scripts/explore.py`.
- [ ] Category-league scoring mode (z-scores / rankings)
- [ ] Final ranked projections + export (CSV/board hand-off)

### Stage 6 — Uncertainty / risk ranges  ← DONE (the honest answer to the availability ceiling)
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
      only way to beat the R²≈0.03 box-score ceiling on games-played (folds into Stage 7).

### Stage 7 — External / news / editorial signal  ← THE FRONTIER (agreed direction; deferred by user)
The box-score model provably can't predict busts/sleepers (Stage 3) or availability (Stage 6
ceiling) because the deciding info is **forward-looking and editorial** — expected minutes,
depth-chart/starter changes, injury timelines, transactions. Basketball Monster/RotoWire solve this
with hand-maintained depth charts + expert projections (humans reading news). It's an *information*
input to acquire, not an algorithm to derive. **Demonstrated feasible** via live web search (2026-07-07):
LLM extraction surfaced exactly the needed signal (e.g. "Amen Thompson → full-time starter, 32 mpg";
"Reed Sheppard usage spike after HOU trades"; injuries Luka/Curry; rookies Dybantsa/Boozer).
- [ ] **LLM news-signal layer** → structured extraction (`expected_mpg`, `injury_games_risk`,
      `role_note`, **with source citations**) → feed as a **minutes override + availability
      adjustment** → recompute stat line + risk ranges. Its edge over editorial services: full
      coverage/consistency, freshness, and fusion with our *calibrated* risk ranges.
- [ ] **Manual expected-minutes override** in the explorer (type a player's minutes → live re-project).
- [ ] **Opportunity-change flags** — surface each team's vacated/added minutes from roster turnover.
- **Build options:** (A) *in-session* — research top ~150 players' news → sourced override table
      that plugs in today (no infra; best for the actual draft); (B) *automated* — Claude-API script
      over news feeds on a schedule (needs API key + cost + source handling). Start with (A).
- **Caveats (must respect):** data-acquisition/ToS (24/7 scraping is fraught; some sources paid);
      verification (LLM can hallucinate → require citations + spot-checks, never silently move a
      projection); **cannot be cleanly backtested** (no point-in-time news archive → trust on sourced
      face-validity, not MAE); "sentiment" per se is weak — use *facts* (injuries, depth charts,
      transactions, coach quotes); it's operational — refresh near the draft.
      See memory `project-direction-news-signal`, `key-finding-role-change-lever`.

## How we track progress
- **This file** — durable checklist, the source of truth.
- **Claude memory** — decisions and rationale (the "why").
- **In-session todos** — the active working list for the current sitting.
