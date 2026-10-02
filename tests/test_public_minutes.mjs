import test from "node:test";
import assert from "node:assert/strict";
import { minutesResult, validMinutes, validateMinutesArtifact } from "../static/minutes.mjs";

const board = { season: "2026-27", generated_at: "2026-10-02T00:00:00Z", scoring_key: "abc",
  rows: [{ PLAYER_ID: 1, mpg: 30, fpts_pg: 12 }] };
const curve = { current_mpg: 30, approved_fpts_pg: 12, scored_current_fpts_pg: 10,
  retained_rate_residual: 2, values: Array.from({ length: 84 }, (_, index) => 2 + (index + 1) * 0.5 / 3) };
const artifact = { schema: 1, season: board.season, generated_at: board.generated_at,
  scoring_key: board.scoring_key, board_rows: 1, min_mpg: 0.5, step_mpg: 0.5,
  max_mpg: 42, rows: { 1: curve } };

test("matching artifact preserves approved baseline and looks up a discrete scenario", () => {
  assert.equal(validateMinutesArtifact(artifact, board), artifact);
  assert.deepEqual(minutesResult(curve, null), { assumed: null, fpts: 12, contribution: 0 });
  assert.equal(minutesResult(curve, 36).fpts, curve.values[71]);
  assert.equal(minutesResult(curve, 36).contribution, Math.round((curve.values[71] - 12) * 100) / 100);
});

test("stale or malformed curves are rejected", () => {
  assert.throws(() => validateMinutesArtifact({ ...artifact, generated_at: "old" }, board));
  assert.throws(() => validateMinutesArtifact({ ...artifact, rows: { 1: { ...curve, approved_fpts_pg: 13 } } }, board));
  assert.throws(() => validateMinutesArtifact({ ...artifact, rows: { 2: curve } }, board));
});

test("minute input enforces published half-minute grid", () => {
  assert.equal(validMinutes("36"), true);
  for (const value of ["", "abc", "0", "0.1", "42.5", "36.1"]) assert.equal(validMinutes(value), false);
  assert.throws(() => minutesResult(curve, 36.1));
});
