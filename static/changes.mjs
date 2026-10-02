const validId = value => Number.isSafeInteger(value) && value !== 0;
const validNumber = value => value == null || (typeof value === "number" && Number.isFinite(value));

export function validateChangeSnapshot(value) {
  if (!value || value.schema !== 1 || typeof value.version !== "string" || !value.version ||
      typeof value.asof !== "string" || !Number.isFinite(Date.parse(value.asof)) ||
      typeof value.season !== "string" || typeof value.rankedBy !== "string" || !value.rankedBy ||
      typeof value.scoringKey !== "string" || !value.scoringKey ||
      !["public", "local"].includes(value.source) || !Array.isArray(value.rows) || value.rows.length > 2000)
    throw new Error("Invalid projection history snapshot.");
  const ids = new Set();
  for (const row of value.rows) {
    if (!row || !validId(row.PLAYER_ID) || ids.has(row.PLAYER_ID) ||
        typeof row.PLAYER_NAME !== "string" || !row.PLAYER_NAME ||
        !Number.isSafeInteger(row.rank) || row.rank < 1 ||
        !validNumber(row.fpts_pg) || !validNumber(row.mpg) ||
        !(row.TEAM_ABBREVIATION == null || typeof row.TEAM_ABBREVIATION === "string") ||
        !(row.analyst_action == null || typeof row.analyst_action === "string") ||
        !(row.analyst_date == null || typeof row.analyst_date === "string"))
      throw new Error("Invalid player in projection history.");
    ids.add(row.PLAYER_ID);
  }
  return value;
}

export function compareSnapshots(latestValue, baselineValue) {
  const latest = validateChangeSnapshot(latestValue);
  const baseline = validateChangeSnapshot(baselineValue);
  if (latest.season !== baseline.season || latest.rankedBy !== baseline.rankedBy ||
      latest.scoringKey !== baseline.scoringKey || latest.source !== baseline.source)
    throw new Error("These snapshots use different season, scoring or ranking semantics.");
  const before = new Map(baseline.rows.map(row => [row.PLAYER_ID, row]));
  const after = new Map(latest.rows.map(row => [row.PLAYER_ID, row]));
  const events = [];
  for (const id of new Set([...before.keys(), ...after.keys()])) {
    const oldRow = before.get(id) || null;
    const row = after.get(id) || null;
    if (oldRow && row && ["rank", "fpts_pg", "mpg", "TEAM_ABBREVIATION", "analyst_action", "analyst_date"]
        .every(key => oldRow[key] === row[key])) continue;
    const kind = !oldRow ? "added" : !row ? "removed" :
      oldRow.fpts_pg === row.fpts_pg && oldRow.mpg === row.mpg && oldRow.TEAM_ABBREVIATION === row.TEAM_ABBREVIATION &&
      oldRow.analyst_action === row.analyst_action && oldRow.analyst_date === row.analyst_date ? "rank-only" : "changed";
    const analystChanged = Boolean(oldRow && row && (oldRow.analyst_action !== row.analyst_action || oldRow.analyst_date !== row.analyst_date));
    const explanation = kind === "added" ? "New to this board; no previous value is assumed." :
      kind === "removed" ? "Absent from this board; no current value is assumed." :
      kind === "rank-only" ? "Rank moved while this player's projection stayed the same." :
      analystChanged ? `Recorded analyst action/date changed${row.analyst_date ? ` on ${row.analyst_date}` : ""}; this is context, not proof of cause.` :
      "Projection changed; no specific cause is recorded in this archive.";
    events.push({ id, name: row?.PLAYER_NAME || oldRow.PLAYER_NAME, team: row?.TEAM_ABBREVIATION || oldRow.TEAM_ABBREVIATION || null,
      kind, before: oldRow, after: row, fptsDelta: oldRow && row && oldRow.fpts_pg != null && row.fpts_pg != null ? +(row.fpts_pg - oldRow.fpts_pg).toFixed(2) : null,
      mpgDelta: oldRow && row && oldRow.mpg != null && row.mpg != null ? +(row.mpg - oldRow.mpg).toFixed(2) : null,
      rankDelta: oldRow && row ? oldRow.rank - row.rank : null, explanation });
  }
  return events.sort((a, b) => Math.abs(b.fptsDelta || 0) - Math.abs(a.fptsDelta || 0) ||
    Math.abs(b.rankDelta || 0) - Math.abs(a.rankDelta || 0) || (a.after?.rank ?? a.before?.rank ?? Infinity) - (b.after?.rank ?? b.before?.rank ?? Infinity) || a.id - b.id);
}
