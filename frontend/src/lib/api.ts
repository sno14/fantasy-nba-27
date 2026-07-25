// Typed API client + a tiny cache-aware fetch hook (no query library needed: the
// board endpoints are few, keyed by their query string, and immutable per key).

import { useEffect, useRef, useState } from "react";

export interface Meta {
  scoring: { name: string; weights: Record<string, number> };
  league: { name?: string; platform?: string; teams?: number; format?: string };
  target_seasons: string[];
  current_target: string;
  models: Record<string, string>;
  stances: Record<string, string>;
  data_ready: boolean;
  data_seasons: [string, string] | null;
  fixture: boolean;
}

export interface BoardRow {
  rank: number;
  tier: number | null;
  PLAYER_ID: number;
  PLAYER_NAME: string;
  TEAM_ABBREVIATION: string | null;
  // market-seeded rows (rookies / returning vets with no 2025-26 games) carry no model
  // projection: age/gp/mpg and the simulated ranges arrive as null — render "—".
  target_age: number | null;
  gp: number | null;
  mpg: number | null;
  fpts_pg: number;
  fpts_total?: number;
  draft_value: number;
  fpts_p10: number | null;
  fpts_median: number | null;
  fpts_p90: number | null;
  risk: number | null;
  market_priced?: number | null;
  seed_class?: string | null;
  analyst_action?: string | null;
  analyst_category?: string | null;
  analyst_date?: string | null;
  analyst_rationale?: string | null;
  model_rank?: number | null;
  vor?: number | null;
  vor_rank?: number | null;
  adp?: number | null;
  actual_rank?: number | null;
  act_fpts_pg?: number | null;
  act_fpts_total?: number | null;
  act_gp?: number | null;
}

export interface BoardResponse {
  target: string;
  model: string;
  stance: string;
  analyst_applied: boolean;
  n_adjusted: number;
  has_actuals: boolean;
  teams: string[];
  rows: BoardRow[];
}

export interface RosRow {
  rank: number;
  PLAYER_ID?: number;
  PLAYER_NAME: string;
  games_so_far?: number;
  gp?: number;
  mpg?: number;
  fpts_pg: number;
  fpts_total?: number;
  naive_fpts_pg?: number;
  naive_rank?: number;
  status_override?: string;
  rank_gap?: number;
  redist_mpg?: number;
}

// ------------------------------------------------------------------- weekly planner
export interface WeekInfo {
  week: number;
  week_name: string;
  start: string; // ISO date (Monday of the fantasy week)
  end: string; // ISO date (Sunday)
  days: string[]; // ISO dates on which any game is played that week
  n_games: number; // total NBA games that week
}

export interface WeeksResponse {
  target: string;
  has_schedule: boolean;
  weeks: WeekInfo[];
}

export interface WeeklyRow {
  PLAYER_ID: number;
  PLAYER_NAME: string;
  TEAM_ABBREVIATION: string | null;
  rank: number; // season-long board rank
  fpts_pg: number;
  gp: number | null; // projected games played (season)
  games: string[]; // ISO dates this player's team plays this week
  n_games: number;
  weekly_fpts: number; // fpts_pg × n_games (all days)
}

export interface WeeklyResponse {
  target: string;
  week: number;
  week_name: string;
  start: string;
  end: string;
  days: string[]; // the week's game-days, ascending
  teams: string[];
  rows: WeeklyRow[];
}

export interface CareerRow {
  SEASON: string;
  AGE: number;
  TEAM: string;
  GP: number;
  MPG: number;
  PTS: number;
  REB: number;
  AST: number;
  STL: number;
  BLK: number;
  FG3M: number;
  TOV: number;
  USG?: number;
  FPTS: number;
}

// Analyst-layer provenance for the Player page (data/manual/bbm_transcripts workflow).
export interface BbmNote {
  date: string;
  team: string | null;
  claim_type: string; // injury | role | depth | rank | hype
  direction: string; // up | down | (blank)
  quote: string;
  source_file: string;
}

export interface OverrideHistoryEntry {
  date: string;
  category: string; // role | injury | hype | rookie | other
  action: string; // "+2.5 fpts/g" | "none"
  rationale: string;
  effective: boolean; // the currently-applied (latest-dated) entry; others are superseded
}

export interface PlayerDetail {
  projection: BoardRow & Record<string, number | string | null>;
  career: CareerRow[];
  game_log_season: string | null;
  game_log: { GAME_DATE: string; MIN: number; PTS: number }[];
  bbm_notes: BbmNote[];
  overrides: OverrideHistoryEntry[];
}

export interface Proposal {
  name: string;
  date: string;
  category: string;
  action: unknown;
  action_str: string;
  rationale: string;
  status: "proposed" | "approved" | "rejected";
  preview?: string;
  triangulation?: string;
}

