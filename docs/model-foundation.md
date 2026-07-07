# Model foundation — design note & architecture decision (Stage 7)

Status: **proposal for review** (2026-07, rev. 2 — now with daily in-season updating as a
first-class requirement). Companion to `ROADMAP.md` §Stage 7 and `EXPERIMENTS.md`. Answers:
**(1) is this effort worthwhile?** and **(2) which foundational model should we build on?** — weighing
the real alternatives rather than asserting one.

> **Revision note (rev. 2):** rev. 1 framed this as a one-shot *preseason draft* projection and, on
> that basis, dismissed DARKO-style daily-updating engines as irrelevant. The user clarified the real
> requirement: **the system runs all season** — preseason draft *and* **daily-updating** projections
> for waivers and trade value as new box scores + news arrive. That makes daily/in-season updating a
> core requirement and re-opens the architecture question. This revision re-weighs accordingly.

---

## 0. The goal, stated precisely

For an NBA **fantasy points** league, produce, **for the top ~100–150 relevant players, a projected
rest-of-season production *level* that is right — especially for players whose level is changing
(risers & fallers) — and that updates every day** as games and news come in.

Two deliverables from **one engine**:
- **Preseason draft board** — projection as of the season start (T₀).
- **In-season rest-of-season (ROS) projection**, refreshed daily — the waiver-wire and trade-value
  tool. *This is the highest-value use:* catching a riser **early**, from a small in-season sample,
  before the waiver market does.

Design consequence: the projection must be a **pure function of information available as of a date
T** — `project(data ≤ T) → ROS line + fantasy value` — runnable at any T. T₀ = draft; every
subsequent day = an updated ROS number. Everything below follows from this "as-of-date" framing.

---

## 1. Is this worthwhile? (the honest answer)

**Yes — and the in-season use strengthens the case.** Split the problem into a skill/role dimension
(genuinely improvable) and an availability dimension (capped preseason, but *much more knowable
in-season*).

**Why it's worth it:**
- The current model's miss on movers is a **systematic bias, not random noise** — built only from a
  player's *own* recency-weighted history, it mean-reverts and mechanically under-projects risers /
  over-projects fallers. Correcting a systematic bias with unused signal is exactly where effort pays.
- Movers aren't random: the research (below) ties them to identifiable conditions — age 22–24, prior
  gradual improvement, usage↑ at held TS%, and above all a **change in opportunity** (a teammate
  leaves, a role opens, an injury vacates minutes). The current model uses none of these.
- **In-season, the payoff compounds.** The waiver edge is being *early and calibrated* on "is this
  6-game surge a real role change or noise?" — a question a disciplined updating model answers better
  than the market's gut. And **injury news makes availability directly knowable in-season** ("out 2
  weeks"), so the preseason R²≈0.03 games-played ceiling (EXP-004) **does not bind in-season** — a
  whole dimension that was capped preseason opens up once we ingest news.

**The honest caveat (preseason only):** at draft time, games-played is still ~unpredictable from box
scores; only **external injury history (7.C)** helps there. In-season, news replaces that guesswork.

**Net:** worthwhile on skill/role/trajectory year-round, and on availability *in-season* via news.
Expect "systematically less biased on movers, and earlier on in-season risers" — not "predicts every
breakout." Opportunity-driven moves are forecastable; pure skill leaps partly aren't.

---

## 2. What the research says, and how it becomes features

Reviewed 2026-07. Takeaways map to model *inputs*, largely independent of algorithm:

- **DARKO** (Bayesian/Kalman, per-possession, **daily-updated** box-score projections): its design is
  *exactly* the daily-updating skill engine our in-season use wants — intelligent per-stat recency
  weighting, aging in the transition, per-possession normalization, updated every game. **Rev-2
  implication:** this is no longer "irrelevant" — it's a template. But it is a *box-score skill*
  engine; it is **blind to exogenous context** (roster turnover, news, depth charts) — the dominant
  fantasy levers. → either borrow its ideas as features, **or consume DARKO/DPM itself as an input**
  (see §4) and spend our effort on the context layer it can't see.
- **RAPM family (EPM, LEBRON):** learn the map from features to next-period value; confirms the
  learned-mapping pattern over hand-set constants.
