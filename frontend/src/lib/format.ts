export const f0 = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : Math.round(v).toLocaleString();

export const f1 = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : v.toFixed(1);

export const f2 = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : v.toFixed(2);

export const signed = (v: number, digits = 1) => (v > 0 ? "+" : "") + v.toFixed(digits);

/** "fpts_delta:+3" -> { kind: "fpts_delta", value: 3 } ; "none"/"" -> null */
export function parseAction(action?: string | null): { kind: string; value: number } | null {
  if (!action || action === "none") return null;
  const [kind, raw] = action.split(":");
  const value = Number(raw);
  if (!kind || Number.isNaN(value)) return null;
  return { kind, value };
}
