import { downloadBackup, MAX_FILE_BYTES, normalizeTarget, parseIds, snakePicks, validateBackup } from "./workspace.mjs";
import { choosePracticePlayer, createPracticeRun, MAX_RUNS, parsePracticeRuns, PRACTICE_KEY, practiceRounds, practiceSummary, practiceTeam, undoPracticePick, validatePracticeRun } from "./practice.mjs";
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const fmt = (value, digits = 1) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(digits);
const integer = (value) => fmt(value, 0);
const signed = (value, digits = 1) => value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(digits)}`;
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);

function storageUnavailable() {
  const note = $("#storage-note");
  if (note) note.hidden = false;
}

function readStored(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key) || "null") ?? fallback; }
  catch (error) {
    if (!(error instanceof SyntaxError)) storageUnavailable();
    return fallback;
  }
}

function writeStored(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); }
  catch (_) { storageUnavailable(); }
}

const savedCompare = readStored("fantasy-nba-compare", []);
const state = {
  rows: [], meta: null, view: "board", query: "", team: "All", tier: "All",
  radar: "All", adjustedOnly: false, limit: 100, sort: "rank", direction: 1,
  compare: new Set(Array.isArray(savedCompare) ? savedCompare.filter(Number.isInteger).slice(0, 4) : []),
  preset: "draft", layout: "auto",
  targets: {}, playerId: null, season: "",
  mock: { picks: [], myTeam: 1, query: "", radar: "All", limit: 60 },
  practice: { runs: [], selected: null, query: "" },
};

const TARGETS_KEY = "fantasy-nba-draft-targets-v1";

function loadTargets() {
  const saved = readStored(TARGETS_KEY, {});
  if (saved && typeof saved === "object" && !Array.isArray(saved)) {
    for (const [id, target] of Object.entries(saved)) {
      if (!/^[1-9]\d*$/.test(id)) continue;
      try { state.targets[id] = normalizeTarget(target); } catch { /* Ignore invalid saved entries. */ }
    }
  }
}

function saveTargets() {
  writeStored(TARGETS_KEY, state.targets);
  drawPlan();
}

function isTarget(row) { return Boolean(state.targets[String(row.PLAYER_ID)]); }
function radarName(label) { return ({ strong_target: "Strong target", target: "Target", fade: "Fade", strong_fade: "Strong fade" })[label] || ""; }
function radarMatches(row, filter) {
  if (filter === "Targets") return String(row.radar_label || "").includes("target");
  if (filter === "Fades") return String(row.radar_label || "").includes("fade");
  if (filter === "Watchlist") return isTarget(row);
  return true;
}

function radarMarkup(row, currentPick = null, interactive = true) {
  const chip = (tone, label, title) => interactive
    ? `<button type="button" class="chip radar-button ${tone}" data-player="${row.PLAYER_ID}" title="${esc(title)}" aria-label="Explain ${esc(label)} for ${esc(row.PLAYER_NAME)}">${esc(label)}</button>`
    : `<span class="chip ${tone}" title="${esc(title)}">${esc(label)}</span>`;
  const target = state.targets[String(row.PLAYER_ID)];
  if (target) {
    const due = target.takeBy != null && currentPick != null && currentPick >= target.takeBy;
    const label = due ? "★ due" : target.takeBy ? `★ by ${target.takeBy}` : "★ priority";
    const title = [row.radar_reasons, target.takeBy ? `Take by overall pick ${target.takeBy}` : "", target.note].filter(Boolean).join(" · ");
    return chip(due ? "watch-due" : "watch", label, title);
  }
  if (!row.radar_label) return "";
  const tone = String(row.radar_label).includes("target") ? "up" : row.radar_label === "strong_fade" ? "down" : "fade";
  return chip(tone, radarName(row.radar_label), row.radar_reasons || "");
}

function openTarget(row) {
  const target = state.targets[String(row.PLAYER_ID)] || {};
  $("#target-player-name").textContent = row.PLAYER_NAME;
  $("#target-player-id").value = row.PLAYER_ID;
  $("#target-take-by").value = target.takeBy ?? (row.adp != null ? Math.max(1, Math.round(row.adp - 12)) : "");
  $("#target-note").value = target.note || "";
  $("#target-round").value = target.preferredRound ?? "";
  $("#target-group").value = target.backupGroup ?? "";
  $("#target-priority").value = target.priority ?? "";
  $("#target-status").value = target.status || "active";
  $("#target-error").textContent = "";
  $("#target-remove").hidden = !isTarget(row);
  const dialog = $("#target-dialog");
  if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
}

const viewCopy = {
  board: ["Draft Board", "Projected fantasy points per game with analyst layer applied."],
  mock: ["Manual Mock Draft", "Assign every pick yourself; the draft and roster summaries stay in this browser."],
  tiers: ["Projection Tiers", "Value bands from unusually large adjacent FP/G gaps."],
  teams: ["Team Overview", "Projected leaders and top-five strength for every NBA team."],
  compare: ["Player Compare", "Put up to four projections side by side."],
  plan: ["My Draft Plan", "Your targets, upcoming picks and roster needs."],
  practice: ["Practice My Draft", "Test choices in a saved, repeatable snake draft."],
  method: ["Methodology", "What this public snapshot includes—and what remains local."],
};

function loadMock() {
  const saved = readStored("fantasy-nba-mock", {});
  if (saved && typeof saved === "object") {
    state.mock.picks = Array.isArray(saved.picks) ? saved.picks.filter(pick => pick && Number.isInteger(pick.playerId) && Number.isInteger(pick.team)) : [];
    state.mock.myTeam = Number(saved.myTeam) || 1;
  }
}

function saveMock() {
  writeStored("fantasy-nba-mock", { picks: state.mock.picks, myTeam: state.mock.myTeam });
  $("#mock-count").textContent = state.mock.picks.length || "";
  drawPlan();
}

function mockConfig() {
  return state.meta?.draft_config || { teams: 10, roster: { PG: 1, SG: 1, SF: 1, PF: 1, C: 1, G: 1, F: 1, UTIL: 3, BENCH: 3, IR: 1 } };
}

function teamForPick(pickIndex) {
  const n = mockConfig().teams;
  const round = Math.floor(pickIndex / n);
  const inRound = pickIndex % n;
  return round % 2 === 0 ? inRound + 1 : n - inRound;
}

function playerPositions(row) {
  return String(row?.positions || "").split("|").filter(Boolean);
}

function fillsSlot(slot, positions) {
  if (slot === "UTIL") return true;
  if (slot === "G") return positions.includes("PG") || positions.includes("SG");
  if (slot === "F") return positions.includes("SF") || positions.includes("PF");
  return positions.includes(slot);
}

function rosterFit(players) {
  const roster = mockConfig().roster || {};
  const priority = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"];
  const open = Object.fromEntries(priority.filter(slot => roster[slot]).map(slot => [slot, Number(roster[slot])]));
  let starterFpg = 0;
  players.forEach(player => {
    const positions = playerPositions(player);
    const slot = priority.find(name => open[name] > 0 && fillsSlot(name, positions));
    if (slot) {
      open[slot] -= 1;
      starterFpg += Number(player.fpts_pg) || 0;
    }
  });
  return { open, starterFpg };
}

function drawPlan() {
  if (!state.rows.length) return;
  const config = mockConfig();
  const fromOverall = state.mock.picks.length + 1;
  const rounds = Object.entries(config.roster || {}).filter(([slot]) => slot !== "IR").reduce((sum, [, count]) => sum + Number(count), 0);
  const order = Array.from({ length: config.teams }, (_, index) => index + 1);
  const picks = snakePicks(order, state.mock.myTeam, fromOverall, Math.min(30, rounds));
  const selected = state.mock.picks.filter(pick => pick.team === state.mock.myTeam);
  const owned = new Map(state.mock.picks.map(pick => [pick.playerId, pick.team]));
  const byId = new Map(state.rows.map(row => [row.PLAYER_ID, row]));
  const tierRemaining = new Map();
  state.rows.forEach(row => { if (row.tier != null && !owned.has(row.PLAYER_ID)) tierRemaining.set(row.tier, (tierRemaining.get(row.tier) || 0) + 1); });
  const fit = rosterFit(selected.map(pick => byId.get(pick.playerId)).filter(Boolean));
  const openSlots = Object.entries(fit.open).filter(([, count]) => count > 0).map(([slot, count]) => `${slot} ${count}`);
  const entries = Object.entries(state.targets).map(([id, target]) => ({ id: Number(id), row: byId.get(Number(id)), target, owner: owned.get(Number(id)) }));
  const active = entries.filter(item => item.target.status === "active" && !item.owner && item.row);
  const overdue = active.filter(item => item.target.takeBy != null && item.target.takeBy < fromOverall);
  $("#plan-team").value = String(state.mock.myTeam);
  $("#plan-summary").innerHTML = [
    ["Next planned pick", picks.length ? `#${picks[0].overall}` : "—", picks.length ? `Round ${picks[0].round} · Team ${state.mock.myTeam}` : "Draft complete"],
    ["Remaining targets", String(active.length), `${entries.length} saved targets`],
    ["Past take-by pick", String(overdue.length), "Available targets only"],
    ["Open starters", openSlots.length ? String(openSlots.reduce((n, x) => n + Number(x.split(" ")[1]), 0)) : "0", openSlots.join(" · ") || "None"],
  ].map(([label, value, note]) => `<article class="summary-card"><small>${esc(label)}</small><strong>${esc(value)}</strong><em>${esc(note)}</em></article>`).join("");
  const unknownPositions = selected.some(pick => !playerPositions(byId.get(pick.playerId)).length);
  $("#plan-source").textContent = `Published ${state.season} board · ADP vintage ${state.meta.market_date || "unavailable"}. ${picks.length ? `Upcoming picks: ${picks.slice(0, 5).map(pick => `#${pick.overall} (R${pick.round})`).join(", ")}.` : "No picks remain in this scenario."} ${unknownPositions ? "Open starting slots are an estimate because some drafted players have unknown eligibility." : ""}`;
  const groups = new Map();
  for (const item of entries) {
    const round = item.target.preferredRound ?? (item.target.takeBy ? Math.ceil(item.target.takeBy / config.teams) : null);
    const key = round && round <= rounds ? round : "Unassigned";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  }
  if (!entries.length) { $("#plan-groups").innerHTML = `<div class="empty">No targets yet. Star a player on the <button class="link-button" data-go="board">Draft Board</button> to begin.</div>`; return; }
  $("#plan-groups").innerHTML = [...groups].sort(([a], [b]) => a === "Unassigned" ? 1 : b === "Unassigned" ? -1 : a - b).map(([round, items]) => {
    const upcoming = typeof round === "number" ? picks.find(pick => pick.round === round) : null;
    const sorted = items.sort((a, b) => (a.target.backupGroup || "").localeCompare(b.target.backupGroup || "") || (a.target.priority ?? 1001) - (b.target.priority ?? 1001) || (a.row?.rank ?? 9999) - (b.row?.rank ?? 9999));
    return `<section class="panel plan-group"><header><h2>${round === "Unassigned" ? "Unassigned targets" : `Round ${round}`}</h2><span>${upcoming ? `Your pick #${upcoming.overall}` : round === "Unassigned" ? "Choose a round in Edit plan" : "Pick already passed or not yours"}</span></header>${sorted.map(({ id, row, target, owner }) => {
      const availability = owner ? owner === state.mock.myTeam ? "Drafted by you" : `Drafted by Team ${owner}` : !row ? "Absent from this board" : target.status === "hold" ? "On hold" : target.takeBy != null && target.takeBy < fromOverall ? "Past take-by pick" : target.takeBy === fromOverall ? "Due now" : "Available";
      const conflict = !owner && upcoming && target.takeBy != null && upcoming.overall > target.takeBy;
      return `<div class="plan-row"><div><strong>${row ? esc(row.PLAYER_NAME) : `Player ID ${id}`}</strong><small>${row ? `#${row.rank} · ${fmt(row.fpts_pg)} FP/G · ADP ${integer(row.adp)}${row.tier != null ? ` · Tier ${integer(row.tier)} (${tierRemaining.get(row.tier) || 0} remain)` : ""}` : "No current projection"}</small><small>${target.backupGroup ? `Backup: ${esc(target.backupGroup)} · ` : ""}${target.priority ? `Priority ${target.priority} · ` : ""}${target.takeBy ? `Take by #${target.takeBy}` : "No take-by pick"}</small>${conflict ? `<small class="plan-deadline">Your round pick #${upcoming.overall} is after take-by #${target.takeBy}.</small>` : ""}${target.note ? `<p>${esc(target.note)}</p>` : ""}</div><span class="plan-status">${esc(availability)}</span>${row ? `<button class="button subtle-action" data-target-player="${id}">Edit plan</button>` : `<button class="button subtle-action" data-plan-remove="${id}">Remove</button>`}</div>`;
    }).join("")}</section>`;
  }).join("");
}

function loadPractice() {
  try { state.practice.runs = parsePracticeRuns(readStored(PRACTICE_KEY, [])); }
  catch { state.practice.runs = []; }
}

function savePractice(runs) {
  state.practice.runs = runs;
  try { localStorage.setItem(PRACTICE_KEY, JSON.stringify(runs)); $("#practice-message").textContent = ""; }
  catch { storageUnavailable(); $("#practice-message").textContent = "Browser storage is full or unavailable. Export this run to keep it."; }
  drawPractice();
}

function exportPractice(run) {
  const blob = new Blob([JSON.stringify(run, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `fantasy-nba-practice-${run.snapshot.season}-${run.name.replace(/[^a-z0-9-]+/gi, "-").toLowerCase()}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function drawPractice() {
  const runs = state.practice.runs;
  const run = runs.find(item => item.id === state.practice.selected) || runs[0];
  const summary = run ? practiceSummary(run) : null;
  const currentBoardDate = state.meta?.market_date || null;
  $("#practice-current").innerHTML = !run ? `<div class="empty">No practice runs yet. Start one from the current board.</div>` : (() => {
    const limit = run.config.teams * practiceRounds(run.config.roster);
    const next = run.picks.length + 1;
    const yourTurn = next <= limit && practiceTeam(next, run.config.teams) === run.config.position;
    const taken = new Set(run.picks.map(pick => pick.playerId));
    const query = state.practice.query.toLowerCase();
    const choices = run.snapshot.players.filter(player => !taken.has(player.id) && player.name.toLowerCase().includes(query)).sort((a, b) => a.rank - b.rank || a.id - b.id).slice(0, 100);
    const byId = new Map(run.snapshot.players.map(player => [player.id, player]));
    const metrics = [["Projected season FP", integer(summary.seasonFp)], ["Feasible starter FP/G", fmt(summary.starterFpg)], ["Open starters", summary.openStarters], ["Depth outside starters", summary.depth]];
    return `<section class="panel practice-current"><header><div><h2>${esc(run.name)}</h2><p>${esc(run.snapshot.season)} · ${esc(run.snapshot.ranking)} · Board captured ${esc(new Date(run.createdAt).toLocaleString())} · ADP ${esc(run.snapshot.marketDate || "unavailable")} · ${run.config.teams} teams · slot ${run.config.position} · ${run.config.rule === "adp" ? "ADP" : "board rank"} opponents</p></div><div class="practice-actions"><button class="button subtle-action" data-practice-undo ${run.checkpoints.length ? "" : "disabled"}>Undo my last pick</button><button class="button subtle-action" data-practice-export="${esc(run.id)}">Export run</button></div></header>
      <p class="status">${run.snapshot.marketDate === currentBoardDate ? "Using this run's saved board snapshot." : "The published board has changed or is unavailable; this run keeps its original projections and pick order."}</p>
      <strong>${yourTurn ? `Your pick #${next} · round ${Math.ceil(next / run.config.teams)}` : `Draft complete · ${run.picks.length} picks`}</strong>
      <div class="summary-grid">${metrics.map(([label, value]) => `<article class="summary-card"><small>${esc(label)}</small><strong>${esc(value)}</strong></article>`).join("")}</div>
      <p class="status">Positions: ${Object.entries(summary.positions).map(([slot, count]) => `${slot} ${count}`).join(" · ")}. ${summary.unknownEligibility ? `${summary.unknownEligibility} player(s) have unknown eligibility and can only fill UTIL here. ` : ""}${summary.unknownSeasonTotal ? `${summary.unknownSeasonTotal} player(s) lack season totals; the sum excludes them.` : ""}</p>
      <div class="practice-grid"><div><h3>Your available choices</h3><input id="practice-search" type="search" placeholder="Search saved board…" value="${esc(state.practice.query)}" aria-label="Search practice players" /><div class="practice-list">${choices.map(player => `<div><span><strong>${esc(player.name)}</strong><small>#${player.rank} · ${fmt(player.fptsPg)} FP/G · ADP ${fmt(player.adp)}</small></span><button class="button subtle-action" data-practice-pick="${player.id}" ${yourTurn ? "" : "disabled"}>Pick</button></div>`).join("") || `<p>No matching available players.</p>`}</div></div><div><h3>Pick history</h3><div class="practice-list">${run.picks.slice().reverse().map((pick, index) => `<div class="${pick.team === run.config.position ? "mine" : ""}"><span>#${run.picks.length - index} ${esc(byId.get(pick.playerId)?.name || `Player ${pick.playerId}`)}</span><small>Team ${pick.team}${pick.team === run.config.position ? " · you" : ""}</small></div>`).join("")}</div></div></div></section>`;
  })();
  $("#practice-runs").innerHTML = runs.map(item => {
    const view = practiceSummary(item);
    return `<div class="practice-run"><div><strong>${esc(item.name)}</strong><small>${esc(item.snapshot.marketDate || "No ADP date")} · ${item.config.teams} teams · slot ${item.config.position} · ${view.own.length} of ${practiceRounds(item.config.roster)} picks · ${view.starters} starters at ${fmt(view.starterFpg)} FP/G · ${view.depth} depth · ${integer(view.seasonFp)} season FP${view.unknownSeasonTotal ? ` (${view.unknownSeasonTotal} totals missing)` : ""}</small><small>Position mix: ${Object.entries(view.positions).map(([slot, count]) => `${slot} ${count}`).join(" · ")}${view.unknownEligibility ? ` · ${view.unknownEligibility} eligibility unknown` : ""}</small></div><div class="practice-actions"><button class="button subtle-action" data-practice-open="${esc(item.id)}">Open</button><button class="button subtle-action" data-practice-delete="${esc(item.id)}">Delete</button></div></div>`;
  }).join("");
  $("#practice-form button[type=submit]").disabled = !state.rows.length || runs.length >= MAX_RUNS;
}

function draftPlayer(playerId) {
  const team = Number($("#mock-team").value) || teamForPick(state.mock.picks.length);
  if (state.mock.picks.some(pick => pick.playerId === playerId)) return;
  state.mock.picks.push({ playerId, team });
  saveMock();
  drawMock();
}

function drawMock() {
  if (!state.rows.length) return;
  const config = mockConfig();
  const draftedIds = new Set(state.mock.picks.map(pick => pick.playerId));
  const playerById = new Map(state.rows.map(row => [row.PLAYER_ID, row]));
  const pickIndex = state.mock.picks.length;
  const onClock = teamForPick(pickIndex);
  const round = Math.floor(pickIndex / config.teams) + 1;
  $("#mock-clock-team").textContent = `Team ${onClock}${onClock === state.mock.myTeam ? " · yours" : ""}`;
  $("#mock-clock-detail").textContent = `Pick ${pickIndex + 1} · Round ${round}`;
  $("#mock-team").value = String(onClock);
  $("#mock-my-team").value = String(state.mock.myTeam);
  $("#mock-undo").disabled = !pickIndex;
  $("#mock-reset").disabled = !pickIndex;

  const query = state.mock.query.trim().toLowerCase();
  const available = state.rows.filter(row => !draftedIds.has(row.PLAYER_ID) && radarMatches(row, state.mock.radar) && (!query || `${row.PLAYER_NAME} ${row.TEAM_ABBREVIATION || ""} ${row.positions || ""}`.toLowerCase().includes(query)));
  $("#mock-rows").innerHTML = available.slice(0, state.mock.limit).map(row => `<tr>
    <td class="rank tnum">${row.rank}</td>
    <td class="player-col"><button class="player-button" data-player="${row.PLAYER_ID}">${esc(row.PLAYER_NAME)}</button><button class="target-star ${isTarget(row) ? "active" : ""}" data-target-player="${row.PLAYER_ID}" title="${isTarget(row) ? "Edit priority target" : "Add priority target"}">${isTarget(row) ? "★" : "☆"}</button><small>${esc(row.TEAM_ABBREVIATION || "—")}</small></td>
    <td class="muted">${esc((row.positions || "—").replaceAll("|", "/"))}</td>
    <td class="fpg tnum">${fmt(row.fpts_pg)}</td>
    <td class="tnum">${integer(row.adp)}</td>
    <td>${radarMarkup(row, pickIndex + 1)}</td>
    <td><button class="draft-button" data-draft-player="${row.PLAYER_ID}">Draft</button></td>
  </tr>`).join("");

  const recent = state.mock.picks.slice(-12).reverse();
  $("#mock-pick-total").textContent = `${pickIndex} picks`;
  $("#mock-picks").innerHTML = recent.length ? recent.map((pick, reverseIndex) => {
    const overall = pickIndex - reverseIndex;
    const player = playerById.get(pick.playerId);
    return `<div class="mock-pick"><span>#${overall}</span><strong>${esc(player?.PLAYER_NAME || "Unavailable player")}</strong><b>Team ${pick.team}</b></div>`;
  }).join("") : `<p class="mock-empty">No picks yet. Choose a player to begin.</p>`;

  const teams = Array.from({ length: config.teams }, (_, index) => index + 1).map(team => {
    const picks = state.mock.picks.filter(pick => pick.team === team);
    const players = picks.map(pick => playerById.get(pick.playerId)).filter(Boolean);
    const seasonFp = players.reduce((sum, row) => sum + (Number(row.fpts_total) || 0), 0);
    const avg = players.reduce((sum, row) => sum + (Number(row.fpts_pg) || 0), 0) / Math.max(players.length, 1);
    return { team, players, seasonFp, avg, fit: rosterFit(players) };
  });
  const ranked = [...teams].sort((a, b) => b.seasonFp - a.seasonFp);
  const myRank = ranked.findIndex(team => team.team === state.mock.myTeam) + 1;
  const topAvailable = available[0];
  $("#mock-summary").innerHTML = [
    ["Draft progress", `${pickIndex} picks`, `${round} of ${Object.entries(config.roster || {}).filter(([slot]) => slot !== "IR").reduce((sum, [, count]) => sum + Number(count), 0)} roster rounds`],
    ["Best available", topAvailable ? `#${topAvailable.rank}` : "—", topAvailable?.PLAYER_NAME || "Draft complete"],
    ["Your power rank", pickIndex ? `#${myRank}` : "—", `Team ${state.mock.myTeam} by projected season FP`],
    ["ADP vintage", state.meta?.market_date || "Current export", `${state.rows.filter(row => row.adp != null).length} players covered`],
  ].map(([label, value, note]) => `<article class="summary-card"><small>${label}</small><strong>${esc(value)}</strong><em>${esc(note)}</em></article>`).join("");

  $("#mock-teams").innerHTML = teams.map(({ team, players, seasonFp, avg, fit }) => {
    const unfilled = Object.entries(fit.open).filter(([, count]) => count > 0).map(([slot, count]) => `${slot}${count > 1 ? ` ×${count}` : ""}`);
    return `<article class="mock-team-card panel ${team === state.mock.myTeam ? "mine" : ""}">
      <header><div><h3>Team ${team}${team === state.mock.myTeam ? " · yours" : ""}</h3><span>${players.length} players · ${integer(seasonFp)} season FP</span></div><b>${fmt(avg)}<small>avg FP/G</small></b></header>
      <div class="slot-line"><span>Open starters</span><strong>${unfilled.length ? esc(unfilled.join(" · ")) : "Complete"}</strong></div>
      <div class="mock-roster">${players.length ? players.map((row, index) => `<div><span>${index + 1}</span><button data-player="${row.PLAYER_ID}">${esc(row.PLAYER_NAME)}</button><small>${esc((row.positions || "—").replaceAll("|", "/"))}</small><b>${fmt(row.fpts_pg)}</b></div>`).join("") : `<p>Awaiting first pick</p>`}</div>
    </article>`;
  }).join("");
}

