// Read-only, URL-backed trade comparisons over the current local roster cache.
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { TradeRosterRow, TradeSandboxResponse, TradeScenarioSide, WeeksResponse, useApi } from "../lib/api";
import { f1, signed } from "../lib/format";
import { CopyLink } from "../components/Portability";
import { LineupDetail } from "../components/LineupDetail";
import { Card, Chip, EmptyNote, ErrorNote, Field, SearchInput, Select, Spinner } from "../components/ui";

const selectionKeys = ["out_a", "out_b", "drop_a", "drop_b", "pickup_a", "pickup_b"] as const;
type SelectionKey = typeof selectionKeys[number];

function ids(raw: string | null): number[] {
  return (raw ?? "").split(",").filter(Boolean).map(Number).filter(Number.isSafeInteger);
}

function difference(after: number | null, before: number | null, unit = ""): string {
  return after == null || before == null ? "unknown" : `${signed(after - before)}${unit}`;
}

function Metric({ label, before, after, unit = "", note }: { label: string; before: number | null; after: number | null; unit?: string; note?: string }) {
  return <div className="rounded-lg border border-bdr p-2 text-[12px]">
    <div className="text-ink-3" title={note}>{label}</div>
    <div className="mt-1 font-semibold tnum">{before == null ? "unknown" : f1(before)} → {after == null ? "unknown" : f1(after)}{unit}</div>
    <div className="tnum text-ink-3">Change {difference(after, before, unit)}</div>
  </div>;
}

function SideResult({ title, side, schedule }: { title: string; side: TradeScenarioSide; schedule: boolean }) {
  const { before, after } = side;
  const seasonComparable = before.season_total_common_source && after.season_total_common_source;
  return <Card className="min-w-0 p-4">
    <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-bold">{title}</h3><Chip tone={side.roster_delta === 0 ? "neutral" : "warn"}>Roster {signed(side.roster_delta, 0)}</Chip></div>
    <div className="mt-3 grid grid-cols-2 gap-2">
      <Metric label="Roster FP/G sum" before={before.fpts_pg_total} after={after.fpts_pg_total} />
      <Metric label="Eligible starters FP/G" before={before.starter_fpts_pg} after={after.starter_fpts_pg} note="Best eligible assignment on an all-play day; not a weekly total." />
      <Metric label="Players above unrostered benchmark" before={before.depth_above_wire} after={after.depth_above_wire} />
      <Metric label="Open starting slots" before={before.open_slots.length} after={after.open_slots.length} />
      <Metric label="Projected season total" before={seasonComparable ? before.season_total : null} after={seasonComparable ? after.season_total : null} note="Only shown when every player has the same projection source and horizon." />
      <Metric label="Roster size" before={before.n_players} after={after.n_players} />
      {schedule && <>
        <Metric label="Usable week FP" before={before.week.usable_points} after={after.week.usable_points} />
        <Metric label="Raw scheduled FP" before={before.week.raw_points} after={after.week.raw_points} />
      </>}
    </div>
    {!seasonComparable && <p className="mt-2 text-[11px] text-warn">Season totals are hidden because player projections do not share one source and horizon.</p>}
    {(!before.starter_exact || !after.starter_exact) && <p className="mt-2 text-[11px] text-warn">Starter FP/G is uncertain where eligibility or FP/G is missing. Known assigned FP/G: {f1(before.known_starter_fpts_pg)} → {f1(after.known_starter_fpts_pg)}.</p>}
    {schedule && (!before.week.exact || !after.week.exact) && <p className="mt-2 text-[11px] text-warn">Weekly feasible points are uncertain where eligibility, FP/G or game dates are missing.</p>}
    <p className="mt-2 text-[11px] text-ink-3">Top unrostered benchmark: {after.wire_fpts_pg == null ? "unavailable" : `${f1(after.wire_fpts_pg)} FP/G`}. Depth counts rostered players above that single benchmark; partial draft rosters may leave stars unrostered.</p>
    <details className="mt-3 text-[12px]"><summary className="cursor-pointer font-semibold">After-trade roster and individual risk</summary>
      <div className="mt-2 space-y-1">{side.rows_after.map((row) => <div key={row.PLAYER_ID} className="flex flex-wrap justify-between gap-x-2 border-b border-bdr py-1">
        <Link to={`/players/${row.PLAYER_ID}`} className="text-accent hover:underline">{row.PLAYER_NAME}</Link>
        <span className="tnum text-ink-2">{f1(row.fpts_pg)} FP/G · risk {row.risk == null ? "unknown" : f1(row.risk)} · P10–P90 {row.fpts_p10 == null || row.fpts_p90 == null ? "unknown" : `${f1(row.fpts_p10)}–${f1(row.fpts_p90)}`}</span>
      </div>)}</div>
      <p className="mt-2 text-[11px] text-ink-3">Risk ranges belong to individual players and are not added into a team interval.</p>
    </details>
  </Card>;
}

