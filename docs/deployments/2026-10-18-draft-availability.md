# Draft availability release — October 18, 2026

User authorized publication of the completed availability review and deployment
of the local app. This release publishes the tested static snapshot, its module
dependencies and the top-200 CSV through the existing GitHub Pages workflow.
Private review evidence, personal draft state and credentials stay local.

The default Draft Value Rank uses Effective FP/G through March 21: reviewed GP,
unchanged conditional production, 24 replacement FP/G and 35% marginal usable
coverage. The Risk view exposes 25% and 50% alternatives. Coverage is a planning
judgment, not empirically calibrated. All final top 200 were individually reviewed;
250 reviewed overall, with 184 GP changes. Ten roster/team cases have no draft
value and are explicitly listed in both interfaces. Original FP/G, minutes, stat
components, FP/G ranks and tiers are preserved across all 599 players.

Public board SHA-256:
`f5209662f5b64af591499e4757cd5f9fe6c4ab8484c5c45ff14dd269c3e2bad6`.
Availability overlay SHA-256:
`f9d57d16c7c695b6ee91df8564fe81a686f7aefe2fc4fadbfb212c2f3a243a75`.

The full React/FastAPI app is served locally at `http://127.0.0.1:8787/`.
The public companion is `https://sno14.github.io/fantasy-nba-27/`.
The local static preview is `http://127.0.0.1:8788/`.
No live draft picks are submitted or reset during deployment.

Pre-release validation includes 67 focused Python tests, the production frontend
build, public history/rotation/minutes validators, and read-only desktop/mobile
checks of both boards and draft rooms. The deployment workflow must finish and
live artifacts must match before publication is described as complete.
