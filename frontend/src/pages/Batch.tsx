// Batch page (route "/batch", F13): an FPO officer or lender adds up to 20 farms by searching a village or clicking
// the map to drop a pin, and sees them as red/amber/green risk pins plus a table sorted by risk, exportable as CSV.
// Each farm gets a quick live check (satellite, forecast, baseline, risk engine; no AI plan) streamed back as it
// finishes.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip, ZoomControl, useMap, useMapEvents } from "react-leaflet";
import { ArrowLeft, Download, Loader2, MapPin, Play, Trash2, X } from "lucide-react";
import type { Crop, Level } from "@/lib/api";
import { postStream } from "@/lib/stream";
import { HAZARD_LABEL, LEVEL_BG, LEVEL_COLOR, LEVEL_TEXT, LEVEL_WORD } from "@/lib/colors";
import { SearchBox } from "@/components/SearchBox";

interface Item {
  index: number;
  label?: string | null;
  lat: number;
  lon: number;
  status: "ok" | "rejected" | "error";
  message?: string;
  place?: { name: string; district?: string; state?: string };
  scores?: { hazard: keyof typeof HAZARD_LABEL; score: number | null; level: Level | null; top_driver: string | null }[];
  overall_level?: Level | null;
  confidence?: string;
  satellite?: string | null;
  missing?: string[];
  sources?: string[];
  fetched_at?: string;
}

/** A farm on the list: from a village search or a pin dropped on the map. */
interface Farm {
  id: number;
  lat: number;
  lon: number;
  label: string;
  where: string;
}

const MAX_FARMS = 20;
const ORDER: Record<string, number> = { high: 3, moderate: 2, low: 1 };

/** Click on the map drops a pin, except the click that only closes an open popup. */
function DropPin({ onDrop }: { onDrop: (lat: number, lon: number) => void }) {
  const lastClose = useRef(0);
  useMapEvents({
    popupclose: () => { lastClose.current = Date.now(); },
    click: (e) => { if (Date.now() - lastClose.current > 300) onDrop(e.latlng.lat, e.latlng.lng); },
  });
  return null;
}

