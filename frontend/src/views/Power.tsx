// League power rankings: per-team draft strength aggregated from the drafted rosters (the
// same in-session picks the Draft Room holds). Descriptive, like the room — these sum
// independent per-player projections into a team-strength index, not a win probability
// (that needs the gated H2H simulator). A "Simulate mock draft" action fills every team by
// best-available snake so the table has data to preview before draft night.

import { useCallback, useEffect, useState } from "react";
import { PowerResponse, PowerTeam, get } from "../lib/api";
import { f0, f1 } from "../lib/format";
import { Column, DataTable } from "../components/DataTable";
import { RangeStrip, RiskMeter } from "../components/charts";
import { Card, Chip, EmptyNote, ErrorNote, Spinner } from "../components/ui";

async function post(path: string) {
  const res = await fetch(path, { method: "POST" });
  if (!res.ok) {
    const b = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(b?.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function Bar({ v, min, max }: { v: number; min: number; max: number }) {
  const frac = max > min ? (v - min) / (max - min) : 1;
  return (
    <span className="flex items-center justify-end gap-2">
      <span className="h-1.5 w-24 overflow-hidden rounded-full bg-grid">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${18 + frac * 82}%` }} />
      </span>
      <span className="tnum font-semibold">{f0(v)}</span>
    </span>
  );
}

export default function Power() {
  const [st, setSt] = useState<PowerResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setSt(await get<PowerResponse>("/api/draft/power", true));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (path: string) => {
    setBusy(true);
    try {
      await post(path);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const teams = st?.teams ?? [];
  const drafted = (st?.n_picks ?? 0) > 0 && teams.length > 0;
  const seasonVals = teams.map((t) => t.total_fpts_season);
  const sMin = Math.min(...seasonVals, 0);
  const sMax = Math.max(...seasonVals, 1);
  const rMin = Math.min(...teams.map((t) => t.floor_season), 0);
  const rMax = Math.max(...teams.map((t) => t.ceiling_season), 1);
  const anyChronic = teams.some((t) => t.n_chronic > 0);
  const mine = teams.find((t) => t.is_me);

  const cols: Column<PowerTeam>[] = [
    {
      key: "rank", label: "#", align: "right",
      sortValue: (t) => t.power_rank,
      render: (t) => <span className="font-bold">{t.power_rank}</span>,
    },
    {
      key: "team", label: "Team",
      sortValue: (t) => t.team_id,
      render: (t) => (
        <span className="flex items-center gap-2">
          <span className="font-medium">Team {t.team_id}</span>
          {t.is_me && <Chip tone="accent" title="Your team">You</Chip>}
        </span>
      ),
    },
    {
      key: "players", label: "P", align: "right", title: "Players drafted",
      sortValue: (t) => t.n_players, render: (t) => t.n_players, hideBelow: "md",
    },
    {
      key: "season", label: "Season FP", align: "right",
      title: "Projected total fantasy points for the season (Σ FP/G × games) — the power-rank metric",
      sortValue: (t) => t.total_fpts_season,
      render: (t) => <Bar v={t.total_fpts_season} min={sMin} max={sMax} />,
    },
    {
      key: "totpg", label: "Total FP/G", align: "right",
      title: "Sum of every rostered player's projected FP/G",
      sortValue: (t) => t.total_fpts_pg, render: (t) => f1(t.total_fpts_pg),
    },
    {
      key: "avg", label: "Avg FP/G", align: "right", title: "Mean projected FP/G per player",
      sortValue: (t) => t.avg_fpts_pg, render: (t) => f1(t.avg_fpts_pg), hideBelow: "md",
    },
    {
      key: "starters", label: "Starters", align: "right",
      title: "FP/G of the strongest legal starting lineup (bench excluded)",
      sortValue: (t) => t.starters_fpts_pg, render: (t) => f1(t.starters_fpts_pg), hideBelow: "lg",
    },
    {
      key: "star", label: "Star pwr", align: "right",
      title: "Combined FP/G of the team's top 3 players — elite-talent concentration",
      sortValue: (t) => t.star_power, render: (t) => f1(t.star_power), hideBelow: "lg",
    },
    {
      key: "depth", label: "Depth", align: "right",
      title: "Players projected above replacement level — startable-caliber roster spots",
      sortValue: (t) => t.depth, render: (t) => t.depth, hideBelow: "lg",
    },
    {
      key: "range", label: "Floor → Ceiling",
      title: "Summed p10 → p90 season totals (indicative spread; ignores cross-player correlation)",
      render: (t) => (
        <RangeStrip p10={t.floor_season} p50={t.total_fpts_season} p90={t.ceiling_season} min={rMin} max={rMax} />
      ),
      hideBelow: "xl",
    },
    {
      key: "risk", label: "Risk", align: "right", title: "Mean injury-risk of the roster (lower is safer)",
      sortValue: (t) => t.mean_risk ?? null,
      render: (t) => (t.mean_risk != null ? <RiskMeter value={t.mean_risk} /> : "—"),
      hideBelow: "sm",
    },
    {
      key: "best", label: "Top player",
      sortValue: (t) => t.best_fpts_pg ?? null,
      render: (t) => (
        <span className="text-ink-2">
          {t.best_player ?? "—"}
          {t.best_fpts_pg != null && <span className="ml-1 text-[11px] text-ink-3">{f1(t.best_fpts_pg)}</span>}
        </span>
      ),
      hideBelow: "lg",
    },
  ];
  if (anyChronic)
    cols.splice(11, 0, {
      key: "chronic", label: "Inj", align: "right", title: "Players flagged with a chronic injury history",
      sortValue: (t) => t.n_chronic,
      render: (t) => (t.n_chronic > 0 ? <Chip tone="down">{t.n_chronic}</Chip> : null),
      hideBelow: "md",
    });
  if (st?.has_positions)
    cols.splice(cols.length - 1, 0, {
      key: "lineup", label: "Open", align: "right", title: "Unfilled starting-lineup slots (0 = complete)",
      sortValue: (t) => t.unfilled_starts,
      render: (t) => (t.unfilled_starts > 0 ? <Chip tone="warn">{t.unfilled_starts}</Chip> : <span className="text-up">✓</span>),
      hideBelow: "md",
    });

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight">Power Rankings</h1>
          <p className="text-[13px] text-ink-2">
            Every team's drafted roster, ranked by projected season fantasy points. Reads the
            live Draft Room picks — draft in there (manual or ESPN) and this updates.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => act("/api/draft/simulate")}
            disabled={busy}
            className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-accent-ink transition-opacity disabled:opacity-40"
          >
            {drafted ? "Re-simulate mock draft" : "Simulate mock draft"}
          </button>
          {drafted && (
            <button
              onClick={() => act("/api/draft/reset")}
              disabled={busy}
              className="rounded-lg border border-bdr px-3 py-1.5 text-xs font-medium text-ink-2 transition-colors hover:bg-surface-2 disabled:opacity-40"
            >
              Clear draft
            </button>
          )}
        </div>
      </header>

      {err && <ErrorNote message={err} />}
      {!st && !err && <Spinner label="Loading…" />}

      {st && !drafted && (
        <EmptyNote>
          <p className="mb-3">
            No teams have drafted yet. Enter picks in the <b>Draft Room</b>, or hit{" "}
            <b>Simulate mock draft</b> above to auto-fill all {st.n_teams} teams by best-available
            and preview how the league would shake out.
          </p>
        </EmptyNote>
      )}

      {st && drafted && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
            <Chip tone="neutral">{st.n_teams} teams · {st.n_picks} picks</Chip>
            {mine && (
              <Chip tone="accent" title="Where your team ranks">
                Your team: #{mine.power_rank} of {teams.length}
              </Chip>
            )}
            {st.synthetic_teams && (
              <Chip tone="warn" title="No ESPN connection — teams are 1..N stand-ins and there is no slot eligibility, so positional lineup completeness is hidden">
                mock teams · no positions
              </Chip>
            )}
          </div>

          <DataTable columns={cols} rows={teams} rowKey={(t) => t.team_id} />

          <Card className="p-4 text-[13px] text-ink-2">
            <h2 className="mb-1 text-[13px] font-semibold text-ink">How the columns read</h2>
            <ul className="space-y-1 text-ink-2">
              <li><b>Season FP</b> — projected total points (rate × durability); the ranking metric.</li>
              <li><b>Total / Avg FP/G</b> — roster scoring rate, summed and per-player.</li>
              <li><b>Starters</b> — FP/G of the best legal lineup; <b>Star pwr</b> — top-3 FP/G (studs win H2H weeks); <b>Depth</b> — startable-caliber players (streaming cushion).</li>
              <li><b>Floor → Ceiling</b> and <b>Risk</b> — summed season-total spread and mean injury risk (indicative; independent per-player draws, so read as a guide, not a simulated roster distribution).</li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
