import { BoardRow } from "../lib/api";
import { DraftTargets } from "../lib/draftRadar";
import { f0, f1 } from "../lib/format";
import { Column } from "./DataTable";

interface Props {
  rows: BoardRow[];
  columns: Column<BoardRow>[];
  targets: DraftTargets;
  compareIds: number[];
  onCompare: (row: BoardRow) => void;
  onTarget: (row: BoardRow) => void;
  onPlayer: (row: BoardRow) => void;
}

/** Expandable cards reuse table renderers so actuals and analyst detail stay consistent. */
export function BoardCards({ rows, columns, targets, compareIds, onCompare, onTarget, onPlayer }: Props) {
  const radar = columns.find(column => column.key === "radar");
  const details = columns.filter(column => !["rank", "player", "positions", "fpts_pg", "adp", "radar", "range"].includes(column.key));
  return <div className="board-card-view grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
    {rows.map(row => <article key={row.PLAYER_ID} data-player-card={row.PLAYER_ID} className="min-w-0 rounded-xl border border-bdr bg-surface p-4">
      <header className="flex items-start gap-2">
        <span className="tnum text-xs font-semibold text-ink-3">#{row.rank}</span>
        <div className="min-w-0 flex-1">
          <button onClick={() => onPlayer(row)} className="break-words text-left text-sm font-semibold hover:text-accent">{row.PLAYER_NAME}</button>
          <p className="mt-1 text-xs text-ink-3">{row.TEAM_ABBREVIATION || "—"} · {row.positions?.join("/") || "Position unavailable"}</p>
        </div>
        <button onClick={() => onTarget(row)} aria-label={`${targets[String(row.PLAYER_ID)] ? "Edit" : "Add"} priority target for ${row.PLAYER_NAME}`} className="px-2 text-lg text-warn">
          {targets[String(row.PLAYER_ID)] ? "★" : "☆"}
        </button>
        <input type="checkbox" aria-label={`Compare ${row.PLAYER_NAME}`} checked={compareIds.includes(row.PLAYER_ID)} onChange={() => onCompare(row)} className="mt-1 h-5 w-5 shrink-0 accent-[var(--accent)]" />
      </header>
      <div className="my-4 flex flex-wrap items-center gap-5">
        <div><p className="text-[11px] text-ink-3">FP/G</p><strong className="tnum text-xl">{f1(row.fpts_pg)}</strong></div>
        <div><p className="text-[11px] text-ink-3">ADP</p><strong className="tnum text-xl">{f0(row.adp)}</strong></div>
        <div className="ml-auto">{radar?.render?.(row)}</div>
      </div>
      <details className="border-t border-bdr pt-2">
        <summary className="cursor-pointer py-1 text-xs font-medium text-ink-2">Projection details{row.tier != null ? ` · Tier ${row.tier}` : ""}</summary>
        <dl className="mt-3 grid grid-cols-2 gap-3">
          {details.map(column => <div key={column.key} className="min-w-0">
            <dt className="text-[11px] text-ink-3">{column.label}</dt>
            <dd className="tnum mt-1 break-words text-sm">{column.render?.(row) ?? "—"}</dd>
          </div>)}
          <div className="col-span-2">
            <dt className="text-[11px] text-ink-3">Season totals · floor / median / ceiling</dt>
            <dd className="tnum mt-1 text-sm">{f0(row.fpts_p10)} / {f0(row.fpts_median)} / {f0(row.fpts_p90)}</dd>
          </div>
        </dl>
      </details>
    </article>)}
  </div>;
}