export interface ProposalImpact {
  on_board: boolean;
  fpts_old?: number;
  fpts_new?: number;
  rank_old?: number;
  rank_new?: number;
  message?: string; // only on the "_error" pseudo-entry
}

export interface ProposalsResponse {
  proposals: Proposal[];
  impact: Record<string, ProposalImpact>;
  counts: Record<string, number>;
}

// ------------------------------------------------------------------- draft room
export interface DraftBoardRow {
  live_rank: number;
  rank: number;
  PLAYER_ID: number;
  PLAYER_NAME: string;
  TEAM_ABBREVIATION: string | null;
  positions: string[];
  fpts_pg: number;
  live_vor: number;
  live_repl: number;
  fpts_p10: number;
  fpts_median: number;
  fpts_p90: number;
  risk: number;
  adp?: number | null;
}

export interface RosterPlayer {
  player_id: number;
  name: string;
  positions: string[];
  fpts_pg: number | null;
  risk: number | null;
  fpts_p10: number | null;
  fpts_median: number | null;
  chronic: number;
}

export interface RosterPanel {
  team_id: number;
  is_me: boolean;
  players: RosterPlayer[];
  unfilled: Record<string, number>;
  n_chronic: number;
  mean_risk: number | null;
  sum_fpts_pg: number;
}

export interface DraftSettings {
  size: number;
  slot_counts: Record<string, number>;
  pick_order: number[];
  draft_type: string;
  draft_date: number | null;
  seconds_per_pick: number;
  /** ESPN seeds pickOrder sorted and randomizes before the draft — true = not yet drawn. */
  order_is_placeholder: boolean;
  is_scheduled: boolean;
}

export interface DraftStateResponse {
  source: "manual" | "espn";
  sources: Record<string, string>;
  league_id: string;
  season: number;
  my_team_id: number;
  team_ids: number[];
  settings: DraftSettings | null;
  espn_error: string | null;
  espn_ready: boolean;
  /** false = no ESPN map cached yet, so no slot eligibility and no positional scarcity. */
  has_positions: boolean;
  /** true = team ids are 1..N stand-ins, not ESPN's real (non-contiguous) ids. */
  synthetic_teams: boolean;
  n_picks: number;
  picks: { overall: number; team_id: number; player_id: number }[];
  /** null when the draft order isn't known — never fabricated (survival keys off it). */
  picks_until_next: number | null;
  on_the_clock: number | null;
  replacement: Record<string, number>;
  rosters: RosterPanel[];
  board: DraftBoardRow[];
}

// ------------------------------------------------------------------- power rankings
export interface PowerTeam {
  team_id: number;
  is_me: boolean;
  power_rank: number;
  n_players: number;
  total_fpts_pg: number;
  avg_fpts_pg: number;
  total_fpts_season: number;
  starters_fpts_pg: number;
  star_power: number;
  best_player: string | null;
  best_fpts_pg: number | null;
  depth: number;
  floor_season: number;
  ceiling_season: number;
  mean_risk: number | null;
  n_chronic: number;
  unfilled_starts: number;
}

export interface PowerResponse {
  n_picks: number;
  my_team_id: number;
  n_teams: number;
  roster_size: number;
  has_positions: boolean;
  synthetic_teams: boolean;
  starting_slots: Record<string, number>;
  teams: PowerTeam[];
}

export interface DatasetPage {
  name: string;
  columns: string[];
  total: number;
  seasons: string[];
  rows: Record<string, unknown>[];
}

const cache = new Map<string, unknown>();

export async function get<T>(path: string, fresh = false): Promise<T> {
  if (!fresh && cache.has(path)) return cache.get(path) as T;
  const res = await fetch(path);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(
      (body as { detail?: string } | null)?.detail ?? `${res.status} ${res.statusText}`,
    );
  }
  const data = (await res.json()) as T;
  cache.set(path, data);
  return data;
}

export function invalidate(prefix: string) {
  for (const k of cache.keys()) if (k.startsWith(prefix)) cache.delete(k);
}

