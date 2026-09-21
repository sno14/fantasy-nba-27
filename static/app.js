const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const fmt = (value, digits = 1) => value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(digits);
const integer = (value) => fmt(value, 0);
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);

const state = {
  rows: [], meta: null, view: "board", query: "", team: "All", tier: "All",
  adjustedOnly: false, limit: 100, sort: "rank", direction: 1,
  compare: new Set(JSON.parse(localStorage.getItem("fantasy-nba-compare") || "[]")),
};

const viewCopy = {
  board: ["Draft Board", "Projected fantasy points per game with analyst layer applied."],
  tiers: ["Projection Tiers", "Value bands from unusually large adjacent FP/G gaps."],
  teams: ["Team Overview", "Projected leaders and top-five strength for every NBA team."],
  compare: ["Player Compare", "Put up to four projections side by side."],
  method: ["Methodology", "What this public snapshot includes—and what remains local."],
};

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

function saveCompare() {
  localStorage.setItem("fantasy-nba-compare", JSON.stringify([...state.compare]));
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
}

function filteredRows() {
  const query = state.query.trim().toLowerCase();
  const filtered = state.rows.filter(row => {
    if (query && !`${row.PLAYER_NAME} ${row.TEAM_ABBREVIATION || ""}`.toLowerCase().includes(query)) return false;
    if (state.team !== "All" && row.TEAM_ABBREVIATION !== state.team) return false;
    if (state.tier !== "All" && String(row.tier) !== state.tier) return false;
    return !state.adjustedOnly || isAdjusted(row);
  });
  const direction = state.direction;
  filtered.sort((a, b) => {
    const av = a[state.sort];
    const bv = b[state.sort];
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
  const all = filteredRows();
  const rows = all.slice(0, state.limit);
  $("#rows").innerHTML = rows.map(row => `<tr>
    <td class="compare-cell"><input class="row-check" type="checkbox" data-compare="${row.PLAYER_ID}" ${state.compare.has(row.PLAYER_ID) ? "checked" : ""} aria-label="Compare ${esc(row.PLAYER_NAME)}"></td>
    <td class="rank tnum">${row.rank}</td>
    <td class="player-col"><button class="player-button" data-player="${row.PLAYER_ID}">${esc(row.PLAYER_NAME)}</button></td>
    <td class="muted">${esc(row.TEAM_ABBREVIATION || "—")}</td>
    <td class="optional tnum">${row.tier == null ? "—" : row.tier}</td>
    <td class="optional tnum">${integer(row.target_age)}</td>
    <td class="fpg tnum">${fmt(row.fpts_pg)}</td>
    <td class="optional tnum">${fmt(row.vor)}</td>
    <td class="optional tnum">${integer(row.adp)}</td>
    <td class="optional tnum">${fmt(row.mpg)}</td>
    <td class="tnum">${integer(row.gp)}</td>
    <td class="range-col">${rangeMarkup(row)}</td>
    <td class="optional tnum">${riskMarkup(row.risk)}</td>
    <td>${analystChip(row)}</td>
  </tr>`).join("");
  $("#status").textContent = `${rows.length} of ${all.length} matching players · sorted by ${state.sort === "rank" ? "FP/G rank" : state.sort}${state.direction < 0 ? " descending" : " ascending"}`;
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
  if (!players.length) {
    $("#compare-view").innerHTML = `<div class="empty">Select two to four players from the Draft Board or a player detail card.<br><button class="link-button" data-go="board">Open draft board</button></div>`;
    return;
  }
  const metrics = [
    ["FP/G rank", "rank", value => `#${integer(value)}`, "min"],
    ["FP / game", "fpts_pg", fmt, "max"], ["VOR", "vor", fmt, "max"],
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
  $("#compare-view").innerHTML = `<div class="compare-actions"><p>${players.length} of 4 comparison slots used</p><button class="link-button" id="clear-compare">Clear all</button></div><div class="compare-shell panel"><table class="compare-table"><thead><tr><th>Metric</th>${players.map(player => `<th><button class="player-button compare-name" data-player="${player.PLAYER_ID}">${esc(player.PLAYER_NAME)}</button><br><span class="muted">${esc(player.TEAM_ABBREVIATION || "—")} · Tier ${player.tier ?? "—"}</span></th>`).join("")}</tr></thead><tbody>${rows}<tr><td>Analyst</td>${players.map(player => `<td>${analystChip(player) || "—"}</td>`).join("")}</tr><tr><td>Remove</td>${players.map(player => `<td><button class="link-button" data-remove="${player.PLAYER_ID}">Remove</button></td>`).join("")}</tr></tbody></table></div>`;
}

function openPlayer(id) {
  const row = state.rows.find(player => player.PLAYER_ID === Number(id));
  if (!row) return;
  const valueGap = row.adp == null ? null : row.adp - row.rank;
  const valueText = valueGap == null ? "No ADP available" : valueGap >= 12 ? `Market discount: ${integer(valueGap)} picks` : valueGap <= -12 ? `Market is ${integer(-valueGap)} picks higher` : "Close to market price";
  $("#player-detail").innerHTML = `<header class="player-hero"><p class="eyebrow">${esc(row.TEAM_ABBREVIATION || "FREE AGENT")} · TIER ${row.tier ?? "—"}</p><h2>${esc(row.PLAYER_NAME)}</h2><p>FP/G rank #${row.rank} · safe source rank #${row.source_rank ?? "—"} · model source rank #${row.model_source_rank ?? "—"}</p></header>
    <div class="detail-body">
      <div class="detail-stats"><div class="detail-stat"><small>FP / game</small><strong>${fmt(row.fpts_pg)}</strong></div><div class="detail-stat"><small>VOR</small><strong>${fmt(row.vor)}</strong></div><div class="detail-stat"><small>Projected GP</small><strong>${integer(row.gp)}</strong></div><div class="detail-stat"><small>Projected MPG</small><strong>${fmt(row.mpg)}</strong></div><div class="detail-stat"><small>Age</small><strong>${integer(row.target_age)}</strong></div><div class="detail-stat"><small>ADP</small><strong>${integer(row.adp)}</strong></div><div class="detail-stat"><small>Risk</small><strong>${fmt(row.risk, 2)}</strong></div><div class="detail-stat"><small>Market read</small><strong>${esc(valueText)}</strong></div></div>
      <section class="detail-section"><h3>Projected per-game line</h3><div class="projection-line">${[["PTS",row.pts],["REB",row.reb],["AST",row.ast],["STL",row.stl],["BLK",row.blk],["3PM",row.fg3m],["TOV",row.tov]].map(([label,value]) => `<div><small>${label}</small><strong>${fmt(value)}</strong></div>`).join("")}</div></section>
      <section class="detail-section"><h3>Simulated season totals</h3><div class="season-band"><div><small>Floor · p10</small><strong>${integer(row.fpts_p10)}</strong></div><div><small>Median</small><strong>${integer(row.fpts_median)}</strong></div><div><small>Ceiling · p90</small><strong>${integer(row.fpts_p90)}</strong></div></div></section>
      ${isAdjusted(row) ? `<section class="detail-section"><h3>Analyst layer</h3><div class="analyst-note">${analystChip(row)} &nbsp; ${esc(row.analyst_category || "")} · ${esc(row.analyst_date || "")}. Detailed rationale remains in the private review workflow.</div></section>` : ""}
      <button class="button" data-modal-compare="${row.PLAYER_ID}">${state.compare.has(row.PLAYER_ID) ? "Remove from compare" : "Add to compare"}</button>
    </div>`;
  const dialog = $("#player-dialog");
  if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
}

function setView(view) {
  if (!viewCopy[view]) view = "board";
  state.view = view;
  $$(".view").forEach(section => section.hidden = section.id !== `view-${view}`);
  $$(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  [$("#view-title").textContent, $("#view-subtitle").textContent] = viewCopy[view];
  $(".sidebar").classList.remove("open");
  if (location.hash !== `#${view}`) history.replaceState(null, "", `#${view}`);
  if (view === "compare") drawCompare();
}

function populateFilters() {
  const teams = [...new Set(state.rows.map(row => row.TEAM_ABBREVIATION).filter(Boolean))].sort();
  $("#team-filter").insertAdjacentHTML("beforeend", teams.map(team => `<option value="${team}">${team}</option>`).join(""));
  const tiers = [...new Set(state.rows.map(row => row.tier).filter(tier => tier != null))].sort((a, b) => a - b);
  $("#tier-filter").insertAdjacentHTML("beforeend", tiers.map(tier => `<option value="${tier}">Tier ${tier}</option>`).join(""));
}

function bindEvents() {
  $("#search").addEventListener("input", event => { state.query = event.target.value; drawBoard(); });
  $("#team-filter").addEventListener("change", event => { state.team = event.target.value; drawBoard(); });
  $("#tier-filter").addEventListener("change", event => { state.tier = event.target.value; drawBoard(); });
  $("#limit").addEventListener("change", event => { state.limit = Number(event.target.value); drawBoard(); });
  $("#adjusted-only").addEventListener("change", event => { state.adjustedOnly = event.target.checked; drawBoard(); });
  $$("[data-sort]").forEach(button => button.addEventListener("click", () => {
    if (state.sort === button.dataset.sort) state.direction *= -1;
    else { state.sort = button.dataset.sort; state.direction = ["rank", "PLAYER_NAME", "TEAM_ABBREVIATION", "tier"].includes(state.sort) ? 1 : -1; }
    drawBoard();
  }));
  document.addEventListener("click", event => {
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
    const team = event.target.closest("[data-team]");
    if (team) { state.team = team.dataset.team; $("#team-filter").value = state.team; setView("board"); drawBoard(); }
    if (event.target.id === "clear-compare") { state.compare.clear(); saveCompare(); drawBoard(); drawCompare(); }
  });
  $("#mobile-nav").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
  $(".dialog-close").addEventListener("click", () => $("#player-dialog").close());
  $("#player-dialog").addEventListener("click", event => { if (event.target === $("#player-dialog")) $("#player-dialog").close(); });
  window.addEventListener("hashchange", () => setView(location.hash.slice(1)));
}

bindEvents();
saveCompare();
fetch("data/board.json", { cache: "no-store" })
  .then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
  .then(data => {
    state.meta = data;
    state.rows = [...data.rows].sort((a, b) => a.rank - b.rank);
    state.compare = new Set([...state.compare].filter(id => state.rows.some(row => row.PLAYER_ID === id)).slice(0, 4));
    $("#loading").hidden = true;
    const stamp = new Date(data.generated_at);
    $("#sidebar-stamp").textContent = Number.isNaN(stamp.valueOf()) ? "Board B" : stamp.toLocaleString();
    populateFilters(); drawSummary(); drawBoard(); drawTiers(); drawTeams(); drawCompare(); saveCompare();
    setView(location.hash.slice(1) || "board");
  })
  .catch(error => {
    $("#loading").hidden = true;
    $("#error").hidden = false;
    $("#error").textContent = `The published board could not be loaded (${error.message}). Run scripts/export_static.py and commit static/data/board.json.`;
  });
