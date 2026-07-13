# BBM video transcripts — the analyst-signal source (feeds the living analyst layer)

Drop one file per video here. Transcripts are the raw material for the
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

## Workflow v2 (user decisions 2026-07-12: a LIVING layer for THIS season)

1. **Drop transcripts** — backlog and, going forward, each new video.
2. **Extraction (Claude):** transcripts → `data/manual/bbm_notes.csv` — the durable
   evidence ledger: `date, player, team, claim_type (injury|role|depth|rank|hype),
   direction, quote, source_file`.
3. **Triangulation (Claude):** three angles per flagged player — (i) our model board,
   (ii) the BBM commentary, (iii) Claude's own fantasy-basketball judgment — synthesized
   into **proposed entries** in `config/analyst_proposals.yaml` (same schema as
   analyst_overrides + `status: proposed` + a triangulation note per entry).
4. **Review (Steven):** approve / edit / reject proposals. Approved entries are copied
   (minus the proposal fields) into `config/analyst_overrides.yaml` — append-only;
   a change of mind later is a NEW, later-dated entry (latest-dated wins), which is how
   the layer stays current as information arrives between now and October.
5. **The visible adjusted board (any time):**
       python scripts/apply_analyst.py data/processed/learned_2026-27.parquet
   → the current model board with every approved adjustment applied + audit columns.
6. **In-season (critical feature, wired 2026-07-12):** `update_daily.py` applies the
   effective analyst overrides to the **nightly ROS board** automatically (audit columns
   `analyst_action/category/date`, `model_rank`; `--no-analyst` to disable). Concrete
   out-timelines still go to `config/overrides.yaml` (availability caps + the EXP-030
   minutes redistribution to teammates).
7. **Mid-Oct pass:** full re-review of every effective entry against fresh videos +
   `analyst_triggers.py` before the dual freeze. The freeze still commits boards A and B.

## Triangulation rubric (bounds the LLM's judgment)

- **Agreement = assurance, not addition.** If BBM agrees with our board and adds no new
  mechanism, record `action: none` (positive assurance; projection unchanged — stacking
  agreement double-counts one underlying fact).
- **Agreement + a NEW mechanism** (e.g. we're high on stats-momentum, he adds "coach
  confirmed starter") → a modest additional delta; the mechanism goes in the rationale.
- **Disagreement** is the interesting case: sized by the strength of his mechanism vs
  the model's evidence, within the caps below.
- Bounded deltas: mild / moderate / strong conviction → `rank_delta` within ±5 / ±10 /
  ±15; `fpts_delta` only for quantified per-game claims, within ±3.
- Concrete role/depth/injury/usage claims move numbers; generic praise/hype → `none`.
- Every transcript-derived rationale starts with ``BBM <video-date>:`` + the quote.

## Scoring = calibration (amended 2026-07-12)

The layer is a **standing supplement** by user decision — it does not have to beat the
model to exist. April 2027's A-vs-B scoring (with the BBM-tagged subset split out)
**calibrates** it instead: are the magnitude translations running hot or cold, and which
source (user vs BBM-derived) earns bigger weights next season. The dual freeze and the
scoring itself are unchanged.