/** POST with no body; throws the server `detail` on failure. Used by the mutating views. */
export async function post<T = unknown>(path: string): Promise<T> {
  const res = await fetch(path, { method: "POST" });
  if (!res.ok) {
    const b = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(b?.detail ?? `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export interface Loaded<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Fetch `path` (cached); `null` path = idle. Stale responses are dropped. */
export function useApi<T>(path: string | null): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const [nonce, setNonce] = useState(0);
  const live = useRef(path);
  live.current = path;

  useEffect(() => {
    if (!path) {
      setData(null);
      setLoading(false);
      return;
    }
    let stale = false;
    setLoading(true);
    setError(null);
    get<T>(path, nonce > 0)
      .then((d) => {
        if (!stale && live.current === path) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((e: Error) => {
        if (!stale && live.current === path) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      stale = true;
    };
  }, [path, nonce]);

  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}

// ------------------------------------------------------------- season views (V1/V2/V6)
export interface TrendRow {
  PLAYER_ID: number;
  PLAYER_NAME: string;
  TEAM_ABBREVIATION: string | null;
  rank: number;
  rank_delta: number; // baseline_rank - rank: positive = riser
  fpts_pg: number;
  fpts_delta: number;
  mpg: number | null;
  mpg_delta: number | null;
  status_override: string;
  spark: [string, number, number][]; // [date, fpts_pg, rank] per trailing snapshot
}

export interface TrendsResponse {
  has_history: boolean;
  n_snapshots: number;
  window: number;
  latest: string | null;
  baseline: string | null;
  note?: string;
  rows: TrendRow[];
}

export interface TradeRow {
  PLAYER_ID: number;
  PLAYER_NAME: string;
  TEAM_ABBREVIATION: string | null;
  rank: number;
  fpts_pg: number;
  consensus_rank: number | null;
  market_gap: number | null; // consensus_rank - rank: positive = buy low
  naive_rank: number | null;
  heat_gap: number | null; // rank - naive_rank: positive = hot streak model discounts
  fpts_delta_14: number | null;
  risk: number | null;
  status_override: string;
  rostered_by: number | null;
  is_mine: boolean;
}

export interface TradeTargetsResponse {
  mode: "ros" | "preseason";
  market_date: string | null;
  has_market: boolean;
  has_naive: boolean;
  has_trend: boolean;
  ownership: boolean;
  roster_source: RosterSource;
  rosters_asof: string | null;
  my_team_id: number;
  rows: TradeRow[];
}

export interface ScheduleTeamRow {
  team: string;
  total_games: number;
  b2b: number;
  playoff_games: number;
  by_week: Record<string, number>;
}

export interface ScheduleStrengthResponse {
  has_schedule: boolean;
  target: string;
  playoff_weeks: number[];
  playoff_weeks_confirmed: boolean;
  note?: string;
  weeks: { week: number; week_name: string; start: string; end: string }[];
  teams: ScheduleTeamRow[];
}

export interface WaiverRow {
  PLAYER_ID: number;
  PLAYER_NAME: string;
  TEAM_ABBREVIATION: string | null;
  rank: number;
  fpts_pg: number;
  games: string[];
  n_games: number;
  weekly_fpts: number;
  redist_mpg: number | null; // >0 = inheriting minutes from an OUT teammate (EXP-030)
  breakout_p: number | null;
  fpts_delta_14: number | null;
  status_override: string;
}

// V3b: ownership source for the season views. "espn_live" = live in-season ESPN rosters
// were pulled (they follow adds/drops); "draft" = the draft-session picks (the default).
export type RosterSource = "draft" | "espn_live";

export interface WaiversResponse {
  mode: "ros" | "preseason";
  ownership: boolean;
  n_rostered: number;
  roster_source: RosterSource;
  rosters_asof: string | null;
  my_team_id: number;
  has_schedule: boolean;
  week?: number | null;
  week_name?: string;
  start?: string;
  end?: string;
  days?: string[];
  rows: WaiverRow[];
}

export interface RosterWeekRow {
  PLAYER_ID: number;
  PLAYER_NAME: string;
  TEAM_ABBREVIATION: string | null;
  rank: number | null;
  fpts_pg: number | null;
  fpts_p10: number | null;
  fpts_median: number | null;
  fpts_p90: number | null;
  risk: number | null;
  chronic: number;
  status_override: string;
  redist_mpg: number | null;
  fpts_delta_14: number | null;
  spark: [string, number, number][];
  games: string[];
  n_games: number;
  weekly_fpts: number;
}

export interface DayGridCell {
  day: string;
  games: number;
  benched: number;
}

export interface MyTeamResponse {
  has_team: boolean;
  my_team_id: number;
  note?: string;
  roster_source?: RosterSource;
  rosters_asof?: string | null;
  has_positions?: boolean;
  positions?: Record<string, string[]>;
  unfilled?: Record<string, number>;
  has_schedule?: boolean;
  week?: number | null;
  week_name?: string;
  start?: string;
  end?: string;
  days?: string[];
  weekly_total?: number;
  day_grid?: DayGridCell[];
  n_out?: number;
  daily_slots?: number;
  rows?: RosterWeekRow[];
}

export interface MatchupSide {
  team_id: number;
  total: number;
  rows: RosterWeekRow[];
  day_grid: DayGridCell[];
}

export interface MatchupResponse {
  has_matchup: boolean;
  my_team_id: number;
  note?: string;
  roster_source?: RosterSource;
  rosters_asof?: string | null;
  opp_team_id?: number;
  opponents?: number[];
  has_schedule?: boolean;
  week?: number | null;
  week_name?: string;
  start?: string;
  end?: string;
  days?: string[];
  daily_slots?: number;
  me?: MatchupSide;
  opp?: MatchupSide;
  gap?: number;
}
