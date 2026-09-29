import { useEffect, useState } from "react";

export type RadarLabel = "strong_target" | "target" | "fade" | "strong_fade" | "";

export interface RadarRow {
  PLAYER_ID: number;
  PLAYER_NAME: string;
  adp?: number | null;
  radar_label?: RadarLabel | null;
  radar_round_gap?: number | null;
  radar_reasons?: string | null;
}

export interface DraftTarget {
  takeBy: number | null;
  note: string;
}

export type DraftTargets = Record<string, DraftTarget>;

export const TARGETS_KEY = "fantasy-nba-draft-targets-v1";
let sessionTargets: DraftTargets | undefined;
let unavailable = false;

function loadTargets(): DraftTargets {
  if (sessionTargets) return sessionTargets;
  try {
    const value = JSON.parse(localStorage.getItem(TARGETS_KEY) || "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([key, target]) => {
      const t = target as DraftTarget | null;
      return /^\d+$/.test(key) && t && typeof t.note === "string" &&
        (t.takeBy === null || (Number.isInteger(t.takeBy) && t.takeBy > 0));
    })) as DraftTargets;
  } catch (error) {
    unavailable = !(error instanceof SyntaxError);
    return {};
  }
}

export function useDraftTargets() {
  const [targets, setTargets] = useState<DraftTargets>(loadTargets);
  const [storageUnavailable, setStorageUnavailable] = useState(unavailable);
  useEffect(() => {
    const refresh = () => { setTargets(loadTargets()); setStorageUnavailable(unavailable); };
    const external = (event: StorageEvent) => { if (event.key === TARGETS_KEY) { sessionTargets = undefined; refresh(); } };
    window.addEventListener("watchlist-change", refresh);
    window.addEventListener("storage", external);
    return () => { window.removeEventListener("watchlist-change", refresh); window.removeEventListener("storage", external); };
  }, []);
  const save = (next: DraftTargets) => {
    sessionTargets = next;
    try { localStorage.setItem(TARGETS_KEY, JSON.stringify(next)); }
    catch { unavailable = true; setStorageUnavailable(true); }
    setTargets(next);
    window.dispatchEvent(new Event("watchlist-change"));
  };

  const edit = (row: RadarRow) => {
    const key = String(row.PLAYER_ID);
    const existing = targets[key];
    const suggested = existing?.takeBy ?? (row.adp != null ? Math.max(1, Math.round(row.adp - 12)) : null);
    const raw = window.prompt(
      `Priority target: ${row.PLAYER_NAME}\n\nTake by overall pick (optional). Type REMOVE to clear this target.`,
      suggested == null ? "" : String(suggested),
    );
    if (raw == null) return;
    if (raw.trim().toUpperCase() === "REMOVE") {
      const next = { ...targets };
      delete next[key];
      save(next);
      return;
    }
    const parsed = raw.trim() ? Number(raw) : null;
    if (parsed != null && (!Number.isInteger(parsed) || parsed < 1 || parsed > 10000)) {
      window.alert("Take-by pick must be a whole number from 1 to 10,000.");
      return;
    }
    const noteInput = window.prompt("Private draft note (optional)", existing?.note || "");
    const note = noteInput == null ? (existing?.note || "") : noteInput;
    if (note.length > 10000) { window.alert("Keep notes under 10,000 characters."); return; }
    const next = { ...targets, [key]: { takeBy: parsed == null ? null : Math.round(parsed), note } };
    save(next);
  };

  return { targets, save, edit, storageUnavailable };
}

export function radarName(label?: string | null): string {
  return ({
    strong_target: "Strong target",
    target: "Target",
    fade: "Fade",
    strong_fade: "Strong fade",
  } as Record<string, string>)[label || ""] || "";
}

export function radarTone(label?: string | null): "up" | "down" | "warn" | "neutral" {
  if (label === "strong_target" || label === "target") return "up";
  if (label === "strong_fade") return "down";
  if (label === "fade") return "warn";
  return "neutral";
}

export function targetTitle(row: RadarRow, target?: DraftTarget): string {
  const parts = [row.radar_reasons || "Personal priority target"];
  if (target?.takeBy != null) parts.push(`Take by overall pick ${target.takeBy}`);
  if (target?.note) parts.push(target.note);
  return parts.filter(Boolean).join("\n");
}
