// DemoMenu: the "Resilience test" menu opened with Shift+D (only when the backend has DEMO_CONTROLS=true).
// Each option re-runs the current farm with one source switched off, to show recovery live. The trace labels it
// honestly as "Simulated outage: … (demo control)".
import { useEffect } from "react";
import { FlaskConical, X } from "lucide-react";

const LABELS: Record<string, string> = {
  satellite: "Satellite (Sentinel-2/1) down", forecast: "Forecast (Open-Meteo) down", baseline: "Historical baseline down",
  llm: "AI planner/writer (Gemini) down", sarvam: "Translation/voice (Sarvam) down",
};

export function DemoMenu({
  open, setOpen, options, enabled, canRun, onRun,
}: {
  open: boolean;
  setOpen: (v: boolean) => void;
  options: string[];
  enabled: boolean;
  canRun: boolean;
  onRun: (fail: string) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      if (e.shiftKey && (e.key === "D" || e.key === "d")) setOpen(!open);
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);
  if (!open) return null;
  return (
    <div className="fixed bottom-4 right-4 z-[3000] w-72 rounded-lg border border-slate-300 bg-white p-3 shadow-xl" role="dialog" aria-label="Resilience test">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-slate-900"><FlaskConical className="h-4 w-4" aria-hidden /> Resilience test</div>
        <button type="button" className="rounded p-1 hover:bg-slate-100" onClick={() => setOpen(false)} aria-label="Close"><X className="h-4 w-4" /></button>
      </div>
      {!enabled ? (
        <p className="text-xs text-slate-600">Demo controls are switched off on this server.</p>
      ) : !canRun ? (
        <p className="text-xs text-slate-600">Pick a farm first, then simulate an outage for it.</p>
      ) : (
        <ul className="space-y-1">
          {options.map((o) => (
            <li key={o}>
              <button type="button" className="min-h-[40px] w-full rounded-md border border-slate-200 px-2 text-left text-sm hover:bg-amber-50" onClick={() => { onRun(o); setOpen(false); }}>
                {LABELS[o] ?? o}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11px] text-slate-500">Re-runs the same farm live with that source switched off.</p>
    </div>
  );
}
