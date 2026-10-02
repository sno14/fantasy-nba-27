import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useApi } from "../lib/api";
import { f1, f2, signed } from "../lib/format";
import { Card, EmptyNote, ErrorNote, Field, SearchInput, Select, Spinner } from "../components/ui";

interface RotationPlayer {
  id: number; name: string; team: string; rank: number; positions: string[];
  modelMpg: number | null; mpg: number | null; mpgDelta: number | null;
  modelFpg: number | null; fpg: number | null; fpgDelta: number | null;
  modelFpPerMinute: number | null; fpPerMinute: number | null;
  analystAction: string | null; analystDate: string | null; analystCategory: string | null;
  previewStatedMpg: string | null; previewBudgetMpg: number | null;
  rosMpg: number | null; rosFpg: number | null; status: string | null; redistMpg: number | null;
}
interface Preview { date: string; hasClosedBudget: boolean; budgetMinutes: number | null; matchedPlayers: number; ledgerPlayers: number; note: string }
interface RotationTeam { team: string; players: RotationPlayer[]; count: number; modelMinutes: number; modelMissing: number; boardMinutes: number; boardMissing: number; gapTo240: number; preview: Preview | null }
interface RotationResponse { target: string; model: string; stance: string; rankedBy: string; referenceMinutes: number; unassignedPlayers: number; rosDate: string | null; hasRedistribution: boolean; teams: RotationTeam[] }

function metric(label: string, value: string, note: string) {
  return <Card key={label} className="min-w-0 p-3"><div className="text-[11px] font-semibold uppercase tracking-wide text-ink-3">{label}</div><strong className="mt-1 block text-lg">{value}</strong><p className="mt-1 text-xs text-ink-3">{note}</p></Card>;
}

