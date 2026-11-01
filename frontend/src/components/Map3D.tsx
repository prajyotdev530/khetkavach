// Map3D: the tilted 3D view of the same analysis (MapLibre GL, loaded only when the user picks 3D). Esri imagery
// (or OSM streets) is draped over AWS Terrain Tiles. The 500 m box becomes a fence whose colour is the overall risk
// and whose height grows with the headline score; the evidence overlays and the before/now crossfade are draped on
// the ground. On a new farm the camera flies in, then slowly circles until the user touches the map.
import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Bounds } from "@/lib/api";
import type { RunState } from "@/lib/sse";
import { LEVEL_COLOR, RUNNING_GREY } from "@/lib/colors";
import { boxLabel, INDIA_CENTER, visibleOverlays, type CompareState, type LayerState } from "./MapView";

const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TERRAIN = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
const FARM_VIEW = { zoom: 15.2, pitch: 62, bearing: -25 };
const ORBIT_DEG_PER_MS = 360 / 120000; // one full circle every 2 minutes
const FENCE_M = 6; // wall thickness
const LAYER_ORDER = ["truecolor", "ndvi", "delta_ndvi", "radar"] as const;
const PERIODS = ["last_year", "now"] as const;
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function style(base: LayerState["base"]): StyleSpecification {
  return {
    version: 8,
    sources: {
      satellite: { type: "raster", tiles: [ESRI], tileSize: 256, maxzoom: 19,
        attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics" },
      street: { type: "raster", tiles: [OSM], tileSize: 256, maxzoom: 19, attribution: "&copy; OpenStreetMap contributors" },
      terrain: { type: "raster-dem", tiles: [TERRAIN], tileSize: 256, maxzoom: 15, encoding: "terrarium",
        attribution: "Elevation: Mapzen Terrain Tiles on AWS" },
      box: { type: "geojson", data: EMPTY },
      point: { type: "geojson", data: EMPTY },
    },
    layers: [
      { id: "satellite", type: "raster", source: "satellite", layout: { visibility: base === "satellite" ? "visible" : "none" } },
      { id: "street", type: "raster", source: "street", layout: { visibility: base === "street" ? "visible" : "none" } },
      {
        id: "fence", type: "fill-extrusion", source: "box",
        paint: {
          "fill-extrusion-color": RUNNING_GREY, "fill-extrusion-height": 0, "fill-extrusion-opacity": 0.6,
          "fill-extrusion-height-transition": { duration: 900, delay: 0 },
        },
      },
      {
        id: "point", type: "circle", source: "point",
        paint: { "circle-radius": 5, "circle-color": "#111", "circle-stroke-color": "#fff", "circle-stroke-width": 2 },
      },
    ],
    terrain: { source: "terrain", exaggeration: 1.5 },
    sky: { "sky-color": "#9CC9F0", "horizon-color": "#E8F1F8", "fog-color": "#E8F1F8", "sky-horizon-blend": 0.6,
      "horizon-fog-blend": 0.6, "fog-ground-blend": 0.3 },
  };
}

/** The box as a thin ring (outer edge FENCE_M outside the box) so the extrusion is a wall, not a solid block. */
function fence([[s, w], [n, e]]: Bounds): GeoJSON.FeatureCollection {
  const dLat = FENCE_M / 111320;
  const dLon = FENCE_M / (111320 * Math.cos((((s + n) / 2) * Math.PI) / 180));
  const ring = (s: number, w: number, n: number, e: number) => [[w, s], [e, s], [e, n], [w, n], [w, s]];
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: {}, geometry: {
      type: "Polygon", coordinates: [ring(s - dLat, w - dLon, n + dLat, e + dLon), ring(s, w, n, e).reverse()],
    } }],
  };
}

const corners = ([[s, w], [n, e]]: Bounds): [[number, number], [number, number], [number, number], [number, number]] =>
  [[w, n], [e, n], [e, s], [w, s]];

/** Fence colour and height: grey and low while running, then the risk colour, 30-180 m by headline score. */
function fenceLook(run: RunState): { color: string; height: number } {
  const level = run.risk?.overall_level;
  if (!level) return { color: RUNNING_GREY, height: 20 };
  return { color: LEVEL_COLOR[level], height: 30 + (run.risk?.headline?.score ?? 50) * 1.5 };
}