- **Breakout studies (Bruin/Dartmouth/HSAC):** breakouts center at **age 22–24**; **less-established
  players have more room to improve** (mean-reversion is real but *asymmetric* for the young);
  breakouts follow **prior gradual improvement** and **usage↑ at maintained TS%**. → features: age,
  age², experience, own multi-year **slopes/trends**, usage trend, TS% stability, age×trajectory.
- **Trade/roster research:** the **vacancy → redistribution → market-lag** chain — a departing
  high-usage player's minutes/usage are absorbed by teammates and the market underprices the
  beneficiaries. → features: **vacated team minutes/usage**, incoming-player compression (needs
  transactions/roster data). In-season, the same mechanic fires on every injury — the waiver engine.
- **Market/consensus (ADP, FantasyPros, DARKO):** consensus lowers variance but can wash out an edge.
  → use as **benchmark**, as a **disagreement finder** (our biggest deltas vs ADP/market = the
  actionable calls), and possibly as a **core skill input** (§4).

Sources: darko.app/about & nbastuffer DARKO explainer; Bruin & Dartmouth breakout studies; Athlon
trade second-order-effects & usage pieces; `nbainjuries` / prosportstransactions for injury data;
FantasyPros/RotoWire on ADP.

**Theme:** across good systems the algorithm matters less than **feeding the right signals** — and
the mover-driving signals (trajectory, opportunity, news) are exogenous tabular inputs. That, plus
the as-of-date requirement, drives the choice below.

---

## 3. The alternatives, re-weighed for daily updating

Discriminating constraints: **as-of-date / daily-updating**, **small data** (~5–6k season pairs; more
if we snapshot in-season cutpoints), **the mover signal is exogenous/contextual + news-driven**, and
the need for **fast iteration + interpretability**.

| Option | Daily/in-season updating | Ingests context + news | Small-sample skill updating | Iteration speed | Verdict |
|---|---|---|---|---|---|
| **A. Marcel + hand adjustments** | Re-run only; no real recency logic | No | Poor | Fast | Baseline/fallback |
| **B. Learned as-of-date GBM panel** (proposal) | **Yes — re-run f(data≤T) daily** | **Yes, natively** | Good (learns shrinkage from snapshots) | **Fast** | **Recommended backbone** |
| **C. Online state-space / Kalman (DARKO-style)** | **Yes — native per-game update** | **No** (box-score only) | **Best, principled** | Slow to build | Consume as input, or upgrade skill layer later |
| **D. Hierarchical Bayesian partial-pooling** | Batch re-fit | Partly | Good, calibrated | Slow (MCMC) | Later upgrade for the *ranges* |
| **E. Neural / sequence on game logs** | Yes | Yes | Data-hungry → overfits | Slow | Reject for now |

**Reasoning (what changed in rev. 2):**
- **B is still the recommended backbone — for a sharper reason now.** In a *fantasy* system, value is
  dominated by **minutes, role, and news**, and only a feature-based model ingests those alongside box
  scores **in one place**. Daily updating is achieved by re-running `f(data ≤ T)` with fresh recency +
  news features — no online machinery required. Train it on **as-of-date snapshots at many in-season
  cutpoints** (not just season boundaries) so it learns the right small-sample shrinkage ("6 hot games"
  → how much to move). It still **subsumes Marcel** (own-rate + age ⇒ it rediscovers recency/mean-
  reversion/aging), so the floor is "no worse," and Marcel stays as fallback.
- **C rises sharply in relevance but not as the base.** DARKO-style online updating is the *ideal* for
  the pure box-score **skill** sub-layer and the small-sample "is it real?" question. But it is blind
  to the exogenous context/news that dominates fantasy, so it can never be the whole system — it would
  always need a separate minutes/role/news layer bolted on. Two better ways to capture its value:
  **(a) consume a public daily skill feed (DARKO/DPM) as a *feature*** — don't rebuild a Kalman we can
  get for free — and/or **(b)** revisit a home-grown online skill estimator *only if* the eval shows
  the GBM handles small in-season samples poorly.
- **D** stays a later upgrade for **uncertainty** (which we already cover with Monte-Carlo), not the
  point-estimate base. **E** is still too data-hungry for ~thousands of rows.

---

## 4. Recommended foundation (detail)

**A learned, decompositional, as-of-date panel model**, run daily.

