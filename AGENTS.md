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
  `docs/implementation-plan.md`; it takes precedence at its scheduled dates.
- For product/UI work, read `docs/product-experience-plan.md` and its latest
  session handoff. P1a–P9 and the P6b single-move MVP are implemented locally;
  multi-move streaming awaits verified transaction rules. Keep the
  public static site and local React/FastAPI app in scope, preserve their distinct
  rank semantics, and update the product tracker in the implementation commit.
