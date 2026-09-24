// The draft room (Step 19.7): live board + every team's composition, fed by manual entry or
// the ESPN poller.
//
// Draft-night rules this file is built around:
//   * Never block on the network. Every mutation posts and re-reads; a stalled ESPN poll
//     surfaces as a banner, never a spinner that eats the room.
//   * Undo is always visible. Misclicks happen and the draft does not pause.
//   * The source toggle is switchable mid-draft — picks live server-side, so flipping to
//     manual when ESPN lags loses nothing. That is the whole point of having it.
//
// It reports composition; it does not prescribe a pick. "Take player X" needs the H2H
// week-win simulator, whose variance layer is gated and unbuilt (Step 19.4) — inventing a
// number here would be worse than leaving it out.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DraftBoardRow, DraftStateResponse, RosterPanel, get } from "../lib/api";
import { Card, Chip, ErrorNote, Field, Segmented, Select, Spinner } from "../components/ui";
import { Column, DataTable } from "../components/DataTable";
import { f1, f2 } from "../lib/format";
import { DraftTargets, radarName, radarTone, targetTitle, useDraftTargets } from "../lib/draftRadar";

const POLL_MS = 4000;

type EspnDraftUrl = { leagueId: string; season: string; teamId: string };

function parseEspnDraftUrl(value: string): EspnDraftUrl | null {
  try {
    const url = new URL(value.trim().replaceAll("\\&", "&"));
    if (!url.hostname.endsWith("espn.com")) return null;
    const leagueId = url.searchParams.get("leagueId") ?? "";
    const season = url.searchParams.get("seasonId") ?? "";
    const teamId = url.searchParams.get("teamId") ?? "";
    if (!/^\d+$/.test(leagueId) || !/^\d{4}$/.test(season) || !/^\d+$/.test(teamId)) {
      return null;
    }
    return { leagueId, season, teamId };
  } catch {
    return null;
  }
}

