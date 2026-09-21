const n = (v, digits = 1) => v == null ? "—" : Number(v).toFixed(digits);
const state = { rows: [], limit: 100, query: "" };
const body = document.querySelector("#rows");

function draw() {
  const q = state.query.toLowerCase();
  const rows = state.rows.filter(r => !q || `${r.PLAYER_NAME} ${r.TEAM_ABBREVIATION ?? ""}`.toLowerCase().includes(q)).slice(0, state.limit);
  body.innerHTML = rows.map(r => `<tr><td>${r.rank}</td><td>${r.PLAYER_NAME}</td><td>${r.TEAM_ABBREVIATION ?? "—"}</td><td>${n(r.fpts_pg)}</td><td>${n(r.mpg)}</td><td>${n(r.gp, 0)}</td><td>${n(r.fpts_p10)}</td><td>${n(r.fpts_median)}</td><td>${n(r.fpts_p90)}</td><td class="analyst">${r.analyst_action && r.analyst_action !== "none" ? r.analyst_action : ""}</td></tr>`).join("");
  document.querySelector("#status").textContent = `${rows.length} players shown`;
}

document.querySelector("#search").addEventListener("input", e => { state.query = e.target.value; draw(); });
document.querySelector("#limit").addEventListener("change", e => { state.limit = Number(e.target.value); draw(); });

fetch("data/board.json", { cache: "no-store" }).then(r => r.ok ? r.json() : Promise.reject(r.status)).then(data => {
  // Static-board rank is deliberately FP/G-first: safe rank is still available in the
  // live app, but this public view is the quick points-league value board.
  state.rows = data.rows.sort((a, b) => (b.fpts_pg ?? -Infinity) - (a.fpts_pg ?? -Infinity));
  document.querySelector("#stamp").textContent = `Published ${new Date(data.generated_at).toLocaleString()} · analyst layer applied`;
  draw();
}).catch(() => { document.querySelector("#stamp").textContent = "No published board snapshot yet. Run scripts/export_static.py."; });
