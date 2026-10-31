// Batch page (route "/batch", F13): an FPO officer or lender pastes 5-20 locations and sees them as red/amber/
// green risk pins plus a table sorted by risk, exportable as CSV. Each point gets a quick live check (satellite,
// forecast, baseline, risk engine; no AI plan) streamed back as it finishes.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { Download, Loader2, Play } from "lucide-react";
import type { Crop, Level } from "@/lib/api";
import { postStream } from "@/lib/stream";
import { HAZARD_LABEL, LEVEL_BG, LEVEL_COLOR, LEVEL_TEXT, LEVEL_WORD } from "@/lib/colors";

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

const ORDER: Record<string, number> = { high: 3, moderate: 2, low: 1 };

/** Parse "lat, lon[, label]" lines. */
function parse(text: string): { points: { lat: number; lon: number; label?: string }[]; error: string | null } {
  const points: { lat: number; lon: number; label?: string }[] = [];
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  for (const [i, line] of lines.entries()) {
    const [a, b, ...rest] = line.split(/[,\t;]/).map((x) => x.trim());
    const lat = Number(a), lon = Number(b);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      return { points, error: `Line ${i + 1} is not "lat, lon[, label]".` };
    }
    points.push({ lat, lon, label: rest.join(" ") || undefined });
  }
  if (points.length < 1 || points.length > 20) return { points, error: "Paste between 1 and 20 locations." };
  return { points, error: null };
}

function FitBounds({ items }: { items: Item[] }) {
  const map = useMap();
  useEffect(() => {
    if (items.length) map.fitBounds(items.map((i) => [i.lat, i.lon] as [number, number]), { padding: [40, 40], maxZoom: 12 });
  }, [items.length]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

const maxScore = (i: Item) => Math.max(-1, ...(i.scores ?? []).map((s) => s.score ?? -1));

export function Batch() {
  const [text, setText] = useState("");
  const [crop, setCrop] = useState<Crop>("wheat");
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  const sorted = useMemo(() => [...items].sort((a, b) =>
    (ORDER[b.overall_level ?? ""] ?? 0) - (ORDER[a.overall_level ?? ""] ?? 0) || maxScore(b) - maxScore(a)), [items]);

  const run = async () => {
    const { points, error } = parse(text);
    if (error) { setErr(error); return; }
    setErr(null); setItems([]); setBusy(true); setTotal(points.length);
    try {
      await postStream("/api/batch", { crop, points }, (name, data) => {
        if (name === "batch_item") setItems((xs) => [...xs, data]);
      });
    } catch (e: any) {
      setErr(e?.message ?? "Batch failed");
    } finally { setBusy(false); }
  };

  const exportCsv = () => {
    const head = ["label", "lat", "lon", "place", "district", "state", "overall_level", "drought", "excess_rain", "heat",
      "confidence", "satellite", "missing", "sources", "fetched_at"];
    const rows = sorted.map((i) => {
      const s = (h: string) => i.scores?.find((x) => x.hazard === h)?.score ?? "";
      return [i.label ?? "", i.lat, i.lon, i.place?.name ?? "", i.place?.district ?? "", i.place?.state ?? "",
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
      <section className="h-[45vh] min-h-[300px] md:h-auto md:w-3/5" aria-label="Batch map">
        <MapContainer center={[22.5, 79]} zoom={5} className="h-full w-full">
          <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            attribution="Imagery &copy; Esri, Maxar, Earthstar Geographics" />
          <FitBounds items={items} />
          {items.filter((i) => i.status === "ok").map((i) => (
            <CircleMarker key={i.index} center={[i.lat, i.lon]} radius={9}
              pathOptions={{ color: "#fff", weight: 2, fillColor: i.overall_level ? LEVEL_COLOR[i.overall_level] : "#9E9E9E", fillOpacity: 1 }}>
              <Popup>
                <div className="text-sm">
                  <div className="font-semibold">{i.label ? `${i.label} · ` : ""}{i.place?.name}</div>
                  <ul className="my-1">
                    {i.scores?.map((s) => <li key={s.hazard}>{HAZARD_LABEL[s.hazard]}: {s.score ?? "n/a"} {s.level ? `(${LEVEL_WORD[s.level]})` : ""}</li>)}
                  </ul>
                  <Link className="text-brand-700 underline" to={`/?lat=${i.lat}&lon=${i.lon}&crop=${crop}`}>Open full analysis</Link>
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </section>
      <section className="min-h-0 flex-1 space-y-3 overflow-y-auto border-l border-slate-200 bg-slate-50 p-3 md:w-2/5" aria-label="Batch input and results">
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <h2 className="text-sm font-semibold">Many farms at once (FPO / lender view)</h2>
          <label className="mt-2 block text-xs font-medium text-slate-700" htmlFor="kk-batch">One farm per line: latitude, longitude, optional label (max 20)</label>
          <textarea id="kk-batch" rows={6} className="mt-1 w-full rounded-md border border-slate-300 p-2 font-mono text-xs"
            placeholder={"19.10, 74.70, Member 1\n20.05, 74.05, Member 2"} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select className="min-h-[40px] rounded-md border border-slate-300 px-2 text-sm" value={crop} onChange={(e) => setCrop(e.target.value as Crop)} aria-label="Crop">
              <option value="wheat">Wheat</option><option value="mustard">Mustard</option><option value="gram">Gram (chickpea)</option><option value="unknown">Not sure</option>
            </select>
            <button type="button" onClick={run} disabled={busy} className="flex min-h-[40px] items-center gap-2 rounded-md bg-brand-700 px-4 text-sm font-medium text-white disabled:opacity-60">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {busy ? `Checking ${items.length}/${total}…` : "Check risk"}
            </button>
            <button type="button" onClick={exportCsv} disabled={!items.length} className="flex min-h-[40px] items-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm disabled:opacity-50">
              <Download className="h-4 w-4" /> CSV
            </button>
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
                {sorted.map((i) => {
                  const s = (h: string) => i.scores?.find((x) => x.hazard === h)?.score ?? "—";
                  return (
                    <tr key={i.index} className="border-t border-slate-100">
                      <td className="p-2">
                        <div className="font-medium">{i.label ?? `${i.lat.toFixed(3)}, ${i.lon.toFixed(3)}`}</div>
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
