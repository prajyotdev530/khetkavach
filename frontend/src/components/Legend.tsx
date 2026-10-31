// Legend (bottom-left of the map): the colour ramp of the active evidence layer with words, the three risk
// colours with their words, the scene date and how much of the box was hidden (e.g. "18% hidden by cloud").
import type { RunState } from "@/lib/sse";
import { CHANGE_RAMP, LEVEL_COLOR, LEVEL_WORD, NDVI_RAMP } from "@/lib/colors";
import { shortDate } from "@/lib/format";
import type { CompareState, LayerState } from "./MapView";

export function Legend({ run, layers, compare }: { run: RunState; layers: LayerState; compare: CompareState | null }) {
  const ov = run.overlays;
  const radar = ov.find((o) => o.layer === "radar");
  const active =
    compare?.layer ??
    (layers.radar && radar ? "radar" : layers.delta_ndvi && ov.some((o) => o.layer === "delta_ndvi") ? "delta_ndvi"
      : layers.ndvi && ov.some((o) => o.layer === "ndvi") ? "ndvi"
        : layers.truecolor && ov.some((o) => o.layer === "truecolor") ? "truecolor" : null);
  const o = active ? ov.find((x) => x.layer === active && x.period === "now") : undefined;
  const title: Record<string, string> = {
    delta_ndvi: "Change vs last year (NDVI)", ndvi: "Green cover now (NDVI)", truecolor: "True colour (Sentinel-2)",
    radar: "Radar change vs last year (VH)",
  };
  const ramp = active === "ndvi" ? NDVI_RAMP : active === "delta_ndvi" || active === "radar" ? CHANGE_RAMP : null;

  return (
    <div className="absolute bottom-3 left-3 z-[1000] max-w-[15rem] rounded-lg border border-slate-300 bg-white/95 p-2 text-[11px] leading-tight text-slate-800 shadow-md">
      {o && active && (
        <div className="mb-2">
          <div className="mb-1 font-semibold">{title[active]}</div>
          {ramp && (
            <ul className="space-y-0.5">
              {ramp.map((r) => (
                <li key={r.color} className="flex items-center gap-1.5">
                  <span className="inline-block h-3 w-4 rounded-sm border border-slate-300" style={{ background: r.color }} />
                  {active === "radar" ? r.label.replace("green", "biomass") : r.label}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-1 text-slate-600">
            Scene {shortDate(o.scene_date, true)} · {o.masked_pct}% hidden{active === "radar" ? " (no data)" : " by cloud/water"}
          </div>
          {active === "radar" && <div className="text-amber-800">Radar used: optical images were cloudy</div>}
        </div>
      )}
      <div className="font-semibold">Farm risk (next 16 days)</div>
      <ul className="mt-0.5 flex gap-2">
        {(["low", "moderate", "high"] as const).map((l) => (
          <li key={l} className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-sm" style={{ background: LEVEL_COLOR[l] }} />
            {LEVEL_WORD[l]}
          </li>
        ))}
      </ul>
    </div>
  );
}
