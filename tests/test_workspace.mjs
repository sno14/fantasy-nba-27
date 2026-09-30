import test from "node:test";
import assert from "node:assert/strict";
import { createBackup, normalizeTarget, parseIds, snakePicks, validateBackup } from "../static/workspace.mjs";

test("watchlists preserve Unicode and unknown IDs across both apps", () => {
  const targets = { 203999: { takeBy: 3, note: "Jokić ★\n中文 <script>alert(1)</script>" }, 99999999: { takeBy: null, note: "" } };
  const normalized = Object.fromEntries(Object.entries(targets).map(([id, target]) => [id, normalizeTarget(target)]));
  const backup = createBackup(targets, "2026-27");
  assert.equal(backup.version, 2);
  assert.deepEqual(validateBackup(JSON.parse(JSON.stringify(backup)), "2026-27"), normalized);
  assert.deepEqual(validateBackup({ ...backup, version: 1, targets: backup.targets.map(({ playerId, takeBy, note }) => ({ playerId, takeBy, note })) }, "2026-27"), normalized);
  assert.deepEqual(validateBackup(createBackup({}, "2026-27"), "2026-27"), {});
});

test("invalid or foreign backups cannot produce a partial import", () => {
  const base = createBackup({ 203999: { takeBy: null, note: "" } }, "2026-27");
  for (const invalid of [null, [], { ...base, version: 3 }, { ...base, season: "2025-26" },
    { ...base, targets: {} }, { ...base, targets: [...base.targets, ...base.targets] },
    { ...base, targets: Array(1001).fill(base.targets[0]) },
    ...[0, -1, 1.5, "203999", Number.MAX_SAFE_INTEGER + 1].map(playerId => ({ ...base, targets: [{ playerId, takeBy: null, note: "" }] })),
    ...[-1, 0, 1.5, 10001, "10"].map(takeBy => ({ ...base, targets: [{ playerId: 1, takeBy, note: "" }] })),
    ...[null, {}, "x".repeat(10001)].map(note => ({ ...base, targets: [{ playerId: 1, takeBy: null, note }] })),
    ...[-1, 0, 1.5, 101, "2"].map(preferredRound => ({ ...base, targets: [{ playerId: 1, takeBy: null, note: "", preferredRound }] })),
    ...[null, 1, "x".repeat(51)].map(backupGroup => ({ ...base, targets: [{ playerId: 1, takeBy: null, note: "", backupGroup }] })),
    ...[-1, 0, 1.5, 1001, "2"].map(priority => ({ ...base, targets: [{ playerId: 1, takeBy: null, note: "", priority }] })),
    ...[null, "drafted", 1].map(status => ({ ...base, targets: [{ playerId: 1, takeBy: null, note: "", status }] }))])
    assert.throws(() => validateBackup(invalid, "2026-27"));
  assert.throws(() => createBackup({}, undefined));
  assert.throws(() => createBackup(Object.fromEntries(Array.from({ length: 200 }, (_, index) => [index + 1, { takeBy: null, note: "★".repeat(10000) }])), "2026-27"), /1 MB/);
});

test("snake positions preserve real non-contiguous team IDs and update after picks", () => {
  const order = [42, 103, 7, 81];
  assert.deepEqual(snakePicks(order, 103, 1, 4), [{ round: 1, overall: 2 }, { round: 2, overall: 7 }, { round: 3, overall: 10 }, { round: 4, overall: 15 }]);
  assert.deepEqual(snakePicks(order, 103, 8, 4), [{ round: 3, overall: 10 }, { round: 4, overall: 15 }]);
  assert.deepEqual(snakePicks(order, 99, 1, 4), []);
  assert.deepEqual(snakePicks([42, 42], 42, 1, 4), []);
});

test("comparison links validate IDs and deduplicate without changing order", () => {
  assert.deepEqual(parseIds("203999,1641705,203999"), [203999, 1641705]);
  assert.deepEqual(parseIds(""), []);
  for (const raw of ["1,2,3,4,5", "0", "-1", "1.5", "abc", "1,", "9007199254740992", " 1", "01"])
    assert.throws(() => parseIds(raw));
});
