export const MAX_FILE_BYTES: number;
export function parseIds(raw: string): number[];
type Targets = Record<string, { takeBy: number | null; note: string }>;
export function validateBackup(value: unknown, season: string): Targets;
export function createBackup(targets: Targets, season: string): { format: string; version: number; season: string; exportedAt: string; targets: { playerId: number; takeBy: number | null; note: string }[] };
export function downloadBackup(targets: Targets, season: string): void;
