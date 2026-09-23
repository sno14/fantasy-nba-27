import { useState } from "react";

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

function loadTargets(): DraftTargets {
  try {
    const value = JSON.parse(localStorage.getItem(TARGETS_KEY) || "{}");
    return value && typeof value === "object" ? value as DraftTargets : {};
  } catch {
    return {};
  }
}

export function useDraftTargets() {
  const [targets, setTargets] = useState<DraftTargets>(loadTargets);

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
      localStorage.setItem(TARGETS_KEY, JSON.stringify(next));
      setTargets(next);
      return;
    }
    const parsed = raw.trim() ? Number(raw) : null;
    if (parsed != null && (!Number.isFinite(parsed) || parsed < 1)) {
      window.alert("Take-by pick must be a positive overall pick number.");
      return;
    }
    const noteInput = window.prompt("Private draft note (optional)", existing?.note || "");
    const note = noteInput == null ? (existing?.note || "") : noteInput;
    const next = { ...targets, [key]: { takeBy: parsed == null ? null : Math.round(parsed), note } };
    localStorage.setItem(TARGETS_KEY, JSON.stringify(next));
    setTargets(next);
  };

  return { targets, edit };
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
