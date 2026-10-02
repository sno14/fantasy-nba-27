import assert from "node:assert/strict";
import { compareSnapshots } from "../static/changes.mjs";

const row = (id, rank, fpts = 30, mpg = 28, action = null) => ({ PLAYER_ID: id, PLAYER_NAME: `Player ${id}`, TEAM_ABBREVIATION: "NYK", rank, fpts_pg: fpts, mpg, analyst_action: action, analyst_date: action ? "2026-10-02" : null });
const snap = (version, rows) => ({ schema: 1, version, asof: `2026-10-02T00:00:0${version}Z`, season: "2026-27", rankedBy: "FP/G ordinal", scoringKey: "0123456789abcdef", source: "public", rows });

assert.deepEqual(compareSnapshots(snap("2", [row(1, 1)]), snap("1", [row(1, 1)])), []);
const rankOnly = compareSnapshots(snap("2", [row(1, 2)]), snap("1", [row(1, 1)]))[0];
assert.equal(rankOnly.kind, "rank-only");
assert.equal(rankOnly.fptsDelta, 0);
assert.equal(rankOnly.rankDelta, -1);
const events = compareSnapshots(snap("2", [row(2, 1)]), snap("1", [row(1, 1)]));
assert.equal(events.find(event => event.id === 1).kind, "removed");
assert.equal(events.find(event => event.id === 1).fptsDelta, null);
assert.equal(events.find(event => event.id === 2).kind, "added");
assert.equal(events.find(event => event.id === 2).mpgDelta, null);
const analyst = compareSnapshots(snap("2", [row(1, 1, 33, 29, "+2 fpts/g")]), snap("1", [row(1, 1)]))[0];
assert.match(analyst.explanation, /Recorded analyst action\/date changed/);
assert.throws(() => compareSnapshots({ ...snap("2", [row(1, 1)]), scoringKey: "different" }, snap("1", [row(1, 1)])), /different season, scoring or ranking/);
console.log("Change comparison contract passed");
