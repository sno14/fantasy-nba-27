export const PRACTICE_KEY: string;
export const PRACTICE_VERSION: number;
export const MAX_RUNS: number;
export interface PracticePlayer { id: number; rank: number; name: string; adp: number | null; fptsPg: number | null; fptsTotal: number | null; positions: string[] }
export interface PracticePick { playerId: number; team: number }
export interface PracticeRun {
  version: number; id: string; name: string; createdAt: string;
  config: { teams: number; position: number; rule: "adp" | "board"; roster: Record<string, number> };
  snapshot: { season: string; source: "public" | "local"; ranking: "FP/G ordinal" | "learned/safe season value"; marketDate: string | null; boardDate: string | null; players: PracticePlayer[] };
  picks: PracticePick[]; checkpoints: number[];
}
export function practiceRounds(roster: Record<string, number>): number;
export function practiceTeam(overall: number, teams: number): number | null;
export function snapshotPlayers(rows: unknown[]): PracticePlayer[];
export function opponentChoice(players: PracticePlayer[], taken: Set<number>, rule: "adp" | "board"): PracticePlayer | null;
export function advancePractice(run: PracticeRun): PracticeRun;
export function createPracticeRun(options: { name: string; teams: number; position: number; rule: "adp" | "board"; roster: Record<string, number>; season: string; source: "public" | "local"; ranking: "FP/G ordinal" | "learned/safe season value"; marketDate?: string | null; boardDate?: string | null; rows: unknown[] }): PracticeRun;
export function choosePracticePlayer(run: PracticeRun, playerId: number): PracticeRun;
export function undoPracticePick(run: PracticeRun): PracticeRun;
export function validatePracticeRun(value: unknown): PracticeRun;
export function parsePracticeRuns(value: unknown): PracticeRun[];
export function practiceSummary(run: PracticeRun): { own: PracticePlayer[]; starters: number; starterFpg: number; openStarters: number; depth: number; seasonFp: number; unknownEligibility: number; unknownSeasonTotal: number; positions: Record<string, number> };
