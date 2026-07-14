import { useMemo, useState } from "react";
import { DatasetPage, useApi } from "../lib/api";
import { Card, EmptyNote, ErrorNote, Field, SearchInput, Select, Spinner } from "../components/ui";

export default function DataBrowser() {
  const index = useApi<{ datasets: { name: string; label: string; cached: boolean }[] }>("/api/datasets");
  const cached = useMemo(() => index.data?.datasets.filter((d) => d.cached) ?? [], [index.data]);
  const [pick, setPick] = useState<string | null>(null);
  const name = pick ?? cached[0]?.name ?? null;
  const [season, setSeason] = useState("All");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const limit = 100;

  const params = new URLSearchParams();
  if (season !== "All") params.set("season", season);
  if (q) params.set("q", q);
  params.set("offset", String(page * limit));
  params.set("limit", String(limit));
  const { data, error, loading } = useApi<DatasetPage>(name ? `/api/datasets/${name}?${params}` : null);

  const setAndReset = (fn: (v: string) => void) => (v: string) => {
    fn(v);
    setPage(0);
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-lg font-bold tracking-tight">Data browser</h1>
        <p className="text-[13px] text-ink-2">The raw parquet caches the models read (local-only, gitignored).</p>
      </header>

      {index.error && <ErrorNote message={index.error} />}
      {index.data && cached.length === 0 && (
        <EmptyNote>
          Nothing cached yet — pull data with <code>python scripts/pull_data.py</code> (or{" "}
          <code>python scripts/dev_fixtures.py</code> for synthetic dev fixtures).
        </EmptyNote>
      )}

      {name && (
        <>
          <div className="flex flex-wrap items-end gap-2.5">
            <Field label="Dataset">
              <Select value={name} onChange={setAndReset(setPick)}
                options={cached.map((d) => ({ value: d.name, label: d.label }))} />
            </Field>
            {(data?.seasons.length ?? 0) > 0 && (
              <Field label="Season">
                <Select value={season} onChange={setAndReset(setSeason)}
                  options={[{ value: "All", label: "All seasons" }, ...(data?.seasons ?? []).map((s) => ({ value: s, label: s }))]} />
              </Field>
            )}
            <SearchInput value={q} onChange={setAndReset(setQ)} placeholder="Search player…" className="w-52" />
            {data && (
              <span className="mb-1.5 ml-auto text-xs text-ink-3">
                {data.total.toLocaleString()} rows × {data.columns.length} cols
              </span>
            )}
          </div>

          {loading && <Spinner label="Loading…" />}
          {error && <ErrorNote message={error} />}
          {data && (
            <>
              <Card className="scroll-thin overflow-auto" >
                <div style={{ maxHeight: "calc(100vh - 300px)" }} className="scroll-thin overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 z-[5]">
                      <tr className="bg-surface-2 text-left text-[10px] uppercase tracking-wide text-ink-3">
                        {data.columns.map((c) => (
                          <th key={c} className="whitespace-nowrap border-b border-bdr px-2.5 py-1.5 font-semibold">{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.rows.map((r, i) => (
                        <tr key={i} className="border-b border-bdr/50 last:border-b-0">
                          {data.columns.map((c) => (
                            <td key={c} className="tnum whitespace-nowrap px-2.5 py-1">
                              {r[c] == null ? <span className="text-ink-3">—</span> : String(r[c])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <div className="flex items-center gap-3 text-xs text-ink-2">
                <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}
                  className="h-7 rounded-lg border border-bdr px-2.5 font-medium transition-colors hover:bg-surface-2 disabled:opacity-40">
                  ← Prev
                </button>
                <span className="tnum">
                  {page * limit + 1}–{Math.min((page + 1) * limit, data.total)} of {data.total.toLocaleString()}
                </span>
                <button disabled={(page + 1) * limit >= data.total} onClick={() => setPage((p) => p + 1)}
                  className="h-7 rounded-lg border border-bdr px-2.5 font-medium transition-colors hover:bg-surface-2 disabled:opacity-40">
                  Next →
                </button>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