function isAdjusted(row) {
  return Boolean(row.analyst_action && row.analyst_action !== "none");
}

function analystChip(row) {
  if (!isAdjusted(row)) return "";
  const action = row.analyst_action;
  const delta = action.match(/fpts_delta:([+-]?\d+(?:\.\d+)?)/);
  const minutes = action.match(/target_mpg:([+-]?\d+(?:\.\d+)?)/);
  const parts = [];
  if (minutes) parts.push(`${fmt(Number(minutes[1]), 1)} mpg`);
  if (delta) parts.push(`${Number(delta[1]) > 0 ? "+" : ""}${fmt(Number(delta[1]), 1)} FP/G`);
  const tone = delta && Number(delta[1]) < 0 ? "down" : "up";
  return `<span class="chip ${tone}" title="${esc(row.analyst_category || "Analyst adjustment")} · ${esc(row.analyst_date || "")}">${esc(parts.join(" · ") || action)}</span>`;
}

function rangeMarkup(row) {
  if ([row.fpts_p10, row.fpts_median, row.fpts_p90].some(v => v == null)) return "—";
  const span = Math.max(1, row.fpts_p90 - row.fpts_p10);
  const median = Math.max(0, Math.min(100, 100 * (row.fpts_median - row.fpts_p10) / span));
  return `<div class="range" title="p10 ${integer(row.fpts_p10)} · median ${integer(row.fpts_median)} · p90 ${integer(row.fpts_p90)}"><span>${integer(row.fpts_p10)}</span><span class="range-track"><i class="range-fill"></i><i class="range-dot" style="left:${median}%"></i></span><span>${integer(row.fpts_p90)}</span></div>`;
}

