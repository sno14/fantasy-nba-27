import { useState } from "react";
import { ProposalsResponse, invalidate, useApi } from "../lib/api";
import { Card, Chip, EmptyNote, ErrorNote, Segmented, Spinner } from "../components/ui";

// The analyst-proposal review panel (workflow v2): BBM-triangulated proposals await the
// user's approved/rejected verdict; promotion runs the same code path as
// `apply_proposals.py --promote`. Status edits are surgical YAML-text rewrites — the
// file's comments and history stay intact.

const STATUS_TONE: Record<string, "accent" | "up" | "down"> = {
  proposed: "accent",
  approved: "up",
  rejected: "down",
};

export default function Analyst() {
  const { data, error, loading, reload } = useApi<ProposalsResponse>("/api/proposals");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const act = async (name: string, date: string, status: string) => {
    setBusy(name + date);
    setNote(null);
    try {
      const res = await fetch(`/api/proposals/${encodeURIComponent(name)}/${date}?status=${status}`, { method: "PATCH" });
      if (!res.ok) throw new Error(((await res.json()) as { detail?: string }).detail ?? res.statusText);
      invalidate("/api/proposals");
      reload();
    } catch (e) {
      setNote(`Failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const promote = async () => {
    setBusy("promote");
    setNote(null);
    try {
      const res = await fetch("/api/proposals/promote", { method: "POST" });
      const body = (await res.json()) as { promoted?: string[]; detail?: string };
      if (!res.ok) throw new Error(body.detail ?? res.statusText);
      invalidate("/api/");
      reload();
      setNote(
        body.promoted?.length
          ? `Promoted to analyst_overrides.yaml: ${body.promoted.join(", ")}. Boards recompute on next load.`
          : "Nothing new to promote (already present or none approved).",
      );
    } catch (e) {
      setNote(`Promote failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  if (loading) return <Spinner label="Loading proposals…" />;
  if (error) return <ErrorNote message={error} />;
  if (!data) return null;

  const shown = data.proposals.filter((p) => filter === "all" || p.status === filter);
  const nApproved = data.counts["approved"] ?? 0;
  const impactErr = data.impact["_error"];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight">Analyst layer — proposal review</h1>
          <p className="max-w-2xl text-[13px] text-ink-2">
            BBM-transcript triangulations staged in <code className="text-xs">config/analyst_proposals.yaml</code>.
            Approve or reject each; <b>Promote</b> moves approved entries into the live overrides
            (same as <code className="text-xs">apply_proposals.py --promote</code>, idempotent).
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <Segmented value={filter} onChange={setFilter}
            options={[
              { value: "all", label: `All ${data.proposals.length}` },
              { value: "proposed", label: `Proposed ${data.counts["proposed"] ?? 0}` },
              { value: "approved", label: `Approved ${nApproved}` },
              { value: "rejected", label: `Rejected ${data.counts["rejected"] ?? 0}` },
            ]} />
          <button
            onClick={promote}
            disabled={busy != null || nApproved === 0}
            className="h-8 rounded-lg bg-accent px-3.5 text-[13px] font-semibold text-accent-ink transition-opacity disabled:opacity-40"
          >
            {busy === "promote" ? "Promoting…" : `Promote approved (${nApproved})`}
          </button>
        </div>
      </header>

      {note && (
        <div className="rounded-xl border border-bdr bg-accent-soft px-4 py-2.5 text-[13px]">{note}</div>
      )}
      {impactErr && <ErrorNote message={`Impact preview unavailable: ${impactErr.message}`} />}
      {shown.length === 0 && <EmptyNote>No proposals with this status.</EmptyNote>}

      <div className="space-y-3">
        {shown.map((p) => {
          const imp = data.impact[p.name];
          const isDelta = p.action_str !== "none";
          const up = isDelta && p.action_str.includes("+");
          return (
            <Card key={p.name + p.date} className="p-4">
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="text-[15px] font-bold">{p.name}</span>
                <Chip tone={isDelta ? (up ? "up" : "down") : "neutral"}>
                  {isDelta ? p.action_str.replace("fpts_delta:", "FP/G ") : "none — reviewed, no change"}
                </Chip>
                <Chip tone="neutral">{p.category}</Chip>
                <Chip tone={STATUS_TONE[p.status] ?? "neutral"}>{p.status}</Chip>
                <span className="text-xs text-ink-3">{p.date}</span>
                {imp && imp.on_board && (
                  <span className="tnum ml-auto text-[13px] text-ink-2" title="Live impact on the current pure-model board (A)">
                    {imp.fpts_old} → <b className="text-ink">{imp.fpts_new}</b> FP/G
                    <span className="mx-1.5 text-ink-3">·</span>
                    rank {imp.rank_old} → <b className="text-ink">{imp.rank_new}</b>
                    {imp.rank_new! < imp.rank_old! ? <span className="ml-1 text-up">▲{imp.rank_old! - imp.rank_new!}</span>
                      : imp.rank_new! > imp.rank_old! ? <span className="ml-1 text-down">▼{imp.rank_new! - imp.rank_old!}</span> : null}
                  </span>
                )}
                {imp && !imp.on_board && (
                  <Chip tone="warn" title="The name doesn't match any board row — it will fail loudly at apply time">
                    not on board
                  </Chip>
                )}
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{p.rationale}</p>
              {p.triangulation && (
                <details className="mt-1.5">
                  <summary className="cursor-pointer select-none text-xs font-medium text-accent">
                    Triangulation (model × BBM × judgment)
                  </summary>
                  <p className="mt-1 border-l-2 border-grid pl-3 text-[13px] leading-relaxed text-ink-2">
                    {p.triangulation}
                  </p>
                </details>
              )}
              <div className="mt-3 flex gap-2">
                {(["approved", "rejected", "proposed"] as const).map((s) =>
                  p.status === s ? null : (
                    <button
                      key={s}
                      disabled={busy != null}
                      onClick={() => act(p.name, p.date, s)}
                      className={`h-7 rounded-lg border px-2.5 text-xs font-semibold transition-colors disabled:opacity-40 ${
                        s === "approved"
                          ? "border-up/40 text-up hover:bg-up/10"
                          : s === "rejected"
                            ? "border-down/40 text-down hover:bg-down/10"
                            : "border-bdr text-ink-2 hover:bg-surface-2"
                      }`}
                    >
                      {busy === p.name + p.date ? "…" : s === "proposed" ? "reset to proposed" : `mark ${s}`}
                    </button>
                  ),
                )}
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
