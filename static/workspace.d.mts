export const MAX_FILE_BYTES: number;
export function parseIds(raw: string): number[];
export interface Target { takeBy: number | null; note: string; preferredRound: number | null; backupGroup: string; priority: number | null; status: "active" | "hold" }
type Targets = Record<string, Target>;
export const TARGET_DEFAULTS: Pick<Target, "preferredRound" | "backupGroup" | "priority" | "status">;
export function normalizeTarget(value: unknown): Target;
export function snakePicks(order: number[], teamId: number, fromOverall: number, rounds: number): { round: number; overall: number }[];
export function validateBackup(value: unknown, season: string): Targets;
export function createBackup(targets: Targets, season: string): { format: string; version: number; season: string; exportedAt: string; targets: (Target & { playerId: number })[] };
export function downloadBackup(targets: Targets, season: string): void;
