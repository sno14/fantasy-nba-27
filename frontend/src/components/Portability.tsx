import { useRef, useState } from "react";
import { downloadBackup, MAX_FILE_BYTES, validateBackup } from "../../../static/workspace.mjs";
import { DraftTargets, useDraftTargets } from "../lib/draftRadar";

export function CopyLink({ url = location.href }: { url?: string }) {
  const [status, setStatus] = useState("");
  const [fallback, setFallback] = useState(false);
  return <span className="inline-flex max-w-full flex-wrap items-center gap-2">
    <button className="rounded-lg border border-bdr px-3 py-2 text-xs font-semibold" onClick={async () => {
      try { await navigator.clipboard.writeText(url); setStatus("Link copied"); setFallback(false); }
      catch { setFallback(true); setStatus("Select and copy the link below"); }
    }}>Copy link</button><span role="status" className="text-xs text-ink-3">{status}</span>
    {fallback && <input aria-label="Link to copy" readOnly value={url} onFocus={event => event.target.select()} className="w-full min-w-0 rounded border border-bdr p-2 text-xs" />}
  </span>;
}

export function WatchlistBackup({ season, knownIds }: { season: string; knownIds: number[] }) {
  const { targets, save, storageUnavailable } = useDraftTargets();
  const [preview, setPreview] = useState<DraftTargets | null>(null);
  const [mode, setMode] = useState("merge");
  const [message, setMessage] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const unknown = preview ? Object.keys(preview).filter(id => !knownIds.includes(Number(id))) : [];
  return <div className="flex flex-wrap items-center gap-2 text-xs">
    <button className="rounded-lg border border-bdr px-3 py-2" onClick={() => {
      try { downloadBackup(targets, season); setMessage("Backup downloaded, including your private notes."); }
      catch (error) { setMessage((error as Error).message); }
    }}>Export watchlist</button>
    <label className="cursor-pointer rounded-lg border border-bdr px-3 py-2">Import watchlist
      <input type="file" accept=".json,application/json" aria-label="Import watchlist" className="sr-only" onChange={async event => {
        const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
        setPreview(null);
        try {
          if (file.size > MAX_FILE_BYTES) throw new Error("Choose a backup smaller than 1 MB.");
          setPreview(validateBackup(JSON.parse(await file.text()), season)); setMode("merge"); setMessage(""); dialog.current?.showModal();
        } catch (error) { setMessage((error as Error).message); }
      }} />
    </label>
    <span role="status" className="text-ink-3">{message}{storageUnavailable && " Browser storage is unavailable; changes last for this session only. Export a backup to keep them."}</span>
    <dialog ref={dialog} className="board-signal-dialog" aria-labelledby="import-title">
      <h2 id="import-title" className="mb-3 text-base font-bold">Import watchlist</h2>
      <p>{Object.keys(preview || {}).length} targets for {season}. Import includes private notes.</p>
      <p className="my-3 break-words">{unknown.length ? `Unknown player IDs (kept for future boards): ${unknown.join(", ")}` : "All player IDs are on the current board."}</p>
      <div className="my-4 space-y-2">
        <label className="block"><input type="radio" name="import-mode" value="merge" checked={mode === "merge"} onChange={() => setMode("merge")} /> Merge — imported entries overwrite matching targets.</label>
        <label className="block"><input type="radio" name="import-mode" value="replace" checked={mode === "replace"} onChange={() => setMode("replace")} /> Replace — remove existing targets before importing.</label>
      </div>
      <div className="flex gap-3"><button className="rounded border border-bdr px-3 py-2" onClick={() => dialog.current?.close()}>Cancel</button>
        <button className="rounded bg-accent px-3 py-2 text-accent-ink" onClick={() => {
          if (!preview) return; save(mode === "merge" ? { ...targets, ...preview } : preview); dialog.current?.close(); setMessage("Watchlist imported.");
        }}>Confirm import</button></div>
    </dialog>
  </div>;
}