async function post(path: string) {
  const res = await fetch(path, { method: "POST" });
  if (!res.ok) {
    const b = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(b?.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export default function DraftRoom() {
  const [st, setSt] = useState<DraftStateResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [radarFilter, setRadarFilter] = useState("All");
  const [draftUrl, setDraftUrl] = useState("");
  const [leagueId, setLeagueId] = useState("");
  const [season, setSeason] = useState("2027");
  const [teamId, setTeamId] = useState("");
  const connectionSeeded = useRef(false);
  const { targets, edit: editTarget } = useDraftTargets();

  const load = useCallback(async () => {
    try {
      setSt(await get<DraftStateResponse>("/api/draft/state?top=150", true));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!st || connectionSeeded.current) return;
    setLeagueId(st.league_id);
    setSeason(String(st.season));
    setTeamId(st.my_team_id ? String(st.my_team_id) : "");
    connectionSeeded.current = true;
  }, [st]);

  // Poll only when ESPN is the source — manual entry needs no clock.
  useEffect(() => {
    if (st?.source !== "espn") return;
    const t = setInterval(async () => {
      await post("/api/draft/refresh").catch(() => {}); // never surface a transient poll error
      void load();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [st?.source, load]);

  const act = async (path: string) => {
    setBusy(true);
    try {
      await post(path);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const updateDraftUrl = (value: string) => {
    setDraftUrl(value);
    const parsed = parseEspnDraftUrl(value);
    if (!parsed) return;
    setLeagueId(parsed.leagueId);
    setSeason(parsed.season);
    setTeamId(parsed.teamId);
  };

  const connectAndWatch = async () => {
    if (!/^\d+$/.test(leagueId) || !/^\d{4}$/.test(season) || !/^\d+$/.test(teamId)) {
      setErr("Paste a valid ESPN draft URL, or enter numeric league, season, and team IDs.");
      return;
    }
    setBusy(true);
    try {
      const q = new URLSearchParams({
        league_id: leagueId,
        season,
        my_team_id: teamId,
        watch: "true",
      });
      await post(`/api/draft/connect?${q.toString()}`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const available = useMemo(() => {
    if (!st) return [];
    if (radarFilter === "Targets") return st.board.filter((r) => r.radar_label?.includes("target"));
    if (radarFilter === "Fades") return st.board.filter((r) => r.radar_label?.includes("fade"));
    if (radarFilter === "Watchlist") return st.board.filter((r) => targets[String(r.PLAYER_ID)]);
    return st.board;
  }, [st, radarFilter, targets]);

  if (err && !st) return <ErrorNote message={err} />;
  if (!st) return <Spinner label="Loading draft room…" />;

  const me = st.rosters.find((r) => r.is_me);

  return (
    <div className="space-y-4">
      {/* ---------------------------------------------------------------- controls */}
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Pick source">
          <Segmented
            value={st.source}
            onChange={(v) => act(`/api/draft/source?source=${v}`)}
            options={[
              { value: "manual", label: "Manual", title: st.sources.manual },
              { value: "espn", label: "ESPN", title: st.sources.espn },
            ]}
          />
        </Field>
        <Field label="My team">
          <Select
            value={String(st.my_team_id)}
            onChange={(v) => act(`/api/draft/config?my_team_id=${v}`)}
            options={[
              { value: "0", label: "— select —" },
              ...st.team_ids.map((t) => ({ value: String(t), label: `Team ${t}` })),
            ]}
          />
        </Field>
        <Field label="Draft radar">
          <Select value={radarFilter} onChange={setRadarFilter}
            options={["All", "Targets", "Fades", "Watchlist"].map((v) => ({ value: v, label: v === "All" ? "All players" : v }))} />
        </Field>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => act("/api/draft/undo")}
            disabled={busy || st.n_picks === 0}
            className="h-8 rounded-lg border border-bdr px-3 text-[13px] font-semibold text-ink-2 hover:bg-surface-2 disabled:opacity-40"
          >
            ↶ Undo
          </button>
          <button
            onClick={() => confirm("Clear all picks?") && act("/api/draft/reset")}
            className="h-8 rounded-lg px-2 text-[13px] text-ink-3 hover:text-down"
          >
            Reset
          </button>
        </div>
      </div>

      <Card className="p-4">
        <div className="flex flex-col gap-3">
          <div>
            <h2 className="text-[13px] font-bold">ESPN draft connection</h2>
            <p className="text-[11px] text-ink-3">
              Paste the URL from the ESPN draft room. League, season, and team are extracted;
              <code className="ml-1">memberId</code> is ignored and never saved.
            </p>
          </div>
          <Field label="ESPN draft URL">
            <input
              value={draftUrl}
              onChange={(e) => updateDraftUrl(e.target.value)}
              placeholder="https://fantasy.espn.com/basketball/draft?leagueId=..."
              className="h-8 w-full rounded-lg border border-bdr bg-surface px-2.5 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 hover:border-baseline focus:border-accent"
            />
          </Field>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="League ID">
              <input
                inputMode="numeric"
                value={leagueId}
                onChange={(e) => setLeagueId(e.target.value.trim())}
                className="h-8 w-36 rounded-lg border border-bdr bg-surface px-2.5 text-sm text-ink outline-none focus:border-accent"
              />
            </Field>
            <Field label="Season">
              <input
                inputMode="numeric"
                value={season}
                onChange={(e) => setSeason(e.target.value.trim())}
                className="h-8 w-24 rounded-lg border border-bdr bg-surface px-2.5 text-sm text-ink outline-none focus:border-accent"
              />
            </Field>
            <Field label="My team ID">
              <input
                inputMode="numeric"
                value={teamId}
                onChange={(e) => setTeamId(e.target.value.trim())}
                className="h-8 w-24 rounded-lg border border-bdr bg-surface px-2.5 text-sm text-ink outline-none focus:border-accent"
              />
            </Field>
            <button
              onClick={() => void connectAndWatch()}
              disabled={busy}
              className="h-8 rounded-lg bg-accent px-3 text-[13px] font-semibold text-white hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Connectingâ€¦" : "Connect & watch"}
            </button>
            {st.espn_ready && (
              <span className="pb-1 text-[11px] text-ink-3">
                Watching league {st.league_id} as Team {st.my_team_id || "â€”"}
              </span>
            )}
          </div>
        </div>
      </Card>

      {/* ---------------------------------------------------------------- banners */}
      {st.espn_error && (
        <div className="rounded-xl border border-warn/40 bg-warn/10 px-4 py-2.5 text-[13px] text-ink-2">
          <b>ESPN feed problem:</b> {st.espn_error}
          <div className="mt-1 text-ink-3">
            Switch to <b>Manual</b> above and keep drafting — your picks are kept.
            {" "}Session cookies expire; re-harvest <code>espn_s2</code>/<code>SWID</code> into{" "}
            <code>.env</code> if this is a 401.
          </div>
        </div>
      )}
      {st.source === "espn" && !st.browser_sync_asof && st.n_picks === 0 && (
        <div className="rounded-xl border border-warn/40 bg-warn/10 px-4 py-2.5 text-[13px] text-ink-2">
          <b>Waiting for the browser bridge.</b> ESPN's league API does not expose picks while
          a draft is live. Load the repo's <code>browser-extension</code> folder in Chrome and
          keep the ESPN draft tab open; its badge will confirm when picks are reaching this room.
        </div>
      )}
      {st.browser_sync_asof && (
        <div className="rounded-xl border border-up/30 bg-up/10 px-4 py-2.5 text-[13px] text-ink-2">
          <b>Browser bridge live.</b> Pick state was captured from the ESPN draft tab at{" "}
          {new Date(st.browser_sync_asof).toLocaleTimeString()}.
        </div>
      )}
      {!st.has_positions && (
        <div className="rounded-xl border border-warn/40 bg-warn/10 px-4 py-2.5 text-[13px] text-ink-2">
          <b>No position data.</b> ESPN is the only source of slot eligibility — hit{" "}
          <b>Connect ESPN</b> once and it's cached to disk, after which manual mode works fully
          offline. Until then there's no positional scarcity and replacement ignores slots.
        </div>
      )}
      {st.synthetic_teams && (
        <div className="rounded-xl border border-bdr bg-surface-2 px-4 py-2.5 text-[13px] text-ink-2">
          <b>Stand-in teams.</b> Teams are numbered 1–{st.team_ids.length} and the clock runs a
          plain snake — ESPN's real ids are non-contiguous and its order isn't drawn yet.
          Fine for a mock; <b>Connect ESPN</b> before the real draft (and reset, since the ids
          won't line up).
        </div>
      )}
      {st.settings?.order_is_placeholder && (
        <div className="rounded-xl border border-bdr bg-surface-2 px-4 py-2.5 text-[13px] text-ink-2">
          <b>Draft order not drawn yet.</b> ESPN is still returning its sorted default
          ({st.settings.pick_order.join(", ")}), so "picks until your turn" is provisional —
          re-read settings on draft day.
        </div>
      )}

      {/* ---------------------------------------------------------------- status */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Picks made" value={String(st.n_picks)} />
        <Stat
          label="On the clock"
          value={st.on_the_clock === null ? "—" : `Team ${st.on_the_clock}`}
          tone={st.on_the_clock === st.my_team_id && st.my_team_id !== 0 ? "accent" : undefined}
        />
        <Stat
          label="Picks until my turn"
          value={st.picks_until_next === null ? "—" : String(st.picks_until_next)}
          hint={st.picks_until_next === null ? "Draft order unknown — not guessed" : undefined}
        />
        <Stat
          label="Replacement (fpts/g)"
          value={f1(st.replacement.any)}
          hint="Best player left on the wire once every starting slot in the league is filled"
        />
      </div>

      {/* ---------------------------------------------------------------- board + me */}
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-bdr px-4 py-2.5">
            <div>
              <h2 className="text-[13px] font-bold">Available</h2>
              <p className="text-[11px] text-ink-3">
                <b>VOR*</b> is informational — it ranks ~like FP/G until the endgame (slots
                rarely bind: most players are multi-eligible). Roster construction lives in
                the slot chips, not this column.
              </p>
            </div>
            <span className="shrink-0 text-[11px] text-ink-3">
              click a row to draft to {st.on_the_clock ? `Team ${st.on_the_clock}` : "the clock"}
            </span>
          </div>
          <DataTable<DraftBoardRow>
            rows={available}
            rowKey={(r) => r.PLAYER_ID}
            defaultSort="live_rank"
            onRowClick={(r) => !busy && act(`/api/draft/pick?player_id=${r.PLAYER_ID}`)}
            columns={boardColumns(targets, editTarget, st.n_picks + 1)}
            maxHeight="calc(100vh - 430px)"
            dense
          />
        </Card>

        <div className="space-y-3">
          <Card className="p-4">
            <h2 className="mb-2 text-[13px] font-bold">
              My roster {me ? `(Team ${me.team_id})` : ""}
            </h2>
            {!me || st.my_team_id === 0 ? (
              <p className="text-[13px] text-ink-3">Select your team above.</p>
            ) : (
              <RosterCard panel={me} detailed />
            )}
          </Card>
        </div>
      </div>

      {/* ---------------------------------------------------------------- league */}
      <Card className="p-4">
        <h2 className="mb-1 text-[13px] font-bold">League composition</h2>
        <p className="mb-3 text-[11px] text-ink-3">
          What every team has and still needs. Risk is <b>descriptive</b> — chronic-injury
          counts and the board's own p10/median. Roster totals are not simulated: summing
          independent per-player draws would understate correlation, so no team-level
          distribution is shown until the H2H simulator's variance layer is built and passes
          its coverage gate.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {st.rosters.map((r) => (
            <div
              key={r.team_id}
              className={`rounded-lg border p-2.5 ${
                r.is_me ? "border-accent bg-accent-soft/40" : "border-bdr bg-surface-2"
              }`}
            >
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[12px] font-bold">
                  Team {r.team_id} {r.is_me && <span className="text-accent">(me)</span>}
                </span>
                <span className="text-[11px] text-ink-3">{r.players.length}</span>
              </div>
              <RosterCard panel={r} />
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function RosterCard({ panel, detailed = false }: { panel: RosterPanel; detailed?: boolean }) {
  const unfilled = Object.entries(panel.unfilled);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {unfilled.length === 0 ? (
          <Chip tone="up">starters filled</Chip>
        ) : (
          unfilled.map(([slot, n]) => (
            <Chip key={slot} tone="warn" title={`${n} unfilled ${slot} slot(s)`}>
              {slot}
              {n > 1 ? `×${n}` : ""}
            </Chip>
          ))
        )}
      </div>
      {detailed && (
        <ul className="space-y-1">
          {panel.players.map((p) => (
            <li key={p.player_id} className="flex items-baseline justify-between gap-2 text-[12px]">
              <span className="truncate">
                {p.name}
                {p.chronic === 1 && (
                  <span className="ml-1 text-warn" title="chronic injury history (3+ spells in 2y)">
                    ⚠
                  </span>
                )}
              </span>
              <span className="shrink-0 tabular-nums text-ink-3">
                {p.positions.join("/")} · {f1(p.fpts_pg)}
              </span>
            </li>
          ))}
          {panel.players.length === 0 && <li className="text-[12px] text-ink-3">No picks yet.</li>}
        </ul>
      )}
      <div className="flex items-center gap-2 text-[11px] text-ink-3">
        <span>Σ {f1(panel.sum_fpts_pg)} fpts/g</span>
        {panel.n_chronic > 0 && (
          <Chip tone="warn" title="players with 3+ injury spells in the last 2 years">
            {panel.n_chronic} chronic
          </Chip>
        )}
        {panel.mean_risk !== null && <span>risk {f2(panel.mean_risk)}</span>}
      </div>
    </div>
  );
}

function Stat({
  label, value, hint, tone,
}: { label: string; value: string; hint?: string; tone?: "accent" }) {
  return (
    <Card className={`px-3 py-2 ${tone === "accent" ? "border-accent" : ""}`} >
      <div className="text-[11px] text-ink-3">{label}</div>
      <div
        title={hint}
        className={`text-[17px] font-bold tabular-nums ${tone === "accent" ? "text-accent" : ""}`}
      >
        {value}
      </div>
    </Card>
  );
}

function boardColumns(
  targets: DraftTargets,
  editTarget: (row: DraftBoardRow) => void,
  currentPick: number,
): Column<DraftBoardRow>[] {
  return [
    { key: "live_rank", label: "#", align: "right", sortValue: (r) => r.live_rank },
    {
      key: "PLAYER_NAME",
      label: "Player",
      render: (r) => (
        <span className="flex items-center gap-1.5 font-medium">
          {r.PLAYER_NAME}
          <span className="ml-1.5 text-[11px] text-ink-3">{r.TEAM_ABBREVIATION}</span>
          <button
            onClick={(e) => { e.stopPropagation(); editTarget(r); }}
            title={targets[String(r.PLAYER_ID)] ? "Edit priority target (type REMOVE to clear)" : "Add priority target"}
            className={targets[String(r.PLAYER_ID)] ? "text-warn" : "text-ink-3 hover:text-warn"}
          >
            {targets[String(r.PLAYER_ID)] ? "★" : "☆"}
          </button>
        </span>
      ),
      sortValue: (r) => r.PLAYER_NAME,
    },
    {
      key: "positions",
      label: "Pos",
      title: "ESPN slot eligibility — the real multi-position claim",
      render: (r) => <span className="text-[11px] text-ink-2">{r.positions.join("/") || "—"}</span>,
      sortValue: (r) => r.positions.join("/"),
    },
    { key: "fpts_pg", label: "FP/G", align: "right", render: (r) => f1(r.fpts_pg), sortValue: (r) => r.fpts_pg },
    {
      key: "live_vor",
      label: "VOR*",
      align: "right",
      title:
        "Live value over replacement, recomputed from the actual remaining pool and the league's actual remaining slot demand.\n\n" +
        "*INFORMATIONAL. Measured 2026-07-16: this ranks almost identically to FP/G (Spearman 0.99) for ~110 of 130 picks and only diverges in the endgame (0.94 by pick 125). " +
        "One scoring dimension + 3 UTIL slots + 201/353 players multi-eligible = slots rarely bind, so per-slot replacement spread is only ~2.3 fpts/g. " +
        "Use slot feasibility (your roster panel) for roster construction; don't draft off this column.",
      render: (r) => (
        <span className={r.live_vor > 0 ? "font-semibold text-up" : "text-ink-3"}>{f1(r.live_vor)}</span>
      ),
      sortValue: (r) => r.live_vor,
    },
    {
      key: "risk", label: "Risk", align: "right", hideBelow: "lg",
      render: (r) => f2(r.risk), sortValue: (r) => r.risk,
    },
    {
      key: "fpts_p10", label: "Floor", align: "right", hideBelow: "xl",
      title: "10th-percentile season total (Monte-Carlo range)",
      render: (r) => f1(r.fpts_p10), sortValue: (r) => r.fpts_p10,
    },
    {
      key: "adp", label: "ADP", align: "right", hideBelow: "lg",
      render: (r) => (r.adp == null ? "—" : f1(r.adp)), sortValue: (r) => r.adp ?? 9999,
    },
    {
      key: "radar", label: "Radar",
      title: "ADP disagreement with explicit role, growth, or downside support",
      sortValue: (r) => r.radar_round_gap ?? null,
      render: (r) => {
        const target = targets[String(r.PLAYER_ID)];
        if (target) {
          const due = target.takeBy != null && currentPick >= target.takeBy;
          return <Chip tone={due ? "warn" : "accent"} title={targetTitle(r, target)}>
            ★ {due ? "due" : target.takeBy ? `by ${target.takeBy}` : "priority"}
          </Chip>;
        }
        return r.radar_label
          ? <Chip tone={radarTone(r.radar_label)} title={r.radar_reasons || undefined}>{radarName(r.radar_label)}</Chip>
          : null;
      },
    },
  ];
}
