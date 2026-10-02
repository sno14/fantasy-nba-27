export const PRACTICE_KEY = "fantasy-nba-practice-v1";
export const PRACTICE_VERSION = 1;
export const MAX_RUNS = 10;

const positive = value => Number.isSafeInteger(value) && value > 0;
const playerId = value => Number.isSafeInteger(value) && value !== 0;
const finite = value => typeof value === "number" && Number.isFinite(value);
export function practiceRounds(roster) {
  if (!roster || typeof roster !== "object" || Array.isArray(roster)) return 0;
  const entries = Object.entries(roster);
  if (!entries.length || entries.some(([slot, count]) => !["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL", "BENCH", "IR"].includes(slot) || !Number.isInteger(count) || count < 0 || count > 20) ||
      entries.filter(([slot]) => !["IR", "BENCH"].includes(slot)).reduce((sum, [, count]) => sum + count, 0) > 20) return 0;
  const values = entries.filter(([slot]) => slot !== "IR");
  const total = values.reduce((sum, [, count]) => sum + count, 0);
  return total >= 1 && total <= 30 ? total : 0;
}

export function practiceTeam(overall, teams) {
  if (!positive(overall) || !positive(teams)) return null;
  const roundIndex = Math.floor((overall - 1) / teams);
  const slot = (overall - 1) % teams;
  return roundIndex % 2 ? teams - slot : slot + 1;
}

function compactPlayer(row) {
  const id = Number(row.PLAYER_ID ?? row.id);
  const rank = Number(row.rank);
  const name = String(row.PLAYER_NAME ?? row.name ?? "").trim();
  const rawPositions = row.positions;
  const positions = Array.isArray(rawPositions) ? rawPositions : String(rawPositions || "").split("|");
  if (!playerId(id) || !positive(rank) || !name || name.length > 120) throw new Error("Board contains an invalid player.");
  const adp = row.adp == null ? null : Number(row.adp);
  const fptsPg = Number(row.fpts_pg ?? row.fptsPg);
  const fptsTotal = row.fpts_total ?? row.fptsTotal;
  return { id, rank, name, adp: finite(adp) && adp > 0 ? adp : null,
    fptsPg: finite(fptsPg) ? fptsPg : null,
    fptsTotal: finite(Number(fptsTotal)) && fptsTotal != null ? Number(fptsTotal) : null,
    positions: [...new Set(positions.filter(value => typeof value === "string" && /^[A-Z]{1,4}$/.test(value)))].slice(0, 8) };
}

export function snapshotPlayers(rows) {
  if (!Array.isArray(rows) || rows.length > 2000) throw new Error("The board has too many players for a practice run.");
  const players = rows.map(compactPlayer);
  if (new Set(players.map(player => player.id)).size !== players.length) throw new Error("Board has duplicate player IDs.");
  return players;
}

export function opponentChoice(players, taken, rule) {
  const before = (a, b) => {
    if (rule !== "adp") return a.rank - b.rank || a.id - b.id;
    if (a.adp == null || b.adp == null)
      return a.adp == null && b.adp == null ? a.rank - b.rank || a.id - b.id : a.adp == null ? 1 : -1;
    return a.adp - b.adp || a.id - b.id;
  };
  let best = null;
  for (const player of players) if (!taken.has(player.id) && (!best || before(player, best) < 0)) best = player;
  return best;
}

export function advancePractice(run) {
  const picks = [...run.picks];
  const taken = new Set(picks.map(pick => pick.playerId));
  const limit = run.config.teams * practiceRounds(run.config.roster);
  while (picks.length < limit && practiceTeam(picks.length + 1, run.config.teams) !== run.config.position) {
    const player = opponentChoice(run.snapshot.players, taken, run.config.rule);
    if (!player) break;
    picks.push({ playerId: player.id, team: practiceTeam(picks.length + 1, run.config.teams) });
    taken.add(player.id);
  }
  return { ...run, picks };
}

export function createPracticeRun({ name, teams, position, rule, roster, season, source, ranking, marketDate, boardDate, rows }) {
  const players = snapshotPlayers(rows);
  const rounds = practiceRounds(roster);
  if (typeof name !== "string" || !name.trim() || name.trim().length > 60 ||
      !Number.isInteger(teams) || teams < 2 || teams > 20 ||
      !Number.isInteger(position) || position < 1 || position > teams ||
      !["adp", "board"].includes(rule) || !rounds || players.length < teams * rounds ||
      typeof season !== "string" || !/^\d{4}-\d{2}$/.test(season) ||
      !["public", "local"].includes(source) || !["FP/G ordinal", "learned/safe season value"].includes(ranking))
    throw new Error("Check the run name, draft settings, roster size and available board.");
  const run = { version: PRACTICE_VERSION, id: crypto.randomUUID(), name: name.trim(), createdAt: new Date().toISOString(),
    config: { teams, position, rule, roster: { ...roster } },
    snapshot: { season, source, ranking, marketDate: marketDate || null, boardDate: boardDate || null, players },
    picks: [], checkpoints: [] };
  return advancePractice(run);
}

export function choosePracticePlayer(run, playerId) {
  const limit = run.config.teams * practiceRounds(run.config.roster);
  if (run.picks.length >= limit || practiceTeam(run.picks.length + 1, run.config.teams) !== run.config.position)
    throw new Error("Wait for your turn or start another run.");
  if (!run.snapshot.players.some(player => player.id === playerId) || run.picks.some(pick => pick.playerId === playerId))
    throw new Error("Choose an available player from this run's saved board.");
  const checkpoint = run.picks.length;
  return advancePractice({ ...run, picks: [...run.picks, { playerId, team: run.config.position }], checkpoints: [...run.checkpoints, checkpoint] });
}

