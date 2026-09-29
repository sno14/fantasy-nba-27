export const MAX_FILE_BYTES = 1024 * 1024;
export function parseIds(raw) {
  if (raw === "") return [];
  const parts = raw.split(",");
  if (parts.length > 4 || parts.some(id => !/^[1-9]\d*$/.test(id) || !Number.isSafeInteger(Number(id))))
    throw new Error("Comparison links must contain up to four positive player IDs.");
  return [...new Set(parts.map(Number))];
}

export function validateBackup(value, season) {
  if (typeof season !== "string" || !/^\d{4}-\d{2}$/.test(season)) throw new Error("The board season is unavailable. Load a current board before importing or exporting.");
  if (!value || value.format !== "fantasy-nba-watchlist" || value.version !== 1)
    throw new Error("Choose a Fantasy NBA watchlist backup (version 1).");
  if (value.season !== season) throw new Error(`This backup is for ${value.season || "an unknown season"}; this watchlist is for ${season}.`);
  if (!Array.isArray(value.targets) || value.targets.length > 1000) throw new Error("A backup can contain at most 1,000 targets.");
  const targets = {};
  for (const item of value.targets) {
    if (!item || !Number.isSafeInteger(item.playerId) || item.playerId < 1 ||
        !(item.takeBy === null || (Number.isInteger(item.takeBy) && item.takeBy >= 1 && item.takeBy <= 10000)) ||
        typeof item.note !== "string" || item.note.length > 10000)
      throw new Error("Invalid target: use a positive player ID, a pick from 1–10,000 (or null), and a note of at most 10,000 characters.");
    if (Object.hasOwn(targets, item.playerId)) throw new Error(`Duplicate player ID ${item.playerId}.`);
    targets[item.playerId] = { takeBy: item.takeBy, note: item.note };
  }
  return targets;
}

export function createBackup(targets, season) {
  const backup = { format: "fantasy-nba-watchlist", version: 1, season, exportedAt: new Date().toISOString(),
    targets: Object.entries(targets).map(([id, target]) => ({ playerId: Number(id), takeBy: target.takeBy, note: target.note })) };
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
