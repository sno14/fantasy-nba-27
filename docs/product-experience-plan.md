# Product experience implementation plan

Created: 2026-09-29. Status: active; P1a–P3 implemented and verified locally.

This is the execution plan for the experience and feature discussion of 2026-09-29.
It extends the shipped views in [ui-views-plan.md](ui-views-plan.md), which remains
the record of V1–V6. Model work and the standing calendar remain owned by
[implementation-plan.md](implementation-plan.md); scheduled draft verification,
analyst re-review, dual freeze and opening-night updates take precedence.

## 1. Outcome and current observations

Help a manager move from inspecting projections to preparing a draft, understanding
a change, and comparing roster decisions with the information already available.

The public site has a board, tiers, team summaries, comparisons, a manual mock and
browser-local priority targets. The local app additionally has live draft state,
roster ownership, nightly ROS snapshots, trends, waivers, weekly schedules, matchup
views, analyst provenance and review. Build on these features rather than duplicating
them under different names.

Observed on 2026-09-29:

- At 1440px, the public board's 17 columns extend beyond its visible container.
- At 390px, the public table is about 712px wide; FP/G requires horizontal scrolling.
- Radar explanations rely substantially on hover text; they need a tap/keyboard path.
- The public board forgets filters, sorting and display preferences after a reload.
- Public summary cards describe the dataset more than the manager's draft preparation.
- Local My Team and Matchup sum all scheduled roster production. Daily congestion is
  reported separately; totals do not account for the best feasible starting lineup.
- The local app has in-season Trends, but published preseason changes have no history UI.

The public site was inspected in a browser. Local observations are from source and
documentation; the local server was unavailable during the initial visual review.

## 2. Boundaries and conventions

1. **Product work first.** Rendering, persistence, arithmetic and workflow changes
   do not change projections. Any new predictive method is a separately specified,
   evaluated and logged modelling experiment; rejected methods stay rejected.
2. **Two delivery surfaces.** Public features must run without a writable backend.
   Credentials, private rosters, raw BBM notes and analyst rationales stay local.
   Any public explanation must use the existing redacted fields or an explicitly
   reviewed public summary, never expose the private source text accidentally.
3. **Stable semantics.** Public ordinal rank and tiers mean FP/G. Local safe rank is
   a distinct season-value view. Sorting a column does not redefine either rank.
   A future ranking mode needs matching rank, tier and Radar semantics throughout.
4. **Known inputs only.** Unknown position, missing ADP, absent schedule and stale
   ownership have explicit states. ADP is an availability reference, not a calibrated
   chance that a player survives to a pick.
5. **Descriptive comparisons.** No H2H win probabilities, weekly simulations using
   season-range variance, or new prescriptive draft scoring. Practice drafts use
   stated selection rules, not a claim about actual opponent behaviour.
6. **Append-only histories.** Snapshot archives and override histories remain dated
   and append-only. Never manually edit the generated board, roster map or overrides.
7. **Personal data.** Version browser storage, tolerate unavailable/corrupt storage,
   migrate valid older targets, and never place personal notes in shared URLs.
8. **Accessibility.** Every action is available by keyboard and touch. Preserve focus,
   label icon controls, announce counts and provide a readable narrow-screen layout.

## 3. Delivery order and tracker

Relative scope is an estimate of implementation complexity, not a time commitment.
Each row ships independently with the acceptance checks below.

| ID | Deliverable | Surface | Scope | Depends on | Status |
|---|---|---|---|---|---|
| P1a | Board column presets, mobile cards, tap explanations, saved preferences | Public | Small | Existing export | Complete locally, 2026-09-29 |
| P1b | Local board/navigation parity and ranking explanations | Local | Medium | P1a conventions | Complete locally, 2026-09-30 |
| P1c | Shareable player/compare URLs and watchlist backup/restore | Both | Small–medium | P1a storage conventions | Complete locally, 2026-09-30 |
| P2 | My Draft Plan workspace and useful draft summary cards | Both | Medium | P1c; existing targets and picks | Complete locally, 2026-09-30 |
| P3 | Practice My Draft with saved runs | Public, then local | Medium | P2; existing snake/slot logic | Complete locally, 2026-10-02 |
| P4 | What Changed: published history and watched-player changes | Both | Medium | P1c; dated exports | Planned |
| P5 | Rotation & Opportunity team detail | Local, curated public | Medium | Existing team/analyst data | Planned |
| P6a | Feasible daily lineup and usable-production calculation | Local | Medium | Ownership, eligibility, schedule | Planned |
| P6b | Personal Streaming Planner and add/drop scenarios | Local | Large | P6a; league acquisition rules | Planned |
| P7 | Trade Sandbox with both sides and uneven trades | Local | Large | P6a; ownership and schedule | Planned |
| P8 | Today home page evolving My Team | Local | Medium | P4 and P6 | Planned |
| P9 | Player minutes scenario explorer | Local, then public | Medium | Verified decomposition inputs | Planned |