export function undoPracticePick(run) {
  if (!run.checkpoints.length) return run;
  const cut = run.checkpoints.at(-1);
  return { ...run, picks: run.picks.slice(0, cut), checkpoints: run.checkpoints.slice(0, -1) };
}

export function validatePracticeRun(run) {
  if (!run || run.version !== PRACTICE_VERSION || typeof run.id !== "string" || !run.id ||
      run.id.length > 100 ||
      typeof run.name !== "string" || !run.name.trim() || run.name.length > 60 ||
      typeof run.createdAt !== "string" || !Number.isFinite(Date.parse(run.createdAt)) || !run.config || !run.snapshot ||
      !Array.isArray(run.picks) || !Array.isArray(run.checkpoints)) throw new Error("Invalid practice run.");
  const { teams, position, rule, roster } = run.config;
  const rounds = practiceRounds(roster);
  if (!Number.isInteger(teams) || teams < 2 || teams > 20 || !Number.isInteger(position) || position < 1 || position > teams ||
      !["adp", "board"].includes(rule) || !rounds ||
      !/^\d{4}-\d{2}$/.test(run.snapshot.season || "") ||
      !["public", "local"].includes(run.snapshot.source) ||
      !["FP/G ordinal", "learned/safe season value"].includes(run.snapshot.ranking) ||
      !(run.snapshot.marketDate === null || (typeof run.snapshot.marketDate === "string" && run.snapshot.marketDate.length <= 40)) ||
      !(run.snapshot.boardDate === null || (typeof run.snapshot.boardDate === "string" && run.snapshot.boardDate.length <= 60)) ||
      !Array.isArray(run.snapshot.players) || run.snapshot.players.length < teams * rounds || run.snapshot.players.length > 2000 ||
      run.picks.length > teams * rounds) throw new Error("Invalid practice settings or snapshot.");
  const players = snapshotPlayers(run.snapshot.players);
  const ids = new Set(players.map(player => player.id));
  const taken = new Set();
  run.picks.forEach((pick, index) => {
    if (!pick || !ids.has(pick.playerId) || taken.has(pick.playerId) || pick.team !== practiceTeam(index + 1, teams))
      throw new Error("Invalid practice picks.");
    if (pick.team !== position && opponentChoice(players, taken, rule)?.id !== pick.playerId)
      throw new Error("Opponent picks do not match this run's strategy.");
    taken.add(pick.playerId);
  });
  if (run.picks.length < teams * rounds && practiceTeam(run.picks.length + 1, teams) !== position)
    throw new Error("Practice run stops before the manager's turn.");
  let previous = -1;
  for (const cut of run.checkpoints) {
    if (!Number.isInteger(cut) || cut <= previous || cut >= run.picks.length ||
        practiceTeam(cut + 1, teams) !== position || run.picks[cut].team !== position)
      throw new Error("Invalid practice undo history.");
    previous = cut;
  }
  if (run.picks.filter(pick => pick.team === position).length !== run.checkpoints.length) throw new Error("Incomplete practice undo history.");
  return run;
}

export function parsePracticeRuns(value) {
  if (!Array.isArray(value) || value.length > MAX_RUNS) throw new Error("Practice storage must contain at most 10 runs.");
  const runs = value.map(validatePracticeRun);
  if (new Set(runs.map(run => run.id)).size !== runs.length) throw new Error("Duplicate practice run IDs.");
  return runs;
}

function fits(slot, positions) {
  if (slot === "UTIL") return true;
  if (slot === "G") return positions.includes("PG") || positions.includes("SG");
  if (slot === "F") return positions.includes("SF") || positions.includes("PF");
  return positions.includes(slot);
}

export function practiceSummary(run) {
  const byId = new Map(run.snapshot.players.map(player => [player.id, player]));
  const own = run.picks.filter(pick => pick.team === run.config.position).map(pick => byId.get(pick.playerId));
  const slots = Object.entries(run.config.roster).filter(([slot]) => !["IR", "BENCH"].includes(slot.toUpperCase())).flatMap(([slot, count]) => Array(count).fill(slot));
  if (slots.length > 20) throw new Error("Too many starting slots.");
  let states = new Map([[0, { score: 0, chosen: [] }]]);
  for (const player of own) {
    const next = new Map(states);
    for (const [mask, result] of states) for (let index = 0; index < slots.length; index++) {
      if ((mask & (1 << index)) || !fits(slots[index], player.positions)) continue;
      const bit = mask | (1 << index);
      const score = result.score + (player.fptsPg || 0);
      if (!next.has(bit) || next.get(bit).score < score) next.set(bit, { score, chosen: [...result.chosen, player.id] });
    }
    states = next;
  }
  const best = [...states.entries()].sort((a, b) => b[1].score - a[1].score || b[1].chosen.length - a[1].chosen.length)[0];
  const positions = Object.fromEntries(["PG", "SG", "SF", "PF", "C"].map(slot => [slot, own.filter(player => player.positions.includes(slot)).length]));
  return { own, starters: best[1].chosen.length, starterFpg: best[1].score,
    openStarters: slots.length - best[1].chosen.length, depth: own.length - best[1].chosen.length,
    seasonFp: own.reduce((sum, player) => sum + (player.fptsTotal || 0), 0),
    unknownEligibility: own.filter(player => !player.positions.length).length,
    unknownSeasonTotal: own.filter(player => player.fptsTotal == null).length, positions };
}
