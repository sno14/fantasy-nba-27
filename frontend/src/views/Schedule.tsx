// V6 — Schedule strength (docs/ui-views-plan.md): teams × weeks game-count heatmap with
// fantasy-playoff-week highlighting, B2B load, and playoff-games ranking. Draft tiebreak
// + trade-deadline tool; banners the placeholder playoff weeks until league.yaml confirms.

import { useMemo, useState } from "react";
import { ScheduleStrengthResponse, useApi } from "../lib/api";
import { Card, Chip, EmptyNote, ErrorNote, Spinner } from "../components/ui";

type SortKey = "playoff" | "total" | "b2b" | "team";

export default function Schedule() {
  const { data, error, loading } = useApi<ScheduleStrengthResponse>("/api/schedule-strength");
  const [sort, setSort] = useState<SortKey>("playoff");
  const [dir, setDir] = useState<1 | -1>(-1);

  const rows = useMemo(() => {
    if (!data) return [];
    const key = (t: (typeof data.teams)[number]) =>
      sort === "playoff" ? t.playoff_games : sort === "total" ? t.total_games : sort === "b2b" ? t.b2b : t.team;
    return [...data.teams].sort((a, b) => {
      const va = key(a);
      const vb = key(b);
      return va < vb ? -dir : va > vb ? dir : a.team.localeCompare(b.team);
    });
  }, [data, sort, dir]);

  const clickSort = (k: SortKey) => {
    if (sort === k) setDir((d) => (d === 1 ? -1 : 1));
    else {
      setSort(k);
      setDir(k === "team" ? 1 : -1);
    }
  };

  if (error) return <ErrorNote message={error} />;
  if (loading || !data) return <Spinner label="Loading schedule…" />;
  if (!data.has_schedule)
    return (
      <Card>
        <EmptyNote>
          {data.note ?? "No schedule cached."} Once <code>scripts/pull_schedule.py</code> runs
          (the 2026-27 schedule publishes ~mid-August), this view lights up.
        </EmptyNote>
      </Card>
    );

  const playoff = new Set(data.playoff_weeks);
  const arrow = (k: SortKey) => (sort === k ? <span className="ml-0.5 text-accent">{dir === 1 ? "▲" : "▼"}</span> : null);
  const head = "cursor-pointer select-none px-2 py-1.5 text-right font-semibold hover:text-ink-2";

  // Cell shading: 0 games = blank, 1..4 scale the accent-soft background.
  const cellBg = (n: number, isPlayoff: boolean) => ({
    background: n === 0 ? "transparent" : `color-mix(in oklab, var(${isPlayoff ? "--accent" : "--baseline"}) ${8 + n * 14}%, transparent)`,
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-[13px] text-ink-2">
          Games per fantasy week, {data.target}. Playoff weeks{" "}
          <span className="font-semibold">{data.playoff_weeks.join(", ")}</span> highlighted.
        </div>
        {!data.playoff_weeks_confirmed && (
          <Chip tone="warn" title="league.yaml carries placeholder fantasy_playoff_weeks — set fantasy_playoff_weeks_confirmed: true once the ESPN matchup calendar lands (mid-Aug)">
            ⚠ placeholder playoff weeks
          </Chip>
        )}
      </div>

      <div className="scroll-thin overflow-auto rounded-xl border border-bdr bg-surface" style={{ maxHeight: "calc(100vh - 210px)" }}>
        <table className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 z-[5]">
            <tr className="bg-surface-2 text-[11px] uppercase tracking-wide text-ink-3">
              <th className="cursor-pointer select-none px-2.5 py-1.5 text-left font-semibold hover:text-ink-2" onClick={() => clickSort("team")}>
                Team{arrow("team")}
              </th>
              <th className={head} onClick={() => clickSort("playoff")} title="Games in the fantasy playoff weeks — the number that decides championships">
                PO{arrow("playoff")}
              </th>
              <th className={head} onClick={() => clickSort("total")}>
                Tot{arrow("total")}
              </th>
              <th className={head} onClick={() => clickSort("b2b")} title="Back-to-backs — rest-risk load across the season">
                B2B{arrow("b2b")}
              </th>
              {data.weeks.map((w) => (
                <th
                  key={w.week}
                  title={`${w.week_name}: ${w.start} → ${w.end}`}
                  className={`px-1 py-1.5 text-center font-semibold ${playoff.has(w.week) ? "text-accent" : ""}`}
                >
                  {w.week}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.team} className="border-b border-bdr/60 last:border-b-0">
                <td className="px-2.5 py-1 font-medium">{t.team}</td>
                <td className="tnum px-2 py-1 text-right font-semibold text-accent">{t.playoff_games}</td>
                <td className="tnum px-2 py-1 text-right">{t.total_games}</td>
                <td className="tnum px-2 py-1 text-right">{t.b2b}</td>
                {data.weeks.map((w) => {
                  const n = t.by_week[String(w.week)] ?? 0;
                  return (
                    <td key={w.week} className="tnum px-1 py-1 text-center" style={cellBg(n, playoff.has(w.week))}>
                      {n || ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
