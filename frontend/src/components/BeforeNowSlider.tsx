// BeforeNowSlider (F12): a 0-100 range under the map that crossfades the same layer for last year and now.
// The labels show the real scene dates; a toggle switches between True colour and Green cover.
import type { Overlay } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { CompareState } from "./MapView";

export function BeforeNowSlider({
  overlays, compare, setCompare,
}: {
  overlays: Overlay[];
  compare: CompareState | null;
  setCompare: (c: CompareState | null) => void;
}) {
  const layer = compare?.layer ?? "truecolor";
  const before = overlays.find((o) => o.layer === layer && o.period === "last_year");
  const now = overlays.find((o) => o.layer === layer && o.period === "now");
  if (!overlays.some((o) => o.period === "last_year")) return null;
  const t = compare?.t ?? 100;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-200 bg-white px-3 py-2 text-xs">
      <div className="flex overflow-hidden rounded-md border border-slate-300" role="radiogroup" aria-label="Layer to compare">
        {(["truecolor", "ndvi"] as const).map((l) => (
          <button
            key={l}
            type="button"
            role="radio"
            aria-checked={compare?.layer === l}
            className={`min-h-[36px] px-2 font-medium ${compare?.layer === l ? "bg-brand-700 text-white" : "bg-white text-slate-700"}`}
            onClick={() => setCompare({ layer: l, t })}
          >
            {l === "truecolor" ? "True colour" : "Green cover"}
          </button>
        ))}
      </div>
      <span className="w-20 text-right font-medium text-slate-700">{before ? shortDate(before.scene_date, true) : "Last year"}</span>
      <input
        type="range"
        min={0}
        max={100}
        value={t}
        aria-label="Compare last year (left) with now (right)"
        className="min-w-[8rem] flex-1 accent-brand-700"
        onChange={(e) => setCompare({ layer, t: Number(e.target.value) })}
      />
      <span className="w-20 font-medium text-slate-700">{now ? shortDate(now.scene_date, true) : "Now"}</span>
      {compare ? (
        <button type="button" className="min-h-[36px] text-slate-600 underline" onClick={() => setCompare(null)}>Stop comparing</button>
      ) : (
        <span className="text-slate-500">Drag to compare with last year</span>
      )}
    </div>
  );
}
