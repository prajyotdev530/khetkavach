// RiskCard (F6): confidence badge and "Data as of", then three horizontal score bars (Drought, Excess rain,
// Heat), each with its 0-100 score, the level as a word in its colour, and its top 2 drivers with source chips.
import type { RiskScore } from "@/lib/api";
import type { RunState } from "@/lib/sse";
import { HAZARD_LABEL, LEVEL_BG, LEVEL_COLOR, LEVEL_TEXT, LEVEL_WORD } from "@/lib/colors";
import { ago, clock } from "@/lib/format";
import { CitationChip } from "./SourceBadge";
import { Skeleton } from "./ui/skeleton";

const CONF_STYLE = {
  high: "bg-green-100 text-green-900 border-green-300",
  medium: "bg-amber-100 text-amber-900 border-amber-300",
  low: "bg-red-100 text-red-900 border-red-300",
};

function ScoreBar({ s }: { s: RiskScore }) {
  const level = s.level;
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">{HAZARD_LABEL[s.hazard]}</h3>
        {level && s.score !== null ? (
          <span className="flex items-baseline gap-2">
            <span className="rounded px-1.5 py-0.5 text-xs font-semibold" style={{ color: LEVEL_TEXT[level], background: LEVEL_BG[level] }}>
              {LEVEL_WORD[level]}
            </span>
            <span className="font-mono text-lg font-bold text-slate-900">{s.score}</span>
          </span>
        ) : (
          <span className="text-xs font-medium text-slate-600">Not enough data</span>
        )}
      </div>
      <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100" role="meter" aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={s.score ?? undefined} aria-label={`${HAZARD_LABEL[s.hazard]} risk`}>
        {level && s.score !== null && (
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(2, s.score)}%`, background: LEVEL_COLOR[level] }} />
        )}
      </div>
      {s.drivers.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {s.drivers.map((d, i) => (
            <li key={i} className="text-xs text-slate-700">
              <span>{d.text}.</span>{" "}
              <span className="inline-flex flex-wrap gap-1 align-middle">
                {d.citations.map((c, j) => <CitationChip key={j} c={c} />)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {s.status === "not_enough_data" && (
        <p className="mt-2 text-xs text-slate-600">Less than half of this score's evidence is available right now.</p>
      )}
    </div>
  );
}

export function RiskCard({ run }: { run: RunState }) {
  if (!run.risk) {
    if (run.status !== "running") return <p className="p-2 text-sm text-slate-600">Risk scores appear when the evidence is in.</p>;
    return (
      <div className="space-y-2">
        <Skeleton className="h-6 w-40" />
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-24 w-full" />)}
      </div>
    );
  }
  const newest = run.sources.map((s) => s.fetched_at).sort().slice(-1)[0];
  const { confidence, confidence_reasons } = run.risk;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={`rounded-full border px-2 py-0.5 font-semibold ${CONF_STYLE[confidence]}`}>
          Confidence: {confidence[0].toUpperCase() + confidence.slice(1)}
        </span>
        {newest && <span className="text-slate-600" title={clock(newest)}>Data as of {clock(newest)} ({ago(newest)})</span>}
      </div>
      {confidence_reasons.length > 0 && <p className="text-xs text-slate-600">Lower confidence: {confidence_reasons.join("; ")}.</p>}
      {run.risk.scores.map((s) => <ScoreBar key={s.hazard} s={s} />)}
      <p className="text-[11px] text-slate-500">
        Scores are computed in code from the cited data with documented thresholds (risk.yaml), never by the AI.
      </p>
    </div>
  );
}