- **Interface:** `project(data ≤ T) → ROS per-game line + fantasy value`, for any T. T₀ = draft
  board; daily thereafter = waiver/trade tool. Trained on as-of-date snapshots across seasons **and**
  in-season cutpoints.
- **Decomposition (unchanged; each layer updates as T advances):**
  1. **per-minute skill rates** — update as box scores arrive; core challenge is small-sample
     shrinkage. *Candidate input:* a public daily skill feed (DARKO/DPM) as a feature (§3 C-a).
  2. **minutes / role** — the dominant fantasy lever and the **most news-sensitive** layer (teammate
     out → minutes up); driven by recent-minutes trend + depth chart + injury/lineup news + vacated
     minutes.
  3. **availability (remaining games)** — in-season largely **news-driven** ("out 2 weeks") plus a
     distribution; preseason falls back to the durability model + injury history (7.C).
  Compose → ROS line × projected remaining games → fantasy value; **scoring stays swappable**;
  uncertainty via the existing Monte-Carlo layer.
- **Model class:** LightGBM (already a dep), one model per target; rate models share features. Fast
  nightly re-run.
- **Feature families:** own multi-year **levels + slopes/trends** (breakout signal) · **recent-window
  (last-N-games) vs season splits** (in-season riser detection) · age/age²/experience · role & usage ·
  **team-context / vacated minutes** (7.A) · efficiency/TS% + stability · **injury/lineup news status**
  (in-season) · optional **public skill feed** and **market/ADP** (7.E) · per-stat recency summaries.
- **New data the season-long use requires:** a **daily news/status feed** — injury reports, starting
  lineups, transactions (`nbainjuries` / official injury report / prosportstransactions), on top of
  the nightly box-score pull. This is a real added pipeline (see ROADMAP 7 data note).
- **Discipline:** strict as-of-date, no-leakage, **walk-forward within season as well as across
  seasons**; refit per fold; time-series CV.

**Unchanged:** decomposition philosophy, swappable scoring, Monte-Carlo ranges, Marcel as fallback +
"did we lose signal?" baseline.

---

## 5. How we'll know it worked (and de-risk it)

The eval is the safeguard (ROADMAP §7.0), now **as-of-date**:
- Draftable top ~150; **per-game level** error/bias scored separately from availability.
- **Mover-segmented signed bias** — bucket by *actual* change; the deliverable is shrinking the
  riser-under-projection / faller-over-projection bias.
