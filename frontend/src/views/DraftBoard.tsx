import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useCompare, useMeta } from "../App";
import { BoardResponse, BoardRow, useApi } from "../lib/api";
import { f0, f1, parseAction, signed } from "../lib/format";
import { Column, DataTable, sortTableRows, TableSort } from "../components/DataTable";
import { BoardCards } from "../components/BoardCards";
import { RangePlot, RangeStrip, RiskMeter } from "../components/charts";
import { Card, Chip, EmptyNote, ErrorNote, Field, SearchInput, Segmented, Select, Spinner, Toggle } from "../components/ui";
import { radarName, radarTone, targetTitle, useDraftTargets } from "../lib/draftRadar";
import { useStoredPreferences } from "../lib/preferences";
import { CopyLink, WatchlistBackup } from "../components/Portability";

interface BoardPreferences {
  target: string; model: string; stance: string; analyst: boolean;
  team: string; q: string; topN: number; showChart: boolean; radarFilter: string;
  preset: string; layout: string; sort: TableSort;
}
const DEFAULTS: BoardPreferences = {
  target: "2026-27", model: "learned", stance: "safe", analyst: true,
  team: "All", q: "", topN: 100, showChart: false, radarFilter: "All",
  preset: "draft", layout: "auto", sort: { key: "rank", dir: 1 },
};
const PRESETS: Record<string, string[]> = {
  draft: ["rank", "player", "positions", "fpts_pg", "adp", "radar"],
  performance: ["rank", "player", "positions", "fpts_pg", "previous_fpts_pg", "fpts_pg_change", "mpg", "gp"],
  risk: ["rank", "player", "fpts_pg", "gp", "range", "median", "risk"],
};
const SORT_KEYS = ["rank", "player", "positions", "age", "gp", "mpg", "fpts_pg", "previous_fpts_pg", "fpts_pg_change", "analyst", "median", "risk", "vor", "adp", "radar", "actual_rank", "act_fpg", "act_total"];

function validatePreferences(value: unknown): BoardPreferences {
  if (!value || typeof value !== "object" || Array.isArray(value)) return DEFAULTS;
  const saved = value as Record<string, unknown>;
  const next = { ...DEFAULTS };
  for (const key of ["target", "model", "stance", "team", "q"] as const) if (typeof saved[key] === "string") next[key] = saved[key];
  for (const key of ["analyst", "showChart"] as const) if (typeof saved[key] === "boolean") next[key] = saved[key];
  if ([50, 100, 150, 200, 300].includes(saved.topN as number)) next.topN = saved.topN as number;
  if (["All", "Targets", "Fades", "Watchlist"].includes(saved.radarFilter as string)) next.radarFilter = saved.radarFilter as string;
  if (["draft", "performance", "risk", "full"].includes(saved.preset as string)) next.preset = saved.preset as string;
  if (["auto", "table", "cards"].includes(saved.layout as string)) next.layout = saved.layout as string;
  const sort = saved.sort as Partial<TableSort> | null;
  if (sort && SORT_KEYS.includes(sort.key || "") && (sort.dir === 1 || sort.dir === -1)) next.sort = { key: sort.key!, dir: sort.dir };
  return next;
}

function boardQuery(prefs: BoardPreferences) {
  return new URLSearchParams(Object.entries({ ...prefs, sort: prefs.sort.key, direction: prefs.sort.dir }).map(([key, value]) => [key, String(value)])).toString();
}

function readBoardQuery(search: string, fallback: BoardPreferences) {
  const params = new URLSearchParams(search);
  const next = { ...fallback };
  const invalid: string[] = [];
  for (const key of Object.keys(DEFAULTS) as (keyof BoardPreferences)[]) {
    const raw = params.get(key); if (raw === null || key === "sort") continue;
    let value: unknown = raw;
    if (["analyst", "showChart"].includes(key)) value = raw === "true" ? true : raw === "false" ? false : undefined;
    if (key === "topN") value = Number(raw);
    const validated = validatePreferences({ [key]: value });
    if (value === undefined || validated[key] !== value || raw.length > 500) invalid.push(key);
    else Object.assign(next, { [key]: value });
  }
  const sort = params.get("sort"); const direction = params.get("direction");
  if (sort !== null || direction !== null) {
    if ((sort === null || SORT_KEYS.includes(sort)) && (direction === null || ["1", "-1"].includes(direction)))
      next.sort = { key: sort || next.sort.key, dir: direction === null ? next.sort.dir : Number(direction) as 1 | -1 };
    else invalid.push("sort");
  }
  return { prefs: next, invalid };
}

