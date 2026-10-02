export interface ChangeRow { PLAYER_ID: number; PLAYER_NAME: string; TEAM_ABBREVIATION: string | null; rank: number; fpts_pg: number | null; mpg: number | null; analyst_action: string | null; analyst_date: string | null }
export interface ChangeSnapshot { schema: number; version: string; asof: string; season: string; rankedBy: string; scoringKey: string; source: "public" | "local"; rows: ChangeRow[] }
export interface ChangeEvent { id: number; name: string; team: string | null; kind: "added" | "removed" | "changed" | "rank-only"; before: ChangeRow | null; after: ChangeRow | null; fptsDelta: number | null; mpgDelta: number | null; rankDelta: number | null; explanation: string }
export function validateChangeSnapshot(value: unknown): ChangeSnapshot;
export function compareSnapshots(latest: ChangeSnapshot, baseline: ChangeSnapshot): ChangeEvent[];
