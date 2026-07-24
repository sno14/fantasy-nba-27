# BBM team-preview ledgers — the per-team minutes+usage snapshots

One YAML file per processed **team-preview** transcript (Locked On's team-by-team season
previews — a Locked On <team> beat guest joins Josh to walk the whole roster). Each file is
the **closed ~240-minute rotation** reconstructed from the preview: the spine the proposals
fall out of. Committed for provenance (data/manual is the gitignore exception), same as the
transcripts and `bbm_notes.csv`.

These are **dated snapshots, not live tables** — the `model_*` columns are the model base as
of `preview_date`, exactly like a `bbm_notes.csv` row records what was believed then. Do not
mistake a ledger for the current board; in-season the base moves nightly.

**Why they exist (user decision 2026-07-24):** a topic episode names a riser in isolation; a
team preview discusses the WHOLE rotation, so every minutes bump can be checked against a
*nameable* loser, the depth chart is stated outright, and usage is given as a ranked list.
That is the depth-chart redistribution the model can't derive from box scores
(role-change-lever / EXP-030), handed to us by a beat analyst — worth capturing once per team.

**Consumers:** the mid-Oct depth-chart re-pull + EXP-030 redistribution pass (a ready-made
per-team depth chart), and any re-review of the analyst layer against fresh team news.

## File naming

    <preview-date>-<team-slug>.yaml      # mirror the transcript's date + team
                                         # e.g. 2026-07-23-wizards.yaml

## Schema

```yaml
team: WAS                       # tricode
team_full: Washington Wizards
preview_date: 2026-07-23
source_file: 2026-07-23-wizards-season-preview.md   # the transcript in ../bbm_transcripts/
win_proj: 40                    # BBM's stated season win prediction (competitiveness context)
availability_note: >            # team-level rest/tanking/scheme signal -> config/overrides.yaml
  candidate for Steven, NOT the analyst layer. "" when none.
budget_min: 240
rows:
  - player: Trae Young
    model_mpg: 31.8             # board mpg base (null if not on the learned board)
    bbm_mpg: "33-35"            # BBM's stated minutes, verbatim/normalized; "" if none
    model_usg: 34.1            # computed last-season USG% (formula in transcripts README); null if n/a
    bbm_usg: "down from peak, playmaker role"    # "" if none
    verdict: "+2.0"            # fpts_delta value | none | defer(rookie) | note-only
    proposal: true            # true iff this row becomes an analyst_proposals.yaml entry
    note: "offensive engine; 5-game WAS sample had usg down / ast up"
sum_model_mpg: 238.4            # informational
sum_bbm_mpg: 242               # BUDGET CROSS-CHECK: flag if > ~245 or < ~235
```

Rows cover the **full projected rotation** (~10-12), including `none` / `defer(rookie)` /
`note-only` verdicts — systematic coverage is the whole point of a preview. `model_mpg` /
`model_usg` come from `learned_2026-27.parquet` + the USG% formula over
`player_season_stats` x `team_game_logs`; current-team assignment uses `preseason_roster_map`
(the same source the live board uses). Rookies without a learned base carry `defer(rookie)`
and no proposal; their role context still feeds the mid-Oct market seed / sheet.
