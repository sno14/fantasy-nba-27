import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { compareSnapshots, validateChangeSnapshot, type ChangeEvent, type ChangeSnapshot } from "../../../static/changes.mjs";
import { useDraftTargets } from "../lib/draftRadar";
import { get } from "../lib/api";
import { Card, EmptyNote, ErrorNote, Spinner } from "../components/ui";

interface Version { version: string; asof: string; season: string; rankedBy: string; scoringKey: string; source: string }
interface Versions { schema: number; versions: Version[]; legacyCount: number }
type View = "all" | "watched" | "team" | "since";
const VISIT_KEY = "fantasy-nba-local-changes-last-seen-v1";
function storedVisit(): string | null { try { return localStorage.getItem(VISIT_KEY); } catch { return null; } }
function number(value: number | null, places = 1) { return value == null ? "—" : value.toFixed(places); }
function delta(value: number | null, unit = "") { return value == null ? "" : `${value > 0 ? "+" : ""}${number(value)}${unit}`; }

export default function Changes() {
  const { targets } = useDraftTargets();
  const [versions, setVersions] = useState<Version[]>([]);
  const [legacyCount, setLegacyCount] = useState(0);
  const [view, setView] = useState<View>("all");
  const [team, setTeam] = useState("All");
  const [baseline, setBaseline] = useState("");
  const [visit] = useState(storedVisit);
  const [pair, setPair] = useState<{ latest: ChangeSnapshot; previous: ChangeSnapshot; events: ChangeEvent[] } | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    get<Versions>("/api/changes/versions", true).then(data => {
      if (!live) return;
      if (data.schema !== 1 || !Array.isArray(data.versions)) throw new Error("Invalid ROS history manifest");
      setVersions(data.versions);
      setLegacyCount(data.legacyCount);
      setBusy(false);
    }).catch((cause: Error) => { if (live) { setError(cause.message); setBusy(false); } });
    return () => { live = false; };
  }, []);

  const latest = versions.at(-1);
  const compatible = useMemo(() => versions.slice(0, -1).filter(item => latest && item.season === latest.season && item.rankedBy === latest.rankedBy && item.scoringKey === latest.scoringKey && item.source === latest.source), [versions, latest]);
  const selected = view === "since" ? (visit === latest?.version ? latest : compatible.find(item => item.version === visit) ?? compatible.at(-1)) : compatible.find(item => item.version === baseline) ?? compatible.at(-1);

  useEffect(() => {
    if (!latest || !selected) { setPair(null); return; }
    let live = true;
    setBusy(true); setError("");
    Promise.all([get<ChangeSnapshot>(`/api/changes/version/${latest.version}`, true), get<ChangeSnapshot>(`/api/changes/version/${selected.version}`, true)])
      .then(([newValue, oldValue]) => {
        if (!live) return;
        const current = validateChangeSnapshot(newValue);
        const previous = validateChangeSnapshot(oldValue);
        const events = compareSnapshots(current, previous);
        setPair({ latest: current, previous, events });
        try { localStorage.setItem(VISIT_KEY, current.version); } catch { /* Comparison remains usable without storage. */ }
        setBusy(false);
      })
      .catch((cause: Error) => { if (live) { setPair(null); setError(cause.message); setBusy(false); } });
    return () => { live = false; };
  }, [latest?.version, selected?.version]);

  const teams = [...new Set((pair?.events ?? []).map(event => event.team).filter((item): item is string => !!item))].sort();
  const filtered = (pair?.events ?? []).filter(event => view !== "watched" || Boolean(targets[String(event.id)]))
    .filter(event => view !== "team" || team === "All" || event.team === team);
  const count = (kind: ChangeEvent["kind"]) => filtered.filter(event => event.kind === kind).length;

  return <div className="space-y-4">
    <p className="text-sm text-ink-2">Dated ROS projection changes. <Link to="/trends" className="text-accent underline">See Trends</Link> for the rolling FP/G view.</p>
    <Card>
      <div className="grid gap-3 p-4 sm:grid-cols-3">
        <label className="text-xs text-ink-2">View<select aria-label="Change view" className="mt-1 block w-full rounded border border-bdr bg-surface-2 p-2 text-ink" value={view} onChange={event => setView(event.target.value as View)}><option value="all">All changes</option><option value="watched">Watched players</option><option value="team">Selected team</option><option value="since">Since last visit</option></select></label>
        <label className="text-xs text-ink-2">NBA team<select aria-label="Change team" className="mt-1 block w-full rounded border border-bdr bg-surface-2 p-2 text-ink" value={teams.includes(team) ? team : "All"} onChange={event => setTeam(event.target.value)}><option value="All">All teams</option>{teams.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className="text-xs text-ink-2">Compare from<select aria-label="Change baseline" className="mt-1 block w-full rounded border border-bdr bg-surface-2 p-2 text-ink" value={selected?.version ?? ""} disabled={view === "since" || !compatible.length} onChange={event => setBaseline(event.target.value)}>{selected === latest && latest && <option value={latest.version}>{latest.asof}</option>}{compatible.map(item => <option key={item.version} value={item.version}>{item.asof}</option>)}</select></label>
      </div>
    </Card>
    {error && <ErrorNote message={error} />}
    {busy && <Spinner label="Loading ROS history…" />}
    {!busy && !error && !pair && <Card><EmptyNote>A comparison baseline is being collected. Two nightly ROS snapshots with recorded scoring and ranking settings are needed.{legacyCount ? ` ${legacyCount} older snapshot(s) lack that provenance and remain available in Trends.` : ""}</EmptyNote></Card>}
    {pair && !busy && <>
      <p className="text-xs text-ink-3">{pair.previous.asof} → {pair.latest.asof} · {pair.latest.rankedBy} · {pair.events.length} changed players. Rank movement alone does not imply a role change.</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{[["Changed players", filtered.length], ["New / removed", `${count("added")} / ${count("removed")}`], ["Rank only", count("rank-only")], ["FP/G changed", filtered.filter(event => event.fptsDelta !== null && event.fptsDelta !== 0).length]].map(([label, value]) => <Card key={label}><div className="p-3"><div className="text-xs text-ink-3">{label}</div><strong>{value}</strong></div></Card>)}</div>
      {filtered.length === 0 && <Card><EmptyNote>No changes match this view between these snapshots.</EmptyNote></Card>}
      <div className="space-y-2">{filtered.map(event => <Card key={event.id}><div className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><Link to={`/players/${event.id}`} className="font-semibold text-accent hover:underline">{event.name}</Link><div className="text-xs text-ink-3">{event.team ?? "Team unknown"} · {event.kind.replace("-", " ")}</div></div><strong className="text-accent">{delta(event.fptsDelta, " FP/G")}</strong></div>
        <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">{[["FP/G", number(event.before?.fpts_pg ?? null), number(event.after?.fpts_pg ?? null), delta(event.fptsDelta)], ["MPG", number(event.before?.mpg ?? null), number(event.after?.mpg ?? null), delta(event.mpgDelta)], ["Rank", number(event.before?.rank ?? null, 0), number(event.after?.rank ?? null, 0), event.rankDelta == null ? "" : `${event.rankDelta > 0 ? "+" : ""}${event.rankDelta} places`]].map(([label, oldValue, newValue, change]) => <div key={label} className="rounded border border-bdr p-2"><div className="text-ink-3">{label}</div><strong>{oldValue} → {newValue}</strong><div className="text-accent">{change}</div></div>)}</div>
        <p className="mt-3 text-xs text-ink-2">{event.explanation}</p>
        {(event.before?.analyst_action !== event.after?.analyst_action || event.before?.analyst_date !== event.after?.analyst_date) && <p className="mt-1 text-xs text-ink-3">Recorded analyst action: {event.before?.analyst_action ?? "none"} → {event.after?.analyst_action ?? "none"} · date {event.before?.analyst_date ?? "—"} → {event.after?.analyst_date ?? "—"}</p>}
      </div></Card>)}</div>
    </>}
  </div>;
}
