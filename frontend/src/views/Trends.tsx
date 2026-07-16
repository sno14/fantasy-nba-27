// V1 — Trends (docs/ui-views-plan.md): risers & fallers from the nightly ROS archive.
// Pure snapshot-vs-snapshot diffs; the sparkline is the trailing month of nightly boards.

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TrendsResponse, useApi } from "../lib/api";
import { f1, signed } from "../lib/format";
import { Column, DataTable } from "../components/DataTable";
import { Sparkline } from "../components/charts";
import { Card, Chip, EmptyNote, ErrorNote, Field, SearchInput, Segmented, Select, Spinner } from "../components/ui";

type Dir = "all" | "risers" | "fallers";

export default function Trends() {
  const nav = useNavigate();
  const [window, setWindow] = useState("14");
  const [dir, setDir] = useState<Dir>("all");
  const [team, setTeam] = useState("All");
  const [q, setQ] = useState("");
  const [topN, setTopN] = useState(100);

  const { data, error, loading } = useApi<TrendsResponse>(`/api/trends?window=${window}`);

  const teams = useMemo(
    () =>
      data
        ? ["All", ...Array.from(new Set(data.rows.map((r) => r.TEAM_ABBREVIATION).filter((t): t is string => !!t))).sort()]
        : ["All"],
    [data],
  );

  const rows = useMemo(() => {
    if (!data) return [];
    let base = data.rows;
    if (dir === "risers") base = base.filter((r) => r.fpts_delta > 0);
    if (dir === "fallers") base = base.filter((r) => r.fpts_delta < 0);
    if (team !== "All") base = base.filter((r) => r.TEAM_ABBREVIATION === team);
    if (q) base = base.filter((r) => r.PLAYER_NAME.toLowerCase().includes(q.toLowerCase()));
    return [...base].sort((a, b) => Math.abs(b.fpts_delta) - Math.abs(a.fpts_delta)).slice(0, topN);
  }, [data, dir, team, q, topN]);

  type Row = (typeof rows)[number];
  const cols = useMemo<Column<Row>[]>(
    () => [
      { key: "rank", label: "ROS #", align: "right", sortValue: (r) => r.rank },
      {
        key: "rank_delta",
        label: "Δ rank",
        title: "Rank change since the baseline snapshot (positive = rose)",
        align: "right",
        sortValue: (r) => r.rank_delta,
        render: (r) =>
          r.rank_delta === 0 ? (
            <span className="text-ink-3">—</span>
          ) : (
            <Chip tone={r.rank_delta > 0 ? "up" : "down"}>{signed(r.rank_delta, 0)}</Chip>
          ),
      },
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
      { key: "team", label: "Team", hideBelow: "sm", render: (r) => r.TEAM_ABBREVIATION ?? "—", sortValue: (r) => r.TEAM_ABBREVIATION },
      { key: "fpts_pg", label: "ROS FP/G", align: "right", sortValue: (r) => r.fpts_pg, render: (r) => f1(r.fpts_pg) },
      {
        key: "fpts_delta",
        label: `Δ FP/G (${window}d)`,
        title: "Projected ROS FP/G change over the window",
        align: "right",
        sortValue: (r) => r.fpts_delta,
        render: (r) => (
          <span className={r.fpts_delta > 0 ? "font-semibold text-up" : r.fpts_delta < 0 ? "font-semibold text-down" : "text-ink-3"}>
            {signed(r.fpts_delta)}
          </span>
        ),
      },
      {
        key: "mpg_delta",
        label: "Δ MPG",
        title: "Minutes change — the usual mechanism behind a fantasy move",
        align: "right",
        hideBelow: "md",
        sortValue: (r) => r.mpg_delta,
        render: (r) => (r.mpg_delta == null ? "—" : <span className={r.mpg_delta > 1 ? "text-up" : r.mpg_delta < -1 ? "text-down" : ""}>{signed(r.mpg_delta)}</span>),
      },
      {
        key: "spark",
        label: "Trend",
        title: "Projected ROS FP/G across the trailing nightly snapshots",
        render: (r) => <Sparkline values={r.spark.map((s) => s[1])} />,
      },
    ],
    [window],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Window">
          <Segmented
            value={window}
            onChange={setWindow}
            options={[
              { value: "7", label: "7d" },
              { value: "14", label: "14d" },
              { value: "30", label: "30d" },
            ]}
          />
        </Field>
        <Field label="Direction">
          <Segmented
            value={dir}
            onChange={(v) => setDir(v as Dir)}
            options={[
              { value: "all", label: "All" },
              { value: "risers", label: "Risers" },
              { value: "fallers", label: "Fallers" },
            ]}
          />
        </Field>
        <Field label="Team">
          <Select value={team} onChange={setTeam} options={teams.map((t) => ({ value: t, label: t }))} />
        </Field>
        <Field label="Show">
          <Select
            value={String(topN)}
            onChange={(v) => setTopN(Number(v))}
            options={[50, 100, 150, 250].map((n) => ({ value: String(n), label: `Top ${n}` }))}
          />
        </Field>
        <SearchInput value={q} onChange={setQ} placeholder="Search players…" className="w-52" />
        {data?.has_history && (
          <div className="pb-1 text-[12px] text-ink-3">
            {data.latest} vs {data.baseline} · {data.n_snapshots} snapshots
          </div>
        )}
      </div>

      {error && <ErrorNote message={error} />}
      {loading && <Spinner label="Loading trends…" />}
      {data && !data.has_history && (
        <Card>
          <EmptyNote>
            {data.note ?? "Trends need at least two nightly ROS snapshots."} The nightly pipeline
            (<code>scripts/update_daily.py</code>) crons from opening night; each run adds a snapshot.
          </EmptyNote>
        </Card>
      )}
      {data?.has_history && (
        <DataTable
          columns={cols}
          rows={rows}
          rowKey={(r) => r.PLAYER_ID}
          onRowClick={(r) => nav(`/players/${r.PLAYER_ID}`)}
          dense
        />
      )}
    </div>
  );
}
