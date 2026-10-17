// Capacity of a manual snake draft; IR slots are never drafted.
export function draftCapacity(config) {
  const perTeam = Object.entries(config.roster || {}).filter(([slot]) => slot.toUpperCase() !== "IR")
    .reduce((sum, [, count]) => sum + Number(count), 0);
  return { perTeam, total: perTeam * config.teams };
}

export function manualPickProblem(config, picks, playerId, team) {
  const { perTeam, total } = draftCapacity(config);
  if (picks.length >= total) return "Draft complete. Undo a pick to make a correction.";
  if (!Number.isInteger(team) || team < 1 || team > config.teams) return "Choose the receiving team.";
  if (picks.some(pick => pick.playerId === playerId)) return "This player has already been drafted.";
  if (picks.filter(pick => pick.team === team).length >= perTeam) return `Team ${team}'s drafted roster is full.`;
  return null;
}
