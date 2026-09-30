import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { normalizeTarget, snakePicks } from "../../../static/workspace.mjs";
import { useMeta } from "../App";
import { BoardResponse, DraftStateResponse, get, useApi } from "../lib/api";
import { DraftTarget, useDraftTargets } from "../lib/draftRadar";
import { useStoredPreferences } from "../lib/preferences";
import { Card, Chip, EmptyNote, ErrorNote, Spinner } from "../components/ui";
import { WatchlistBackup } from "../components/Portability";

type Position = { slot: number };
function validatePosition(value: unknown): Position {
  const slot = (value as Position | null)?.slot;
  return { slot: typeof slot === "number" && Number.isInteger(slot) && slot >= 1 && slot <= 30 ? slot : 1 };
}

function verifiedOrder(st: DraftStateResponse | null): number[] | null {
  if (!st || st.synthetic_teams || !st.settings || st.settings.order_is_placeholder || !st.my_team_id) return null;
  const order = st.settings.pick_order;
  if (!Array.isArray(order) || order.length !== st.settings.size ||
      order.length !== st.team_ids.length || new Set(order).size !== order.length ||
      !order.includes(st.my_team_id) || !order.every(id => st.team_ids.includes(id))) return null;
  return order;
}

function TargetEditor({ target, onSave, onCancel }: { target: DraftTarget; onSave: (value: DraftTarget) => void; onCancel: () => void }) {
  const [value, setValue] = useState(target);
  const [error, setError] = useState("");
  const update = (patch: Partial<DraftTarget>) => setValue(current => ({ ...current, ...patch }));
  const number = (raw: string) => raw ? Number(raw) : null;
  return <form className="mt-3 grid gap-3 rounded-lg border border-bdr bg-surface-2 p-3 text-xs sm:grid-cols-2" onSubmit={event => {
    event.preventDefault();
    try { onSave(normalizeTarget(value)); } catch (cause) { setError((cause as Error).message); }
  }}>
    <label>Take by overall pick<input aria-label="Take by overall pick" type="number" min="1" max="10000" step="1" value={value.takeBy ?? ""} onChange={event => update({ takeBy: number(event.target.value) })} className="mt-1 block w-full rounded border border-bdr bg-surface p-2" /></label>
    <label>Preferred round<input aria-label="Preferred round" type="number" min="1" max="100" step="1" value={value.preferredRound ?? ""} onChange={event => update({ preferredRound: number(event.target.value) })} className="mt-1 block w-full rounded border border-bdr bg-surface p-2" /></label>
    <label>Backup group<input aria-label="Backup group" maxLength={50} value={value.backupGroup} onChange={event => update({ backupGroup: event.target.value })} className="mt-1 block w-full rounded border border-bdr bg-surface p-2" /></label>
    <label>Priority order<input aria-label="Priority order" type="number" min="1" max="1000" step="1" value={value.priority ?? ""} onChange={event => update({ priority: number(event.target.value) })} className="mt-1 block w-full rounded border border-bdr bg-surface p-2" /></label>
    <label>Status<select aria-label="Target status" value={value.status} onChange={event => update({ status: event.target.value as DraftTarget["status"] })} className="mt-1 block w-full rounded border border-bdr bg-surface p-2"><option value="active">Active</option><option value="hold">On hold</option></select></label>
    <label className="sm:col-span-2">Private note<textarea aria-label="Private note" maxLength={10000} rows={3} value={value.note} onChange={event => update({ note: event.target.value })} className="mt-1 block w-full rounded border border-bdr bg-surface p-2" /></label>
    {error && <p role="alert" className="text-down sm:col-span-2">{error}</p>}
    <div className="flex gap-2 sm:col-span-2"><button className="rounded bg-accent px-3 py-2 font-semibold text-accent-ink">Save target</button><button type="button" className="rounded border border-bdr px-3 py-2" onClick={onCancel}>Cancel</button></div>
  </form>;
}

