// Types mirroring the backend's Pydantic schemas (backend/app/models.py) and small fetch helpers.
// Every number shown in the UI arrives through these types from the backend; nothing is computed or invented here.

// Backend URL: runtime config (public/config.js, editable after deploy) first, then the build-time VITE_API_URL.
const runtimeUrl = (window as unknown as { KK_API_URL?: string }).KK_API_URL;
export const API_URL: string = (runtimeUrl || (import.meta.env.VITE_API_URL as string | undefined) || "http://localhost:7860").replace(/\/$/, "");

export type Level = "low" | "moderate" | "high";
export type Hazard = "drought" | "excess_rain" | "heat";
export type Crop = "wheat" | "mustard" | "gram" | "unknown";
export type Bounds = [[number, number], [number, number]];

export interface SourceRef {
  name: string;
  url: string;
  fetched_at: string;
  cached?: boolean;
  scene_date?: string | null;
  note?: string | null;
}

export interface Citation {
  call_id: string;
  source: string;
  field: string;
  value: unknown;
  unit: string;
  fetched_at: string;
}

export interface Driver {
  text: string;
  citations: Citation[];
}

export interface Component {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  points: number | null;
  weight: number;
  contribution: number;
  available: boolean;
  note?: string | null;
}

export interface RiskScore {
  hazard: Hazard;
  score: number | null;
  level: Level | null;
  drivers: Driver[];
  components: Component[];
  available_weight: number;
  multiplier: number;
  status: "ok" | "not_enough_data";
}

export interface Action {
  by_date: string;
  action: string;
  reason: string;
  citations: Citation[];
  english_fallback?: boolean;
}

export interface Place {
  name: string;
  district?: string | null;
  state?: string | null;
  display_name?: string | null;
  source?: SourceRef;
}

export interface Stage {
  key: string;
  label: string;
  days_after_sowing?: number | null;
  sensitive: boolean;
}

export interface Overlay {
  layer: "delta_ndvi" | "ndvi" | "truecolor" | "radar";
  period: "now" | "last_year";
  png_base64: string;
  bounds: Bounds;
  scene_date: string;
  masked_pct: number;
}

export interface ForecastResult {
  dates: string[];
  rain_series: (number | null)[];
  tmax_series: (number | null)[];
  rain_prob_series: (number | null)[];
  rain_next16_mm: number;
  longest_dry_run_days: number;
  water_deficit_mm: number;
  soil_moisture_root: number | null;
  rain_past30_obs_mm: number | null;
  source: SourceRef;
}

export interface BaselineResult {
  provider: "era5" | "nasa_power";
  years_used: number;
  first_year: number;
  last_year: number;
  rain_past30_normal_mm: number;
  rain_next16_normal_mm: number;
  rain_next16_normal_series: number[];
  tmax_next16_normal_c: number[];
  tmax_next16_normal_mean: number;
  source: SourceRef;
}

export interface OpticalResult {
  scene_id: string;
  scene_date: string;
  scene_cloud_pct: number;
  clear_fraction: number;
  ndvi: { median: number; p10: number; p90: number };
  ndmi: { median: number; p10: number; p90: number };
  ndvi_last_year: number | null;
  ndmi_last_year: number | null;
  delta_ndvi: number | null;
  delta_ndmi: number | null;
  last_year_scene_date: string | null;
  land_note?: string | null;
  source: SourceRef;
}

export interface RadarResult {
  collection: string;
  calibrated: boolean;
  scene_date: string;
  last_year_scene_date: string | null;
  vh_db: number;
  vv_db: number;
  vh_db_last_year: number | null;
  delta_vh_db: number | null;
  source: SourceRef;
}

export interface Evidence {
  optical?: OpticalResult;
  radar?: RadarResult;
  forecast?: ForecastResult;
  baseline?: BaselineResult;
}

export interface ErrorInfo {
  code: string;
  message: string;
  retryable: boolean;
}

export interface Translation {
  lang: string;
  summary: string;
  actions: Action[];
  summary_english_fallback?: boolean;
}

export interface Language {
  code: string;
  name: string;
}

export interface Meta {
  languages: Language[];
  crops: Crop[];
  demo_controls: boolean;
  fail_options: string[];
  version: string;
}

export interface SearchHit {
  name: string;
  district?: string | null;
  state?: string | null;
  lat: number;
  lon: number;
}

/** GET a JSON endpoint on the backend; throws ErrorInfo-shaped errors. */
export async function getJson<T>(path: string, timeoutMs = 10000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_URL}${path}`, { signal: ctrl.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw { code: body.code ?? `HTTP_${res.status}`, message: body.message ?? res.statusText, retryable: !!body.retryable };
    return body as T;
  } finally {
    clearTimeout(timer);
  }
}

/** POST JSON to the backend; throws ErrorInfo-shaped errors. */
export async function postJson<T>(path: string, payload: unknown, timeoutMs = 30000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw { code: body.code ?? `HTTP_${res.status}`, message: body.message ?? res.statusText, retryable: !!body.retryable };
    return body as T;
  } finally {
    clearTimeout(timer);
  }
}

/** Village search (≥ 3 characters), proxied through the backend to Nominatim. */
export function searchPlaces(q: string): Promise<{ results: SearchHit[] }> {
  return getJson(`/api/search?q=${encodeURIComponent(q)}`);
}
