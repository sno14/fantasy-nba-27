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

### Stage 2 — Layered stat models + aging curves
- [ ] Empirical aging curves per stat (delta method / mixed models)
- [ ] Per-minute rate models (usage, reb%, ast%, stl/blk rates)
- [ ] Efficiency + regression models (TS%, FG%, FT%, 3P% — regress low-volume)
- [ ] Games-played / durability model

### Stage 3 — Team-context layer
- [ ] Minutes projection model (depth chart aware)
- [ ] Usage/possession redistribution on roster changes (departures/arrivals)
- [ ] Pace adjustment

### Stage 4 — Special cases
- [ ] Rookie model (draft position + college/international stats)
- [ ] Role-change / traded-player adjustment

### Stage 5 — Scoring & delivery
- [ ] Category-league scoring mode (z-scores / rankings)
- [ ] Uncertainty ranges (floor / median / ceiling)
- [ ] Final ranked projections + export

## How we track progress
- **This file** — durable checklist, the source of truth.
- **Claude memory** — decisions and rationale (the "why").
- **In-session todos** — the active working list for the current sitting.
