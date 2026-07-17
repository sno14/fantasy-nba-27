// V5 — Matchup planner (docs/ui-views-plan.md): my week vs an opponent's,
// DESCRIPTIVELY — FP/G × games totals and the day-by-day volume grid. No win
// probability and no simulation, ever: the H2H variance layer was descoped
// (implementation-plan 19.4) and SD_PG must never become a weekly sigma.

import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { MatchupResponse, RosterWeekRow, WeeksResponse, useApi } from "../lib/api";
import { f1, signed } from "../lib/format";
import { Column, DataTable } from "../components/DataTable";
import { Card, Chip, EmptyNote, ErrorNote, Field, Select, Spinner } from "../components/ui";

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const dow = (iso: string) => DOW[new Date(iso + "T00:00:00").getDay()];

function sideCols(hasSchedule: boolean): Column<RosterWeekRow>[] {
  return [
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
        </span>
      ),
    },
    { key: "team", label: "Tm", hideBelow: "sm", render: (r) => r.TEAM_ABBREVIATION ?? "—", sortValue: (r) => r.TEAM_ABBREVIATION },
    { key: "fpts_pg", label: "FP/G", align: "right", sortValue: (r) => r.fpts_pg, render: (r) => f1(r.fpts_pg) },
    { key: "n_games", label: "G", align: "right", sortValue: (r) => r.n_games, render: (r) => (hasSchedule ? r.n_games : "—") },
    {
      key: "weekly_fpts",
      label: "Week FP",
      align: "right",
      sortValue: (r) => r.weekly_fpts,
      render: (r) => (hasSchedule ? <span className="font-semibold">{f1(r.weekly_fpts)}</span> : "—"),
    },
  ];
}

export default function Matchup() {
  const nav = useNavigate();
  const [week, setWeek] = useState<number | null>(null);
  const [opp, setOpp] = useState<number | null>(null);

  const weeks = useApi<WeeksResponse>("/api/weeks").data;
  const params = new URLSearchParams();
  if (week != null) params.set("week", String(week));
  if (opp != null) params.set("opp", String(opp));
  const qs = params.toString();
  const { data, error, loading } = useApi<MatchupResponse>(`/api/matchup${qs ? `?${qs}` : ""}`);

  useEffect(() => {
    if (week == null && data?.has_schedule && data.week != null) setWeek(data.week);
    if (opp == null && data?.opp_team_id != null) setOpp(data.opp_team_id);
  }, [data, week, opp]);

  const maxDay = useMemo(() => {
    if (!data?.me || !data.opp) return 1;
    return Math.max(1, ...data.me.day_grid.map((g) => g.games), ...data.opp.day_grid.map((g) => g.games));
  }, [data]);

  if (error) return <ErrorNote message={error} />;
  if (loading || !data) return <Spinner label="Loading matchup…" />;
  if (!data.has_matchup || !data.me || !data.opp)
    return (
      <Card>
        <EmptyNote>
          {data.note} → <Link className="text-accent underline" to="/room">Draft Room</Link> ·{" "}
          <Link className="text-accent underline" to="/power">Simulate</Link>
        </EmptyNote>
      </Card>
    );

  const myQuietDays = (data.days ?? []).filter(
    (d) =>
      (data.me!.day_grid.find((g) => g.day === d)?.games ?? 0) === 0 &&
      (data.opp!.day_grid.find((g) => g.day === d)?.games ?? 0) > 0,
  );

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
        <Field label="Opponent">
          <Select
            value={opp != null ? String(opp) : ""}
            onChange={(v) => setOpp(Number(v))}
            options={(data.opponents ?? []).map((t) => ({ value: String(t), label: `Team ${t}` }))}
          />
        </Field>
        <div className="flex items-center gap-2 pb-1 text-[12px] text-ink-3">
          {data.roster_source === "espn_live" && (
            <Chip tone="up" title={`Rosters are live ESPN (adds/drops), pulled ${data.rosters_asof ?? ""}. Refresh from the Waivers view.`}>
              live ESPN rosters
            </Chip>
          )}
          <span>
            projected totals = FP/G × games — <span className="font-medium">volume, not a win probability</span>
          </span>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <div className="text-[11px] uppercase tracking-wide text-ink-3">My week (Team {data.my_team_id})</div>
          <div className="mt-1 text-2xl font-bold tnum">{data.has_schedule ? f1(data.me.total) : "—"}</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wide text-ink-3">Volume gap</div>
          <div className={`mt-1 text-2xl font-bold tnum ${(data.gap ?? 0) > 0 ? "text-up" : (data.gap ?? 0) < 0 ? "text-down" : ""}`}>
            {data.has_schedule && data.gap != null ? signed(data.gap) : "—"}
          </div>
          {myQuietDays.length > 0 && (
            <div className="mt-1 text-[11px] text-ink-3">
              I'm idle while they play: {myQuietDays.map(dow).join(", ")} —{" "}
              <Link className="text-accent hover:underline" to="/waivers">
                stream those days →
              </Link>
            </div>
          )}
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wide text-ink-3">Opponent (Team {data.opp.team_id})</div>
          <div className="mt-1 text-2xl font-bold tnum">{data.has_schedule ? f1(data.opp.total) : "—"}</div>
        </Card>
      </div>

      {data.has_schedule && (
        <Card>
          <div className="mb-2 text-[11px] uppercase tracking-wide text-ink-3">
            Games per day (cap {data.daily_slots} starts) — me <span className="text-accent">■</span> vs them{" "}
            <span className="text-ink-3">■</span>
          </div>
          <div className="flex flex-wrap gap-3">
            {(data.days ?? []).map((d) => {
              const mine = data.me!.day_grid.find((g) => g.day === d);
              const theirs = data.opp!.day_grid.find((g) => g.day === d);
              return (
                <div key={d} className="flex flex-col items-center gap-1" title={`${d}: me ${mine?.games ?? 0}, them ${theirs?.games ?? 0}`}>
                  <div className="flex h-16 items-end gap-1">
                    <div className="w-3.5 rounded-t bg-accent" style={{ height: `${((mine?.games ?? 0) / maxDay) * 100}%` }} />
                    <div className="w-3.5 rounded-t bg-baseline" style={{ height: `${((theirs?.games ?? 0) / maxDay) * 100}%` }} />
                  </div>
                  <div className="text-[10px] font-semibold text-ink-3">{dow(d)}</div>
                  <div className="tnum text-[10px] text-ink-3">
                    {mine?.games ?? 0}·{theirs?.games ?? 0}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <div className="mb-1.5 text-[12px] font-bold uppercase tracking-wide text-ink-3">My roster</div>
          <DataTable
            columns={sideCols(!!data.has_schedule)}
            rows={data.me.rows}
            rowKey={(r) => r.PLAYER_ID}
            onRowClick={(r) => nav(`/players/${r.PLAYER_ID}`)}
            maxHeight="60vh"
            dense
          />
        </div>
        <div>
          <div className="mb-1.5 text-[12px] font-bold uppercase tracking-wide text-ink-3">Team {data.opp.team_id}</div>
          <DataTable
            columns={sideCols(!!data.has_schedule)}
            rows={data.opp.rows}
            rowKey={(r) => r.PLAYER_ID}
            onRowClick={(r) => nav(`/players/${r.PLAYER_ID}`)}
            maxHeight="60vh"
            dense
          />
        </div>
      </div>
    </div>
  );
}
