# Model foundation — design note & architecture decision (Stage 7)

Status: **proposal for review** (2026-07). Companion to `ROADMAP.md` §Stage 7 and `EXPERIMENTS.md`.
This note answers two questions the user raised: **(1) is this effort worthwhile?** and **(2) which
foundational model should we build on?** — weighing the real alternatives rather than asserting one.

---

## 0. The goal, stated precisely

Not "predict fantasy points." The goal is: **for the top ~100–150 (draftable) players, get each
player's projected production *level* right — especially the players whose level is about to change
(risers & fallers) — so they're drafted at the right spot.** A player going 35→40 fantasy pts should
project at ~40, not ~35.

This is a **season-ahead, one-shot** projection for a draft. That framing matters a lot below (it's
why a DARKO-style daily-updating engine is the wrong foundation for *us*, even though DARKO is
excellent at what it does).

---

## 1. Is this worthwhile? (the honest answer)

**Short version: yes for the skill/role/trajectory dimension — that's a real, correctable, unused
signal. It is capped for the availability (games-played) dimension unless we add injury data.**
Splitting those two is the key to not wasting effort.

**Why the skill/mover dimension is genuinely worth it:**
- The current model's miss on movers is a **systematic bias, not irreducible noise.** Because every
  layer is computed from the player's *own* recency-weighted history, the model mean-reverts: it
  **under-projects risers and over-projects fallers** by construction. Correcting a *systematic* bias
  is high-value and achievable — unlike chasing random noise.
- Breakouts/collapses are **not random.** The research (below) shows they concentrate in identifiable
  conditions — age 22–24, a player *already* gradually improving, rising usage at held efficiency,
  and especially a **change in opportunity** (a teammate leaves, a role opens). The current model
  uses *none* of these signals. That unused signal is exactly the edge.
- We are **not trying to beat a perfect oracle or the whole market on average.** We're trying to be
  *systematically less biased on the movers* than a naive own-history model. That bar is reachable:
  even ADP and DARKO are shaky on movers — movers are where *everyone* is uncertain — so a
  disciplined, feature-driven approach to that specific hard subset is where a home edge exists.

**Where it is capped (the honest caveat):**
- **Games played is ~unpredictable from box scores** (EXP-004: fit R²≈0.03; oracle-GP would lift
  top-100 Spearman 0.51→0.89, i.e. *availability is most of the ranking signal*). No model
  architecture fixes this — only **external injury data (7.C)** can. So "total-value ranking" has a
  hard ceiling until we add that data; "per-game level" does not. Chase per-game/role/trajectory
  first; treat games-played as a distribution (Stage 6) plus an injury-data project, not a modelling
  problem to out-clever.

**Net:** the refactor is worthwhile because it's the foundation that (a) removes the mean-reversion
bias on movers, (b) improves per-game level accuracy, and (c) gives injury/market data a place to
plug in later. Expect "meaningfully less biased on the mover subset," **not** "predicts every
breakout." Some skill leaps are genuinely unforecastable; many *opportunity-driven* moves are not.

---

## 2. What the research says, and how it becomes features

We reviewed public projection systems and breakout studies (2026-07). The takeaways map directly to
model *features*, not to a particular algorithm:

- **DARKO** (Bayesian/Kalman, per-possession, *daily-updated*): its edge is **intelligent per-stat
  recency weighting + aging baked into the transition + per-possession normalization**, updated as
  new games arrive. **Crucial for us:** the daily-updating machinery is worth little for a *one-shot
  preseason draft* projection — its benefit collapses to "good recency weighting + aging," which we
  can capture as *features* without adopting a full state-space engine. And a per-player state-space
  model **can't see exogenous context** (who left the team) — the very thing that drives movers.
  → borrow: per-stat recency features, aging as a feature, per-minute/possession normalization.
- **RAPM family (EPM, LEBRON):** predict an impact target from box + on/off. Confirms the workhorse
  pattern — *learn* the mapping from features to next-season value rather than hand-set it.