function riskMarkup(value) {
  if (value == null) return "—";
  const tone = value < .85 ? "low" : value < 1 ? "mid" : "high";
  return `<span class="risk ${tone}">${fmt(value, 2)}</span>`;
}

function changeMarkup(value) {
  if (value == null) return "—";
  const tone = value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
  return `<span class="change ${tone}">${signed(value)}</span>`;
}

function saveCompare() {
  writeStored("fantasy-nba-compare", [...state.compare]);
  const count = state.compare.size;
  $("#compare-count").textContent = count || "";
  $("#top-compare-count").textContent = count;
}

function toggleCompare(id) {
  if (state.compare.has(id)) state.compare.delete(id);
  else if (state.compare.size < 4) state.compare.add(id);
  else {
    alert("Compare supports up to four players. Remove one before adding another.");
    return;
  }
  saveCompare();
  drawBoard();
  drawCompare();
  if (state.view === "compare") writeRoute();
}

function playerMarkup(row) {
  return `<button class="player-button" data-player="${row.PLAYER_ID}">${esc(row.PLAYER_NAME)}</button><button class="target-star ${isTarget(row) ? "active" : ""}" data-target-player="${row.PLAYER_ID}" aria-label="${isTarget(row) ? "Edit" : "Add"} priority target for ${esc(row.PLAYER_NAME)}" title="${isTarget(row) ? "Edit priority target" : "Add priority target"}">${isTarget(row) ? "★" : "☆"}</button><small class="player-team">${esc(row.TEAM_ABBREVIATION || "—")}</small>`;
}

