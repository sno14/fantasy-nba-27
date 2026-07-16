import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMeta } from "../App";
import { WeeklyResponse, WeeksResponse, useApi } from "../lib/api";
import { f1 } from "../lib/format";
import { Column, DataTable } from "../components/DataTable";
import { Card, Chip, EmptyNote, ErrorNote, Field, SearchInput, Select, Spinner, Toggle } from "../components/ui";

// ESPN default lineup: PG/SG/SF/PF/C/G/F + 3×UTIL = 10 startable slots per day. This is
// the reference the daily-load panel checks against — more of your players on one day than
// startable slots means you can't play them all that day.
const DAILY_SLOTS = 10;

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const asDate = (iso: string) => new Date(iso + "T00:00:00");
const dow = (iso: string) => DOW[asDate(iso).getDay()];
const md = (iso: string) => {
  const d = asDate(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
};

interface Row {
  PLAYER_ID: number;
  PLAYER_NAME: string;
  TEAM_ABBREVIATION: string | null;
  rank: number;
  fpts_pg: number;
  gp: number | null;
  games: string[];
  activeN: number;
  activeWeekly: number;
}

export default function Weekly() {
  const meta = useMeta();
  const nav = useNavigate();

  const [analyst, setAnalyst] = useState(true);
  const [team, setTeam] = useState("All");
  const [q, setQ] = useState("");
  const [topN, setTopN] = useState(100);
  const [week, setWeek] = useState<number | null>(null);
  const [activeDays, setActiveDays] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<Set<number>>(new Set());

  const weeksResp = useApi<WeeksResponse>("/api/weeks");
  const weeks = weeksResp.data;

  // Default to the first scheduled week once the index loads.
  useEffect(() => {
    if (weeks?.has_schedule && week == null && weeks.weeks.length) setWeek(weeks.weeks[0].week);
  }, [weeks, week]);

  const weeklyUrl = week != null ? `/api/weekly?week=${week}&analyst=${analyst}` : null;
  const { data, error, loading } = useApi<WeeklyResponse>(weeklyUrl);

  // A new week (or analyst toggle) resets the day filter to the full week.
  const daysKey = data?.days.join(",") ?? "";
  useEffect(() => {
    if (data) setActiveDays(new Set(data.days));
  }, [daysKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleDay = (d: string) =>
    setActiveDays((cur) => {
      const next = new Set(cur);
      next.has(d) ? next.delete(d) : next.add(d);
      return next;
    });

  const toggleSel = (id: number) =>
    setSel((cur) => {
      const next = new Set(cur);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const allDaysOn = !!data && data.days.every((d) => activeDays.has(d));

  // Re-total each player over only the toggled-on days.
  const withActive = (games: string[], fpg: number) => {
    const n = games.filter((d) => activeDays.has(d)).length;
    return { activeN: n, activeWeekly: Math.round(fpg * n * 10) / 10 };
  };

  const rows = useMemo<Row[]>(() => {
    if (!data) return [];
    let base: Row[] = data.rows.map((r) => ({
      PLAYER_ID: r.PLAYER_ID,
      PLAYER_NAME: r.PLAYER_NAME,
      TEAM_ABBREVIATION: r.TEAM_ABBREVIATION,
      rank: r.rank,
      fpts_pg: r.fpts_pg,
      gp: r.gp,
      games: r.games,
      ...withActive(r.games, r.fpts_pg),
    }));
    if (q) base = base.filter((r) => r.PLAYER_NAME.toLowerCase().includes(q.toLowerCase()));
    if (team !== "All") base = base.filter((r) => r.TEAM_ABBREVIATION === team);
    base.sort((a, b) => b.activeWeekly - a.activeWeekly);
    return base.slice(0, topN);
  }, [data, activeDays, q, team, topN]);

  // The selection summary works off the full response (a picked player can sit outside topN).
  const selected = useMemo(() => {
    if (!data) return [];
    return data.rows
      .filter((r) => sel.has(r.PLAYER_ID))
      .map((r) => ({ ...r, ...withActive(r.games, r.fpts_pg) }));
  }, [data, sel, activeDays]);

  const selTotals = useMemo(() => {
    const weekly = selected.reduce((s, r) => s + r.activeWeekly, 0);
    const games = selected.reduce((s, r) => s + r.activeN, 0);
    const perDay = (data?.days ?? [])
      .filter((d) => activeDays.has(d))
      .map((d) => ({ day: d, count: selected.filter((r) => r.games.includes(d)).length }));
    return { weekly: Math.round(weekly * 10) / 10, games, perDay };
  }, [selected, data, activeDays]);

  const cols = useMemo<Column<Row>[]>(() => {
    const dayCols: Column<Row>[] = (data?.days ?? []).map((day) => ({
      key: `d${day}`,
      align: "center",
      label: (
        <button
          onClick={() => toggleDay(day)}
          title={`Toggle ${dow(day)} ${md(day)} — click to count / drop this day`}
          className={`flex flex-col items-center leading-none ${activeDays.has(day) ? "text-ink-2" : "text-ink-3/50 line-through"}`}
        >
          <span className="text-[10px] font-semibold uppercase">{dow(day)}</span>
          <span className="text-[9px]">{md(day)}</span>
        </button>
      ),
      render: (r) => {
        if (!r.games.includes(day)) return <span className="text-ink-3/25">·</span>;
        const on = activeDays.has(day);
        return (
          <span
            title={`${r.PLAYER_NAME} plays ${dow(day)} ${md(day)}${on ? "" : " (day dropped)"}`}
            className={on ? "text-accent" : "text-ink-3/40"}
          >
            ●
          </span>
        );
      },
    }));

    return [
      {
        key: "rank", label: "#", align: "right", title: "Season-long board rank",
        sortValue: (r) => r.rank,
        render: (r) => <span className="text-ink-3">{r.rank}</span>,
      },
      {
        key: "player", label: "Player",
        sortValue: (r) => r.PLAYER_NAME,
        render: (r) => (
          <span className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={sel.has(r.PLAYER_ID)}
              onChange={() => toggleSel(r.PLAYER_ID)}
              onClick={(e) => e.stopPropagation()}
              title="Add to the weekly selection"
              className="h-3.5 w-3.5 accent-[var(--accent)]"
            />
            <span className="font-medium">{r.PLAYER_NAME}</span>
            <span className="text-[11px] text-ink-3">{r.TEAM_ABBREVIATION ?? ""}</span>
          </span>
        ),
      },
      {
        key: "fpg", label: "FP/G", align: "right", title: "Projected fantasy points per game",
        sortValue: (r) => r.fpts_pg,
        render: (r) => f1(r.fpts_pg),
      },
      ...dayCols,
      {
        key: "games", label: "G", align: "right", title: "Games in the counted days",
        sortValue: (r) => r.activeN,
        render: (r) => <span className="font-medium">{r.activeN}</span>,
      },
      {
        key: "weekly", label: "Week FP", align: "right",
        title: "Projected fantasy points this week = FP/G × games in the counted days",
        sortValue: (r) => r.activeWeekly,
        render: (r) => <span className="font-semibold text-accent">{f1(r.activeWeekly)}</span>,
      },
    ];
  }, [data, activeDays, sel]);

  if (!meta) return <Spinner label="Loading…" />;

  const wk = weeks?.weeks.find((w) => w.week === week);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight">Weekly Planner</h1>
          <p className="text-[13px] text-ink-2">
            Who scores most <b>this week</b>: projected FP/G × games scheduled. Four games at 25
            (100) beats three at 30 (90) — this is where waiver-wire volume wins.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2.5">
          <Field label="Week">
            <Select
              value={week != null ? String(week) : ""}
              onChange={(v) => setWeek(Number(v))}
              options={(weeks?.weeks ?? []).map((w) => ({
                value: String(w.week),
                label: `${w.week_name} · ${md(w.start)}–${md(w.end)}`,
              }))}
            />
          </Field>
          <Toggle checked={analyst} onChange={setAnalyst} label="Analyst layer (B)" />
        </div>
      </header>

      {weeksResp.loading && <Spinner label="Loading the schedule…" />}
      {weeks && !weeks.has_schedule && (
        <EmptyNote>
          No schedule is cached for {weeks.target} yet. Run{" "}
          <code className="rounded bg-surface-2 px-1">python scripts/pull_schedule.py</code> — the
          2026-27 schedule publishes ~mid-August, so this view lights up then.
        </EmptyNote>
      )}

      {weeks?.has_schedule && (
        <>
          <div className="flex flex-wrap items-center gap-2.5">
            <SearchInput value={q} onChange={setQ} placeholder="Search player…" className="w-56" />
            <Select value={team} onChange={setTeam}
              options={[{ value: "All", label: "All teams" }, ...(data?.teams ?? []).map((t) => ({ value: t, label: t }))]} />
            <Select value={String(topN)} onChange={(v) => setTopN(Number(v))}
              options={[25, 50, 100, 150, 250].map((n) => ({ value: String(n), label: `Top ${n}` }))} />
            <div className="ml-auto flex items-center gap-2 text-xs text-ink-2">
              {wk && (
                <Chip tone="neutral" title="NBA games scheduled this week">
                  {wk.n_games} games · {md(wk.start)}–{md(wk.end)}
                </Chip>
              )}
              {!allDaysOn && (
                <button
                  onClick={() => data && setActiveDays(new Set(data.days))}
                  className="rounded-lg border border-bdr px-2 py-1 font-medium hover:bg-surface-2"
                >
                  Reset days
                </button>
              )}
            </div>
          </div>

          <p className="text-xs text-ink-3">
            Tip: click a weekday header to drop days you won't set a lineup for — Games and Week FP
            recount over the days left on. Tick players to build a streaming group below.
          </p>

          {selected.length > 0 && (
            <Card className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-4">
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-ink-3">Selection</div>
                    <div className="text-sm font-semibold">{selected.length} players</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-ink-3">Total Week FP</div>
                    <div className="text-sm font-semibold text-accent">{f1(selTotals.weekly)}</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-ink-3">Total games</div>
                    <div className="text-sm font-semibold">{selTotals.games}</div>
                  </div>
                </div>
                <button onClick={() => setSel(new Set())} className="text-xs text-ink-3 hover:text-ink-2">
                  Clear
                </button>
              </div>
              <div className="mt-3">
                <div className="mb-1 text-[11px] uppercase tracking-wide text-ink-3">
                  Games per day (vs {DAILY_SLOTS} startable slots)
                </div>
                <div className="flex gap-1.5">
                  {selTotals.perDay.map(({ day, count }) => {
                    const over = count > DAILY_SLOTS;
                    return (
                      <div key={day} className="flex flex-1 flex-col items-center gap-1">
                        <div className="flex h-16 w-full items-end rounded bg-surface-2" title={`${dow(day)} ${md(day)}: ${count} selected player(s) play`}>
                          <div
                            className={`w-full rounded ${over ? "bg-down" : "bg-accent"}`}
                            style={{ height: `${Math.min(100, (count / Math.max(DAILY_SLOTS, count, 1)) * 100)}%` }}
                          />
                        </div>
                        <div className="text-[10px] font-semibold text-ink-2">{count}</div>
                        <div className="text-[9px] leading-none text-ink-3">{dow(day)}</div>
                      </div>
                    );
                  })}
                </div>
                {selTotals.perDay.some((d) => d.count > DAILY_SLOTS) && (
                  <p className="mt-2 text-[11px] text-down">
                    Some days have more of your players than startable slots — you can't play them
                    all those days, so the raw Week FP over-counts.
                  </p>
                )}
              </div>
            </Card>
          )}

          {error && <ErrorNote message={error} />}
          {loading && <Spinner label={`Loading ${wk?.week_name ?? "the week"}…`} />}
          {!loading && data && rows.length === 0 && <EmptyNote>No players match the current filters.</EmptyNote>}

          {!loading && data && rows.length > 0 && (
            <>
              {/* Rows arrive pre-sorted by Week FP (desc); no defaultSort so DataTable keeps
                  that order until the user clicks a header to re-sort. */}
              <DataTable
                columns={cols}
                rows={rows}
                rowKey={(r) => r.PLAYER_ID}
                onRowClick={(r) => nav(`/players/${r.PLAYER_ID}`)}
              />
              <p className="text-xs text-ink-3">
                Week FP = FP/G × games in the counted days. Ranked by Week FP; click a row for the
                player page. FP/G comes from the {meta.current_target} board
                {analyst ? " (analyst layer on)" : ""}.
              </p>
            </>
          )}
        </>
      )}
    </div>
  );
}
