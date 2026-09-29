---
name: bbm
description: Process new BBM fantasy-basketball transcripts into fact notes and review-gated analyst proposals. Use when a transcript is added under data/manual/bbm_transcripts or the user supplies fantasy-relevant commentary.
---

# BBM transcript to analyst-layer pass

The authoritative judgment contract is
[`data/manual/bbm_transcripts/README.md`](../../../data/manual/bbm_transcripts/README.md).
Read it in full before drafting or changing any ledger, note, or proposal. It
outranks this skill. For a team-preview transcript, also read
[`data/manual/bbm_team_previews/README.md`](../../../data/manual/bbm_team_previews/README.md).

## Outcome and boundaries

Turn unprocessed transcript facts into append-only rows in
`data/manual/bbm_notes.csv`, then make a dated, review-gated batch in
`config/analyst_proposals.yaml`. Validate the batch and stop for Steven's
review. Never promote it without explicit approval.

This layer owns season-level minutes and per-game-rate beliefs, not player
availability. Route concrete out timelines, rest, tanking, and other
availability signals to `config/overrides.yaml` candidates for Steven; never
put them in the analyst layer. Never edit `config/analyst_overrides.yaml`
directly.

## Run the pass

1. Refresh transactions before sizing. Check the cached max date against the
   newest transcript, then run the incremental transaction pull when stale:

   ```powershell
   python -c "import pandas as pd; print(pd.read_parquet('data/raw/transactions.parquet')['date'].max())"
   python scripts/pull_injuries.py --dataset transactions
   ```

   Do not use `--full`. If the pull fails, record affected players as explicit
   data flags; do not hand-edit the roster map.

2. Detect unprocessed source files before reading or writing. Parse the notes
   CSV rather than splitting it on commas; account for the two legacy source
   names recorded without a `.md` suffix. Flag duplicate hashes as a paste
   error, process the content only once, and ask Steven to re-drop any missing
   episode.

3. Extract one player-specific fact per `bbm_notes.csv` row using its existing
   schema: date, player, team, claim type, direction, quote, and source file.
   Resolve transcription errors from roster context, annotate uncertain
   resolutions, and leave genuinely ambiguous names unresolved rather than
   guessing. Extract basketball mechanisms, not BBM rank or tier claims.

4. For every flagged player, pull the current learned-board base and
   re-triangulate the full player from that base. An effective analyst entry
   means the new entry supersedes it; never add the old delta to a new one.
   Rookies absent from the learned board are deferred, not proposed.

5. Append proposals in the established `config/analyst_proposals.yaml` style:
   current date, category, action, preview, rationale, `status: proposed`, and
   triangulation. The proposal categories are only `role`, `injury`, `hype`,
   `rookie`, and `other`; map note `depth`, `usage`, and `transaction` facts to
   `role`. Every transcript-derived rationale begins `BBM <video-date>:` and
   includes the supporting quote.

6. Express minutes beliefs with absolute `target_mpg` and rate/usage/efficiency
   residuals with `fpts_delta`. A proposal may have both, with minutes applied
   first. Do not invent a minutes target for a topic episode. Use only
   `fpts_delta` or `none` for the value outcome—never `rank_delta`—and never
   apply an arbitrary numeric cap or a second conviction trim.

7. For every non-`none` proposal, include the reconciling `sizing:` block
   required by the transcript contract. Account explicitly for what the model
   already prices. A sub-25-game base requires `rate_held`; it is a diagnostic,
   not permission to re-anchor the projection to a healthy season.

8. Treat a whole-roster/team-preview transcript as team-preview mode. Build and
   persist the full rotation ledger before proposals, cover every rotation
   player, and use the 240-minute budget only when the contract's depth-chart
   gate passes. Preserve the distinction between stated `bbm_mpg` and derived
   `budget_mpg`; a failed gate may still yield a proposal from an explicitly
   quoted minutes figure.

9. Validate without promotion:

   ```powershell
   python scripts/apply_proposals.py --status proposed
   ```

   Report the batch, large-delta sizing rationale, transcript/data issues, and
   availability candidates. Then stop for Steven's review.

## Explicit approval only

After Steven explicitly approves specific proposals, update only those statuses
and run:

```powershell
python scripts/apply_proposals.py --promote
python scripts/apply_analyst.py data/processed/learned_2026-27.parquet
```

Promotion is append-only and idempotent. Update the project’s current-status
memory only if that file exists and is part of the established workflow.
