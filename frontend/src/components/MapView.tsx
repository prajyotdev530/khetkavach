// MapView (F1, F12): Leaflet map with satellite/street base layers, click-to-pick, the 500 m analysis box that
// pulses grey while the agent runs and then takes its risk colour, the crop-health overlays from Sentinel-2/1,
// a layer control (top-right) and the legend (bottom-left). BUILD_SPEC §4.
import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import {
  CircleMarker, ImageOverlay, MapContainer, Marker, Pane, Rectangle, TileLayer, ZoomControl, useMap, useMapEvents,
} from "react-leaflet";
import type { Overlay } from "@/lib/api";
import type { RunState } from "@/lib/sse";
import { HAZARD_LABEL, LEVEL_COLOR, LEVEL_FILL_OPACITY, LEVEL_WORD, RUNNING_GREY } from "@/lib/colors";
import { Legend } from "./Legend";
import { SearchBox } from "./SearchBox";

export type EvidenceLayer = "delta_ndvi" | "ndvi" | "truecolor" | "radar";
export interface LayerState {
  base: "satellite" | "street";
  risk: boolean;
  delta_ndvi: boolean;
  ndvi: boolean;
  truecolor: boolean;
  radar: boolean;
}
export interface CompareState {
  layer: "truecolor" | "ndvi";
  t: number; // 0 = last year, 100 = now
}

const INDIA_CENTER: [number, number] = [22.5, 79.0];
const OVERLAY_OPACITY = 0.7;

