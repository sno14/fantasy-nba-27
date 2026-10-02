import test from "node:test";
import assert from "node:assert/strict";
import { choosePracticePlayer, createPracticeRun, opponentChoice, parsePracticeRuns, practiceRounds, practiceSummary, practiceTeam, undoPracticePick, validatePracticeRun } from "../static/practice.mjs";

const rows = Array.from({ length: 15 }, (_, index) => ({
  PLAYER_ID: index + 1, PLAYER_NAME: `Player ${index + 1}`, rank: index + 1,
  adp: index === 0 || index === 1 ? 1 : index === 14 ? null : index + 1,
  fpts_pg: 30 - index, fpts_total: 2000 - index * 20,
  positions: index % 2 ? "SG" : "PG",
}));
const settings = { name: "Snake boundary", teams: 4, position: 2, rule: "board", roster: { PG: 1, SG: 1, IR: 1 }, season: "2026-27", source: "public", ranking: "FP/G ordinal", marketDate: "2026-09-23", boardDate: "2026-09-29", rows };

test("snake boundaries and final roster round are exact", () => {
  assert.deepEqual(Array.from({ length: 8 }, (_, index) => practiceTeam(index + 1, 4)), [1, 2, 3, 4, 4, 3, 2, 1]);
  assert.equal(practiceRounds(settings.roster), 2);
  let run = createPracticeRun(settings);
  assert.deepEqual(run.picks.map(pick => pick.team), [1]);
  run = choosePracticePlayer(run, 10);
  assert.deepEqual(run.picks.map(pick => pick.team), [1, 2, 3, 4, 4, 3]);
  run = choosePracticePlayer(run, 11);
  assert.deepEqual(run.picks.map(pick => pick.team), [1, 2, 3, 4, 4, 3, 2, 1]);
  assert.equal(new Set(run.picks.map(pick => pick.playerId)).size, 8);
  assert.throws(() => choosePracticePlayer(run, 12), /Wait for your turn/);
  assert.deepEqual(validatePracticeRun(JSON.parse(JSON.stringify(run))), run);
});

test("undo includes the scripted picks after a user decision and survives reload", () => {
  const initial = createPracticeRun(settings);
  const after = choosePracticePlayer(initial, 10);
  const reloaded = parsePracticeRuns(JSON.parse(JSON.stringify([after])))[0];
  assert.deepEqual(undoPracticePick(reloaded), initial);
  assert.deepEqual(undoPracticePick(initial), initial);
  assert.equal(reloaded.snapshot.players[9].fptsPg, rows[9].fpts_pg);
  rows[9].fpts_pg = 999;
  assert.equal(reloaded.snapshot.players[9].fptsPg, 21);
  rows[9].fpts_pg = 21;
});

test("ADP ties use stable IDs; missing ADP falls back to board rank", () => {
  const pool = [{ id: 9, rank: 2, adp: 1 }, { id: 3, rank: 3, adp: 1 }, { id: 6, rank: 1, adp: null }, { id: 5, rank: 4, adp: null }];
  assert.equal(opponentChoice(pool, new Set(), "adp").id, 3);
  assert.equal(opponentChoice(pool, new Set([3, 9]), "adp").id, 6);
  assert.equal(opponentChoice(pool, new Set(), "board").id, 6);
});

test("published-board provisional negative IDs remain usable and unique", () => {
  const run = createPracticeRun({ ...settings, rows: [{ ...rows[0], PLAYER_ID: -546453227 }, ...rows.slice(1)] });
  assert.equal(run.snapshot.players[0].id, -546453227);
  assert.equal(run.picks[0].playerId, -546453227);
  assert.deepEqual(validatePracticeRun(JSON.parse(JSON.stringify(run))), run);
});

test("starter matching finds feasible lineup and unknown eligibility stays explicit", () => {
  const run = createPracticeRun({ ...settings, teams: 2, position: 1, roster: { PG: 1, G: 1, UTIL: 1, BENCH: 1 }, rows: [
    { PLAYER_ID: 1, PLAYER_NAME: "PG", rank: 1, fpts_pg: 30, fpts_total: 300, positions: "PG" },
    { PLAYER_ID: 2, PLAYER_NAME: "SG", rank: 2, fpts_pg: 25, fpts_total: 250, positions: "SG" },
    { PLAYER_ID: 3, PLAYER_NAME: "Unknown", rank: 3, fpts_pg: 20, fpts_total: null, positions: "" },
    ...rows.slice(3, 8),
  ] });
  const picked = { ...run, picks: [{ playerId: 1, team: 1 }, { playerId: 2, team: 2 }, { playerId: 3, team: 1 }, { playerId: 4, team: 2 }, { playerId: 5, team: 1 }] };
  const summary = practiceSummary(picked);
  assert.equal(summary.starters, 3);
  assert.equal(summary.openStarters, 0);
  assert.equal(summary.unknownEligibility, 1);
  assert.equal(summary.unknownSeasonTotal, 1);
});

test("corrupt saved picks and duplicate runs are rejected", () => {
  const run = createPracticeRun(settings);
  assert.throws(() => validatePracticeRun({ ...run, picks: [{ playerId: 1, team: 4 }] }), /Invalid practice picks/);
  assert.throws(() => validatePracticeRun({ ...run, picks: [{ playerId: 3, team: 1 }] }), /Opponent picks/);
  assert.throws(() => parsePracticeRuns([run, run]), /Duplicate practice run IDs/);
});