function compareMarkup(row) {
  return `<input class="row-check" type="checkbox" data-compare="${row.PLAYER_ID}" ${state.compare.has(row.PLAYER_ID) ? "checked" : ""} aria-label="Compare ${esc(row.PLAYER_NAME)}">`;
}

const BOARD_COLUMNS = [
  { key: "compare", label: "Compare", className: "compare-cell", render: compareMarkup },
  { key: "rank", label: "FP/G rank", sort: "rank", className: "rank tnum", render: row => integer(row.rank) },
  { key: "player", label: "Player", sort: "PLAYER_NAME", className: "player-col", render: playerMarkup },
  { key: "positions", label: "Position", sort: "positions", className: "muted", render: row => esc((row.positions || "—").replaceAll("|", "/")) },
  { key: "team", label: "Team", sort: "TEAM_ABBREVIATION", className: "muted", render: row => esc(row.TEAM_ABBREVIATION || "—") },
  { key: "tier", label: "Tier", sort: "tier", render: row => integer(row.tier) },
  { key: "age", label: "Age", sort: "target_age", render: row => integer(row.target_age) },
  { key: "fpg", label: "FP/G", sort: "fpts_pg", className: "fpg tnum", render: row => fmt(row.fpts_pg) },
  { key: "previous", label: "25–26 FP/G", sort: "previous_fpts_pg", render: row => fmt(row.previous_fpts_pg) },
  { key: "change", label: "Proj Δ", sort: "fpts_pg_change", render: row => changeMarkup(row.fpts_pg_change) },
  { key: "vor", label: "VOR", sort: "vor", render: row => fmt(row.vor) },
  { key: "adp", label: "ADP", sort: "adp", render: row => integer(row.adp) },
  { key: "radar", label: "Radar", sort: "radar_round_gap", render: row => radarMarkup(row) },
  { key: "mpg", label: "MPG", sort: "mpg", render: row => fmt(row.mpg) },
  { key: "gp", label: "GP", sort: "gp", render: row => integer(row.gp) },
  { key: "range", label: "Season range", render: rangeMarkup },
  { key: "median", label: "Season median", sort: "fpts_median", render: row => integer(row.fpts_median) },
  { key: "risk", label: "Risk", sort: "risk", render: row => riskMarkup(row.risk) },
  { key: "analyst", label: "Analyst", render: analystChip },
];

const COLUMN_PRESETS = {
  draft: ["compare", "rank", "player", "positions", "fpg", "adp", "radar"],
  performance: ["compare", "rank", "player", "positions", "fpg", "previous", "change", "mpg", "gp"],
  risk: ["compare", "rank", "player", "fpg", "gp", "range", "median", "risk"],
  full: BOARD_COLUMNS.map(column => column.key),
};
const PREFERENCES_KEY = "fantasy-nba-board-preferences-v1";
const BOARD_DEFAULTS = { query: "", team: "All", tier: "All", radar: "All", adjustedOnly: false, limit: 100, sort: "rank", direction: 1, preset: "draft", layout: "auto" };

function loadBoardPreferences() {
  const saved = readStored(PREFERENCES_KEY, {});
  if (!saved || typeof saved !== "object" || Array.isArray(saved)) return;
  for (const key of ["query", "team", "tier"]) {
    if (typeof saved[key] === "string") state[key] = saved[key];
  }
  if (Object.hasOwn(COLUMN_PRESETS, saved.preset)) state.preset = saved.preset;
  if (["auto", "table", "cards"].includes(saved.layout)) state.layout = saved.layout;
  if (["All", "Targets", "Fades", "Watchlist"].includes(saved.radar)) state.radar = saved.radar;
  if ([50, 100, 200, 9999].includes(saved.limit)) state.limit = saved.limit;
  if (typeof saved.adjustedOnly === "boolean") state.adjustedOnly = saved.adjustedOnly;
  if (typeof saved.sort === "string" && BOARD_COLUMNS.some(column => column.sort === saved.sort)) state.sort = saved.sort;
  if (saved.direction === 1 || saved.direction === -1) state.direction = saved.direction;
}

function syncBoardControls() {
  for (const [id, key] of [["search", "query"], ["team-filter", "team"], ["tier-filter", "tier"], ["radar-filter", "radar"], ["limit", "limit"], ["column-preset", "preset"], ["board-layout", "layout"], ["board-sort", "sort"]]) {
    $("#" + id).value = state[key];
  }
  $("#adjusted-only").checked = state.adjustedOnly;
  $("#sort-direction").textContent = state.direction === 1 ? "Ascending ↑" : "Descending ↓";
}

function resetBoardFilters() {
  for (const key of ["query", "team", "tier", "radar", "adjustedOnly", "limit", "sort", "direction"]) state[key] = BOARD_DEFAULTS[key];
  drawBoard();
}

function selectBoardSort(sort) {
  state.sort = sort;
  state.direction = ["rank", "PLAYER_NAME", "TEAM_ABBREVIATION", "positions", "tier", "target_age", "adp", "risk"].includes(sort) ? 1 : -1;
}

function filteredRows() {
  const query = state.query.trim().toLowerCase();
  const filtered = state.rows.filter(row => {
    if (query && !`${row.PLAYER_NAME} ${row.TEAM_ABBREVIATION || ""} ${row.positions || ""}`.toLowerCase().includes(query)) return false;
    if (state.team !== "All" && row.TEAM_ABBREVIATION !== state.team) return false;
    if (state.tier !== "All" && String(row.tier) !== state.tier) return false;
    if (!radarMatches(row, state.radar)) return false;
    return !state.adjustedOnly || isAdjusted(row);
  });
  const direction = state.direction;
  filtered.sort((a, b) => {
    const av = a[state.sort];
    const bv = b[state.sort];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return (typeof av === "string" ? av.localeCompare(bv) : av - bv) * direction;
  });
  return filtered;
}