- **Breakout studies (Bruin/Dartmouth/HSAC):** breakouts center at **age 22–24**; a **negative
  relationship between current level and improvement** (room to grow → mean-reversion is real but
  *asymmetric* for the young); breakouts usually follow **prior gradual improvement** and **rising
  usage at maintained TS%**. → features: age & age², experience, own multi-year **slopes/trends**,
  usage trend, TS% stability, age×trajectory interactions.
- **Trade/roster research:** the **vacancy → redistribution → market-lag** chain — a departing
  high-usage player's minutes/usage get absorbed by teammates, and the market underprices the
  secondary beneficiaries. → features: **vacated team minutes/usage** available to each returning
  player, incoming-player compression (needs transactions/roster data).
- **Market/consensus (ADP, FantasyPros):** consensus lowers variance but can wash out a real edge.
  → use as a **benchmark** and a **disagreement finder** (our biggest deltas vs ADP = the actionable
  calls), optionally an ensemble member — not a crutch.

Sources: darko.app/about & nbastuffer DARKO explainer; Bruin Sports Analytics & Dartmouth Sports
Analytics breakout studies; Athlon trade second-order-effects & usage pieces; `nbainjuries` /
prosportstransactions for injury data; FantasyPros/RotoWire on ADP.

**The theme:** across every good system, the algorithm matters less than **feeding the model the
right signals** — and the mover-driving signals (trajectory, opportunity, context) are exogenous
tabular features. That observation drives the architecture choice.

---

## 3. The alternatives, weighed

Constraints that discriminate between them: **small data** (~16 seasons × ~500 players ≈ 5–6k
season-to-season pairs), **season-ahead one-shot** use, need for **fast iteration** and
**interpretability**, and the fact that **the mover signal is exogenous/contextual**.

