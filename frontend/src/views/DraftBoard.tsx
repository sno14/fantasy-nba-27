import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCompare, useMeta } from "../App";
import { BoardResponse, BoardRow, useApi } from "../lib/api";
import { f0, f1, parseAction, signed } from "../lib/format";
import { Column, DataTable } from "../components/DataTable";
import { RangePlot, RangeStrip, RiskMeter } from "../components/charts";
import { Card, Chip, EmptyNote, ErrorNote, Field, SearchInput, Segmented, Select, Spinner, Toggle } from "../components/ui";
import { radarName, radarTone, targetTitle, useDraftTargets } from "../lib/draftRadar";

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
  const compare = useCompare();
  const { targets, edit: editTarget } = useDraftTargets();

  const [target, setTarget] = useState("2026-27");
  const [model, setModel] = useState("learned");
  const [stance, setStance] = useState("safe");
  const [analyst, setAnalyst] = useState(true);
  const [team, setTeam] = useState("All");
  const [q, setQ] = useState("");
  const [topN, setTopN] = useState(100);
  const [showChart, setShowChart] = useState(false);
  const [radarFilter, setRadarFilter] = useState("All");

  const url = `/api/board?target=${target}&model=${model}&stance=${stance}&analyst=${analyst}`;
  const { data, error, loading } = useApi<BoardResponse>(url);
  const targetStart = Number(target.slice(0, 4));
  const previousSeason = `${targetStart - 1}-${String(targetStart).slice(-2)}`;

  const filtered = useMemo(() => {
    if (!data) return [];
    let rows = data.rows;
    if (q) rows = rows.filter((r) => r.PLAYER_NAME.toLowerCase().includes(q.toLowerCase()));
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
        key: "rank", label: "#", align: "right",
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
              className="h-3.5 w-3.5 accent-[var(--accent)]"
            />
            <span className="font-medium">{r.PLAYER_NAME}</span>
            <span className="text-[11px] text-ink-3">{r.TEAM_ABBREVIATION ?? ""}</span>
            <button
              onClick={(e) => { e.stopPropagation(); editTarget(r); }}
              title={targets[String(r.PLAYER_ID)] ? "Edit priority target (type REMOVE to clear)" : "Add priority target"}
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
            <Chip
              tone={a.value > 0 ? "up" : "down"}
              title={
                (r.analyst_rationale ? `${r.analyst_rationale}\n\n` : "") +
                `${r.analyst_category} · ${r.analyst_date} · model rank ${r.model_rank}`
              }
            >
              {a.value > 0 ? "▲" : "▼"} {Math.abs(a.value).toFixed(1)}
            </Chip>
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
    const hasVor = filtered.some((r) => r.vor != null);
    const hasAdp = filtered.some((r) => r.adp != null);
    if (hasVor)
      base.push({
        key: "vor", label: "VOR", align: "right", title: "FP/G above league replacement (D1.2)",
        sortValue: (r) => r.vor ?? null, render: (r) => f1(r.vor), hideBelow: "lg",
      });
    if (hasAdp) {
      base.push({
        key: "adp", label: "ADP", align: "right", title: "Platform ADP — draft-day availability, not value",
        sortValue: (r) => r.adp ?? null, render: (r) => f0(r.adp), hideBelow: "sm",
      });
      base.push({
        key: "radar", label: "Radar", title: "Explainable ADP disagreement: strong calls require a two-round gap plus a role, growth, or downside mechanism",
        sortValue: (r) => r.radar_round_gap ?? null,
        render: (r) => {
          const target = targets[String(r.PLAYER_ID)];
          if (target) return <Chip tone="accent" title={targetTitle(r, target)}>★ {target.takeBy ? `by ${target.takeBy}` : "priority"}</Chip>;
          if (r.radar_label) return <Chip tone={radarTone(r.radar_label)} title={r.radar_reasons || undefined}>{radarName(r.radar_label)}</Chip>;
          const value = valueCall(r);
          return value ? <Chip tone={value.tone} title={value.title}>{value.label}</Chip> : null;
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

  if (!meta) return <Spinner label="Loading…" />;

  return (
    <div className="space-y-4">
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
            <Select value={target} onChange={setTarget}
              options={meta.target_seasons.map((s) => ({ value: s, label: s }))} />
          </Field>
          <Field label="Model">
            <Select value={model} onChange={setModel} title={meta.models[model]}
              options={Object.keys(meta.models).map((v) => ({ value: v, label: v === "learned" ? "learned (default)" : v }))} />
          </Field>
          <Field label="Rank by">
            <Segmented value={stance} onChange={setStance}
              options={Object.entries(meta.stances).map(([v, d]) => ({ value: v, label: v[0].toUpperCase() + v.slice(1), title: d }))} />
          </Field>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-2.5">
        <SearchInput value={q} onChange={setQ} placeholder="Search player…" className="w-56" />
        <Select value={team} onChange={setTeam}
          options={[{ value: "All", label: "All teams" }, ...(data?.teams ?? []).map((t) => ({ value: t, label: t }))]} />
        <Select value={String(topN)} onChange={(v) => setTopN(Number(v))}
          options={[50, 100, 150, 200, 300].map((n) => ({ value: String(n), label: `Top ${n}` }))} />
        <Select value={radarFilter} onChange={setRadarFilter}
          options={["All", "Targets", "Fades", "Watchlist"].map((v) => ({ value: v, label: v === "All" ? "All radar" : v }))} />
        <Toggle checked={analyst} onChange={setAnalyst} label="Analyst layer (B)" />
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
          <Toggle checked={showChart} onChange={setShowChart} label="Range chart" />
        </div>
      </div>

      {error && <ErrorNote message={error} />}
      {loading && <Spinner label={`Computing the ${model} board for ${target}…`} />}
      {!loading && data && filtered.length === 0 && <EmptyNote>No players match the current filters.</EmptyNote>}

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
          <DataTable
            columns={cols}
            rows={filtered}
            rowKey={(r) => r.PLAYER_ID}
            onRowClick={(r) => nav(`/players/${r.PLAYER_ID}`)}
            defaultSort="rank"
            groupOf={(r) => r.tier}
            renderGroup={(t) => <>Tier {t}</>}
          />
          <p className="text-xs text-ink-3">
            {meta.models[model]} · ranked by <b>{stance}</b> — {meta.stances[stance]}.
            Click a row for the player page; tick the checkbox to compare. Tier breaks = unusually
            large draft-value gaps between adjacent players.
          </p>
        </>
      )}
    </div>
  );
}
