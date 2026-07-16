// V4 — My Team (docs/ui-views-plan.md): the daily home page. My roster's health,
// trends, and this week's volume; ownership comes from the Draft Room's picks.

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { MyTeamResponse, WeeksResponse, useApi } from "../lib/api";
import { f1, signed } from "../lib/format";
import { Column, DataTable } from "../components/DataTable";
import { RangeStrip, RiskMeter, Sparkline } from "../components/charts";
import { Card, Chip, EmptyNote, ErrorNote, Field, Select, Spinner } from "../components/ui";

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const dow = (iso: string) => DOW[new Date(iso + "T00:00:00").getDay()];

export default function MyTeam() {
  const nav = useNavigate();
  const [week, setWeek] = useState<number | null>(null);

  const weeks = useApi<WeeksResponse>("/api/weeks").data;
  const url = week != null ? `/api/myteam?week=${week}` : "/api/myteam";
  const { data, error, loading } = useApi<MyTeamResponse>(url);

  useEffect(() => {
    if (week == null && data?.has_schedule && data.week != null) setWeek(data.week);
  }, [data, week]);

  const rows = data?.rows ?? [];
  const [rangeMin, rangeMax] = useMemo(() => {
    const lo = rows.map((r) => r.fpts_p10).filter((v): v is number => v != null);
    const hi = rows.map((r) => r.fpts_p90).filter((v): v is number => v != null);
    return [lo.length ? Math.min(...lo) : 0, hi.length ? Math.max(...hi) : 1];
  }, [rows]);

  type Row = (typeof rows)[number];
  const cols = useMemo<Column<Row>[]>(
    () => [
      { key: "rank", label: "#", align: "right", sortValue: (r) => r.rank, render: (r) => r.rank ?? "—" },
      {
        key: "name",
        label: "Player",
        sortValue: (r) => r.PLAYER_NAME,
        render: (r) => (
          <span className="font-medium">
            {r.PLAYER_NAME}
            {r.status_override && (
              <Chip tone="warn" title={r.status_override}>
                OUT
              </Chip>
            )}
            {r.chronic === 1 && (
              <Chip tone="down" title="Chronic-injury flag (EXP-015 history)">
                chr
              </Chip>
            )}
            {r.redist_mpg != null && r.redist_mpg >= 0.5 && (
              <Chip tone="up" title="Extra minutes inherited from currently-OUT teammates (EXP-030)">
                +{f1(r.redist_mpg)} MPG
              </Chip>
            )}
          </span>
        ),
      },
      { key: "team", label: "Team", hideBelow: "sm", render: (r) => r.TEAM_ABBREVIATION ?? "—", sortValue: (r) => r.TEAM_ABBREVIATION },
      { key: "fpts_pg", label: "FP/G", align: "right", sortValue: (r) => r.fpts_pg, render: (r) => f1(r.fpts_pg) },
      {
        key: "fpts_delta_14",
        label: "14d Δ",
        align: "right",
        hideBelow: "md",
        sortValue: (r) => r.fpts_delta_14,
        render: (r) =>
          r.fpts_delta_14 == null ? (
            <span className="text-ink-3">—</span>
          ) : (
            <span className={r.fpts_delta_14 > 0 ? "text-up" : r.fpts_delta_14 < 0 ? "text-down" : "text-ink-3"}>
              {signed(r.fpts_delta_14)}
            </span>
          ),
      },
      {
        key: "spark",
        label: "Trend",
        hideBelow: "lg",
        render: (r) => <Sparkline values={r.spark.map((s) => s[1])} />,
      },
      {
        key: "range",
        label: "Season range",
        title: "Floor → median → ceiling (season totals, Monte-Carlo ranges)",
        hideBelow: "lg",
        render: (r) =>
          r.fpts_p10 != null && r.fpts_median != null && r.fpts_p90 != null ? (
            <RangeStrip p10={r.fpts_p10} p50={r.fpts_median} p90={r.fpts_p90} min={rangeMin} max={rangeMax} />
          ) : (
            <span className="text-ink-3">—</span>
          ),
      },
      {
        key: "risk",
        label: "Risk",
        hideBelow: "md",
        sortValue: (r) => r.risk,
        render: (r) => (r.risk == null ? <span className="text-ink-3">—</span> : <RiskMeter value={r.risk} />),
      },
      { key: "n_games", label: "Games", align: "right", sortValue: (r) => r.n_games, render: (r) => (data?.has_schedule ? r.n_games : "—") },
      {
        key: "weekly_fpts",
        label: "Week FP",
        align: "right",
        sortValue: (r) => r.weekly_fpts,
        render: (r) => (data?.has_schedule ? <span className="font-semibold">{f1(r.weekly_fpts)}</span> : "—"),
      },
    ],
    [data, rangeMin, rangeMax],
  );

  if (error) return <ErrorNote message={error} />;
  if (loading || !data) return <Spinner label="Loading team…" />;
  if (!data.has_team)
    return (
      <Card>
        <EmptyNote>
          {data.note} → <Link className="text-accent underline" to="/room">Draft Room</Link> ·{" "}
          <Link className="text-accent underline" to="/power">Simulate</Link>
        </EmptyNote>
      </Card>
    );

  const unfilled = Object.entries(data.unfilled ?? {}).filter(([, n]) => n > 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Week">
          <Select
            value={week != null ? String(week) : ""}
            onChange={(v) => setWeek(Number(v))}
            options={
              weeks?.has_schedule
                ? weeks.weeks.map((w) => ({ value: String(w.week), label: `${w.week_name} (${w.start.slice(5)}–${w.end.slice(5)})` }))
                : [{ value: "", label: "no schedule" }]
            }
          />
        </Field>
        <div className="flex gap-2 pb-1 text-[12px]">
          <Link className="text-accent hover:underline" to="/trades">
            Trade Targets →
          </Link>
          <Link className="text-accent hover:underline" to="/waivers">
            Waivers →
          </Link>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <div className="text-[11px] uppercase tracking-wide text-ink-3">Projected week</div>
          <div className="mt-1 text-2xl font-bold tnum">{data.has_schedule ? f1(data.weekly_total) : "—"}</div>
          <div className="text-[11px] text-ink-3">FP/G × games{data.week_name ? ` · ${data.week_name}` : ""}</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wide text-ink-3">Games by day</div>
          {data.has_schedule && data.day_grid ? (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {data.day_grid.map((g) => (
                <span
                  key={g.day}
                  title={`${g.day}: ${g.games} of your players play${g.benched ? ` — ${g.benched} can't start (cap ${data.daily_slots})` : ""}`}
                  className={`rounded-md px-1.5 py-0.5 text-[11px] font-semibold tnum ${
                    g.benched ? "bg-warn/20 text-ink" : g.games === 0 ? "bg-surface-2 text-ink-3" : "bg-accent-soft text-accent"
                  }`}
                >
                  {dow(g.day)} {g.games}
                </span>
              ))}
            </div>
          ) : (
            <div className="mt-1 text-ink-3">no schedule</div>
          )}
          <div className="mt-1 text-[11px] text-ink-3">{data.daily_slots} startable slots/day</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wide text-ink-3">Flagged out</div>
          <div className={`mt-1 text-2xl font-bold tnum ${data.n_out ? "text-down" : ""}`}>{data.n_out}</div>
          <div className="text-[11px] text-ink-3">status overrides on my roster</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wide text-ink-3">Unfilled starting slots</div>
          {data.has_positions ? (
            unfilled.length ? (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {unfilled.map(([slot, n]) => (
                  <Chip key={slot} tone="warn">
                    {slot} ×{n}
                  </Chip>
                ))}
              </div>
            ) : (
              <div className="mt-1 text-2xl font-bold text-up">0</div>
            )
          ) : (
            <div className="mt-1 text-[12px] text-ink-3">needs the ESPN player map (Connect once in the Draft Room)</div>
          )}
        </Card>
      </div>

      <DataTable columns={cols} rows={rows} rowKey={(r) => r.PLAYER_ID} onRowClick={(r) => nav(`/players/${r.PLAYER_ID}`)} dense />
    </div>
  );
}