function drawSummary() {
  const rows = state.rows;
  const top100 = rows.slice(0, 100);
  const adjusted = rows.filter(isAdjusted).length;
  const avg = top100.reduce((sum, row) => sum + row.fpts_pg, 0) / Math.max(1, top100.length);
  const withAdp = rows.filter(row => row.adp != null).length;
  $("#summary-cards").innerHTML = [
    ["No. 1 projection", `${fmt(rows[0]?.fpts_pg)} FP/G`, rows[0]?.PLAYER_NAME || "—"],
    ["Top-100 average", `${fmt(avg)} FP/G`, "Board B projection"],
    ["Analyst adjusted", integer(adjusted), `${rows.length} players published`],
    ["Market coverage", integer(withAdp), "Players with ADP"],
  ].map(([label, value, note]) => `<article class="summary-card"><small>${label}</small><strong>${esc(value)}</strong><em>${esc(note)}</em></article>`).join("");
}

function drawBoard() {
  if (!state.rows.length) return;
  if (state.meta && !applyingRoute && state.view === "board") writeRoute(document.activeElement?.id === "search");
  const focused = document.activeElement;
  const hadBoardFocus = Boolean(focused?.closest("#rows, #board-cards"));
  const focusAttribute = ["data-compare", "data-player", "data-target-player"].find(attribute => focused?.hasAttribute(attribute));
  const focusValue = focusAttribute && focused.getAttribute(focusAttribute);
  const expanded = new Set($$("#board-cards details[open]").map(detail => detail.closest("[data-card]").dataset.card));
  const all = filteredRows();
  const rows = all.slice(0, state.limit);
  const columns = COLUMN_PRESETS[state.preset].map(key => BOARD_COLUMNS.find(column => column.key === key));
  $("#board-head").innerHTML = `<tr>${columns.map(column => {
    const active = column.sort === state.sort;
    const label = column.key === "compare" ? `<span class="sr-only">Compare</span>` : esc(column.label);
    return `<th scope="col" class="${column.className || "tnum"}"${active ? ` aria-sort="${state.direction === 1 ? "ascending" : "descending"}"` : ""}>${column.sort ? `<button data-sort="${column.sort}">${label}${active ? (state.direction === 1 ? " ↑" : " ↓") : ""}</button>` : label}</th>`;
  }).join("")}</tr>`;
  $("#rows").innerHTML = rows.map(row => `<tr>${columns.map(column => `<td class="${column.className || "tnum"}">${column.render(row)}</td>`).join("")}</tr>`).join("");
  const detailColumns = BOARD_COLUMNS.filter(column => !["compare", "rank", "player", "positions", "team", "fpg", "adp", "radar"].includes(column.key));
  $("#board-cards").innerHTML = rows.map(row => `<article class="player-card panel" data-card="${row.PLAYER_ID}">
    <header><span class="rank">#${row.rank}</span><div class="card-player">${playerMarkup(row)}<span class="card-position">${esc((row.positions || "Position unavailable").replaceAll("|", "/"))}</span></div><label class="card-compare">${compareMarkup(row)}<span>Compare</span></label></header>
    <div class="card-metrics"><div><small>FP/G</small><strong class="fpg tnum">${fmt(row.fpts_pg)}</strong></div><div><small>ADP</small><strong class="tnum">${integer(row.adp)}</strong></div><div class="card-radar">${radarMarkup(row) || '<span class="muted">No Radar signal</span>'}</div></div>
    <details${expanded.has(String(row.PLAYER_ID)) ? " open" : ""}><summary>Projection details</summary><dl>${detailColumns.map(column => `<div><dt>${esc(column.label)}</dt><dd>${column.render(row) || "—"}</dd></div>`).join("")}</dl></details>
  </article>`).join("");
  $("#view-board").dataset.layout = state.layout;
  $("#board-empty").hidden = all.length > 0;
  $("#board-table-wrap").classList.toggle("no-results", all.length === 0);
  const sortLabel = BOARD_COLUMNS.find(column => column.sort === state.sort)?.label || "FP/G rank";
  $("#status").textContent = `${rows.length} of ${all.length} matching players · sorted by ${sortLabel} ${state.direction === 1 ? "ascending" : "descending"}`;
  syncBoardControls();
  writeStored(PREFERENCES_KEY, Object.fromEntries(Object.keys(BOARD_DEFAULTS).map(key => [key, state[key]])));
  if (focusAttribute && hadBoardFocus) {
    const next = $$(`[${focusAttribute}]`, $("#view-board")).find(element => element.getAttribute(focusAttribute) === focusValue && element.getClientRects().length);
    next?.focus({ preventScroll: true });
  }
}

function drawTiers() {
  const groups = new Map();
  state.rows.forEach(row => {
    const tier = row.tier == null ? "Unseeded" : row.tier;
    if (!groups.has(tier)) groups.set(tier, []);
    groups.get(tier).push(row);
  });
  $("#tier-grid").innerHTML = [...groups].map(([tier, rows]) => `<article class="tier-section panel">
    <header class="tier-head"><h2>${tier === "Unseeded" ? tier : `Tier ${tier}`}</h2><span>${rows.length} players · ${fmt(rows[0]?.fpts_pg)} to ${fmt(rows.at(-1)?.fpts_pg)} FP/G</span></header>
    <div class="tier-players">${rows.map(row => `<div class="tier-player" data-player="${row.PLAYER_ID}"><span class="rank">#${row.rank}</span><strong>${esc(row.PLAYER_NAME)}<small>${esc(row.TEAM_ABBREVIATION || "—")} · ${integer(row.gp)} GP</small></strong><b>${fmt(row.fpts_pg)}</b></div>`).join("")}</div>
  </article>`).join("");
}

function drawTeams() {
  const groups = new Map();
  state.rows.filter(row => row.TEAM_ABBREVIATION).forEach(row => {
    if (!groups.has(row.TEAM_ABBREVIATION)) groups.set(row.TEAM_ABBREVIATION, []);
    groups.get(row.TEAM_ABBREVIATION).push(row);
  });
  const teams = [...groups].map(([team, rows]) => {
    const top = rows.slice(0, 5);
    return { team, rows, top, avg: top.reduce((sum, row) => sum + row.fpts_pg, 0) / top.length };
  }).sort((a, b) => b.avg - a.avg);
  $("#team-grid").innerHTML = teams.map(({ team, rows, top, avg }) => `<article class="team-card panel" data-team="${team}">
    <header class="team-head"><h2>${team}</h2><span>${fmt(avg)}</span></header>
    <div class="team-meta"><div><small>Top-5 avg</small><strong>${fmt(avg)} FP/G</strong></div><div><small>Best rank</small><strong>#${top[0].rank}</strong></div><div><small>Players</small><strong>${rows.length}</strong></div></div>
    <div class="team-list">${top.map(row => `<div><span>#${row.rank} ${esc(row.PLAYER_NAME)}</span><b>${fmt(row.fpts_pg)}</b></div>`).join("")}</div>
  </article>`).join("");
}

function drawCompare() {
  if (!state.rows.length) return;
  const players = [...state.compare].map(id => state.rows.find(row => row.PLAYER_ID === id)).filter(Boolean);
  const unknown = [...state.compare].filter(id => !players.some(row => row.PLAYER_ID === id));
  const missing = unknown.length ? `<p class="status">IDs absent from this board: ${unknown.map(id => `${id} <button class="link-button" data-remove="${id}">Remove</button>`).join(" · ")}</p>` : "";
  if (!players.length) {
    $("#compare-view").innerHTML = `${missing}<div class="empty">Select two to four players from the Draft Board or a player detail card.<br><button class="link-button" data-go="board">Open draft board</button></div>`;
    return;
  }
  const metrics = [
    ["FP/G rank", "rank", value => `#${integer(value)}`, "min"],
    ["FP / game", "fpts_pg", fmt, "max"], ["2025-26 FP/G", "previous_fpts_pg", fmt, "max"],
    ["Projected change", "fpts_pg_change", signed, "max"], ["VOR", "vor", fmt, "max"],
    ["Median total", "fpts_median", integer, "max"], ["Floor (p10)", "fpts_p10", integer, "max"],
    ["Ceiling (p90)", "fpts_p90", integer, "max"], ["Risk", "risk", value => fmt(value, 2), "min"],
    ["Projected GP", "gp", integer, "max"], ["Projected MPG", "mpg", fmt, "max"],
    ["Age", "target_age", integer, null], ["ADP", "adp", integer, "min"],
    ["PTS", "pts", fmt, "max"], ["REB", "reb", fmt, "max"], ["AST", "ast", fmt, "max"],
    ["STL", "stl", fmt, "max"], ["BLK", "blk", fmt, "max"], ["3PM", "fg3m", fmt, "max"], ["TOV", "tov", fmt, "min"],
  ];
  const rows = metrics.map(([label, key, render, bestDirection]) => {
    const values = players.map(player => player[key]).filter(value => value != null);
    const best = !bestDirection || !values.length ? null : (bestDirection === "max" ? Math.max(...values) : Math.min(...values));
    return `<tr><td>${label}</td>${players.map(player => `<td class="tnum ${best != null && player[key] === best ? "best" : ""}">${render(player[key])}</td>`).join("")}</tr>`;
  }).join("");
  $("#compare-view").innerHTML = `${missing}<div class="compare-actions"><p>${players.length} of 4 comparison slots used</p><button class="link-button" id="clear-compare">Clear all</button></div><div class="compare-shell panel"><table class="compare-table"><thead><tr><th>Metric</th>${players.map(player => `<th><button class="player-button compare-name" data-player="${player.PLAYER_ID}">${esc(player.PLAYER_NAME)}</button><br><span class="muted">${esc(player.TEAM_ABBREVIATION || "—")} · Tier ${player.tier ?? "—"}</span></th>`).join("")}</tr></thead><tbody>${rows}<tr><td>Analyst</td>${players.map(player => `<td>${analystChip(player) || "—"}</td>`).join("")}</tr><tr><td>Remove</td>${players.map(player => `<td><button class="link-button" data-remove="${player.PLAYER_ID}">Remove</button></td>`).join("")}</tr></tbody></table></div>`;
}

