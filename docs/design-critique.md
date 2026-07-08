# Design critique — senior modelling review (2026-07)

Status: **standing review**, written against the state after EXP-010 + the Steps 1–6
infrastructure build. Companion to `docs/breakthrough-plan.md` (diagnosis) and
`docs/implementation-plan.md` (execution). Every action item here is **folded into the
implementation plan** — this doc is the *reasoning*; the plan remains the only run order.

Posture: the program's core discipline is genuinely good — append-only ledger, no-leakage
folds, floor-adjusted gates, adopted-and-rejected both logged. The critique below is what a
reviewer should still lose sleep over: the assumptions nobody wrote down, the places the
eval can fool us, and the decompositions that leave signal on the table.

---

## 0. Verdict summary — the five changes that matter most

1. **The composition may be structurally biased against risers** (§3.1): composing
   `E[rate] × E[MPG]` drops the *positive covariance* between rate and minutes shocks —
   exactly the riser mechanism. One-day check, possible structural win. → **EXP-022**.
2. **The model literally cannot learn recency weighting** (§2.5): it only ever sees the
   pre-aggregated 5/4/3 blend. Feed per-season **lags** + era context. → **EXP-023**.
3. **Volume and efficiency are confounded in the 13 rate targets** (§4.1): split them,
   enforce identities (REB = OREB+DREB, PTS from makes), normalize by **pace/possessions**
  → **EXP-024** — this is also where the user's possessions/pace point lands.
4. **Eval integrity has three soft spots** (§3): pool-selection blindness to missed
   sleepers, eval-season reuse across ~15 experiments, and non-iid bootstrap. Fixes:
   actual-pool recall view, a **prospective 2026-27 holdout**, cluster bootstrap (built).
5. **Label survivorship** (§2.6): training only on players who logged ≥200 min next season
   teaches the model a world where nobody falls out of the rotation. Sensitivity check now,
   hurdle model if Phase 0 says fallers matter. → reserved **EXP-025**.

---

## 1. What is sound (keep, don't relitigate)

- Decomposition into minutes / rates / games with swappable scoring — right shape; minutes
  as the dominant error source is measured (EXP-001), not assumed.
- As-of-date framing (`project(data ≤ T)`) as the one interface for draft + in-season.
- The mover-bucket eval with signed bias per bucket, now floor-adjusted — the correct
  headline for this problem, and ahead of most published fantasy work in honesty.
- GBM-over-panel as the backbone: right for ~10³–10⁴ rows of tabular, exogenous-feature
  data. The alternatives table in `model-foundation.md` §3 holds up.
- Monte-Carlo ranges rather than pretending GP is a point estimate.

## 2. Hidden assumptions (each: assumption → consequence → action)

**2.1 Rate invariance to minutes ("per-36 mirage").** The composition assumes a player's
per-minute rate holds when his minutes change. It doesn't: bench players feast on second
units (their per-minute rates *fall* somewhat when promoted to starter minutes and
defenses/usage share change); very high minutes bring fatigue. Consequence: the **minutes
oracle (Step 3) overstates the minutes-driven share** of mover error — `rate × actual_MPG`
credits the rate model for holding at a role it never saw. *Action:* caveat written into
Step 3's readout; longer-term, an interaction feature (`proj_mpg × bench/starter prior`) or
role-conditional rates inside EXP-024.

**2.2 Era stationarity.** One panel from 2009-10 with no season/era feature assumes the
feature→outcome map is time-invariant across the pace boom, the 3-point explosion, the
load-management era and the 65-game award rule (2023-24). The rate *labels* are absolute:
a tree trained mostly on 2010s basketball systematically under-predicts 2020s 3PM/pace-
inflated rates. *Action:* era features + era-relative targets in **EXP-023** (predict rate
relative to that season's league mean; re-scale by the target season's context at
inference).

