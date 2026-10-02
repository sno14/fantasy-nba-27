import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MinutesScenarioResponse, useApi } from "../lib/api";
import { f1, f2, signed } from "../lib/format";
import { Card, ErrorNote, Spinner } from "./ui";
import { CopyLink } from "./Portability";

export function MinutesScenario({ playerId }: { playerId: number }) {
  const [params, setParams] = useSearchParams();
  const linked = params.get("minutes");
  const [draft, setDraft] = useState(linked ?? "");
  const [inputError, setInputError] = useState("");
  const path = `/api/player/${playerId}/minutes-scenario${linked ? `?mpg=${encodeURIComponent(linked)}` : ""}`;
  const { data, error, loading } = useApi<MinutesScenarioResponse>(path);

  useEffect(() => {
    setDraft(linked ?? (data?.current_mpg == null ? "" : data.current_mpg.toFixed(1)));
    setInputError("");
  }, [playerId, linked, data?.current_mpg]);

  function apply(event: React.FormEvent) {
    event.preventDefault();
    const value = Number(draft);
    if (!draft.trim() || !Number.isFinite(value) || value <= 0 || value > (data?.max_mpg ?? 42)) {
      setInputError(`Enter an assumed MPG above 0 and at most ${data?.max_mpg ?? 42}.`);
      return;
    }
    const rounded = Math.round(value * 10) / 10;
    if (rounded <= 0) { setInputError("Enter at least 0.1 MPG."); return; }
    setParams(current => { const next = new URLSearchParams(current); next.set("minutes", rounded.toFixed(1)); return next; });
  }

  function reset() {
    setParams(current => { const next = new URLSearchParams(current); next.delete("minutes"); return next; });
  }

  return <Card className="p-4">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="text-sm font-bold">Minutes scenario</h2><p className="mt-1 text-[12px] text-ink-3">Hold the approved stat rates and analyst rate adjustment while changing minutes. This is a read-only assumption.</p></div>{linked && data?.enabled && <CopyLink />}</div>
    {loading && <Spinner label="Scoring the minutes scenario…" />}
    {error && <div className="mt-3 space-y-2"><ErrorNote message={error} />{linked && <button type="button" onClick={reset} className="rounded-lg border border-bdr px-3 py-2 text-xs text-accent">Reset invalid assumption</button>}</div>}
    {data && !loading && !data.enabled && <p className="mt-3 text-[12px] text-warn">Scenario unavailable: {data.reason}</p>}
    {data?.enabled && !loading && <>
      <form onSubmit={apply} className="mt-3 flex flex-wrap items-end gap-2"><label className="flex flex-col gap-1 text-xs font-medium text-ink-2">Assumed MPG<input type="number" min={data.min_mpg} max={data.max_mpg} step="0.1" value={draft} onChange={event => { setDraft(event.target.value); setInputError(""); }} className="h-9 w-28 rounded-lg border border-bdr bg-surface px-2.5 text-sm text-ink" /></label><button type="submit" className="h-9 rounded-lg bg-accent px-3 text-xs font-bold text-accent-ink">Calculate</button>{linked && <button type="button" onClick={reset} className="h-9 rounded-lg border border-bdr px-3 text-xs">Reset to approved</button>}</form>
      {inputError && <p role="alert" className="mt-1 text-xs text-down">{inputError}</p>}
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-[12px]">
        <div className="rounded-lg border border-bdr p-2"><div className="text-ink-3">Approved baseline</div><strong className="mt-1 block tnum">{f1(data.current_mpg)} MPG · {f2(data.approved_fpts_pg)} FP/G</strong><div className="text-ink-3">Scored stat line {f2(data.scored_current_fpts_pg)}</div></div>
        <div className="rounded-lg border border-bdr p-2"><div className="text-ink-3">Minutes-only contribution</div><strong className="mt-1 block tnum">{signed(data.minutes_contribution ?? 0, 2)} FP/G</strong><div className="text-ink-3">Rescored line at {f1(data.assumed_mpg)} MPG: {f2(data.scored_assumed_fpts_pg)}</div></div>
        <div className="rounded-lg border border-bdr p-2"><div className="text-ink-3">Retained analyst rate residual</div><strong className="mt-1 block tnum">{signed(data.retained_rate_residual ?? 0, 2)} FP/G</strong><div className="text-ink-3">Recorded leg {signed(data.recorded_rate_leg ?? 0, 2)}</div></div>
        <div className="rounded-lg border border-bdr bg-accent-soft p-2"><div className="text-ink-3">Scenario at {f1(data.assumed_mpg)} MPG</div><strong className="mt-1 block tnum text-lg">{f2(data.assumed_fpts_pg)} FP/G</strong><div className="text-ink-3">Change {signed(data.fpts_pg_change ?? 0, 2)}</div></div>
      </div>
      <p className="mt-2 text-[11px] text-ink-3">{data.rate_note} {data.scope_note} The scenario does not change this player’s saved projection.</p>
    </>}
  </Card>;
}