function ClickHandler({ onPick }: { onPick: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

/** Fly to a newly picked farm at zoom 16 over 1.2 s. */
function FlyTo({ target }: { target: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo(target, 16, { duration: 1.2 });
  }, [map, target?.[0], target?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** Find one overlay by layer and period. */
function find(overlays: Overlay[], layer: string, period: "now" | "last_year") {
  return overlays.find((o) => o.layer === layer && o.period === period);
}

function EvidenceImage({ o, opacity }: { o: Overlay; opacity: number }) {
  return (
    <ImageOverlay
      url={`data:image/png;base64,${o.png_base64}`}
      bounds={o.bounds}
      opacity={opacity}
      className="kk-pixelated"
      pane="evidence"
    />
  );
}

/** The analysis box: grey dashed pulse while running, then the overall risk colour. */
function RiskBox({ run, visible }: { run: RunState; visible: boolean }) {
  const ref = useRef<L.Rectangle | null>(null);
  const level = run.risk?.overall_level ?? null;
  const running = run.status === "running" && !level;
  const color = level ? LEVEL_COLOR[level] : RUNNING_GREY;

  useEffect(() => {
    const el = ref.current?.getElement();
    if (!el) return;
    el.classList.toggle("kk-running", running);
    el.classList.toggle("kk-high", level === "high");
  }, [running, level]);

  if (!run.bounds || !visible || run.status === "rejected") return null;
  return (
    <Rectangle
      ref={ref}
      bounds={run.bounds}
      interactive={false}
      pathOptions={{
        color, weight: 3, dashArray: running ? "8 6" : undefined, fillColor: color,
        fillOpacity: level ? LEVEL_FILL_OPACITY[level] : 0.05, className: "kk-box",
      }}
    />
  );
}

/** Label pinned above the box, e.g. "High drought risk · 72". */
function BoxLabel({ run }: { run: RunState }) {
  const icon = useMemo(() => {
    if (!run.bounds || run.status === "rejected") return null;
    const h = run.risk?.headline;
    const level = run.risk?.overall_level;
    let text = "Analysing…";
    let bg = "#424242";
    if (h && level) {
      text = `${LEVEL_WORD[h.level]} ${HAZARD_LABEL[h.hazard as keyof typeof HAZARD_LABEL].toLowerCase()} risk · ${h.score}`;
      bg = h.level === "moderate" ? "#6D4C00" : LEVEL_COLOR[h.level];
    } else if (run.status === "error") {
      text = "Analysis stopped";
    } else if (run.status === "done") {
      text = "Not enough data";
    }
    return L.divIcon({
      className: "kk-label-icon",
      html: `<div class="kk-label" style="background:${bg}">${text}</div>`,
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    });
  }, [run.bounds, run.risk, run.status]);
  if (!icon || !run.bounds) return null;
  const [[, west], [north, east]] = run.bounds;
  return <Marker position={[north, (west + east) / 2]} icon={icon} interactive={false} keyboard={false} />;
}

export function MapView({
  run, layers, compare, onPick, setLayers,
}: {
  run: RunState;
  layers: LayerState;
  compare: CompareState | null;
  onPick: (lat: number, lon: number) => void;
  setLayers: (fn: (l: LayerState) => LayerState) => void;
}) {
  const target = run.params ? ([run.params.lat, run.params.lon] as [number, number]) : null;
  const ov = run.overlays;
  const hasRadar = !!find(ov, "radar", "now");
  const hasOptical = !!find(ov, "ndvi", "now");

  return (
    <div className="relative h-full w-full">
      <MapContainer center={INDIA_CENTER} zoom={5} zoomControl={false} className="h-full w-full" worldCopyJump>
        {layers.base === "satellite" ? (
          <TileLayer
            key="esri"
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            attribution="Imagery &copy; Esri, Maxar, Earthstar Geographics"
            maxZoom={19}
          />
        ) : (
          <TileLayer
            key="osm"
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap contributors"
            maxZoom={19}
          />
        )}
        <ZoomControl position="bottomright" />
        <ClickHandler onPick={onPick} />
        <FlyTo target={target} />
        <Pane name="evidence" style={{ zIndex: 350 }}>
          {layers.truecolor && find(ov, "truecolor", "now") && compare?.layer !== "truecolor" && (
            <EvidenceImage o={find(ov, "truecolor", "now")!} opacity={OVERLAY_OPACITY} />
          )}
          {layers.ndvi && find(ov, "ndvi", "now") && compare?.layer !== "ndvi" && (
            <EvidenceImage o={find(ov, "ndvi", "now")!} opacity={OVERLAY_OPACITY} />
          )}
          {layers.delta_ndvi && !compare && find(ov, "delta_ndvi", "now") && (
            <EvidenceImage o={find(ov, "delta_ndvi", "now")!} opacity={OVERLAY_OPACITY} />
          )}
          {layers.radar && hasRadar && !compare && <EvidenceImage o={find(ov, "radar", "now")!} opacity={OVERLAY_OPACITY} />}
          {compare && find(ov, compare.layer, "last_year") && (
            <EvidenceImage o={find(ov, compare.layer, "last_year")!} opacity={OVERLAY_OPACITY * (1 - compare.t / 100)} />
          )}
          {compare && find(ov, compare.layer, "now") && (
            <EvidenceImage o={find(ov, compare.layer, "now")!} opacity={OVERLAY_OPACITY * (compare.t / 100)} />
          )}
        </Pane>
        <RiskBox key={run.runId ?? `${target?.[0]},${target?.[1]}`} run={run} visible={layers.risk} />
        {target && run.status !== "rejected" && (
          <CircleMarker center={target} radius={4} pathOptions={{ color: "#fff", weight: 2, fillColor: "#111", fillOpacity: 1 }} interactive={false} />
        )}
        {layers.risk && <BoxLabel run={run} />}
      </MapContainer>

      <SearchBox onPick={(hit) => onPick(hit.lat, hit.lon)} />
      <LayerControl layers={layers} setLayers={setLayers} hasRadar={hasRadar} hasOptical={hasOptical} />
      <Legend run={run} layers={layers} compare={compare} />
    </div>
  );
}

function LayerControl({
  layers, setLayers, hasRadar, hasOptical,
}: {
  layers: LayerState;
  setLayers: (fn: (l: LayerState) => LayerState) => void;
  hasRadar: boolean;
  hasOptical: boolean;
}) {
  const box = (key: keyof Omit<LayerState, "base">, label: string, enabled = true) => (
    <label className={`flex min-h-[32px] cursor-pointer items-center gap-2 ${enabled ? "" : "opacity-50"}`}>
      <input
        type="checkbox"
        className="h-4 w-4 accent-brand-700"
        checked={layers[key] as boolean}
        disabled={!enabled}
        onChange={(e) => setLayers((l) => ({ ...l, [key]: e.target.checked }))}
      />
      {label}
    </label>
  );
  return (
    <div className="absolute right-3 top-3 z-[1000] rounded-lg border border-slate-300 bg-white/95 p-2 text-xs shadow-md" onClick={(e) => e.stopPropagation()}>
      <div className="mb-1 flex overflow-hidden rounded-md border border-slate-300" role="radiogroup" aria-label="Base map">
        {(["satellite", "street"] as const).map((b) => (
          <button
            key={b}
            type="button"
            role="radio"
            aria-checked={layers.base === b}
            className={`min-h-[32px] flex-1 px-2 font-medium ${layers.base === b ? "bg-brand-700 text-white" : "bg-white text-slate-700"}`}
            onClick={() => setLayers((l) => ({ ...l, base: b }))}
          >
            {b === "satellite" ? "Satellite" : "Street"}
          </button>
        ))}
      </div>
      <div className="hidden sm:block">
        {box("risk", "Risk outline")}
        {box("delta_ndvi", "Change vs last year", hasOptical)}
        {box("ndvi", "Green cover now", hasOptical)}
        {box("truecolor", "True colour", hasOptical)}
        {hasRadar && box("radar", "Radar change")}
      </div>
    </div>
  );
}