P1a–P3 are complete locally. The next implementation is P4 What Changed?
The remaining rows are documented scope, not an assertion that they are implemented.

## 4. P1 — board usability and workspace foundations

### P1a: public board

Files: `static/index.html`, `static/app.js`, `static/style.css`.

- Replace the fixed wide header/row duplication with one column definition list.
- Default **Draft** preset: compare control, FP/G rank, player/team, position, FP/G,
  ADP and Radar. Provide **Performance**, **Risk** and **Full detail** presets.
- Performance includes prior-season production, projected change and minutes.
  Risk includes GP, season-total range, median and relative range width.
- Provide **Automatic**, **Table** and **Cards** layouts. Automatic uses cards at
  widths up to 760px and a table above it. Users can still inspect the full table.
- Cards show name/team/position, FP/G, ADP, Radar, compare and priority actions without
  sideways scrolling. Expand for GP, MPG, change, range and the remaining board fields.
- Keep search, filters, limits and sort identical across layouts. Add a sort selector
  for card users, visible sort direction, matching table headers and empty states.
- A Radar chip opens the existing player detail, where its explanation is visible.
  Do not generate new explanations or reveal private rationales.
- Persist preset, layout, filters, limit and sorting under a versioned preferences
  key. Validate saved values against allowed values and current teams/tiers.
- Keep existing target, compare and mock storage keys compatible. A storage failure
  must not prevent browsing or interacting during the current session.
- Explain near the controls that rank/tiers reflect FP/G and ranges reflect season
  totals. This release does not introduce a second public ranking policy.

Acceptance:

- All four presets show matching headers/cells and the same underlying values.
- At 320px, 390px and 760px, automatic cards show FP/G and ADP within the viewport;
  the page has no horizontal overflow. Explicit Table retains its scroll container.
- At 1440px, Draft columns fit the visible board container.
- Search, sort, compare, target edit and Radar detail work in both layouts.
- Preferences survive reload; obsolete teams/tiers and malformed JSON recover safely.
- Existing manual mock, undo, tiers, team drill-down and comparison still work.
- Generated `static/data/board.json` is unchanged by this work.

### P1b: local parity and navigation

Files: `frontend/src/views/DraftBoard.tsx`, `frontend/src/components/DataTable.tsx`,
`frontend/src/App.tsx`, `frontend/src/index.css`; reusable preference hook in `lib/`.

- Reuse the same preset names and essential fields, preserving local-only actuals,
  analyst details and ranking stance. Do not hide historical evaluation controls.
- Explain the selected stance beside it: FP/G, safe season value, median, floor or
  ceiling as actually supported by the API. Sorting remains distinct from ranking.
- Add narrow-screen navigation and accessible sort controls to the existing shell.
- Use shared table/card conventions before extending them to ROS and waivers.
- Keep existing rank and tier calculations intact; any change gets a separate spec.

Acceptance: TypeScript/build pass; current/historical boards retain their semantics;
navigation, table and comparison tray fit a phone; preference recovery works.

### P1c: links and personal-data portability

- Public hash routes support a player ID and 2–4 comparison IDs, and optional public
  filters. Local URLs use existing routes and validated query parameters.
- Define precedence: explicit URL state, valid saved preferences, defaults.
- Support back/forward and copied links; gracefully handle IDs missing from a refresh.
- Export versioned JSON containing season, target IDs, take-by picks and notes.
  Import previews merge/replace choices, validates types/limits and shows unknown IDs.