function SignalDetail({ row, note, onClose }: { row: BoardRow | null; note?: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (row && !dialog.current?.open) dialog.current?.showModal(); }, [row]);
  return <dialog ref={dialog} className="board-signal-dialog" aria-labelledby="signal-title" onClose={onClose}
    onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
    <header className="mb-4 flex items-start justify-between gap-4"><h2 id="signal-title" className="font-bold">{row?.PLAYER_NAME}</h2><button aria-label="Close explanation" onClick={() => dialog.current?.close()} className="rounded px-2 py-1">✕</button></header>
    {row && <div className="space-y-4 text-sm">
      <section><h3 className="mb-1 font-semibold">Draft Radar</h3><p className="whitespace-pre-wrap break-words text-ink-2">{row.radar_reasons || valueCall(row)?.title || "No market disagreement recorded."}</p></section>
      {note && <section><h3 className="mb-1 font-semibold">Your priority target</h3><p className="whitespace-pre-wrap break-words text-ink-2">{note}</p></section>}
      {row.analyst_action && row.analyst_action !== "none" && <section><h3 className="mb-1 font-semibold">Analyst layer</h3><p className="text-ink-2">{row.analyst_action} · {row.analyst_category} · {row.analyst_date}</p><p className="mt-2 whitespace-pre-wrap break-words text-ink-2">{row.analyst_rationale || "No rationale recorded."}</p></section>}
    </div>}
  </dialog>;
}

// ADP-vs-board value calls: our board rank vs where the market drafts the player.
const VALUE_GAP = 12; // picks later than our rank = a discount worth flagging

function valueCall(row: BoardRow): { tone: "up" | "down"; label: string; title: string } | null {
  if (row.adp == null || row.rank == null) return null;
  const gap = row.adp - row.rank;
  if (gap >= VALUE_GAP)
    return {
      tone: "up",
      label: `+${Math.round(gap)}`,
      title: `Value: our rank ${row.rank}, drafted ~pick ${Math.round(row.adp)} — available ${Math.round(gap)} picks after we'd take him`,
    };
  if (gap <= -VALUE_GAP)
    return {
      tone: "down",
      label: `${Math.round(gap)}`,
      title: `Market reach: drafted ~pick ${Math.round(row.adp)}, our rank ${row.rank} — the market is ${Math.round(-gap)} picks higher than our board`,
    };
  return null;
}

