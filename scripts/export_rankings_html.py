"""Export a standalone, self-contained HTML of the FPTS rankings — an ad-hoc view.

    python scripts/export_rankings_html.py                 # -> fpts_rankings.html (board B)
    python scripts/export_rankings_html.py --no-analyst    # board A (no analyst layer)
    python scripts/export_rankings_html.py --top 200 --out ~/Desktop/rankings.html

Pulls the SAME board the web app serves (`api.boards.ranked_board`), so returning-vet
seeds and the analyst layer are included. Ranks by projected fantasy points per game
(the board's own `rank` column — risk-adjusted, "safe" stance — is kept as a cross-
reference "Draft #"). The output is a single file with no external assets: open it in any
browser, offline. Regenerate any time the board changes (nightly update, new BBM batch).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fantasy_nba.api import boards  # noqa: E402

PROCESSED = ROOT / "data" / "processed"


def _positions() -> dict[int, str]:
    """PLAYER_ID -> position string, ESPN eligibility preferred, pos_group fallback."""
    pos: dict[int, str] = {}
    sheet = PROCESSED / "draft_sheet_2026-27.parquet"
    if sheet.exists():
        s = pd.read_parquet(sheet)
        if {"PLAYER_ID", "pos_group"} <= set(s.columns):
            for pid, pg in zip(s["PLAYER_ID"], s["pos_group"]):
                if pd.notna(pg):
                    pos[int(pid)] = str(pg)
    emap = PROCESSED / "espn_player_map.parquet"
    if emap.exists():
        m = pd.read_parquet(emap)
        if {"PLAYER_ID", "eligible"} <= set(m.columns):
            for pid, el in zip(m["PLAYER_ID"], m["eligible"]):
                if pd.notna(el) and str(el).strip():
                    pos[int(pid)] = str(el)  # ESPN eligibility wins
    return pos


def _parse_delta(action) -> float | None:
    """The fpts_delta in an ``analyst_action`` string, or None when there is no rate leg.

    Must handle the composite form ``target_mpg:31|fpts_delta:-4.3`` — an anchored match on
    ``fpts_delta:`` alone silently returns None there, reporting an adjusted player as
    reviewed-with-no-delta.
    """
    if not isinstance(action, str):
        return None
    m = re.search(r"fpts_delta:([+-]?\d+(?:\.\d+)?)", action.strip())
    return float(m.group(1)) if m else None


def build_rows(model: str, stance: str, analyst: bool, top: int | None) -> tuple[list[dict], dict]:
    b = boards.ranked_board(boards.CURRENT_TARGET, model, stance, analyst).copy()
    b = b.sort_values("fpts_pg", ascending=False).reset_index(drop=True)
    if top:
        b = b.head(top)
    pos = _positions()

    def num(v):
        return None if v is None or pd.isna(v) else round(float(v), 2)

    rows: list[dict] = []
    n_adjusted = 0
    for i, r in b.iterrows():
        action = r.get("analyst_action")
        delta = _parse_delta(action)
        reviewed = isinstance(action, str) and action.strip() != ""
        if delta is not None:
            n_adjusted += 1
        adate = r.get("analyst_date")
        seed = str(r.get("seed_class") or "")
        rows.append({
            "frank": i + 1,
            "drank": None if pd.isna(r.get("rank")) else int(r["rank"]),
            "player": str(r.get("PLAYER_NAME", "")),
            "team": None if pd.isna(r.get("TEAM_ABBREVIATION")) else str(r["TEAM_ABBREVIATION"]),
            "pos": pos.get(int(r["PLAYER_ID"]), "") if pd.notna(r.get("PLAYER_ID")) else "",
            "tier": None if pd.isna(r.get("tier")) else int(r["tier"]),
            "gp": None if pd.isna(r.get("gp")) else int(round(float(r["gp"]))),
            "mpg": num(r.get("mpg")),
            "fpts": num(r.get("fpts_pg")),
            "floor": num(r.get("fpts_p10")),
            "ceil": num(r.get("fpts_p90")),
            "delta": delta,
            "reviewed": reviewed,
            "adate": "" if adate is None or pd.isna(adate) else str(adate),
            "seed": seed,
        })
    meta = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": boards.CURRENT_TARGET,
        "model": model,
        "stance": stance,
        "analyst": analyst,
        "n": len(rows),
        "n_adjusted": n_adjusted,
    }
    return rows, meta


def render(rows: list[dict], meta: dict) -> str:
    board_label = "B — analyst-adjusted" if meta["analyst"] else "A — model only"
    return (_TEMPLATE
            .replace("__DATA__", json.dumps(rows, ensure_ascii=False))
            .replace("__META__", json.dumps(meta, ensure_ascii=False))
            .replace("__BOARD_LABEL__", board_label)
            .replace("__TARGET__", meta["target"]))


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FPTS Rankings &middot; __TARGET__</title>
<style>
  :root{
    --bg:#f7f8fa; --card:#fff; --fg:#12151c; --muted:#5b6472; --line:#e4e7ec;
    --head:#eef1f5; --zebra:#fafbfc; --hover:#eef4ff; --accent:#2456d6;
    --pos:#0f8a4f; --neg:#c8321f; --chip:#eceff3; --seed:#8a5a00; --seedbg:#fff3d6;
  }
  @media (prefers-color-scheme:dark){
    :root{
      --bg:#0e1116; --card:#151a21; --fg:#e6e9ef; --muted:#98a2b3; --line:#242b35;
      --head:#1b2129; --zebra:#12161c; --hover:#1a2233; --accent:#6f9bff;
      --pos:#37c47f; --neg:#ff6b57; --chip:#232a34; --seed:#e0b25a; --seedbg:#332a12;
    }
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{background:var(--bg);color:var(--fg);
    font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  .wrap{max-width:1180px;margin:0 auto;padding:22px 16px 60px}
  h1{font-size:20px;margin:0 0 2px;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:12.5px;margin-bottom:16px}
  .sub b{color:var(--fg);font-weight:600}
  .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
  input[type=search]{flex:1 1 240px;min-width:180px;padding:8px 11px;border:1px solid var(--line);
    border-radius:8px;background:var(--card);color:var(--fg);font-size:13.5px}
  input[type=search]:focus{outline:2px solid var(--accent);outline-offset:0;border-color:transparent}
  .toggle{display:inline-flex;align-items:center;gap:6px;color:var(--muted);font-size:13px;
    padding:7px 11px;border:1px solid var(--line);border-radius:8px;background:var(--card);cursor:pointer;user-select:none}
  .toggle input{accent-color:var(--accent)}
  .count{color:var(--muted);font-size:12.5px;margin-left:auto}
  .tablecard{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:auto}
  table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
  thead th{position:sticky;top:0;background:var(--head);z-index:2;text-align:right;
    font-weight:600;font-size:11.5px;letter-spacing:.03em;text-transform:uppercase;color:var(--muted);
    padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap;cursor:pointer;user-select:none}
  thead th.l{text-align:left}
  thead th .ind{display:inline-block;width:10px;opacity:.9;color:var(--accent)}
  tbody td{padding:8px 12px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
  tbody td.l{text-align:left}
  tbody tr:nth-child(even){background:var(--zebra)}
  tbody tr:hover{background:var(--hover)}
  .fr{color:var(--muted);font-size:12px}
  .pl{font-weight:600}
  .fpts{font-weight:700;font-size:14.5px}
  .rng{color:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums}
  .team,.pos{color:var(--muted);font-size:12px}
  .d-pos{color:var(--pos);font-weight:600} .d-neg{color:var(--neg);font-weight:600} .d-none{color:var(--muted)}
  .seedtag{display:inline-block;margin-left:6px;padding:0 5px;border-radius:4px;font-size:10px;font-weight:600;
    color:var(--seed);background:var(--seedbg)}
</style>
</head>
<body>
<div class="wrap">
  <h1>FPTS Rankings &middot; <span id="target"></span></h1>
  <div class="sub" id="subline"></div>
  <div class="controls">
    <input type="search" id="q" placeholder="Filter by player, team, or position…" autocomplete="off">
    <label class="toggle"><input type="checkbox" id="adjonly"> Analyst-adjusted only</label>
    <span class="count" id="count"></span>
  </div>
  <div class="tablecard">
    <table>
      <thead><tr id="hrow">
        <th data-k="frank" data-dir="1">#</th>
        <th data-k="player" data-dir="1" class="l">Player</th>
        <th data-k="team" data-dir="1" class="l">Tm</th>
        <th data-k="pos" data-dir="1" class="l">Pos</th>
        <th data-k="tier" data-dir="1">Tier</th>
        <th data-k="gp" data-dir="-1">GP</th>
        <th data-k="mpg" data-dir="-1">MPG</th>
        <th data-k="fpts" data-dir="-1">FPTS/g</th>
        <th data-k="floor" data-dir="-1">Floor&ndash;Ceil</th>
        <th data-k="delta" data-dir="-1">Analyst</th>
        <th data-k="drank" data-dir="1">Draft #</th>
      </tr></thead>
      <tbody id="tb"></tbody>
    </table>
  </div>
</div>
<script>
const DATA = __DATA__;
const META = __META__;
const NUM = new Set(["frank","drank","tier","gp","mpg","fpts","floor","delta"]);
let sortK = "frank", sortDir = 1;

const fmt = (v, d=1) => (v===null||v===undefined) ? "—" : (typeof v==="number" ? v.toFixed(d) : v);
const esc = s => String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function deltaCell(r){
  if(r.delta===null||r.delta===undefined){
    return r.reviewed ? '<span class="d-none">none</span>' : '';
  }
  const cls = r.delta>0 ? "d-pos" : (r.delta<0 ? "d-neg" : "d-none");
  const sign = r.delta>0 ? "+" : "";
  const t = r.adate ? ' title="'+esc(r.adate)+'"' : "";
  return '<span class="'+cls+'"'+t+'>'+sign+r.delta.toFixed(1)+'</span>';
}
function seedTag(r){
  return r.seed==="returning-vet"
    ? '<span class="seedtag" title="ADP-anchored (returning veteran, not box-score modelled)">mkt</span>' : '';
}
function rowHtml(r){
  const rng = (r.floor===null&&r.ceil===null) ? "—" : (fmt(r.floor)+"–"+fmt(r.ceil));
  return '<tr>'
    + '<td class="fr">'+r.frank+'</td>'
    + '<td class="l"><span class="pl">'+esc(r.player)+'</span>'+seedTag(r)+'</td>'
    + '<td class="l team">'+esc(r.team||"—")+'</td>'
    + '<td class="l pos">'+esc(r.pos||"—")+'</td>'
    + '<td>'+(r.tier===null?"—":r.tier)+'</td>'
    + '<td>'+(r.gp===null?"—":r.gp)+'</td>'
    + '<td>'+fmt(r.mpg)+'</td>'
    + '<td class="fpts">'+fmt(r.fpts)+'</td>'
    + '<td class="rng">'+rng+'</td>'
    + '<td>'+deltaCell(r)+'</td>'
    + '<td class="fr">'+(r.drank===null?"—":r.drank)+'</td>'
    + '</tr>';
}
function indicators(){
  document.querySelectorAll("#hrow th").forEach(th=>{
    const base = th.dataset.k;
    let ind = "";
    if(base===sortK) ind = ' <span class="ind">'+(sortDir>0?"▲":"▼")+'</span>';
    // strip any old indicator then re-add
    th.innerHTML = th.innerHTML.replace(/ <span class="ind">[▲▼]<\/span>$/,"") + ind;
  });
}
function apply(){
  const q = document.getElementById("q").value.trim().toLowerCase();
  const adj = document.getElementById("adjonly").checked;
  let rows = DATA.filter(r=>{
    if(adj && (r.delta===null||r.delta===undefined)) return false;
    if(!q) return true;
    return r.player.toLowerCase().includes(q)
        || (r.team||"").toLowerCase().includes(q)
        || (r.pos||"").toLowerCase().includes(q);
  });
  rows.sort((a,b)=>{
    let x=a[sortK], y=b[sortK];
    const xn=(x===null||x===undefined), yn=(y===null||y===undefined);
    if(xn&&yn) return 0; if(xn) return 1; if(yn) return -1;
    if(NUM.has(sortK)) return (x-y)*sortDir;
    return String(x).localeCompare(String(y))*sortDir;
  });
  document.getElementById("tb").innerHTML = rows.map(rowHtml).join("");
  document.getElementById("count").textContent = rows.length+" shown";
}
document.querySelectorAll("#hrow th").forEach(th=>{
  th.addEventListener("click", ()=>{
    const k = th.dataset.k;
    if(k===sortK){ sortDir = -sortDir; }
    else { sortK = k; sortDir = parseInt(th.dataset.dir,10); }
    indicators(); apply();
  });
});
document.getElementById("q").addEventListener("input", apply);
document.getElementById("adjonly").addEventListener("change", apply);

document.getElementById("target").textContent = META.target;
document.getElementById("subline").innerHTML =
  'Board <b>__BOARD_LABEL__</b> &middot; '+META.model+'/'+META.stance+' &middot; ESPN 12-team H2H points '
  + '&middot; <b>'+META.n+'</b> players, <b>'+META.n_adjusted+'</b> analyst-adjusted &middot; generated '+META.generated;

indicators();
apply();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Export FPTS rankings to a standalone HTML.")
    ap.add_argument("--model", default="learned", choices=list(boards.MODELS))
    ap.add_argument("--stance", default="safe", choices=list(boards.STANCES))
    ap.add_argument("--no-analyst", action="store_true", help="Board A (skip the analyst layer).")
    ap.add_argument("--top", type=int, default=None, help="Limit to the top N by fpts/g.")
    ap.add_argument("--out", default=str(ROOT / "fpts_rankings.html"))
    args = ap.parse_args()

    rows, meta = build_rows(args.model, args.stance, not args.no_analyst, args.top)
    html = render(rows, meta)
    out = Path(args.out).expanduser()
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}  ({meta['n']} players, {meta['n_adjusted']} analyst-adjusted)")


if __name__ == "__main__":
    main()