export default function DraftPlan() {
  const meta = useMeta();
  const nav = useNavigate();
  const { targets, save, storageUnavailable } = useDraftTargets();
  const [position, setPosition] = useStoredPreferences("fantasy-nba-plan-position-v1", { slot: 1 }, validatePosition);
  const [st, setSt] = useState<DraftStateResponse | null>(null);
  const [draftError, setDraftError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const board = useApi<BoardResponse>(meta ? `/api/board?target=${meta.current_target}&model=learned&stance=safe&analyst=true` : null);
  const load = useCallback(() => { void get<DraftStateResponse>("/api/draft/state?top=1", true).then(value => { setSt(value); setDraftError(""); }).catch(cause => setDraftError((cause as Error).message)); }, []);
  useEffect(() => { load(); window.addEventListener("focus", load); return () => window.removeEventListener("focus", load); }, [load]);
  useEffect(() => { if (st?.source !== "espn") return; const timer = setInterval(load, 5000); return () => clearInterval(timer); }, [st?.source, load]);

  const nTeams = st?.team_ids.length || meta?.league.teams || 12;
  const realOrder = verifiedOrder(st);
  const chosenSlot = Math.min(position.slot, nTeams);
  const order = realOrder || Array.from({ length: nTeams }, (_, index) => index + 1);
  const teamId = realOrder ? st!.my_team_id : chosenSlot;
  const fromOverall = (st?.n_picks || 0) + 1;
  const rounds = st?.roster_slots ? Object.entries(st.roster_slots).filter(([slot]) => slot.toUpperCase() !== "IR").reduce((sum, [, count]) => sum + count, 0) : 0;
  const picks = snakePicks(order, teamId, fromOverall, Math.min(30, rounds));
  const picked = new Map(st?.picks.map(pick => [pick.player_id, pick.team_id]) || []);
  const rows = useMemo(() => new Map((board.data?.rows || []).map(row => [row.PLAYER_ID, row])), [board.data]);
  const tierRemaining = new Map<number, number>();
  for (const row of board.data?.rows || []) if (row.tier != null && !picked.has(row.PLAYER_ID)) tierRemaining.set(row.tier, (tierRemaining.get(row.tier) || 0) + 1);
  const items = Object.entries(targets).map(([id, target]) => ({ id, target, row: rows.get(Number(id)), owner: picked.get(Number(id)) }));
  const active = items.filter(item => item.target.status === "active" && !item.owner && item.row);
  const overdue = active.filter(item => item.target.takeBy != null && item.target.takeBy < fromOverall);
  const me = st?.rosters.find(roster => roster.team_id === st.my_team_id);
  const openSlots = me && st?.has_positions ? Object.entries(me.unfilled).filter(([, count]) => count > 0) : [];
  const groups = new Map<number | "Unassigned", typeof items>();
  for (const item of items) {
    const rawRound = item.target.preferredRound ?? (item.target.takeBy ? Math.ceil(item.target.takeBy / nTeams) : null);
    const round = rawRound && rawRound <= rounds ? rawRound : "Unassigned";
    groups.set(round, [...(groups.get(round) || []), item]);
  }
  const groupList = [...groups].sort(([a], [b]) => a === "Unassigned" ? 1 : b === "Unassigned" ? -1 : a - b);

  if (!meta) return <Spinner label="Loading draft plan…" />;
  return <div className="space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-lg font-bold">My Draft Plan</h1><p className="text-sm text-ink-2">Organize targets against your picks. Availability follows the existing Draft Room.</p></div><div className="flex gap-2"><Link to="/" className="rounded border border-bdr px-3 py-2 text-xs">Draft Board</Link><Link to="/room" className="rounded bg-accent px-3 py-2 text-xs font-semibold text-accent-ink">Open Draft Room</Link></div></header>
    {draftError && <ErrorNote message={`Draft state unavailable: ${draftError}. Target editing is still available.`} />}
    {board.error && <ErrorNote message={`Board unavailable: ${board.error}`} />}
    <Card className="flex flex-wrap items-end gap-4 p-4 text-sm">
      <div><strong className="block">Draft position</strong>{realOrder ? <span className="text-ink-2">Verified order · Team {st!.my_team_id} · slot {realOrder.indexOf(st!.my_team_id) + 1} of {nTeams}</span> : <label className="mt-1 block text-xs">Illustrative slot <select aria-label="Illustrative draft position" value={chosenSlot} onChange={event => setPosition({ slot: Number(event.target.value) })} className="ml-2 rounded border border-bdr bg-surface p-2">{Array.from({ length: nTeams }, (_, index) => <option key={index + 1} value={index + 1}>{index + 1} of {nTeams}</option>)}</select></label>}</div>
      <p className="min-w-[210px] flex-1 text-xs text-ink-2">{realOrder ? "ESPN pick order was verified when saved. Recheck it in the Draft Room on draft day." : "Live draft order is unverified or unavailable. These are scenario picks, not a claim about your actual position."}</p>
      {picks.length > 0 && <div className="text-xs"><strong className="block">Next scenario picks</strong>{picks.slice(0, 5).map(pick => `#${pick.overall} (R${pick.round})`).join(" · ")}</div>}
    </Card>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {[["Next known pick", realOrder && picks.length ? `#${picks[0].overall}` : "—"], ["Remaining targets", String(active.length)], ["Past take-by pick", String(overdue.length)], ["Open starters", me && st?.has_positions ? String(openSlots.reduce((sum, [, count]) => sum + count, 0)) : "—"]].map(([label, value]) => <Card key={label} className="p-3"><small className="text-ink-3">{label}</small><strong className="mt-1 block text-lg">{value}</strong></Card>)}
    </div>
    <p className="text-xs text-ink-2">{picks.length ? `Next ${realOrder ? "verified" : "illustrative"} picks: ${picks.slice(0, 5).map(pick => `#${pick.overall} in round ${pick.round}`).join(", ")}. ` : "No upcoming picks in this scenario. "}{me && st?.has_positions ? `Open starters: ${openSlots.map(([slot, count]) => `${slot} ${count}`).join(" · ") || "none"}.` : "Open starting positions require your team and confirmed eligibility."} ADP vintage: {board.data?.market_date || "unavailable"}. No player-availability probability is implied.</p>
    {board.data && <WatchlistBackup season={meta.current_target} knownIds={board.data.rows.map(row => row.PLAYER_ID)} />}
    {storageUnavailable && <p role="status" className="text-xs text-ink-2">Browser storage is unavailable. Export a backup to keep this session’s plan.</p>}
    {board.loading && <Spinner label="Loading targets…" />}
    {!board.loading && !items.length && <EmptyNote>No targets yet. Star players on the <button className="font-semibold text-accent" onClick={() => nav("/")}>Draft Board</button> to build your plan.</EmptyNote>}
    {groupList.map(([round, list]) => {
      const upcoming = typeof round === "number" ? picks.find(pick => pick.round === round) : null;
      const sorted = [...list].sort((a, b) => a.target.backupGroup.localeCompare(b.target.backupGroup) || (a.target.priority ?? 1001) - (b.target.priority ?? 1001) || (a.row?.rank ?? 9999) - (b.row?.rank ?? 9999));
      return <Card key={round} className="overflow-hidden"><header className="flex flex-wrap items-center justify-between gap-2 border-b border-bdr px-4 py-3"><h2 className="font-bold">{round === "Unassigned" ? "Unassigned targets" : `Round ${round}`}</h2><span className="text-xs text-ink-3">{upcoming ? `Your ${realOrder ? "verified" : "illustrative"} pick #${upcoming.overall}` : round === "Unassigned" ? "Choose a preferred round" : "Pick passed or not yours"}</span></header>
        {sorted.map(({ id, target, row, owner }) => {
          let availability = owner ? owner === st?.my_team_id && st.my_team_id !== 0 ? "Drafted by you" : `Drafted by Team ${owner}` : !row ? "Absent from current board" : target.status === "hold" ? "On hold" : target.takeBy != null && target.takeBy < fromOverall ? "Past take-by pick" : target.takeBy === fromOverall ? "Due now" : "Available";
          const conflict = !owner && upcoming && target.takeBy != null && upcoming.overall > target.takeBy;
          if (conflict && availability === "Available") availability = "Round pick after take-by";
          return <div key={id} className="border-b border-bdr px-4 py-3"><div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><button className="font-semibold hover:text-accent" onClick={() => row && nav(`/players/${id}`)}>{row?.PLAYER_NAME || `Player ID ${id}`}</button><Chip tone={owner ? "neutral" : availability === "Available" ? "up" : "warn"}>{availability}</Chip></div><p className="mt-1 text-xs text-ink-3">{row ? `Board #${row.rank} · ${row.fpts_pg.toFixed(1)} FP/G · ADP ${row.adp == null ? "—" : Math.round(row.adp)}${row.tier != null ? ` · Tier ${row.tier} (${tierRemaining.get(row.tier) || 0} remain)` : ""}` : "No current projection"}{target.backupGroup ? ` · Backup: ${target.backupGroup}` : ""}{target.priority ? ` · Priority ${target.priority}` : ""}{target.takeBy ? ` · Take by #${target.takeBy}` : ""}</p>{target.note && <p className="mt-2 whitespace-pre-wrap break-words text-xs text-ink-2">{target.note}</p>}</div><div className="flex gap-2"><button className="rounded border border-bdr px-3 py-2 text-xs" onClick={() => setEditing(editing === id ? null : id)}>Edit plan</button><button className="rounded border border-bdr px-3 py-2 text-xs" onClick={() => { const next = { ...targets }; delete next[id]; save(next); }}>Remove</button></div></div>{editing === id && <TargetEditor key={id} target={target} onSave={nextTarget => { save({ ...targets, [id]: nextTarget }); setEditing(null); }} onCancel={() => setEditing(null)} />}</div>;
        })}</Card>;
    })}
  </div>;
}