export default function DraftBoard() {
  const meta = useMeta();
  const nav = useNavigate();
  const loc = useLocation();
  const compare = useCompare();
  const { targets, edit: editTarget, storageUnavailable: targetStorageUnavailable } = useDraftTargets();
  const [savedPrefs, setPrefs, storageUnavailable] = useStoredPreferences("fantasy-nba-local-board-preferences-v1", DEFAULTS, validatePreferences);
  const initialPrefs = useRef(savedPrefs);
  const route = useMemo(() => readBoardQuery(loc.search, initialPrefs.current), [loc.search]);
  const prefs = route.prefs;
  const update = (patch: Partial<BoardPreferences>) => nav(`/?${boardQuery({ ...prefs, ...patch })}`, { replace: Object.hasOwn(patch, "q") });
  useEffect(() => {
    setPrefs(current => JSON.stringify(current) === JSON.stringify(prefs) ? current : prefs);
    if (!loc.search) nav(`/?${boardQuery(prefs)}`, { replace: true });
  }, [prefs, loc.search, nav, setPrefs]);
  const { analyst, team, q, topN, showChart, radarFilter } = prefs;
  const target = meta?.target_seasons.includes(prefs.target) ? prefs.target : meta?.current_target || DEFAULTS.target;
  const model = meta && Object.hasOwn(meta.models, prefs.model) ? prefs.model : DEFAULTS.model;
  const stance = meta && Object.hasOwn(meta.stances, prefs.stance) ? prefs.stance : DEFAULTS.stance;
  const [signal, setSignal] = useState<BoardRow | null>(null);
  const url = meta ? `/api/board?target=${target}&model=${model}&stance=${stance}&analyst=${analyst}` : null;
  const { data, error, loading } = useApi<BoardResponse>(url);
  const playerIndex = useApi<{ rows: { PLAYER_ID: number }[] }>("/api/players");
  const targetStart = Number(target.slice(0, 4));
  const previousSeason = `${targetStart - 1}-${String(targetStart).slice(-2)}`;

  useEffect(() => {
    if (meta && (target !== prefs.target || model !== prefs.model || stance !== prefs.stance)) nav(`/?${boardQuery({ ...prefs, target, model, stance })}`, { replace: true });
  }, [meta, target, model, stance, prefs, nav]);
  useEffect(() => {
    if (!loading && data?.target === target && team !== "All" && !data.teams.includes(team)) nav(`/?${boardQuery({ ...prefs, team: "All" })}`, { replace: true });
  }, [loading, data, target, team, prefs, nav]);

  const filtered = useMemo(() => {
    if (!data) return [];
    let rows = data.rows;
    if (q.trim()) rows = rows.filter((r) => `${r.PLAYER_NAME} ${r.TEAM_ABBREVIATION || ""} ${(r.positions || []).join(" ")}`.toLowerCase().includes(q.trim().toLowerCase()));
    if (team !== "All") rows = rows.filter((r) => r.TEAM_ABBREVIATION === team);
    if (radarFilter === "Targets") rows = rows.filter((r) => r.radar_label?.includes("target"));
    if (radarFilter === "Fades") rows = rows.filter((r) => r.radar_label?.includes("fade"));
    if (radarFilter === "Watchlist") rows = rows.filter((r) => targets[String(r.PLAYER_ID)]);
    return rows.slice(0, topN);
  }, [data, q, team, topN, radarFilter, targets]);

  const [rMin, rMax] = useMemo(() => {
    const head = filtered.slice(0, Math.min(filtered.length, topN));
    const p10s = head.map((r) => r.fpts_p10).filter((v): v is number => v != null && Number.isFinite(v));
    const p90s = head.map((r) => r.fpts_p90).filter((v): v is number => v != null && Number.isFinite(v));
    if (!p10s.length || !p90s.length) return [0, 1];
    return [Math.min(...p10s), Math.max(...p90s)];
  }, [filtered, topN]);

  // Historical honesty check: of our top-N, how many actually finished top-N?
  const hitRate = useMemo(() => {
    if (!data?.has_actuals) return null;
    const n = Math.min(topN, data.rows.length);
    const proj = new Set(data.rows.slice(0, n).map((r) => r.PLAYER_ID));
    const act = data.rows
      .filter((r) => r.actual_rank != null)
      .sort((a, b) => a.actual_rank! - b.actual_rank!)
      .slice(0, n);
    const hit = act.filter((r) => proj.has(r.PLAYER_ID)).length;
    return n ? Math.round((100 * hit) / n) : null;
  }, [data, topN]);

  const cols = useMemo<Column<BoardRow>[]>(() => {
    const base: Column<BoardRow>[] = [
      {
        key: "rank", label: "Rank", align: "right", title: "Rank under the selected season-value stance",
        sortValue: (r) => r.rank,
        render: (r) => <span className="font-semibold">{r.rank}</span>,
      },
      {
        key: "player", label: "Player",
        sortValue: (r) => r.PLAYER_NAME,
        render: (r) => (
          <span className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={compare.ids.includes(r.PLAYER_ID)}
              onChange={() => compare.toggle(r.PLAYER_ID, r.PLAYER_NAME)}
              onClick={(e) => e.stopPropagation()}
              title="Add to compare"
              aria-label={`Compare ${r.PLAYER_NAME}`}
              className="h-3.5 w-3.5 accent-[var(--accent)]"
            />
            <button onClick={() => nav(`/players/${r.PLAYER_ID}`)} className="font-medium text-left hover:text-accent">{r.PLAYER_NAME}</button>
            <span className="text-[11px] text-ink-3">{r.TEAM_ABBREVIATION ?? ""}</span>
            <button
              onClick={(e) => { e.stopPropagation(); editTarget(r); }}
              title={targets[String(r.PLAYER_ID)] ? "Edit priority target (type REMOVE to clear)" : "Add priority target"}
              aria-label={`${targets[String(r.PLAYER_ID)] ? "Edit" : "Add"} priority target for ${r.PLAYER_NAME}`}
              className={targets[String(r.PLAYER_ID)] ? "text-warn" : "text-ink-3 hover:text-warn"}
            >
              {targets[String(r.PLAYER_ID)] ? "★" : "☆"}
            </button>
          </span>
        ),
      },
      { key: "age", label: "Age", align: "right", sortValue: (r) => r.target_age, render: (r) => f0(r.target_age), hideBelow: "md" },
      { key: "gp", label: "GP", align: "right", title: "Projected games played", sortValue: (r) => r.gp, render: (r) => f0(r.gp) },
      { key: "mpg", label: "MPG", align: "right", sortValue: (r) => r.mpg, render: (r) => f1(r.mpg), hideBelow: "md" },
      {
        key: "fpts_pg", label: "FP/G", align: "right", title: "Projected fantasy points per game",
        sortValue: (r) => r.fpts_pg,
        render: (r) => <span className="font-semibold">{f1(r.fpts_pg)}</span>,
      },
      { key: "positions", label: "Position", sortValue: row => row.positions?.join("/") || null, render: row => row.positions?.length ? row.positions.join("/") : "—" },
      {
        key: "previous_fpts_pg", label: `${previousSeason} FP/G`, align: "right",
        title: `Actual ${previousSeason} fantasy points per game under the current scoring settings`,
        sortValue: (r) => r.previous_fpts_pg ?? null,
        render: (r) => f1(r.previous_fpts_pg), hideBelow: "md",
      },
      {
        key: "fpts_pg_change", label: "Proj Δ", align: "right",
        title: `Projected FP/G minus actual ${previousSeason} FP/G`,
        sortValue: (r) => r.fpts_pg_change ?? null,
        render: (r) => r.fpts_pg_change == null ? "—" : (
          <span className={r.fpts_pg_change > 0 ? "text-up" : r.fpts_pg_change < 0 ? "text-down" : "text-ink-3"}>
            {signed(r.fpts_pg_change)}
          </span>
        ),
      },
      {
        key: "analyst", label: "Analyst", title: "Analyst layer (board B) adjustment — blank = pure model",
        sortValue: (r) => parseAction(r.analyst_action)?.value ?? null,
        render: (r) => {
          const a = parseAction(r.analyst_action);
          if (!a) return null;
          return (
            <button onClick={event => { event.stopPropagation(); setSignal(r); }} aria-label={`Explain analyst adjustment for ${r.PLAYER_NAME}`}><Chip
              tone={a.value > 0 ? "up" : "down"}
              title={
                (r.analyst_rationale ? `${r.analyst_rationale}\n\n` : "") +
                `${r.analyst_category} · ${r.analyst_date} · model rank ${r.model_rank}`
              }
            >
              {a.value > 0 ? "▲" : "▼"} {Math.abs(a.value).toFixed(1)}
            </Chip></button>
          );
        },
      },
      {
        key: "range", label: "Floor → Ceiling", title: "Simulated season-total range (p10 → median → p90)",
        render: (r) =>
          r.fpts_p10 == null || r.fpts_median == null || r.fpts_p90 == null
            ? <span className="text-ink-3">—</span>
            : <RangeStrip p10={r.fpts_p10} p50={r.fpts_median} p90={r.fpts_p90} min={rMin} max={rMax} />,
        hideBelow: "lg",
      },
      { key: "median", label: "Median", align: "right", title: "Median simulated season total", sortValue: (r) => r.fpts_median, render: (r) => f0(r.fpts_median) },
      {
        key: "risk", label: "Risk", align: "right", title: "Relative width of the p10–p90 band",
        sortValue: (r) => r.risk,
        render: (r) => (r.risk == null ? <span className="text-ink-3">—</span> : <RiskMeter value={r.risk} />),
        hideBelow: "sm",
      },
    ];
    const hasVor = data?.rows.some((r) => r.vor != null);
    if (hasVor)
      base.push({
        key: "vor", label: "VOR", align: "right", title: "FP/G above league replacement (D1.2)",
        sortValue: (r) => r.vor ?? null, render: (r) => f1(r.vor), hideBelow: "lg",
      });
    {
      base.push({
        key: "adp", label: "ADP", align: "right", title: "Platform ADP — draft-day availability, not value",
        sortValue: (r) => r.adp ?? null, render: (r) => f0(r.adp), hideBelow: "sm",
      });
      base.push({
        key: "radar", label: "Radar", title: "Explainable ADP disagreement: strong calls require a two-round gap plus a role, growth, or downside mechanism",
        sortValue: (r) => r.radar_round_gap ?? null,
        render: (r) => {
          const target = targets[String(r.PLAYER_ID)];
          const explain = (content: React.ReactNode) => <button onClick={event => { event.stopPropagation(); setSignal(r); }} aria-label={`Explain Radar for ${r.PLAYER_NAME}`}>{content}</button>;
          if (target) return explain(<Chip tone="accent" title={targetTitle(r, target)}>★ {target.takeBy ? `by ${target.takeBy}` : "priority"}</Chip>);
          if (r.radar_label) return explain(<Chip tone={radarTone(r.radar_label)} title={r.radar_reasons || undefined}>{radarName(r.radar_label)}</Chip>);
          const value = valueCall(r);
          return value ? explain(<Chip tone={value.tone} title={value.title}>{value.label}</Chip>) : null;
        },
      });
    }
    if (data?.has_actuals) {
      base.push(
        {
          key: "actual_rank", label: "Act #", align: "right", title: "Actual finish rank by real season total",
          sortValue: (r) => r.actual_rank ?? null,
          render: (r) => (
            <span className={r.actual_rank != null && Math.abs(r.actual_rank - r.rank) >= 25 ? "text-down" : ""}>
              {f0(r.actual_rank)}
            </span>
          ),
        },
        { key: "act_fpg", label: "Act FP/G", align: "right", sortValue: (r) => r.act_fpts_pg ?? null, render: (r) => f1(r.act_fpts_pg), hideBelow: "md" },
        { key: "act_total", label: "Act Total", align: "right", sortValue: (r) => r.act_fpts_total ?? null, render: (r) => f0(r.act_fpts_total), hideBelow: "lg" },
      );
    }
    return base;
  }, [data, filtered, rMin, rMax, compare, previousSeason, targets, editTarget]);

  const tableColumns = useMemo(() => {
    const selected = prefs.preset === "full" ? cols : (PRESETS[prefs.preset] || PRESETS.draft)
      .map(key => cols.find(column => column.key === key))
      .filter((column): column is Column<BoardRow> => column != null);
    const actuals = data?.has_actuals ? cols.filter(column => ["actual_rank", "act_fpg", "act_total"].includes(column.key) && !selected.includes(column)) : [];
    return [...selected, ...actuals].map(column => ({ ...column, hideBelow: undefined }));
  }, [cols, prefs.preset, data?.has_actuals]);
  const displayed = useMemo(() => sortTableRows(filtered, cols, prefs.sort), [filtered, cols, prefs.sort]);
  useEffect(() => {
    if (!loading && data && !cols.some(column => column.key === prefs.sort.key && column.sortValue)) nav(`/?${boardQuery({ ...prefs, sort: DEFAULTS.sort })}`, { replace: true });
  }, [loading, data, cols, prefs, nav]);
  const resetFilters = () => update({ q: "", team: "All", radarFilter: "All", topN: 100, sort: DEFAULTS.sort });

  if (!meta) return <Spinner label="Loading…" />;

  return (
    <div className="local-board space-y-4" data-layout={prefs.layout}>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight">Draft Board</h1>
          <p className="text-[13px] text-ink-2">
            {target === meta.current_target
              ? "No-leakage projection for the upcoming season, with simulated risk ranges."
              : "Past season, re-projected with no leakage — actual results shown alongside."}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2.5">
          <Field label="Season">
            <Select value={target} onChange={value => update({ target: value, team: "All" })}
              options={meta.target_seasons.map((s) => ({ value: s, label: s }))} />
          </Field>
          <Field label="Model">
            <Select value={model} onChange={value => update({ model: value })} title={meta.models[model]}
              options={Object.keys(meta.models).map((v) => ({ value: v, label: v === "learned" ? "learned (default)" : v }))} />
          </Field>
          <Field label="Rank by">
            <Segmented value={stance} onChange={value => update({ stance: value })}
              options={Object.entries(meta.stances).map(([v, d]) => ({ value: v, label: v[0].toUpperCase() + v.slice(1), title: d }))} />
          </Field>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-3"><CopyLink url={`${location.origin}/?${boardQuery({ ...prefs, radarFilter: radarFilter === "Watchlist" ? "All" : radarFilter })}`} />
        {radarFilter === "Watchlist" && <span className="text-xs text-ink-3">Shared board links show all players; export your watchlist to transfer targets.</span>}
      </div>
      {playerIndex.data && <WatchlistBackup season={meta.current_target} knownIds={playerIndex.data.rows.map(row => row.PLAYER_ID)} />}
      {route.invalid.length > 0 && <p role="status" className="text-xs text-ink-2">Ignored invalid link settings: {route.invalid.join(", ")}. Your saved settings apply.</p>}

      <div className="flex flex-wrap items-center gap-2.5">
        <SearchInput value={q} onChange={value => update({ q: value })} placeholder="Search player, team or position…" className="w-full sm:w-64" />
        <Field label="Team"><Select value={team} onChange={value => update({ team: value })}
          options={[{ value: "All", label: "All teams" }, ...(data?.teams ?? []).map((t) => ({ value: t, label: t }))]} /></Field>
        <Field label="Show"><Select value={String(topN)} onChange={(v) => update({ topN: Number(v) })}
          options={[50, 100, 150, 200, 300].map((n) => ({ value: String(n), label: `Top ${n}` }))} /></Field>
        <Field label="Radar"><Select value={radarFilter} onChange={value => update({ radarFilter: value })}
          options={["All", "Targets", "Fades", "Watchlist"].map((v) => ({ value: v, label: v === "All" ? "All radar" : v }))} /></Field>
        <Toggle checked={analyst} onChange={value => update({ analyst: value })} label="Analyst layer (B)" />
        <div className="ml-auto flex items-center gap-3 text-xs text-ink-2">
          {data?.analyst_applied && data.n_adjusted > 0 && (
            <Chip tone="accent" title="config/analyst_overrides.yaml applied before the ranges were simulated">
              board B · {data.n_adjusted} adjusted
            </Chip>
          )}
          {hitRate != null && (
            <Chip tone="neutral" title={`Of this board's top ${Math.min(topN, data?.rows.length ?? 0)}, ${hitRate}% actually finished top-${Math.min(topN, data?.rows.length ?? 0)}`}>
              hit rate {hitRate}%
            </Chip>
          )}
          <Toggle checked={showChart} onChange={value => update({ showChart: value })} label="Range chart" />
        </div>
      </div>

      <Card className="space-y-3 p-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Table columns"><Select value={prefs.preset} onChange={value => update({ preset: value })} options={[{value:"draft",label:"Draft"},{value:"performance",label:"Performance"},{value:"risk",label:"Risk"},{value:"full",label:"Full detail"}]} /></Field>
          <Field label="Layout"><Select value={prefs.layout} onChange={value => update({ layout: value })} options={[{value:"auto",label:"Automatic"},{value:"table",label:"Table"},{value:"cards",label:"Cards"}]} /></Field>
          <Field label="Sort by"><Select value={prefs.sort.key} onChange={key => update({ sort: { key, dir: ["rank", "player", "positions", "age", "risk", "adp", "actual_rank"].includes(key) ? 1 : -1 } })} options={cols.filter(column => column.sortValue).map(column => ({value:column.key,label:String(column.label)}))} /></Field>
          <button onClick={() => update({ sort: { ...prefs.sort, dir: prefs.sort.dir === 1 ? -1 : 1 } })} className="h-8 rounded-lg border border-bdr px-3 text-xs" aria-label="Change sort direction">{prefs.sort.dir === 1 ? "Ascending ↑" : "Descending ↓"}</button>
          <button onClick={resetFilters} className="h-8 px-2 text-xs font-semibold text-accent">Reset filters</button>
        </div>
        <p className="text-xs leading-relaxed text-ink-2"><b>{stance[0].toUpperCase() + stance.slice(1)} season-value ranking:</b> {meta.stances[stance]}. Sorting rearranges the displayed top {topN}; ranks and tiers remain tied to this stance. FP/G measures production when playing; ranges describe season totals.</p>
        {(storageUnavailable || targetStorageUnavailable) && <p className="text-xs text-ink-2" role="status">Browser storage is unavailable. Your changes will last for this session only.</p>}
      </Card>

      {error && <ErrorNote message={error} />}
      {loading && <Spinner label={`Computing the ${model} board for ${target}…`} />}
      {!loading && data && filtered.length === 0 && <EmptyNote>No players match the current filters. <button onClick={resetFilters} className="font-semibold text-accent">Reset filters</button></EmptyNote>}

      {!loading && data && filtered.length > 0 && (
        <>
          {showChart && (
            <Card className="p-4">
              <h2 className="mb-1 text-[13px] font-semibold text-ink-2">
                Floor → median → ceiling, top {Math.min(30, filtered.length)} (projected season total)
              </h2>
              <RangePlot
                rows={filtered
                  .slice(0, 30)
                  .filter((r) => r.fpts_p10 != null && r.fpts_median != null && r.fpts_p90 != null)
                  .map((r) => ({
                    name: r.PLAYER_NAME, p10: r.fpts_p10!, p50: r.fpts_median!, p90: r.fpts_p90!,
                    extra: r.risk == null ? "market-priced" : `risk ${r.risk.toFixed(2)}`,
                  }))}
                onPick={(name) => {
                  const row = filtered.find((r) => r.PLAYER_NAME === name);
                  if (row) nav(`/players/${row.PLAYER_ID}`);
                }}
              />
            </Card>
          )}
          <div className="board-table-view"><DataTable
            columns={tableColumns}
            rows={displayed}
            rowKey={(r) => r.PLAYER_ID}
            onRowClick={(r) => nav(`/players/${r.PLAYER_ID}`)}
            defaultSort="rank"
            controlledSort={prefs.sort}
            onSortChange={sort => update({ sort })}
            maxHeight="max(260px, calc(100dvh - 400px))"
            groupOf={(r) => r.tier}
            renderGroup={(t) => <>Tier {t}</>}
          /></div>
          <BoardCards rows={displayed} columns={cols} targets={targets} compareIds={compare.ids}
            onCompare={row => compare.toggle(row.PLAYER_ID, row.PLAYER_NAME)} onTarget={editTarget}
            onPlayer={row => nav(`/players/${row.PLAYER_ID}`)} />
          <p className="text-xs text-ink-3" role="status">{displayed.length} players · sorted by {String(cols.find(column => column.key === prefs.sort.key)?.label || "Rank")} {prefs.sort.dir === 1 ? "ascending" : "descending"}</p>
          <p className="text-xs text-ink-3">
            {meta.models[model]} · ranked by <b>{stance}</b> — {meta.stances[stance]}.
            Click a row for the player page; tick the checkbox to compare. Tier breaks = unusually
            large draft-value gaps between adjacent players.
          </p>
        </>
      )}
      <SignalDetail row={signal} note={signal && targets[String(signal.PLAYER_ID)] ? targetTitle(signal, targets[String(signal.PLAYER_ID)]) : undefined} onClose={() => setSignal(null)} />
    </div>
  );
}
