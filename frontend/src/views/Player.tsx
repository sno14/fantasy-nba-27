import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useCompare } from "../App";
import { PlayerDetail, useApi } from "../lib/api";
import { f0, f1, parseAction, signed } from "../lib/format";
import { BarChart, LineChart, RangeStrip } from "../components/charts";
import { Card, Chip, ErrorNote, SearchInput, Spinner } from "../components/ui";
import { radarName, radarTone, targetTitle, useDraftTargets } from "../lib/draftRadar";

function StatCard({ label, value, sub, title }: { label: string; value: string; sub?: string; title?: string }) {
  return (
    <Card className="px-4 py-3" >
      <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-3" title={title}>{label}</div>
      <div className="tnum mt-0.5 text-xl font-bold tracking-tight">{value}</div>
      {sub && <div className="text-[11px] text-ink-3">{sub}</div>}
    </Card>
  );
}

export default function Player() {
  const { id } = useParams();
  const nav = useNavigate();
  const compare = useCompare();
  const { targets, edit: editTarget } = useDraftTargets();
  const [q, setQ] = useState("");

  const idx = useApi<{ rows: { PLAYER_ID: number; PLAYER_NAME: string; TEAM_ABBREVIATION: string | null; rank: number }[] }>("/api/players");
  const detail = useApi<PlayerDetail>(id ? `/api/player/${id}` : null);

  const matches = useMemo(() => {
    const rows = idx.data?.rows ?? [];
    if (!q) return rows.slice(0, 12);
    return rows.filter((r) => r.PLAYER_NAME.toLowerCase().includes(q.toLowerCase())).slice(0, 12);
  }, [idx.data, q]);

  // --------------------------------------------------------- no player selected
  if (!id) {
    return (
      <div className="mx-auto max-w-xl space-y-4 pt-8">
        <h1 className="text-lg font-bold tracking-tight">Players</h1>
        <SearchInput value={q} onChange={setQ} placeholder="Search any projected player…" />
        {idx.loading && <Spinner />}
        <div className="divide-y divide-bdr/60 overflow-hidden rounded-xl border border-bdr bg-surface">
          {matches.map((r) => (
            <button key={r.PLAYER_ID} onClick={() => nav(`/players/${r.PLAYER_ID}`)}
              className="flex w-full items-center justify-between px-4 py-2.5 text-left transition-colors hover:bg-accent-soft/60">
              <span className="font-medium">{r.PLAYER_NAME}
                <span className="ml-2 text-xs text-ink-3">{r.TEAM_ABBREVIATION}</span>
              </span>
              <span className="tnum text-xs text-ink-3">#{r.rank}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (detail.loading) return <Spinner label="Loading player…" />;
  if (detail.error) return <ErrorNote message={detail.error} />;
  if (!detail.data) return null;

  const d = detail.data;
  const p = d.projection;
  const action = parseAction(p.analyst_action as string | null);
  const inCompare = compare.ids.includes(Number(id));
  const priority = targets[String(p.PLAYER_ID)];

  const fpgSeries = [{
    name: "FP/G", color: "var(--series-1)",
    points: d.career.map((c) => ({ x: 0, label: c.SEASON, y: c.FPTS ?? null })),
  }];
  const mpgSeries = [{
    name: "MPG", color: "var(--series-2)",
    points: d.career.map((c) => ({ x: 0, label: c.SEASON, y: c.MPG ?? null })),
  }];
  const gameMinutes = d.game_log.map((g, i) => ({
    label: `${i + 1}`, y: g.MIN, sub: `${g.GAME_DATE} · ${g.PTS} pts`,
  }));
  const minMean = d.game_log.length ? d.game_log.reduce((s, g) => s + g.MIN, 0) / d.game_log.length : 0;
  const minStd = d.game_log.length
    ? Math.sqrt(d.game_log.reduce((s, g) => s + (g.MIN - minMean) ** 2, 0) / d.game_log.length)
    : 0;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button onClick={() => nav(-1)} className="grid h-8 w-8 place-items-center rounded-lg border border-bdr text-ink-2 transition-colors hover:bg-surface-2" title="Back">
            ←
          </button>
          <div>
            <h1 className="flex items-center gap-2.5 text-lg font-bold tracking-tight">
              {p.PLAYER_NAME}
              <span className="text-sm font-medium text-ink-3">{p.TEAM_ABBREVIATION}</span>
              {p.tier != null && <Chip tone="accent">Tier {p.tier}</Chip>}
              {action && (
                <Chip tone={action.value > 0 ? "up" : "down"}
                  title={`Analyst layer: ${p.analyst_category} · ${p.analyst_date} · model rank ${p.model_rank}`}>
                  analyst {action.value > 0 ? "▲" : "▼"} {Math.abs(action.value).toFixed(1)}
                </Chip>
              )}
              {p.radar_label && <Chip tone={radarTone(p.radar_label)} title={p.radar_reasons || undefined}>{radarName(p.radar_label)}</Chip>}
            </h1>
            <p className="text-[13px] text-ink-2">2026-27 projection · learned model · board B (analyst layer applied)</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={() => editTarget(p)} title={targetTitle(p, priority)}
            className={`h-8 rounded-lg px-3 text-[13px] font-semibold ${priority ? "bg-warn/15 text-warn" : "border border-bdr text-ink-2 hover:bg-surface-2"}`}>
            {priority ? `★ ${priority.takeBy ? `Take by ${priority.takeBy}` : "Priority target"}` : "☆ Add target"}
          </button>
          <button
            onClick={() => compare.toggle(Number(id), p.PLAYER_NAME)}
            className={`h-8 rounded-lg px-3 text-[13px] font-semibold transition-colors ${
              inCompare ? "bg-accent text-accent-ink" : "border border-bdr text-ink-2 hover:bg-surface-2"
            }`}
          >
            {inCompare ? "✓ In compare" : "+ Compare"}
          </button>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-8">
        <StatCard label="Proj rank" value={`#${f0(p.rank as number)}`} sub={action ? `model #${f0(p.model_rank as number)}` : undefined} />
        <StatCard label="Age" value={f0(p.target_age as number)} />
        <StatCard label="Proj GP" value={f0(p.gp as number)} />
        <StatCard label="Proj MPG" value={f1(p.mpg as number)} />
        <StatCard label="FP / game" value={f1(p.fpts_pg as number)} />
        <StatCard label="2025-26 FP/G" value={f1(p.previous_fpts_pg)} />
        <StatCard label="Projected change" value={p.fpts_pg_change == null ? "—" : signed(p.fpts_pg_change)} />
        <StatCard label="Median total" value={f0(p.fpts_median as number)} sub={`risk ${(p.risk as number).toFixed(2)}`} />
      </div>

      <Card className="flex flex-wrap items-center gap-4 px-4 py-3">
        <span className="text-[13px] font-semibold text-ink-2">Season range</span>
        <div className="flex items-center gap-3 text-[13px]">
          <span className="tnum">floor <b>{f0(p.fpts_p10 as number)}</b></span>
          <RangeStrip p10={p.fpts_p10 as number} p50={p.fpts_median as number} p90={p.fpts_p90 as number}
            min={(p.fpts_p10 as number) * 0.92} max={(p.fpts_p90 as number) * 1.05} width={220} />
          <span className="tnum">ceiling <b>{f0(p.fpts_p90 as number)}</b></span>
        </div>
        {p.vor != null && (
          <span className="ml-auto flex gap-4 text-[13px] text-ink-2">
            <span>VOR <b className="tnum text-ink">{f1(p.vor as number)}</b></span>
            {p.adp != null && <span>ADP <b className="tnum text-ink">{f0(p.adp as number)}</b></span>}
          </span>
        )}
      </Card>

      {(p.radar_label || priority) && (
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[13px] font-semibold text-ink-2">Draft radar</h2>
            {p.radar_label && <Chip tone={radarTone(p.radar_label)}>{radarName(p.radar_label)}</Chip>}
            {priority && <Chip tone="accent">★ {priority.takeBy ? `take by ${priority.takeBy}` : "priority"}</Chip>}
          </div>
          <p className="mt-2 text-[13px] text-ink-2">{p.radar_reasons || "Personal priority target."}</p>
          {priority?.note && <p className="mt-1 text-[12px] text-ink-3">Your note: {priority.note}</p>}
        </Card>
      )}

      {(d.overrides.length > 0 || d.bbm_notes.length > 0) && (
        <Card className="space-y-3 p-4">
          <h2 className="text-[13px] font-semibold text-ink-2">
            Analyst layer &amp; BBM provenance
            <span className="ml-2 font-normal text-ink-3">why board B differs from the model</span>
          </h2>

          {d.overrides.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] uppercase tracking-wide text-ink-3">
                Override history — append-only, newest first ({d.overrides.length})
              </div>
              {d.overrides.map((o, i) => (
                <div key={i} className="rounded-lg border border-bdr/60 px-3 py-2 text-[13px]">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="tnum text-ink-3">{o.date}</span>
                    <Chip tone="neutral">{o.category}</Chip>
                    <span
                      className={`font-semibold tnum ${
                        o.action.startsWith("+") ? "text-up" : o.action.startsWith("-") ? "text-down" : "text-ink-2"
                      }`}
                    >
                      {o.action}
                    </span>
                    {o.effective ? (
                      <Chip tone="accent" title="The latest-dated entry — the one currently applied to board B">
                        effective
                      </Chip>
                    ) : (
                      <span className="text-[11px] text-ink-3" title="Superseded by a later-dated entry (append-only; latest wins)">
                        superseded
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-ink-2">{o.rationale}</p>
                </div>
              ))}
            </div>
          )}

          {d.bbm_notes.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] uppercase tracking-wide text-ink-3">
                BBM facts — data/manual/bbm_notes.csv ({d.bbm_notes.length})
              </div>
              {d.bbm_notes.map((n, i) => (
                <div key={i} className="text-[13px] text-ink-2">
                  <span className="tnum text-ink-3">{n.date}</span>{" "}
                  <Chip tone={n.direction === "up" ? "up" : n.direction === "down" ? "down" : "neutral"}>
                    {n.claim_type}
                    {n.direction === "up" ? " ▲" : n.direction === "down" ? " ▼" : ""}
                  </Chip>{" "}
                  <span>{n.quote}</span>
                  <span className="ml-1 text-[11px] text-ink-3">— {n.source_file}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="text-[13px] font-semibold text-ink-2">Fantasy points per game, by season</h2>
          <LineChart series={fpgSeries} height={200} />
        </Card>
        <Card className="p-4">
          <h2 className="text-[13px] font-semibold text-ink-2">Minutes per game, by season</h2>
          <LineChart series={mpgSeries} height={200} />
        </Card>
      </div>

      {gameMinutes.length > 0 && (
        <Card className="p-4">
          <h2 className="text-[13px] font-semibold text-ink-2">
            Per-game minutes — {d.game_log_season}
            <span className="ml-2 font-normal text-ink-3">
              {d.game_log.length} games · mean {f1(minMean)} · std {f1(minStd)} (higher = more volatile role)
            </span>
          </h2>
          <BarChart points={gameMinutes} height={190} name="Per-game minutes" unit=" min" />
        </Card>
      )}

      <Card className="overflow-hidden">
        <h2 className="px-4 pt-3 text-[13px] font-semibold text-ink-2">Career (per game)</h2>
        <div className="scroll-thin overflow-x-auto p-2">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-ink-3">
                {["Season", "Age", "Team", "GP", "MPG", "PTS", "REB", "AST", "STL", "BLK", "3PM", "TOV", "USG%", "FP/G"].map((h) => (
                  <th key={h} className={`px-2.5 py-1.5 ${h !== "Season" && h !== "Team" ? "text-right" : ""}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.career.map((c) => (
                <tr key={c.SEASON} className="border-t border-bdr/60">
                  <td className="px-2.5 py-1.5 font-medium">{c.SEASON}</td>
                  <td className="tnum px-2.5 text-right">{f0(c.AGE)}</td>
                  <td className="px-2.5">{c.TEAM}</td>
                  <td className="tnum px-2.5 text-right">{f0(c.GP)}</td>
                  <td className="tnum px-2.5 text-right">{f1(c.MPG)}</td>
                  <td className="tnum px-2.5 text-right">{f1(c.PTS)}</td>
                  <td className="tnum px-2.5 text-right">{f1(c.REB)}</td>
                  <td className="tnum px-2.5 text-right">{f1(c.AST)}</td>
                  <td className="tnum px-2.5 text-right">{f1(c.STL)}</td>
                  <td className="tnum px-2.5 text-right">{f1(c.BLK)}</td>
                  <td className="tnum px-2.5 text-right">{f1(c.FG3M)}</td>
                  <td className="tnum px-2.5 text-right">{f1(c.TOV)}</td>
                  <td className="tnum px-2.5 text-right">{c.USG != null ? f1(c.USG) : "—"}</td>
                  <td className="tnum px-2.5 text-right font-semibold">{f1(c.FPTS)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
