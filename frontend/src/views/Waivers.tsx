// V3 — Waiver wire (docs/ui-views-plan.md): the pickup list. Unrostered players ranked
// by ROS FP/G × games in the chosen week, with the opportunity signals attached:
// redist_mpg (inheriting an OUT teammate's minutes right now — EXP-030), breakout_p,
// the 14d trend, and OUT status. Ownership comes from the Draft Room's picks.

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { WaiversResponse, WeeksResponse, invalidate, post, useApi } from "../lib/api";
import { f1, signed } from "../lib/format";
import { Column, DataTable } from "../components/DataTable";
import { Card, Chip, EmptyNote, ErrorNote, Field, SearchInput, Select, Spinner } from "../components/ui";

// V3b refresh response (POST /api/draft/rosters/refresh) — see api/draft.py.
interface RosterRefresh {
  n_rostered?: number;
  mapped?: number;
  n_teams?: number;
  espn_error?: string;
  note?: string | null;
}

export default function Waivers() {
  const nav = useNavigate();
  const [week, setWeek] = useState<number | null>(null);
  const [team, setTeam] = useState("All");
  const [q, setQ] = useState("");
  const [topN, setTopN] = useState(100);
  const [rosterBusy, setRosterBusy] = useState(false);
  const [rosterMsg, setRosterMsg] = useState<string | null>(null);

  const weeks = useApi<WeeksResponse>("/api/weeks").data;
  const url = week != null ? `/api/waivers?week=${week}` : "/api/waivers";
  const { data, error, loading, reload } = useApi<WaiversResponse>(url);

  // V3b: pull live ESPN rosters, then re-read every ownership-driven view.
  async function syncRosters(clear: boolean) {
    setRosterBusy(true);
    setRosterMsg(null);
    try {
      const r = await post<RosterRefresh>(`/api/draft/rosters/${clear ? "clear" : "refresh"}`);
      setRosterMsg(
        clear
          ? "Reverted to Draft Room picks."
          : r.espn_error
            ? `ESPN error: ${r.espn_error}`
            : r.n_rostered
              ? `Loaded ${r.n_rostered} rostered players across ${r.n_teams} teams` +
                (r.mapped != null && r.mapped < r.n_rostered ? ` (${r.mapped} mapped)` : "")
              : (r.note ?? "ESPN rosters are empty (undrafted)."),
      );
      for (const p of ["/api/waivers", "/api/myteam", "/api/matchup", "/api/trade-targets"]) invalidate(p);
      reload();
    } catch (e) {
      setRosterMsg((e as Error).message);
    } finally {
      setRosterBusy(false);
    }
  }

  // Adopt the server's default week once, so the picker shows where we landed.
  useEffect(() => {
    if (week == null && data?.has_schedule && data.week != null) setWeek(data.week);
  }, [data, week]);

  const teams = useMemo(
    () =>
      data
        ? ["All", ...Array.from(new Set(data.rows.map((r) => r.TEAM_ABBREVIATION).filter((t): t is string => !!t))).sort()]
        : ["All"],
    [data],
  );

  const rows = useMemo(() => {
    if (!data) return [];
    let base = data.rows;
    if (team !== "All") base = base.filter((r) => r.TEAM_ABBREVIATION === team);
    if (q) base = base.filter((r) => r.PLAYER_NAME.toLowerCase().includes(q.toLowerCase()));
    return base.slice(0, topN);
  }, [data, team, q, topN]);

  type Row = (typeof rows)[number];
  const cols = useMemo<Column<Row>[]>(
    () => [
      { key: "rank", label: "ROS #", align: "right", sortValue: (r) => r.rank },
      {
        key: "name",
        label: "Player",
        sortValue: (r) => r.PLAYER_NAME,
        render: (r) => (
          <span className="font-medium">
            {r.PLAYER_NAME}
            {r.status_override && (
              <Chip tone="warn" title={r.status_override}>
                OUT
              </Chip>
            )}
            {r.redist_mpg != null && r.redist_mpg >= 0.5 && (
              <Chip tone="up" title="Projected extra minutes inherited from currently-OUT teammates (EXP-030 redistribution)">
                +{f1(r.redist_mpg)} MPG
              </Chip>
            )}
            {r.breakout_p != null && r.breakout_p >= 0.25 && (
              <Chip tone="accent" title="EXP-026 breakout archetype probability (informational)">
                brk {Math.round(r.breakout_p * 100)}%
              </Chip>
            )}
          </span>
        ),
      },
      { key: "team", label: "Team", hideBelow: "sm", render: (r) => r.TEAM_ABBREVIATION ?? "—", sortValue: (r) => r.TEAM_ABBREVIATION },
      { key: "fpts_pg", label: "FP/G", align: "right", sortValue: (r) => r.fpts_pg, render: (r) => f1(r.fpts_pg) },
      {
        key: "fpts_delta_14",
        label: "14d Δ",
        title: "ROS FP/G move over ~14 days (Trends view) — rising free agents first",
        align: "right",
        hideBelow: "md",
        sortValue: (r) => r.fpts_delta_14,
        render: (r) =>
          r.fpts_delta_14 == null ? (
            <span className="text-ink-3">—</span>
          ) : (
            <span className={r.fpts_delta_14 > 0 ? "text-up" : r.fpts_delta_14 < 0 ? "text-down" : "text-ink-3"}>
              {signed(r.fpts_delta_14)}
            </span>
          ),
      },
      {
        key: "n_games",
        label: "Games",
        title: "Games scheduled in the chosen week",
        align: "right",
        sortValue: (r) => r.n_games,
        render: (r) => (data?.has_schedule ? r.n_games : "—"),
      },
      {
        key: "weekly_fpts",
        label: "Week FP",
        title: "FP/G × games that week — the streaming number",
        align: "right",
        sortValue: (r) => r.weekly_fpts,
        render: (r) => (data?.has_schedule ? <span className="font-semibold">{f1(r.weekly_fpts)}</span> : "—"),
      },
    ],
    [data],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Week">
          <Select
            value={week != null ? String(week) : ""}
            onChange={(v) => setWeek(Number(v))}
            options={
              weeks?.has_schedule
                ? weeks.weeks.map((w) => ({ value: String(w.week), label: `${w.week_name} (${w.start.slice(5)}–${w.end.slice(5)})` }))
                : [{ value: "", label: "no schedule" }]
            }
          />
        </Field>
        <Field label="Team">
          <Select value={team} onChange={setTeam} options={teams.map((t) => ({ value: t, label: t }))} />
        </Field>
        <Field label="Show">
          <Select
            value={String(topN)}
            onChange={(v) => setTopN(Number(v))}
            options={[50, 100, 200].map((n) => ({ value: String(n), label: `Top ${n}` }))}
          />
        </Field>
        <SearchInput value={q} onChange={setQ} placeholder="Search players…" className="w-52" />
        <Field label="Rosters">
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={rosterBusy}
              onClick={() => void syncRosters(false)}
              title="Pull live ESPN league rosters (mRoster) so ownership follows in-season adds/drops — V3b. Empty pre-draft; falls back to Draft Room picks."
              className="rounded-md border border-line px-2 py-1 text-[12px] font-medium hover:bg-surface-2 disabled:opacity-50"
            >
              {rosterBusy ? "Syncing…" : "↻ ESPN rosters"}
            </button>
            {data?.roster_source === "espn_live" && (
              <button
                type="button"
                disabled={rosterBusy}
                onClick={() => void syncRosters(true)}
                title="Stop using live ESPN rosters; revert ownership to the Draft Room picks"
                className="rounded-md border border-line px-2 py-1 text-[12px] text-ink-3 hover:bg-surface-2 disabled:opacity-50"
              >
                use picks
              </button>
            )}
          </div>
        </Field>
        {data && (
          <div className="flex flex-wrap items-center gap-2 pb-1 text-[12px] text-ink-3">
            <span>{data.mode === "ros" ? "vs latest nightly ROS board" : "preseason board"}</span>
            {data.roster_source === "espn_live" && (
              <Chip tone="up" title={`Ownership is live ESPN rosters (adds/drops), pulled ${data.rosters_asof ?? ""}`}>
                live ESPN rosters{data.rosters_asof ? ` · ${data.rosters_asof.slice(0, 16).replace("T", " ")}` : ""}
              </Chip>
            )}
            {data.ownership ? (
              <span>· {data.n_rostered} rostered players hidden</span>
            ) : (
              <Chip tone="neutral" title="Rostered players are marked once the Draft Room has picks (draft, connect ESPN, or Simulate), or once you pull live ESPN rosters — until then everyone shows">
                no rosters yet — showing everyone
              </Chip>
            )}
            {!data.has_schedule && (
              <Chip tone="warn" title="Weekly game counts need the schedule pull (publishes ~mid-August)">
                no schedule — season ranking only
              </Chip>
            )}
            {rosterMsg && <span className="text-ink-3">· {rosterMsg}</span>}
          </div>
        )}
      </div>

      {error && <ErrorNote message={error} />}
      {loading && <Spinner label="Loading waiver wire…" />}
      {data && rows.length === 0 && !loading && (
        <Card>
          <EmptyNote>No unrostered players match the filters.</EmptyNote>
        </Card>
      )}
      {rows.length > 0 && (
        <DataTable columns={cols} rows={rows} rowKey={(r) => r.PLAYER_ID} onRowClick={(r) => nav(`/players/${r.PLAYER_ID}`)} dense />
      )}
    </div>
  );
}