- **In-season as-of-date eval:** at cutpoints through the season, score the ROS projection vs the
  actual remainder — *especially* early-season, where the waiver edge lives ("given 10 games, did we
  call the riser?"). Directional Δ capture: do we move players the right way, early?

**Validation sequence (each → `EXPERIMENTS.md`, adopt or reject; EXP-006..009):**
1. Build the as-of-date eval; **quantify the current model's mover bias** (baseline the disease),
   preseason **and** at in-season cutpoints.
2. Learned as-of-date model on Marcel-equivalent features → expect ~**tie** (signal-safe swap;
   fallback to Marcel if it loses).
3. **+ trajectory/slope + recent-window features** → does it catch in-season risers earlier and cut
   the young-cohort riser bias?
4. **+ team-context / vacated-minutes (+ news, in-season)** → the decisive lever for both the draft
   role-change subpopulation and the waiver engine.

**Fallback:** any layer that doesn't beat Marcel on the mover buckets → keep Marcel there, log the
negative result. Because B subsumes Marcel, the floor is "no worse."

---

## 6. Recommendation

Adopt **Option B** — a learned, decompositional, **as-of-date** GBM panel that runs daily — as the
backbone, because in a fantasy system minutes + role + news dominate value and only a feature model
ingests them alongside box scores in one place, updating by re-running `f(data ≤ T)`. **Borrow
DARKO's daily-skill idea by *consuming* a public feed as a feature rather than rebuilding a Kalman**;
keep a home-grown online skill estimator (C) and hierarchical-Bayes ranges (D) as eval-gated future
upgrades. Encode the breakout research as trajectory/recent-window features and the trade research as
vacated-minutes features; use the market as benchmark + disagreement-finder.

**Worthwhileness:** real, correctable, unused signal on the skill/role/trajectory dimension
year-round; availability opens up **in-season** via news (the preseason ceiling doesn't bind once
games start); the one honest cap is *preseason* games-played, addressable only with injury history
(7.C). The season-long, daily-updating use — waivers and trades — is where this system earns its keep.

---

## 7. Data pipeline shape (season-long)

Two cadences feed the one as-of-date engine:

- **Preseason / periodic (already built):** `scripts/pull_data.py` pulls per-season `player_season_stats`,
  `player_game_logs`, `player_bio`, `team_rosters`; curves (aging / minutes / durability / GP pool) are
  fit once. Refresh weekly-ish before the draft as rosters settle.
- **Nightly, in-season (new — needed for the daily ROS use):**
  1. **Box scores** — incremental `player_game_logs` for games since the last pull (early AM, after
     stats settle). Append-only to the cache, keyed by game date.
  2. **News / status feed (new fetchers):** injury report + designations (out / questionable / GTD),
     **starting lineups**, and **transactions** (`nbainjuries` / NBA official injury report /
     prosportstransactions). Lineups finalize ~30–60 min pre-tip, so a late-afternoon refresh is the
     one that matters for same-day decisions; overnight is enough for ROS/waiver planning.
  3. **Re-project:** run `project(data ≤ today)` → updated ROS board + risk ranges.
- **Storage discipline:** everything append-only and **date-stamped**, so `project(data ≤ T)` is a
  clean filter (`rows.date ≤ T`) — this is what makes the same code serve the draft (T₀), any
  backtest cutpoint, and today. Never overwrite history; that's how in-season no-leakage stays honest.
- **Optional external inputs:** a public daily skill feed (DARKO/DPM) and market/ADP — pulled on their
  own cadence, joined by player + date.

## 8. Picking this up later — concrete run order

> **⚠️ SUPERSEDED (2026-07):** this section's run order (EXP-006…009) has been **completed** —
> see `EXPERIMENTS.md` for the results. The current run order lives in
> [`docs/implementation-plan.md`](implementation-plan.md) (the step-by-step execution spec),
> with the post-EXP-010 diagnosis in [`docs/breakthrough-plan.md`](breakthrough-plan.md).
> Kept below unedited as the historical record of the original plan.

Do these in order; log each to `EXPERIMENTS.md` (adopt/reject) so the trail stays complete.

0. **Prereqs (local — the remote/web env can't reach `stats.nba.com`):** `pip install -e .`, then
   `python scripts/pull_data.py --seasons 2009-10 … 2025-26 --datasets player_season_stats
   player_game_logs player_bio team_rosters`. Confirm the current model still runs
   (`python scripts/project.py --target 2026-27 --ranges`).
1. **EXP-006 — as-of-date eval harness (keystone).** Extend `models/backtest.py` (or a new
   `models/eval_movers.py`): draftable top ~150; per-game level MAE/RMSE + **signed bias per
   YoY-change bucket**; directional Δ capture; run at **preseason and in-season cutpoints**. First
   output = the current v2m model's mover bias — the number every later experiment is judged against.
2. **EXP-007 — learned decompositional model, Marcel-equivalent features.** New
   `models/learned.py`: LightGBM per target (rate per stat, MPG, GP) over the as-of-date panel; only
   features Marcel already uses. Expect a **tie** on EXP-006 metrics → proves the swap is signal-safe.
   Keep Marcel as fallback.
3. **EXP-008 — + trajectory / recent-window features.** Slopes, last-N-games vs season splits,
   age×trajectory. Target: shrink the riser under-projection bias (young cohort + in-season early risers).
4. **EXP-009 — + team-context / vacated-minutes features.** Needs a transactions/roster-turnover pull.
   The decisive lever for both draft role-changes and the in-season waiver engine.
5. **In parallel:** build the nightly news/status ingestion (§7) so in-season availability + role can
   respond to "out 2 weeks" and lineup changes. **EXP-010+:** injury history (7.C), consume a public
   skill feed / market (7.E), hyper-parameter tuning.

**Guardrails to keep the findings trustworthy:** strict date-based no-leakage (train only on
`date < cutpoint`; refit curves/models per fold); judge each layer on the **mover buckets**, not
aggregate correlation (aggregate hides the whole point); keep Marcel as the "did we lose signal?"
baseline — because the learned model subsumes it, the floor is "no worse."