- Notes render as escaped text. Export/import never modifies the projection snapshot.
- A storage failure shows a small message explaining that changes are session-only.

Acceptance: round-trip notes including Unicode; invalid files leave current state
intact; refresh/back/forward reproduce public context; URLs contain no private notes.

Implemented contract (2026-09-30):

- Public examples: `#board?player=203999`, `#compare?ids=203999,1641705`,
  `#board?team=DEN&preset=performance&layout=cards`. A player can open over any
  existing view, including Compare. Closing the dialog, navigating and changing
  filters create browser history; search typing replaces the current entry.
- Local examples: `/players/203999`, `/compare?ids=203999,1641705`,
  `/?target=2026-27&stance=safe&preset=risk&layout=cards`. Existing routes remain
  available. Explicit validated query settings override saved preferences;
  omitted settings use saved preferences and then defaults. Complete view settings
  are written into the current URL so back/forward restores the previous context.
- Invalid settings get a recovery message; metadata-dependent season/model/team
  settings recover against the loaded board. Duplicate comparison IDs collapse
  in order. Empty and single-player selections have a choose-players prompt;
  unavailable IDs have a removal action. Public missing-player cards explain that
  the ID is absent from the published snapshot. Local player failures use the
  existing error state; a freshly opened player link can return to Draft Board.
- Copy link is available on the board, player and comparison views. When clipboard
  access fails, a selectable text field contains the link. Copying a board with
  Watchlist selected changes that shared filter to All and explains that targets
  should be transferred with a backup. Links include no target notes or picks.
- The backup schema is shared in `static/workspace.mjs`, imported into the React
  bundle and used directly by the public site. It contains
  `format: "fantasy-nba-watchlist"`, `version: 1`, `season`, `exportedAt` and
  `targets: [{ playerId, takeBy, note }]`. `playerId` is a positive safe integer;
  `takeBy` is null or a whole overall pick from 1 to 10,000; `note` is a string of
  at most 10,000 characters. At most 1,000 targets and a 1 MB JSON file are accepted.
  Export also checks file size, so downloaded backups can be imported again.
- Import validates the entire file before opening its preview. Cancel leaves state
  intact. Merge keeps existing targets and uses imported values for matching IDs;
  Replace replaces the entire watchlist, including allowing an empty list. Unknown
  IDs are shown and retained for future boards. Duplicate IDs, wrong seasons,
  unsupported versions, invalid values and oversized files are rejected atomically.
- Watchlists belong to the current target season even when the local board is
  viewing a historical season. Public exports now include season metadata; existing
  snapshots recover the season from their title. Browser origins retain separate
  storage, so the file is the explicit transfer between ports 8787 and 8788.
- Local target state is shared across mounted views and survives navigation when
  storage is blocked. Both interfaces report session-only storage and still allow
  a backup download. Imports render notes as text and perform no backend writes.

Reusable verification: `node tests/test_workspace.mjs` covers the shared contract,
Unicode, invalid files, limits, wrong seasons and comparison ID validation. Browser
walkthroughs cover both interfaces and both directions of file transfer; details are
recorded in the work log below.

## 5. P2 — My Draft Plan

Public route: `#plan`. Local route: `/draft-plan`. Extend the existing target store,
not a parallel watchlist. Proposed target additions: preferred round, backup group,
priority order and status. Keep take-by picks and free-text notes.

Layout: draft position/settings, round groups, remaining targets, backups, and a
compact roster-fit summary. Provide a clear link to the existing draft/mock room.

- Compute the manager's upcoming snake picks from the configured team count and
  draft position; local live order is usable only when verified, never a placeholder.
- Display pick/round ADP references with the source date. Do not infer survival odds.
- Picks mark targets taken by me, taken by another team, or still available.
- Highlight take-by deadlines and remaining players in an FP/G tier. A warning is
  descriptive and does not silently reorder the authoritative board.
- Allow backups within each round/group and editing from either board or plan.
- Summary cards: next known pick, remaining personal targets, overdue targets and
  open starting positions. Unknown order/eligibility gets an explicit placeholder.

Files: static views/renderers and styles; `frontend/src/views/DraftPlan.tsx`;
`frontend/src/lib/draftRadar.ts`; existing draft state API for read-only integration.