**2.3 GP ⟂ per-game in the Monte-Carlo.** `simulate_ranges` draws games and per-game value
independently. Reality: low-GP seasons correlate with lower per-game on return (minutes
restrictions, rust), and league-wide shocks move cohorts together. `SD_PG = 9` was tuned to
absorb this in *total* coverage — acceptable, but it means the ranges are right on average
while mis-shaped player-by-player. *Action:* revisit inside Step 14 (quantile ranges make
the per-game spread player-specific; the GP↔per-game coupling can be added as a copula/
conditional draw if coverage-by-bucket says it matters).

**2.4 Fixed bucket edges are scoring-config-conditional.** ±2/±6 fpts/g edges were chosen
under points scoring; every adopt/reject verdict is conditional on that config. Fine — but
un-written until now. *Action:* one line in the ledger template ("verdicts are
points-scoring-conditional"); re-run the headline eval once under the user's real league
config before draft day. Also check bucket-edge robustness (±1 shift) once per adopted
model — a verdict that flips when an edge moves 1 fpt/g was never real.

**2.5 The GBM can re-weight what it cannot see.** EXP-007's win was "learned shrinkage" —
but the model receives only the *pre-blended* 5/4/3 aggregate. It can rescale that blend;
it cannot express "trust last season more for 22-year-olds" because the per-season values
were destroyed before it ever saw them. EXP-008's failed *slope* features are not evidence
against lags — a slope is a lossy, noise-amplifying transform of the lags; raw lags let the
trees choose their own weighting, including age-interactions. *Action:* **EXP-023** — a
compact per-season lag block (MPG, GP, USG, TS, fpts/min for the last 3 seasons) alongside
the aggregates, with the feature-hygiene protocol (§5.1) to control redundancy.

**2.6 Label survivorship (min_label_minutes = 200).** Training labels exist only for
players who logged ≥200 minutes in the label season. Players who fell out of the rotation
or league — the far faller tail — are absent, so every level model is trained on a
survivor-biased world and is optimistic for marginal/aging players. The ranking backtest
has the same documented blind spot ("a projected star who missed the whole season simply
drops out"). *Action:* cheap sensitivity first (re-run EXP-013 control at
`min_label_minutes ∈ {0*, 100, 200}` — *0 needs a rates-undefined guard); if faller bias is
a Phase-0 priority, a two-stage hurdle (P(in rotation) × level | in rotation) is reserved
as **EXP-025**.

**2.7 Name joins are not identity joins.** DARKO/ADP/injuries all join on normalized names.
The league contains genuine collisions (Jalen Williams and Jaylin Williams were on the
*same OKC roster*). *Action:* every external join must (a) join on name+team when team
exists, (b) hard-fail on duplicate name_keys within a source rather than silently keeping
one, (c) keep the alias map append-only. Written into Steps 7–9 as an amendment.

**2.8 `rookie_reserve` must be fit on training seasons only.** The helper takes whatever
`season_stats` it is handed; in a backtest fold the caller must pass the training slice, or
the reserve constant leaks the eval season's rookie share. Small, but exactly the kind of
leak the skeptic pass exists for. Written into Step 6.

## 3. Leakage & evaluation-integrity risks

**3.1 The eval reuses the same four seasons across the entire program.** EXP-006…021+ are
all judged on 2022-23…2025-26. With ~15 experiments × multiple variants × three seeds, the
family-wise chance of a spurious "gate pass" somewhere is material even with CIs. This is
the quiet killer of modelling programs. *Actions* (now plan rule 10): (a) **prospective
holdout** — before the 2026-27 season starts, freeze and commit the board + predictions;
score them after the season; that is the only truly out-of-sample test this program will
ever get, and it costs one file. (b) Hyperparameter tuning (Step 5d) must be **nested**:
select params on folds ≤ 2021-22 (or leave-one-season-out), confirm once on the eval
window — never grid-search directly on the four verdict seasons. (c) Ledger entries for
adopted items note "eval-window-conditional until 2026-27 confirms."

**3.2 Pool-selection blindness (the missed-sleeper hole).** The mover eval pools on the
*model's own* top-150 — so a big riser the model ranked #200 never appears in any bucket;
the measured riser bias **understates** the true riser miss, and improvements that merely
promote already-pooled players look better than ones that find new sleepers. This is the
mirror image of the outcome-selection problem the floor sim handles. *Action* (Step 1
amendment): add an **actual-pool view** — same tables computed on the *realized* top-150 —
plus a recall line: "% of actual top-150 that the model pooled." Both views, always.

**3.3 Non-iid panel ⇒ overconfident CIs.** Player-seasons repeat players (autocorrelated
residuals) and teammates share team shocks; the pooled bootstrap treats rows as
independent, so the rule-8 CIs are somewhat too narrow. *Action:* cluster bootstrap by
PLAYER_ID — **implemented** (`bootstrap_bias_delta_ci(cluster="PLAYER_ID")`) and made the
default recommendation in rule 8 for pooled multi-season CIs.

**3.4 In-season leakage surfaces to watch (Step 10+).** Injury-report rows are dated but
occasionally corrected retroactively (treat the scrape archive as append-only, never
re-scrape history); "team games remaining" must come from the schedule as of T; lineup
data finalizes ~30–60 min pre-tip (a lineup-aware feature computed at midnight is fine for
ROS, leaky for same-day DFS-style claims — we only do ROS, keep it that way).

## 4. Correlation & statistical issues

**4.1 The 13 rate targets are trained independently but are strongly dependent.**
Three concrete costs:
- **Internal inconsistency:** projected REB ≠ OREB + DREB; FGM can exceed FGA at clip
  boundaries; PTS is modeled instead of derived from makes. Harmless-looking, but any
  scoring config that uses the components (DK uses REB; others use OREB/DREB) silently
  gets a different player than one using totals.
- **Wrong shrinkage structure:** volume (FGA/min, FTA/min, 3PA/min) is *sticky* and
  role-driven; efficiency (FG%, FT%, 3P%) is *noisy* and mean-reverts hard (3P% needs
  ~750+ attempts to stabilize). One squared-loss-per-raw-rate treats them identically, so
  efficiency noise leaks into projected scoring volume.
- **Composition covariance (the riser connection):** for each stat,
  `E[rate × MPG] = E[rate]·E[MPG] + cov(rate, MPG)`. Conditional on features, the residual
  covariance is *positive* — the same latent role shock lifts minutes and usage/rates
  together (a promoted player gets minutes *and* plays); so composing the two conditional
  means **under-projects exactly when both move up: risers**. Part of the stubborn riser
  bias may be this arithmetic, not missing features. *Check is nearly free:* the direct
  per-game-fpts model already exists (the quantile q50 head, or an L2 twin) — compare
  direct vs composed on the mover buckets; estimate `cov(resid_rate·MPG)` on the panel; if
  real, add the covariance correction (or blend direct/composed). → **EXP-022, run first.**

*Action:* **EXP-024** re-targets the rate layer: volume rates + efficiency ratios +
identities (REB, PTS derived; FGM = FG2%·2PA + FG3%·3PA bounded by construction), with
efficiency targets given heavier shrinkage (their own regression constants / priors).

**4.2 Pace / possessions confound (user's point — correct, and we half-hold the data).**
Per-*minute* rates mix player skill with team pace: a move from a 96-possession team to a
103-possession team is a mechanical ~7% rate lift no skill model should have to learn from
scratch. Per-100-possession rates + a projected team-pace multiplier separate "how much he
does per opportunity" from "how many opportunities the environment provides" — and the
target team's prior-season pace is a **preseason-known feature for team-switchers**.
Data: the Advanced merge in `player_season_stats` should carry `PACE`/`USG_PCT` (verify the
cached columns locally; if PACE is absent, one cheap `leaguedashteamstats` pull per season
supplies team pace). Folded into **EXP-024**. Full possession-ledger modelling
(`minutes × pace × usage share × efficiency`) is the *end state*; EXP-024's pace-normalized
rates capture most of the value at a fraction of the machinery.

**4.3 Heteroscedasticity:** constant SD_PG=9 across players is wrong player-by-player
(planned fix = quantile heads, Step 14 — no change, just noting it closes this).

**4.4 Seed and sampling noise on small buckets:** handled by rule 8 (three seeds + CI);
with the cluster bootstrap (§3.3) this is now adequate.

## 5. Feature engineering review (the user's brain-dump, systematized)

**5.1 Redundancy protocol (make it standing policy).** GBMs tolerate correlated features
for accuracy but pay in variance on a ~5k-row panel, diluted importances, and slower A/Bs.
Policy (added to plan rule 11): every new feature group ships with (a) permutation
importance on the validation fold, (b) a correlation sweep vs existing features — any
|ρ| > 0.95 pair must justify both members or drop one, (c) the group A/B *as a group*
(EXP-008's lesson: judge groups, not single features).

**5.2 Lags > aggregates-only; EWM with fitted half-lives in-season.**
- Preseason (season-granular): per-season **lags** (EXP-023) — the aggregates stay (good
  denoised baseline), lags add the trajectory the blend destroys.
- In-season (game-granular, Step 10): replace the hard last-N window with **per-stat EWMAs
  with fitted half-lives** — steals/blocks stabilize in a handful of games, 3P% barely
  stabilizes in a season; one window for all stats is provably wrong. Fit half-lives per
  stat on the cutpoint panel (grid {5, 10, 20, 40 games}); DARKO's core insight, borrowed
  at feature level. Written into Step 10.
- Transforms: trees are invariant to monotone *feature* transforms — do not waste time
  transforming inputs. Transforms matter on the **target/loss** side only (delta targets =
  EXP-013a; logit for bounded share targets = Step 6; efficiency ratios = EXP-024).

**5.3 Foul trouble (user's point — a real, free feature).** PF is in the Base pull but not
in COUNTING and not a feature anywhere. Foul *rate* (PF/min) is stable, skill-like, and a
hard mechanical cap on minutes (a 5.5-fouls-per-36 big cannot play 34 MPG; coaches bench
foul-prone players early). Highest-leverage as a **minutes/allocation feature**
(`pf_per_min`, lagged), not a scoring stat. Added to Step 6's feature list (and available
to EXP-023's lag block). Cost: one column.

**5.4 Blowouts / garbage time.** Two distinct contaminations: starters *lose* minutes on
frequently-blown-out (or blowout-winning) teams; deep bench *gains* garbage-time rates
that don't survive promotion to real minutes. Season-level this mostly nets out but biases
by team quality; window-level (recency, EWMAs) it's louder. Pragmatic handling, in order
of cost: (a) team point-differential / blowout share as a *context feature* (needs one
team-game-log pull; margins aren't derivable from player logs); (b) exclude |margin| ≥ 25
games from recency windows in Step 10 (flag on the game row once team logs exist);
(c) full play-by-play garbage-time filtering — **not worth it** at this stage (see §7).
(a)+(b) written into Step 10.

**5.5 Injuries & role changes, in-season (beyond the preseason 7.C plan).** What the
current plan under-specifies, now added to Step 10's feature block:
- **Teammate-vacated minutes, live:** minutes/usage of currently-OUT teammates (from the
  injury feed), same-position-weighted — the single biggest waiver signal ("star out 6
  weeks → who absorbs").
- **Return-from-absence ramp:** games since return from a ≥5-game absence + a
  minutes-restriction flag (recent MPG ≪ pre-injury MPG) — prevents the model reading a
  rust-limited star as a faller.
- **Schedule-aware ROS totals:** remaining value must use the player's *team's actual
  remaining schedule count* as of T (teams differ by 1–3 games at any date), plus
  back-to-back density for GP risk. Never `82 − games_so_far` generically.
- **Trade/role events:** the post-trade split (built, EXP-012) plus a preseason
  changed-team flag (trivial once EXP-016 rosters exist).

## 6. Situational handling — one table

| Situation | Current handling | Gap | Action (where) |
|---|---|---|---|
| Season-long injury risk | GP model + MC pool by age | player-agnostic tail | per-player tails (EXP-015b) |
| In-season "out X weeks" | overrides.yaml (Step 12) | no auto feed yet | injury feed = same scraper as EXP-015 (Step 12) |
| Teammate injury opportunity | — | biggest waiver signal missing | live vacated-minutes features (Step 10 amendment) |
| Return-from-injury ramp | — | rust read as decline | ramp/restriction features (Step 10 amendment) |
| Preseason role change (trade/FA) | context features (parked), allocation (Step 6) | position-blind, EOS-roster leak | EXP-014 + EXP-016 (planned; unchanged) |
| Mid-season trade | post-trade split (built) | — | run EXP-012 |
| Foul trouble | — | free minutes-cap signal | pf_per_min → Step 6 / EXP-023 |
| Blowouts / garbage time | — | window contamination | margin features + window filter (Step 10 amendment) |
| Rest / load management / tanking | skip_last trim (built) | verdict pending | run EXP-012 |
| Pace / possessions | — (deferred in Stage 3) | mechanical rate confound | EXP-024 |
| Rookies | excluded from panel & eval | whole board segment | Stage 4, unchanged priority; allocation's rookie_reserve absorbs their *minutes* pressure |

## 7. What I would **not** do (scope discipline)

- **Play-by-play ingestion** (lineup-level on/off, garbage-time filters, RAPM): an order of
  magnitude more data engineering for third-order accuracy at this stage. Revisit only if
  the in-season engine plateaus.
- **Rebuild a Kalman/state-space skill engine:** settled in `model-foundation.md` — consume
  DARKO; spend effort where the fantasy edge is (minutes/role/news).
- **Deep/sequence models on game logs:** ~45k cutpoint rows is still tabular-GBM territory;
  revisit at ≥10× the data or with transfer from public embeddings.
- **A full possession-ledger simulator** (team offense → shot distribution): elegant, but
  EXP-024's pace-normalized rates capture most of the value for ~5% of the machinery.
- **More preseason feature archaeology on own-history:** the four-experiment meta-finding
  stands; EXP-022/023/024 attack *structure* (composition, lags-vs-blend, volume/efficiency
  /pace), not new own-history features. If those don't move risers, the answer is Phase 2/3
  data, full stop.

## 8. Where this landed in the plan (delta list)

- **Rule 10** (prospective holdout + eval-reuse guard + nested tuning) and **rule 11**
  (feature-hygiene protocol) added to `implementation-plan.md` §0.
- **Step 1 amendment:** actual-pool recall view; cluster bootstrap (implemented); bucket-
  edge sensitivity check.
- **Step 3 amendment:** minutes-oracle overstatement caveat (§2.1) in the readout.
- **Step 5d amendment:** nested tuning (params selected on ≤2021-22 folds only).
- **Step 6 amendments:** `pf_per_min` feature; logit-share option; `rookie_reserve`
  train-slice-only note.
- **New Phase 1.5 (Steps R1–R3):** EXP-022 composition-covariance check → EXP-023 lags +
  era context → EXP-024 volume/efficiency/pace re-decomposition. Sequenced after Step 6,
  before Phase 2 — all run on data already held.
- **Steps 7–9 amendment:** name-join hardening (§2.7).
- **Step 10 amendments:** EWMA fitted half-lives; live teammate-vacated minutes;
  return-ramp features; schedule-aware ROS; blowout margin features + window filter (needs
  a team-game-logs pull — added to the Step 0/10 data list).
- **EXP-025 reserved:** rotation-survival hurdle model (label survivorship, §2.6).
- **Ledger + README pointers updated.**
