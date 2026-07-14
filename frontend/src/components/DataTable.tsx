// Generic sortable data table: sticky header, tabular numerals, optional group
// separator rows (used for draft-board tiers), row click-through.

import { ReactNode, useMemo, useState } from "react";

export interface Column<T> {
  key: string;
  label: ReactNode;
  title?: string;
  align?: "left" | "right" | "center";
  render?: (row: T) => ReactNode;
  sortValue?: (row: T) => number | string | null;
  hideBelow?: "sm" | "md" | "lg" | "xl"; // cell hidden below this breakpoint
}

// Literal class strings — Tailwind only generates classes it can see in the source.
const HIDE_BELOW: Record<string, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
  xl: "hidden xl:table-cell",
};

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  groupOf,
  renderGroup,
  defaultSort,
  maxHeight = "calc(100vh - 260px)",
  dense = false,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  /** When set (and unsorted-by-user), a separator row renders whenever the group changes. */
  groupOf?: (row: T) => string | number | null;
  renderGroup?: (group: string | number) => ReactNode;
  defaultSort?: string;
  maxHeight?: string;
  dense?: boolean;
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(
    defaultSort ? { key: defaultSort, dir: 1 } : null,
  );
  const userSorted = sort?.key !== defaultSort || sort?.dir !== 1;

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const sv = col.sortValue;
    return [...rows].sort((a, b) => {
      const va = sv(a);
      const vb = sv(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1; // nulls last regardless of direction
      if (vb == null) return -1;
      if (va < vb) return -sort.dir;
      if (va > vb) return sort.dir;
      return 0;
    });
  }, [rows, sort, columns]);

  const clickSort = (key: string) => {
    const col = columns.find((c) => c.key === key);
    if (!col?.sortValue) return;
    setSort((s) => (s?.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: 1 }));
  };

  const pad = dense ? "px-2.5 py-1" : "px-2.5 py-1.5";
  let lastGroup: string | number | null | undefined;

  return (
    <div className="scroll-thin overflow-auto rounded-xl border border-bdr bg-surface" style={{ maxHeight }}>
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-[5]">
          <tr className="bg-surface-2 text-left text-[11px] uppercase tracking-wide text-ink-3">
            {columns.map((c) => (
              <th
                key={c.key}
                title={c.title}
                onClick={() => clickSort(c.key)}
                className={`${pad} whitespace-nowrap border-b border-bdr font-semibold ${
                  c.sortValue ? "cursor-pointer select-none hover:text-ink-2" : ""
                } ${c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : ""} ${
                  c.hideBelow ? HIDE_BELOW[c.hideBelow] : ""
                }`}
              >
                {c.label}
                {sort?.key === c.key && (
                  <span className="ml-0.5 text-accent">{sort.dir === 1 ? "▲" : "▼"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const cells = (
              <tr
                key={rowKey(row)}
                onClick={() => onRowClick?.(row)}
                className={`border-b border-bdr/60 last:border-b-0 ${
                  onRowClick ? "cursor-pointer transition-colors hover:bg-accent-soft/60" : ""
                }`}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={`${pad} whitespace-nowrap ${
                      c.align === "right" ? "tnum text-right" : c.align === "center" ? "text-center" : ""
                    } ${c.hideBelow ? HIDE_BELOW[c.hideBelow] : ""}`}
                  >
                    {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            );
            if (groupOf && renderGroup && !userSorted) {
              const g = groupOf(row);
              if (g != null && g !== lastGroup) {
                lastGroup = g;
                return (
                  <FragmentRow key={`g${g}-${rowKey(row)}`} sep={
                    <tr className="bg-surface-2/70">
                      <td colSpan={columns.length} className="px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider text-accent">
                        {renderGroup(g)}
                      </td>
                    </tr>
                  }>
                    {cells}
                  </FragmentRow>
                );
              }
            }
            return cells;
          })}
        </tbody>
      </table>
    </div>
  );
}

function FragmentRow({ sep, children }: { sep: ReactNode; children: ReactNode }) {
  return (
    <>
      {sep}
      {children}
    </>
  );
}