Acceptance: old targets migrate; two views stay synchronized; picks/undo update
availability; non-contiguous local team IDs work; no automatic pick is submitted.

## 6. P3 — Practice My Draft

Extend the manual mock with a separate practice session. Choose position, team count
from supported configuration, opponent rule (ADP or board order), and run name.

- User picks for their team; other teams advance automatically until the next user
  pick. ADP ties use stable IDs; missing ADP falls back to board order and is labelled.
- Respect roster size and available-player uniqueness. Eligibility/slot fit uses
  existing logic, with a missing-eligibility notice rather than invented positions.
- No predicted availability probability or simulated weekly win outcome.
- Undo returns to the prior user decision, including the intervening opponent picks.
- Save multiple named runs, including export version/date, strategy, configuration
  and picks. Compare composition, feasible starters, depth and season production.
- Keep practice and manual/live sessions separate; deleting a run affects only it.

Acceptance: snake boundaries and final round are correct; no duplicate IDs; strategy
is reproducible; undo/reload restore the exact run; a refreshed board shows the run's
original snapshot context instead of silently repricing its recorded results.

## 7. P4 — What Changed?

Public route: `#changes`; local integrates with `/trends` and a changes view.
Use existing in-season snapshot joins locally. Add a redacted dated public archive
through `scripts/export_static.py`; never manufacture a historical baseline from the
current board. First run explicitly says that a baseline is being collected.

- Save a stable export version plus dated public rows. A manifest identifies available
  versions. Preserve multiple exports on one date with timestamp/version IDs.
- Compare the same IDs and same ranking/scoring semantics. New/removed players are
  separate events; do not turn missing values into zero or interpret re-ranking as
  a role change. Show old/new values, FP/G/MPG/rank deltas and baseline dates.
- Recorded analyst action/date changes can explain an event. When attribution is
  absent, say that the projection changed without guessing why.
- Views: all changes, watched players, selected team and since-last-visit. Advance
  the last-seen marker only after the user has viewed that version successfully.
- Retention/payload policy must be documented before archive rollout. Keep summaries
  lightweight and load detailed versions on demand.

Acceptance: unchanged exports produce no events; unavailable baseline gets a useful
empty state; rank-only changes are distinguished; raw private text never enters exports;
existing public export tests and deployment validation still pass.

## 8. P5 — Rotation & Opportunity

Start with local NBA team detail, extending existing team summaries and player pages.
Display projected MPG, FP/G, role evidence, analyst effective date and competition.

- Reuse roster maps and the approved team-preview minutes ledgers when present.
  Keep model totals and a separately approved rotation distinct.
- Show the sum of projected minutes versus the regulation 240-minute reference as
  a diagnostic; do not automatically reconcile projections (EXP-031 rejected).
- Separate minutes opportunity, rate assumptions and availability. Explain existing
  redistribution fields only for snapshots that contain them.
- Teammate changes may be displayed as context, but no new automatic usage or FP/G
  adjustment is introduced by this page.
- Public rollout requires a curated redacted summary schema; no raw transcripts,
  private rationales or fabricated depth-chart ordering.

Acceptance: effective/current team mapping; accurate sums and missing-data labels;
public export allowlist tests; no change to board values.

## 9. P6 — usable lineups and personal streaming

### P6a: shared calculation

Implement a pure helper shared by My Team, Matchup, streaming and trades. Inputs:
roster IDs, authoritative eligible slots, league starting slots, available game dates
and projected FP/G. Reuse `current_rosters()`, `week_games_by_team()` and
`games_while_active()` in `api/season.py`; preserve their source timestamps.

For each day, find the maximum projected points assignment to starting slots. Use
an exact weighted matching/assignment, not highest-FP/G greedy seating: multi-position
players can otherwise occupy a slot another starter needs. Sum feasible starts across
the week. Report raw scheduled points, usable points, benched production, chosen daily
assignments, idle slots and missing eligibility separately.

Daily FP/G is a constant expectation here; no opponent adjustment, game-level variance
or win probability. Describe the result as a planning projection, not the actual ESPN
lineup or a submission. Historical season risk ranges are not additive team intervals.

