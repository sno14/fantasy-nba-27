// V2 — Trade targets (docs/ui-views-plan.md): the buy-low / sell-high disagreement
// finder. Three signals shown side by side — market gap (consensus vs our rank: the
// likely trade price), heat gap (naive recency-chaser vs the model: what a streak looks
// like without a model), and the 14d trend. Deliberately no composite score.

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TradeRow, TradeTargetsResponse, useApi } from "../lib/api";
import { f1, signed } from "../lib/format";
import { Column, DataTable } from "../components/DataTable";
import { RiskMeter } from "../components/charts";
import { Card, Chip, EmptyNote, ErrorNote, Field, SearchInput, Segmented, Spinner } from "../components/ui";

type Side = "buy" | "sell";

// A gap only counts as a signal once it clears noise.
const GAP_MIN = 8;

export default function Trades() {
  const nav = useNavigate();
  const [side, setSide] = useState<Side>("buy");
  const [q, setQ] = useState("");

  const { data, error, loading } = useApi<TradeTargetsResponse>("/api/trade-targets");

  const rows = useMemo(() => {
    if (!data) return [];
    // Classification signal: the market gap. Heat only substitutes when there is no
    // market pull at all — per-row fallback would pull deep-bench streak noise into
    // the lists whenever a name misses the market join.
    const gap = (r: TradeRow) =>
      data.has_market ? r.market_gap : r.heat_gap != null ? -r.heat_gap : null;
    let base = data.rows.filter((r) => {
      const g = gap(r);
      return g != null && (side === "buy" ? g >= GAP_MIN : g <= -GAP_MIN);
    });
    if (q) base = base.filter((r) => r.PLAYER_NAME.toLowerCase().includes(q.toLowerCase()));
    return base.sort((a, b) => Math.abs(gap(b) ?? 0) - Math.abs(gap(a) ?? 0));
  }, [data, side, q]);

  const cols = useMemo<Column<TradeRow>[]>(
    () => [
      { key: "rank", label: "Our #", title: "Our current ROS/board rank", align: "right", sortValue: (r) => r.rank },
      {
        key: "consensus_rank",
        label: "Mkt #",
        title: "Market consensus rank (latest pull_market.py archive) — roughly what leaguemates believe",
        align: "right",
        sortValue: (r) => r.consensus_rank,
        render: (r) => r.consensus_rank ?? "—",
      },
      {
        key: "market_gap",
        label: "Mkt gap",
        title: "consensus − ours: positive = the market is colder on him than we are (buy low)",
        align: "right",
        sortValue: (r) => r.market_gap,
        render: (r) =>
          r.market_gap == null ? (
            <span className="text-ink-3">—</span>
          ) : (
            <Chip tone={r.market_gap > 0 ? "up" : r.market_gap < 0 ? "down" : "neutral"}>{signed(r.market_gap, 0)}</Chip>
          ),
      },
      {
        key: "name",
        label: "Player",
        sortValue: (r) => r.PLAYER_NAME,
        render: (r) => (
          <span className="font-medium">
            {r.PLAYER_NAME}
            {r.is_mine && <Chip tone="accent">mine</Chip>}
            {!r.is_mine && r.rostered_by != null && (
              <Chip tone="neutral" title="Rostered by this league team (draft-room picks)">T{r.rostered_by}</Chip>
            )}
            {r.status_override && (
              <Chip tone="warn" title={r.status_override}>
                OUT
              </Chip>
            )}
          </span>
        ),
      },
      { key: "team", label: "Team", hideBelow: "sm", render: (r) => r.TEAM_ABBREVIATION ?? "—", sortValue: (r) => r.TEAM_ABBREVIATION },
      { key: "fpts_pg", label: "FP/G", align: "right", sortValue: (r) => r.fpts_pg, render: (r) => f1(r.fpts_pg) },
      {
        key: "heat_gap",
        label: "Heat",
        title: "our rank − naive rank: positive = a hot streak the model discounts (sell-high signal); negative = a cold streak it looks through (buy-low signal)",
        align: "right",
        hideBelow: "md",
        sortValue: (r) => r.heat_gap,
        render: (r) =>
          r.heat_gap == null || Math.abs(r.heat_gap) < GAP_MIN ? (
            <span className="text-ink-3">—</span>
          ) : (
            <Chip tone={r.heat_gap > 0 ? "down" : "up"} title={r.heat_gap > 0 ? "hot streak" : "cold streak"}>
              {r.heat_gap > 0 ? "hot" : "cold"} {signed(r.heat_gap, 0)}
            </Chip>
          ),
      },
      {
        key: "fpts_delta_14",
        label: "14d Δ",
        title: "Our own ROS FP/G move over ~14 days (Trends view)",
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
        key: "risk",
        label: "Risk",
        hideBelow: "lg",
        sortValue: (r) => r.risk,
        render: (r) => (r.risk == null ? <span className="text-ink-3">—</span> : <RiskMeter value={r.risk} />),
      },
    ],
    [],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Side">
          <Segmented
            value={side}
            onChange={(v) => setSide(v as Side)}
            options={[
              { value: "buy", label: "Buy low", title: "We value him meaningfully above the market price" },
              { value: "sell", label: "Sell high", title: "The market (or a hot streak) prices him above our projection" },
            ]}
          />
        </Field>
        <SearchInput value={q} onChange={setQ} placeholder="Search players…" className="w-52" />
        {data && (
          <div className="flex flex-wrap items-center gap-2 pb-1 text-[12px] text-ink-3">
            <span>{data.mode === "ros" ? "vs latest nightly ROS board" : "preseason board"}</span>
            {data.has_market ? (
              <span>· market {data.market_date}</span>
            ) : (
              <Chip tone="warn" title="No market archive — run scripts/pull_market.py (re-pulls are a Sept calendar item)">
                no market pull
              </Chip>
            )}
            {!data.has_naive && (
              <Chip tone="warn" title="Heat needs the nightly naive-updater columns — snapshots start at the opening-night cron">
                no naive line
              </Chip>
            )}
            {!data.ownership && (
              <Chip tone="neutral" title="Owner chips appear once the Draft Room has picks (draft, connect ESPN, or Simulate)">
                no rosters yet
              </Chip>
            )}
          </div>
        )}
      </div>

      <Card className="text-[12px] text-ink-3">
        A <span className="font-semibold text-ink-2">disagreement finder, not advice</span>: “buy low” = our
        projection sits ≥{GAP_MIN} ranks above the market’s price; “sell high” = the market or a hot streak
        prices him ≥{GAP_MIN} ranks above our projection. The signals are shown separately — judge the
        mechanism, then trade the price gap.
      </Card>

      {error && <ErrorNote message={error} />}
      {loading && <Spinner label="Loading trade targets…" />}
      {data && rows.length === 0 && !loading && (
        <Card>
          <EmptyNote>
            No {side === "buy" ? "buy-low" : "sell-high"} gaps ≥ {GAP_MIN} ranks right now
            {!data.has_market && !data.has_naive ? " — both signal sources are missing (see the chips above)" : ""}.
          </EmptyNote>
        </Card>
      )}
      {rows.length > 0 && (
        <DataTable columns={cols} rows={rows} rowKey={(r) => r.PLAYER_ID} onRowClick={(r) => nav(`/players/${r.PLAYER_ID}`)} dense />
      )}
    </div>
  );
}
