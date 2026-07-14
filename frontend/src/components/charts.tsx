// SVG chart primitives, written against the design tokens (they re-theme with the
// toggle automatically because every color is a CSS variable).
//
// Marks follow the dataviz spec: 2px lines, >=8px hover targets, recessive hairline
// grid, direct value labels only where selective, and an always-on hover layer
// (crosshair + tooltip on lines, per-mark tooltip on bars/dots).

import { ReactNode, useCallback, useMemo, useRef, useState } from "react";

// ------------------------------------------------------------------ shared tooltip
interface Tip {
  x: number;
  y: number;
  body: ReactNode;
}

function TipBox({ tip, width }: { tip: Tip; width: number }) {
  const left = tip.x > width - 140;
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-lg border border-bdr bg-surface px-2.5 py-1.5 text-xs shadow-[var(--shadow)]"
      style={{
        left: left ? undefined : tip.x + 12,
        right: left ? width - tip.x + 12 : undefined,
        top: Math.max(0, tip.y - 14),
      }}
    >
      {tip.body}
    </div>
  );
}

// ---------------------------------------------------------------------- line chart
export interface Series {
  name: string;
  color: string; // a CSS var, e.g. "var(--series-1)"
  points: { x: number; label: string; y: number | null }[];
}

/** Multi-series line chart on a shared ordinal x axis, crosshair + tooltip. */
export function LineChart({
  series,
  height = 220,
  yLabel,
  unit = "",
}: {
  series: Series[];
  height?: number;
  yLabel?: string;
  unit?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const [width, setWidth] = useState(560);

  const measure = useCallback((el: HTMLDivElement | null) => {
    (wrap as { current: HTMLDivElement | null }).current = el;
    if (el) {
      const ro = new ResizeObserver(() => setWidth(el.clientWidth));
      ro.observe(el);
      setWidth(el.clientWidth);
    }
  }, []);

  const pad = { l: 40, r: 12, t: 12, b: 24 };
  const labels = series[0]?.points.map((p) => p.label) ?? [];
  const n = labels.length;
  const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter((v): v is number => v != null);
  const yMax = Math.max(1, ...ys) * 1.08;
  const yMin = Math.min(0, ...ys);
  const px = (i: number) => pad.l + (n <= 1 ? 0.5 : i / (n - 1)) * (width - pad.l - pad.r);
  const py = (v: number) => pad.t + (1 - (v - yMin) / (yMax - yMin)) * (height - pad.t - pad.b);
  const ticks = useMemo(() => {
    const step = Math.max(1, Math.ceil((yMax - yMin) / 4 / 5) * 5);
    const out: number[] = [];
    for (let v = Math.ceil(yMin / step) * step; v <= yMax; v += step) out.push(v);
    return out;
  }, [yMax, yMin]);

  const onMove = (e: React.MouseEvent) => {
    const rect = wrap.current?.getBoundingClientRect();
    if (!rect || n === 0) return;
    const mx = e.clientX - rect.left;
    const i = Math.max(
      0,
      Math.min(n - 1, Math.round(((mx - pad.l) / (width - pad.l - pad.r)) * (n - 1))),
    );
    setHoverX(i);
    setTip({
      x: px(i),
      y: e.clientY - rect.top,
      body: (
        <div className="space-y-0.5">
          <div className="font-semibold text-ink">{labels[i]}</div>
          {series.map((s) => (
            <div key={s.name} className="flex items-center gap-1.5 text-ink-2">
              <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
              {s.name}: <span className="tnum font-medium text-ink">
                {s.points[i]?.y != null ? s.points[i].y!.toFixed(1) : "—"}
                {unit}
              </span>
            </div>
          ))}
        </div>
      ),
    });
  };

  const xTickEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(width / 90))));

  return (
    <div ref={measure} className="relative" onMouseMove={onMove} onMouseLeave={() => {
      setTip(null);
      setHoverX(null);
    }}>
      <svg width={width} height={height} role="img" aria-label={yLabel}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={width - pad.r} y1={py(v)} y2={py(v)} stroke="var(--grid)" />
            <text x={pad.l - 6} y={py(v) + 3.5} textAnchor="end" fontSize="10" fill="var(--ink-3)" className="tnum">
              {v}
            </text>
          </g>
        ))}
        <line x1={pad.l} x2={width - pad.r} y1={py(Math.max(0, yMin))} y2={py(Math.max(0, yMin))} stroke="var(--baseline)" />
        {labels.map((lb, i) =>
          i % xTickEvery === 0 ? (
            <text key={lb + i} x={px(i)} y={height - 8} textAnchor="middle" fontSize="10" fill="var(--ink-3)">
              {lb}
            </text>
          ) : null,
        )}
        {hoverX != null && (
          <line x1={px(hoverX)} x2={px(hoverX)} y1={pad.t} y2={height - pad.b} stroke="var(--baseline)" strokeDasharray="3 3" />
        )}
        {series.map((s) => {
          const path = s.points
            .map((p, i) => (p.y == null ? null : `${i === 0 || s.points[i - 1].y == null ? "M" : "L"}${px(i)},${py(p.y)}`))
            .filter(Boolean)
            .join(" ");
          return (
            <g key={s.name}>
              <path d={path} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              {s.points.map((p, i) =>
                p.y == null ? null : (
                  <circle
                    key={i}
                    cx={px(i)}
                    cy={py(p.y)}
                    r={hoverX === i ? 4 : 2.5}
                    fill={s.color}
                    stroke="var(--surface)"
                    strokeWidth="2"
                  />
                ),
              )}
            </g>
          );
        })}
      </svg>
      {series.length > 1 && (
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 pl-10 text-xs text-ink-2">
          {series.map((s) => (
            <span key={s.name} className="inline-flex items-center gap-1.5">
              <span className="h-0.5 w-4 rounded" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      {tip && <TipBox tip={tip} width={width} />}
    </div>
  );
}

// ----------------------------------------------------------------------- bar chart
export function BarChart({
  points,
  height = 200,
  color = "var(--series-1)",
  unit = "",
  name,
}: {
  points: { label: string; y: number; sub?: string }[];
  height?: number;
  color?: string;
  unit?: string;
  name: string;
}) {
  const [tip, setTip] = useState<Tip | null>(null);
  const [width, setWidth] = useState(560);
  const wrap = useRef<HTMLDivElement>(null);
  const measure = useCallback((el: HTMLDivElement | null) => {
    (wrap as { current: HTMLDivElement | null }).current = el;
    if (el) {
      const ro = new ResizeObserver(() => setWidth(el.clientWidth));
      ro.observe(el);
      setWidth(el.clientWidth);
    }
  }, []);

  const pad = { l: 36, r: 8, t: 10, b: 20 };
  const n = points.length;
  const yMax = Math.max(1, ...points.map((p) => p.y)) * 1.08;
  const bw = Math.max(2, Math.min(14, (width - pad.l - pad.r) / Math.max(n, 1) - 2));
  const px = (i: number) => pad.l + ((i + 0.5) / Math.max(n, 1)) * (width - pad.l - pad.r);
  const py = (v: number) => pad.t + (1 - v / yMax) * (height - pad.t - pad.b);
  const ticks = [0, Math.round(yMax / 2), Math.round(yMax)];
  const xTickEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(width / 70))));

  return (
    <div ref={measure} className="relative" onMouseLeave={() => setTip(null)}>
      <svg width={width} height={height} role="img" aria-label={name}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={width - pad.r} y1={py(v)} y2={py(v)} stroke="var(--grid)" />
            <text x={pad.l - 5} y={py(v) + 3.5} textAnchor="end" fontSize="10" fill="var(--ink-3)" className="tnum">
              {v}
            </text>
          </g>
        ))}
        <line x1={pad.l} x2={width - pad.r} y1={py(0)} y2={py(0)} stroke="var(--baseline)" />
        {points.map((p, i) => (
          <g key={i}>
            <rect
              x={px(i) - bw / 2}
              y={py(p.y)}
              width={bw}
              height={Math.max(0, py(0) - py(p.y))}
              rx={Math.min(3, bw / 2)}
              fill={color}
              opacity={tip ? 0.75 : 1}
            />
            <rect
              x={px(i) - Math.max(bw, 10) / 2}
              y={pad.t}
              width={Math.max(bw, 10)}
              height={height - pad.t - pad.b}
              fill="transparent"
              onMouseEnter={(e) => {
                const rect = wrap.current?.getBoundingClientRect();
                setTip({
                  x: px(i),
                  y: rect ? e.clientY - rect.top : py(p.y),
                  body: (
                    <div>
                      <div className="font-semibold text-ink">{p.label}</div>
                      <div className="text-ink-2">
                        <span className="tnum font-medium text-ink">{p.y.toFixed(1)}{unit}</span>
                        {p.sub && <span> · {p.sub}</span>}
                      </div>
                    </div>
                  ),
                });
              }}
            />
          </g>
        ))}
        {points.map((p, i) =>
          i % xTickEvery === 0 ? (
            <text key={i} x={px(i)} y={height - 6} textAnchor="middle" fontSize="10" fill="var(--ink-3)">
              {p.label}
            </text>
          ) : null,
        )}
      </svg>
      {tip && <TipBox tip={tip} width={width} />}
    </div>
  );
}