Acceptance: meaningful arithmetic tests for scarce positions, multi-eligibility,
crowded/idle days, OUT dates, unknown positions and no schedule. Usable points never
exceed raw points; no player or starting slot is used twice on a day.

### P6b: streaming scenarios

New `/streaming` view, linked from Waivers/Weekly/My Team/Matchup. Select date range,
one or more drop candidates, acquisitions already used and an optional keep list.

- Read verified league acquisition limits, waiver delay, daily/weekly lock rules,
  timezone and IR rules where available. Missing settings require explicit scenario
  assumptions before claiming that an add/drop can take effect on a date.
- Enumerate feasible candidate transactions and compare P6a before/after results.
  Rank by incremental usable points; show raw volume and ROS quality separately.
- Explain the gain with usable game dates, crowded-day losses and lost drop-player
  contribution. Preserve unknown ownership/status states and source freshness.
- MVP evaluates one add/drop at a specified effective date. Multi-move sequences and
  weekly acquisition-budget planning follow after single-move correctness.
- Moves remain scenarios; no roster transaction is sent to ESPN.

Acceptance: four scheduled games/two feasible starts can lose to three feasible starts;
locked days and transaction limits are honoured; injured/rostered players are handled
correctly; missing settings and stale ownership are visible.

## 10. P7 — Trade Sandbox

New `/trade-sandbox`, linked from Trade Targets and Compare. Select two actual teams
and outgoing players on each side; calculate a scenario using current ownership.

- Show both sides before/after: FP/G, usable week points (P6a), projected season/ROS
  totals with a common horizon, eligible starters, open slots and above-replacement
  depth. Show individual risk without treating summed player bounds as team coverage.
- For an uneven trade, require the receiving team's drop choice and the other team's
  optional available pickup. Display legal roster-size/IR requirements and assumptions.
- Add playoff-week schedule comparisons only when the league calendar is confirmed.
- Market disagreement is a price reference; no composite fairness score, trade
  acceptance prediction or win probability.
- Preserve a shareable local scenario without publishing roster data or executing it.

Acceptance: empty/duplicate/wrong-owner selections rejected; both sides reconcile;
uneven trades include the replacement/drop opportunity cost; comparison dates and
ownership freshness are explicit; no persistent roster mutation.

## 11. P8 — Today

Evolve My Team into the local daily home. Show today's known availability, feasible
lineup, crowded days, watched-player changes, relevant streaming scenarios and links
to unfinished planning tasks. Keep the full roster view accessible.

- Show distinct timestamps for board, rosters, schedule and status data.
- Prioritize the manager's own roster/watchlist; deduplicate alerts by event/version.
- Missing data provides a targeted link to setup/refresh. A delayed feed is not
  presented as a confirmed player status.
- In-app alerts first. Push/email notifications, accounts and cross-device sync
  require a later product/infrastructure scope; no messaging integration is implied.

Acceptance: useful pre-draft and in-season empty states; no phantom alerts after reload;
each item links to the relevant player or scenario; date boundaries use league settings.

## 12. P9 — minutes scenario explorer

Add an optional player/compare panel: current approved minutes, assumed minutes and
resulting FP/G at held model rates. Scenario values never overwrite the board.

- Reuse the actual decomposition and scoring calculation. A Board-B rate residual
  must be handled explicitly; do not rescale the final adjusted FP/G blindly.
- Public export needs a verified held-rate/scenario input schema before this can ship.
  Current `mpg` plus adjusted `fpts_pg` alone is insufficient for faithful re-composition.
- Show baseline, minutes contribution and any retained rate residual separately.
  Missing/market-priced inputs disable the scenario with an explanation.
- No invented usage elasticity, team-budget reconciliation or forecast confidence.

Acceptance: baseline reproduces approved FP/G; changed minutes preserve held rates;
rounding/zero-input cases are defined; saved scenario has no effect on future exports.

## 13. Verification and release discipline

- P1 uses JavaScript syntax validation and a browser walkthrough at 320/390/760/1440px,
  with real redacted snapshot data. Check interactions, reload, keyboard, overflow and
  bad/unavailable storage. Avoid tests that merely duplicate rendering implementation.