function RosterSelector({ title, rows, outgoing, drops, onToggle }: { title: string; rows: TradeRosterRow[]; outgoing: number[]; drops: number[]; onToggle: (key: SelectionKey, id: number) => void }) {
  const side = title === "Team A" ? "a" : "b";
  return <Card className="min-w-0 p-4">
    <h2 className="text-sm font-bold">{title} · sends {outgoing.length}</h2>
    <p className="mt-1 text-[11px] text-ink-3">Choose players to send. Market gap is consensus rank minus our rank; it is only a price reference.</p>
    <div className="mt-3 max-h-80 space-y-1.5 overflow-y-auto pr-1">{rows.map((row) => <div key={row.PLAYER_ID} className="rounded-lg border border-bdr p-2 text-[12px]">
      <label className="flex cursor-pointer items-start gap-2"><input type="checkbox" checked={outgoing.includes(row.PLAYER_ID)} onChange={() => onToggle(`out_${side}`, row.PLAYER_ID)} className="mt-0.5" />
        <span className="min-w-0"><strong>{row.PLAYER_NAME}</strong> <span className="text-ink-3">{row.TEAM_ABBREVIATION ?? "unknown"} · {f1(row.fpts_pg)} FP/G</span>
          <span className="block text-[11px] text-ink-3">Our #{row.rank ?? "?"} · market #{row.consensus_rank ?? "?"} · gap {row.market_gap == null ? "unknown" : signed(row.market_gap, 0)}{row.status_override ? ` · ${row.status_override}` : ""}</span>
        </span>
      </label>
      {!outgoing.includes(row.PLAYER_ID) && <label className="ml-5 mt-1 flex items-center gap-1 text-[11px] text-ink-2"><input type="checkbox" checked={drops.includes(row.PLAYER_ID)} onChange={() => onToggle(`drop_${side}`, row.PLAYER_ID)} /> Drop to make room</label>}
    </div>)}</div>
  </Card>;
}

