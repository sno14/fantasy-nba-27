import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { RosRow, useApi } from "../lib/api";
import { f0, f1 } from "../lib/format";
import { Column, DataTable } from "../components/DataTable";
import { Card, Chip, EmptyNote, ErrorNote, Field, SearchInput, Select, Spinner } from "../components/ui";

export default function Ros() {
  const nav = useNavigate();
  const index = useApi<{ snapshots: string[] }>("/api/ros");
  const snaps = index.data?.snapshots ?? [];
  const [pick, setPick] = useState<string | null>(null);
  const date = pick ?? snaps[snaps.length - 1] ?? null;
  const snap = useApi<{ date: string; rows: RosRow[] }>(date ? `/api/ros/${date}` : null);
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    let r = snap.data?.rows ?? [];
    if (q) r = r.filter((x) => x.PLAYER_NAME.toLowerCase().includes(q.toLowerCase()));
    return r.slice(0, 300);
  }, [snap.data, q]);

  const disagreements = useMemo(() => {
    const r = (snap.data?.rows ?? []).filter((x) => x.rank_gap != null);
    return [...r].sort((a, b) => Math.abs(b.rank_gap!) - Math.abs(a.rank_gap!)).slice(0, 20);
  }, [snap.data]);

  const cols: Column<RosRow>[] = [
    { key: "rank", label: "#", align: "right", sortValue: (r) => r.rank, render: (r) => <b>{r.rank}</b> },
    {
      key: "name", label: "Player", sortValue: (r) => r.PLAYER_NAME,
      render: (r) => (
        <span className="flex items-center gap-2">
          <span className="font-medium">{r.PLAYER_NAME}</span>
          {r.status_override && (
            <Chip tone="warn" title={`config/overrides.yaml availability cap: ${r.status_override}`}>
              {r.status_override.replace(/_/g, " ")}
            </Chip>
          )}
        </span>
      ),
    },
    { key: "games_so_far", label: "Played", align: "right", title: "Games played so far this season", sortValue: (r) => r.games_so_far ?? null, render: (r) => f0(r.games_so_far) },
    { key: "gp", label: "ROS GP", align: "right", title: "Projected remaining games", sortValue: (r) => r.gp ?? null, render: (r) => f0(r.gp) },
    { key: "mpg", label: "MPG", align: "right", sortValue: (r) => r.mpg ?? null, render: (r) => f1(r.mpg), hideBelow: "md" },
    { key: "fpts_pg", label: "ROS FP/G", align: "right", sortValue: (r) => r.fpts_pg, render: (r) => <b>{f1(r.fpts_pg)}</b> },
    { key: "fpts_total", label: "ROS Total", align: "right", sortValue: (r) => r.fpts_total ?? null, render: (r) => f0(r.fpts_total), hideBelow: "sm" },
    { key: "naive_fpts_pg", label: "Naive FP/G", align: "right", title: "The naive-updater benchmark line", sortValue: (r) => r.naive_fpts_pg ?? null, render: (r) => f1(r.naive_fpts_pg), hideBelow: "lg" },
    {
      key: "rank_gap", label: "Δ vs naive", align: "right",
      title: "naive rank − model rank: positive = our model is higher on the player",
      sortValue: (r) => r.rank_gap ?? null,
      render: (r) =>
        r.rank_gap == null || r.rank_gap === 0 ? (
          <span className="text-ink-3">0</span>
        ) : (
          <span className={r.rank_gap > 0 ? "text-up" : "text-down"}>
            {r.rank_gap > 0 ? "+" : ""}{r.rank_gap}
          </span>
        ),
    },
  ];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight">ROS — in-season board</h1>
          <p className="text-[13px] text-ink-2">
            Nightly remaining-of-season snapshots from <code className="text-xs">update_daily.py</code>, with
            the naive-updater disagreement signal.
          </p>
        </div>
        {snaps.length > 0 && (
          <Field label="Snapshot">
            <Select value={date ?? ""} onChange={setPick}
              options={[...snaps].reverse().map((s) => ({ value: s, label: s }))} />
          </Field>
        )}
      </header>

      {index.error && <ErrorNote message={index.error} />}
      {index.data && snaps.length === 0 && (
        <EmptyNote>
          No nightly ROS snapshots yet — they land in <code>data/processed/ros_board/</code> once{" "}
          <code>update_daily.py</code> crons from opening night.
        </EmptyNote>
      )}

      {snap.loading && <Spinner label="Loading snapshot…" />}
      {snap.data && (
        <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
          <div className="space-y-2">
            <SearchInput value={q} onChange={setQ} placeholder="Search player…" className="w-56" />
            <DataTable columns={cols} rows={rows} rowKey={(r) => r.PLAYER_ID ?? r.PLAYER_NAME}
              onRowClick={(r) => r.PLAYER_ID && nav(`/players/${r.PLAYER_ID}`)} defaultSort="rank" dense />
            <p className="text-xs text-ink-3">
              {snap.data.rows.length.toLocaleString()} players · as of <b>{snap.data.date}</b>
            </p>
          </div>
          <Card className="h-fit p-4">
            <h2 className="text-[13px] font-semibold">Model vs naive updater</h2>
            <p className="mb-2 text-xs text-ink-3">
              Biggest rank disagreements — the standing daily signal. Positive = our as-of model
              is higher on the player than naive shrinkage.
            </p>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wide text-ink-3">
                  <th className="py-1">Player</th>
                  <th className="text-right">Model</th>
                  <th className="text-right">Naive</th>
                  <th className="text-right">Δ</th>
                </tr>
              </thead>
              <tbody>
                {disagreements.map((r) => (
                  <tr key={r.PLAYER_NAME} className="cursor-pointer border-t border-bdr/60 hover:bg-accent-soft/60"
                      onClick={() => r.PLAYER_ID && nav(`/players/${r.PLAYER_ID}`)}>
                    <td className="py-1 font-medium">{r.PLAYER_NAME}</td>
                    <td className="tnum text-right">{r.rank}</td>
                    <td className="tnum text-right">{r.naive_rank}</td>
                    <td className={`tnum text-right font-semibold ${r.rank_gap! > 0 ? "text-up" : "text-down"}`}>
                      {r.rank_gap! > 0 ? "+" : ""}{r.rank_gap}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </div>
  );
}