- Local UI changes run TypeScript and the production frontend build.
- Export changes run `tests/test_export_static.py` and the Pages validation contract.
- P6/P7 introduce arithmetic/constraint behaviour and require meaningful pure helper
  tests plus API integration checks with explicit fixtures, never remote NBA pulls.
- Update this tracker and link the delivered behaviour in README/ROADMAP. Do not
  claim shipped status for planned rows or create ledger entries for presentation work.
- This task prepares reviewable local changes. Publishing, deployment and commits are
  separate actions; nothing here requires them to validate the first deliverable.

## 14. Session hand-off

2026-09-29: P1a implemented in the public site. Four column presets and three layouts
share the same filtered/sorted rows. Mobile cards expose FP/G, ADP, position and Radar;
details expand to the remaining fields. Preferences persist under the versioned key;
corrupt/unavailable storage recovers. Radar opens its existing explanation and personal
notes are visible as escaped text. README, ROADMAP and the original UI plan link here.

Verification: `node --check static/app.js`, `git diff --check`, and a Chromium browser
walkthrough at 320/390/760/1440px. Verified preset/header/value agreement, desktop fit,
phone overflow including expanded details, explicit Table, keyboard sorting, retained
compare focus/expanded cards, compare page, priority edit, escaped Unicode notes,
reload preferences, missing filter values, empty/reset, position search, mock pick/undo,
tiers/team drill-down, malformed/invalid/unavailable storage and absence of page errors.
The existing generated board retained the same SHA-256 during verification.

Initial follow-up: P1b local parity and P1c links/backup, then P2 My Draft Plan. Remaining phases
stay planned; the standing modelling calendar is unchanged. Public assets are prepared
locally; deployment has not been performed.

2026-09-30, local parity: P1b completed on the React/FastAPI app at port 8787. Draft,
Performance, Risk and Full detail presets reuse existing local fields. Automatic
cards use the same 760px breakpoint as the public site, with an explicit table option.
Local season-value ranks/tiers and historical actuals remain intact. Independent
sorting is shared by cards/table and saved with filters, season/model/stance, chart
choice, preset and layout in `fantasy-nba-local-board-preferences-v1`.

New `BoardCards` and browser-preferences helpers establish reusable conventions.
Shared tables now expose keyboard sort buttons and optional controlled sorting.
The mobile shell uses a native navigation dialog; its compare tray fits a phone.
Radar and analyst chips open an accessible explanation dialog. Storage failures
leave theme, comparison and target editing usable within the current session.

The board API adds current ESPN eligibility labels from the existing in-memory
player map. Historical boards return empty position arrays and do not read today's
eligibility; no remote pull, identity remapping or projection adjustment is performed.

Verification: TypeScript and production Vite build pass; 59 relevant board/draft/season
API tests pass, including current-versus-historical eligibility isolation. Browser
checks against the real cached board cover presets, desktop fit, keyboard sorting,
mobile cards/details at 320/390/760px, explicit layouts, compare tray, Radar dialog,
mobile navigation, both themes, route/reload preferences, historical actuals/hit rate,
and malformed/invalid/unavailable storage with no browser errors. The local server
is running on port 8787. Next: P1c links/watchlist backup, then P2 My Draft Plan.

2026-09-30, links and portability: P1c completed in both apps. Board viewing settings,
player detail and comparison IDs now have shareable URLs with working history and
reload. Copy controls include clipboard fallback. Watchlist import/export shares a
versioned validation module, preview, merge/replace behavior and unknown-ID handling.
The React target store synchronizes mounted views and retains session-only state
across navigation. A visual review also corrected the public preference loader's
default sort: an absent sort must not match an unsortable column's undefined key.

Verification: TypeScript/production Vite build, JavaScript syntax check, three shared
contract tests and four existing public-export tests pass. Chromium against the real
localhost apps verifies explicit URL precedence, filter history, comparison history,
player-dialog back/forward/reload, missing and malformed IDs, Unicode and escaped
markup notes, canceled and invalid imports, wrong-season rejection, both directions
of backup transfer, merge/replace including an empty replacement, and phone controls
at 320/390/760px. Blocked-storage imports remain usable during navigation; blocked
clipboard access reveals a selectable link; no browser script errors were observed.
The existing board JSON retained SHA-256
`B01258485CF95FA3BB90B76441998DF40A2C0B52771B5211E4E11B59B25B3769`.
Previews remain on ports 8787 and 8788. Next: P2 My Draft Plan. At verification time
deployment was pending; the modelling calendar is unchanged.

