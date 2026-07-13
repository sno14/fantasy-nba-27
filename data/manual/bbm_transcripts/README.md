# BBM video transcripts — the analyst-signal source (feeds EXP-029)

Drop one file per video here. These transcripts are the raw material for the
transcript→override workflow; they are **committed** (data/manual is the gitignore's
committed exception) so every derived override has checkable provenance.

## File naming

    YYYY-MM-DD_short-slug.txt        # date = video publish date

## File header (paste above the transcript text)

    Title: <video title>
    URL:   <video url>
    Date:  <YYYY-MM-DD>
    ---
    <full transcript below>

## The workflow (agreed 2026-07-11)

1. **Drop transcripts** here — backlog and, going forward, each new video.
2. **Extraction pass (Claude):** transcripts → `data/manual/bbm_notes.csv` — the durable
   intermediate: `date, player, team, claim_type (injury|role|depth|rank|hype),
   direction, quote, source_file`. The backlog is NEVER translated straight into
   overrides (July claims are stale by October).
3. **Availability facts** (in-season, once games start): concrete out-timelines →
   proposed `config/overrides.yaml` entries — reviewed by Steven before commit.
4. **Judgment calls** (the mid-Oct analyst pass, EXP-029): notes ledger + fresh videos +
   `analyst_triggers.py` output → Claude DRAFTS `config/analyst_overrides.yaml` entries;
   Steven reviews/edits/approves; `apply_analyst.py` → board B; dual freeze.

## Translation rubric (bounds the LLM's magnitude judgment)

- Concrete, mechanism-backed claims only (named role/depth/injury/usage changes) get a
  delta; generic praise/hype gets `action: none` (recorded — "reviewed, no change" is
  information).
- Bounded deltas: mild / moderate / strong conviction → rank_delta within ±5 / ±10 / ±15
  (fpts_delta only for quantified per-game claims, within ±3).
- Only write an entry where the transcript view DIVERGES from our board and adds
  information the market-consensus column doesn't already price (no double-counting).
- Every transcript-derived entry's rationale starts with ``BBM <video-date>:`` + the
  supporting quote — April 2027 scores the BBM-derived subset separately from
  Steven's own entries. The layer must earn its place or be deleted (EXP-029's rule).
