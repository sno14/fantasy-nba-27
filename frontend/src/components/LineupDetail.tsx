import { LineupWeek } from "../lib/api";
import { f1 } from "../lib/format";
import { Card } from "./ui";

export function LineupDetail({ lineup, title = "Feasible daily starts" }: { lineup: LineupWeek; title?: string }) {
  if (!lineup.has_schedule) return null;
  return (
    <Card>
      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-3">{title}</div>
      <p className="mt-1 text-[12px] text-ink-3">
        Highest projected FP/G assignment to configured starting slots each day. This is a planning projection, not your submitted ESPN lineup.
      </p>
      {lineup.unknown_game_dates.length > 0 && (
        <p className="mt-1 text-[12px] text-warn">NBA team missing for player IDs {lineup.unknown_game_dates.join(", ")}; their game dates and weekly contribution are unknown.</p>
      )}
      <div className="mt-2 space-y-1.5">
        {lineup.days.map((day) => (
          <details key={day.day} className="rounded-lg border border-line px-3 py-2">
            <summary className="cursor-pointer text-[12px] font-semibold">
              {day.day} · {day.games} games · {day.assignments.length} confirmed starts · usable {day.usable_points == null ? "—" : f1(day.usable_points)} FP
              {day.benched_points != null ? ` · bench ${f1(day.benched_points)} FP` : ""}
            </summary>
            <div className="mt-2 text-[12px] text-ink-3">
              {day.assignments.length ? (
                <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                  {day.assignments.map((a) => (
                    <span key={a.slot} className="rounded bg-surface-2 px-2 py-1">
                      <b className="text-ink">{a.slot}</b> · {a.player_name} · {f1(a.fpts_pg)} FP
                    </span>
                  ))}
                </div>
              ) : <div>No confirmed starts.</div>}
              {day.idle_slots.length > 0 && <div className="mt-1">Open slots: {day.idle_slots.join(", ")}</div>}
              {day.unknown_eligibility.length > 0 && <div className="mt-1 text-warn">Eligibility missing for player IDs {day.unknown_eligibility.join(", ")}.</div>}
              {day.unknown_projection.length > 0 && <div className="mt-1 text-warn">FP/G missing for player IDs {day.unknown_projection.join(", ")}.</div>}
              {!day.exact && <div className="mt-1">Known-player feasible floor: {f1(day.known_usable_points)} FP. The final total depends on missing data.</div>}
            </div>
          </details>
        ))}
      </div>
    </Card>
  );
}