export default function TradeSandbox() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const weeks = useApi<WeeksResponse>("/api/weeks").data;
  const setupQuery = new URLSearchParams();
  for (const key of ["team_a", "team_b", "week", "start", "end"]) { const value = params.get(key); if (value) setupQuery.set(key, value); }
  const setupPath = `/api/trade-sandbox${setupQuery.size ? `?${setupQuery}` : ""}`;
  const setup = useApi<TradeSandboxResponse>(setupPath);
  const submitted = params.get("apply") === "1";
  const runQuery = new URLSearchParams(setupQuery);
  for (const key of selectionKeys) { const value = params.get(key); if (value) runQuery.set(key, value); }
  const run = useApi<TradeSandboxResponse>(submitted ? `/api/trade-sandbox?${runQuery}` : null);
  const data = setup.loading || setup.error ? null : setup.data;
  const scenario = submitted && !run.loading && !run.error ? run.data?.scenario : null;
  const aOut = ids(params.get("out_a")); const bOut = ids(params.get("out_b"));
  const aDrops = ids(params.get("drop_a")); const bDrops = ids(params.get("drop_b"));
  const aPickups = ids(params.get("pickup_a")); const bPickups = ids(params.get("pickup_b"));
  const neededA = Math.max(0, bOut.length - aOut.length);
  const neededB = Math.max(0, aOut.length - bOut.length);
  const optionalA = Math.max(0, aOut.length - bOut.length);
  const optionalB = Math.max(0, bOut.length - aOut.length);
  const canEvaluate = aOut.length > 0 && bOut.length > 0 && aDrops.length === neededA && bDrops.length === neededB && aPickups.length <= optionalA && bPickups.length <= optionalB;

  function update(key: string, value: string) {
    setParams(current => {
      const next = new URLSearchParams(current); next.delete("apply");
      if (value) next.set(key, value); else next.delete(key);
      if (key === "week") { next.delete("start"); next.delete("end"); }
      return next;
    });
  }
  function changeTeam(key: "team_a" | "team_b", value: string) {
    setParams(current => {
      const next = new URLSearchParams(current); next.delete("apply");
      selectionKeys.forEach(k => next.delete(k));
      next.set(key, value);
      const other = key === "team_a" ? "team_b" : "team_a";
      const otherValue = next.get(other) ?? String(key === "team_a" ? data?.team_b : data?.team_a);
      if (otherValue === value) {
        const replacement = data?.teams?.find(t => String(t.team_id) !== value);
        if (replacement) next.set(other, String(replacement.team_id));
      }
      return next;
    });
  }
  function toggle(key: SelectionKey, id: number) {
    const selected = ids(params.get(key));
    const next = selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id];
    setParams(current => {
      const result = new URLSearchParams(current); result.delete("apply");
      if (next.length) result.set(key, next.join(",")); else result.delete(key);
      if (key === "out_a" || key === "out_b") {
        const dropKey = key === "out_a" ? "drop_a" : "drop_b";
        result.set(dropKey, ids(result.get(dropKey)).filter(x => x !== id).join(","));
        if (!result.get(dropKey)) result.delete(dropKey);
      }
      return result;
    });
  }
  function evaluate() { if (canEvaluate) setParams(current => { const result = new URLSearchParams(current); result.set("apply", "1"); return result; }); }

  const weekOptions = weeks?.has_schedule ? weeks.weeks : [];
  const selectedWeek = weekOptions.find(w => w.week === Number(params.get("week") ?? data?.week));
  const available = (data?.available ?? []).filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase())).slice(0, 40);
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="text-xl font-bold">Trade Sandbox</h1><p className="mt-1 text-[12px] text-ink-3">Compare both rosters after a proposed trade. This read-only view never sends a trade to ESPN.</p></div>{scenario && <CopyLink />}</div>
    {setup.error && <><ErrorNote message={setup.error} /><button className="text-sm text-accent underline" onClick={() => setParams(new URLSearchParams())}>Reset team selection</button></>}{setup.loading && <Spinner label="Loading league rosters…" />}
    {data && !data.has_teams && <Card className="p-4"><EmptyNote>{data.note} <Link to="/room" className="text-accent underline">Open Draft Room</Link></EmptyNote></Card>}
    {data?.has_teams && <>
      <Card className="p-4 text-[12px]"><div className="flex flex-wrap gap-2"><Chip tone={data.ownership_status === "fresh_snapshot" ? "up" : "warn"}>Ownership: {data.ownership_status?.replaceAll("_", " ")}</Chip><Chip>Projections: {data.projection_source === "ros" ? "ROS" : "preseason board"}</Chip><Chip>Slots: {data.slot_source?.replaceAll("_", " ")}</Chip></div>
        <p className="mt-2 text-ink-3">Roster source {data.roster_source === "espn_live" ? "ESPN snapshot" : "draft-session picks"}{data.rosters_asof ? ` · as of ${data.rosters_asof}` : ""}. Projection as of {data.projection_asof ?? "preseason board"}; market ranks as of {data.market_date ?? "unavailable"}. Shared URL rechecks current ownership when opened.</p>
        <p className="mt-1 text-ink-3">{data.note} Standard capacity {data.standard_roster_capacity ?? "unknown"}, IR slots {data.ir_slots ?? "unknown"}; IR assignments are unknown.</p>
      </Card>
      <Card className="p-4"><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Team A"><Select value={String(data.team_a)} onChange={v => changeTeam("team_a", v)} options={(data.teams ?? []).map(t => ({ value: String(t.team_id), label: `Team ${t.team_id}${t.team_id === data.my_team_id ? " (mine)" : ""} · ${t.n_players} players` }))} /></Field>
        <Field label="Team B"><Select value={String(data.team_b)} onChange={v => changeTeam("team_b", v)} options={(data.teams ?? []).map(t => ({ value: String(t.team_id), label: `Team ${t.team_id}${t.team_id === data.my_team_id ? " (mine)" : ""} · ${t.n_players} players` }))} /></Field>
        <Field label="Matchup week"><Select value={selectedWeek ? String(selectedWeek.week) : ""} onChange={v => update("week", v)} options={weekOptions.length ? weekOptions.map(w => ({ value: String(w.week), label: `${w.week_name} (${w.start}–${w.end})` })) : [{ value: "", label: "No cached schedule" }]} /></Field>
        {selectedWeek && <Field label="Date range"><span className="text-sm text-ink-2">{data.start ?? selectedWeek.start} to {data.end ?? selectedWeek.end}</span></Field>}
        {selectedWeek && <><Field label="Start"><Select value={params.get("start") ?? selectedWeek.start} onChange={v => update("start", v)} options={selectedWeek.days.map(d => ({ value: d, label: d }))} /></Field><Field label="End"><Select value={params.get("end") ?? selectedWeek.end} onChange={v => update("end", v)} options={selectedWeek.days.map(d => ({ value: d, label: d }))} /></Field></>}
      </div>{!data.has_schedule && <p className="mt-2 text-[12px] text-warn">No cached game schedule. Weekly feasible points and playoff volume cannot be calculated; season and roster comparisons remain available.</p>}</Card>
      <div className="grid gap-4 lg:grid-cols-2"><RosterSelector title="Team A" rows={data.a_roster ?? []} outgoing={aOut} drops={aDrops} onToggle={toggle} /><RosterSelector title="Team B" rows={data.b_roster ?? []} outgoing={bOut} drops={bDrops} onToggle={toggle} /></div>
      <Card className="p-4 text-[12px]"><h2 className="text-sm font-bold">Roster spots</h2>
        <p className="mt-1 text-ink-3">Team A must drop {neededA} and may add up to {optionalA} unrostered player{optionalA === 1 ? "" : "s"}. Team B must drop {neededB} and may add up to {optionalB}. Mark required drops on each roster above. Optional pickups fill vacated spots; they are separate from the trade.</p>
        {(optionalA > 0 || optionalB > 0) && <><div className="mt-3 max-w-sm"><SearchInput value={search} onChange={setSearch} placeholder="Find an available player" /></div><div className="mt-2 grid max-h-56 gap-1 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">{available.map(p => <div key={p.player_id} className="rounded border border-bdr px-2 py-1.5"><div className="font-medium">{p.name} <span className="text-ink-3">{f1(p.fpts_pg)} FP/G{p.status ? ` · ${p.status}` : ""}</span></div><div className="mt-1 flex gap-3">{optionalA > 0 && <label><input type="checkbox" checked={aPickups.includes(p.player_id)} onChange={() => toggle("pickup_a", p.player_id)} /> Team A pickup</label>}{optionalB > 0 && <label><input type="checkbox" checked={bPickups.includes(p.player_id)} onChange={() => toggle("pickup_b", p.player_id)} /> Team B pickup</label>}</div></div>)}</div></>}
        {!canEvaluate && (aOut.length || bOut.length) > 0 && <p className="mt-2 text-warn">Both sides must send a player. Required drops: A {aDrops.length}/{neededA}; B {bDrops.length}/{neededB}. Optional pickups cannot exceed open spots.</p>}
        <button type="button" disabled={!canEvaluate} onClick={evaluate} className="mt-3 rounded-lg bg-accent px-4 py-2 font-bold text-accent-ink disabled:opacity-50">Compare trade</button>
      </Card>
      {submitted && run.error && <ErrorNote message={run.error} />}{submitted && run.loading && <Spinner label="Calculating both sides…" />}
      {scenario && <>
        <Card className="p-4 text-[12px]"><h2 className="text-sm font-bold">Scenario assumptions</h2><p className="mt-1 text-ink-3">Team A sends {scenario.out_a.length}, receives {scenario.out_b.length}; Team B sends {scenario.out_b.length}, receives {scenario.out_a.length}. {scenario.released_ids.length} drop{scenario.released_ids.length === 1 ? "" : "s"}, {scenario.acquired_ids.length} optional pickup{scenario.acquired_ids.length === 1 ? "" : "s"}. Both sides are evaluated over the same {data.start && data.end ? `${data.start} to ${data.end}` : "unscheduled projection horizon"}.</p>
          <p className="mt-1 text-warn">Standard roster capacity {scenario.capacity.standard}; after-trade over capacity: A {scenario.capacity.a_after_over_standard ? "yes" : "no"}, B {scenario.capacity.b_after_over_standard ? "yes" : "no"}. IR placement and ESPN trade acceptance remain unverified, even when neither side exceeds standard capacity.</p>
        </Card>
        <div className="grid gap-4 lg:grid-cols-2"><SideResult title={`Team ${data.team_a}`} side={scenario.a} schedule={!!data.has_schedule} /><SideResult title={`Team ${data.team_b}`} side={scenario.b} schedule={!!data.has_schedule} /></div>
        {scenario.playoff_volume && <Card className="p-4 text-[12px]"><h2 className="text-sm font-bold">Confirmed playoff schedule · raw rostered games</h2><p className="mt-1 text-ink-3">These are scheduled roster games, not feasible starts.</p>{scenario.playoff_volume.weeks.map(w => <p key={w} className="mt-1">Week {w}: A {scenario.playoff_volume?.a_before[String(w)] ?? "?"} → {scenario.playoff_volume?.a_after[String(w)] ?? "?"}; B {scenario.playoff_volume?.b_before[String(w)] ?? "?"} → {scenario.playoff_volume?.b_after[String(w)] ?? "?"}</p>)}</Card>}
        {data.has_schedule && <div className="grid gap-4 lg:grid-cols-2"><LineupDetail lineup={scenario.a.after.week} title={`Team ${data.team_a} after · feasible starts`} /><LineupDetail lineup={scenario.b.after.week} title={`Team ${data.team_b} after · feasible starts`} /></div>}
        <p className="text-[11px] text-ink-3">The sandbox shows each side separately. Market gap is a price reference; no fairness grade, trade win probability or team risk interval is inferred.</p>
      </>}
    </>}
  </div>;
}
