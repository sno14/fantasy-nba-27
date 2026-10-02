// Daily home. Dated signals only; a missing league timezone suppresses date-specific claims.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { compareSnapshots, validateChangeSnapshot, type ChangeEvent, type ChangeSnapshot } from "../../../static/changes.mjs";
import { MyTeamResponse, TodayContext, get, useApi } from "../lib/api";
import { useDraftTargets } from "../lib/draftRadar";
import { f1, signed } from "../lib/format";
import { Card, Chip, EmptyNote, ErrorNote, Spinner } from "../components/ui";

interface Version { version: string; asof: string; season: string; rankedBy: string; scoringKey: string; source: string }
interface Versions { schema: number; versions: Version[] }
interface History { version: string; previous: string; events: ChangeEvent[] }

function Source({ label, source, asof, note }: { label: string; source: string; asof: string | null; note?: string }) {
  return <div className="rounded-lg border border-bdr p-2 text-[12px]"><div className="font-semibold">{label}</div><div className="mt-1 text-ink-2">{source}</div><div className="tnum text-ink-3">{asof ?? "No dated source"}</div>{note && <div className="text-[11px] text-ink-3">{note}</div>}</div>;
}

export default function Today() {
  const { targets } = useDraftTargets();
  const context = useApi<TodayContext>("/api/today/context", true);
  const team = useApi<MyTeamResponse>("/api/myteam", true);
  const [history, setHistory] = useState<History | null>(null);
  const [historyState, setHistoryState] = useState<"loading" | "collecting" | "ready" | "error">("loading");

  useEffect(() => {
    let live = true;
    get<Versions>("/api/changes/versions", true).then(async manifest => {
      if (manifest.schema !== 1 || !Array.isArray(manifest.versions)) throw new Error("Invalid ROS history manifest");
      const latest = manifest.versions.at(-1);
      const previous = manifest.versions.slice(0, -1).reverse().find(item => latest && item.season === latest.season && item.rankedBy === latest.rankedBy && item.scoringKey === latest.scoringKey && item.source === latest.source);
      if (!latest || !previous) { if (live) setHistoryState("collecting"); return; }
      const [newValue, oldValue] = await Promise.all([
        get<ChangeSnapshot>(`/api/changes/version/${latest.version}`),
        get<ChangeSnapshot>(`/api/changes/version/${previous.version}`),
      ]);
      if (!live) return;
      const events = compareSnapshots(validateChangeSnapshot(newValue), validateChangeSnapshot(oldValue));
      setHistory({ version: latest.version, previous: previous.version, events });
      setHistoryState("ready");
    }).catch(() => { if (live) setHistoryState("error"); });
    return () => { live = false; };
  }, []);

  const data = team.loading || team.error ? null : team.data;
  const info = context.loading || context.error ? null : context.data;
  const rows = data?.rows ?? [];
  const rosterIds = useMemo(() => new Set(rows.map(row => row.PLAYER_ID)), [rows]);
  const watched = useMemo(() => new Set(Object.keys(targets).map(Number)), [targets]);
  const alerts = useMemo(() => {
    const byId = new Map<number, { id: number; name: string; status: string; event: ChangeEvent | null; onRoster: boolean; watched: boolean }>();
    if (info?.status.source === "ros_snapshot") for (const row of rows) if (row.status_override) byId.set(row.PLAYER_ID, { id: row.PLAYER_ID, name: row.PLAYER_NAME, status: row.status_override, event: null, onRoster: true, watched: watched.has(row.PLAYER_ID) });
    if (history) for (const event of history.events) {
      if (!rosterIds.has(event.id) && !watched.has(event.id)) continue;
      const item = byId.get(event.id);
      byId.set(event.id, { id: event.id, name: event.name, status: item?.status ?? "", event,
        onRoster: rosterIds.has(event.id), watched: watched.has(event.id) });
    }
    return [...byId.values()].sort((a, b) => Number(!!b.status) - Number(!!a.status) || Math.abs(b.event?.fptsDelta ?? 0) - Math.abs(a.event?.fptsDelta ?? 0) || a.name.localeCompare(b.name));
  }, [history, info?.status.source, rosterIds, rows, watched]);
  const day = info?.league_date && data?.lineup?.days.find(item => item.day === info.league_date);
  const crowded = (data?.day_grid ?? []).filter(item => (item.benched ?? 0) > 0);
  const openDays = (data?.day_grid ?? []).filter(item => item.games > 0 && item.starts < (data?.daily_slots ?? 0)).slice(0, 3);
  const unfinished: { title: string; detail: string; to: string }[] = [];
  if (!data?.has_team) unfinished.push({ title: "Set up my roster", detail: "Choose your team or add draft picks.", to: "/room" });
  if (data?.has_team && data.roster_source !== "espn_live") unfinished.push({ title: "Check current ownership", detail: "This view uses draft-session picks until a live roster refresh.", to: "/waivers" });
  if (data?.has_team && !data.has_positions) unfinished.push({ title: "Load player eligibility", detail: "Connect the ESPN player map to calculate legal starts.", to: "/room" });
  if (!data?.has_schedule) unfinished.push({ title: "Check the matchup calendar", detail: "Weekly and daily game dates are unavailable.", to: "/schedule" });
  if (watched.size === 0) unfinished.push({ title: "Build a watchlist", detail: "Save draft targets so their dated changes appear here.", to: "/draft-plan" });
  if (historyState === "collecting") unfinished.push({ title: "Collect a change baseline", detail: "Two compatible nightly ROS snapshots are needed.", to: "/changes" });

  return <div className="space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-xl font-bold">Today</h1><p className="mt-1 text-[12px] text-ink-3">Your roster, dated changes and next useful actions in one place.</p></div><Link to="/myteam" className="rounded-lg border border-bdr px-3 py-2 text-xs font-semibold text-accent hover:bg-surface-2">Full My Team roster →</Link></header>
    {context.error && <ErrorNote message={`Source context: ${context.error}`} />}{team.error && <ErrorNote message={`My Team: ${team.error}`} />}
    {(context.loading || team.loading) && <Spinner label="Loading daily home…" />}
    {info && <Card className="p-4" ><div id="today-sources" className="text-sm font-bold">What this view knows</div><div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <Source label="Board" source={info.board.source === "ros_snapshot" ? "Nightly ROS snapshot" : "Live-computed preseason model"} asof={info.board.asof} note={info.board.asof ? undefined : "No dated board snapshot"} />
      <Source label="Rosters" source={info.rosters.source === "espn_live" ? "ESPN roster snapshot" : "Draft-session picks"} asof={info.rosters.asof} note={info.rosters.freshness === "stale_snapshot" ? "Snapshot older than 24 hours or undated" : info.rosters.asof ? undefined : "Ownership is undated"} />
      <Source label="Schedule" source={info.schedule.source === "local_schedule_file" ? "Local schedule file" : "No local schedule"} asof={info.schedule.asof} note={info.schedule.asof ? "File modified (UTC)" : undefined} />
      <Source label="Availability" source={info.status.source === "ros_snapshot" ? "Status in ROS snapshot" : "No status snapshot"} asof={info.status.asof} note="Never a live injury confirmation" />
    </div><p className="mt-2 text-[11px] text-ink-3">{info.note} {rows.some(row => info.board.source === "ros_snapshot" && row.projection_source !== "ros") ? "Some rostered players fall back to the preseason board." : ""}</p></Card>}
    {info && !info.league_date && <Card className="p-4 text-[12px] text-ink-2"><strong>League day unavailable.</strong> The league timezone is not configured, so this page does not label any scheduled games or lineup as “today.” Use the <Link to="/weekly" className="text-accent underline">Weekly view</Link> for dated schedules.</Card>}
    {info?.league_date && <Card className="p-4 text-[12px]"><strong>League date: {info.league_date}</strong> <span className="text-ink-3">({info.league_timezone})</span>{day && data?.has_schedule ? <div className="mt-2">Scheduled roster games {day.games} · feasible starts {day.assignments.length} · usable {day.usable_points == null ? "unknown" : f1(day.usable_points)} FP{!day.exact && <span className="text-warn"> · incomplete eligibility, projection or game dates</span>}</div> : <p className="mt-1 text-ink-3">No confirmed lineup for this date in the current schedule. <Link to="/myteam" className="text-accent underline">Inspect the full week</Link>.</p>}</Card>}
    {data && !data.has_team && <Card className="p-4"><EmptyNote>{data.note} <Link to="/room" className="text-accent underline">Open Draft Room</Link></EmptyNote></Card>}
    {data?.has_team && <div className="grid gap-3 sm:grid-cols-3"><Card className="p-4"><div className="text-[11px] text-ink-3">My roster</div><strong className="mt-1 block text-xl">{rows.length} players</strong><Link to="/myteam" className="text-xs text-accent hover:underline">Open full roster →</Link></Card><Card className="p-4"><div className="text-[11px] text-ink-3">Known status flags</div><strong className="mt-1 block text-xl">{info?.status.source === "ros_snapshot" ? data.n_out ?? 0 : "unknown"}</strong><span className="text-xs text-ink-3">{info?.status.asof ? `snapshot ${info.status.asof}` : "no live status feed"}</span></Card><Card className="p-4"><div className="text-[11px] text-ink-3">Feasible week</div><strong className="mt-1 block text-xl">{data.has_schedule && data.lineup?.usable_points != null ? f1(data.lineup.usable_points) : "unknown"} FP</strong><span className="text-xs text-ink-3">{data.has_schedule ? `${data.week_name ?? `Week ${data.week}`} · ${data.start}–${data.end}` : "schedule unavailable"}</span></Card></div>}
    {data?.has_team && data.has_schedule && <Card className="p-4 text-[12px]"><h2 className="text-sm font-bold">This week’s lineup pressure</h2><div className="mt-2 grid gap-3 sm:grid-cols-2"><div><strong>Crowded dates</strong>{crowded.length ? <ul className="mt-1 space-y-1">{crowded.map(item => <li key={item.day}>{item.day}: {item.benched} scheduled game{item.benched === 1 ? "" : "s"} benched</li>)}</ul> : <p className="text-ink-3">No known benched games.</p>}</div><div><strong>Potential open capacity</strong>{openDays.length ? <ul className="mt-1 space-y-1">{openDays.map(item => <li key={item.day}>{item.day}: {item.starts}/{data.daily_slots} starting slots used</li>)}</ul> : <p className="text-ink-3">No open capacity on roster game dates.</p>}</div></div><p className="mt-2 text-ink-3">Open capacity is a date to inspect, not a feasible transaction. <Link to={openDays.length && data.week != null ? `/streaming?week=${data.week}&day=${openDays[0].day}` : "/streaming"} className="text-accent underline">Compare conditional single-move scenarios{openDays.length ? ` for ${openDays[0].day}` : ""}</Link>.</p></Card>}
    <Card className="p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-bold">Roster and watched-player signals</h2><Link to="/changes" className="text-xs text-accent hover:underline">All dated changes →</Link></div><p className="mt-1 text-[11px] text-ink-3">One item per player. Projection changes compare {history ? `${history.previous} to ${history.version}` : "two compatible ROS snapshots"}; status flags use the separate availability date above. These are recorded signals, not new notifications.</p>
      {historyState === "loading" && <p className="mt-2 text-xs text-ink-3">Loading change history…</p>}{historyState === "error" && <p className="mt-2 text-xs text-warn">Change history is unavailable. <Link to="/changes" className="underline">Open What Changed?</Link></p>}
      {alerts.length ? <div className="mt-3 space-y-2">{alerts.slice(0, 12).map(item => <div key={`${history?.version ?? "status"}:${item.id}`} className="rounded-lg border border-bdr p-3 text-[12px]"><div className="flex flex-wrap items-center gap-1.5"><Link to={`/players/${item.id}`} className="font-semibold text-accent hover:underline">{item.name}</Link>{item.onRoster && <Chip tone="accent">my roster</Chip>}{item.watched && <Chip>watched</Chip>}{item.status && <Chip tone="warn">status in snapshot</Chip>}</div>{item.status && <p className="mt-1 text-ink-2">Recorded availability: {item.status}</p>}{item.event && <p className="mt-1 text-ink-2">{item.event.kind.replace("-", " ")}{item.event.fptsDelta != null ? ` · ${signed(item.event.fptsDelta)} FP/G` : ""} · {item.event.explanation}</p>}</div>)}</div> : <EmptyNote>{historyState === "collecting" ? "A second compatible ROS snapshot is needed for watched changes." : "No recorded roster or watched-player signals in the available sources."}</EmptyNote>}
    </Card>
    <Card className="p-4"><h2 className="text-sm font-bold">Planning tasks</h2>{unfinished.length ? <div className="mt-2 grid gap-2 sm:grid-cols-2">{unfinished.map(item => <Link key={item.title} to={item.to} className="rounded-lg border border-bdr p-3 text-[12px] hover:bg-surface-2"><strong className="block text-accent">{item.title} →</strong><span className="text-ink-3">{item.detail}</span></Link>)}</div> : <p className="mt-2 text-xs text-ink-3">No setup gaps in the available sources. <Link to="/draft-plan" className="text-accent underline">Review your draft plan</Link>.</p>}</Card>
  </div>;
}