function openPlayer(id, navigate = true) {
  state.playerId = Number(id);
  if (navigate) writeRoute();
  const row = state.rows.find(player => player.PLAYER_ID === Number(id));
  if (!row) {
    $("#player-detail").innerHTML = `<div class="target-form"><h2>Player unavailable</h2><p>Player ID ${esc(id)} is absent from this published board. Close this card to browse available players.</p></div>`;
    if (!$("#player-dialog").open) $("#player-dialog").showModal();
    return;
  }
  const valueGap = row.adp == null ? null : row.adp - row.rank;
  const valueText = valueGap == null ? "No ADP available" : valueGap >= 12 ? `Market discount: ${integer(valueGap)} picks` : valueGap <= -12 ? `Market is ${integer(-valueGap)} picks higher` : "Close to market price";
  $("#player-detail").innerHTML = `<header class="player-hero"><p class="eyebrow">${esc(row.TEAM_ABBREVIATION || "FREE AGENT")} · TIER ${row.tier ?? "—"}</p><h2>${esc(row.PLAYER_NAME)}</h2><p>FP/G rank #${row.rank} · safe source rank #${row.source_rank ?? "—"} · model source rank #${row.model_source_rank ?? "—"}</p></header>
    <div class="detail-body">
      <div class="detail-stats"><div class="detail-stat"><small>FP / game</small><strong>${fmt(row.fpts_pg)}</strong></div><div class="detail-stat"><small>2025-26 FP/G</small><strong>${fmt(row.previous_fpts_pg)}</strong></div><div class="detail-stat"><small>Projected change</small><strong>${changeMarkup(row.fpts_pg_change)}</strong></div><div class="detail-stat"><small>VOR</small><strong>${fmt(row.vor)}</strong></div><div class="detail-stat"><small>Projected GP</small><strong>${integer(row.gp)}</strong></div><div class="detail-stat"><small>Projected MPG</small><strong>${fmt(row.mpg)}</strong></div><div class="detail-stat"><small>Age</small><strong>${integer(row.target_age)}</strong></div><div class="detail-stat"><small>ADP</small><strong>${integer(row.adp)}</strong></div><div class="detail-stat"><small>Risk</small><strong>${fmt(row.risk, 2)}</strong></div><div class="detail-stat"><small>Market read</small><strong>${esc(valueText)}</strong></div></div>
      <section class="detail-section"><h3>Projected per-game line</h3><div class="projection-line">${[["PTS",row.pts],["REB",row.reb],["AST",row.ast],["STL",row.stl],["BLK",row.blk],["3PM",row.fg3m],["TOV",row.tov]].map(([label,value]) => `<div><small>${label}</small><strong>${fmt(value)}</strong></div>`).join("")}</div></section>
      <section class="detail-section"><h3>Simulated season totals</h3><div class="season-band"><div><small>Floor · p10</small><strong>${integer(row.fpts_p10)}</strong></div><div><small>Median</small><strong>${integer(row.fpts_median)}</strong></div><div><small>Ceiling · p90</small><strong>${integer(row.fpts_p90)}</strong></div></div></section>
      ${(row.radar_label || isTarget(row)) ? `<section class="detail-section"><h3>Draft radar</h3><div class="analyst-note">${radarMarkup(row, null, false)} &nbsp; ${esc(row.radar_reasons || "Personal priority target")}</div></section>` : ""}
      ${isTarget(row) ? `<section class="detail-section"><h3>Your draft note</h3><div class="analyst-note">${state.targets[String(row.PLAYER_ID)].takeBy ? `Take by pick ${esc(state.targets[String(row.PLAYER_ID)].takeBy)}. ` : ""}${esc(state.targets[String(row.PLAYER_ID)].note || "No note yet.")}</div></section>` : ""}
      ${isAdjusted(row) ? `<section class="detail-section"><h3>Analyst layer</h3><div class="analyst-note">${analystChip(row)} &nbsp; ${esc(row.analyst_category || "")} · ${esc(row.analyst_date || "")}. Detailed rationale remains in the private review workflow.</div></section>` : ""}
      <div class="detail-actions"><button class="button" data-target-player="${row.PLAYER_ID}">${isTarget(row) ? "Edit priority target" : "Add priority target"}</button><button class="button" data-modal-compare="${row.PLAYER_ID}">${state.compare.has(row.PLAYER_ID) ? "Remove from compare" : "Add to compare"}</button><button class="button" data-copy-link>Copy link</button><span class="copy-status" role="status"></span><input class="copy-fallback" aria-label="Link to copy" readonly hidden /></div>
    </div>`;
  const dialog = $("#player-dialog");
  if (!dialog.open) { if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", ""); }
}

function setView(view, navigate = true) {
  if (!Object.hasOwn(viewCopy, view)) view = "board";
  state.view = view;
  $$(".view").forEach(section => section.hidden = section.id !== `view-${view}`);
  $$(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  [$("#view-title").textContent, $("#view-subtitle").textContent] = viewCopy[view];
  $(".sidebar").classList.remove("open");
  if (navigate) { state.playerId = null; $("#player-dialog").close(); writeRoute(); }
  if (view === "compare") drawCompare();
  if (view === "plan") drawPlan();
  if (view === "practice") drawPractice();
}

function populateFilters() {
  const teams = [...new Set(state.rows.map(row => row.TEAM_ABBREVIATION).filter(Boolean))].sort();
  $("#team-filter").insertAdjacentHTML("beforeend", teams.map(team => `<option value="${team}">${team}</option>`).join(""));
  const tiers = [...new Set(state.rows.map(row => row.tier).filter(tier => tier != null))].sort((a, b) => a - b);
  $("#tier-filter").insertAdjacentHTML("beforeend", tiers.map(tier => `<option value="${tier}">Tier ${tier}</option>`).join(""));
  if (state.team !== "All" && !teams.includes(state.team)) state.team = "All";
  if (state.tier !== "All" && !tiers.some(tier => String(tier) === state.tier)) state.tier = "All";
  $("#board-sort").innerHTML = BOARD_COLUMNS.filter(column => column.sort).map(column => `<option value="${column.sort}">${esc(column.label)}</option>`).join("");
}

let applyingRoute = false;
let routeFallback = {};
let lastRouteHash = "";
let importPreview = null;

function routeHash(shared = false) {
  const params = new URLSearchParams(Object.keys(BOARD_DEFAULTS).map(key => [key, String(shared && key === "radar" && state.radar === "Watchlist" ? "All" : state[key])]));
  if (state.view === "compare") params.set("ids", [...state.compare].join(","));
  if (state.playerId !== null) params.set("player", state.playerId);
  return `#${state.view}?${params}`;
}

function writeRoute(replace = false) {
  if (applyingRoute) return;
  const hash = routeHash();
  if (location.hash !== hash) history[replace ? "replaceState" : "pushState"](null, "", hash);
  lastRouteHash = location.hash;
}

function applyRoute(force = false) {
  if (!state.rows.length || (!force && location.hash === lastRouteHash)) return;
  applyingRoute = true;
  const [view, search = ""] = location.hash.slice(1).split("?");
  const params = new URLSearchParams(search);
  const invalid = [];
  Object.assign(state, routeFallback);
  for (const key of Object.keys(BOARD_DEFAULTS)) {
    const raw = params.get(key); if (raw === null) continue;
    let value = raw;
    let valid = raw.length <= 500;
    if (key === "preset") valid &&= Object.hasOwn(COLUMN_PRESETS, raw);
    if (key === "layout") valid &&= ["auto", "table", "cards"].includes(raw);
    if (key === "radar") valid &&= ["All", "Targets", "Fades", "Watchlist"].includes(raw);
    if (key === "limit") { value = Number(raw); valid &&= [50, 100, 200, 9999].includes(value); }
    if (key === "direction") { value = Number(raw); valid &&= [1, -1].includes(value); }
    if (key === "adjustedOnly") { value = raw === "true"; valid &&= ["true", "false"].includes(raw); }
    if (key === "sort") valid &&= BOARD_COLUMNS.some(column => column.sort === raw);
    if (key === "team") valid &&= raw === "All" || state.rows.some(row => row.TEAM_ABBREVIATION === raw);
    if (key === "tier") valid &&= raw === "All" || state.rows.some(row => String(row.tier) === raw);
    if (valid) state[key] = value; else invalid.push(key);
  }
  if (params.has("ids")) {
    try { state.compare = new Set(parseIds(params.get("ids"))); }
    catch (error) { state.compare.clear(); invalid.push(error.message); }
  }
  state.playerId = null;
  setView(view || "board", false);
  if (view && !Object.hasOwn(viewCopy, view)) invalid.push("page");
  const player = params.get("player");
  if (player !== null && /^[1-9]\d*$/.test(player) && Number.isSafeInteger(Number(player))) openPlayer(player, false);
  else { if (player !== null) invalid.push("player ID"); $("#player-dialog").close(); }
  $("#route-note").textContent = invalid.length ? `Ignored invalid link settings: ${invalid.join(", ")}. Browse the board or choose players again.` : "";
  $("#route-note").hidden = !invalid.length;
  saveCompare(); drawBoard(); drawCompare();
  applyingRoute = false;
  lastRouteHash = location.hash;
  if (!search && !invalid.length) writeRoute(true);
}

async function copyCurrentLink(button) {
  const url = `${location.origin}${location.pathname}${routeHash(true)}`;
  const modal = button.closest("#player-dialog");
  const note = modal ? $(".copy-status", modal) : $("#route-note");
  note.hidden = false;
  try {
    await navigator.clipboard.writeText(url);
    note.textContent = state.radar === "Watchlist" ? "Link copied. Shared boards show all players; export your watchlist to transfer targets." : "Link copied";
  } catch {
    note.textContent = "Select and copy the link below.";
    const input = modal ? $(".copy-fallback", modal) : $("#copy-url");
    if (!modal) $("#copy-fallback").hidden = false;
    input.hidden = false; input.value = url; input.focus(); input.select();
  }
}

function bindEvents() {
  $("#export-watchlist").addEventListener("click", () => {
    try { downloadBackup(state.targets, state.season); $("#backup-status").textContent = "Backup downloaded, including your private notes."; }
    catch (error) { $("#backup-status").textContent = error.message; }
  });
  $("#import-watchlist").addEventListener("click", () => $("#watchlist-file").click());
  $("#watchlist-file").addEventListener("change", async event => {
    const file = event.target.files[0]; event.target.value = ""; if (!file) return;
    importPreview = null;
    try {
      if (file.size > MAX_FILE_BYTES) throw new Error("Choose a backup smaller than 1 MB.");
      importPreview = validateBackup(JSON.parse(await file.text()), state.season);
      const unknown = Object.keys(importPreview).filter(id => !state.rows.some(row => row.PLAYER_ID === Number(id)));
      $("#import-preview").textContent = `${Object.keys(importPreview).length} targets for ${state.season}. Import includes private notes.`;
      $("#import-unknown").textContent = unknown.length ? `Unknown player IDs (kept for future boards): ${unknown.join(", ")}` : "All player IDs are on the current board.";
      $('[name="import-mode"][value="merge"]').checked = true;
      $("#backup-status").textContent = ""; $("#import-dialog").showModal();
    } catch (error) { $("#backup-status").textContent = error.message; }
  });
  $("#cancel-import").addEventListener("click", () => $("#import-dialog").close());
  $("#confirm-import").addEventListener("click", () => {
    if (!importPreview) return;
    state.targets = $('[name="import-mode"]:checked').value === "merge" ? { ...state.targets, ...importPreview } : importPreview;
    saveTargets(); drawBoard(); drawMock(); $("#import-dialog").close(); $("#backup-status").textContent = "Watchlist imported.";
  });
  $("#search").addEventListener("input", event => { state.query = event.target.value; drawBoard(); });
  $("#team-filter").addEventListener("change", event => { state.team = event.target.value; drawBoard(); });
  $("#tier-filter").addEventListener("change", event => { state.tier = event.target.value; drawBoard(); });
  $("#radar-filter").addEventListener("change", event => { state.radar = event.target.value; drawBoard(); });
  $("#limit").addEventListener("change", event => { state.limit = Number(event.target.value); drawBoard(); });
  $("#adjusted-only").addEventListener("change", event => { state.adjustedOnly = event.target.checked; drawBoard(); });
  $("#column-preset").addEventListener("change", event => { state.preset = event.target.value; drawBoard(); });
  $("#board-layout").addEventListener("change", event => { state.layout = event.target.value; drawBoard(); });
  $("#board-sort").addEventListener("change", event => { selectBoardSort(event.target.value); drawBoard(); });
  $("#sort-direction").addEventListener("click", () => { state.direction *= -1; drawBoard(); });
  $("#reset-filters").addEventListener("click", resetBoardFilters);
  $("#mock-search").addEventListener("input", event => { state.mock.query = event.target.value; drawMock(); });
  $("#mock-radar").addEventListener("change", event => { state.mock.radar = event.target.value; drawMock(); });
  $("#mock-limit").addEventListener("change", event => { state.mock.limit = Number(event.target.value); drawMock(); });
  $("#mock-my-team").addEventListener("change", event => { state.mock.myTeam = Number(event.target.value); saveMock(); drawMock(); });
  $("#plan-team").addEventListener("change", event => { state.mock.myTeam = Number(event.target.value); saveMock(); drawMock(); });
  $("#practice-teams").addEventListener("change", event => {
    const teams = Number(event.target.value);
    $("#practice-position").innerHTML = Array.from({ length: teams }, (_, index) => `<option value="${index + 1}">${index + 1}</option>`).join("");
  });
  $("#practice-form").addEventListener("submit", event => {
    event.preventDefault();
    try {
      if (state.practice.runs.length >= MAX_RUNS) throw new Error(`Save at most ${MAX_RUNS} runs. Export and delete one to continue.`);
      const run = createPracticeRun({ name: $("#practice-name").value, teams: Number($("#practice-teams").value), position: Number($("#practice-position").value), rule: $("#practice-rule").value, roster: mockConfig().roster, season: state.season, source: "public", ranking: "FP/G ordinal", marketDate: state.meta.market_date, boardDate: state.meta.generated_at, rows: state.rows });
      state.practice.selected = run.id;
      state.practice.query = "";
      savePractice([run, ...state.practice.runs]);
    } catch (error) { $("#practice-message").textContent = error.message; }
  });
  $("#practice-import").addEventListener("change", async event => {
    const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error("Practice files must be smaller than 2 MB.");
      const run = validatePracticeRun(JSON.parse(await file.text()));
      const existing = state.practice.runs.find(item => item.id === run.id);
      if (!existing && state.practice.runs.length >= MAX_RUNS) throw new Error("Delete a saved run before importing another.");
      state.practice.selected = run.id;
      savePractice(existing ? state.practice.runs.map(item => item.id === run.id ? run : item) : [run, ...state.practice.runs]);
    } catch (error) { $("#practice-message").textContent = error.message; }
  });
  $("#view-practice").addEventListener("input", event => {
    if (event.target.id === "practice-search") {
      state.practice.query = event.target.value;
      const start = event.target.selectionStart;
      drawPractice();
      $("#practice-search").focus();
      $("#practice-search").setSelectionRange(start, start);
    }
  });
  $("#mock-undo").addEventListener("click", () => { state.mock.picks.pop(); saveMock(); drawMock(); });
  $("#mock-reset").addEventListener("click", () => {
    if (state.mock.picks.length && confirm("Clear every pick in this browser mock draft?")) {
      state.mock.picks = []; saveMock(); drawMock();
    }
  });
  document.addEventListener("click", event => {
    const practicePick = event.target.closest("[data-practice-pick]");
    if (practicePick) {
      const run = state.practice.runs.find(item => item.id === state.practice.selected) || state.practice.runs[0];
      try { savePractice(state.practice.runs.map(item => item.id === run.id ? choosePracticePlayer(run, Number(practicePick.dataset.practicePick)) : item)); }
      catch (error) { $("#practice-message").textContent = error.message; }
    }
    if (event.target.closest("[data-practice-undo]")) {
      const run = state.practice.runs.find(item => item.id === state.practice.selected) || state.practice.runs[0];
      savePractice(state.practice.runs.map(item => item.id === run.id ? undoPracticePick(run) : item));
    }
    const practiceOpen = event.target.closest("[data-practice-open]");
    if (practiceOpen) { state.practice.selected = practiceOpen.dataset.practiceOpen; state.practice.query = ""; drawPractice(); }
    const practiceDelete = event.target.closest("[data-practice-delete]");
    if (practiceDelete && confirm("Delete this browser-local practice run?")) {
      state.practice.runs = state.practice.runs.filter(item => item.id !== practiceDelete.dataset.practiceDelete);
      if (state.practice.selected === practiceDelete.dataset.practiceDelete) state.practice.selected = null;
      savePractice(state.practice.runs);
    }
    const practiceExport = event.target.closest("[data-practice-export]");
    if (practiceExport) { const run = state.practice.runs.find(item => item.id === practiceExport.dataset.practiceExport); if (run) exportPractice(run); }
    const copy = event.target.closest("[data-copy-link]"); if (copy) copyCurrentLink(copy);
    const sort = event.target.closest("[data-sort]");
    if (sort) {
      if (state.sort === sort.dataset.sort) state.direction *= -1;
      else selectBoardSort(sort.dataset.sort);
      drawBoard();
      $$('[data-sort]', $("#board-head")).find(button => button.dataset.sort === state.sort)?.focus({ preventScroll: true });
    }
    if (event.target.closest("[data-reset-filters]")) resetBoardFilters();
    const view = event.target.closest("[data-view], [data-go]");
    if (view) setView(view.dataset.view || view.dataset.go);
    const player = event.target.closest("[data-player]");
    if (player) openPlayer(player.dataset.player);
    const compare = event.target.closest("[data-compare]");
    if (compare) toggleCompare(Number(compare.dataset.compare));
    const remove = event.target.closest("[data-remove]");
    if (remove) toggleCompare(Number(remove.dataset.remove));
    const modalCompare = event.target.closest("[data-modal-compare]");
    if (modalCompare) { toggleCompare(Number(modalCompare.dataset.modalCompare)); $("#player-dialog").close(); }
    const draft = event.target.closest("[data-draft-player]");
    if (draft) draftPlayer(Number(draft.dataset.draftPlayer));
    const target = event.target.closest("[data-target-player]");
    if (target) {
      const row = state.rows.find(r => r.PLAYER_ID === Number(target.dataset.targetPlayer));
      if (row) { if ($("#player-dialog").open) $("#player-dialog").close(); openTarget(row); }
    }
    const planRemove = event.target.closest("[data-plan-remove]");
    if (planRemove) { delete state.targets[planRemove.dataset.planRemove]; saveTargets(); drawBoard(); drawMock(); }
    const team = event.target.closest("[data-team]");
    if (team) { state.team = team.dataset.team; $("#team-filter").value = state.team; setView("board"); drawBoard(); }
    if (event.target.id === "clear-compare") { state.compare.clear(); saveCompare(); drawBoard(); drawCompare(); writeRoute(); }
  });
  $("#mobile-nav").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  $(".dialog-close").addEventListener("click", () => $("#player-dialog").close());
  $("#player-dialog").addEventListener("click", event => { if (event.target === $("#player-dialog")) $("#player-dialog").close(); });
  $("#player-dialog").addEventListener("close", () => {
    if (!$("#player-dialog").open && state.playerId !== null) { state.playerId = null; writeRoute(); }
  });
  $(".target-dialog-close").addEventListener("click", () => $("#target-dialog").close());
  $("#target-dialog").addEventListener("click", event => { if (event.target === $("#target-dialog")) $("#target-dialog").close(); });
  $("#target-form").addEventListener("submit", event => {
    event.preventDefault();
    const id = String($("#target-player-id").value);
    const takeBy = $("#target-take-by").value ? Number($("#target-take-by").value) : null;
    try {
      state.targets[id] = normalizeTarget({ takeBy, note: $("#target-note").value.trim(),
        preferredRound: $("#target-round").value ? Number($("#target-round").value) : null,
        backupGroup: $("#target-group").value.trim(),
        priority: $("#target-priority").value ? Number($("#target-priority").value) : null,
        status: $("#target-status").value });
      saveTargets(); $("#target-dialog").close(); drawBoard(); drawMock(); drawPlan();
    } catch (error) { $("#target-error").textContent = error.message; }
  });
  $("#target-remove").addEventListener("click", () => {
    delete state.targets[String($("#target-player-id").value)];
    saveTargets(); $("#target-dialog").close(); drawBoard(); drawMock(); drawPlan();
  });
  window.addEventListener("hashchange", () => applyRoute());
  window.addEventListener("popstate", () => applyRoute());
}

loadTargets();
loadMock();
loadPractice();
loadBoardPreferences();
routeFallback = Object.fromEntries(Object.keys(BOARD_DEFAULTS).map(key => [key, state[key]]));
bindEvents();
saveCompare();
saveMock();
fetch("data/board.json", { cache: "no-store" })
  .then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
  .then(data => {
    state.meta = data;
    state.season = data.season || data.title?.match(/\b\d{4}-\d{2}\b/)?.[0] || "";
    applyingRoute = true;
    state.rows = [...data.rows].sort((a, b) => a.rank - b.rank);
    const knownIds = new Set(state.rows.map(row => row.PLAYER_ID));
    state.mock.picks = state.mock.picks.filter(pick => knownIds.has(pick.playerId) && pick.team >= 1 && pick.team <= mockConfig().teams);
    $("#loading").hidden = true;
    const stamp = new Date(data.generated_at);
    $("#sidebar-stamp").textContent = Number.isNaN(stamp.valueOf()) ? "Board B" : stamp.toLocaleString();
    const teamOptions = Array.from({ length: mockConfig().teams }, (_, index) => `<option value="${index + 1}">Team ${index + 1}</option>`).join("");
    $("#mock-team").innerHTML = teamOptions;
    $("#mock-my-team").innerHTML = teamOptions;
    $("#plan-team").innerHTML = teamOptions;
    $("#practice-teams").innerHTML = [...new Set([8, 10, 12, 14, mockConfig().teams])].sort((a, b) => a - b).map(count => `<option value="${count}">${count}</option>`).join("");
    $("#practice-teams").value = String(mockConfig().teams);
    $("#practice-position").innerHTML = Array.from({ length: mockConfig().teams }, (_, index) => `<option value="${index + 1}">${index + 1}</option>`).join("");
    populateFilters();
    routeFallback = Object.fromEntries(Object.keys(BOARD_DEFAULTS).map(key => [key, state[key]]));
    drawSummary(); drawBoard(); drawMock(); drawTiers(); drawTeams(); drawCompare(); drawPlan(); drawPractice(); saveCompare(); saveMock();
    applyingRoute = false;
    applyRoute(true);
  })
  .catch(error => {
    $("#loading").hidden = true;
    $("#error").hidden = false;
    $("#error").textContent = `The published board could not be loaded (${error.message}). Run scripts/export_static.py and commit static/data/board.json.`;
  });
