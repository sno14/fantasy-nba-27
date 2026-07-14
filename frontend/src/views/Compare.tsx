import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCompare } from "../App";
import { PlayerDetail, get } from "../lib/api";
import { f0, f1, parseAction } from "../lib/format";
import { LineChart, RangeStrip, Series } from "../components/charts";
import { Card, Chip, EmptyNote, Spinner } from "../components/ui";

const SERIES_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-5)"];

export default function Compare() {
  const { ids, toggle, clear } = useCompare();
  const nav = useNavigate();
  const [details, setDetails] = useState<Record<number, PlayerDetail>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let stale = false;
    setLoading(true);
    Promise.all(ids.map((id) => get<PlayerDetail>(`/api/player/${id}`).then((d) => [id, d] as const)))
      .then((pairs) => {
        if (!stale) setDetails(Object.fromEntries(pairs));
      })
      .finally(() => !stale && setLoading(false));
    return () => {
      stale = true;
    };
  }, [ids]);

  const players = ids.map((id) => details[id]).filter(Boolean);

  // Overlaid FP/G careers on the union of seasons.
  const fpgSeries = useMemo<Series[]>(() => {
    const seasons = Array.from(
      new Set(players.flatMap((p) => p.career.map((c) => c.SEASON))),
    ).sort();
    return players.map((p, i) => ({
      name: p.projection.PLAYER_NAME as string,
      color: SERIES_COLORS[i % SERIES_COLORS.length],
      points: seasons.map((s) => {
        const row = p.career.find((c) => c.SEASON === s);
        return { x: 0, label: s, y: row?.FPTS ?? null };
      }),
    }));
  }, [players]);

  if (ids.length < 2)
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-bold tracking-tight">Compare</h1>
        <EmptyNote>
          Pick 2–4 players to compare — tick the checkboxes on the{" "}
          <button className="font-semibold text-accent" onClick={() => nav("/")}>Draft Board</button>{" "}
          or use the + Compare button on a player page.
        </EmptyNote>
      </div>
    );

  if (loading && players.length < ids.length) return <Spinner label="Loading players…" />;

  const rangeLo = Math.min(...players.map((p) => p.projection.fpts_p10 as number)) * 0.95;
  const rangeHi = Math.max(...players.map((p) => p.projection.fpts_p90 as number)) * 1.03;

  const metric = (label: string, title: string, fn: (p: PlayerDetail) => React.ReactNode, highlight?: (p: PlayerDetail) => number) => {
    const best = highlight ? Math.max(...players.map(highlight)) : null;
    return (
      <tr className="border-t border-bdr/60">
        <td className="px-3 py-1.5 text-[12px] font-medium text-ink-2" title={title}>{label}</td>
        {players.map((p) => (
          <td key={p.projection.PLAYER_ID as number}
            className={`tnum px-3 py-1.5 text-right ${highlight && highlight(p) === best ? "font-bold text-accent" : ""}`}>
            {fn(p)}
          </td>
        ))}
      </tr>
    );
  };

  return (
    <div className="space-y-4">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-bold tracking-tight">Compare</h1>
          <p className="text-[13px] text-ink-2">Side-by-side 2026-27 projections (board B) and career trajectories.</p>
        </div>
        <button onClick={clear} className="text-xs font-medium text-ink-3 hover:text-ink-2">Clear all</button>
      </header>

      <Card className="overflow-hidden">
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr>
                <th className="w-36 px-3 py-2" />
                {players.map((p) => {
                  const a = parseAction(p.projection.analyst_action as string | null);
                  const pid = p.projection.PLAYER_ID as number;
                  return (
                    <th key={pid} className="px-3 py-2 text-right">
                      <button onClick={() => nav(`/players/${pid}`)} className="font-bold text-ink hover:text-accent">
                        {p.projection.PLAYER_NAME as string}
                      </button>
                      <div className="mt-0.5 flex items-center justify-end gap-1.5 text-[11px] font-normal text-ink-3">
                        {p.projection.TEAM_ABBREVIATION as string} · #{p.projection.rank as number}
                        {a && <Chip tone={a.value > 0 ? "up" : "down"}>{a.value > 0 ? "▲" : "▼"}{Math.abs(a.value).toFixed(1)}</Chip>}
                        <button onClick={() => toggle(pid, p.projection.PLAYER_NAME as string)}
                          className="text-ink-3 hover:text-down" title="Remove">✕</button>
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {metric("Proj rank", "Board rank (safe stance)", (p) => `#${p.projection.rank}`, (p) => -(p.projection.rank as number))}
              {metric("FP / game", "Projected fantasy points per game", (p) => f1(p.projection.fpts_pg as number), (p) => p.projection.fpts_pg as number)}
              {metric("Median total", "Median simulated season total", (p) => f0(p.projection.fpts_median as number), (p) => p.projection.fpts_median as number)}
              {metric("Floor (p10)", "10th percentile season total", (p) => f0(p.projection.fpts_p10 as number), (p) => p.projection.fpts_p10 as number)}
              {metric("Ceiling (p90)", "90th percentile season total", (p) => f0(p.projection.fpts_p90 as number), (p) => p.projection.fpts_p90 as number)}
              {metric("Risk", "Relative width of the p10–p90 band (lower is safer)", (p) => (p.projection.risk as number).toFixed(2), (p) => -(p.projection.risk as number))}
              {metric("Proj GP", "Projected games played", (p) => f0(p.projection.gp as number), (p) => p.projection.gp as number)}
              {metric("Proj MPG", "Projected minutes per game", (p) => f1(p.projection.mpg as number))}
              {metric("Age", "Age in the target season", (p) => f0(p.projection.target_age as number))}
              {metric("VOR", "FP/G above league replacement", (p) => (p.projection.vor != null ? f1(p.projection.vor as number) : "—"), (p) => (p.projection.vor as number) ?? -Infinity)}
              {metric("ADP", "Market average draft position", (p) => (p.projection.adp != null ? f0(p.projection.adp as number) : "—"))}
              <tr className="border-t border-bdr/60">
                <td className="px-3 py-2 text-[12px] font-medium text-ink-2">Range</td>
                {players.map((p) => (
                  <td key={p.projection.PLAYER_ID as number} className="px-3 py-2">
                    <div className="flex justify-end">
                      <RangeStrip p10={p.projection.fpts_p10 as number} p50={p.projection.fpts_median as number}
                        p90={p.projection.fpts_p90 as number} min={rangeLo} max={rangeHi} width={150} />
                    </div>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="p-4">
        <h2 className="text-[13px] font-semibold text-ink-2">Career fantasy points per game</h2>
        <LineChart series={fpgSeries} height={240} />
      </Card>
    </div>
  );
}
