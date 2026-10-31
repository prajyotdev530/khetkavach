// SourceBadge: a small pill like "Sentinel-2 · 30 Oct" or "Open-Meteo · 3 min ago (cached)" linking to the
// provider. CitationChip: the same pill for one cited number, with a tooltip showing source, value and fetch time.
import type { Citation, SourceRef } from "@/lib/api";
import { ago, clock, shortDate, showValue } from "@/lib/format";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** Short provider name for chips. */
export function shortSource(name: string): string {
  if (name.startsWith("Sentinel-2")) return "Sentinel-2";
  if (name.startsWith("Sentinel-1")) return name.includes("GRD") ? "Sentinel-1 GRD" : "Sentinel-1";
  if (name.startsWith("Open-Meteo")) return "Open-Meteo";
  if (name.startsWith("ERA5")) return "ERA5";
  if (name.startsWith("NASA")) return "NASA POWER";
  if (name.includes("Nominatim")) return "OpenStreetMap";
  if (name.includes("risk engine")) return "Risk engine";
  return name;
}

export function SourceBadge({ source }: { source: SourceRef }) {
  const when = source.scene_date ? shortDate(source.scene_date) : `fetched ${ago(source.fetched_at)}`;
  const text = `${shortSource(source.name)} · ${when}${source.cached ? " (cached)" : ""}`;
  const cls = "inline-flex items-center rounded-full border border-slate-300 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-700";
  return source.url ? (
    <a href={source.url} target="_blank" rel="noreferrer" className={`${cls} hover:bg-slate-100`} title={`${source.name}, fetched ${clock(source.fetched_at)}`}>
      {text}
    </a>
  ) : (
    <span className={cls} title={`${source.name}, computed ${clock(source.fetched_at)}`}>{text}</span>
  );
}

export function CitationChip({ c }: { c: Citation }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="inline-flex items-center rounded-full border border-brand-100 bg-brand-50 px-2 py-0.5 text-[11px] font-medium text-brand-900 hover:bg-brand-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600">
          {shortSource(c.source)} · {c.call_id}
        </button>
      </TooltipTrigger>
      <TooltipContent>
        <div className="font-semibold">{c.source}</div>
        <div>{c.field.replace(/_/g, " ")}: <span className="font-mono">{showValue(c.value, c.unit)}</span></div>
        <div className="text-slate-300">fetched {clock(c.fetched_at)} ({ago(c.fetched_at)})</div>
      </TooltipContent>
    </Tooltip>
  );
}
