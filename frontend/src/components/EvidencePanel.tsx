// Evidence tab: a 16-day chart of daily rain (bars) and max temperature (line), each with its 20-year normal as
// a dashed line, then the satellite numbers (NDVI/NDMI now vs last year, scene date, cloud %), or radar values.
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RunState } from "@/lib/sse";
import { shortDate } from "@/lib/format";
import { SourceBadge } from "./SourceBadge";
import { Skeleton } from "./ui/skeleton";

function Row({ label, now, before, unit = "" }: { label: string; now: number | null | undefined; before?: number | null; unit?: string }) {
  return (
    <tr className="border-t border-slate-100">
      <th scope="row" className="py-1 pr-2 text-left font-normal text-slate-700">{label}</th>
      <td className="py-1 pr-2 text-right font-mono">{now ?? "—"}{now != null ? unit : ""}</td>
      <td className="py-1 text-right font-mono text-slate-600">{before ?? "—"}{before != null ? unit : ""}</td>
    </tr>
  );
}

export function EvidencePanel({ run }: { run: RunState }) {
  const { forecast, baseline, optical, radar } = run.evidence;
  if (!forecast && !optical && !radar) {
    if (run.status === "running") return <Skeleton className="h-56 w-full" />;
    return <p className="p-2 text-sm text-slate-600">Evidence appears here once the data is fetched.</p>;
  }
  const data = forecast?.dates.map((d, i) => ({
    day: shortDate(d),
    rain: forecast.rain_series[i],
    tmax: forecast.tmax_series[i],
    rainNormal: baseline?.rain_next16_normal_series[i],
    tmaxNormal: baseline?.tmax_next16_normal_c[i],
  }));
  return (
    <div className="space-y-4">
      {forecast && data ? (
        <section aria-label="16-day forecast chart">
          <h3 className="mb-1 text-sm font-semibold text-slate-900">Next 16 days: rain and max temperature</h3>
          <div className="h-56 w-full">
            <ResponsiveContainer>
              <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                <CartesianGrid stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 10 }} interval={2} />
                <YAxis yAxisId="rain" tick={{ fontSize: 10 }} width={40} allowDecimals={false} />
                <YAxis yAxisId="t" orientation="right" tick={{ fontSize: 10 }} unit="°" domain={[(m: number) => Math.floor(m - 2), (m: number) => Math.ceil(m + 2)]} width={36} />
                <Tooltip contentStyle={{ fontSize: 12 }} isAnimationActive={false} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar yAxisId="rain" dataKey="rain" name="Rain (mm)" fill="#1E88E5" isAnimationActive={false} />
                {baseline && <Line yAxisId="rain" dataKey="rainNormal" name="Normal rain" stroke="#1565C0" strokeDasharray="4 3" dot={false} isAnimationActive={false} />}
                <Line yAxisId="t" dataKey="tmax" name="Max temp (°C)" stroke="#E65100" strokeWidth={2} dot={false} isAnimationActive={false} />
                {baseline && <Line yAxisId="t" dataKey="tmaxNormal" name="Normal max temp" stroke="#E65100" strokeDasharray="4 3" dot={false} isAnimationActive={false} />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            <SourceBadge source={forecast.source} />
            {baseline && <SourceBadge source={baseline.source} />}
          </div>
          {baseline && (
            <p className="mt-1 text-[11px] text-slate-500">
              Dashed lines: {baseline.years_used}-year normal ({baseline.first_year}–{baseline.last_year}) for the same dates,
              from {baseline.provider === "era5" ? "ERA5" : "NASA POWER"}.
            </p>
          )}
        </section>
      ) : (
        <p className="rounded-md bg-amber-50 p-2 text-sm text-amber-900">Forecast unavailable right now.</p>
      )}

      {optical && (
        <section aria-label="Satellite crop health">
          <h3 className="mb-1 text-sm font-semibold text-slate-900">Crop health from Sentinel-2</h3>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500">
                <th className="text-left font-normal" />
                <th className="text-right font-normal">Now ({shortDate(optical.scene_date)})</th>
                <th className="text-right font-normal">Last year ({shortDate(optical.last_year_scene_date)})</th>
              </tr>
            </thead>
            <tbody>
              <Row label="Greenness (NDVI)" now={optical.ndvi.median} before={optical.ndvi_last_year} />
              <Row label="Crop moisture (NDMI)" now={optical.ndmi.median} before={optical.ndmi_last_year} />
            </tbody>
          </table>
          <p className="mt-1 text-[11px] text-slate-600">
            Scene cloud {optical.scene_cloud_pct}% · farm box {Math.round(optical.clear_fraction * 100)}% clear ·
            values are medians over clear 10 m pixels.
          </p>
          {optical.land_note && <p className="mt-1 rounded bg-amber-50 p-1.5 text-xs text-amber-900">{optical.land_note}</p>}
          <div className="mt-1"><SourceBadge source={optical.source} /></div>
        </section>
      )}

      {radar && (
        <section aria-label="Radar crop evidence">
          <h3 className="mb-1 text-sm font-semibold text-slate-900">Radar (Sentinel-1) — sees through cloud</h3>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500">
                <th className="text-left font-normal" />
                <th className="text-right font-normal">Now ({shortDate(radar.scene_date)})</th>
                <th className="text-right font-normal">Last year ({shortDate(radar.last_year_scene_date)})</th>
              </tr>
            </thead>
            <tbody>
              <Row label="VH backscatter" now={radar.vh_db} before={radar.vh_db_last_year} unit=" dB" />
            </tbody>
          </table>
          {radar.delta_vh_db != null && (
            <p className="mt-1 text-[11px] text-slate-600">
              Change {radar.delta_vh_db} dB: {radar.delta_vh_db < 0 ? "lower than last year suggests less crop biomass" : "higher than last year suggests more crop biomass"}.
            </p>
          )}
          <div className="mt-1"><SourceBadge source={radar.source} /></div>
        </section>
      )}
    </div>
  );
}