## 14. Session handoff — 2026-09-30

P1a, P1b and P1c are implemented and verified. The user requested documentation sync
and a push to `origin/main` before starting a new session. The existing Pages workflow
deploys the public site on a main-branch push; its run must succeed before describing
the public update as deployed. The React/FastAPI app is a local build at port 8787.

Resume with **P2 My Draft Plan (§5)** on both surfaces. Start by extending the existing
target schema with backward-compatible defaults for preferred round, backup group,
priority and status. Update the shared backup validator/version and migration together;
keep old version-1 files importable. Then implement the plan views (`#plan` and
`/draft-plan`), configured snake-pick references, descriptive target deadlines and
summary cards. Read existing mock/live draft state; never submit a pick automatically.
Verify old-target migration, board/plan synchronization, pick/undo availability,
non-contiguous local team IDs and missing order/eligibility. Do not start P3 until P2
acceptance passes. The scheduled modelling and draft-verification gates retain priority.

Useful code entry points:

- Public: `static/app.js` (columns, cards, hash routing, targets, mock),
  `static/index.html`, `static/style.css`.
- Local: `frontend/src/views/DraftBoard.tsx`, `frontend/src/App.tsx`,
  `frontend/src/components/BoardCards.tsx`, `frontend/src/components/Portability.tsx`.
- State/contracts: `frontend/src/lib/draftRadar.ts`,
  `frontend/src/lib/preferences.ts`, `static/workspace.mjs` and its TypeScript
  declarations. The shared target key is `fantasy-nba-draft-targets-v1`.
- Eligibility: `src/fantasy_nba/api/app.py` exposes current positions through the
  cached `player_positions()` helper in `api/draft.py`. Historical board requests
  return empty arrays; current eligibility must never leak into historical evidence.
- Static snapshot generation: `scripts/export_static.py`. The existing snapshot
  was already changed at session start and was not hand-edited during product work.
  New exports add season metadata; old snapshots use their title as a fallback.

Run/review commands from the repository root:

```powershell
npm --prefix frontend run build
python scripts/serve.py
# A separate terminal for the public preview:
python -m http.server 8788 --bind 127.0.0.1 --directory static
# Checks (separate terminal while the servers are running):
node --check static/app.js
node tests/test_workspace.mjs
python -m pytest tests/test_board_api.py tests/test_draft.py tests/test_season_api.py tests/test_export_static.py -q
python scripts/check_product_portability.py
git diff --check
```

The optional browser script requires Python Playwright and its Chromium binary;
install them only when needed (`python -m pip install playwright`, then
`python -m playwright install chromium`). It uses fresh contexts, browser-local
synthetic notes, and read-only API requests; it never mutates the live draft. Its
screenshots and test downloads go to ignored `.tmp/ux-review/`. Runtime logs go to
ignored `.run/`. The frontend build is ignored and must be rebuilt on a new checkout.
Windows sandbox restrictions may require approved child-process execution for Vite
and Chromium; do not interpret a spawn-permission failure as an application failure.
If pytest cannot access the default Windows temp directory, use a new, verified
workspace directory with `--basetemp .tmp/pytest-<unique-session-id>`; never point
`--basetemp` at an existing directory containing work, because pytest clears it.

Documentation synchronized: README usage/run commands; ROADMAP status; this detailed
tracker/handoff; the original UI plan's follow-up status; implementation-plan ownership
pointers; and agent orientation. Historical modelling/design records and the append-only
experiment ledger receive no product-only edits. Private research, credentials and
local caches remain excluded from Git and the Pages artifact.

Pre-push check (2026-09-30): the existing 595-row snapshot passes the Pages ranking,
capability and 12-team checks and the exporter field allowlist. Its pre-existing diff
contains 452 changed public rows; it is included as-is, without changing projections
or adding private research. The reusable browser check is now
`scripts/check_product_portability.py`. Local agent guidance and the Codex BBM skill
are included for session continuity; generated build files, browser downloads,
screenshots and server logs remain local.