/** Fly to a searched village. */
function FlyTo({ to }: { to: { lat: number; lon: number; n: number } | null }) {
  const map = useMap();
  useEffect(() => {
    if (to) map.flyTo([to.lat, to.lon], 13, { duration: 1 });
  }, [to?.n]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** Fit all farms in view when a check starts. */
function FitBounds({ farms, fitKey }: { farms: Farm[]; fitKey: number }) {
  const map = useMap();
  useEffect(() => {
    if (fitKey && farms.length) map.fitBounds(farms.map((f) => [f.lat, f.lon] as [number, number]), { padding: [40, 40], maxZoom: 12 });
  }, [fitKey]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

const maxScore = (i: Item) => Math.max(-1, ...(i.scores ?? []).map((s) => s.score ?? -1));

export function Batch() {
  const [farms, setFarms] = useState<Farm[]>([]);
  const [results, setResults] = useState<Record<number, Item>>({});
  const [crop, setCrop] = useState<Crop>("wheat");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [flyTo, setFlyTo] = useState<{ lat: number; lon: number; n: number } | null>(null);
  const [fitKey, setFitKey] = useState(0);
  const nextId = useRef(1);

  const addFarm = (lat: number, lon: number, label: string | null, where: string) => {
    if (farms.length >= MAX_FARMS) { setErr(`Up to ${MAX_FARMS} farms at a time. Remove one to add another.`); return; }
    if (farms.some((f) => Math.abs(f.lat - lat) < 1e-5 && Math.abs(f.lon - lon) < 1e-5)) return;
    const id = nextId.current++;
    setErr(null);
    setFarms((fs) => [...fs, { id, lat, lon, label: label ?? `Farm ${id}`, where }]);
  };
  const removeFarm = (id: number) => {
    setFarms((fs) => fs.filter((f) => f.id !== id));
    setResults(({ [id]: _, ...rest }) => rest);
  };
  const renameFarm = (id: number, label: string) => setFarms((fs) => fs.map((f) => (f.id === id ? { ...f, label } : f)));
  const clearAll = () => { setFarms([]); setResults({}); setErr(null); };

  const checked = useMemo(() => farms.filter((f) => results[f.id]).map((f) => ({ farm: f, item: results[f.id] })), [farms, results]);
  const sorted = useMemo(() => [...checked].sort((a, b) =>
    (ORDER[b.item.overall_level ?? ""] ?? 0) - (ORDER[a.item.overall_level ?? ""] ?? 0) || maxScore(b.item) - maxScore(a.item)), [checked]);

  const run = async () => {
    if (!farms.length) { setErr("Add a farm first: search a village or click the map."); return; }
    const snapshot = farms;
    setErr(null); setResults({}); setBusy(true); setTotal(snapshot.length); setFitKey((k) => k + 1);
    try {
      await postStream("/api/batch", {
        crop, points: snapshot.map((f) => ({ lat: f.lat, lon: f.lon, label: f.label.trim() || undefined })),
      }, (name, data) => {
        const farm = name === "batch_item" ? snapshot[data.index] : undefined;
        if (farm) setResults((r) => ({ ...r, [farm.id]: data }));
      });
    } catch (e: any) {
      setErr(e?.message ?? "Batch failed");
    } finally { setBusy(false); }
  };

  const exportCsv = () => {
    const head = ["label", "lat", "lon", "place", "district", "state", "overall_level", "drought", "excess_rain", "heat",
      "confidence", "satellite", "missing", "sources", "fetched_at"];
    const rows = sorted.map(({ farm: f, item: i }) => {
      const s = (h: string) => i.scores?.find((x) => x.hazard === h)?.score ?? "";
      return [f.label, i.lat, i.lon, i.place?.name ?? "", i.place?.district ?? "", i.place?.state ?? "",
        i.overall_level ?? i.status, s("drought"), s("excess_rain"), s("heat"), i.confidence ?? "", i.satellite ?? "",
        (i.missing ?? []).join("; "), (i.sources ?? []).join("; "), i.fetched_at ?? ""];
    });
    const csv = [head, ...rows].map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "khetkavach-batch.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <main className="flex min-h-0 flex-1 flex-col md:flex-row">
      <section className="relative h-[45vh] min-h-[300px] md:h-auto md:w-3/5" aria-label="Batch map">
        <MapContainer center={[22.5, 79]} zoom={5} zoomControl={false} className="kk-crosshair h-full w-full">
          <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            attribution="Imagery &copy; Esri, Maxar, Earthstar Geographics" />
          <ZoomControl position="bottomright" />
          <DropPin onDrop={(lat, lon) => addFarm(lat, lon, null, `${lat.toFixed(4)}, ${lon.toFixed(4)}`)} />
          <FlyTo to={flyTo} />
          <FitBounds farms={farms} fitKey={fitKey} />
          {farms.map((f) => {
            const i = results[f.id];
            const fill = i?.overall_level ? LEVEL_COLOR[i.overall_level] : i ? "#9E9E9E" : "#FFFFFF";
            return (
              <CircleMarker key={f.id} center={[f.lat, f.lon]} radius={9} bubblingMouseEvents={false}
                pathOptions={{ color: i ? "#fff" : "#1B5E20", weight: 2, fillColor: fill, fillOpacity: 1 }}>
                <Tooltip direction="top" offset={[0, -8]}>{f.label}</Tooltip>
                <Popup>
                  <div className="text-sm">
                    <div className="font-semibold">{f.label}{i?.place?.name && i.place.name !== f.label ? ` · ${i.place.name}` : ""}</div>
                    {!i && <div className="my-1 text-slate-600">Not checked yet</div>}
                    {i && i.status !== "ok" && <div className="my-1 text-slate-600">{i.message}</div>}
                    {i?.status === "ok" && (
                      <>
                        <ul className="my-1">
                          {i.scores?.map((s) => <li key={s.hazard}>{HAZARD_LABEL[s.hazard]}: {s.score ?? "n/a"} {s.level ? `(${LEVEL_WORD[s.level]})` : ""}</li>)}
                        </ul>
                        <Link className="text-brand-700 underline" to={`/?lat=${f.lat}&lon=${f.lon}&crop=${crop}`}>Open full analysis</Link>
                      </>
                    )}
                    <button type="button" className="mt-1 block text-xs text-high-text underline" onClick={() => removeFarm(f.id)}>Remove this farm</button>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>
        <SearchBox onPick={(hit) => {
          addFarm(hit.lat, hit.lon, hit.name, [hit.district, hit.state].filter(Boolean).join(", "));
          setFlyTo({ lat: hit.lat, lon: hit.lon, n: Date.now() });
        }} />
      </section>
      <section className="min-h-0 flex-1 space-y-3 overflow-y-auto border-l border-slate-200 bg-slate-50 p-3 md:w-2/5" aria-label="Batch input and results">
        <Link to="/" className="inline-flex min-h-[40px] items-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-800 hover:bg-slate-100">
          <ArrowLeft className="h-4 w-4" aria-hidden /> Back to main map
        </Link>
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <h2 className="text-sm font-semibold">Many farms at once (FPO / lender view)</h2>
          <p className="mt-1 text-xs text-slate-600">Search a village on the map, or click the map to drop a pin. Up to {MAX_FARMS} farms.</p>
          {farms.length === 0 ? (
            <div className="mt-2 flex items-center gap-2 rounded-md border border-dashed border-slate-300 p-3 text-xs text-slate-600">
              <MapPin className="h-4 w-4 shrink-0 text-brand-700" aria-hidden /> No farms yet.
            </div>
          ) : (
            <ol className="mt-2 divide-y divide-slate-100" aria-label="Farms to check">
              {farms.map((f, n) => {
                const level = results[f.id]?.overall_level;
                return (
                  <li key={f.id} className="flex items-center gap-2 py-1.5">
                    <span className="w-5 shrink-0 text-right text-xs font-semibold text-slate-500">{n + 1}</span>
                    <div className="min-w-0 flex-1">
                      <input className="w-full rounded border border-slate-300 px-2 py-1 text-sm" value={f.label}
                        aria-label={`Name of farm ${n + 1}`} onChange={(e) => renameFarm(f.id, e.target.value)} />
                      <div className="truncate text-[11px] text-slate-500">{f.where}</div>
                    </div>
                    {level && (
                      <span className="shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold" style={{ color: LEVEL_TEXT[level], background: LEVEL_BG[level] }}>
                        {LEVEL_WORD[level]}
                      </span>
                    )}
                    <button type="button" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                      aria-label={`Remove ${f.label || `farm ${n + 1}`}`} onClick={() => removeFarm(f.id)} disabled={busy}>
                      <X className="h-4 w-4" />
                    </button>
                  </li>
                );
              })}
            </ol>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select className="min-h-[40px] rounded-md border border-slate-300 px-2 text-sm" value={crop} onChange={(e) => setCrop(e.target.value as Crop)} aria-label="Crop">
              <option value="wheat">Wheat</option><option value="mustard">Mustard</option><option value="gram">Gram (chickpea)</option><option value="unknown">Not sure</option>
            </select>
            <button type="button" onClick={run} disabled={busy || !farms.length} className="flex min-h-[40px] items-center gap-2 rounded-md bg-brand-700 px-4 text-sm font-medium text-white disabled:opacity-60">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {busy ? `Checking ${checked.length}/${total}…` : `Check risk${farms.length ? ` (${farms.length})` : ""}`}
            </button>
            <button type="button" onClick={exportCsv} disabled={!sorted.length} className="flex min-h-[40px] items-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm disabled:opacity-50">
              <Download className="h-4 w-4" /> CSV
            </button>
            {farms.length > 0 && (
              <button type="button" onClick={clearAll} disabled={busy} className="flex min-h-[40px] items-center gap-2 rounded-md px-2 text-sm text-slate-600 hover:text-slate-900 disabled:opacity-50">
                <Trash2 className="h-4 w-4" /> Clear all
              </button>
            )}
          </div>
          {err && <p className="mt-2 text-xs text-high-text" role="alert">{err}</p>}
          <p className="mt-2 text-[11px] text-slate-500">Each farm gets a live check of Sentinel-2 (radar if cloudy), the 16-day forecast and the 20-year normal. No sowing date, so stage-specific multipliers are not applied.</p>
        </div>
        {sorted.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left text-slate-600">
                <tr><th className="p-2">Farm</th><th className="p-2">Risk</th><th className="p-2 text-right">Drought</th><th className="p-2 text-right">Excess rain</th><th className="p-2 text-right">Heat</th></tr>
              </thead>
              <tbody>
                {sorted.map(({ farm: f, item: i }) => {
                  const s = (h: string) => i.scores?.find((x) => x.hazard === h)?.score ?? "—";
                  return (
                    <tr key={f.id} className="border-t border-slate-100">
                      <td className="p-2">
                        <div className="font-medium">{f.label || `${f.lat.toFixed(3)}, ${f.lon.toFixed(3)}`}</div>
                        <div className="text-slate-500">{i.status === "ok" ? [i.place?.name, i.place?.district].filter(Boolean).join(", ") : i.message}</div>
                        {i.missing && i.missing.length > 0 && <div className="text-amber-800">Missing: {i.missing.join(", ")}</div>}
                      </td>
                      <td className="p-2">
                        {i.overall_level ? <span className="rounded px-1.5 py-0.5 font-semibold" style={{ color: LEVEL_TEXT[i.overall_level], background: LEVEL_BG[i.overall_level] }}>{LEVEL_WORD[i.overall_level]}</span> : <span className="text-slate-500">{i.status}</span>}
                      </td>
                      <td className="p-2 text-right font-mono">{s("drought")}</td>
                      <td className="p-2 text-right font-mono">{s("excess_rain")}</td>
                      <td className="p-2 text-right font-mono">{s("heat")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
