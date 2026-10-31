// Live analysis runs over Server-Sent Events (BUILD_SPEC §5). `useAnalysis` opens an EventSource on
// /api/analyze and folds each event into one state object that every panel reads from.
//
// Rules from BUILD_SPEC §10: clicking again mid-run closes the old stream and starts fresh; if the connection
// drops before the run finishes we reconnect once, then show "Connection lost — Retry".
import { useCallback, useEffect, useReducer, useRef } from "react";
import {
  API_URL,
  type Action,
  type Bounds,
  type Crop,
  type ErrorInfo,
  type Evidence,
  type Level,
  type Overlay,
  type Place,
  type RiskScore,
  type SourceRef,
  type Stage,
  type Translation,
} from "./api";

export type RunStatus = "idle" | "running" | "done" | "rejected" | "error";

export interface RunParams {
  lat: number;
  lon: number;
  crop: Crop;
  sowing_date?: string;
  lang: string;
  fail?: string;
}

export interface ToolRow {
  kind: "tool";
  id: string;
  call_id: string;
  tool: string;
  label: string;
  status: "running" | "done" | "failed";
  duration_ms?: number;
  summary?: string;
  source?: SourceRef;
  error?: string;
  will_retry?: boolean;
}
export interface PlanRow {
  kind: "plan";
  id: string;
  source: "llm" | "rules";
  cached?: boolean;
  steps: { id: string; tool: string; reason: string; added_by: string }[];
}
export interface FallbackRow {
  kind: "fallback";
  id: string;
  label: string;
  reason: string;
  chosen_by: string;
}
export interface MessageRow {
  kind: "validation" | "note" | "partial" | "error" | "done";
  id: string;
  level: "info" | "warning" | "error" | "ok";
  text: string;
}
export type TraceRow = ToolRow | PlanRow | FallbackRow | MessageRow;

export interface RiskInfo {
  scores: RiskScore[];
  overall_level: Level | null;
  confidence: "high" | "medium" | "low";
  confidence_reasons: string[];
  headline: { hazard: string; score: number; level: Level } | null;
}

export interface RunState {
  status: RunStatus;
  params: RunParams | null;
  runId: string | null;
  bounds: Bounds | null;
  place: Place | null;
  stage: Stage | null;
  rows: TraceRow[];
  evidence: Evidence;
  sources: SourceRef[];
  overlays: Overlay[];
  risk: RiskInfo | null;
  plan: { summary: string; actions: Action[]; source: "llm" | "rules" } | null;
  validation: { numbers_checked: number; numbers_rejected: number; message: string } | null;
  translation: Translation | null;
  missing: string[];
  notes: string[];
  analysisId: string | null;
  durationMs: number | null;
  error: ErrorInfo | null;
  startedAt: number | null;
}

export const initialRun: RunState = {
  status: "idle", params: null, runId: null, bounds: null, place: null, stage: null, rows: [], evidence: {},
  sources: [], overlays: [], risk: null, plan: null, validation: null, translation: null, missing: [], notes: [],
  analysisId: null, durationMs: null, error: null, startedAt: null,
};

type Msg =
  | { type: "start"; params: RunParams; bounds: Bounds }
  | { type: "event"; name: string; data: any }
  | { type: "connection_lost" }
  | { type: "translation"; translation: Translation | null }
  | { type: "reset" };

let rowSeq = 0;
const rid = () => `r${++rowSeq}`;

/** Fold one server event into the run state. */
function reducer(state: RunState, msg: Msg): RunState {
  switch (msg.type) {
    case "reset":
      return initialRun;
    case "start":
      return { ...initialRun, status: "running", params: msg.params, bounds: msg.bounds, startedAt: Date.now() };
    case "connection_lost":
      return {
        ...state, status: "error",
        error: { code: "CONNECTION_LOST", message: "Connection lost — Retry", retryable: true },
      };
    case "translation":
      return { ...state, translation: msg.translation };
    case "event":
      return applyEvent(state, msg.name, msg.data);
  }
}