export default function Rotation() {
  const { data, error, loading, reload } = useApi<RotationResponse>("/api/rotation");
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [adjustedOnly, setAdjustedOnly] = useState(false);
  const requestedTeam = params.get("team") ?? "";
  const selected = data?.teams.find(item => item.team === requestedTeam) ?? data?.teams[0];
  const players = useMemo(() => {
    if (!selected) return [];
    return selected.players.filter(item => !adjustedOnly || (item.analystAction && item.analystAction !== "none"))
      .filter(item => !query.trim() || `${item.name} ${item.positions.join(" ")}`.toLowerCase().includes(query.trim().toLowerCase()));
  }, [selected, adjustedOnly, query]);

  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-xl font-bold">Rotation & Opportunity</h1><p className="mt-1 max-w-3xl text-sm text-ink-2">Compare the current learned/safe Board A model with approved Board B actions. Team assignments follow the current board cache; its transaction map may lag new moves.</p></div>
      <button onClick={reload} className="rounded-lg border border-bdr px-3 py-2 text-xs font-semibold text-ink-2 hover:bg-surface-2">Refresh</button>
    </div>
    {error && <ErrorNote message={error} />}
    {loading && <Spinner label="Loading team rotations…" />}
    {data && !data.teams.length && <Card><EmptyNote>No team-assigned players are available in the current board.</EmptyNote></Card>}
    {selected && <>
      <Card className="flex flex-wrap items-end gap-3 p-4">
        <Field label="NBA team"><Select value={selected.team} onChange={team => setParams({ team })} options={data!.teams.map(item => ({ value: item.team, label: item.team }))} /></Field>
        <Field label="Find player"><SearchInput value={query} onChange={setQuery} placeholder="Name or position…" className="w-48" /></Field>
        <label className="flex items-center gap-2 pb-1 text-xs text-ink-2"><input type="checkbox" checked={adjustedOnly} onChange={event => setAdjustedOnly(event.target.checked)} /> Approved actions only</label>
        <p className="text-xs text-ink-3">{selected.count} assigned players · {data!.unassignedPlayers} with no team assignment · local rank means {data!.rankedBy}</p>
      </Card>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {metric("Board B minutes", `${f1(selected.boardMinutes)} / 240`, `${selected.boardMissing} missing MPG · known subtotal`)}
        {metric("Board A minutes", `${f1(selected.modelMinutes)} / 240`, `${selected.modelMissing} missing MPG · same Board B roster IDs`)}
        {metric("Difference from 240", signed(selected.gapTo240), "Diagnostic only; no automatic reconciliation")}
        {metric("Dated preview", selected.preview?.hasClosedBudget ? "240 allocated" : "No closed budget", selected.preview ? `${selected.preview.date} · ${selected.preview.matchedPlayers}/${selected.preview.ledgerPlayers} names matched` : "No team-preview ledger available")}
      </div>
      <Card className="p-4 text-xs leading-5 text-ink-2">
        <strong className="text-ink">How to read the minutes</strong>
        <p>Board totals add each player's conditional projected MPG across the full roster, so they can exceed 240. Missing MPG stays missing. The 240-minute line is a regulation reference, not a forced team allocation.</p>
        <p className="mt-1">{selected.preview?.note ?? "No dated preview is available for this team."} {selected.preview ? `Preview date: ${selected.preview.date}; it is not today's board.` : ""}</p>
        <p className="mt-1">FP/min is derived from FP/G ÷ MPG. It separates a minutes change from a rate change without assigning a cause. Cached eligible-position overlap shows possible roster competition, not a depth-chart order.</p>
        <p className="mt-1">{data!.rosDate ? `Latest ROS availability snapshot: ${data!.rosDate}. ${data!.hasRedistribution ? "Positive redistribution MPG is the model's documented lift from an OUT teammate, prorated over the remaining season." : "This snapshot has no redistribution field."}` : "No nightly ROS availability snapshot exists yet; availability and redistribution are unknown here."}</p>
      </Card>
      <p className="text-xs text-ink-3">{players.length} players shown, ordered by Board B MPG. Preview statements and allocations never change the board values below.</p>
      {players.length === 0 && <Card><EmptyNote>No players match these filters.</EmptyNote></Card>}
      <div className="grid gap-3 xl:grid-cols-2">{players.map(player => {
        const peers = player.positions.length ? selected.players.filter(other => other.id !== player.id && other.positions.some(position => player.positions.includes(position))).slice(0, 3) : [];
        return <Card key={player.id} className="min-w-0 p-4">
          <div className="flex flex-wrap justify-between gap-2"><div><Link to={`/players/${player.id}`} className="font-semibold text-accent hover:underline">{player.name}</Link><p className="text-xs text-ink-3">#{player.rank} safe season-value rank · {player.positions.length ? player.positions.join("/") : "eligibility unknown"}</p></div><span className="text-xs text-ink-3">{player.analystDate ? `Action ${player.analystDate}` : "No dated action"}</span></div>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {[["MPG · A → B", f1(player.modelMpg), f1(player.mpg), player.mpgDelta], ["FP/G · A → B", f1(player.modelFpg), f1(player.fpg), player.fpgDelta], ["FP/min · A → B", f2(player.modelFpPerMinute), f2(player.fpPerMinute), null]].map(([label, oldValue, newValue, change]) =>
              <div key={String(label)} className="min-w-0 rounded-lg border border-bdr p-2 text-xs"><span className="block text-ink-3">{label}</span><strong className="mt-1 block break-words">{oldValue} → {newValue}</strong>{typeof change === "number" && <span className="text-accent">{signed(change)}</span>}</div>)}
          </div>
          <div className="mt-3 space-y-1 text-xs text-ink-2">
            <p><b>Approved action:</b> {player.analystAction && player.analystAction !== "none" ? `${player.analystAction}${player.analystCategory ? ` · ${player.analystCategory}` : ""}` : "none recorded"}</p>
            {selected.preview && <p><b>Dated preview:</b> {player.previewStatedMpg ? `stated MPG “${player.previewStatedMpg}”` : "no quoted MPG"}{player.previewBudgetMpg != null ? ` · separate ${f1(player.previewBudgetMpg)}-MPG allocation` : ""} · {selected.preview.date}</p>}
            {data!.rosDate && <p><b>ROS {data!.rosDate}:</b> {player.rosMpg == null ? "player absent or MPG unknown" : `${f1(player.rosMpg)} MPG · ${f1(player.rosFpg)} FP/G`}{player.status ? ` · status ${player.status}` : ""}{data!.hasRedistribution && player.redistMpg != null && player.redistMpg > 0 ? ` · +${f1(player.redistMpg)} redistributed MPG` : ""}</p>}
            <p><b>Eligible-position peers:</b> {player.positions.length ? (peers.length ? peers.map(item => `${item.name} ${f1(item.mpg)} MPG`).join(" · ") : "none verified in the cached map") : "unknown without cached eligibility"}</p>
          </div>
        </Card>;
      })}</div>
    </>}
  </div>;
}