| Option | Fit to the mover problem | Ingests context features | Uncertainty | Iteration speed | Data-hungry | Verdict |
|---|---|---|---|---|---|---|
| **A. Marcel + hand adjustments** (status quo, extended) | Poor — own-history only | No (hand hacks don't scale) | Bolt-on MC | Fast | No | Baseline/fallback only |
| **B. Learned decompositional GBM panel** (proposal) | **Strong** — trees model context × trajectory × age interactions | **Yes, natively** | Bolt-on MC (fine) | **Fast** | No | **Recommended** |
| **C. State-space / Kalman (DARKO-style)** | Weak for *our* use — models own-state evolution, blind to exogenous context; daily-update edge irrelevant to a draft | No (not without heavy extension) | Native, good | Slow to build | Medium | Borrow ideas, don't adopt as base |
| **D. Hierarchical Bayesian partial-pooling** | OK — group predictors possible; mean-reversion & per-player uncertainty fall out | Yes, but adding many interacting features is awkward | **Native, best-calibrated** | Slow (MCMC) | No | Later refinement for the *ranges*, not the base |
| **E. Neural / sequence (RNN/transformer on game logs)** | Could learn trajectory | Yes | Hard | Slow | **Yes — data-starved here** | Overkill; reject for now |

**Reasoning:**
- **Why B (recommended).** The mover signal lives in *exogenous, heterogeneous, interacting* tabular
  features (age × usage-trend × vacated-minutes × efficiency). Gradient-boosted trees are the best
  tool for exactly that on small tabular data: they capture interactions natively, need little
  preprocessing, iterate in seconds, and expose feature importances for interpretability. Decisively,
  **B *subsumes* the current model** — give it only "own recency-weighted rate + age" and it can
  rediscover recency-weighting, mean-reversion and aging, so on the same inputs it can't do worse
  than Marcel, and unlike Marcel it can *use* the context features. Marcel becomes a hand-tuned
  special case and stays as the fallback/sanity baseline. We keep the **decomposition** (predict
  per-minute rates, MPG, GP separately — proven right by EXP-001) and compose to a stat line, so
  scoring stays swappable and Stage-6 ranges keep working.
- **Why not C as the base.** DARKO is superb, but its architecture is built for **online daily
  updating**, which is worthless for a one-shot preseason draft — and a per-player state-space model
  structurally **can't see the exogenous context** (roster turnover) that drives most movers. High
  effort, wrong-shaped benefit. We take its *ideas* (per-stat recency, aging-in-transition,
  per-possession) as **features in B** instead.
- **Why not D as the base.** Its strength is calibrated uncertainty — which we already get from the
  Monte-Carlo layer (Stage 6). As a *point-estimate* engine it rarely beats a GBM, and it's much
  slower to iterate and clumsier to load with dozens of interacting features. Keep it in the back
  pocket as a possible upgrade to the *ranges*, not the foundation.
- **Why not E.** ~5–6k pairs is far too little for sequence models to beat trees; they'd overfit and
  iterate slowly. Reconsider only if we ever move to game-by-game modelling with far more rows.

---

## 4. Recommended foundation (detail)

**A learned, decompositional panel model.** Keep the decomposition; learn each layer.

- **Targets (predict season t+1 from t and earlier, walk-forward):**
  1. **per-minute rate** for each counting stat,
  2. **MPG** (the dominant error driver, EXP-001),
  3. **GP** — kept separate, expected low R² (EXP-004 ceiling); primarily feeds the Stage-6
     distribution, and is where injury data (7.C) plugs in.
- **Compose:** `stat_pg = MPG × rate` → fantasy points via the swappable scoring config. Uncertainty
  via the existing Monte-Carlo layer.
- **Model class:** LightGBM (already a dependency). Separate model per target; per-stat rate models
  can share features.
- **Feature families:** own multi-year **levels and slopes/trends** (breakout signal) · age, age²,
  experience · role & usage (usage rate, minutes/starter share, position) · **team-context /
  vacated minutes & usage** (7.A) · efficiency/TS% and its stability · per-stat recency summaries
  (DARKO-style) · later: injury history (7.C), market/ADP (7.E).
- **Discipline:** strict no-leakage temporal walk-forward; refit everything per fold; tune with
  time-series CV. This is already the harness convention — extend it with the §5 eval.

**What stays exactly as-is:** the decomposition philosophy, the swappable scoring config, the
Monte-Carlo risk ranges, and Marcel — retained as the fallback and the "did the learned model lose
signal?" baseline.

---

## 5. How we'll know it worked (and de-risk it)

The eval **is** the safeguard against fooling ourselves (§7.0 in the roadmap):
- Draftable top ~150; score **per-game level** error/bias separately from GP-capped totals.
- **Mover-segmented signed bias**: bucket by *actual* YoY change; the deliverable is shrinking the
  riser-under-projection / faller-over-projection bias — not a headline correlation number.
- Directional Δ capture: do we move players the right way vs their own last year?

**Validation sequence (each an `EXPERIMENTS.md` entry, adopt or reject — see EXP-006..009):**
1. Build the eval; **quantify the current model's mover bias** (baseline the disease).
2. Learned model on **Marcel-equivalent features** → expect a **tie** (proves the swap loses no
   signal; if it *loses*, fix the framework before adding features). We do **not** judge the refactor
   on this tie — it's a safety check.
3. **+ trajectory/slope features** → does the riser bias shrink for the young cohort?
4. **+ team-context / vacated-minutes features** (needs transactions data) → the decisive test; the
   largest expected mover-error reduction, for the role-change subpopulation specifically.

**Fallback:** if a stage doesn't beat Marcel on the mover buckets, we keep Marcel for that layer and
log the negative result — no sunk-cost. Because B subsumes Marcel, the floor is "no worse."

---

## 6. Recommendation

Adopt **Option B** (learned decompositional GBM panel) as the foundation, borrow DARKO's recency/
aging/per-possession *ideas* as features, encode the breakout research as trajectory + opportunity
features, and use the market as benchmark/disagreement-finder. Keep hierarchical-Bayes (D) as a
possible later upgrade to the *ranges* only. **Your effort is worthwhile on the per-game/role/
trajectory dimension — that's real, unused, correctable signal — with the honest caveat that the
availability dimension is capped until external injury data (7.C) is added.**