function applyEvent(s: RunState, name: string, d: any): RunState {
  switch (name) {
    case "run_started":
      return { ...s, runId: d.run_id, bounds: d.bounds, stage: d.stage, place: d.place ?? s.place };
    case "plan":
      return { ...s, rows: [...s.rows, { kind: "plan", id: rid(), source: d.source, cached: d.cached, steps: d.steps }] };
    case "tool_started":
      return {
        ...s,
        rows: [...s.rows, { kind: "tool", id: rid(), call_id: d.call_id, tool: d.tool, label: d.label, status: "running" }],
      };
    case "tool_succeeded": {
      const rows = s.rows.map((r) =>
        r.kind === "tool" && r.call_id === d.call_id
          ? { ...r, status: "done" as const, duration_ms: d.duration_ms, summary: d.summary, source: d.source }
          : r);
      const evidence = d.kind && d.result ? { ...s.evidence, [d.kind]: d.result } : s.evidence;
      const sources = d.source ? [...s.sources, d.source] : s.sources;
      return { ...s, rows, evidence, sources, place: d.place ?? s.place };
    }
    case "tool_failed": {
      const rows = s.rows.map((r) =>
        r.kind === "tool" && r.call_id === d.call_id
          ? { ...r, status: "failed" as const, duration_ms: d.duration_ms, error: d.message, will_retry: d.will_retry }
          : r);
      return { ...s, rows };
    }
    case "fallback":
      return { ...s, rows: [...s.rows, { kind: "fallback", id: rid(), label: d.label, reason: d.reason, chosen_by: d.chosen_by }] };
    case "overlay":
      return { ...s, overlays: [...s.overlays.filter((o) => !(o.layer === d.layer && o.period === d.period)), d] };
    case "risk":
      return { ...s, risk: d };
    case "partial":
      return {
        ...s, missing: d.missing,
        rows: [...s.rows, { kind: "partial", id: rid(), level: "warning", text: d.message }],
      };
    case "note":
      return {
        ...s, notes: d.level === "warning" && !d.message.startsWith("Plan generated") && !d.message.startsWith("Recovery")
          ? [...s.notes, d.message] : s.notes,
        rows: [...s.rows, { kind: "note", id: rid(), level: d.level === "warning" ? "warning" : "info", text: d.message }],
      };
    case "action_plan":
      return { ...s, plan: { summary: d.summary, actions: d.actions, source: d.source } };
    case "validation":
      return {
        ...s, validation: d,
        rows: [...s.rows, {
          kind: "validation", id: rid(), level: d.numbers_rejected > 0 && d.regenerated ? "warning" : "ok", text: d.message,
        }],
      };
    case "translation":
      return { ...s, translation: d };
    case "run_completed":
      return {
        ...s, status: "done", analysisId: d.analysis_id, durationMs: d.duration_ms,
        rows: [...s.rows, { kind: "done", id: rid(), level: "ok", text: `Finished in ${(d.duration_ms / 1000).toFixed(1)} s` }],
      };
    case "error":
      return {
        ...s, status: d.code === "REJECTED_LOCATION" ? "rejected" : "error",
        error: { code: d.code, message: d.message, retryable: d.retryable },
        rows: [...s.rows, { kind: "error", id: rid(), level: "error", text: d.message }],
      };
    default:
      return s;
  }
}

const EVENTS = [
  "run_started", "plan", "tool_started", "tool_succeeded", "tool_failed", "fallback", "overlay", "risk",
  "action_plan", "validation", "translation", "partial", "run_completed", "error", "note",
];

/** Half-side of the 500 m box in degrees, so the box can be drawn before the server answers. */
export function boxAround(lat: number, lon: number): Bounds {
  const dlat = 250 / 111320;
  const dlon = 250 / (111320 * Math.cos((lat * Math.PI) / 180));
  return [[lat - dlat, lon - dlon], [lat + dlat, lon + dlon]];
}

/** React hook that runs analyses and exposes their live state. */
export function useAnalysis() {
  const [state, dispatch] = useReducer(reducer, initialRun);
  const esRef = useRef<EventSource | null>(null);
  const retriedRef = useRef(false);

  const close = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  const open = useCallback((params: RunParams) => {
    close();
    const qs = new URLSearchParams({ lat: params.lat.toFixed(6), lon: params.lon.toFixed(6), crop: params.crop, lang: params.lang });
    if (params.sowing_date) qs.set("sowing_date", params.sowing_date);
    if (params.fail) qs.set("fail", params.fail);
    const es = new EventSource(`${API_URL}/api/analyze?${qs.toString()}`);
    esRef.current = es;
    let terminal = false;
    for (const name of EVENTS) {
      es.addEventListener(name, (ev) => {
        if (esRef.current !== es) return;
        const data = JSON.parse((ev as MessageEvent).data);
        dispatch({ type: "event", name, data });
        if (name === "run_completed" || name === "error") {
          terminal = true;
          es.close();
        }
      });
    }
    es.onerror = () => {
      if (esRef.current !== es || terminal) return;
      es.close();
      if (!retriedRef.current) {
        retriedRef.current = true;
        dispatch({ type: "start", params, bounds: boxAround(params.lat, params.lon) });
        open(params);
      } else {
        dispatch({ type: "connection_lost" });
      }
    };
  }, [close]);

  const start = useCallback((params: RunParams) => {
    retriedRef.current = false;
    dispatch({ type: "start", params, bounds: boxAround(params.lat, params.lon) });
    open(params);
  }, [open]);

  const setTranslation = useCallback((translation: Translation | null) => dispatch({ type: "translation", translation }), []);
  const reset = useCallback(() => { close(); dispatch({ type: "reset" }); }, [close]);

  useEffect(() => close, [close]);
  return { state, start, reset, setTranslation };
}


/** Rebuild a finished run's state from a saved analysis (share page): replay its trace through the same reducer,
 * then add the map overlays stored with the satellite evidence. */
export function replayRun(payload: any): RunState {
  let state: RunState = { ...initialRun, status: "running", params: { lat: payload.lat, lon: payload.lon, crop: payload.crop, lang: payload.lang ?? "en-IN" } };
  for (const ev of payload.trace ?? []) state = applyEvent(state, ev.event, ev.data);
  const overlays: Overlay[] = [];
  for (const kind of ["optical", "radar"]) overlays.push(...(payload.evidence?.[kind]?.result?.overlays ?? []));
  return {
    ...state, status: "done", overlays, bounds: payload.bounds, place: payload.place ?? state.place,
    analysisId: payload.id, translation: payload.translation ?? state.translation,
  };
}
