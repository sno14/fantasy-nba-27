const finite = value => typeof value === "number" && Number.isFinite(value);

export function validMinutes(value) {
  const mpg = Number(value);
  return value !== "" && finite(mpg) && mpg >= 0.5 && mpg <= 42 && Math.abs(mpg * 2 - Math.round(mpg * 2)) < 1e-8;
}

export function validateMinutesArtifact(value, board) {
  if (!value || value.schema !== 1 || value.season !== board.season ||
      value.generated_at !== board.generated_at || value.scoring_key !== board.scoring_key ||
      value.board_rows !== board.rows.length || value.min_mpg !== 0.5 ||
      value.step_mpg !== 0.5 || value.max_mpg !== 42 ||
      !value.rows || typeof value.rows !== "object" || Array.isArray(value.rows))
    throw new Error("Minutes data does not match this board.");
  const byId = new Map(board.rows.map(row => [String(row.PLAYER_ID), row]));
  if (Object.keys(value.rows).length > byId.size) throw new Error("Invalid minutes data.");
  for (const [id, curve] of Object.entries(value.rows)) {
    const row = byId.get(id);
    if (!row || !curve || Object.keys(curve).sort().join() !==
        ["approved_fpts_pg", "current_mpg", "retained_rate_residual", "scored_current_fpts_pg", "values"].join() ||
        !finite(curve.current_mpg) || curve.current_mpg <= 0 ||
        !finite(curve.approved_fpts_pg) || !finite(curve.scored_current_fpts_pg) ||
        !finite(curve.retained_rate_residual) ||
        Math.abs(curve.current_mpg - row.mpg) > 0.001 ||
        Math.abs(curve.approved_fpts_pg - row.fpts_pg) > 0.001 ||
        Math.abs(curve.scored_current_fpts_pg + curve.retained_rate_residual - curve.approved_fpts_pg) > 0.035 ||
        !Array.isArray(curve.values) || curve.values.length !== 84 || !curve.values.every(finite))
      throw new Error("Invalid player minutes curve.");
  }
  return value;
}

export function minutesResult(curve, assumed) {
  if (assumed == null) return { assumed: null, fpts: curve.approved_fpts_pg, contribution: 0 };
  if (!validMinutes(assumed)) throw new Error("Assumed MPG must be 0.5–42 in 0.5 increments.");
  const index = Math.round(Number(assumed) * 2) - 1;
  const fpts = curve.values[index];
  return { assumed: Number(assumed), fpts, contribution: Math.round((fpts - curve.approved_fpts_pg) * 100) / 100 };
}
