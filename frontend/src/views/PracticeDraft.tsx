import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { choosePracticePlayer, createPracticeRun, MAX_RUNS, parsePracticeRuns, PRACTICE_KEY, practiceRounds, practiceSummary, practiceTeam, undoPracticePick, validatePracticeRun } from "../../../static/practice.mjs";
import type { PracticeRun } from "../../../static/practice.mjs";
import { useMeta } from "../App";
import { BoardResponse, useApi } from "../lib/api";
import { Card, EmptyNote, ErrorNote, Spinner } from "../components/ui";

function readRuns(): PracticeRun[] {
  try { return parsePracticeRuns(JSON.parse(localStorage.getItem(PRACTICE_KEY) || "[]")); }
  catch { return []; }
}

function saveFile(run: PracticeRun) {
  const blob = new Blob([JSON.stringify(run, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `fantasy-nba-practice-${run.snapshot.season}-${run.name.replace(/[^a-z0-9-]+/gi, "-").toLowerCase()}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function PracticeDraft() {
  const meta = useMeta();
  const board = useApi<BoardResponse>(meta ? `/api/board?target=${meta.current_target}&model=learned&stance=safe&analyst=true` : null);
  const [runs, setRuns] = useState<PracticeRun[]>(readRuns);
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("Practice run");
  const [teams, setTeams] = useState(12);
  const [position, setPosition] = useState(1);
  const [rule, setRule] = useState<"adp" | "board">("adp");
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const active = runs.find(run => run.id === selected) || runs[0];
  const roster = meta?.league.roster;
  const rounds = roster ? practiceRounds(roster) : 0;
  const teamOptions = [...new Set([8, 10, 12, 14, meta?.league.teams || 12])].sort((a, b) => a - b);
  const update = (next: PracticeRun[]) => {
    setRuns(next);
    try { localStorage.setItem(PRACTICE_KEY, JSON.stringify(next)); setMessage(""); }
    catch { setMessage("Browser storage is full or unavailable. Export the run to keep it."); }
  };
  const replace = (run: PracticeRun) => update(runs.map(saved => saved.id === run.id ? run : saved));
  const summary = active ? practiceSummary(active) : null;
  const picked = useMemo(() => new Set(active?.picks.map(pick => pick.playerId) || []), [active]);
  const available = active?.snapshot.players.filter(player => !picked.has(player.id) && player.name.toLowerCase().includes(query.toLowerCase())).sort((a, b) => a.rank - b.rank || a.id - b.id) || [];
  const draftLimit = active ? active.config.teams * practiceRounds(active.config.roster) : 0;
  const currentPick = active ? active.picks.length + 1 : 0;
  const yourTurn = Boolean(active && currentPick <= draftLimit && practiceTeam(currentPick, active.config.teams) === active.config.position);
  const sameBoard = active && active.snapshot.marketDate === (board.data?.market_date || null);

  return <div className="space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-lg font-bold">Practice My Draft</h1><p className="text-sm text-ink-2">Practice your picks while other teams follow a repeatable board or ADP rule.</p></div><div className="flex gap-2"><Link to="/draft-plan" className="rounded border border-bdr px-3 py-2 text-xs">My Draft Plan</Link><Link to="/room" className="rounded border border-bdr px-3 py-2 text-xs">Draft Room</Link></div></header>
    <p className="text-xs text-ink-2">Practice runs are browser-local and separate from the live Draft Room. Opponent picks are scripted scenarios, not player-availability probabilities or weekly win forecasts.</p>
    {board.error && <ErrorNote message={`Current board unavailable: ${board.error}. Saved runs still use their recorded snapshots.`} />}
    {message && <p role="status" className="text-xs text-down">{message}</p>}
    <Card className="p-4"><h2 className="mb-3 font-semibold">Start a run</h2><div className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-5">
      <label>Run name<input aria-label="Run name" maxLength={60} value={name} onChange={event => setName(event.target.value)} className="mt-1 block w-full rounded border border-bdr bg-surface p-2" /></label>
      <label>Teams<select aria-label="Practice teams" value={teams} onChange={event => { const next = Number(event.target.value); setTeams(next); setPosition(Math.min(position, next)); }} className="mt-1 block w-full rounded border border-bdr bg-surface p-2">{teamOptions.map(count => <option key={count}>{count}</option>)}</select></label>
      <label>Draft position<select aria-label="Practice draft position" value={position} onChange={event => setPosition(Number(event.target.value))} className="mt-1 block w-full rounded border border-bdr bg-surface p-2">{Array.from({ length: teams }, (_, index) => <option key={index + 1} value={index + 1}>{index + 1}</option>)}</select></label>
      <label>Opponents<select aria-label="Opponent rule" value={rule} onChange={event => setRule(event.target.value as "adp" | "board")} className="mt-1 block w-full rounded border border-bdr bg-surface p-2"><option value="adp">ADP order</option><option value="board">Board rank</option></select></label>
      <button disabled={!board.data || !roster || !rounds || runs.length >= MAX_RUNS} onClick={() => {
        try {
          const run = createPracticeRun({ name, teams, position, rule, roster: roster!, season: meta!.current_target, source: "local", ranking: "learned/safe season value", marketDate: board.data!.market_date, boardDate: new Date().toISOString(), rows: board.data!.rows });
          update([run, ...runs]); setSelected(run.id); setQuery("");
        } catch (error) { setMessage((error as Error).message); }
      }} className="self-end rounded bg-accent px-3 py-2 font-semibold text-accent-ink disabled:opacity-50">Start practice</button>
    </div><p className="mt-3 text-xs text-ink-3">Team count is a draft scenario and does not recalculate projections. {rounds ? `${rounds} draft rounds from the configured roster; injured-reserve slots are excluded.` : "Waiting for configured roster slots."} Up to {MAX_RUNS} runs can be saved. ADP ties use player ID; missing ADP follows board rank after priced players.</p></Card>
    {board.loading && <Spinner label="Loading current board…" />}
    {!active && <EmptyNote>No saved practice runs. Start one using the current board.</EmptyNote>}
    {active && summary && <>
      <Card className="p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold">{active.name}</h2><p className="mt-1 text-xs text-ink-3">{active.snapshot.season} · {active.snapshot.ranking} · Board captured {new Date(active.createdAt).toLocaleString()} · ADP {active.snapshot.marketDate || "unavailable"} · {active.config.teams} teams · slot {active.config.position} · {active.config.rule === "adp" ? "ADP opponents" : "Board-rank opponents"}</p><p className="mt-1 text-xs text-ink-2">{sameBoard ? "Using this run’s saved board snapshot." : "The current board has a different date or is unavailable. This run keeps its original projections and pick order."}</p></div><div className="flex flex-wrap gap-2"><button disabled={!active.checkpoints.length} onClick={() => replace(undoPracticePick(active))} className="rounded border border-bdr px-3 py-2 text-xs disabled:opacity-50">Undo my last pick</button><button onClick={() => saveFile(active)} className="rounded border border-bdr px-3 py-2 text-xs">Export run</button></div></div>
        <p className="mt-3 text-sm font-semibold">{yourTurn ? `Your pick #${currentPick} · round ${Math.ceil(currentPick / active.config.teams)}` : `Draft complete · ${active.picks.length} picks`}</p>
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4"><div>Projected season FP<strong className="block text-lg">{Math.round(summary.seasonFp)}</strong></div><div>Feasible starter FP/G<strong className="block text-lg">{summary.starterFpg.toFixed(1)}</strong></div><div>Starter spots open<strong className="block text-lg">{summary.openStarters}</strong></div><div>Depth outside starters<strong className="block text-lg">{summary.depth}</strong></div></div>
        <p className="mt-2 text-xs text-ink-3">Positions: {Object.entries(summary.positions).map(([slot, count]) => `${slot} ${count}`).join(" · ")}. {summary.unknownEligibility ? `${summary.unknownEligibility} player(s) have unknown eligibility; only UTIL can hold them here. ` : ""}{summary.unknownSeasonTotal ? `${summary.unknownSeasonTotal} player(s) lack season totals; the displayed sum excludes them.` : ""}</p>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2"><Card className="p-4"><h2 className="font-semibold">Your available choices</h2><input aria-label="Search practice players" placeholder="Search saved board…" value={query} onChange={event => setQuery(event.target.value)} className="mt-3 w-full rounded border border-bdr bg-surface p-2 text-sm" /><div className="mt-3 max-h-[510px] overflow-y-auto">{available.slice(0, 100).map(player => <div key={player.id} className="flex items-center justify-between gap-2 border-b border-bdr py-2 text-xs"><div className="min-w-0"><strong>{player.name}</strong><span className="ml-2 text-ink-3">#{player.rank} · {player.fptsPg?.toFixed(1) ?? "—"} FP/G · ADP {player.adp ?? "—"}</span></div><button disabled={!yourTurn} onClick={() => { try { replace(choosePracticePlayer(active, player.id)); } catch (error) { setMessage((error as Error).message); } }} className="rounded border border-bdr px-2 py-1 disabled:opacity-40">Pick</button></div>)}{!available.length && <p className="text-xs text-ink-3">No matching available players.</p>}</div></Card>
      <Card className="p-4"><h2 className="font-semibold">Pick history</h2><div className="mt-3 max-h-[565px] space-y-2 overflow-y-auto text-xs">{active.picks.slice().reverse().map((pick, index) => { const player = active.snapshot.players.find(row => row.id === pick.playerId); return <div key={index} className={`flex justify-between gap-3 border-b border-bdr py-1 ${pick.team === active.config.position ? "font-bold text-accent" : "text-ink-2"}`}><span>#{active.picks.length - index} {player?.name || `Player ${pick.playerId}`}</span><span>Team {pick.team}{pick.team === active.config.position ? " · you" : ""}</span></div>; })}</div></Card></div>
    </>}
    <Card className="p-4"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">Compare saved runs</h2><label className="rounded border border-bdr px-3 py-2 text-xs">Import run<input type="file" accept=".json,application/json" className="sr-only" aria-label="Import practice run" onChange={async event => {
      const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
      try {
        if (file.size > 2 * 1024 * 1024) throw new Error("Practice files must be smaller than 2 MB.");
        const run = validatePracticeRun(JSON.parse(await file.text()));
        const existing = runs.find(saved => saved.id === run.id);
        if (!existing && runs.length >= MAX_RUNS) throw new Error("Delete a saved run before importing another.");
        update(existing ? runs.map(saved => saved.id === run.id ? run : saved) : [run, ...runs]); setSelected(run.id);
      } catch (error) { setMessage((error as Error).message); }
    }} /></label></div>
      <div className="mt-3 space-y-2">{runs.map(run => { const view = practiceSummary(run); return <div key={run.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-bdr p-3 text-xs"><div><strong>{run.name}</strong><p className="text-ink-3">{run.snapshot.marketDate || "No ADP date"} · {run.config.teams} teams · slot {run.config.position} · {view.own.length} of {practiceRounds(run.config.roster)} picks · {view.starters} starters at {view.starterFpg.toFixed(1)} FP/G · {view.depth} depth · {Math.round(view.seasonFp)} season FP{view.unknownSeasonTotal ? ` (${view.unknownSeasonTotal} totals missing)` : ""}</p><p className="text-ink-3">Position mix: {Object.entries(view.positions).map(([slot, count]) => `${slot} ${count}`).join(" · ")}{view.unknownEligibility ? ` · ${view.unknownEligibility} eligibility unknown` : ""}</p></div><div className="flex gap-2"><button onClick={() => { setSelected(run.id); setQuery(""); }} className="rounded border border-bdr px-2 py-1">Open</button><button onClick={() => { if (!window.confirm(`Delete practice run “${run.name}”?`)) return; update(runs.filter(saved => saved.id !== run.id)); if (selected === run.id) setSelected(""); }} className="rounded border border-bdr px-2 py-1">Delete</button></div></div>; })}</div>
    </Card>
  </div>;
}
