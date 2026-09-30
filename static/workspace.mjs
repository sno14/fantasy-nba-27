export const MAX_FILE_BYTES = 1024 * 1024;
export const TARGET_DEFAULTS = { preferredRound: null, backupGroup: "", priority: null, status: "active" };
export function normalizeTarget(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      !(value.takeBy === null || (Number.isInteger(value.takeBy) && value.takeBy >= 1 && value.takeBy <= 10000)) ||
      typeof value.note !== "string" || value.note.length > 10000)
    throw new Error("Invalid target take-by pick or note.");
  const preferredRound = value.preferredRound === undefined ? null : value.preferredRound;
  const backupGroup = value.backupGroup === undefined ? "" : value.backupGroup;
  const priority = value.priority === undefined ? null : value.priority;
  const status = value.status === undefined ? "active" : value.status;
  if (!(preferredRound === null || (Number.isInteger(preferredRound) && preferredRound >= 1 && preferredRound <= 100)) ||
      typeof backupGroup !== "string" || backupGroup.length > 50 ||
      !(priority === null || (Number.isInteger(priority) && priority >= 1 && priority <= 1000)) ||
      !["active", "hold"].includes(status))
    throw new Error("Invalid plan details: check round, backup group, priority and status.");
  return { takeBy: value.takeBy, note: value.note, preferredRound, backupGroup, priority, status };
}

export function snakePicks(order, teamId, fromOverall, rounds) {
  if (!Array.isArray(order) || order.length < 2 || order.length > 30 ||
      new Set(order).size !== order.length || order.some(id => !Number.isSafeInteger(id) || id < 1) ||
      !order.includes(teamId) || !Number.isInteger(fromOverall) || fromOverall < 1 ||
      !Number.isInteger(rounds) || rounds < 1 || rounds > 30) return [];
  const result = [];
  for (let round = 1; round <= rounds; round++) {
    const position = round % 2 ? order.indexOf(teamId) : order.length - 1 - order.indexOf(teamId);
    const overall = (round - 1) * order.length + position + 1;
    if (overall >= fromOverall) result.push({ round, overall });
  }
  return result;
}
export function parseIds(raw) {
  if (raw === "") return [];
  const parts = raw.split(",");
  if (parts.length > 4 || parts.some(id => !/^[1-9]\d*$/.test(id) || !Number.isSafeInteger(Number(id))))
    throw new Error("Comparison links must contain up to four positive player IDs.");
  return [...new Set(parts.map(Number))];
}

export function validateBackup(value, season) {
  if (typeof season !== "string" || !/^\d{4}-\d{2}$/.test(season)) throw new Error("The board season is unavailable. Load a current board before importing or exporting.");
  if (!value || value.format !== "fantasy-nba-watchlist" || ![1, 2].includes(value.version))
    throw new Error("Choose a Fantasy NBA watchlist backup (version 1 or 2).");
  if (value.season !== season) throw new Error(`This backup is for ${value.season || "an unknown season"}; this watchlist is for ${season}.`);
  if (!Array.isArray(value.targets) || value.targets.length > 1000) throw new Error("A backup can contain at most 1,000 targets.");
  const targets = {};
  for (const item of value.targets) {
    if (!item || !Number.isSafeInteger(item.playerId) || item.playerId < 1)
      throw new Error("Invalid target player ID.");
    if (Object.hasOwn(targets, item.playerId)) throw new Error(`Duplicate player ID ${item.playerId}.`);
    targets[item.playerId] = normalizeTarget(item);
  }
  return targets;
}

export function createBackup(targets, season) {
  const backup = { format: "fantasy-nba-watchlist", version: 2, season, exportedAt: new Date().toISOString(),
    targets: Object.entries(targets).map(([id, target]) => ({ playerId: Number(id), ...normalizeTarget(target) })) };
  validateBackup(backup, season);
  if (new TextEncoder().encode(JSON.stringify(backup, null, 2)).length > MAX_FILE_BYTES)
    throw new Error("This watchlist exceeds the 1 MB backup limit. Shorten notes or reduce targets before exporting.");
  return backup;
}

export function downloadBackup(targets, season) {
  const blob = new Blob([JSON.stringify(createBackup(targets, season), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = `fantasy-nba-watchlist-${season}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
