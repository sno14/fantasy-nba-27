import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { Meta, useApi } from "./lib/api";
import { Chip } from "./components/ui";
import DraftBoard from "./views/DraftBoard";
import DraftRoom from "./views/DraftRoom";
import Ros from "./views/Ros";
import Weekly from "./views/Weekly";
import Player from "./views/Player";
import Compare from "./views/Compare";
import Analyst from "./views/Analyst";
import DataBrowser from "./views/DataBrowser";

// --------------------------------------------------------------------------- theme
function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light"),
  );
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next === "dark" ? "dark" : "";
      if (next === "dark") document.documentElement.dataset.theme = "dark";
      else delete document.documentElement.dataset.theme;
      localStorage.setItem("theme", next);
      return next;
    });
  }, []);
  return { theme, toggle };
}

// ------------------------------------------------------------------- compare state
interface CompareCtx {
  ids: number[];
  names: Record<number, string>;
  toggle: (id: number, name: string) => void;
  clear: () => void;
}
const CompareContext = createContext<CompareCtx>({ ids: [], names: {}, toggle: () => {}, clear: () => {} });
export const useCompare = () => useContext(CompareContext);
export const MetaContext = createContext<Meta | null>(null);
export const useMeta = () => useContext(MetaContext);

function CompareProvider({ children }: { children: React.ReactNode }) {
  const [sel, setSel] = useState<{ id: number; name: string }[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem("compare") ?? "[]");
    } catch {
      return [];
    }
  });
  useEffect(() => sessionStorage.setItem("compare", JSON.stringify(sel)), [sel]);
  const value = useMemo<CompareCtx>(
    () => ({
      ids: sel.map((s) => s.id),
      names: Object.fromEntries(sel.map((s) => [s.id, s.name])),
      toggle: (id, name) =>
        setSel((cur) =>
          cur.some((s) => s.id === id)
            ? cur.filter((s) => s.id !== id)
            : cur.length >= 4
              ? cur // max four side-by-side
              : [...cur, { id, name }],
        ),
      clear: () => setSel([]),
    }),
    [sel],
  );
  return <CompareContext.Provider value={value}>{children}</CompareContext.Provider>;
}

function CompareTray() {
  const { ids, names, clear } = useCompare();
  const nav = useNavigate();
  const loc = useLocation();
  if (ids.length === 0 || loc.pathname === "/compare") return null;
  return (
    <div className="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-2 rounded-full border border-bdr bg-surface px-3 py-1.5 shadow-[var(--shadow)]">
      <span className="text-xs font-medium text-ink-2">Compare:</span>
      {ids.map((id) => (
        <Chip key={id} tone="accent">{names[id]}</Chip>
      ))}
      <button
        onClick={() => nav("/compare")}
        disabled={ids.length < 2}
        className="rounded-full bg-accent px-3 py-1 text-xs font-semibold text-accent-ink transition-opacity disabled:opacity-40"
      >
        Compare {ids.length >= 2 ? `(${ids.length})` : ""}
      </button>
      <button onClick={clear} className="px-1 text-xs text-ink-3 hover:text-ink-2" title="Clear">
        ✕
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------- nav
const NAV = [
  { to: "/", label: "Draft Board", icon: "M4 6h16M4 10h16M4 14h10M4 18h7" },
  { to: "/room", label: "Draft Room", icon: "M12 3v4M5 8h14l-1.5 11a2 2 0 01-2 2h-7a2 2 0 01-2-2L5 8zM9 12v5M15 12v5" },
  { to: "/ros", label: "ROS", icon: "M4 17l5-5 4 3 7-8M16 7h4v4" },
  { to: "/weekly", label: "Weekly", icon: "M4 5h16v15H4zM4 9h16M8 3v4M16 3v4" },
  { to: "/players", label: "Players", icon: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 20a8 8 0 0116 0" },
  { to: "/compare", label: "Compare", icon: "M8 4v16M16 4v16M4 9h8M12 15h8" },
  { to: "/analyst", label: "Analyst", icon: "M9 12l2 2 4-5M12 21a9 9 0 110-18 9 9 0 010 18z" },
  { to: "/data", label: "Data", icon: "M4 6c0-1.5 3.6-3 8-3s8 1.5 8 3-3.6 3-8 3-8-1.5-8-3zm0 0v12c0 1.5 3.6 3 8 3s8-1.5 8-3V6M4 12c0 1.5 3.6 3 8 3s8-1.5 8-3" },
];

function Shell() {
  const { theme, toggle } = useTheme();
  const meta = useApi<Meta>("/api/meta").data;

  return (
    <MetaContext.Provider value={meta ?? null}>
      <div className="flex h-full">
        {/* ------------------------------------------------------------- sidebar */}
        <aside className="flex w-[190px] shrink-0 flex-col border-r border-bdr bg-surface">
          <Link to="/" className="flex items-center gap-2.5 px-4 pb-4 pt-5">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-[15px] font-black text-accent-ink">
              27
            </span>
            <span className="leading-tight">
              <span className="block text-[13px] font-bold tracking-tight">Fantasy NBA</span>
              <span className="block text-[11px] text-ink-3">2026-27 projections</span>
            </span>
          </Link>
          <nav className="flex flex-col gap-0.5 px-2.5">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors ${
                    isActive ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface-2 hover:text-ink"
                  }`
                }
              >
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d={n.icon} />
                </svg>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="mt-auto space-y-2 px-4 pb-4 text-[11px] text-ink-3">
            {meta && (
              <div className="space-y-1.5">
                {meta.fixture && (
                  <Chip tone="warn" title="data/raw carries the synthetic dev-fixture cache (scripts/dev_fixtures.py) — every number is generated">
                    ⚠ synthetic data
                  </Chip>
                )}
                <div>
                  {meta.league.teams}-team {meta.league.platform?.toUpperCase()} ·{" "}
                  {meta.scoring.name}
                </div>
                {meta.data_seasons && (
                  <div>
                    data {meta.data_seasons[0]} – {meta.data_seasons[1]}
                  </div>
                )}
              </div>
            )}
            <button
              onClick={toggle}
              className="flex w-full items-center justify-between rounded-lg border border-bdr px-2.5 py-1.5 text-xs font-medium text-ink-2 transition-colors hover:bg-surface-2"
            >
              <span>{theme === "dark" ? "Dark" : "Light"} theme</span>
              <span aria-hidden>{theme === "dark" ? "🌙" : "☀️"}</span>
            </button>
          </div>
        </aside>

        {/* ------------------------------------------------------------- content */}
        <main className="scroll-thin min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1400px] px-6 py-5">
            <Routes>
              <Route path="/" element={<DraftBoard />} />
              <Route path="/room" element={<DraftRoom />} />
              <Route path="/ros" element={<Ros />} />
              <Route path="/weekly" element={<Weekly />} />
              <Route path="/players" element={<Player />} />
              <Route path="/players/:id" element={<Player />} />
              <Route path="/compare" element={<Compare />} />
              <Route path="/analyst" element={<Analyst />} />
              <Route path="/data" element={<DataBrowser />} />
            </Routes>
          </div>
        </main>
        <CompareTray />
      </div>
    </MetaContext.Provider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <CompareProvider>
        <Shell />
      </CompareProvider>
    </BrowserRouter>
  );
}
