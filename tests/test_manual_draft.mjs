import assert from "node:assert/strict";
import { draftCapacity, manualPickProblem } from "../static/manual-draft.mjs";

const config = { teams: 2, roster: { UTIL: 1, BENCH: 1, IR: 3 } };
assert.deepEqual(draftCapacity(config), { perTeam: 2, total: 4 });
const picks = [{ playerId: 10, team: 1 }, { playerId: 20, team: 1 }];
assert.match(manualPickProblem(config, picks, 30, 1), /full/);
assert.match(manualPickProblem(config, picks, 10, 2), /already/);
assert.match(manualPickProblem(config, picks, 30, 0), /Choose/);
assert.equal(manualPickProblem(config, picks, -30, 2), null);
const complete = [...picks, { playerId: 30, team: 2 }, { playerId: 40, team: 2 }];
assert.match(manualPickProblem(config, complete, 50, 2), /complete/);
assert.equal(manualPickProblem(config, complete.slice(0, -1), 50, 2), null);
console.log("Manual draft capacity, duplicate, assignment and undo checks passed.");
