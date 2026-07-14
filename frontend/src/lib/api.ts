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
  target_age: number;
  gp: number;
  mpg: number;
  fpts_pg: number;
  fpts_total?: number;
  draft_value: number;
  fpts_p10: number;
  fpts_median: number;
  fpts_p90: number;
  risk: number;
  analyst_action?: string | null;
  analyst_category?: string | null;
  analyst_date?: string | null;
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

export interface PlayerDetail {
  projection: BoardRow & Record<string, number | string | null>;
  career: CareerRow[];
  game_log_season: string | null;
  game_log: { GAME_DATE: string; MIN: number; PTS: number }[];
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
