// TracePanel (F7): one row per agent step as it happens: the plan, each tool call (spinner → tick or red x)
// with duration and source chip, fallbacks in amber ("Cloud 85% → switching to radar"), validation and notes.
// Tool rows expand to show the tool's summary output. The list auto-scrolls while the run is live.
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, Info, ListChecks, Loader2, ShieldCheck, XCircle } from "lucide-react";
import type { RunState, TraceRow } from "@/lib/sse";
import { SourceBadge } from "./SourceBadge";

const TOOL_NAMES: Record<string, string> = {
  geocode: "Place name", get_optical_index: "Sentinel-2 crop health", get_radar_index: "Sentinel-1 radar",
  get_forecast: "16-day forecast", get_baseline: "20-year normal", score_risk: "Risk engine",
};

function Row({ row }: { row: TraceRow }) {
  const [open, setOpen] = useState(false);
  if (row.kind === "plan") {
    return (
      <li className="rounded-md border border-slate-200 bg-slate-50 p-2">
        <div className="flex items-center gap-2 font-medium text-slate-900">
          <ListChecks className="h-4 w-4 text-brand-700" aria-hidden /> Plan
          {row.source === "rules" && <span className="rounded bg-slate-200 px-1.5 text-[11px] text-slate-700">Generated from rules</span>}
          {row.cached && <span className="rounded bg-slate-200 px-1.5 text-[11px] text-slate-700">cached</span>}
        </div>
        <ol className="mt-1 list-decimal space-y-0.5 pl-6 text-xs text-slate-700">
          {row.steps.map((s) => (
            <li key={s.id}><span className="font-medium">{TOOL_NAMES[s.tool] ?? s.tool}</span> — {s.reason}</li>
          ))}
        </ol>
      </li>
    );
  }
  if (row.kind === "fallback") {
    return (
      <li className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-amber-900">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-label="Fallback" />
        <div>
          <div className="font-medium">{row.label}</div>
          {row.reason && row.reason.toLowerCase() !== row.label.toLowerCase() && (
            <div className="text-xs">{row.chosen_by === "llm" ? "Agent's reason: " : ""}{row.reason}</div>
          )}
        </div>
      </li>
    );
  }
  if (row.kind === "tool") {
    const icon =
      row.status === "running" ? <Loader2 className="h-4 w-4 animate-spin text-slate-500" aria-label="Running" />
        : row.status === "done" ? <CheckCircle2 className="h-4 w-4 text-low" aria-label="Done" />
          : row.will_retry ? <AlertTriangle className="h-4 w-4 text-moderate-text" aria-label="Failed, will recover" />
            : <XCircle className="h-4 w-4 text-high" aria-label="Failed" />;
    return (
      <li className="rounded-md border border-slate-200 bg-white p-2">
        <button type="button" className="flex w-full items-start gap-2 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <span className="mt-0.5">{icon}</span>
          <span className="flex-1">
            <span className="block text-sm text-slate-900">{row.label}</span>
            {row.status === "failed" && <span className="block text-xs text-high-text">{row.error}</span>}
          </span>
          {row.duration_ms !== undefined && <span className="shrink-0 font-mono text-[11px] text-slate-500">{row.duration_ms} ms</span>}
          {row.summary && <ChevronDown className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />}
        </button>
        {(row.source || (open && row.summary)) && (
          <div className="mt-1 space-y-1 pl-6">
            {open && row.summary && <div className="text-xs text-slate-700">{row.summary}</div>}
            {row.source && <SourceBadge source={row.source} />}
          </div>
        )}
      </li>
    );
  }
  const styles = {
    ok: "border-green-200 bg-green-50 text-green-900",
    info: "border-slate-200 bg-slate-50 text-slate-700",
    warning: "border-amber-300 bg-amber-50 text-amber-900",
    error: "border-red-300 bg-red-50 text-red-900",
  }[row.level];
  const icon = row.kind === "validation" ? <ShieldCheck className="h-4 w-4" aria-hidden />
    : row.level === "error" ? <XCircle className="h-4 w-4" aria-hidden />
      : row.level === "warning" ? <AlertTriangle className="h-4 w-4" aria-hidden />
        : row.level === "ok" ? <CheckCircle2 className="h-4 w-4" aria-hidden /> : <Info className="h-4 w-4" aria-hidden />;
  return (
    <li className={`flex items-start gap-2 rounded-md border p-2 text-sm ${styles}`}>
      <span className="mt-0.5">{icon}</span>
      <span>{row.kind === "validation" ? `Citation check: ${row.text}` : row.text}</span>
    </li>
  );
}

export function TracePanel({ run }: { run: RunState }) {
  const end = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    if (run.status === "running") end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [run.rows.length, run.status]);
  if (!run.rows.length) {
    return <p className="p-2 text-sm text-slate-600">The agent's steps will appear here as they happen.</p>;
  }
  return (
    <ol className="space-y-1.5" aria-live="polite">
      {run.rows.map((r) => <Row key={r.id} row={r} />)}
      {run.status === "running" && (
        <li ref={end} className="flex items-center gap-2 p-2 text-xs text-slate-500">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> Working…
        </li>
      )}
    </ol>
  );
}
