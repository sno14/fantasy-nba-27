# Fantasy NBA 2026-27 — repository guidance

Before changing the project, read the documentation in the order given by
`README.md`. For active modelling work, `ROADMAP.md`,
`docs/implementation-plan.md`, and `EXPERIMENTS.md` are especially important.

## Non-negotiable project rules

- `EXPERIMENTS.md` is append-only. Do not edit past entries or rerun work it
  records as rejected or do-not-retry; record corrections as dated addenda.
- `data/raw/` and `data/processed/` are local caches. Do not attempt remote
  `stats.nba.com` pulls from a remote session.
- Do not fabricate or hand-edit boards, roster maps, or overrides. Override
  histories are append-only and the latest dated entry for a player wins.
- Record every modelling experiment—adopted or rejected—in `EXPERIMENTS.md`,
  including a skeptic pass for leakage, selection, and seed stability.

## Operating workflows

- For new BBM transcripts or fantasy-relevant commentary, use the repo-local
  `$bbm` skill. The transcript README is its canonical judgment contract.
- Use `scripts/update_daily.py` for the in-season nightly workflow. Put concrete
  availability timelines in `config/overrides.yaml`, not the analyst layer.
- Follow the standing calendar and active tracker in
  `docs/implementation-plan.md`, subject to the 2026-10-14 projection hold below.
- **2026-10-14 user direction:** the current 2026-27 projections and rankings are
  accepted for now. Do not refresh/rebuild their model or analyst boards, regenerate
  the draft sheet or triggers, promote analyst proposals, re-export the public board,
  or run the preseason dual freeze as routine calendar work. A separate session
  explicitly requested by the user will handle final projection review. Read-only
  checks and product work that preserves existing values can continue. Do not start
  the opening-night projection update job before that review resolves the hold.
- For product/UI work, read `docs/product-experience-plan.md` and its latest
  session handoff. P1a–P9 and the P6b single-move MVP are implemented locally;
  multi-move streaming awaits verified transaction rules. Keep the
  public static site and local React/FastAPI app in scope, preserve their distinct
  rank semantics, and update the product tracker in the implementation commit.

## Next-session handoff (2026-10-14)

- Start from `docs/product-experience-plan.md` §26. The next active work is draft-room
  readiness on the **existing** board: inspect ESPN league ID, team count/IDs,
  roster slots and pick-order status, and test a real mock's polling latency when
  authenticated access is available. Record changed settings for the separate
  final projection review; do not update `league.yaml`, recompute VOR or rerank.
  Draft-session state and scrubbed mock fixtures may be saved without changing
  projection artifacts. Never treat a placeholder order as a real draft order.
- If live ESPN access is unavailable, record the precise blocker and continue
  product/UI improvements against the fixed board on both the public static site
  and local React/FastAPI app. P6b multi-move streaming still requires verified
  acquisition rules; do not invent them. Update the product handoff with results.
- This is **not** the final projection-review session. Do not use the missing
  preseason caches or a passing preflight to resume the paused projection path.
  Confirm the local model board, analyst board and public board remain unchanged
  after product work; their 2026-10-14 SHA-256 baselines are in §26.