export function Map3D({
  run, layers, compare, onPick, onFail,
}: {
  run: RunState;
  layers: LayerState;
  compare: CompareState | null;
  onPick: (lat: number, lon: number) => void;
  onFail: (message: string) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const orbitRef = useRef(false);
  const flightRef = useRef(0);
  // The map instance whose style has loaded; `loaded` counts load events so the effects below re-run for a new map.
  const loadedRef = useRef<maplibregl.Map | null>(null);
  const [loaded, setLoaded] = useState(0);
  const readyMap = () => (mapRef.current && loadedRef.current === mapRef.current ? mapRef.current : null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  const failRef = useRef(onFail);
  failRef.current = onFail;

  const target = run.params ? ([run.params.lon, run.params.lat] as [number, number]) : null;
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

  // Create the map once; start at the farm if there is one.
  useEffect(() => {
    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container: el.current!,
        style: style(layers.base),
        center: target ?? [INDIA_CENTER[1], INDIA_CENTER[0]],
        zoom: target ? FARM_VIEW.zoom : 4.3,
        pitch: target ? FARM_VIEW.pitch : 45,
        bearing: target ? FARM_VIEW.bearing : 0,
        maxPitch: 75,
        attributionControl: { compact: true },
      });
    } catch {
      failRef.current("3D needs WebGL, which is turned off in this browser. Showing the flat map.");
      return;
    }
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    map.on("load", () => { loadedRef.current = map; setLoaded((n) => n + 1); });
    map.on("click", (e) => pickRef.current(e.lngLat.lat, e.lngLat.lng));
    // Any camera move the user makes (drag, wheel, buttons) stops the orbit for this farm.
    map.on("movestart", (e) => { if (e.originalEvent) orbitRef.current = false; });
    // When our own fly-in ends (not one a newer fly-in replaced), start circling.
    map.on("moveend", (e: maplibregl.MapLibreEvent & { kkFlight?: number }) => {
      if (e.kkFlight !== undefined && e.kkFlight === flightRef.current && orbitRef.current) orbit(map, e.kkFlight);
    });
    mapRef.current = map;
    return () => {
      orbitRef.current = false;
      map.remove();
      mapRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /** Turn the camera a little every frame until the user moves the map or a newer fly-in starts. */
  function orbit(map: maplibregl.Map, flight: number) {
    let last = 0;
    const step = (now: number) => {
      if (!orbitRef.current || flightRef.current !== flight || mapRef.current !== map) return;
      if (last) map.setBearing(map.getBearing() + (now - last) * ORBIT_DEG_PER_MS);
      last = now;
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // Base layer switch.
  useEffect(() => {
    const map = readyMap();
    if (!map) return;
    map.setLayoutProperty("satellite", "visibility", layers.base === "satellite" ? "visible" : "none");
    map.setLayoutProperty("street", "visibility", layers.base === "street" ? "visible" : "none");
  }, [loaded,layers.base]);

  // Evidence images: rebuild when the run's overlays change, in a fixed order under the fence.
  useEffect(() => {
    const map = readyMap();
    if (!map) return;
    for (const layer of LAYER_ORDER) {
      for (const period of PERIODS) {
        const id = `ov-${layer}-${period}`;
        if (map.getLayer(id)) map.removeLayer(id);
        if (map.getSource(id)) map.removeSource(id);
        const o = run.overlays.find((x) => x.layer === layer && x.period === period);
        if (!o) continue;
        map.addSource(id, { type: "image", url: `data:image/png;base64,${o.png_base64}`, coordinates: corners(o.bounds) });
        map.addLayer({
          id, type: "raster", source: id, layout: { visibility: "none" },
          paint: { "raster-resampling": "nearest", "raster-fade-duration": 0 },
        }, "fence");
      }
    }
  }, [loaded,run.overlays]);

  // Which evidence images show, and how strongly (same rules as the 2D map, including the before/now slider).
  useEffect(() => {
    const map = readyMap();
    if (!map) return;
    const shown = new Map(visibleOverlays(run.overlays, layers, compare).map(({ o, opacity }) => [`ov-${o.layer}-${o.period}`, opacity]));
    for (const layer of LAYER_ORDER) {
      for (const period of PERIODS) {
        const id = `ov-${layer}-${period}`;
        if (!map.getLayer(id)) continue;
        const opacity = shown.get(id);
        map.setLayoutProperty(id, "visibility", opacity ? "visible" : "none");
        if (opacity) map.setPaintProperty(id, "raster-opacity", opacity);
      }
    }
  }, [loaded,run.overlays, layers, compare]);

  // The risk fence: grey and low while running, then it rises in the risk colour.
  const look = fenceLook(run);
  const showBox = !!run.bounds && layers.risk && run.status !== "rejected";
  useEffect(() => {
    const map = readyMap();
    if (!map) return;
    (map.getSource("box") as GeoJSONSource).setData(showBox && run.bounds ? fence(run.bounds) : EMPTY);
    map.setPaintProperty("fence", "fill-extrusion-height-transition", { duration: reducedMotion ? 0 : 900, delay: 0 });
    map.setPaintProperty("fence", "fill-extrusion-color", look.color);
    map.setPaintProperty("fence", "fill-extrusion-height", showBox ? look.height : 0);
  }, [loaded,run.bounds, showBox, look.color, look.height, reducedMotion]);

  // The picked point.
  useEffect(() => {
    const map = readyMap();
    if (!map) return;
    const show = target && run.status !== "rejected";
    (map.getSource("point") as GeoJSONSource).setData(show ? {
      type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: target } }],
    } : EMPTY);
  }, [loaded,target?.[0], target?.[1], run.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Label above the north edge of the box, e.g. "High drought risk · 72".
  const label = boxLabel(run);
  useEffect(() => {
    const map = readyMap();
    markerRef.current?.remove();
    markerRef.current = null;
    if (!map || !label || !layers.risk || !run.bounds) return;
    const [[, w], [n, e]] = run.bounds;
    const anchor = document.createElement("div");
    anchor.style.width = "0";
    anchor.style.height = "0";
    const pill = document.createElement("div");
    pill.className = "kk-label";
    pill.style.background = label.bg;
    pill.textContent = label.text;
    anchor.appendChild(pill);
    markerRef.current = new maplibregl.Marker({ element: anchor, anchor: "center" }).setLngLat([(w + e) / 2, n]).addTo(map);
  }, [loaded,label?.text, label?.bg, layers.risk, run.bounds]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fly to each new farm, then circle it (skipped when the user prefers reduced motion).
  useEffect(() => {
    const map = readyMap();
    if (!map || !target) return;
    const flight = ++flightRef.current;
    orbitRef.current = !reducedMotion;
    if (reducedMotion) {
      map.jumpTo({ center: target, ...FARM_VIEW });
    } else {
      map.flyTo({ center: target, ...FARM_VIEW, speed: 1.4, essential: false }, { kkFlight: flight });
    }
    return () => { orbitRef.current = false; };
  }, [loaded,target?.[0], target?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={el} className="h-full w-full" aria-label="3D map: drag to move, right-drag or two fingers to tilt and turn" />;
}
