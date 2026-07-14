// Small shared UI primitives: selects, segmented controls, badges, cards, toggles.

import { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-bdr bg-surface shadow-[var(--shadow)] ${className}`}>
      {children}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-ink-2">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function Select({
  value,
  onChange,
  options,
  title,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  title?: string;
}) {
  return (
    <select
      title={title}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 rounded-lg border border-bdr bg-surface px-2.5 text-sm text-ink outline-none transition-colors hover:border-baseline focus:border-accent"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Segmented({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string; title?: string }[];
}) {
  return (
    <div className="flex h-8 items-stretch rounded-lg border border-bdr bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 text-[13px] font-medium transition-colors ${
            value === o.value
              ? "bg-surface text-ink shadow-[var(--shadow)]"
              : "text-ink-3 hover:text-ink-2"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2 text-[13px] font-medium text-ink-2"
    >
      <span
        className={`relative inline-flex h-[18px] w-8 items-center rounded-full transition-colors ${
          checked ? "bg-accent" : "bg-baseline"
        }`}
      >
        <span
          className={`absolute h-3.5 w-3.5 rounded-full bg-white transition-transform ${
            checked ? "translate-x-[15px]" : "translate-x-[3px]"
          }`}
        />
      </span>
      {label}
    </button>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder,
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <svg
        viewBox="0 0 20 20"
        className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <circle cx="9" cy="9" r="6" />
        <path d="m14 14 4 4" strokeLinecap="round" />
      </svg>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-8 w-full rounded-lg border border-bdr bg-surface pl-8 pr-2.5 text-sm text-ink outline-none transition-colors placeholder:text-ink-3 hover:border-baseline focus:border-accent"
      />
    </div>
  );
}

/** Analyst / status chip. tone: up | down | neutral | accent | warn */
export function Chip({
  tone = "neutral",
  children,
  title,
}: {
  tone?: "up" | "down" | "neutral" | "accent" | "warn";
  children: ReactNode;
  title?: string;
}) {
  const tones: Record<string, string> = {
    up: "text-up bg-up/10",
    down: "text-down bg-down/10",
    neutral: "text-ink-2 bg-surface-2",
    accent: "text-accent bg-accent-soft",
    warn: "text-ink-2 bg-warn/15",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-ink-3">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-baseline border-t-accent" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-down/30 bg-down/5 px-4 py-3 text-sm text-ink-2">
      <span className="font-semibold text-down">Error: </span>
      {message}
    </div>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-bdr bg-surface-2 px-4 py-6 text-center text-sm text-ink-2">
      {children}
    </div>
  );
}