## 15. P2 delivery and handoff — 2026-09-30

P2 My Draft Plan is implemented on both surfaces: public `#plan` and local
`/draft-plan`. Both use the existing browser-local target key and show configured
snake picks, grouped targets, backups, target deadlines, FP/G tier counts, ADP
vintage, roster needs and a link to their respective draft rooms. Editing a target
from either the board or the plan updates the same store. Picks and undo change
target availability; neither plan submits a pick. Public `rank` remains the
published FP/G ordinal, while local `rank` retains the selected board semantics.

The target schema now adds `preferredRound`, `backupGroup`, `priority` and `status`.
Old stored targets load with defaults without changing the storage key. Exported
backups use version 2; version-1 files remain importable on both apps. Unknown IDs
remain in a backup and appear as absent targets. Plan notes are private, escaped in
the public HTML renderer and never added to shareable URLs.

The local plan uses real, potentially non-contiguous team IDs only when the saved
ESPN order is complete and non-placeholder. Otherwise the page labels its pick
numbers as an illustrative slot scenario. Open starting positions are explicitly
unknown without confirmed eligibility and a selected team. Current-board ADP
vintage comes from the latest cached market filename; historical board responses
do not borrow it. No survival odds or automatic board reorder are shown.

Verification: frontend production build; shared workspace tests including v1/v2
backup validation and non-contiguous snake picks; 63 relevant backend tests; the
cross-app portability Playwright check; and `scripts/check_draft_plan.py` covering
old-target migration, plan editing, public pick/undo, simulated local pick/undo,
verified order and placeholder fallback. The draft-plan browser check intercepts
read-only draft-state requests in an isolated context and does not touch the live
session. Mobile screenshots are in ignored `.tmp/ux-review/`.

Next: P3 Practice My Draft (§6). Keep practice runs isolated from the existing
manual mock and live draft session. Follow the standing calendar in
`docs/implementation-plan.md` before product work at its scheduled gates. Local
previews can be started with `python scripts/serve.py` on port 8787 and
`python -m http.server 8788 --bind 127.0.0.1 --directory static`; rebuild the
frontend with `npm --prefix frontend run build` after React changes.

## 16. P3 delivery and handoff — 2026-10-02

Practice My Draft is implemented on the public `#practice` route and local
`/practice` route. The shared pure engine is `static/practice.mjs`, with a typed
declaration for the React app. A manager chooses a run name, team count (8, 10,
12, 14 or the configured count), draft position and deterministic opponent rule.
Opponents take the best remaining ADP or board-rank player. Equal ADP uses player
ID; unpriced players follow board rank after priced players. The manager makes only
their own picks. Undo returns to the state before the last manager decision and
removes all intervening scripted picks.

Each run saves its own compact player snapshot, source/rank meaning, board capture
time, ADP vintage, roster configuration, strategy, picks and undo checkpoints in a
separate browser-local key (`fantasy-nba-practice-v1`). Up to ten named runs can be
compared, exported as version-1 JSON, imported, opened and deleted. Snapshot rows
drive both subsequent opponent picks and review metrics, so a current-board update
does not silently reprice an old run. Comparison shows position mix, feasible
starter FP/G, depth and projected season FP; unknown eligibility and missing season
totals are explicit. Public provisional player IDs can be negative and are retained
as stable IDs. The public mock key and local live draft session are never written
by practice actions.

Verification: `node tests/test_practice.mjs` covers snake boundaries, final-round
limits, deterministic strategy, negative provisional IDs, snapshot immutability,
matching, undo/reload and malformed-run rejection; `npm run build` passed; 64
relevant backend tests passed; `scripts/check_practice_draft.py` passed against
both previews in isolated browser contexts, covering scripted turns, persistence,
export/import, mobile fit and no live-draft POST. Browser screenshots are ignored
under `.tmp/ux-review/`.

Next: P4 What Changed? (§7), after the scheduled October modelling and draft
verification gates in `docs/implementation-plan.md` when those dates arrive. Keep
the public archive redacted and use dated exports as real baselines. P3 requires no
model experiment entry and changes no board values.
