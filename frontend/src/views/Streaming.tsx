// Single-add/drop scenarios only. ESPN transaction rules are not saved locally;
// every result is conditional on the manager's explicit timing and budget inputs.

import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { StreamingResponse, WeeksResponse, useApi } from "../lib/api";
import { f1, signed } from "../lib/format";
import { LineupDetail } from "../components/LineupDetail";
import { Card, Chip, EmptyNote, ErrorNote, Field, Select, Spinner } from "../components/ui";

export default function Streaming() {
  const weeks = useApi<WeeksResponse>("/api/weeks").data;
  const [week, setWeek] = useState<number | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [effective, setEffective] = useState("");
  const [lock, setLock] = useState<"before_games" | "after_games">("before_games");
  const [drops, setDrops] = useState<number[]>([]);
  const [keep, setKeep] = useState<number[]>([]);
  const [used, setUsed] = useState("");
  const [limit, setLimit] = useState("");
  const [rulesConfirmed, setRulesConfirmed] = useState(false);
  const [pickupText, setPickupText] = useState("");
  const [runUrl, setRunUrl] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const setup = useApi<StreamingResponse>(week == null ? "/api/streaming" : `/api/streaming?week=${week}`);
  const run = useApi<StreamingResponse>(runUrl);
  const data = runUrl ? run.data : setup.data;
  const error = runUrl ? run.error : setup.error;
  const loading = runUrl ? run.loading : setup.loading;

  useEffect(() => {
    if (week == null && setup.data?.has_schedule && setup.data.week != null) setWeek(setup.data.week);
  }, [setup.data, week]);
  useEffect(() => {
    if (!setup.data?.has_schedule) return;
    setStart(setup.data.start ?? "");
    setEnd(setup.data.end ?? "");
    setEffective(setup.data.start ?? "");
  }, [setup.data?.week, setup.data?.start, setup.data?.end]);

  const dayOptions = (setup.data?.days ?? []).map((d) => ({ value: d, label: d }));
  const roster = setup.data?.roster ?? [];
  const results = data?.results ?? [];
  const chosen = results.find((r) => `${r.drop_id}:${r.pickup_id}` === selected) ?? results[0];
  const unknown = data?.rules?.unverified ?? [];
  const choices = setup.data?.candidate_choices ?? [];
  const pickupOption = (c: (typeof choices)[number]) => `${c.name} (#${c.player_id})`;
  const selectedPickup = choices.find((c) => pickupOption(c) === pickupText);
  const pickupListId = useId();

  function changeWeek(value: string) {
    setWeek(Number(value));
    setRunUrl(null);
    setSelected(null);
    setDrops([]);
    setKeep([]);
    setPickupText("");
  }

  function toggleDrop(id: number) {
    setDrops((cur) => cur.includes(id) ? cur.filter((p) => p !== id) : [...cur, id]);
    setKeep((cur) => cur.filter((p) => p !== id));
    setRunUrl(null);
  }

  function toggleKeep(id: number) {
    setKeep((cur) => cur.includes(id) ? cur.filter((p) => p !== id) : [...cur, id]);
    setDrops((cur) => cur.filter((p) => p !== id));
    setRunUrl(null);
  }

  function evaluate() {
    const q = new URLSearchParams();
    if (week != null) q.set("week", String(week));
    q.set("start", start);
    q.set("end", end);
    q.set("effective_date", effective);
    q.set("lock_rule", lock);
    q.set("drops", drops.join(","));
    if (keep.length) q.set("keep", keep.join(","));
    if (used !== "") q.set("acquisitions_used", used);
    if (limit !== "") q.set("acquisition_limit", limit);
    if (selectedPickup) q.set("pickup_id", String(selectedPickup.player_id));
    q.set("rules_confirmed", String(rulesConfirmed));
    setSelected(null);
    setRunUrl(`/api/streaming?${q.toString()}`);
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Personal Streaming Planner</h1>
        <p className="mt-1 text-[12px] text-ink-3">Compare one assumed add/drop against your feasible daily lineup. No transaction is sent to ESPN.</p>
      </div>

      {error && <ErrorNote message={error} />}
      {loading && <Spinner label="Calculating streaming scenarios…" />}
      {data && !data.has_team && <Card className="p-4"><EmptyNote>{data.note} <Link to="/room" className="text-accent underline">Draft Room</Link></EmptyNote></Card>}
      {data?.has_team && (
        <>
          <Card className="p-4">
            <div className="flex flex-wrap items-center gap-2 text-[12px]">
              <strong>Source: {data.roster_source === "espn_live" ? "ESPN roster snapshot" : "Draft Room picks"}</strong>
              {data.rosters_asof && <span className="text-ink-3">pulled {data.rosters_asof}</span>}
              {data.ownership_status === "draft_only" && <Chip tone="warn">Ownership may be stale after adds/drops</Chip>}
              {data.ownership_status === "stale_snapshot" && <Chip tone="warn">Roster snapshot over 24h old or undated</Chip>}
            </div>
            <p className="mt-2 text-[12px] text-ink-3">League acquisition limit, waiver processing, game locks, timezone and IR transaction rules are not verified in the saved settings. Choose an assumed effective date and lock timing. Results remain conditional even when you confirm your assumptions.</p>
            <p className="mt-1 text-[11px] text-ink-3">Unverified: {unknown.join(" · ")}</p>
          </Card>

          <Card className="p-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Matchup week">
                <Select value={week == null ? "" : String(week)} onChange={changeWeek}
                  options={weeks?.has_schedule ? weeks.weeks.map((w) => ({ value: String(w.week), label: `${w.week_name} (${w.start}–${w.end})` })) : [{ value: "", label: "No schedule" }]} />
              </Field>
              <Field label="Range start"><Select value={start} onChange={(v) => { setStart(v); setRunUrl(null); }} options={dayOptions} /></Field>
              <Field label="Range end"><Select value={end} onChange={(v) => { setEnd(v); setRunUrl(null); }} options={dayOptions} /></Field>
              <Field label="Move effective on"><Select value={effective} onChange={(v) => { setEffective(v); setRunUrl(null); }} options={dayOptions} /></Field>
              <Field label="Game lock assumption">
                <Select value={lock} onChange={(v) => { setLock(v as typeof lock); setRunUrl(null); }} options={[
                  { value: "before_games", label: "Before games on effective date" },
                  { value: "after_games", label: "After games; next date counts" },
                ]} />
              </Field>
              <Field label="Acquisitions already used">
                <input type="number" min="0" value={used} onChange={(e) => { setUsed(e.target.value); setRunUrl(null); }} placeholder="Unknown" className="h-8 rounded-lg border border-bdr bg-surface px-2 text-sm" />
              </Field>
              <Field label="Acquisition limit">
                <input type="number" min="0" value={limit} onChange={(e) => { setLimit(e.target.value); setRunUrl(null); }} placeholder="Unknown" className="h-8 rounded-lg border border-bdr bg-surface px-2 text-sm" />
              </Field>
              <Field label="Inspect one available player (optional)">
                <input list={pickupListId} value={pickupText} onChange={(e) => { setPickupText(e.target.value); setRunUrl(null); }}
                  placeholder="Blank ranks all candidates" className="h-8 rounded-lg border border-bdr bg-surface px-2 text-sm" />
                <datalist id={pickupListId}>{choices.map((c) => <option key={c.player_id} value={pickupOption(c)} label={`${c.team ?? "team unknown"} · ${f1(c.fpts_pg)} FP/G${c.status ? " · OUT" : ""}`} />)}</datalist>
              </Field>
            </div>
            {pickupText && !selectedPickup && <p className="mt-1 text-[11px] text-warn">Choose a player from the suggestions, or clear this field to rank everyone.</p>}
            <label className="mt-3 flex items-start gap-2 text-[12px] text-ink-2">
              <input type="checkbox" checked={rulesConfirmed} onChange={(e) => { setRulesConfirmed(e.target.checked); setRunUrl(null); }} />
              I have checked that my league's waiver delay, acquisition budget, lock rules, timezone and roster/IR rules allow a one-for-one move by this date.
            </label>
            <div className="mt-3 text-[12px] text-ink-3">{data.rules?.budget_status === "blocked" ? "Assumed acquisition limit reached. No move is evaluated." : data.rules?.budget_status === "unknown" ? "Acquisition budget is unknown; rankings are conditional." : "Acquisition count is under the entered limit; other rules remain assumed."}</div>
          </Card>

          <Card className="p-4">
            <div className="text-[12px] font-bold">My roster · choose drop candidates and optional keeps</div>
            <p className="mt-1 text-[11px] text-ink-3">Each result makes one add/drop. A kept player cannot be selected as a drop. Injured players retain their availability-filtered dates.</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {roster.map((r) => (
                <div key={r.PLAYER_ID} className="rounded-lg border border-bdr px-2 py-1.5 text-[12px]">
                  <div className="font-medium">{r.PLAYER_NAME} <span className="text-ink-3">{r.TEAM_ABBREVIATION ?? "team unknown"} · {f1(r.fpts_pg)} FP/G</span></div>
                  <div className="mt-1 flex gap-3">
                    <label className="flex items-center gap-1"><input type="checkbox" checked={drops.includes(r.PLAYER_ID)} onChange={() => toggleDrop(r.PLAYER_ID)} />Drop</label>
                    <label className="flex items-center gap-1"><input type="checkbox" checked={keep.includes(r.PLAYER_ID)} onChange={() => toggleKeep(r.PLAYER_ID)} />Keep</label>
                  </div>
                </div>
              ))}
            </div>
            <button type="button" disabled={!data.has_schedule || drops.length === 0 || !start || !end || !effective || start > end || effective < start || effective > end || (!!pickupText && !selectedPickup)}
              onClick={evaluate} className="mt-3 rounded-lg bg-accent px-4 py-2 text-[13px] font-bold text-accent-ink disabled:opacity-50">
              Compare single-move scenarios
            </button>
            {!data.has_schedule && <p className="mt-2 text-[12px] text-warn">{data.note ?? "No cached schedule; streaming points cannot be calculated yet."}</p>}
          </Card>

          {runUrl && data.before && (
            <Card className="p-4 text-[12px]">
              <strong>Current roster:</strong> usable {data.before.usable_points == null ? "—" : f1(data.before.usable_points)} FP · raw scheduled {data.before.raw_points == null ? "—" : f1(data.before.raw_points)} FP across {data.days?.length ?? 0} game dates.
              {!data.before.exact && <span className="ml-1 text-warn">Missing data; known feasible floor {f1(data.before.known_usable_points)} FP.</span>}
              {data.note && <p className="mt-1 text-ink-3">{data.note}</p>}
            </Card>
          )}

          {runUrl && results.length > 0 && (
            <>
              <Card className="p-4">
                <div className="text-[12px] font-bold">Ranked single moves · {data.evaluated_count} evaluated{data.truncated ? ", top 50 shown" : ""}</div>
                <p className="mt-1 text-[11px] text-ink-3">Ranked by incremental usable FP; raw volume and {data.projection_source === "ros" ? "nightly ROS" : "preseason board"} FP/G are separate. Unknown eligibility or projection places a move after scored results. Every result assumes the move can take effect on the selected date.</p>
                <div className="mt-2 space-y-1.5">
                  {results.map((r) => {
                    const key = `${r.drop_id}:${r.pickup_id}`;
                    return <button type="button" key={key} onClick={() => setSelected(key)}
                      className={`w-full rounded-lg border px-3 py-2 text-left text-[12px] ${chosen && key === `${chosen.drop_id}:${chosen.pickup_id}` ? "border-accent bg-accent-soft" : "border-bdr hover:bg-surface-2"}`}>
                      <span className="font-semibold">Add {r.pickup_name}</span> <span className="text-ink-3">for {r.drop_name}</span>
                      {r.pickup_status && <span className="ml-1 text-warn">OUT</span>}
                      <span className="mt-1 block tnum">Usable {r.usable_delta == null ? "unknown" : `${signed(r.usable_delta)} FP`} · raw {r.raw_delta == null ? "unknown" : `${signed(r.raw_delta)} FP`} · {data.projection_source === "ros" ? "ROS" : "Board"} {f1(r.pickup_fpts_pg)} FP/G</span>
                    </button>;
                  })}
                </div>
              </Card>
              {chosen && <Card className="p-4 text-[12px]">
                <div className="font-bold">{chosen.pickup_name} for {chosen.drop_name}</div>
                <div className="mt-1 text-ink-3">Usable game dates: {chosen.pickup_start_dates.join(", ") || "none"}</div>
                <div className="text-ink-3">Scheduled but benched: {chosen.pickup_benched_dates.join(", ") || "none"}</div>
                <div className="text-ink-3">Pickup raw {chosen.pickup_raw_points == null ? "unknown" : f1(chosen.pickup_raw_points)} FP · used {chosen.pickup_used_points == null ? "unknown" : f1(chosen.pickup_used_points)} FP · dropped starter production {chosen.drop_lost_starter_points == null ? "unknown" : f1(chosen.drop_lost_starter_points)} FP</div>
                {chosen.usable_delta == null && <div className="mt-1 text-warn">Usable gain is unknown because this roster or pickup lacks eligibility, FP/G or game dates.</div>}
              </Card>}
              {chosen && <LineupDetail lineup={chosen.after} title="After-move feasible starts" />}
            </>
          )}
          {runUrl && !loading && results.length === 0 && data.has_schedule && <Card className="p-4"><EmptyNote>{data.note ?? "No available scheduled pickups for this scenario."}</EmptyNote></Card>}
        </>
      )}
    </div>
  );
}