// -------------------------------------------------------------- range strip (table)
/** Inline floor→median→ceiling strip for table rows: a thin rule spanning the global
    [min,max] with a median dot — one glance = position + spread. */
export function RangeStrip({
  p10,
  p50,
  p90,
  min,
  max,
  width = 120,
}: {
  p10: number;
  p50: number;
  p90: number;
  min: number;
  max: number;
  width?: number;
}) {
  const h = 16;
  const x = (v: number) => 4 + ((v - min) / Math.max(1, max - min)) * (width - 8);
  return (
    <svg width={width} height={h} className="block" aria-hidden>
      <line x1={4} x2={width - 4} y1={h / 2} y2={h / 2} stroke="var(--grid)" strokeWidth="1" />
      <line x1={x(p10)} x2={x(p90)} y1={h / 2} y2={h / 2} stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" opacity="0.45" />
      <circle cx={x(p50)} cy={h / 2} r="3.5" fill="var(--accent)" stroke="var(--surface)" strokeWidth="1.5" />
    </svg>
  );
}

// ------------------------------------------------------------------- range dot plot
/** Horizontal floor→median→ceiling dot plot for the board's top-N. Single logical
    series (per-player ranges) → no legend; identity is the row label. */
export function RangePlot({
  rows,
  onPick,
}: {
  rows: { name: string; p10: number; p50: number; p90: number; extra?: string }[];
  onPick?: (name: string) => void;
}) {
  const [tip, setTip] = useState<Tip | null>(null);
  const [width, setWidth] = useState(720);
  const wrap = useRef<HTMLDivElement>(null);
  const measure = useCallback((el: HTMLDivElement | null) => {
    (wrap as { current: HTMLDivElement | null }).current = el;
    if (el) {
      const ro = new ResizeObserver(() => setWidth(el.clientWidth));
      ro.observe(el);
      setWidth(el.clientWidth);
    }
  }, []);

  const rowH = 24;
  const pad = { l: 150, r: 16, t: 8, b: 22 };
  const height = pad.t + pad.b + rows.length * rowH;
  const lo = Math.min(...rows.map((r) => r.p10));
  const hi = Math.max(...rows.map((r) => r.p90));
  const x = (v: number) => pad.l + ((v - lo) / Math.max(1, hi - lo)) * (width - pad.l - pad.r);
  const y = (i: number) => pad.t + i * rowH + rowH / 2;
  const step = Math.max(250, Math.ceil((hi - lo) / 6 / 250) * 250);
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);

  return (
    <div ref={measure} className="relative" onMouseLeave={() => setTip(null)}>
      <svg width={width} height={height} role="img" aria-label="Projected season total: floor to ceiling">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={x(v)} x2={x(v)} y1={pad.t} y2={height - pad.b} stroke="var(--grid)" />
            <text x={x(v)} y={height - 6} textAnchor="middle" fontSize="10" fill="var(--ink-3)" className="tnum">
              {v.toLocaleString()}
            </text>
          </g>
        ))}
        {rows.map((r, i) => (
          <g
            key={r.name}
            className={onPick ? "cursor-pointer" : undefined}
            onClick={() => onPick?.(r.name)}
            onMouseEnter={(e) => {
              const rect = wrap.current?.getBoundingClientRect();
              setTip({
                x: x(r.p50),
                y: rect ? e.clientY - rect.top : y(i),
                body: (
                  <div>
                    <div className="font-semibold text-ink">{r.name}</div>
                    <div className="tnum text-ink-2">
                      floor {Math.round(r.p10).toLocaleString()} · median{" "}
                      <span className="font-medium text-ink">{Math.round(r.p50).toLocaleString()}</span> · ceiling{" "}
                      {Math.round(r.p90).toLocaleString()}
                      {r.extra && <span> · {r.extra}</span>}
                    </div>
                  </div>
                ),
              });
            }}
          >
            <rect x={0} y={y(i) - rowH / 2} width={width} height={rowH} fill="transparent" />
            <text x={pad.l - 8} y={y(i) + 3.5} textAnchor="end" fontSize="11" fill="var(--ink-2)">
              {r.name.length > 22 ? r.name.slice(0, 21) + "…" : r.name}
            </text>
            <line x1={x(r.p10)} x2={x(r.p90)} y1={y(i)} y2={y(i)} stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" opacity="0.4" />
            <circle cx={x(r.p50)} cy={y(i)} r="4" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" />
          </g>
        ))}
      </svg>
      {tip && <TipBox tip={tip} width={width} />}
    </div>
  );
}

// ----------------------------------------------------------------------- risk meter
/** Compact risk meter: magnitude on the blue sequential ramp + the value as text
    (color never carries it alone). */
export function RiskMeter({ value, max = 1.2 }: { value: number; max?: number }) {
  const frac = Math.max(0, Math.min(1, value / max));
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="relative inline-block h-1.5 w-10 overflow-hidden rounded-full bg-grid align-middle">
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{
            width: `${frac * 100}%`,
            background: `color-mix(in oklab, var(--seq-lo), var(--seq-hi) ${Math.round(frac * 100)}%)`,
          }}
        />
      </span>
      <span className="tnum text-ink-2">{value.toFixed(2)}</span>
    </span>
  );
}
